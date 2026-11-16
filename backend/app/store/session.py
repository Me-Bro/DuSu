"""Session: the unit of work over Mongo, shaped like SQLAlchemy's AsyncSession (`get`, `add`, `delete`, `flush`, `commit`, `rollback`, `execute`).

Semantics, in one place (each is a test in tests/store):

* READS before the session has written anything are plain reads of the latest committed state (Postgres READ COMMITTED). Once the session has written, reads go through its
  transaction so it sees its own writes. Every query first AUTOFLUSHES pending changes, like SQLAlchemy.
* The first write opens a MONGO TRANSACTION (the shared Mongo is a replica set, so this works); `commit()` commits it, an exception or `rollback()` aborts it.
  Everything the session wrote is kept as a LOG of operations. A transaction can be aborted and REPLAYED from the log:
    - never wait for a lock with a transaction open (a stale snapshot would conflict with the very write the lock protects): abort, lock, then replay in a fresh snapshot;
    - a transient WriteConflict (another transaction touched one of our documents) = abort, short back-off, replay, carry on.
  A replay must reproduce what the body already saw (same matched counts); if it does not, ConcurrencyError - loud, never a silent wrong write.
* ROW LOCKS are in-process keyed async locks (collection, primary key), taken BEFORE a locked read (`with_for_update`, `get(..., with_for_update=True)`) and at flush for every
  document the session updates or deletes (what UPDATE's row lock did), held to commit / rollback / close, in sorted order, with a timeout. The deployment is one process;
  Mongo's own write-conflict detection stays the cross-process safety net.
* A duplicate key aborts a Mongo transaction (there are no savepoints): it surfaces as IntegrityError and the session's transaction is already gone - the caller rolls back.
  The SQLAlchemy savepoint idiom (`begin_nested()` + IntegrityError) is NOT available; use `insert(...).on_conflict_do_nothing(...)` (an upsert) instead.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError, ConnectionFailure, DuplicateKeyError, OperationFailure, PyMongoError

from . import core
from .errors import ConcurrencyError, DataError, DBAPIError, IntegrityError, NotSupported
from .expr import And, Arith, ColumnOps, FuncCall, InList, Or, and_, pushdown_sort, sort_docs, to_filter
from .model import Base
from .query import Delete, Insert, Result, Row, Select, Update

MAX_ATTEMPTS = 8


@dataclass
class Op:
    kind: str                       # insert | update_one | update_many | delete_one | delete_many | upsert
    coll: str
    a: Any = None                   # documents / filter
    b: Any = None                   # update document
    expect: int | None = None       # what the first run affected; a replay must match it


def _transient(e: OperationFailure) -> bool:
    return e.has_error_label("TransientTransactionError") or e.code in (112, 251, 246)     # WriteConflict, NoSuchTransaction, SnapshotUnavailable


def _wrap(e: Exception) -> Exception:
    if isinstance(e, (IntegrityError, DataError, ConcurrencyError, NotSupported)):
        return e
    if isinstance(e, DuplicateKeyError) or (isinstance(e, BulkWriteError) and any(w.get("code") == 11000 for w in (e.details or {}).get("writeErrors", []))):
        return IntegrityError("duplicate key")
    if isinstance(e, OperationFailure) and e.code == 11000:
        return IntegrityError("duplicate key")
    if isinstance(e, OverflowError):
        return DataError(str(e))
    return DBAPIError(f"{type(e).__name__}: {str(e)[:200]}")


class _Savepoint:
    async def __aenter__(self):
        raise NotSupported("begin_nested() savepoints are not available: a duplicate key aborts a Mongo transaction. Use insert(...).on_conflict_do_nothing(...) or check first under a lock.")

    async def __aexit__(self, *a):
        return False


class Session:
    def __init__(self, factory=None):
        self._ident: dict = {}
        self._new: list = []
        self._deleted: list = []
        self._held: list = []
        self._held_set: set = set()
        self._ms = None
        self._in_txn = False
        self._log: list[Op] = []
        self._flushing = False
        self._fk_known: set = set()                 # (parent table, key) pairs already seen to exist in this session

    async def __aenter__(self):
        return self

    async def __aexit__(self, et, ev, tb):
        await self.close()
        return False

    # ================================================================ transaction plumbing

    async def _abort_txn(self):
        ms, self._ms, self._in_txn = self._ms, None, False
        if ms is not None:
            try:
                if ms.in_transaction:
                    await ms.abort_transaction()
            except Exception:                                    # noqa: BLE001 - already failing
                pass
            try:
                await ms.end_session()
            except Exception:                                    # noqa: BLE001
                pass

    async def _ensure_txn(self):
        if self._in_txn:
            return
        ms = core.client().start_session()
        self._ms = ms
        try:
            await ms.start_transaction()
            self._in_txn = True
            if self._log:
                core.STATS["replays"] += 1
            for op in self._log:                                  # replay what this session already wrote, in a fresh snapshot
                n, _ = await self._exec_op(op, ms)
                if n != op.expect:
                    raise ConcurrencyError(f"replay of {op.kind} on {op.coll} affected {n} document(s), the first run affected {op.expect}")
        except BaseException:
            await self._abort_txn()
            raise

    async def _exec_op(self, op: Op, ms):
        c = core.coll(op.coll)
        k = op.kind
        if k == "insert":
            if len(op.a) == 1:
                await c.insert_one(op.a[0], session=ms)
            else:
                await c.insert_many(op.a, ordered=True, session=ms)
            return len(op.a), None
        if k == "update_one":
            return (await c.update_one(op.a, op.b, session=ms)).matched_count, None
        if k == "update_many":
            return (await c.update_many(op.a, op.b, session=ms)).matched_count, None
        if k == "delete_one":
            return (await c.delete_one(op.a, session=ms)).deleted_count, None
        if k == "delete_many":
            return (await c.delete_many(op.a, session=ms)).deleted_count, None
        if k == "upsert":
            r = await c.update_one(op.a, op.b, upsert=True, session=ms)
            return (1 if r.upserted_id is not None else 0), r.upserted_id
        raise NotSupported(f"unknown op {k}")

    async def _run(self, fn, *, write=False):
        """Run `fn(pymongo_session | None)`. A write, or a session that has already written, runs inside the transaction (replayed from a fresh snapshot on a transient failure)."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            in_txn = write or bool(self._log) or self._in_txn
            try:
                if in_txn:
                    await self._ensure_txn()
                return await fn(self._ms if in_txn else None)
            except OperationFailure as e:
                if in_txn and _transient(e) and attempt < MAX_ATTEMPTS:
                    core.STATS["txn_retries"] += 1
                    await self._abort_txn()
                    await asyncio.sleep(core.backoff(attempt))
                    continue
                if in_txn:
                    await self._abort_txn()
                    self._log.clear()
                raise _wrap(e) from e
            except (DuplicateKeyError, BulkWriteError, OverflowError) as e:
                await self._abort_txn()
                self._log.clear()
                raise _wrap(e) from e
            except ConnectionFailure as e:
                await self._abort_txn()
                raise _wrap(e) from e
            except PyMongoError as e:
                await self._abort_txn()
                self._log.clear()
                raise _wrap(e) from e

    async def _apply(self, op: Op):
        async def go(ms):
            return await self._exec_op(op, ms)
        n, extra = await self._run(go, write=True)
        op.expect = n
        self._log.append(op)
        return n, extra

    async def _finish(self, commit: bool):
        if commit:
            if self._log and not self._in_txn:
                await self._run(lambda ms: _noop(), write=True)          # replay the log into a fresh transaction so there is something to commit
            for attempt in range(1, MAX_ATTEMPTS + 1):
                if not self._in_txn:
                    break
                try:
                    await self._ms.commit_transaction()
                    break
                except OperationFailure as e:
                    if e.has_error_label("UnknownTransactionCommitResult") and attempt < MAX_ATTEMPTS:
                        continue                                          # the commit may have happened: asking again is safe
                    if _transient(e) and attempt < MAX_ATTEMPTS:
                        await self._abort_txn()
                        await asyncio.sleep(core.backoff(attempt))
                        await self._ensure_txn()
                        continue
                    await self._abort_txn()
                    self._log.clear()
                    raise _wrap(e) from e
            await self._end_session()
        else:
            await self._abort_txn()
        self._log.clear()

    async def _end_session(self):
        ms, self._ms, self._in_txn = self._ms, None, False
        if ms is not None:
            try:
                await ms.end_session()
            except Exception:                                            # noqa: BLE001
                pass

    # ================================================================ locks

    async def _lock_keys(self, keys):
        new = [k for k in sorted(set(keys), key=repr) if k not in self._held_set]
        if not new:
            return
        if self._in_txn:                                                  # never wait for a lock with a transaction open
            await self._abort_txn()
        await core.LOCKS.acquire(new, core.LOCK_TIMEOUT)
        self._held.extend(new)
        self._held_set.update(new)

    def _release_locks(self):
        if self._held:
            core.LOCKS.release(self._held)
        self._held, self._held_set = [], set()

    @staticmethod
    def _key(model, doc) -> tuple:
        return (model.__tablename__, tuple(doc[c.field] for c in model.__pk__))

    # ================================================================ identity map

    def _instance(self, model, doc, populate=False):
        inst = model.__new__(model)
        inst._deleted = False
        inst._load(doc)
        key = (model, inst._pk())
        have = self._ident.get(key)
        if have is not None:
            if populate:
                have._load(doc)
            return have
        self._ident[key] = inst
        return inst

    # ================================================================ public API

    def add(self, inst):
        if not isinstance(inst, Base):
            raise TypeError(f"cannot add {type(inst).__name__}")
        if inst in self._new or (inst._snap is not None and self._ident.get((type(inst), inst._pk())) is inst):
            return
        inst._deleted = False
        self._new.append(inst)

    def add_all(self, insts):
        for i in insts:
            self.add(i)

    async def delete(self, inst):
        if inst in self._new:
            self._new.remove(inst)
            return
        if inst._snap is None:
            return
        inst._deleted = True
        if inst not in self._deleted:
            self._deleted.append(inst)

    def begin_nested(self):
        return _Savepoint()

    async def get(self, model, pk, *, with_for_update=False, populate_existing=False, options=None):
        pk = model.pk_of(pk)
        key = (model, pk)
        have = self._ident.get(key)
        if have is not None and have._deleted:
            return None
        if have is not None and not with_for_update and not populate_existing:
            return have
        flt = model.pk_filter(pk)
        if with_for_update:
            await self._autoflush()
            await self._lock_keys([(model.__tablename__, model.pk_id(pk))])
        else:
            await self._autoflush()

        async def fetch(ms):
            return await core.coll(model.__tablename__).find_one(flt, session=ms)
        doc = await self._run(fetch)
        if doc is None:
            return None
        return self._instance(model, doc, populate=populate_existing or with_for_update)

    async def execute(self, stmt, params=None):
        if isinstance(stmt, Select):
            return await self._select(stmt)
        if isinstance(stmt, Update):
            return await self._update(stmt)
        if isinstance(stmt, Delete):
            return await self._delete(stmt)
        if isinstance(stmt, Insert):
            return await self._insert(stmt)
        raise NotSupported(f"cannot execute {type(stmt).__name__}")

    async def scalar(self, stmt):
        return (await self.execute(stmt)).scalar()

    # ================================================================ flush / commit / rollback

    def _dirty(self):
        out = []
        for inst in self._ident.values():
            if inst._deleted or inst._snap is None:
                continue
            ch = inst._changes()
            if ch:
                out.append((inst, ch))
        return out

    async def _autoflush(self):
        if self._flushing:
            return
        if self._new or self._deleted or self._dirty():
            await self.flush()

    async def flush(self):
        if self._flushing:
            return
        self._flushing = True
        try:
            await self._flush()
        finally:
            self._flushing = False

    async def _flush(self):
        dirty = self._dirty()
        new, self._new = self._new, []
        dele, self._deleted = self._deleted, []
        if not (dirty or new or dele):
            return
        try:
            await self._lock_keys([(type(i).__tablename__, type(i).pk_id(i._pk())) for i, _ in dirty] + [(type(i).__tablename__, type(i).pk_id(i._pk())) for i in dele])
            prepared = []                                           # (instance, stored form)
            new = sorted(new, key=lambda i: type(i).fk_rank())      # parents before children (stable: add order otherwise)
            for inst in new:
                inst._apply_defaults()
                if inst._needs_id():
                    c = type(inst).__pk__[0]
                    inst._data[c.name] = await core.next_id(type(inst).__tablename__)
                for c in type(inst).__pk__:
                    if inst._data.get(c.name) is None:
                        raise DataError(f"{type(inst).__name__}.{c.name} is a primary key and has no value")
                prepared.append((inst, inst._stored()))
            i = 0
            while i < len(prepared):                                # one ordered insert per run of the same collection
                model = type(prepared[i][0])
                j = i
                while j < len(prepared) and type(prepared[j][0]) is model:
                    j += 1
                await self._fk_check_insert(model, [st for _inst, st in prepared[i:j]])
                docs = [inst._doc_from_stored(st) for inst, st in prepared[i:j]]
                await self._apply(Op("insert", model.__tablename__, docs))
                i = j
            for inst, ch in dirty:
                model = type(inst)
                n, _ = await self._apply(Op("update_one", model.__tablename__, model.pk_filter(inst._pk()), {"$set": ch}))
                if n != 1:
                    raise ConcurrencyError(f"{model.__name__} {inst._pk()}: the row to update was not found (deleted by someone else?)")
            for model in {type(i) for i in dele}:
                await self._fk_restrict(model, [model.pk_id(i._pk()) for i in dele if type(i) is model])
            for inst in dele:
                model = type(inst)
                await self._apply(Op("delete_one", model.__tablename__, model.pk_filter(inst._pk())))
        except BaseException:
            # the transaction is already gone (or about to be): nothing this flush wrote stays; pending rows are dropped like SQLAlchemy's rollback would
            await self._abort_txn()
            self._log.clear()
            raise
        for inst, st in prepared:
            inst._snap = copy.deepcopy(st)
            self._ident[(type(inst), inst._pk())] = inst
        for inst, _ch in dirty:
            inst._snap = copy.deepcopy(inst._stored())
        for inst in dele:
            self._ident.pop((type(inst), inst._pk()), None)
            inst._snap = None

    async def commit(self):
        await self.flush()
        await self._finish(commit=True)
        self._release_locks()

    async def rollback(self):
        await self._abort_txn()
        self._log.clear()
        self._new, self._deleted = [], []
        self._fk_known.clear()
        for inst in list(self._ident.values()):
            if inst._snap is not None:                                # back to what the database holds
                inst._deleted = False
                for name, c in inst.__columns__.items():
                    raw = inst._snap.get(name)
                    inst._data[name] = c.type.from_store(raw) if raw is not None else None
        self._release_locks()

    async def close(self):
        """Roll back anything uncommitted and release the locks (a session may be used again afterwards, like SQLAlchemy's)."""
        await self.rollback()

    # ================================================================ referential integrity + the SQLAlchemy idioms Mongo cannot do the same way

    async def _fk_check_insert(self, model, stored_rows):
        """Postgres refused a row whose parent did not exist (a learner deleted a moment ago, a typo'd id); Mongo has no foreign keys, so the same refusal is made here."""
        for col, tbl, tcol in getattr(model, "__fks__", ()):
            target = Base._registry.get(tbl)
            if target is None or len(target.__pk__) != 1 or target.__pk__[0].name != tcol:
                continue
            for v in {st[col.name] for st in stored_rows if st.get(col.name) is not None}:
                if (tbl, v) in self._fk_known:
                    continue

                async def fetch(ms, tbl=tbl, v=v):
                    return await core.coll(tbl).find_one({"_id": v}, {"_id": 1}, session=ms)
                if await self._run(fetch) is None:
                    raise IntegrityError(f"{model.__tablename__}.{col.name}={v!r} references {tbl}.{tcol}, which has no such row")
                self._fk_known.add((tbl, v))

    async def _fk_restrict(self, model, keys):
        """Deleting a parent that still has children is an error (Postgres RESTRICT): a cascade that forgot a table fails loudly instead of leaving orphans."""
        refs = Base.fk_referrers(model.__tablename__)
        if not refs or not keys or len(model.__pk__) != 1:
            return
        vals = [k[0] for k in keys]
        for M, col in refs:
            async def count(ms, M=M, col=col):
                return await core.coll(M.__tablename__).count_documents({col.field: {"$in": vals}}, limit=1, session=ms)
            if await self._run(count):
                raise IntegrityError(f"cannot delete from {model.__tablename__}: {M.__tablename__}.{col.name} still references it")
        for v in vals:
            self._fk_known.discard((model.__tablename__, v))

    async def insert_if_absent(self, inst, key) -> bool:
        """The SQLAlchemy savepoint idiom - `try: async with s.begin_nested(): s.add(x); await s.flush()  except IntegrityError: <take the winner's row>` - for a UNIQUE key:
        insert `inst` unless a row with the same `key` columns exists. True = inserted (`inst` is persistent in this session); False = a row exists (`inst` is left alone and not added).
        An atomic upsert, so a duplicate never aborts the transaction (a Mongo transaction has no savepoints)."""
        model = type(inst)
        await self._autoflush()
        inst._apply_defaults()
        if inst._needs_id():
            inst._data[model.__pk__[0].name] = await core.next_id(model.__tablename__)
        for c in model.__pk__:
            if inst._data.get(c.name) is None:
                raise DataError(f"{model.__name__}.{c.name} is a primary key and has no value")
        stored = inst._stored()
        filt = {model.__columns__[k].field: stored[k] for k in key}
        if any(v is None for v in filt.values()):
            raise DataError("insert_if_absent: the key columns must all have a value")
        await self._fk_check_insert(model, [stored])
        doc = inst._doc_from_stored(stored)
        n, upserted = await self._apply(Op("upsert", model.__tablename__, filt, {"$setOnInsert": {k: v for k, v in doc.items() if k not in filt}}))
        if upserted is None:
            return False
        inst._snap = copy.deepcopy(stored)
        inst._deleted = False
        self._ident[(model, inst._pk())] = inst
        return True

    async def advisory_lock(self, key: str):
        """pg_advisory_xact_lock(hashtext(key)): a named lock held to the end of the session (serialises a check-then-insert that has no row to lock yet)."""
        await self._lock_keys([("advisory", (key,))])

    # ================================================================ SELECT

    @staticmethod
    def _model_of(st: Select):
        if st._from is not None:
            return st._from
        def first_model(e):
            if isinstance(e, type) and issubclass(e, Base):
                return e
            if isinstance(e, ColumnOps):
                return e.model
            if isinstance(e, FuncCall):
                for a in e.args:
                    m = first_model(a)
                    if m is not None:
                        return m
            return None
        for e in st.entities:
            m = first_model(e)
            if m is not None:
                return m
        raise NotSupported("select() without an entity: add select_from(Model)")

    async def _resolve(self, node):
        """`col IN (SELECT ...)`: run the inner select and put its values in the list (NULLs drop out, as in SQL)."""
        if isinstance(node, InList) and node.sub is not None:
            return InList(node.col, (await self.execute(node.sub)).scalars().all())
        if isinstance(node, (And, Or)):
            return type(node)([await self._resolve(p) for p in node.parts])
        return node

    async def _filter(self, conds) -> dict:
        return to_filter(and_(*[await self._resolve(c) for c in conds]))

    async def _select(self, st: Select) -> Result:
        model = self._model_of(st)
        flt = await self._filter(st._where)
        await self._autoflush()
        if st._group or any(isinstance(e, FuncCall) for e in st.entities):
            return await self._aggregate(st, model, flt)

        ents = st.entities
        as_entity = len(ents) == 1 and isinstance(ents[0], type) and issubclass(ents[0], Base)
        if not as_entity:
            for e in ents:
                if not isinstance(e, ColumnOps) or e.model is not model:
                    raise NotSupported("select(): columns of ONE model, or one whole model")
        order = st._order
        push = pushdown_sort(order) if order else None
        projection = None if (as_entity or (order and push is None)) else {c.field: 1 for c in ents}      # a sort done here needs the sort keys, so fetch whole documents then
        coll_name = model.__tablename__
        off, lim = st._offset or 0, st._limit
        populate = bool(st._opts.get("populate_existing")) or bool(st._for_update)

        async def fetch(ms):
            cur = core.coll(coll_name).find(flt, projection, session=ms)
            if order and push is not None:
                cur = cur.sort(push if any(f == "_id" for f, _ in push) else push + [("_id", 1)])     # the tie-break must not repeat a key already sorted on
                if off:
                    cur = cur.skip(off)
                if lim is not None:
                    cur = cur.limit(lim)
                return await cur.to_list(None)
            if order:                                                   # Postgres NULL placement, or an expression: sort here (the data is small)
                docs = sort_docs(await cur.sort([("_id", 1)]).to_list(None), order)
                return docs[off: off + lim] if lim is not None else docs[off:]
            if lim is not None or off:
                cur = cur.sort([("_id", 1)])
                if off:
                    cur = cur.skip(off)
                if lim is not None:
                    cur = cur.limit(lim)
            return await cur.to_list(None)

        if st._for_update:
            locked: set = set()
            docs = []
            for _ in range(6):
                docs = await self._run(fetch)
                new = [self._key(model, d) for d in docs if self._key(model, d) not in locked]
                if not new:
                    break
                await self._lock_keys(new)
                locked.update(new)
        else:
            docs = await self._run(fetch)
        if st._distinct and not as_entity:
            seen, uniq = set(), []
            for d in docs:
                k = tuple(repr(d.get(c.field)) for c in ents)
                if k not in seen:
                    seen.add(k)
                    uniq.append(d)
            docs = uniq
        if as_entity:
            return Result([Row((model.__name__,), (self._instance(model, d, populate),)) for d in docs])
        fields = [c.name for c in ents]
        rows = []
        for d in docs:
            vals = []
            for c in ents:
                raw = d.get(c.field)
                vals.append(c.type.from_store(raw) if raw is not None else None)
            rows.append(Row(fields, vals))
        return Result(rows)

    # ---------------------------------------------------------------- aggregates / group_by

    async def _aggregate(self, st: Select, model, flt) -> Result:
        if st._order or st._limit is not None or st._offset or st._for_update:
            raise NotSupported("order_by / limit / offset / FOR UPDATE with aggregates is not supported")
        groups = list(st._group)
        for g in groups:
            if not isinstance(g, ColumnOps):
                raise NotSupported("group_by() takes columns")
        accs: dict[str, tuple] = {}

        def plan(e):
            """-> function(group row) -> value; registers the accumulators it needs."""
            if isinstance(e, FuncCall):
                if e.name == "coalesce":
                    parts = [plan(a) for a in e.args]
                    return lambda g: next((v for v in (p(g) for p in parts) if v is not None), None)
                if e.name == "count":
                    if not e.args:
                        acc = ("count_all", None, None)
                    elif isinstance(e.args[0], FuncCall) and e.args[0].name == "distinct":
                        acc = ("count_distinct", e.args[0].args[0].field, None)
                    else:
                        acc = ("count", e.args[0].field, None)
                elif e.name in ("sum", "min", "max", "avg") and len(e.args) == 1 and isinstance(e.args[0], ColumnOps):
                    acc = (e.name, e.args[0].field, e.args[0])
                else:
                    raise NotSupported(f"func.{e.name}(...) is not supported")
                name = f"a{len(accs)}"
                accs[name] = acc
                if acc[0] == "sum":                                          # SQL: SUM of only NULLs is NULL; Mongo's $sum says 0 - count the non-NULLs alongside
                    accs[name + "n"] = ("count", acc[1], None)

                def get(g, name=name, acc=acc):
                    v = g.get(name)
                    if acc[0] == "count_distinct":
                        return len({x for x in (v or []) if x is not None})
                    if acc[0] == "sum" and not g.get(name + "n"):
                        return None
                    if acc[0] in ("min", "max") and v is not None:
                        return acc[2].type.from_store(v)
                    return v
                return get
            if isinstance(e, ColumnOps):
                idx = next((i for i, g in enumerate(groups) if g is e), None)           # identity: `==` on a column builds an expression, which is always truthy
                if idx is None:
                    raise NotSupported(f"{e.name} must appear in group_by()")
                return lambda g, idx=idx, c=e: (c.type.from_store(g["_id"][f"k{idx}"]) if g["_id"][f"k{idx}"] is not None else None)
            if isinstance(e, (int, float, str)) or e is None:
                return lambda g, v=e: v
            raise NotSupported(f"cannot select {type(e).__name__} next to aggregates")

        getters = [plan(e) for e in st.entities]
        fields = [getattr(e, "name", None) or (e.name if isinstance(e, FuncCall) else f"col{i}") for i, e in enumerate(st.entities)]
        coll_name = model.__tablename__

        if not groups and len(accs) == 1 and next(iter(accs.values()))[0] == "count_all" and len(st.entities) == 1:
            async def count(ms):
                return await core.coll(coll_name).count_documents(flt, session=ms)
            return Result([Row(fields, [await self._run(count)])])

        grp: dict[str, Any] = {"_id": ({f"k{i}": "$" + g.field for i, g in enumerate(groups)} if groups else None)}
        for name, (kind, field, _col) in accs.items():
            f = "$" + field if field else None
            grp[name] = {"count_all": {"$sum": 1},
                         "count": {"$sum": {"$cond": [{"$in": [{"$type": f}, ["null", "missing"]]}, 0, 1]}} if f else None,
                         "count_distinct": {"$addToSet": f},
                         "sum": {"$sum": f}, "min": {"$min": f}, "max": {"$max": f}, "avg": {"$avg": f}}[kind]
        pipeline = [{"$match": flt}, {"$group": grp}]

        async def agg(ms):
            return await (await core.coll(coll_name).aggregate(pipeline, session=ms)).to_list(None)
        docs = await self._run(agg)
        if not groups and not docs:                                     # SQL: an aggregate over no rows is one row (count 0, the rest NULL)
            docs = [{"_id": None, **{n: (0 if k[0] in ("count_all", "count") else [] if k[0] == "count_distinct" else None) for n, k in accs.items()}}]
        return Result([Row(fields, [g(d) for g in getters]) for d in docs])

    # ================================================================ UPDATE / DELETE / INSERT

    def _sync_loaded(self, model, ids: set, set_doc: dict, inc_doc: dict):
        """SQLAlchemy's synchronize_session: instances already loaded reflect a bulk UPDATE."""
        by_field = {c.field: c for c in model.__columns__.values()}
        for key, inst in self._ident.items():
            if key[0] is not model or inst._deleted or inst._snap is None:
                continue
            if tuple(model.pk_filter(inst._pk()).values()) not in ids:
                continue
            for f, v in set_doc.items():
                c = by_field[f]
                inst._data[c.name] = c.type.from_store(v) if v is not None else None
                inst._snap[c.name] = copy.deepcopy(v)
            for f, n in inc_doc.items():
                c = by_field[f]
                cur = (inst._data.get(c.name) or 0) + n
                inst._data[c.name] = cur
                inst._snap[c.name] = c.type.to_store(cur)

    @staticmethod
    def _split_values(model, values: dict):
        set_doc, inc_doc = {}, {}
        for name, v in values.items():
            c = model.__columns__[name]
            if isinstance(v, Arith):
                if v.col is not c:
                    raise NotSupported("a column may only be incremented from itself")
                inc_doc[c.field] = v.n if v.op == "+" else -v.n
            elif isinstance(v, (ColumnOps, FuncCall)):
                raise NotSupported("UPDATE ... SET col = <expression> is limited to `col + n` / `col - n` and literals")
            else:
                set_doc[c.field] = c.type.to_store(v)
        return set_doc, inc_doc

    async def _matching_ids(self, model, flt):
        async def fetch(ms):
            return await core.coll(model.__tablename__).find(flt, {"_id": 1, **{c.field: 1 for c in model.__pk__}}, session=ms).to_list(None)
        docs = await self._run(fetch)
        return [self._key(model, d)[1] for d in docs]

    async def _update(self, st: Update) -> Result:
        model = st.model
        flt = await self._filter(st._where)
        set_doc, inc_doc = self._split_values(model, st._values)
        await self._autoflush()
        upd = {}
        if set_doc:
            upd["$set"] = set_doc
        if inc_doc:
            upd["$inc"] = inc_doc
        if not upd:
            return Result([], 0)
        ids = await self._matching_ids(model, flt)
        await self._lock_keys([(model.__tablename__, i) for i in ids])
        if st._returning:
            return await self._update_returning(st, model, flt, upd, set_doc, inc_doc)
        n, _ = await self._apply(Op("update_many", model.__tablename__, {"$and": [flt, self._ids_filter(model, ids)]} if flt else self._ids_filter(model, ids), upd))
        self._sync_loaded(model, set(ids), set_doc, inc_doc)
        return Result([], n)

    @staticmethod
    def _ids_filter(model, ids):
        if len(model.__pk__) == 1:
            return {"_id": {"$in": [i[0] for i in ids]}}
        return {"$or": [{c.field: v for c, v in zip(model.__pk__, i)} for i in ids]} if ids else {"_id": {"$in": []}}

    async def _update_returning(self, st, model, flt, upd, set_doc, inc_doc) -> Result:
        """UPDATE ... RETURNING cols - used as an exactly-once claim, so one row at a time and atomic."""
        rows, n = [], 0
        for col in st._returning:
            if not isinstance(col, ColumnOps) or col.model is not model:
                raise NotSupported("returning(): columns of the updated model")
        while True:
            async def go(ms):
                return await core.coll(model.__tablename__).find_one_and_update(flt, upd, return_document=ReturnDocument.AFTER, sort=[("_id", 1)], session=ms)
            doc = await self._run(go, write=True)
            if doc is None:
                break
            n += 1
            self._log.append(Op("update_one", model.__tablename__, {"_id": doc["_id"]} if len(model.__pk__) == 1 else {c.field: doc[c.field] for c in model.__pk__}, upd, expect=1))
            self._sync_loaded(model, {self._key(model, doc)[1]}, set_doc, inc_doc)
            rows.append(Row([c.name for c in st._returning], [c.type.from_store(doc.get(c.field)) if doc.get(c.field) is not None else None for c in st._returning]))
        return Result(rows, n)

    async def _delete(self, st: Delete) -> Result:
        model = st.model
        flt = await self._filter(st._where)
        await self._autoflush()
        ids = await self._matching_ids(model, flt)
        await self._lock_keys([(model.__tablename__, i) for i in ids])
        await self._fk_restrict(model, ids)
        n = 0
        if ids:
            n, _ = await self._apply(Op("delete_many", model.__tablename__, {"$and": [flt, self._ids_filter(model, ids)]} if flt else self._ids_filter(model, ids)))
        gone = set(ids)
        for key, inst in list(self._ident.items()):
            if key[0] is model and tuple(model.pk_filter(inst._pk()).values()) in gone:
                inst._deleted = True
                inst._snap = None
                self._ident.pop(key, None)
        return Result([], n)

    async def _insert(self, st: Insert) -> Result:
        model = st.model
        await self._autoflush()
        inst = model(**st._values)
        inst._apply_defaults()
        if inst._needs_id():
            inst._data[model.__pk__[0].name] = await core.next_id(model.__tablename__)
        for c in model.__pk__:
            if inst._data.get(c.name) is None:
                raise DataError(f"{model.__name__}.{c.name} is a primary key and has no value")
        stored = inst._stored()
        doc = inst._doc_from_stored(stored)
        await self._fk_check_insert(model, [stored])
        if st._conflict is None:
            await self._apply(Op("insert", model.__tablename__, [doc]))
            inst._snap = copy.deepcopy(stored)
            return Result([Row([c.name for c in st._returning], [inst._data.get(c.name) for c in st._returning])] if st._returning else [], 1)

        mode, elements, *rest = st._conflict
        if elements:
            cols = [model.__columns__[e] for e in elements]
        else:
            cols = list(model.__pk__)
        filt = {c.field: stored[c.name] for c in cols}
        if any(v is None for v in filt.values()):                      # a NULL never conflicts (a partial unique index skips it): plain insert
            await self._apply(Op("insert", model.__tablename__, [doc]))
            return Result([Row([c.name for c in st._returning], [inst._data.get(c.name) for c in st._returning])] if st._returning else [], 1)
        on_insert = {k: v for k, v in doc.items() if k not in filt}
        update: dict[str, Any] = {}
        if mode == "update":
            set_doc, inc_doc = self._split_values(model, rest[0])
            for k in list(on_insert):
                if k in set_doc or k in inc_doc:
                    del on_insert[k]
            if set_doc:
                update["$set"] = set_doc
            if inc_doc:
                update["$inc"] = inc_doc
        if on_insert:
            update["$setOnInsert"] = on_insert
        if not update:
            update = {"$setOnInsert": {}}
        n, upserted = await self._apply(Op("upsert", model.__tablename__, filt, update))
        inserted = upserted is not None
        if mode == "nothing":
            return Result([Row([c.name for c in st._returning], [inst._data.get(c.name) for c in st._returning])] if (st._returning and inserted) else [], 1 if inserted else 0)
        return Result([], 1)


async def _noop():
    return None


class SessionFactory:
    """`_Session = SessionFactory()` ; `async with _Session() as s:` - stands where `async_sessionmaker(engine, expire_on_commit=False)` stood."""

    def __call__(self) -> Session:
        return Session(self)


async_sessionmaker = SessionFactory


# ---------------------------------------------------------------- an atomic claim, outside any session (the replacement for FOR UPDATE SKIP LOCKED)

async def claim_one(model, where: list, values: dict, *, sort=None):
    """Atomically take ONE row matching `where` and apply `values` (a find_one_and_update): two claimers can never get the same row, in or out of this process. Returns a detached
    instance holding the row AFTER the update, or None when nothing matched. `sort` is a Mongo sort spec, e.g. [("fire_at", 1)]."""
    flt = to_filter(and_(*where))
    set_doc, inc_doc = Session._split_values(model, values)
    upd = {}
    if set_doc:
        upd["$set"] = set_doc
    if inc_doc:
        upd["$inc"] = inc_doc
    try:
        doc = await core.coll(model.__tablename__).find_one_and_update(flt, upd, sort=(sort or [("_id", 1)]), return_document=ReturnDocument.AFTER)
    except PyMongoError as e:
        raise _wrap(e) from e
    if doc is None:
        return None
    inst = model.__new__(model)
    inst._deleted = False
    inst._load(doc)
    return inst
