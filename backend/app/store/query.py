"""Statement builders (`select`, `update`, `delete`, `insert`) and results - SQLAlchemy 2.0 shaped, immutable (every method returns a copy, so a base query can be reused).

Not supported, and loud about it: joins, `exists`, `union`, subqueries, aggregate FILTER, negation, savepoints. Those few call sites are ported by hand.
"""

from __future__ import annotations

import copy

from .errors import MultipleResultsFound, NoResultFound, NotSupported
from .expr import Arith, ColumnOps, Expr, FuncCall, OrderBy
from .model import Base, Column


def _clone(o):
    n = copy.copy(o)
    for k, v in list(vars(n).items()):
        if isinstance(v, list):
            setattr(n, k, list(v))
        elif isinstance(v, dict):
            setattr(n, k, dict(v))
    return n


class Select:
    def __init__(self, *entities):
        if not entities:
            raise NotSupported("select() needs at least one entity")
        self.entities = list(entities)
        self._where: list = []
        self._order: list = []
        self._limit = None
        self._offset = None
        self._for_update = None
        self._group: list = []
        self._distinct = False
        self._from = None
        self._opts: dict = {}

    def where(self, *conds):
        n = _clone(self)
        n._where += [c for c in conds if c is not None]
        return n

    def order_by(self, *items):
        n = _clone(self)
        n._order += list(items)
        return n

    def limit(self, k):
        n = _clone(self)
        n._limit = None if k is None else int(k)
        return n

    def offset(self, k):
        n = _clone(self)
        n._offset = None if k is None else int(k)
        return n

    def with_for_update(self, *, skip_locked=False, nowait=False, of=None, read=False, key_share=False):
        if skip_locked or nowait:
            raise NotSupported("SKIP LOCKED / NOWAIT: use an atomic find_one_and_update claim (see store.Session.claim)")
        n = _clone(self)
        n._for_update = True
        return n

    def select_from(self, model):
        n = _clone(self)
        n._from = model
        return n

    def group_by(self, *cols):
        n = _clone(self)
        n._group += list(cols)
        return n

    def distinct(self):
        n = _clone(self)
        n._distinct = True
        return n

    def execution_options(self, **kw):
        n = _clone(self)
        n._opts.update(kw)
        return n

    def join(self, *a, **k):
        raise NotSupported("joins are not supported by the store (port the call site: two queries and a dict)")

    outerjoin = join

    def subquery(self, *a, **k):
        raise NotSupported("subqueries are not supported by the store")

    scalar_subquery = subquery


def select(*entities) -> Select:
    return Select(*entities)


class Update:
    def __init__(self, model):
        self.model = model
        self._where: list = []
        self._values: dict = {}
        self._returning: list = []
        self._opts: dict = {}

    def where(self, *conds):
        n = _clone(self)
        n._where += [c for c in conds if c is not None]
        return n

    def values(self, **kw):
        n = _clone(self)
        for k in kw:
            if k not in self.model.__columns__:
                raise NotSupported(f"{self.model.__name__} has no column {k!r}")
        n._values.update(kw)
        return n

    def returning(self, *cols):
        n = _clone(self)
        n._returning = list(cols)
        return n

    def execution_options(self, **kw):
        n = _clone(self)
        n._opts.update(kw)
        return n


def update(model) -> Update:
    return Update(model)


class Delete:
    def __init__(self, model):
        self.model = model
        self._where: list = []
        self._opts: dict = {}

    def where(self, *conds):
        n = _clone(self)
        n._where += [c for c in conds if c is not None]
        return n

    def execution_options(self, **kw):
        n = _clone(self)
        n._opts.update(kw)
        return n


def delete(model) -> Delete:
    return Delete(model)


class _Excluded:
    """`stmt.excluded.col` inside on_conflict_do_update(set_=...): the value proposed for the insert."""

    def __init__(self, values):
        self._v = values

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._v[name]

    def __getitem__(self, name):
        return self._v[name]


class Insert:
    def __init__(self, model):
        self.model = model
        self._values: dict = {}
        self._conflict = None            # None | ("nothing", elements, where) | ("update", elements, set_, where)
        self._returning: list = []

    def values(self, **kw):
        n = _clone(self)
        for k in kw:
            if k not in self.model.__columns__:
                raise NotSupported(f"{self.model.__name__} has no column {k!r}")
        n._values.update(kw)
        return n

    @property
    def excluded(self):
        return _Excluded(self._values)

    def on_conflict_do_nothing(self, index_elements=None, index_where=None, constraint=None):
        n = _clone(self)
        n._conflict = ("nothing", [getattr(c, "name", c) for c in (index_elements or [])], index_where)
        return n

    def on_conflict_do_update(self, index_elements=None, index_where=None, constraint=None, set_=None, where=None):
        if where is not None:
            raise NotSupported("on_conflict_do_update(where=...) is not supported")
        n = _clone(self)
        n._conflict = ("update", [getattr(c, "name", c) for c in (index_elements or [])], dict(set_ or {}), index_where)
        return n

    def returning(self, *cols):
        n = _clone(self)
        n._returning = list(cols)
        return n


def insert(model) -> Insert:
    return Insert(model)


pg_insert = insert


# ---------------------------------------------------------------- results

class Row(tuple):
    """A result row: a tuple that also answers to attribute names."""

    def __new__(cls, fields, values):
        o = super().__new__(cls, values)
        o._fields = tuple(fields)
        return o

    def __getattr__(self, name):
        try:
            return self[self._fields.index(name)]
        except ValueError:
            raise AttributeError(name) from None


class ScalarResult:
    def __init__(self, values):
        self._v = list(values)

    def all(self):
        return list(self._v)

    def first(self):
        return self._v[0] if self._v else None

    def one(self):
        if not self._v:
            raise NoResultFound("no row was found")
        if len(self._v) > 1:
            raise MultipleResultsFound("multiple rows were found")
        return self._v[0]

    def one_or_none(self):
        if len(self._v) > 1:
            raise MultipleResultsFound("multiple rows were found")
        return self._v[0] if self._v else None

    def __iter__(self):
        return iter(self._v)


class Result:
    def __init__(self, rows=None, rowcount=-1):
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self):
        return ScalarResult(r[0] for r in self._rows)

    def scalar(self):
        return self._rows[0][0] if self._rows else None

    def scalar_one(self):
        return self.scalars().one()

    def scalar_one_or_none(self):
        return self.scalars().one_or_none()

    def all(self):
        return list(self._rows)

    fetchall = all

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if not self._rows:
            raise NoResultFound("no row was found")
        if len(self._rows) > 1:
            raise MultipleResultsFound("multiple rows were found")
        return self._rows[0]

    def one_or_none(self):
        if len(self._rows) > 1:
            raise MultipleResultsFound("multiple rows were found")
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)
