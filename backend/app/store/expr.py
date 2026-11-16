"""Filter / order expressions with the SQLAlchemy operators the application uses, compiled to Mongo filters.

`Model.col == 5`, `Model.col.in_([..])`, `Model.col.is_(None)`, `Model.col.like('x%')`, `and_(..)`, `or_(..)`, `a & b`, `a | b`, `col.desc()`, `col.nulls_last()`,
`func.lower(col) == 'x'`. No negation (`~` / `not_`): the application never uses it and three-valued logic is not worth faking for nothing.

NULL semantics are SQL's, not Mongo's:
  col != v        excludes rows where col is NULL      -> {col: {$nin: [v, null]}}
  col IN (..)     never matches NULL                   -> None is dropped from the list
  col == None     is `IS NULL`                         -> {col: null} (null and missing)
and `evaluate()` runs the same expressions in Python with real three-valued logic (True / False / None=unknown) - used for ordering by an expression and to
check, in the tests, that what Mongo matches is what SQL would.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import DataError, NotSupported
from .types import String


class Expr:
    """A boolean / value expression node."""

    def __and__(self, other):
        return And([self, other])

    def __or__(self, other):
        return Or([self, other])

    def __invert__(self):
        raise NotSupported("negation (~ / not_) is not supported by the store")

    def desc(self):
        return OrderBy(self, True)

    def asc(self):
        return OrderBy(self, False)

    def nulls_last(self):
        return OrderBy(self, False, "last")

    def nulls_first(self):
        return OrderBy(self, False, "first")

    __hash__ = object.__hash__


class ColumnOps:
    """The operators of a mapped column; mixed into `model.Column`. A column needs: name, field, type (SqlType), nullable."""

    def __eq__(self, o):                                        # type: ignore[override]
        if o is None:
            return Is(self, None, False)
        return Cmp(self, "==", o)

    def __ne__(self, o):                                        # type: ignore[override]
        if o is None:
            return Is(self, None, True)
        return Cmp(self, "!=", o)

    def __lt__(self, o):
        return Cmp(self, "<", o)

    def __le__(self, o):
        return Cmp(self, "<=", o)

    def __gt__(self, o):
        return Cmp(self, ">", o)

    def __ge__(self, o):
        return Cmp(self, ">=", o)

    def in_(self, values):
        return InList(self, values if hasattr(values, "entities") else list(values))       # a select(...) stays one: the Session resolves it

    def notin_(self, values):
        return NotInList(self, list(values))

    not_in = notin_

    def is_(self, v):
        return Is(self, v, False)

    def is_not(self, v):
        return Is(self, v, True)

    isnot = is_not

    def like(self, pattern):
        return Like(self, pattern)

    def asc(self):
        return OrderBy(self, False)

    def desc(self):
        return OrderBy(self, True)

    def nulls_last(self):
        return OrderBy(self, False, "last")

    def nulls_first(self):
        return OrderBy(self, False, "first")

    def __add__(self, n):
        return Arith(self, "+", n)

    def __sub__(self, n):
        return Arith(self, "-", n)

    def label(self, name):
        raise NotSupported("label() is not supported by the store")

    def __getitem__(self, key):
        """`Model.json_col["key"]` (then `.astext`): a field inside the embedded document - the Mongo path "json_col.key"."""
        if not getattr(self.type, "json", False) or isinstance(self, JsonPath):
            raise NotSupported("indexing works on a JSON column, one level deep")
        return JsonPath(self, key)

    __hash__ = object.__hash__


class JsonPath(ColumnOps):
    """One key of a JSON column, as text. Compares like a string column; a missing key is NULL (never matches)."""

    def __init__(self, col, key):
        self.base, self.key = col, str(key)
        self.name = f"{col.name}[{self.key}]"
        self.field = f"{col.field}.{self.key}"
        self.type = String()
        self.nullable = True
        self.model = col.model

    @property
    def astext(self):
        return self


class Arith(Expr):
    """`Column + n` / `Column - n` - only meaningful on the right of an UPDATE / upsert (-> $inc)."""

    def __init__(self, col, op, n):
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            raise NotSupported("arithmetic on a column is limited to a numeric literal")
        self.col, self.op, self.n = col, op, n


class FuncCall(Expr):
    def __init__(self, name: str, args: list):
        self.name, self.args = name, list(args)

    def filter(self, *a, **k):
        raise NotSupported("aggregate FILTER is not supported by the store")

    def label(self, *a, **k):
        raise NotSupported("label() is not supported by the store")

    # lower(col) == 'x'  and  coalesce(col_a, col_b, ...) <op> value
    def _cmp(self, op, o):
        if o is None:
            raise NotSupported(f"comparing func.{self.name}(...) with None is not supported")
        if self.name == "lower" and len(self.args) == 1 and op == "==":
            return Cmp(self, "==", o)
        if self.name == "coalesce" and self.args and all(isinstance(a, ColumnOps) for a in self.args):
            return Cmp(self, op, o)
        raise NotSupported(f"comparing func.{self.name}(...) is not supported")

    def __eq__(self, o):                                        # type: ignore[override]
        return self._cmp("==", o)

    def __ne__(self, o):                                        # type: ignore[override]
        return self._cmp("!=", o)

    def __lt__(self, o):
        return self._cmp("<", o)

    def __le__(self, o):
        return self._cmp("<=", o)

    def __gt__(self, o):
        return self._cmp(">", o)

    def __ge__(self, o):
        return self._cmp(">=", o)

    __hash__ = object.__hash__

    @property
    def is_aggregate(self):
        return self.name in ("count", "sum", "min", "max", "avg")


class _Func:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def make(*args):
            return FuncCall(name, args)
        return make


func = _Func()


class Cmp(Expr):
    def __init__(self, left, op, value):
        if isinstance(value, (ColumnOps, Expr)):
            raise NotSupported("comparing two columns / expressions is not supported by the store")
        self.left, self.op = left, op
        if isinstance(left, FuncCall):
            if left.name == "coalesce" and all(getattr(a.type, "name", "") in ("int", "smallint", "float") for a in left.args):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise DataError(f"expected a number to compare with {left.name}(...), got {type(value).__name__}")
                self.value = value                                              # int and float columns coalesce to a number: keep it as given (1.5 stays 1.5)
            else:
                self.value = left.args[0].type.to_bind(value) if left.name == "coalesce" else value
        else:
            self.value = left.type.to_bind(value)


class InList(Expr):
    def __init__(self, col, values):
        self.col = col
        self.sub = None
        if hasattr(values, "entities") and hasattr(values, "_where"):             # `col.in_(select(...))`: the Session runs the inner select first (Session._resolve)
            self.sub, self.values = values, None
            return
        self.values = [col.type.to_bind(v) for v in values if v is not None]      # SQL: x IN (1, NULL) is true only for 1


class NotInList(Expr):
    """`col NOT IN (...)`: never true for a NULL column, and never true at all when the list holds a NULL (SQL's three-valued logic)."""

    def __init__(self, col, values):
        self.col = col
        self.has_null = any(v is None for v in values)
        self.values = [col.type.to_bind(v) for v in values if v is not None]


class Is(Expr):
    def __init__(self, col, value, negate):
        if value not in (None, True, False):
            raise NotSupported("IS only supports NULL / TRUE / FALSE")
        self.col, self.value, self.negate = col, value, negate


class Like(Expr):
    def __init__(self, col, pattern):
        self.col, self.pattern = col, pattern


class And(Expr):
    def __init__(self, parts):
        self.parts = []
        for p in parts:
            self.parts.extend(p.parts if isinstance(p, And) else [p])


class Or(Expr):
    def __init__(self, parts):
        self.parts = []
        for p in parts:
            self.parts.extend(p.parts if isinstance(p, Or) else [p])


class OrderBy:
    def __init__(self, expr, desc, nulls=None):
        self.expr, self.is_desc, self.nulls = expr, desc, nulls

    def nulls_last(self):
        return OrderBy(self.expr, self.is_desc, "last")

    def nulls_first(self):
        return OrderBy(self.expr, self.is_desc, "first")


def and_(*conds):
    conds = [c for c in conds if c is not None]
    if not conds:
        return And([])
    return conds[0] if len(conds) == 1 else And(conds)


def or_(*conds):
    conds = [c for c in conds if c is not None]
    if not conds:
        raise NotSupported("or_() of nothing")
    return conds[0] if len(conds) == 1 else Or(conds)


def desc(x):
    return x if isinstance(x, OrderBy) and x.is_desc else OrderBy(x.expr if isinstance(x, OrderBy) else x, True)


def asc(x):
    return OrderBy(x.expr if isinstance(x, OrderBy) else x, False)


def text(sql):
    raise NotSupported("raw SQL text() is not supported by the store (it is DDL / Postgres-only; port the call site)")


def exists(*a, **k):
    raise NotSupported("exists() is not supported by the store (port the call site)")


# ---------------------------------------------------------------- compile to a Mongo filter

def like_to_regex(pattern: str) -> str:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if c == "%" else "." if c == "_" else re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def to_filter(node) -> dict:
    """The Mongo filter for a boolean expression; `{}` for an empty AND."""
    if node is None:
        return {}
    if isinstance(node, And):
        parts = [to_filter(p) for p in node.parts]
        parts = [p for p in parts if p]
        return {} if not parts else parts[0] if len(parts) == 1 else {"$and": parts}
    if isinstance(node, Or):
        return {"$or": [to_filter(p) for p in node.parts]}
    if isinstance(node, Cmp):
        if isinstance(node.left, FuncCall) and node.left.name == "coalesce":   # coalesce(a, b, ...) <op> v - NULL (every column null) never compares true
            coal = {"$ifNull": ["$" + a.field for a in node.left.args] + [None]}
            opn = {"==": "$eq", "!=": "$ne", "<": "$lt", "<=": "$lte", ">": "$gt", ">=": "$gte"}[node.op]
            return {"$expr": {"$and": [{"$ne": [coal, None]}, {opn: [coal, node.value]}]}}
        if isinstance(node.left, FuncCall):                                   # lower(col) == v
            col = node.left.args[0]
            return {"$and": [{col.field: {"$ne": None}}, {"$expr": {"$eq": [{"$toLower": "$" + col.field}, node.value]}}]}
        f, v = node.left.field, node.value
        if v is None:
            raise NotSupported("compare with None via is_(None) / == None")
        return {"==": {f: v}, "!=": {f: {"$nin": [v, None]}}, "<": {f: {"$lt": v}}, "<=": {f: {"$lte": v}}, ">": {f: {"$gt": v}}, ">=": {f: {"$gte": v}}}[node.op]
    if isinstance(node, InList):
        if node.sub is not None:
            raise NotSupported("an IN (subquery) must be resolved by the Session before it is compiled")
        return {node.col.field: {"$in": node.values}}
    if isinstance(node, NotInList):
        if node.has_null:
            return {"_id": {"$in": []}}                                          # x NOT IN (..., NULL) is never true
        return {node.col.field: {"$nin": node.values + [None]}}                  # excludes the listed values AND null / missing
    if isinstance(node, Is):
        f = node.col.field
        if node.value is None:
            return {f: {"$ne": None}} if node.negate else {f: None}
        return {f: {"$ne": node.value}} if node.negate else {f: node.value}
    if isinstance(node, Like):
        return {node.col.field: {"$regex": like_to_regex(node.pattern), "$options": "s"}}
    raise NotSupported(f"cannot filter on {type(node).__name__}")


# ---------------------------------------------------------------- evaluate in Python (three-valued logic)

def _field(doc: dict, field: str):
    if "." in field and field not in doc:                                    # a path into an embedded document ("meta.day")
        cur = doc
        for part in field.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur
    return doc.get(field)


def evaluate(node, doc: dict):
    """True / False / None (unknown) for a stored document - SQL semantics. Used for ordering by an expression and by the tests."""
    if isinstance(node, And):
        vals = [evaluate(p, doc) for p in node.parts]
        return False if any(v is False for v in vals) else None if any(v is None for v in vals) else True
    if isinstance(node, Or):
        vals = [evaluate(p, doc) for p in node.parts]
        return True if any(v is True for v in vals) else None if any(v is None for v in vals) else False
    if isinstance(node, Cmp):
        if isinstance(node.left, FuncCall) and node.left.name == "coalesce":
            lhs = next((v for v in (_field(doc, a.field) for a in node.left.args) if v is not None), None)
            if lhs is None:
                return None
            v = node.value
            return {"==": lambda: lhs == v, "!=": lambda: lhs != v, "<": lambda: lhs < v, "<=": lambda: lhs <= v, ">": lambda: lhs > v, ">=": lambda: lhs >= v}[node.op]()
        if isinstance(node.left, FuncCall):
            lhs = _field(doc, node.left.args[0].field)
            return None if lhs is None else str(lhs).lower() == node.value
        lhs = _field(doc, node.left.field)
        if lhs is None:
            return None
        v = node.value
        return {"==": lambda: lhs == v, "!=": lambda: lhs != v, "<": lambda: lhs < v, "<=": lambda: lhs <= v, ">": lambda: lhs > v, ">=": lambda: lhs >= v}[node.op]()
    if isinstance(node, InList):
        lhs = _field(doc, node.col.field)
        return None if lhs is None else lhs in node.values
    if isinstance(node, NotInList):
        lhs = _field(doc, node.col.field)
        if lhs is None or lhs in node.values:
            return None if lhs is None else False
        return None if node.has_null else True
    if isinstance(node, Is):
        lhs = _field(doc, node.col.field)
        res = (lhs is None) if node.value is None else (lhs is node.value)
        return (not res) if node.negate else res
    if isinstance(node, Like):
        lhs = _field(doc, node.col.field)
        return None if lhs is None else re.match(like_to_regex(node.pattern), lhs, re.S) is not None
    raise NotSupported(f"cannot evaluate {type(node).__name__}")


# ---------------------------------------------------------------- ordering the way Postgres orders

def value_of(expr, doc: dict):
    """The VALUE of a column / coalesce / lower expression for a stored document (what an ORDER BY sorts on); a boolean expression gives True / False / None."""
    if isinstance(expr, ColumnOps):
        return _field(doc, expr.field)
    if isinstance(expr, FuncCall) and expr.name == "coalesce":
        return next((v for v in (value_of(a, doc) for a in expr.args) if v is not None), None)
    if isinstance(expr, FuncCall) and expr.name == "lower" and len(expr.args) == 1:
        v = value_of(expr.args[0], doc)
        return None if v is None else str(v).lower()
    return evaluate(expr, doc)


def order_key_fn(item):
    """-> (key function over a stored doc, reverse flag) for one ORDER BY item, Postgres NULL placement: ASC puts NULL last, DESC puts it first, unless told."""
    expr, is_desc, nulls = (item.expr, item.is_desc, item.nulls) if isinstance(item, OrderBy) else (item, False, None)
    null_is_largest = (not is_desc and nulls in (None, "last")) or (is_desc and nulls in (None, "first"))
    null_rank = 1 if null_is_largest else -1

    def key(doc):
        v = value_of(expr, doc)
        return (null_rank, 0) if v is None else (0, v)
    return key, is_desc


def sort_docs(docs: list, order: list) -> list:
    """A stable multi-key sort (least significant key first), docs given in `_id` order so ties keep insertion order like a heap scan."""
    out = list(docs)
    for item in reversed(order):
        key, rev = order_key_fn(item)
        out.sort(key=key, reverse=rev)
    return out


def pushdown_sort(order: list):
    """The Mongo sort spec when it gives Postgres's order for sure - every key a NOT NULL column with default NULL placement - else None (sort in Python)."""
    spec = []
    for item in order:
        expr, is_desc, nulls = (item.expr, item.is_desc, item.nulls) if isinstance(item, OrderBy) else (item, False, None)
        if not isinstance(expr, ColumnOps) or expr.nullable or nulls is not None:
            return None
        spec.append((expr.field, -1 if is_desc else 1))
    return spec
