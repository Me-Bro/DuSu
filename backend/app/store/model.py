"""Declarative models: `class User(Base): __tablename__ = 'users'; id: Mapped[str] = mapped_column(String(64), primary_key=True) ...` - the shape the application already uses.

A model is a Mongo collection (name = `__tablename__`):
  * a single-column primary key is the document's `_id` (the column keeps its Python name; only the stored field is `_id`);
  * a composite primary key is a UNIQUE compound index (`pk_<collection>`) and Mongo assigns `_id`;
  * an integer primary key without a value gets the next number of a per-collection counter when the row is added (see core.next_id);
  * `Index(name, "a", "-b", unique=True, where={...})` declares an index; `where` is a Mongo partialFilterExpression. A unique index over a column that can be NULL MUST be
    partial (Mongo treats two NULLs as equal, Postgres does not).
A column's value in Python is whatever the code assigned; what is stored is `column.type.to_store(value)`. Change detection compares stored forms, so an in-place edit of a JSON
column is found without `flag_modified` (which stays as a no-op so existing code reads the same).
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any

from .errors import DataError
from .expr import ColumnOps
from .types import (Boolean, Date, DateTime, Float, Integer, JSONB, SqlType, String, as_type, trunc_ms)


class _MappedAlias:
    def __init__(self, item):
        self.item = item

    def __repr__(self):
        return f"Mapped[{self.item!r}]"


class Mapped:
    """Annotation only: `Mapped[str]`, `Mapped[dt.datetime | None]`. Keeps the inner type so a bare `mapped_column(default=0.0)` can be typed from it."""

    def __class_getitem__(cls, item):
        return _MappedAlias(item)


class ForeignKey:
    def __init__(self, target, **kw):
        self.target = target


class Index:
    """`Index('ix_name', 'col_a', '-col_b', unique=False, where=None)`. A leading '-' = descending."""

    def __init__(self, name, *cols, unique=False, where=None, postgresql_where=None, **kw):
        if postgresql_where is not None:
            raise TypeError("use where={...} (a Mongo partialFilterExpression), not postgresql_where")
        self.name, self.cols, self.unique, self.where = name, [str(c) for c in cols], bool(unique), where


_MISSING = object()


class Column(ColumnOps):
    def __init__(self, type_=None, *, primary_key=False, autoincrement="auto", nullable=None, default=_MISSING, index=False, unique=False, fk=None):
        self.type: SqlType | None = type_
        self.primary_key = primary_key
        self.autoincrement = autoincrement
        self._nullable = nullable
        self.default = default
        self.index = index
        self.unique = unique
        self.fk = fk
        self.name = None
        self.field = None
        self.model = None
        self.nullable = True

    # --- descriptor: class access = the expression, instance access = the value
    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, inst, owner=None):
        if inst is None:
            return self
        return inst._data.get(self.name)

    def __set__(self, inst, value):
        if isinstance(value, dt.datetime):
            value = trunc_ms(value)            # memory agrees with what the database keeps
        inst._data[self.name] = value

    @property
    def has_default(self):
        return self.default is not _MISSING

    def make_default(self):
        d = self.default
        return d() if callable(d) else copy.deepcopy(d)

    def __repr__(self):
        return f"<Column {self.model.__tablename__ if self.model else '?'}.{self.name}>"


def mapped_column(*args, **kw) -> Column:
    type_, fk = None, None
    for a in args:
        if isinstance(a, ForeignKey):
            fk = a
        elif as_type(a) is not None:
            type_ = as_type(a)
        else:
            raise TypeError(f"mapped_column: unexpected argument {a!r}")
    unsupported = set(kw) - {"primary_key", "autoincrement", "nullable", "default", "index", "unique"}
    if unsupported:
        raise TypeError(f"mapped_column: unsupported option(s) {sorted(unsupported)}")
    return Column(type_, fk=fk, **kw)


class _Columns:
    """`Model.__table__.c`: the columns by name (attribute or item) and in definition order - what the tests' column-width checks read (`.type.length`)."""

    def __init__(self, model):
        self._m = model

    def __iter__(self):
        return iter(self._m.__columns__.values())

    def __len__(self):
        return len(self._m.__columns__)

    def __contains__(self, name):
        return (getattr(name, "name", name)) in self._m.__columns__

    def __getitem__(self, name):
        return self._m.__columns__[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._m.__columns__[name]
        except KeyError:
            raise AttributeError(name) from None


class _Table:
    def __init__(self, model):
        self._m = model
        self.name = model.__tablename__
        self.c = self.columns = _Columns(model)

    def delete(self):
        from .query import delete
        return delete(self._m)


class _Metadata:
    """`Base.metadata.sorted_tables` / `.tables`: read-only, parents before children. There is no create_all(): `store.init()` creates collections and indexes."""

    @property
    def tables(self):
        return {M.__tablename__: M.__table__ for M in Base._registry.values()}

    @property
    def sorted_tables(self):
        return [M.__table__ for M in sorted(Base._registry.values(), key=lambda m: (m.fk_rank(), m.__tablename__))]


def flag_modified(instance, attr):          # noqa: ARG001 - change detection compares stored forms; kept so existing code reads the same
    return None


# ---------------------------------------------------------------- type / nullability from the annotation

def _infer(annotation) -> tuple[SqlType, bool]:
    s = annotation if isinstance(annotation, str) else repr(getattr(annotation, "item", annotation))
    if s.startswith("Mapped[") and s.endswith("]"):
        s = s[len("Mapped["):-1]
    nullable = bool(re.search(r"\bNone\b", s))
    if "datetime" in s:
        t: SqlType = DateTime()
    elif re.search(r"\bdate\b", s):
        t = Date()
    elif re.search(r"\bbool\b", s):
        t = Boolean()
    elif re.search(r"\bfloat\b", s):
        t = Float()
    elif re.search(r"\bint\b", s):
        t = Integer()
    elif re.search(r"\b(dict|list)\b", s):
        t = JSONB()
    else:
        t = String()
    return t, nullable


class Base:
    """Declarative base: subclasses that set `__tablename__` become collections."""

    __tablename__: str
    metadata = _Metadata()
    __table_args__: Any = ()
    __columns__: dict
    __pk__: list
    __indexes__: list
    _registry: dict[str, type] = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if "__tablename__" not in cls.__dict__:
            return
        ann = cls.__dict__.get("__annotations__", {})
        cols: dict[str, Column] = {}
        for name, val in cls.__dict__.items():
            if isinstance(val, Column):
                cols[name] = val
        for name, c in cols.items():
            a_type, a_null = _infer(ann[name]) if name in ann else (None, True)
            if c.type is None:
                c.type = a_type or String()
            c.nullable = False if c.primary_key else (c._nullable if c._nullable is not None else a_null)
            c.model = cls
            c.name = name
        pk = [c for c in cols.values() if c.primary_key]
        if not pk:
            raise TypeError(f"{cls.__name__}: a model needs a primary key")
        for c in cols.values():
            c.field = "_id" if (len(pk) == 1 and c.primary_key) else c.name
        cls.__columns__ = cols
        cls.__table__ = _Table(cls)
        cls.__pk__ = pk
        cls.__fks__ = [(c, *str(c.fk.target).partition(".")[::2]) for c in cols.values() if c.fk is not None]       # [(column, parent table, parent column)]
        idx = list(Index_each(cls.__dict__.get("__table_args__", ())))
        for c in cols.values():
            if c.index and not c.primary_key:
                idx.append(Index(f"ix_{cls.__tablename__}_{c.name}", c.name))
            if c.unique and not c.primary_key:
                idx.append(Index(f"uq_{cls.__tablename__}_{c.name}", c.name, unique=True, where={c.field: {"$type": c.type.bson_type}} if c.nullable else None))
        if len(pk) > 1:
            idx.append(Index(f"pk_{cls.__tablename__}", *[c.name for c in pk], unique=True))
        cls.__indexes__ = idx
        Base._registry[cls.__tablename__] = cls

    def __init__(self, **kw):
        self._data: dict[str, Any] = {}
        self._snap: dict[str, Any] | None = None       # stored forms as last read / written; None = not yet in the database
        self._deleted = False
        for k, v in kw.items():
            if k not in self.__columns__:
                raise TypeError(f"{type(self).__name__} has no column {k!r}")
            setattr(self, k, v)

    # ----------------------------------------------------------- identity
    @classmethod
    def models(cls):
        return list(Base._registry.values())

    @classmethod
    def fk_referrers(cls, table: str) -> list:
        """[(model, column)] of every foreign key that points at `table` (the delete-side RESTRICT check)."""
        return [(M, c) for M in Base._registry.values() for (c, tbl, _col) in getattr(M, "__fks__", []) if tbl == table]

    @classmethod
    def fk_rank(cls, _stack=()) -> int:
        """0 for a model without a foreign key, else 1 + its deepest parent: parents are inserted before children, as SQLAlchemy's unit of work did."""
        if cls.__tablename__ in _stack:
            return 0
        ranks = [Base._registry[tbl].fk_rank(_stack + (cls.__tablename__,)) for (_c, tbl, _col) in getattr(cls, "__fks__", []) if tbl in Base._registry]
        return 1 + max(ranks) if ranks else 0

    @classmethod
    def pk_of(cls, instance_or_values) -> tuple:
        if isinstance(instance_or_values, Base):
            return tuple(instance_or_values._data.get(c.name) for c in cls.__pk__)
        v = instance_or_values
        return tuple(v) if isinstance(v, (tuple, list)) else (v,)

    def _pk(self) -> tuple:
        return tuple(self._data.get(c.name) for c in self.__pk__)

    @classmethod
    def pk_filter(cls, pk) -> dict:
        pk = cls.pk_of(pk)
        if len(pk) != len(cls.__pk__):
            raise DataError(f"{cls.__name__}: a primary key needs {len(cls.__pk__)} value(s)")
        return {c.field: c.type.to_bind(v) for c, v in zip(cls.__pk__, pk)}

    @classmethod
    def pk_id(cls, pk):
        """A hashable, ORDERABLE-by-repr key for the in-process lock registry."""
        return tuple(cls.pk_filter(pk).values())

    # ----------------------------------------------------------- storage
    def _stored(self) -> dict[str, Any]:
        """The stored form of every column (keyed by column name)."""
        return {name: c.type.to_store(self._data.get(name)) for name, c in self.__columns__.items()}

    def _apply_defaults(self):
        for name, c in self.__columns__.items():
            if self._data.get(name) is None and c.has_default and not (c.primary_key and c.autoincrement is not False and isinstance(c.type, Integer)):
                setattr(self, name, c.make_default())              # through the descriptor: a datetime default is truncated to what is stored

    def _needs_id(self) -> bool:
        if len(self.__pk__) != 1:
            return False
        c = self.__pk__[0]
        return isinstance(c.type, Integer) and c.autoincrement is not False and self._data.get(c.name) is None

    def _doc_from_stored(self, stored: dict[str, Any]) -> dict[str, Any]:
        doc = {}
        for name, c in self.__columns__.items():
            doc[c.field] = stored[name]
        return doc

    def _changes(self) -> dict[str, Any]:
        """{field: stored value} of what differs from the snapshot (empty for a clean row)."""
        if self._snap is None:
            return {}
        now = self._stored()
        out = {}
        for name, c in self.__columns__.items():
            if c.field == "_id":
                continue
            if now[name] != self._snap.get(name):
                out[c.field] = now[name]
        return out

    def _load(self, doc: dict[str, Any]):
        data, snap = {}, {}
        for name, c in self.__columns__.items():
            if c.field in doc:
                raw = doc[c.field]
            elif c.has_default and not callable(c.default):
                raw = c.make_default()                  # a field added after the row was written: what ALTER TABLE ... DEFAULT gave old rows
            else:
                raw = None
            data[name] = c.type.from_store(raw) if raw is not None else None
            snap[name] = c.type.to_store(data[name])
        self._data, self._snap = data, snap

    def _mark_stored(self):
        self._snap = copy.deepcopy(self._stored())

    def __repr__(self):
        pk = ", ".join(f"{c.name}={self._data.get(c.name)!r}" for c in self.__pk__)
        return f"<{type(self).__name__} {pk}>"


def Index_each(table_args):
    """`__table_args__` is a tuple of Index objects, optionally ending in a dict of options (SQLAlchemy habit)."""
    if isinstance(table_args, Index):
        yield table_args
        return
    for a in table_args or ():
        if isinstance(a, Index):
            yield a
