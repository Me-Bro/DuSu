"""Exceptions of the store. The names match the SQLAlchemy ones the application already catches (`IntegrityError`, `DBAPIError`, `DataError`)."""


class StoreError(Exception):
    """Base of everything the store raises on purpose."""


class DBAPIError(StoreError):
    """A database-level failure (the driver, the server, the network). `IntegrityError` and `DataError` are kinds of it, as in SQLAlchemy."""


class IntegrityError(DBAPIError):
    """A unique index refused a write (Mongo's DuplicateKeyError)."""


class DataError(DBAPIError):
    """A value the store cannot hold: an out-of-range integer, JSON that is not JSON, the wrong type for a column."""


class ConcurrencyError(StoreError):
    """A write conflict that survived the retries, or a replay that no longer reproduces what the body already decided on."""


class LockTimeout(ConcurrencyError):
    """Waited too long for a row lock held by another session of this process (a deadlock, or a session that never ended)."""


class NoResultFound(StoreError):
    """`scalar_one()` / `one()` found no row."""


class MultipleResultsFound(StoreError):
    """`scalar_one()` / `one()` found more than one row."""


class NotSupported(NotImplementedError):
    """A SQLAlchemy construct the store does not implement (a join, `exists`, a savepoint ...). Raised loudly: nothing silently misbehaves."""
