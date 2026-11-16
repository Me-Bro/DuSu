"""Copy every DuSu table from the OLD Postgres into MongoDB (the shared `rooted-mongo`, database `dusu`) - data only, once - and verify the copy.

  python scripts/pg_to_mongo.py --src postgresql://user:pw@host:5432/db            # copy every table that is still empty on the Mongo side
  python scripts/pg_to_mongo.py --src ... --dry-run                                # read + convert everything, write nothing (finds data the new types would refuse)
  python scripts/pg_to_mongo.py --src ... --verify                                 # after a copy (or alone): every row of Postgres == its document in Mongo
  python scripts/pg_to_mongo.py --src ... --replace                                # drop and re-copy the collections (a rehearsal re-run); never the default

The Mongo side is MONGODB_URI (or --dst). Each row goes through the SAME store models and type rules the app writes with (DateTime -> ms-truncated UTC date, Date -> ISO string, JSONB
-> embedded document, ...), so a copied row is exactly what the app would have stored. Integer ids are kept (the API paths use them) and each collection's counter is raised past
its largest id. Indexes are created FIRST, so a unique index that the data would violate fails loudly during the copy instead of silently later.

Runs where both databases are reachable (a one-off container on both networks). Needs `asyncpg` (the old image has it) and `pymongo`. Prints counts and key statistics only - never a row.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.environ.get("SRC_DATABASE_URL", ""), help="the Postgres to copy FROM (or SRC_DATABASE_URL)")
    ap.add_argument("--dst", default="", help="the Mongo to copy INTO (default: MONGODB_URI)")
    ap.add_argument("--dry-run", action="store_true", help="read and convert only")
    ap.add_argument("--verify", action="store_true", help="compare every row with its document")
    ap.add_argument("--verify-only", action="store_true", help="only compare (no copy)")
    ap.add_argument("--replace", action="store_true", help="drop the destination collection first")
    ap.add_argument("--tables", default="", help="comma list (default: all)")
    return ap.parse_args()


A = _args()
if A.dst:
    os.environ["MONGODB_URI"] = A.dst
if not A.src:
    sys.exit("--src (or SRC_DATABASE_URL) is required: the Postgres to copy from")
if not os.environ.get("MONGODB_URI") and not A.dry_run:
    sys.exit("no destination: set MONGODB_URI or pass --dst")

import asyncpg                                                   # noqa: E402

from app import db, store                                         # noqa: E402  (db registers its models; configure() runs from MONGODB_URI)
# the feature modules register their models on import
from app.planner import models as _p                              # noqa: E402,F401
from app.resume_interview import models as _r                     # noqa: E402,F401
from app.grammar import models as _g                              # noqa: E402,F401
from app.notify import models as _n                               # noqa: E402,F401
from app.keys import models as _k                                 # noqa: E402,F401
from app.insights import models as _i                             # noqa: E402,F401
from app.store import core                                        # noqa: E402
from app.store.model import Base                                  # noqa: E402

BATCH = 500
_SAFE = re.compile(r"^[a-z_0-9]+$")


def log(*a):
    print(*a, flush=True)


async def connect_pg():
    url = A.src.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")
    conn = await asyncpg.connect(url)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    return conn


def models_in_order() -> list:
    want = {t.strip() for t in A.tables.split(",") if t.strip()}
    ms = sorted(Base.models(), key=lambda m: (m.fk_rank(), m.__tablename__))
    if want:
        unknown = want - {m.__tablename__ for m in ms}
        if unknown:
            sys.exit(f"unknown table(s): {sorted(unknown)}")
        ms = [m for m in ms if m.__tablename__ in want]
    return ms


def to_doc(M, row) -> dict:
    """The document the app would have stored for this Postgres row (the same type conversions, none of the defaults: a copy is a copy)."""
    inst = M.__new__(M)
    inst._data, inst._snap, inst._deleted = {}, None, False
    for name in M.__columns__:
        inst._data[name] = row[name] if name in row.keys() else None
    return inst._doc_from_stored(inst._stored())


def bad_json_keys(v, path="", out=None) -> list:
    out = [] if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            if "." in k or k.startswith("$") or "\x00" in k:
                out.append(path + "/" + k)
            bad_json_keys(x, path + "/" + k, out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            bad_json_keys(x, f"{path}[{i}]", out)
    return out


async def rows_of(conn, table: str):
    assert _SAFE.match(table)
    async with conn.transaction():
        async for rec in conn.cursor(f'SELECT * FROM "{table}"'):
            yield dict(rec)


def pk_filter(M, doc) -> dict:
    return {"_id": doc["_id"]} if "_id" in doc and len(M.__pk__) == 1 else {c.field: doc[c.field] for c in M.__pk__}


async def copy_table(conn, M) -> dict:
    t = M.__tablename__
    coll = core.coll(t)
    have = 0 if A.dry_run else await coll.count_documents({})
    if have and not A.replace:
        return {"table": t, "skipped": f"destination already holds {have} document(s) (use --replace to re-copy)"}
    if have and A.replace:
        await coll.drop()
        await store.init([M])
    n = bad = 0
    keys_bad: list = []
    batch: list = []
    max_id = None
    single_int_pk = len(M.__pk__) == 1 and M.__pk__[0].type.name in ("int", "smallint")
    async for row in rows_of(conn, t):
        try:
            doc = to_doc(M, row)
        except Exception as e:                                            # a value the new types refuse: say which table and column class, never the value
            bad += 1
            if bad <= 3:
                log(f"   ! {t}: a row was refused: {type(e).__name__}: {str(e)[:120]}")
            continue
        for c in M.__columns__.values():
            if c.type.json and doc.get(c.field):
                keys_bad += bad_json_keys(doc[c.field], c.name)
        if single_int_pk:
            max_id = doc["_id"] if max_id is None else max(max_id, doc["_id"])
        batch.append(doc)
        n += 1
        if len(batch) >= BATCH and not A.dry_run:
            await coll.insert_many(batch, ordered=False)
            batch = []
    if batch and not A.dry_run:
        await coll.insert_many(batch, ordered=False)
    if single_int_pk and max_id is not None and not A.dry_run:
        await store.raise_counter(t, max_id)
    return {"table": t, "rows": n, "refused": bad, "json_keys_with_dot_or_dollar": len(keys_bad), "counter": max_id}


async def verify_table(conn, M) -> dict:
    t = M.__tablename__
    coll = core.coll(t)
    pg_n = mismatch = missing = 0
    examples: list = []
    async for row in rows_of(conn, t):
        pg_n += 1
        want = to_doc(M, row)
        got = await coll.find_one(pk_filter(M, want))
        if got is None:
            missing += 1
            if len(examples) < 3:
                examples.append(f"missing: {pk_filter(M, want)}")
            continue
        got.pop("_id", None) if "_id" not in want else None               # a composite-key collection has a Mongo-made _id the row does not carry
        diff = [k for k in set(want) | set(got) if want.get(k) != got.get(k)]
        if diff:
            mismatch += 1
            if len(examples) < 3:
                examples.append(f"{pk_filter(M, want)}: differs in {sorted(diff)}")
    mongo_n = await coll.count_documents({})
    counter_ok = True
    if len(M.__pk__) == 1 and M.__pk__[0].type.name in ("int", "smallint") and pg_n:
        mx = await coll.find_one({}, sort=[("_id", -1)])
        c = await core.coll("counters").find_one({"_id": t})
        counter_ok = bool(c) and c["seq"] >= mx["_id"]
    ok = pg_n == mongo_n and not mismatch and not missing and counter_ok
    return {"table": t, "postgres": pg_n, "mongo": mongo_n, "missing": missing, "differ": mismatch, "counter_ok": counter_ok, "ok": ok, "examples": examples}


async def main() -> int:
    conn = await connect_pg()
    models = models_in_order()
    t0 = time.time()
    failures = 0
    try:
        if not A.dry_run and not A.verify_only:
            if not store.enabled():
                sys.exit("no destination configured")
            await store.init()
            log(f"indexes ready on {len(models)} collection(s); copying ...")
        if not A.verify_only:
            total = 0
            for M in models:
                r = await copy_table(conn, M)
                if "skipped" in r:
                    log(f"  {r['table']:<20} SKIPPED - {r['skipped']}")
                    continue
                total += r["rows"]
                flag = "" if not r["refused"] else f"  REFUSED {r['refused']}"
                extra = f"  (json keys with '.' or '$': {r['json_keys_with_dot_or_dollar']})" if r["json_keys_with_dot_or_dollar"] else ""
                log(f"  {r['table']:<20} {r['rows']:>6} row(s){'  [dry run]' if A.dry_run else ''}{flag}{extra}")
                failures += 1 if r["refused"] else 0
            log(f"{'read' if A.dry_run else 'copied'} {total} row(s) in {time.time() - t0:.1f}s")
        if (A.verify or A.verify_only) and not A.dry_run:
            log("verifying every row ...")
            allok = True
            for M in models:
                v = await verify_table(conn, M)
                allok &= v["ok"]
                log(f"  {v['table']:<20} postgres {v['postgres']:>6}  mongo {v['mongo']:>6}  missing {v['missing']}  differ {v['differ']}  counter {'ok' if v['counter_ok'] else 'BEHIND'}  -> {'OK' if v['ok'] else 'MISMATCH ' + '; '.join(v['examples'])}")
            log("VERIFIED: every row is in Mongo exactly as the app would have written it" if allok else "VERIFICATION FAILED")
            failures += 0 if allok else 1
    finally:
        await conn.close()
        await store.close()
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
