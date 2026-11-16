"""Does the SHARED Mongo (rooted-mongo, as DuSu's scoped user) behave the way app/store assumes?

Owner-run / agent-run once, and again after any change to the shared server (a Mongo upgrade, a role change). It touches ONE throwaway collection family
(`_store_probe_<random>_*`) inside the `dusu` database and drops it at the end; it never reads or writes any other database.

  docker run --rm --network rooted-shared-net --env-file ~/Desktop/RootEd_ALL/shared-services/creds/dusu-prod.env \
      -v "$PWD/tests":/tests dusu-mongo-test python /tests/store/probe_shared_mongo.py

The URI comes from MONGODB_URI in the environment and is never printed.
"""

import asyncio
import datetime as dt
import os
import secrets
import sys

from pymongo import AsyncMongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

URI = os.environ["MONGODB_URI"]
TAG = "_store_probe_" + secrets.token_hex(4)
fails = 0


def ok(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails += 1


async def main():
    client = AsyncMongoClient(URI, tz_aware=True, serverSelectionTimeoutMS=8000)
    db = client.get_default_database()
    print("database:", db.name)
    ok("the URI names the dusu database", db.name == "dusu")

    hello = await client.admin.command("hello")
    ok("connected to a writable replica-set primary", bool(hello.get("isWritablePrimary")) and bool(hello.get("setName")), str({k: hello.get(k) for k in ("setName", "isWritablePrimary")}))
    bi = await client.admin.command("buildInfo")
    print("server version:", bi.get("version"))

    # --- who can this user see?
    try:
        names = await client.list_database_names()
        ok("the scoped user sees no other database", names == ["dusu"] or names == [], str(names))
    except OperationFailure as e:
        ok("listDatabases is refused for the scoped user (so no other database is visible)", e.code in (13, 8000), f"code {e.code}")
    try:
        await client.get_database("admin").command("listCollections")
        ok("admin database is NOT readable", False)
    except OperationFailure as e:
        ok("admin database is not readable", e.code in (13, 8000), f"code {e.code}")
    try:
        await client.get_database("rooted").list_collection_names()
        ok("RootEd's database is NOT readable", False)
    except OperationFailure as e:
        ok("RootEd's database is not readable", e.code in (13, 8000), f"code {e.code}")

    a, b, ctr, q = db[TAG + "_a"], db[TAG + "_b"], db[TAG + "_ctr"], db[TAG + "_q"]
    try:
        # --- indexes the models need
        await a.create_index([("user_id", ASCENDING), ("client_key", ASCENDING)], unique=True, name="uq_client",
                             partialFilterExpression={"client_key": {"$type": "string"}})
        await a.create_index([("fire_at", ASCENDING)], name="ix_due", partialFilterExpression={"status": "scheduled"})
        await a.create_index([("parent_id", ASCENDING), ("occ_date", ASCENDING)], unique=True, name="uq_occ",
                             partialFilterExpression={"parent_id": {"$type": "number"}})
        ok("partial indexes ($type string, $eq, $type number) can be created", True)

        await a.insert_one({"user_id": "u1", "client_key": None})
        await a.insert_one({"user_id": "u1", "client_key": None})
        await a.insert_one({"user_id": "u1"})
        ok("a partial unique index lets many NULL / missing keys through (Postgres semantics)", await a.count_documents({"user_id": "u1"}) == 3)
        await a.insert_one({"user_id": "u1", "client_key": "k"})
        try:
            await a.insert_one({"user_id": "u1", "client_key": "k"})
            ok("a duplicate string key is refused", False)
        except DuplicateKeyError:
            ok("a duplicate string key is refused (DuplicateKeyError)", True)
        await a.insert_one({"user_id": "u2", "client_key": "k"})
        ok("the same key for another user is fine", True)

        await a.insert_one({"parent_id": 5, "occ_date": "2026-11-16"})
        try:
            await a.insert_one({"parent_id": 5, "occ_date": "2026-11-16"})
            ok("unique on an int parent id is enforced", False)
        except DuplicateKeyError:
            ok("unique on (parent_id, occ_date) with $type number is enforced", True)
        await a.insert_one({"parent_id": None, "occ_date": "2026-11-16"})
        await a.insert_one({"parent_id": None, "occ_date": "2026-11-16"})
        ok("rows without a parent are not constrained", True)

        # --- a NON-partial unique index and NULLs: the trap the design notes
        await b.create_index([("k", ASCENDING)], unique=True, name="uq_plain")
        await b.insert_one({"k": None})
        try:
            await b.insert_one({"k": None})
            ok("(expected trap) a plain unique index treats two NULLs as equal", False)
        except DuplicateKeyError:
            ok("(documented trap) a plain unique index treats two NULLs as EQUAL - nullable unique columns must be partial", True)
        await b.delete_many({})

        # --- transactions
        async with client.start_session() as s:
            async with await s.start_transaction():
                await a.insert_one({"user_id": "tx", "n": 1}, session=s)
                await b.insert_one({"k": "tx"}, session=s)
                seen = await a.count_documents({"user_id": "tx"}, session=s)
        ok("a transaction commits across two collections and sees its own writes", seen == 1 and await a.count_documents({"user_id": "tx"}) == 1 and await b.count_documents({"k": "tx"}) == 1)

        try:
            async with client.start_session() as s:
                async with await s.start_transaction():
                    await a.insert_one({"user_id": "tx2"}, session=s)
                    raise RuntimeError("boom")
        except RuntimeError:
            pass
        ok("an exception rolls the whole transaction back", await a.count_documents({"user_id": "tx2"}) == 0)

        async with client.start_session() as s:
            try:
                async with await s.start_transaction():
                    await a.insert_one({"user_id": "u9", "client_key": "dup"}, session=s)
                    await a.insert_one({"user_id": "u9", "client_key": "dup"}, session=s)
            except DuplicateKeyError:
                pass
        ok("a duplicate key inside a transaction aborts it (no savepoints) - nothing from it is kept", await a.count_documents({"user_id": "u9"}) == 0)

        # --- write conflict: two transactions, one document
        await a.insert_one({"_id": "hot", "n": 0})
        s1, s2 = client.start_session(), client.start_session()
        got = None
        try:
            await s1.start_transaction()
            await a.update_one({"_id": "hot"}, {"$inc": {"n": 1}}, session=s1)
            await s2.start_transaction()
            try:
                await a.update_one({"_id": "hot"}, {"$inc": {"n": 1}}, session=s2)
                got = "no conflict"
            except OperationFailure as e:
                got = "conflict " + str(e.code) + (" transient" if e.has_error_label("TransientTransactionError") else "")
            await s1.commit_transaction()
        finally:
            await s1.end_session()
            await s2.end_session()
        ok("two transactions on one document: the second fails FAST with a transient WriteConflict (no waiting)", got == "conflict 112 transient", str(got))

        # --- with_transaction retries on its own
        async def bump(session):
            await a.update_one({"_id": "hot"}, {"$inc": {"n": 1}}, session=session)

        async def worker():
            async with client.start_session() as s:
                await s.with_transaction(bump)

        await asyncio.gather(*[worker() for _ in range(8)])
        n = (await a.find_one({"_id": "hot"}))["n"]
        ok("8 concurrent with_transaction increments all land (retry on conflict)", n == 9, f"n={n}")

        # --- counters outside a transaction
        v1 = (await ctr.find_one_and_update({"_id": "t"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True))["seq"]
        v2 = (await ctr.find_one_and_update({"_id": "t"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True))["seq"]
        ok("counters: find_one_and_update upsert $inc returns 1, 2", (v1, v2) == (1, 2), f"{v1},{v2}")
        got = await asyncio.gather(*[ctr.find_one_and_update({"_id": "c"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True) for _ in range(25)])
        ok("25 concurrent counter increments never collide", sorted(d["seq"] for d in got) == list(range(1, 26)))

        # --- queue claim: atomic find_one_and_update, disjoint
        await q.insert_many([{"_id": i, "status": "scheduled", "fire_at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=i)} for i in range(30)])

        async def claim():
            return await q.find_one_and_update({"status": "scheduled"}, {"$set": {"status": "sending"}}, sort=[("fire_at", ASCENDING)], return_document=True)

        claimed = [d for d in await asyncio.gather(*[claim() for _ in range(30)]) if d]
        ok("30 concurrent claimers each get a different reminder", sorted(d["_id"] for d in claimed) == list(range(30)))

        # --- time
        now = dt.datetime.now(dt.timezone.utc)
        await q.insert_one({"_id": "t", "at": now})
        back = (await q.find_one({"_id": "t"}))["at"]
        ok("datetimes come back timezone-aware UTC", back.tzinfo is not None and back.utcoffset() == dt.timedelta(0))
        ok("datetimes keep milliseconds only (microseconds are truncated)", back.microsecond == (now.microsecond // 1000) * 1000, f"{now.microsecond} -> {back.microsecond}")

        # --- ordering of NULL / missing
        await a.delete_many({})
        await a.insert_many([{"_id": 1, "v": 5}, {"_id": 2, "v": None}, {"_id": 3}, {"_id": 4, "v": 1}])
        asc = [d["_id"] async for d in a.find().sort("v", ASCENDING)]
        desc = [d["_id"] async for d in a.find().sort("v", DESCENDING)]
        ok("(documented) Mongo sorts NULL / missing FIRST on ascending - Postgres puts them LAST", asc[:2] != [4, 1] and asc[-2:] == [1, 4] or asc[2:] == [4, 1], str(asc))
        ok("(documented) Mongo sorts NULL / missing LAST on descending - Postgres puts them FIRST", desc[:2] == [1, 4] or desc[:2] == [1, 4][::-1], str(desc))

        # --- $ne and NULL
        ne = sorted([d["_id"] async for d in a.find({"v": {"$ne": 5}})])
        ok("(documented) {$ne: 5} also matches NULL / missing rows - SQL `v != 5` would not", ne == [2, 3, 4], str(ne))
        nin = sorted([d["_id"] async for d in a.find({"v": {"$nin": [5, None]}})])
        ok("{$nin: [5, null]} gives SQL's `v != 5`", nin == [4], str(nin))

        # --- awkward JSON keys inside a document
        try:
            await a.insert_one({"_id": "k1", "doc": {"a.b": 1, "$x": 2, "c": {"d.e": 3}}})
            back = await a.find_one({"_id": "k1"})
            ok("nested keys with a dot or a leading $ are stored and read back unchanged", back["doc"] == {"a.b": 1, "$x": 2, "c": {"d.e": 3}})
            await a.update_one({"_id": "k1"}, {"$set": {"doc": {"a.b": 9}}})
            back = await a.find_one({"_id": "k1"})
            ok("a whole-field $set with such keys works (the layer only ever replaces whole JSON fields)", back["doc"] == {"a.b": 9})
        except PyMongoError as e:
            ok("nested keys with a dot or a leading $ are accepted", False, type(e).__name__)

        # --- big ints
        await a.insert_one({"_id": "big", "n": 2 ** 40})
        ok("a 64-bit integer survives", (await a.find_one({"_id": "big"}))["n"] == 2 ** 40)

        # --- what init_db will need
        info = await a.index_information()
        ok("index_information() lists the indexes created (init_db idempotence)", {"uq_client", "ix_due", "uq_occ"} <= set(info))
        names = await db.list_collection_names()
        ok("list_collection_names() works", TAG + "_a" in names)
    finally:
        for c in (a, b, ctr, q):
            try:
                await c.drop()
            except PyMongoError:
                pass
        left = [n for n in await db.list_collection_names() if n.startswith(TAG)]
        ok("the probe collections were dropped", not left, str(left))
        await client.close()


asyncio.run(main())
print("\n%s - %d failed" % ("ALL OK" if not fails else "PROBLEMS", fails))
sys.exit(1 if fails else 0)
