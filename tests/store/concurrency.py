"""Locks, races, conflicts, atomicity - what Postgres row locks and transactions gave, on Mongo. tests/store/run.sh concurrency.py"""

import time

from _h import *                                                            # noqa: F401,F403
from _h import (TDay, TItem, TUser, Sess, now, ok, raises, reset, run, section, wipe)
from app.store import core, claim_one, insert, select, update, func
from app.store.errors import ConcurrencyError, IntegrityError, LockTimeout


async def bump(uid, n=1, locked=True):
    async with Sess() as s:
        u = await s.get(TUser, uid, with_for_update=locked)
        cur = u.score
        await asyncio.sleep(0.005)                                      # a window in which an unlocked reader would lose an update
        u.score = cur + n
        await s.commit()


async def main():
    await reset()

    section("row locks: a locked read-modify-write loses nothing")
    async with Sess() as s:
        s.add(TUser(id="c"))
        await s.commit()
    await asyncio.gather(*[bump("c") for _ in range(12)])
    ok("12 concurrent locked increments -> exactly 12", (await store.core.coll("t_users").find_one({"_id": "c"}))["score"] == 12)
    ok("every lock was released", core.LOCKS.held() == 0)

    section("unlocked read-modify-write: last writer wins, like Postgres - but nobody gets an error")
    async with Sess() as s:
        s.add(TUser(id="d"))
        await s.commit()
    core.STATS.update(txn_retries=0, replays=0)
    res = await asyncio.gather(*[bump("d", locked=False) for _ in range(12)], return_exceptions=True)
    ok("in-process contention never needs the safety nets: the flush locks serialise the writers (0 write-conflict retries)", core.STATS["txn_retries"] == 0, str(core.STATS))
    ok("12 concurrent UNlocked increments raise nothing", all(not isinstance(r, BaseException) for r in res), str([r for r in res if isinstance(r, BaseException)][:2]))
    v = (await store.core.coll("t_users").find_one({"_id": "d"}))["score"]
    ok("and the count is somewhere in 1..12 (lost updates are the Postgres behaviour without FOR UPDATE)", 1 <= v <= 12, str(v))

    section("the other ways to lock: a locked SELECT and a bulk UPDATE")
    async with Sess() as s:
        s.add(TUser(id="e"))
        s.add(TUser(id="f"))
        await s.commit()

    async def bump_select(uid):
        async with Sess() as s:
            u = (await s.execute(select(TUser).where(TUser.id == uid).with_for_update())).scalars().first()
            cur = u.score
            await asyncio.sleep(0.005)
            u.score = cur + 1
            await s.commit()
    await asyncio.gather(*[bump_select("e") for _ in range(12)])
    ok("12 concurrent `select ... with_for_update()` read-modify-writes -> exactly 12", (await store.core.coll("t_users").find_one({"_id": "e"}))["score"] == 12)

    async def bump_bulk(uid):
        async with Sess() as s:
            await s.execute(update(TUser).where(TUser.id == uid).values(score=TUser.score + 1))
            await asyncio.sleep(0.005)
            await s.commit()
    core.STATS.update(txn_retries=0, replays=0)
    await asyncio.gather(*[bump_bulk("f") for _ in range(12)])
    ok("12 concurrent bulk `update ... set score = score + 1` -> exactly 12 and no write-conflict retries (the bulk update locks its rows)",
       (await store.core.coll("t_users").find_one({"_id": "f"}))["score"] == 12 and core.STATS["txn_retries"] == 0, str(core.STATS))

    section("lock waits, timeouts, deadlocks")
    async with Sess() as a, Sess() as b:
        await a.get(TUser, "c", with_for_update=True)
        keep = core.LOCK_TIMEOUT
        core.LOCK_TIMEOUT = 0.3
        try:
            t0 = time.monotonic()
            err = await raises(LockTimeout, lambda: b.get(TUser, "c", with_for_update=True))
            ok("a second session waiting for a held lock gets LockTimeout after the timeout", err is not None and 0.25 < time.monotonic() - t0 < 2.0)
        finally:
            core.LOCK_TIMEOUT = keep
        await a.commit()
        u = await b.get(TUser, "c", with_for_update=True)
        ok("after the holder commits the waiter gets the row", u is not None and u.id == "c")
        await b.commit()
    ok("locks are all released", core.LOCKS.held() == 0)

    async with Sess() as s:
        s.add(TUser(id="x1"))
        s.add(TUser(id="x2"))
        await s.commit()
    keep = core.LOCK_TIMEOUT
    core.LOCK_TIMEOUT = 0.6

    async def opposite(first, second, hold=0.15):
        async with Sess() as s:
            await s.get(TUser, first, with_for_update=True)
            await asyncio.sleep(hold)
            await s.get(TUser, second, with_for_update=True)
            await s.commit()
    t0 = time.monotonic()
    res = await asyncio.gather(opposite("x1", "x2"), opposite("x2", "x1"), return_exceptions=True)
    core.LOCK_TIMEOUT = keep
    errs = [r for r in res if isinstance(r, BaseException)]
    ok("opposite lock order: a real deadlock breaks by timeout (loud, no hang), at least one side finishes", len(errs) >= 1 and all(isinstance(e, LockTimeout) for e in errs) and len(errs) <= 2 and time.monotonic() - t0 < 5)
    ok("a deadlock leaves no lock behind", core.LOCKS.held() == 0)
    async with Sess() as s:
        rows = (await s.execute(select(TUser).where(TUser.id.in_(["x1", "x2"])).order_by(TUser.id).with_for_update())).scalars().all()
        ok("a locked multi-row select locks rows in sorted order (the safe way)", [r.id for r in rows] == ["x1", "x2"])
        await s.commit()
    res = await asyncio.gather(*[_locked_pair(["x1", "x2"] if i % 2 else ["x2", "x1"]) for i in range(10)], return_exceptions=True)
    ok("10 sessions locking the same two rows through one select never deadlock", all(not isinstance(r, BaseException) for r in res), str([r for r in res if isinstance(r, BaseException)][:1]))

    section("a session that ends badly releases its locks")
    try:
        async with Sess() as s:
            await s.get(TUser, "c", with_for_update=True)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    ok("an exception releases the locks", core.LOCKS.held() == 0)

    async def hold_forever():
        async with Sess() as s:
            await s.get(TUser, "c", with_for_update=True)
            await asyncio.sleep(30)
    t = asyncio.create_task(hold_forever())
    await asyncio.sleep(0.2)
    ok("a task holding a lock", core.LOCKS.held() == 1)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    ok("cancelling the task releases its lock", core.LOCKS.held() == 0)

    section("racing creators: the unique index decides, exactly one wins")
    await wipe()
    await store.init()
    async with Sess() as s:
        s.add(TUser(id="r"))
        await s.commit()

    async def create(key):
        async with Sess() as s:
            s.add(TItem(user_id="r", client_key=key))
            await s.commit()
    res = await asyncio.gather(*[create("same") for _ in range(12)], return_exceptions=True)
    wins = [r for r in res if not isinstance(r, BaseException)]
    ok("12 racing inserts of one (user, client_key): exactly one succeeds, the rest IntegrityError", len(wins) == 1 and all(isinstance(r, IntegrityError) for r in res if isinstance(r, BaseException)),
       str([type(r).__name__ for r in res]))
    ok("one row", await store.core.coll("t_items").count_documents({"client_key": "same"}) == 1)

    async def create_or_ignore(key):
        async with Sess() as s:
            r = await s.execute(insert(TItem).values(user_id="r", client_key=key).on_conflict_do_nothing(index_elements=["user_id", "client_key"]).returning(TItem.id))
            got = r.scalar()
            await s.commit()
            return got
    res = await asyncio.gather(*[create_or_ignore("again") for _ in range(12)], return_exceptions=True)
    ok("12 racing `on conflict do nothing` inserts: no errors, exactly one row inserted", all(not isinstance(r, BaseException) for r in res) and sum(1 for r in res if r is not None) == 1
       and await store.core.coll("t_items").count_documents({"client_key": "again"}) == 1, str(res))

    async def race_if_absent(key):
        async with Sess() as s:
            won = await s.insert_if_absent(TItem(user_id="r", client_key=key, n=1), ["user_id", "client_key"])
            await s.commit()
            return won
    res = await asyncio.gather(*[race_if_absent("absent") for _ in range(12)], return_exceptions=True)
    ok("12 racing insert_if_absent calls: no errors, exactly one wins, one row", all(not isinstance(r, BaseException) for r in res) and sum(1 for r in res if r is True) == 1
       and await store.core.coll("t_items").count_documents({"client_key": "absent"}) == 1, str(res))

    order = []

    async def with_advisory(tag):
        async with Sess() as s:
            await s.advisory_lock("plrr:someone")
            order.append(("in", tag))
            await asyncio.sleep(0.05)
            order.append(("out", tag))
            await s.commit()
    await asyncio.gather(*[with_advisory(i) for i in range(5)])
    ok("advisory_lock serialises sessions on a name: never two inside at once", all(order[i][0] == "in" and order[i + 1][0] == "out" and order[i][1] == order[i + 1][1] for i in range(0, len(order), 2)), str(order))

    async def bump_day(day):
        async with Sess() as s:
            st = insert(TDay).values(user_id="r", day=day, requests=1)
            await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded.requests}))
            await s.commit()
    res = await asyncio.gather(*[bump_day("d") for _ in range(20)], return_exceptions=True)
    ok("20 racing upsert-increments: no error and the count is exactly 20 (atomic $inc)", all(not isinstance(r, BaseException) for r in res)
       and (await store.core.coll("t_days").find_one({"user_id": "r", "day": "d"}))["requests"] == 20, str([r for r in res if isinstance(r, BaseException)][:1]))

    section("atomic claims: two claimers never get the same row")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="q"))
        for i in range(30):
            s.add(TItem(user_id="q", n=i, status="scheduled"))
        await s.commit()

    async def claim():
        return await claim_one(TItem, [TItem.status == "scheduled"], {"status": "sending"}, sort=[("n", 1)])
    got = await asyncio.gather(*[claim() for _ in range(40)])
    taken = [g.n for g in got if g is not None]
    ok("40 concurrent claimers over 30 rows: each row exactly once, 10 get nothing", sorted(taken) == list(range(30)) and sum(1 for g in got if g is None) == 10)

    section("a transaction is all-or-nothing")
    await wipe()
    await store.init()
    async with Sess() as s:
        s.add(TUser(id="t"))
        s.add(TItem(user_id="t", client_key="k"))
        await s.commit()
    async with Sess() as s:
        s.add(TItem(user_id="t", client_key="new1"))
        s.add(TItem(user_id="t", client_key="new2"))
        s.add(TItem(user_id="t", client_key="k"))                       # the duplicate
        err = await raises(IntegrityError, s.commit)
        await s.rollback()
    ok("a duplicate in the third row rolls the first two back", err is not None and await store.core.coll("t_items").count_documents({"user_id": "t"}) == 1)

    async def award(i, fail=False):
        async with Sess() as s:
            u = await s.get(TUser, "t", with_for_update=True)
            u.score = u.score + 10
            s.add(TItem(user_id="t", label=f"a{i}"))
            await s.flush()
            if fail:
                raise RuntimeError("the second half failed")
            await s.commit()
    res = await asyncio.gather(*[award(i, fail=(i % 4 == 0)) for i in range(12)], return_exceptions=True)
    done = sum(1 for r in res if not isinstance(r, BaseException))
    u = await store.core.coll("t_users").find_one({"_id": "t"})
    n_items = await store.core.coll("t_items").count_documents({"label": {"$regex": "^a"}})
    ok("12 'award' sessions, 3 fail midway: score and rows reflect exactly the 9 that finished (the failed ones left nothing)", done == 9 and u["score"] == 90 and n_items == 9, f"done={done} score={u['score']} rows={n_items}")

    section("a write conflict with a transaction outside the lock registry: wait, replay, succeed")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="w", name="orig"))
        await s.commit()
    raw = core.client().start_session()
    await raw.start_transaction()
    await core.coll("t_users").update_one({"_id": "w"}, {"$set": {"score": 41}}, session=raw)

    async def writer():
        async with Sess() as s:
            u = await s.get(TUser, "w")
            u.name = "by-store"
            await s.commit()
    task = asyncio.create_task(writer())
    await asyncio.sleep(0.4)
    ok("while the other transaction holds the document, the store session is still retrying (not failed, not done)", not task.done())
    await raw.commit_transaction()
    await raw.end_session()
    await asyncio.wait_for(task, 10)
    row = await core.coll("t_users").find_one({"_id": "w"})
    ok("after the other commits, the store write lands too (WriteConflict was retried, nothing lost)", row["name"] == "by-store" and row["score"] == 41, str(row))

    section("a replay that no longer reproduces what the body saw fails loudly")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="v", name="orig"))
        s.add(TUser(id="p", name="orig"))
        s.add(TUser(id="other"))
        await s.commit()

    async def gap_session(target, hold):
        """Writes `target`, then needs the lock `hold` (held by someone else): its transaction is aborted while it waits, and replayed when it gets the lock."""
        async with Sess() as s:
            row = await s.get(TUser, target)
            row.name = "mine"
            await s.flush()
            await s.get(TUser, "other", with_for_update=True)
            await s.commit()

    holder = Sess()
    await holder.get(TUser, "other", with_for_update=True)
    task = asyncio.create_task(gap_session("v", "other"))
    await asyncio.sleep(0.4)
    ok("the session is waiting for the lock (its transaction is aborted meanwhile, nothing holds the row)", not task.done())
    await core.coll("t_users").delete_one({"_id": "v"})                       # the row vanishes in the gap, outside every lock - and nothing blocks
    await holder.commit()
    res = (await asyncio.gather(task, return_exceptions=True))[0]
    ok("replaying an UPDATE of a row that vanished -> ConcurrencyError (the replay one, not a lock timeout), never a silent wrong write",
       type(res) is ConcurrencyError and "replay" in str(res), repr(res))
    ok("and nothing was resurrected", await core.coll("t_users").find_one({"_id": "v"}) is None)
    ok("every lock was released", core.LOCKS.held() == 0)

    holder = Sess()
    await holder.get(TUser, "other", with_for_update=True)
    task = asyncio.create_task(gap_session("p", "other"))
    await asyncio.sleep(0.4)
    await core.coll("t_users").update_one({"_id": "p"}, {"$set": {"score": 5}})        # a harmless change in the gap
    await holder.commit()
    res = (await asyncio.gather(task, return_exceptions=True))[0]
    row = await core.coll("t_users").find_one({"_id": "p"})
    ok("a replay after a harmless change in the gap succeeds and keeps both writes", res is None and row["name"] == "mine" and row["score"] == 5, f"{res!r} {row}")

    section("a new lock mid-session: the earlier writes survive the abort-and-replay")
    await wipe()
    async with Sess() as s:
        for i in ("m1", "m2", "m3"):
            s.add(TUser(id=i))
        await s.commit()
    async with Sess() as s:
        a = await s.get(TUser, "m1")
        a.score = 1
        await s.flush()
        b = await s.get(TUser, "m2", with_for_update=True)
        b.score = 2
        await s.flush()
        c = await s.get(TUser, "m3", with_for_update=True)
        c.score = 3
        s.add(TItem(user_id="m1", label="made"))
        await s.commit()
    rows = {d["_id"]: d["score"] for d in await core.coll("t_users").find({}).to_list(None)}
    ok("three writes, two mid-session locks: all three landed, once", rows == {"m1": 1, "m2": 2, "m3": 3} and await core.coll("t_items").count_documents({"label": "made"}) == 1)

    section("reads see the latest committed state until the session writes")
    async with Sess() as r, Sess() as w:
        u = await r.get(TUser, "m1", populate_existing=True)
        before = u.score
        wu = await w.get(TUser, "m1", with_for_update=True)
        wu.score = 100
        await w.commit()
        ok("a reader that has not written sees another session's commit on its next read", (await r.execute(select(TUser.score).where(TUser.id == "m1"))).scalar() == 100 and before == 1)

    section("throughput (information only)")
    t0 = time.monotonic()
    for i in range(100):
        async with Sess() as s:
            s.add(TItem(user_id="m1", n=i))
            await s.commit()
    dt_ = time.monotonic() - t0
    print(f"  100 sequential one-row write sessions: {dt_:.2f}s ({dt_ * 10:.1f} ms each)")
    ok("a write session is not absurdly slow (< 250 ms each on a scratch Mongo)", dt_ < 25)
    t0 = time.monotonic()
    await asyncio.gather(*[_one_write(i) for i in range(100)])
    print(f"  100 concurrent one-row write sessions: {time.monotonic() - t0:.2f}s")
    ok("100 concurrent write sessions all succeed", await core.coll("t_items").count_documents({"user_id": "m2"}) == 100)


async def _locked_pair(ids):
    async with Sess() as s:
        rows = (await s.execute(select(TUser).where(TUser.id.in_(ids)).order_by(TUser.id.desc() if ids[0] > ids[1] else TUser.id).with_for_update())).scalars().all()
        await asyncio.sleep(0.01)
        await s.commit()
        return len(rows)


async def _one_write(i):
    async with Sess() as s:
        s.add(TItem(user_id="m2", n=i))
        await s.commit()


run(main)
