"""Connection, integer-id counters, in-process row locks and index creation.

One `AsyncMongoClient` per event loop (PyMongo's async client is bound to the loop it first runs on). `tz_aware=True`: every datetime read is UTC-aware, like timestamptz was.

DUSU_SCRATCH_ONLY=1 (set by every test harness) makes `configure()` refuse any host that is not a scratch container - a test must never reach the shared `rooted-mongo`.
"""

from __future__ import annotations

import asyncio
import os
import random
from urllib.parse import urlsplit

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import CollectionInvalid, OperationFailure

from .errors import LockTimeout

LOCK_TIMEOUT = float(os.getenv("STORE_LOCK_TIMEOUT", "20"))
STATS = {"txn_retries": 0, "replays": 0, "lock_waits": 0}      # what the safety nets had to do: a healthy in-process workload retries and replays nothing

_uri: str | None = None
_client: AsyncMongoClient | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _host_of(uri: str) -> str:
    return urlsplit(uri).netloc.rsplit("@", 1)[-1].split(",")[0].split(":")[0]


def configure(uri: str | None) -> bool:
    """Remember the URI (no connection yet). Returns whether a database is configured."""
    global _uri, _client, _loop
    uri = (uri or "").strip()
    if uri and not uri.startswith(("mongodb://", "mongodb+srv://")):
        raise RuntimeError("MONGODB_URI must start with mongodb:// (a postgres:// URL in the old DATABASE_URL is no longer used)")
    if uri and os.getenv("DUSU_SCRATCH_ONLY") == "1" and "scratch" not in _host_of(uri):
        raise RuntimeError(f"DUSU_SCRATCH_ONLY=1: refusing to connect to {_host_of(uri)!r} - tests use a scratch container only")
    _uri, _client, _loop = uri or None, None, None
    return bool(_uri)


def enabled() -> bool:
    return bool(_uri)


def client() -> AsyncMongoClient:
    """The client for the running loop (created on first use; a new loop - a test that calls asyncio.run twice - gets a new client)."""
    global _client, _loop
    loop = asyncio.get_running_loop()
    if _client is None or _loop is not loop:
        if not _uri:
            raise RuntimeError("no database configured (MONGODB_URI is empty)")
        _client = AsyncMongoClient(_uri, tz_aware=True, serverSelectionTimeoutMS=10000, appname="dusu")
        _loop = loop
    return _client


def database():
    db = client().get_default_database()
    return db


def coll(name: str):
    return database()[name]


async def close():
    global _client, _loop
    c, _client, _loop = _client, None, None
    if c is not None:
        try:
            await c.close()
        except Exception:                                            # noqa: BLE001 - shutting down
            pass


# ---------------------------------------------------------------- integer ids (a sequence per collection, outside every transaction, gaps are fine)

async def next_id(collection: str) -> int:
    d = await coll("counters").find_one_and_update({"_id": collection}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(d["seq"])


async def raise_counter(collection: str, at_least: int) -> int:
    """Make sure the NEXT id is above `at_least` (the ETL after copying rows that carry their own ids)."""
    d = await coll("counters").find_one_and_update({"_id": collection}, {"$max": {"seq": int(at_least)}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(d["seq"])


# ---------------------------------------------------------------- keyed in-process locks (what SELECT ... FOR UPDATE / a row lock on UPDATE gave)

class _KeyedLocks:
    def __init__(self):
        self._m: dict = {}

    async def acquire(self, keys: list, timeout: float):
        got = []
        try:
            for k in keys:
                ent = self._m.get(k)
                if ent is None:
                    ent = self._m[k] = [asyncio.Lock(), 0]
                ent[1] += 1
                try:
                    await asyncio.wait_for(ent[0].acquire(), timeout)
                except BaseException as e:
                    ent[1] -= 1
                    self._drop(k)
                    if isinstance(e, asyncio.TimeoutError):
                        raise LockTimeout(f"waited {timeout:.0f}s for a row lock held by another session (a deadlock, or a session that never ended): {k!r}") from None
                    raise
                got.append(k)
        except BaseException:
            self.release(got)
            raise

    def release(self, keys: list):
        for k in reversed(keys):
            ent = self._m.get(k)
            if ent is None:
                continue
            if ent[0].locked():
                ent[0].release()
            ent[1] -= 1
            self._drop(k)

    def _drop(self, k):
        ent = self._m.get(k)
        if ent is not None and ent[1] <= 0 and not ent[0].locked():
            del self._m[k]

    def held(self) -> int:
        return sum(1 for e in self._m.values() if e[0].locked())


LOCKS = _KeyedLocks()


# ---------------------------------------------------------------- indexes

def _index_keys(model, ix):
    keys = []
    for spec in ix.cols:
        desc = spec.startswith("-")
        name = spec[1:] if desc else spec
        c = model.__columns__.get(name)
        keys.append((c.field if c is not None else name, -1 if desc else 1))
    return keys


async def ensure_indexes(models) -> dict:
    """Create every collection and index the models declare. Idempotent: an identical index is a no-op; a plain index whose definition changed is replaced; a changed UNIQUE index
    is an error (it needs a human). Returns {collection: [index names]}."""
    out = {}
    db = database()
    for M in models:
        name = M.__tablename__
        try:
            await db.create_collection(name)
        except CollectionInvalid:                                    # it already exists
            pass
        except OperationFailure as e:
            if e.code != 48:                                         # 48 = NamespaceExists
                raise
        c = db[name]
        names = []
        for ix in M.__indexes__:
            kw = {"name": ix.name, "unique": ix.unique}
            if ix.where:
                kw["partialFilterExpression"] = ix.where
            keys = _index_keys(M, ix)
            try:
                await c.create_index(keys, **kw)
            except OperationFailure as e:
                if e.code in (85, 86) and not ix.unique:             # IndexOptionsConflict / IndexKeySpecsConflict: a plain index we can safely rebuild
                    await c.drop_index(ix.name)
                    await c.create_index(keys, **kw)
                else:
                    raise
            names.append(ix.name)
        out[name] = names
    try:
        await db.create_collection("counters")
    except CollectionInvalid:
        pass
    except OperationFailure as e:
        if e.code != 48:
            raise
    return out


def backoff(attempt: int) -> float:
    return min(0.4, 0.01 * (2 ** attempt)) * (0.5 + random.random())
