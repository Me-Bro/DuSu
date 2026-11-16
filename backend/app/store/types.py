"""Column types: how a Python value is stored in a Mongo document and read back.

  DateTime  -> BSON date, tz-aware UTC, MILLISECOND precision (Postgres had microseconds; the value is truncated here so memory and database agree)
  Date      -> ISO string 'YYYY-MM-DD' (a date has no time zone and no BSON type; ISO strings sort and compare like dates)
  JSONB     -> an embedded document, normalised exactly as json.dumps/json.loads would (string keys, tuples -> lists; anything else is an error)
  Integer   -> int (int64 range)      Float -> double      Boolean -> bool      String / Text -> str

`to_store` is for values written; `to_bind` is for values compared against in a filter (the same conversion, but None stays None).
"""

from __future__ import annotations

import datetime as dt
import math

from .errors import DataError

_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1
_UTC = dt.timezone.utc


class SqlType:
    name = "?"
    json = False          # an embedded document / list (compared whole, never by `==` in a filter)

    def __init__(self, *args, **kw):
        self.args, self.kw = args, kw

    def to_store(self, v):
        return v

    def from_store(self, v):
        return v

    def to_bind(self, v):
        return None if v is None else self.to_store(v)

    def __repr__(self):
        return self.name


class String(SqlType):
    name = "string"
    bson_type = "string"

    def __init__(self, length=None, *a, **k):
        super().__init__(length, *a, **k)
        self.length = length

    def to_store(self, v):
        if v is None:
            return None
        if not isinstance(v, str):
            raise DataError(f"expected str for a string column, got {type(v).__name__}")
        return v


class Text(String):
    name = "text"


class Integer(SqlType):
    name = "int"
    bson_type = "number"

    def to_store(self, v):
        if v is None:
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, float):
            if not v.is_integer():
                raise DataError(f"expected an integer, got {v!r}")
            v = int(v)
        if not isinstance(v, int):
            raise DataError(f"expected int for an integer column, got {type(v).__name__}")
        if not _INT64_MIN <= v <= _INT64_MAX:
            raise DataError(f"integer out of range: {v}")
        return v

    def from_store(self, v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v


class SmallInteger(Integer):
    name = "smallint"


class Float(SqlType):
    name = "float"
    bson_type = "number"

    def to_store(self, v):
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise DataError(f"expected a number for a float column, got {type(v).__name__}")
        return float(v)


class Boolean(SqlType):
    name = "bool"
    bson_type = "bool"

    def to_store(self, v):
        if v is None:
            return None
        if not isinstance(v, (bool, int)):
            raise DataError(f"expected bool for a boolean column, got {type(v).__name__}")
        return bool(v)


def trunc_ms(v: dt.datetime) -> dt.datetime:
    return v.replace(microsecond=(v.microsecond // 1000) * 1000)


class DateTime(SqlType):
    name = "datetime"
    bson_type = "date"

    def __init__(self, timezone=True, *a, **k):
        super().__init__(timezone, *a, **k)

    def to_store(self, v):
        if v is None:
            return None
        if not isinstance(v, dt.datetime):
            raise DataError(f"expected datetime for a datetime column, got {type(v).__name__}")
        v = v.replace(tzinfo=_UTC) if v.tzinfo is None else v.astimezone(_UTC)
        return trunc_ms(v)

    def from_store(self, v):
        if isinstance(v, dt.datetime):
            return v.replace(tzinfo=_UTC) if v.tzinfo is None else v.astimezone(_UTC)
        return v


class Date(SqlType):
    name = "date"
    bson_type = "string"

    def to_store(self, v):
        if v is None:
            return None
        if isinstance(v, dt.datetime):      # asyncpg took the date part of a datetime for a DATE column; so does this
            v = v.date()
        if not isinstance(v, dt.date):
            raise DataError(f"expected date for a date column, got {type(v).__name__}")
        return v.isoformat()

    def from_store(self, v):
        if isinstance(v, str):
            return dt.date.fromisoformat(v)
        if isinstance(v, dt.datetime):
            return v.date()
        return v


def _json_key(k):
    """What json.dumps does to a dict key."""
    if isinstance(k, str):
        return k
    if k is None:
        return "null"
    if isinstance(k, bool):
        return "true" if k else "false"
    if isinstance(k, int):
        return str(k)
    if isinstance(k, float):
        return repr(k)
    raise DataError(f"a JSON object key must be a string, number, bool or null, not {type(k).__name__}")


def json_norm(v, _depth=0):
    """The value as JSON would carry it: dict keys become strings, tuples become lists, anything not JSON is an error (as in Postgres)."""
    if _depth > 60:
        raise DataError("JSON nested too deeply")
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        if not _INT64_MIN <= v <= _INT64_MAX:
            raise DataError(f"integer out of range: {v}")
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise DataError("NaN / Infinity are not valid JSON")
        return v
    if isinstance(v, dict):
        return {_json_key(k): json_norm(x, _depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_norm(x, _depth + 1) for x in v]
    raise DataError(f"a {type(v).__name__} is not JSON serialisable")


class JSONB(SqlType):
    name = "json"
    json = True

    def to_store(self, v):
        return json_norm(v)

    def from_store(self, v):
        return v

    def to_bind(self, v):
        return None if v is None else json_norm(v)


JSON = JSONB


def as_type(t):
    """`mapped_column(String(64))`, `mapped_column(Integer)` and `mapped_column(TS)` all arrive here."""
    if t is None:
        return None
    if isinstance(t, SqlType):
        return t
    if isinstance(t, type) and issubclass(t, SqlType):
        return t()
    return None
