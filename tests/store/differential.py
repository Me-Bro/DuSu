"""Differential test: the SAME random queries on real SQLAlchemy + Postgres and on the store + Mongo must give the same answers.

A seeded generator builds a table full of NULLs and ties, then random filters (comparisons, IS [NOT] NULL / TRUE / FALSE, IN, LIKE, lower(), AND / OR nested), random ORDER BY (columns,
both directions, NULLS FIRST / LAST, boolean expressions), LIMIT / OFFSET, aggregates and GROUP BY. Every query is described once as a tiny AST and built twice, once per engine.
Needs PG_URL (tests/store/run.sh starts a scratch Postgres). Usage: tests/store/run.sh differential.py [seed] [queries]
"""

import asyncio
import datetime as dt
import decimal
import os
import random
import sys

sys.path.insert(0, "/app")

import sqlalchemy as sa                                                      # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert                # noqa: E402,F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine   # noqa: E402
from sqlalchemy.orm import DeclarativeBase                                   # noqa: E402

from app import store                                                        # noqa: E402
from app.store import Base, Boolean, Date, DateTime, Float, Integer, Mapped, String, mapped_column  # noqa: E402

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261116
NQ = int(sys.argv[2]) if len(sys.argv) > 2 else 700
UTC = dt.timezone.utc


class SABase(DeclarativeBase):
    pass


class SAItem(SABase):
    __tablename__ = "d_items"
    id = sa.Column(sa.Integer, primary_key=True)
    grp = sa.Column(sa.String(8))
    n = sa.Column(sa.Integer)
    f = sa.Column(sa.Float)
    flag = sa.Column(sa.Boolean)
    s = sa.Column(sa.String(16))
    d = sa.Column(sa.Date)
    at = sa.Column(sa.DateTime(timezone=True))
    at2 = sa.Column(sa.DateTime(timezone=True))


class DItem(Base):
    __tablename__ = "d_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    grp: Mapped[str | None] = mapped_column(String(8), nullable=True)
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    f: Mapped[float | None] = mapped_column(Float, nullable=True)
    flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    s: Mapped[str | None] = mapped_column(String(16), nullable=True)
    d: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    at2: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


COLS = ["grp", "n", "f", "flag", "s", "d", "at", "at2"]
DOMAIN = {
    "grp": ["x", "y", "z"],
    "n": list(range(-3, 7)),
    "f": [0.5, 1.5, 2.5, -1.0],
    "flag": [True, False],
    "s": ["Alpha", "alpha", "BETA", "beta", "gamma", "a_b", "a%b", "", "Zed"],
    "d": [dt.date(2026, 3, i) for i in range(1, 7)],
    "at": [dt.datetime(2026, 1, i, 12, 0, 0, tzinfo=UTC) for i in range(1, 7)],
    "at2": [dt.datetime(2026, 1, i, 18, 0, 0, tzinfo=UTC) for i in range(1, 7)],
}
ORDERABLE = ["grp", "n", "f", "flag", "s", "d", "at"]
CMP_COLS = ["n", "f", "s", "d", "at", "at2", "grp"]
LIKES = ["a%", "%a", "%e%", "_eta", "a_b", "a\\%b", "%", "A%", "%z%", "__"]


def make_rows(rng, count=70):
    rows = []
    for i in range(1, count + 1):
        r = {"id": i}
        for c in COLS:
            r[c] = None if rng.random() < 0.25 else rng.choice(DOMAIN[c])
        rows.append(r)
    return rows


# ---------------------------------------------------------------- the query AST, built twice
def gen_pred(rng, depth=0):
    k = rng.random()
    if depth < 2 and k < 0.30:
        return (rng.choice(["and", "or"]), [gen_pred(rng, depth + 1) for _ in range(rng.randint(2, 3))])
    c = rng.choice(COLS)
    t = rng.random()
    if t < 0.40 and c in CMP_COLS:
        return ("cmp", c, rng.choice(["==", "!=", "<", "<=", ">", ">="]), rng.choice(DOMAIN[c]))
    if t < 0.55:
        return ("isnull", c, rng.random() < 0.5)
    if t < 0.65 and c == "flag":
        return ("isbool", c, rng.choice([True, False]), rng.random() < 0.5)
    if t < 0.80 and c in CMP_COLS:
        vals = [rng.choice(DOMAIN[c]) for _ in range(rng.randint(0, 3))]
        if rng.random() < 0.3:
            vals.append(None)
        return ("in", c, vals)
    if t < 0.90 and c == "s":
        return ("like", c, rng.choice(LIKES))
    if t < 0.93 and c == "s":
        return ("lower_eq", c, rng.choice(["alpha", "beta", "gamma", "", "zed"]))
    if t < 0.97:
        if rng.random() < 0.5:
            return ("coalesce", ["at", "at2"], rng.choice(["==", "!=", "<", "<=", ">", ">="]), rng.choice(DOMAIN["at"] + DOMAIN["at2"]))
        return ("coalesce", ["n", "f"], rng.choice(["==", "!=", "<", "<=", ">", ">="]), rng.choice(DOMAIN["n"] + DOMAIN["f"]))
    return ("cmp", "n", rng.choice(["==", "!=", "<", ">"]), rng.choice(DOMAIN["n"]))


def build(node, M, A):
    """M: the model class (columns as attributes); A: the module with and_/or_/func for this engine."""
    k = node[0]
    if k in ("and", "or"):
        return (A.and_ if k == "and" else A.or_)(*[build(p, M, A) for p in node[1]])
    if k == "coalesce":
        fn = A.func.coalesce(*[getattr(M, c) for c in node[1]])
        op, v = node[2], node[3]
        return {"==": fn == v, "!=": fn != v, "<": fn < v, "<=": fn <= v, ">": fn > v, ">=": fn >= v}[op]
    col = getattr(M, node[1])
    if k == "cmp":
        op, v = node[2], node[3]
        return {"==": col == v, "!=": col != v, "<": col < v, "<=": col <= v, ">": col > v, ">=": col >= v}[op]
    if k == "isnull":
        return col.is_not(None) if node[2] else col.is_(None)
    if k == "isbool":
        return col.is_not(node[2]) if node[3] else col.is_(node[2])
    if k == "in":
        return col.in_(node[2])
    if k == "like":
        return col.like(node[2])
    if k == "lower_eq":
        return A.func.lower(col) == node[2]
    raise AssertionError(k)


def gen_order(rng):
    items = []
    for _ in range(rng.randint(0, 3)):
        if rng.random() < 0.10:
            items.append(("coalesce", rng.choice([["at", "at2"], ["n", "f"], ["s", "grp"]]), rng.choice([True, False]), rng.choice([None, "first", "last"])))
        elif rng.random() < 0.15:
            items.append(("expr", rng.choice(["n", "s", "flag"]), rng.choice([True, False]), rng.choice(DOMAIN["n"])))
        else:
            items.append(("col", rng.choice(ORDERABLE), rng.choice([True, False]), rng.choice([None, "first", "last"])))
    return items


def build_order(items, M, A=None):
    out = []
    for it in items:
        if it[0] == "coalesce":
            e = A.func.coalesce(*[getattr(M, c) for c in it[1]])
            e = e.desc() if it[2] else e.asc()
            if it[3] == "first":
                e = e.nulls_first()
            elif it[3] == "last":
                e = e.nulls_last()
            out.append(e)
        elif it[0] == "expr":
            col = getattr(M, it[1])
            e = (col == it[3]) if it[1] == "n" else (col == "beta") if it[1] == "s" else (col == True)    # noqa: E712
            out.append(e.desc() if it[2] else e.asc())
        else:
            e = getattr(M, it[1])
            e = e.desc() if it[2] else e.asc()
            if it[3] == "first":
                e = e.nulls_first()
            elif it[3] == "last":
                e = e.nulls_last()
            out.append(e)
    out.append(M.id.asc())
    return out


class SAmod:
    and_, or_, func = staticmethod(sa.and_), staticmethod(sa.or_), sa.func


class STmod:
    and_, or_, func = staticmethod(store.and_), staticmethod(store.or_), store.func


def norm(v):
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, dt.datetime):
        return v.astimezone(UTC).replace(tzinfo=UTC)
    return v


async def main():
    rng = random.Random(SEED)
    rows = make_rows(rng)
    pg_url = os.environ["PG_URL"].replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(pg_url)
    async with engine.begin() as conn:
        await conn.run_sync(SABase.metadata.drop_all)
        await conn.run_sync(SABase.metadata.create_all)
        await conn.execute(sa.insert(SAItem), rows)
    pg = async_sessionmaker(engine, expire_on_commit=False)

    store.configure(os.environ["MONGODB_URI"])
    db = store.core.database()
    await db.drop_collection("d_items")
    await store.init([DItem])
    Sess = store.SessionFactory()
    async with Sess() as s:
        for r in rows:
            s.add(DItem(**r))
        await s.commit()

    # the data itself must round-trip identically
    async with pg() as ps, Sess() as ms:
        a = [(r.id, *[norm(getattr(r, c)) for c in COLS]) for r in (await ps.execute(sa.select(SAItem).order_by(SAItem.id))).scalars().all()]
        b = [(r.id, *[norm(getattr(r, c)) for c in COLS]) for r in (await ms.execute(store.select(DItem).order_by(DItem.id))).scalars().all()]
        data_same = a == b

    bad, n_ok = [], 0

    def check(desc, left, right):
        nonlocal n_ok
        if left == right:
            n_ok += 1
        else:
            bad.append((desc, left, right))

    async with pg() as ps, Sess() as ms:
        # ---- entity selects: filter + order + limit / offset
        for qi in range(NQ):
            pred = gen_pred(rng) if rng.random() < 0.9 else None
            order = gen_order(rng)
            lim = rng.choice([None, None, 1, 3, 10])
            off = rng.choice([None, None, 0, 2, 5])
            q1 = sa.select(SAItem.id)
            q2 = store.select(DItem.id)
            if pred is not None:
                q1 = q1.where(build(pred, SAItem, SAmod))
                q2 = q2.where(build(pred, DItem, STmod))
            q1 = q1.order_by(*build_order(order, SAItem, SAmod))
            q2 = q2.order_by(*build_order(order, DItem, STmod))
            if lim is not None:
                q1, q2 = q1.limit(lim), q2.limit(lim)
            if off:
                q1, q2 = q1.offset(off), q2.offset(off)
            left = (await ps.execute(q1)).scalars().all()
            right = (await ms.execute(q2)).scalars().all()
            check(f"select #{qi}: where={pred} order={order} limit={lim} offset={off}", left, right)

        # ---- the whole entity (not just ids), with a filter
        for qi in range(60):
            pred = gen_pred(rng)
            left = [(r.id, *[norm(getattr(r, c)) for c in COLS]) for r in (await ps.execute(sa.select(SAItem).where(build(pred, SAItem, SAmod)).order_by(SAItem.id))).scalars().all()]
            right = [(r.id, *[norm(getattr(r, c)) for c in COLS]) for r in (await ms.execute(store.select(DItem).where(build(pred, DItem, STmod)).order_by(DItem.id))).scalars().all()]
            check(f"entities #{qi}: where={pred}", left, right)

        # ---- aggregates
        aggs = [("count", lambda M, A: A.func.count()), ("count_n", lambda M, A: A.func.count(M.n)), ("sum_n", lambda M, A: A.func.sum(M.n)), ("min_n", lambda M, A: A.func.min(M.n)),
                ("max_s", lambda M, A: A.func.max(M.s)), ("min_d", lambda M, A: A.func.min(M.d)), ("max_at", lambda M, A: A.func.max(M.at)), ("avg_f", lambda M, A: A.func.avg(M.f)),
                ("sum_f", lambda M, A: A.func.sum(M.f)), ("coalesce_sum", lambda M, A: A.func.coalesce(A.func.sum(M.n), 0))]
        for qi in range(140):
            pred = gen_pred(rng) if rng.random() < 0.85 else None
            name, mk = rng.choice(aggs)
            q1 = sa.select(mk(SAItem, SAmod)).select_from(SAItem)
            q2 = store.select(mk(DItem, STmod)).select_from(DItem)
            if pred is not None:
                q1, q2 = q1.where(build(pred, SAItem, SAmod)), q2.where(build(pred, DItem, STmod))
            check(f"aggregate {name} #{qi}: where={pred}", norm((await ps.execute(q1)).scalar()), norm((await ms.execute(q2)).scalar()))

        # ---- GROUP BY
        for qi in range(80):
            pred = gen_pred(rng) if rng.random() < 0.7 else None
            gcols = rng.sample(["grp", "flag", "s"], rng.randint(1, 2))
            vals = [("count", lambda M, A: A.func.count()), ("sum_n", lambda M, A: A.func.sum(M.n)), ("max_d", lambda M, A: A.func.max(M.d))]
            picks = rng.sample(vals, rng.randint(1, 2))
            q1 = sa.select(*[getattr(SAItem, c) for c in gcols], *[mk(SAItem, SAmod) for _n, mk in picks]).group_by(*[getattr(SAItem, c) for c in gcols])
            q2 = store.select(*[getattr(DItem, c) for c in gcols], *[mk(DItem, STmod) for _n, mk in picks]).group_by(*[getattr(DItem, c) for c in gcols])
            if pred is not None:
                q1, q2 = q1.where(build(pred, SAItem, SAmod)), q2.where(build(pred, DItem, STmod))
            key = lambda r: repr(tuple(norm(x) for x in r))                     # noqa: E731
            left = sorted((tuple(norm(x) for x in r) for r in (await ps.execute(q1)).all()), key=key)
            right = sorted((tuple(norm(x) for x in r) for r in (await ms.execute(q2)).all()), key=key)
            check(f"group_by {gcols} {[n for n, _ in picks]} #{qi}: where={pred}", left, right)

        # ---- a deterministic LIKE battery: every pattern against every row (a random draw can miss the one that tells anchored from unanchored)
        for pat in LIKES + ["lph", "eta", "Al", "alpha", "a%b", "%a%", "_", "%_%", "a\\_b", "", "%%", "a_%", "_a%", "%a_", "Z%", "%d", "%ed", "z%"]:
            left = (await ps.execute(sa.select(SAItem.id).where(SAItem.s.like(pat)).order_by(SAItem.id))).scalars().all()
            right = (await ms.execute(store.select(DItem.id).where(DItem.s.like(pat)).order_by(DItem.id))).scalars().all()
            check(f"like battery {pat!r}", left, right)

        # ---- count(distinct)
        for c in ["grp", "n", "s", "d"]:
            check(f"count distinct {c}", (await ps.execute(sa.select(sa.func.count(sa.func.distinct(getattr(SAItem, c)))))).scalar(),
                  (await ms.execute(store.select(store.func.count(store.func.distinct(getattr(DItem, c)))))).scalar())

    await engine.dispose()
    print(f"seed {SEED}: data round-trips identically: {data_same}")
    print(f"{n_ok} of {n_ok + len(bad)} queries gave the same answer on Postgres and on the store")
    for d, l, r in bad[:12]:
        print("\nDIFFERENT:", d, "\n  postgres:", l, "\n  store   :", r)
    if bad:
        print(f"\n{len(bad)} query/queries differ")
    sys.exit(0 if (data_same and not bad) else 1)


asyncio.run(main())
