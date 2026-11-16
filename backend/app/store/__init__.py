"""app.store - MongoDB behind the SQLAlchemy-2.0-shaped surface DuSu's code is written against.

    from .store import Base, Mapped, mapped_column, String, Integer, ..., select, update, delete, insert, func, and_, or_, desc, Session ...

Not SQLAlchemy and not a general ORM: only what the application uses, and anything else raises NotSupported. The contract (and why each choice) is in DUSU_MONGO_MIGRATION_PLAN.md
section 4 and tested in tests/store/. Configure once with `configure(uri)`; `init()` creates the collections and indexes of every registered model.
"""

from . import core
from .core import LOCKS, close, configure, enabled, next_id, raise_counter
from .errors import (ConcurrencyError, DataError, DBAPIError, IntegrityError, LockTimeout, MultipleResultsFound, NoResultFound, NotSupported, StoreError)
from .expr import and_, asc, desc, exists, func, or_, text
from .model import Base, Column, ForeignKey, Index, Mapped, flag_modified, mapped_column
from .query import Result, Row, delete, insert, pg_insert, select, update
from .session import Session, SessionFactory, async_sessionmaker, claim_one
from .types import (Boolean, Date, DateTime, Float, Integer, JSON, JSONB, SmallInteger, String, Text, trunc_ms)


async def init(models=None) -> dict:
    """Create every collection and index the registered models declare (idempotent). Returns {collection: [index names]}."""
    return await core.ensure_indexes(models if models is not None else Base.models())


__all__ = [n for n in dir() if not n.startswith("_")]
