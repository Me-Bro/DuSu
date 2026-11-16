"""The store layer's contract, one behaviour per check (see DUSU_MONGO_MIGRATION_PLAN.md section 4). Runs on a scratch Mongo: tests/store/run.sh unit.py"""

from _h import *                                                            # noqa: F401,F403
from _h import (TDay, TItem, TUser, TWeek, MODELS, Sess, UTC, now, ok, raises, reset, run, section, wipe)
import datetime as dt
from app.store import expr as E, types as T
from app.store.errors import DataError, IntegrityError, NotSupported
from app.store.model import Base
from app.store import (and_, delete, desc, func, insert, or_, select, update, claim_one)


async def main():
    await reset()

    # ============================================================ types
    section("types: what is stored and what comes back")
    dtt = T.DateTime()
    micro = dt.datetime(2026, 11, 16, 10, 20, 30, 123456, tzinfo=UTC)
    ok("DateTime keeps milliseconds only", dtt.to_store(micro).microsecond == 123000)
    ok("DateTime: a naive value is taken as UTC", dtt.to_store(dt.datetime(2026, 1, 1, 12)).tzinfo is not None)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    ok("DateTime: an aware value in another zone is converted to UTC", dtt.to_store(dt.datetime(2026, 1, 1, 12, tzinfo=ist)).hour == 6)
    ok("DateTime: a date is refused", await raises(DataError, lambda: _c(dtt.to_store, dt.date(2026, 1, 1))) is not None)
    ok("Date is stored as an ISO string", T.Date().to_store(dt.date(2026, 11, 16)) == "2026-11-16")
    ok("Date: a datetime gives its date part (what asyncpg did)", T.Date().to_store(dt.datetime(2026, 11, 16, 23, 59)) == "2026-11-16")
    ok("Date round-trips", T.Date().from_store("2026-11-16") == dt.date(2026, 11, 16))
    ok("Integer refuses a string", await raises(DataError, lambda: _c(T.Integer().to_store, "5")) is not None)
    ok("Integer refuses a non-integral float", await raises(DataError, lambda: _c(T.Integer().to_store, 1.5)) is not None)
    ok("Integer refuses a value beyond int64", await raises(DataError, lambda: _c(T.Integer().to_store, 2 ** 70)) is not None)
    ok("Integer accepts an integral float and a bool as numbers", T.Integer().to_store(3.0) == 3 and T.Integer().to_store(True) == 1)
    ok("String refuses an int", await raises(DataError, lambda: _c(T.String().to_store, 5)) is not None)
    ok("JSON: int / float / None keys become strings, tuples become lists (json.dumps semantics)", T.json_norm({1: (1, 2), 2.5: None, None: 0}) == {"1": [1, 2], "2.5": None, "null": 0})
    ok("JSON: a bool key becomes 'true' / 'false'", T.json_norm({True: 1}) == {"true": 1})
    ok("JSON: NaN is refused", await raises(DataError, lambda: _c(T.json_norm, float("nan"))) is not None)
    ok("JSON: a datetime inside is refused (as json.dumps would)", await raises(DataError, lambda: _c(T.json_norm, {"a": micro})) is not None)
    ok("JSON: a set is refused", await raises(DataError, lambda: _c(T.json_norm, {1, 2})) is not None)

    # ============================================================ models
    section("models: keys, defaults, ids, annotations")
    ok("a single-column primary key is stored as _id", TUser.id.field == "_id" and TUser.name.field == "name")
    ok("a composite key keeps its own fields and gets a unique compound index", TDay.user_id.field == "user_id" and any(i.name == "pk_t_days" and i.unique for i in TDay.__indexes__))
    ok("annotation: Mapped[int | None] is nullable, Mapped[int] is not", TUser.age.nullable and not TUser.score.nullable)
    ok("annotation types are inferred when mapped_column has none", isinstance(TUser.ratio.type, T.Float) and isinstance(TUser.born.type, T.Date) and isinstance(TUser.seen.type, T.DateTime))
    ok("a primary key is never nullable", not TUser.id.nullable)
    ok("column-level index=True becomes an index", any(i.name == "ix_t_items_user_id" for i in TItem.__indexes__) and any(i.name == "ix_t_weeks_xp" for i in TWeek.__indexes__))

    async with Sess() as s:
        u = TUser(id="u1")
        ok("an unset attribute reads None before the flush (SQLAlchemy)", u.name is None and u.score is None)
        s.add(u)
        await s.commit()
        ok("defaults are applied at insert and visible after", u.name == "" and u.score == 0 and u.active is True and u.data == {} and u.tags == [] and u.ratio == 0.5)
        ok("a callable default ran (datetime, aware, ms)", u.seen is not None and u.seen.tzinfo is not None and u.seen.microsecond % 1000 == 0)
        ok("a nullable column without default is None", u.age is None and u.born is None)
        u2 = TUser(id="u2", age=None, name=None)
        s.add(u2)
        await s.commit()
        ok("an explicit None on a column WITH a default takes the default at insert (SQLAlchemy)", u2.name == "")
        u3 = TUser(id="u3", age=None)
        s.add(u3)
        await s.commit()
        ok("an explicit None on a column with no default is stored as NULL", u3.age is None)
        doc = await store.core.coll("t_users").find_one({"_id": "u3"})
        ok("the document has _id and no 'id' field", "id" not in doc and doc["_id"] == "u3" and doc["age"] is None)

    async with Sess() as s:
        a, b, c = TItem(user_id="u1"), TItem(user_id="u1"), TItem(user_id="u1")
        s.add_all([a, b, c])
        await s.flush()
        ok("integer ids come from a counter, 1, 2, 3, visible at flush", [a.id, b.id, c.id] == [1, 2, 3])
        await s.commit()
    async with Sess() as s:
        d = TItem(user_id="u1")
        s.add(d)
        await s.commit()
        ok("the counter continues in a later session", d.id == 4)
        try:
            await s.rollback()
        except Exception:
            pass
        e = TItem(user_id="u1")
        s.add(e)
        await s.flush()
        eid = e.id
        await s.rollback()
        f = TItem(user_id="u1")
        s.add(f)
        await s.commit()
        ok("ids are never reused after a rollback (a gap is fine, like a sequence)", eid == 5 and f.id == 6)

    # ============================================================ expressions vs SQL semantics
    section("filters: SQL semantics, not Mongo's")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="u1"))
        await s.flush()
        for i, (n, k, st, fl, lab) in enumerate([(1, "a", "open", True, "Alpha"), (2, None, "open", False, "alpha"), (None, "c", "done", None, None), (5, None, "done", True, "BETA"),
                                                  (None, None, "open", None, "beta")], start=1):
            s.add(TItem(id=i, user_id="u1", n=n, client_key=k, status=st, flag=fl, label=lab, at=(dt.datetime(2026, 1, i, tzinfo=UTC) if i % 2 else None),
                        due=(dt.date(2026, 3, i) if i != 4 else None)))
        await s.commit()
        ids = lambda rows: sorted(r.id for r in rows)
        allrows = (await s.execute(select(TItem))).scalars().all()
        ok("select returns instances in the identity map (same object twice)", (await s.execute(select(TItem).where(TItem.id == 1))).scalars().first() is next(r for r in allrows if r.id == 1))
        q = lambda *w: select(TItem).where(*w)
        r = lambda *w: _ids(s, q(*w))
        ok("==", await r(TItem.n == 2) == [2])
        ok("!= excludes NULL rows (SQL), unlike Mongo's $ne", await r(TItem.n != 2) == [1, 4])
        ok("== None is IS NULL", await r(TItem.n == None) == [3, 5])                    # noqa: E711
        ok("!= None is IS NOT NULL", await r(TItem.n != None) == [1, 2, 4])             # noqa: E711
        ok("is_(None) / is_not(None)", await r(TItem.n.is_(None)) == [3, 5] and await r(TItem.n.is_not(None)) == [1, 2, 4] and await r(TItem.n.isnot(None)) == [1, 2, 4])
        ok("< <= > >= skip NULL", await r(TItem.n < 5) == [1, 2] and await r(TItem.n <= 5) == [1, 2, 4] and await r(TItem.n > 1) == [2, 4] and await r(TItem.n >= 2) == [2, 4])
        ok("in_ never matches NULL, even with None in the list", await r(TItem.n.in_([1, 5, None])) == [1, 4])
        ok("in_ of an empty list matches nothing", await r(TItem.n.in_([])) == [])
        ok("notin_ excludes the listed values AND the NULL rows, and matches nothing when the list holds a NULL (SQL)", await r(TItem.n.notin_([1, 2])) == [4] and await r(TItem.n.notin_([99])) == [1, 2, 4]
           and await r(TItem.n.notin_([1, None])) == [] and await r(TItem.n.not_in([])) == [1, 2, 4])
        ok("in_(select ...): the inner select runs first (and its NULLs drop out, as in SQL)", await r(TItem.id.in_(select(TItem.id).where(TItem.n > 1))) == [2, 4]
           and await r(TItem.n.in_(select(TItem.n).where(TItem.id.in_([1, 3])))) == [1] and await r(TItem.id.in_(select(TItem.id).where(TItem.n > 99))) == [])
        ok("is_(True) / is_(False): NULL is neither", await r(TItem.flag.is_(True)) == [1, 4] and await r(TItem.flag.is_(False)) == [2])
        ok("is_not(True) includes NULL and False (IS NOT TRUE)", await r(TItem.flag.is_not(True)) == [2, 3, 5])
        ok("string != excludes NULL", await r(TItem.client_key != "a") == [3])
        ok("and_ / & / commas", await r(and_(TItem.status == "open", TItem.n > 1)) == [2] and await r((TItem.status == "open") & (TItem.n > 1)) == [2] and await r(TItem.status == "open", TItem.n > 1) == [2])
        ok("or_ / |", await r(or_(TItem.n == 1, TItem.n == 5)) == [1, 4] and await r((TItem.n == 1) | (TItem.status == "done")) == [1, 3, 4])
        ok("nested and/or", await r(and_(TItem.status == "open", or_(TItem.n == 1, TItem.n == 2))) == [1, 2])
        ok("like prefix / suffix / middle / single char", await r(TItem.label.like("Al%")) == [1] and await r(TItem.label.like("%eta")) == [5] and await r(TItem.label.like("%lph%")) == [1, 2]
           and await r(TItem.label.like("_eta")) == [5])
        ok("like is case-sensitive and escapes regex characters", await r(TItem.label.like("alpha")) == [2] and await r(TItem.label.like("a.pha")) == [])
        ok("like without wildcards is an EXACT match, not 'contains' (the pattern is anchored at both ends)",
           await r(TItem.label.like("lph")) == [] and await r(TItem.label.like("eta")) == [] and await r(TItem.label.like("Al")) == [] and await r(TItem.label.like("beta")) == [5])
        ok("like with a wildcard on one side is anchored on the other", await r(TItem.label.like("lph%")) == [] and await r(TItem.label.like("%lph")) == [] and await r(TItem.label.like("%pha")) == [1, 2] and await r(TItem.label.like("Alp%")) == [1])
        ok("like '_' needs exactly one character", await r(TItem.label.like("_lpha")) == [1, 2] and await r(TItem.label.like("__")) == [] and await r(TItem.label.like("_")) == [])
        ok("like on NULL does not match", 3 not in await r(TItem.label.like("%")))
        ok("func.lower(col) == x (case-insensitive, NULL never matches)", await r(func.lower(TItem.label) == "alpha") == [1, 2] and await r(func.lower(TItem.label) == "beta") == [4, 5])
        ok("a Date column compares as a date", await r(TItem.due == dt.date(2026, 3, 2)) == [2] and await r(TItem.due >= dt.date(2026, 3, 3)) == [3, 5] and await r(TItem.due.is_(None)) == [4])
        ok("a DateTime column compares as a datetime", await r(TItem.at >= dt.datetime(2026, 1, 3, tzinfo=UTC)) == [3, 5] and await r(TItem.at.is_(None)) == [2, 4])
        ok("a datetime bound with microseconds still compares sensibly (ms store)", await r(TItem.at == dt.datetime(2026, 1, 1, 0, 0, 0, 999, tzinfo=UTC)) == [1])
        ok("comparing two columns is refused (loud)", await raises(NotSupported, lambda: _c(lambda: TItem.n == TItem.id)) is not None)
        ok("negation is refused (loud)", await raises(NotSupported, lambda: _c(lambda: ~(TItem.n == 1))) is not None)
        ok("join / exists / text / subquery are refused (loud)", await raises(NotSupported, lambda: _c(lambda: select(TItem).join(TUser))) is not None and await raises(NotSupported, lambda: _c(E.exists)) is not None
           and await raises(NotSupported, lambda: _c(E.text, "select 1")) is not None)
        ok("with_for_update(skip_locked=True) is refused (loud)", await raises(NotSupported, lambda: _c(lambda: select(TItem).with_for_update(skip_locked=True))) is not None)
        # the Mongo filter and the Python evaluator agree on every expression (so ordering by an expression is the same as filtering by it)
        exprs = [TItem.n == 2, TItem.n != 2, TItem.n.is_(None), TItem.flag.is_not(True), TItem.n.in_([1, 5]), TItem.label.like("%eta"), and_(TItem.status == "open", TItem.n > 1),
                 or_(TItem.n == 1, TItem.flag.is_(True)), func.lower(TItem.label) == "alpha", TItem.due >= dt.date(2026, 3, 2)]
        docs = await store.core.coll("t_items").find({}).to_list(None)
        for ex in exprs:
            by_mongo = sorted(d["_id"] for d in await store.core.coll("t_items").find(E.to_filter(ex)).to_list(None))
            by_eval = sorted(d["_id"] for d in docs if E.evaluate(ex, d) is True)
            ok(f"filter == evaluator for {type(ex).__name__}", by_mongo == by_eval, f"{by_mongo} vs {by_eval}")

    # ============================================================ ordering
    section("ordering: Postgres NULL placement")
    async with Sess() as s:
        o = lambda *ob, **kw: _ids(s, select(TItem).order_by(*ob), **kw)
        ok("ASC puts NULL last", await o(TItem.n, TItem.id, ordered=True) == [1, 2, 4, 3, 5])
        ok("DESC puts NULL first", await o(desc(TItem.n), TItem.id, ordered=True) == [3, 5, 4, 2, 1])
        ok(".desc() == desc()", await o(TItem.n.desc(), TItem.id, ordered=True) == [3, 5, 4, 2, 1])
        ok("nulls_last() on DESC", await o(TItem.n.desc().nulls_last(), TItem.id, ordered=True) == [4, 2, 1, 3, 5])
        ok("nulls_first() on ASC", await o(TItem.n.asc().nulls_first(), TItem.id, ordered=True) == [3, 5, 1, 2, 4])
        ok("a NOT NULL column pushes the sort down and breaks ties by id", await o(TItem.status, ordered=True) == [3, 4, 1, 2, 5])
        ok("two keys with mixed directions", await o(TItem.status.desc(), desc(TItem.id), ordered=True) == [5, 2, 1, 4, 3])
        ok("ordering by a boolean expression follows SQL (NULL is the largest)", await o((TItem.n == 2).desc(), TItem.id, ordered=True) == [3, 5, 2, 1, 4])
        ok("limit / offset", (await _ids(s, select(TItem).order_by(TItem.id).limit(2), ordered=True)) == [1, 2] and (await _ids(s, select(TItem).order_by(TItem.id).offset(3), ordered=True)) == [4, 5]
           and (await _ids(s, select(TItem).order_by(TItem.id).limit(2).offset(1), ordered=True)) == [2, 3])
        ok("limit with a NULL-bearing key sorts first, then cuts", (await _ids(s, select(TItem).order_by(TItem.n).limit(2), ordered=True)) == [1, 2])
        s.add_all([TUser(id=i, score=7, name="tie") for i in ("tc", "ta", "tb")])     # inserted in a different order than their ids sort; filtered on a non-indexed field so the scan is in insertion order
        await s.flush()
        tied = (await s.execute(select(TUser.id).where(TUser.name == "tie").order_by(TUser.score))).scalars().all()
        ok("ties in a pushed-down sort are broken by id, not by insertion order (deterministic, like autoincrement ids)", tied == ["ta", "tb", "tc"], str(tied))
        await s.rollback()
        ok("a column select returns rows with attribute access", [(x.id, x.n) for x in (await s.execute(select(TItem.id, TItem.n).order_by(TItem.id))).all()] == [(1, 1), (2, 2), (3, None), (4, 5), (5, None)])
        ok("scalars() of one column", (await s.execute(select(TItem.due).where(TItem.id == 2))).scalars().all() == [dt.date(2026, 3, 2)])
        ok("a column select converts types (date -> date, datetime -> datetime)", isinstance((await s.execute(select(TItem.at).where(TItem.id == 1))).scalar(), dt.datetime))
        ok("distinct() on a column", sorted((await s.execute(select(TItem.status).distinct())).scalars().all()) == ["done", "open"])

    # ============================================================ aggregates
    section("aggregates and group_by")
    async with Sess() as s:
        ok("count()", (await s.execute(select(func.count()).select_from(TItem))).scalar() == 5)
        ok("count() with where", (await s.execute(select(func.count()).select_from(TItem).where(TItem.status == "open"))).scalar() == 3)
        ok("count() of no rows is 0", (await s.execute(select(func.count()).select_from(TItem).where(TItem.n > 99))).scalar() == 0)
        ok("count(col) skips NULL", (await s.execute(select(func.count(TItem.n)))).scalar() == 3)
        ok("count(distinct col)", (await s.execute(select(func.count(func.distinct(TItem.status))))).scalar() == 2)
        ok("sum / min / max / avg", (await s.execute(select(func.sum(TItem.n)))).scalar() == 8 and (await s.execute(select(func.min(TItem.n)))).scalar() == 1
           and (await s.execute(select(func.max(TItem.n)))).scalar() == 5 and abs((await s.execute(select(func.avg(TItem.n)))).scalar() - 8 / 3) < 1e-9)
        ok("sum over no rows is NULL and coalesce(.., 0) fixes it", (await s.execute(select(func.sum(TItem.n)).where(TItem.n > 99))).scalar() is None
           and (await s.execute(select(func.coalesce(func.sum(TItem.n), 0)).where(TItem.n > 99))).scalar() == 0)
        ok("min of a date column returns a date", (await s.execute(select(func.min(TItem.due)))).scalar() == dt.date(2026, 3, 1))
        rows = (await s.execute(select(TItem.status, func.count()).group_by(TItem.status))).all()
        ok("group_by one column", sorted((r[0], r[1]) for r in rows) == [("done", 2), ("open", 3)])
        rows = (await s.execute(select(TItem.status, TItem.flag, func.count()).group_by(TItem.status, TItem.flag))).all()
        ok("group_by two columns (NULL is a group of its own)", sorted((r[0], str(r[1]), r[2]) for r in rows) == [("done", "None", 1), ("done", "True", 1), ("open", "False", 1), ("open", "None", 1), ("open", "True", 1)])
        ok("group_by with sum", dict((r[0], r[1]) for r in (await s.execute(select(TItem.status, func.sum(TItem.n)).group_by(TItem.status))).all()) == {"open": 3, "done": 5})

    # ============================================================ session: identity, dirty tracking, transactions
    section("session: identity map, change detection, commit, rollback")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="a", name="Ann", score=1, data={"k": [1, 2]}, tags=["x"]))
        await s.commit()
    async with Sess() as s1, Sess() as s2:
        a1 = await s1.get(TUser, "a")
        ok("get returns the row", a1 is not None and a1.name == "Ann" and a1.data == {"k": [1, 2]})
        ok("get twice returns the same instance", await s1.get(TUser, "a") is a1)
        ok("get of a missing key is None", await s1.get(TUser, "zz") is None)
        ok("a stored datetime comes back timezone-aware UTC", a1.seen.tzinfo is not None and a1.seen.utcoffset() == dt.timedelta(0))
        a1.name = "Anna"
        a2 = await s2.get(TUser, "a")
        ok("an uncommitted change is invisible to another session", a2.name == "Ann")
        await s1.commit()
        ok("after commit the change is in the database", (await store.core.coll("t_users").find_one({"_id": "a"}))["name"] == "Anna")
        a1.data["k"].append(3)                                              # in place, NO flag_modified
        await s1.commit()
        ok("an in-place JSON edit is persisted without flag_modified", (await store.core.coll("t_users").find_one({"_id": "a"}))["data"] == {"k": [1, 2, 3]})
        store.flag_modified(a1, "data")
        ok("flag_modified exists and is harmless", True)
    async with Sess() as s1, Sess() as s2:
        a1 = await s1.get(TUser, "a")
        a2 = await s2.get(TUser, "a")
        a1.name = "ONE"
        a2.score = 99
        await s1.commit()
        await s2.commit()
        row = await store.core.coll("t_users").find_one({"_id": "a"})
        ok("only the changed columns are written: two sessions changing different columns both land", row["name"] == "ONE" and row["score"] == 99)
    async with Sess() as s:
        a = await s.get(TUser, "a")
        a.name = "temp"
        await s.rollback()
        ok("rollback puts a persistent instance back to what the database holds", a.name == "ONE")
        ok("rollback discards pending adds", True)
        s.add(TUser(id="gone"))
        await s.rollback()
        ok("a rolled-back add is not stored", await store.core.coll("t_users").find_one({"_id": "gone"}) is None)
    try:
        async with Sess() as s:
            s.add(TUser(id="boom"))
            await s.flush()
            raise RuntimeError("x")
    except RuntimeError:
        pass
    ok("an exception leaving `async with` rolls the flushed rows back", await store.core.coll("t_users").find_one({"_id": "boom"}) is None)
    async with Sess() as s:
        s.add(TUser(id="flushed"))
        await s.flush()
        ok("flush alone is not a commit: another session cannot see it", await store.core.coll("t_users").find_one({"_id": "flushed"}) is None)
        ok("the session sees its own flushed row (read-your-writes)", (await s.execute(select(func.count()).select_from(TUser).where(TUser.id == "flushed"))).scalar() == 1)
        await s.commit()
        ok("commit makes it visible", await store.core.coll("t_users").find_one({"_id": "flushed"}) is not None)
    async with Sess() as s:
        s.add(TUser(id="auto"))
        n = (await s.execute(select(func.count()).select_from(TUser).where(TUser.id == "auto"))).scalar()
        ok("a query autoflushes pending adds", n == 1)
        u = await s.get(TUser, "auto")
        u.score = 7
        ok("a query autoflushes pending changes", (await s.execute(select(TUser.id).where(TUser.score == 7))).scalars().all() == ["auto"])
        await s.commit()
    async with Sess() as s:
        u = await s.get(TUser, "auto")
        await s.delete(u)
        ok("delete is flushed by the next query", (await s.execute(select(func.count()).select_from(TUser).where(TUser.id == "auto"))).scalar() == 0)
        await s.commit()
        ok("delete is committed", await store.core.coll("t_users").find_one({"_id": "auto"}) is None)
    async with Sess() as s:
        x = TUser(id="never")
        s.add(x)
        await s.delete(x)
        await s.commit()
        ok("adding then deleting a pending row writes nothing", await store.core.coll("t_users").find_one({"_id": "never"}) is None)

    # ============================================================ unique indexes
    section("unique indexes: IntegrityError, partial indexes, composite keys")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="a"))
        s.add(TUser(id="b"))
        await s.commit()
    async with Sess() as s:
        s.add(TItem(user_id="a", client_key=None))
        s.add(TItem(user_id="a", client_key=None))
        s.add(TItem(user_id="a"))
        await s.commit()
        ok("a nullable unique column lets many NULLs through (partial index)", (await s.execute(select(func.count()).select_from(TItem))).scalar() == 3)
        s.add(TItem(user_id="a", client_key="k"))
        await s.commit()
        s.add(TItem(user_id="b", client_key="k"))
        await s.commit()
        ok("the same key for another user is fine", True)
        s.add(TItem(user_id="a", client_key="k"))
        err = await raises(IntegrityError, s.commit)
        ok("a duplicate (user, client_key) raises IntegrityError", err is not None)
        await s.rollback()
        ok("after the error the session is usable again and nothing of it was kept", (await s.execute(select(func.count()).select_from(TItem).where(TItem.client_key == "k"))).scalar() == 2)
    async with Sess() as s:
        s.add(TItem(user_id="a", client_key="one"))
        s.add(TItem(user_id="a", client_key="one"))
        err = await raises(IntegrityError, s.commit)
        ok("two duplicates in one flush: IntegrityError and the first is NOT kept (one transaction)", err is not None and await store.core.coll("t_items").count_documents({"client_key": "one"}) == 0)
        await s.rollback()
        s.add(TDay(user_id="a", day="2026-11-16", requests=1))
        await s.commit()
        s.add(TDay(user_id="a", day="2026-11-16", requests=2))
        ok("a duplicate composite primary key raises IntegrityError", await raises(IntegrityError, s.commit) is not None)
        await s.rollback()
        d = await s.get(TDay, ("a", "2026-11-16"))
        ok("get by composite key (tuple)", d is not None and d.requests == 1)
        ok("a missing composite key is None", await s.get(TDay, ("a", "2000-01-01")) is None)
        s.add(TWeek(user_id="a", week_start=dt.date(2026, 11, 16), xp=5))
        await s.commit()
        w = await s.get(TWeek, ("a", dt.date(2026, 11, 16)))
        ok("a composite key with a date part works (the date is a bound value)", w is not None and w.xp == 5 and w.week_start == dt.date(2026, 11, 16))
        ok("IntegrityError is a DBAPIError (existing `except DBAPIError` still catches it)", issubclass(IntegrityError, store.DBAPIError))
    async with Sess() as s:
        ok("a primary key with no value is a DataError", await raises(DataError, lambda: _add_commit(s, TDay(user_id="a", day=None))) is not None)
        await s.rollback()
        ok("a bad value is a DataError at flush", await raises(DataError, lambda: _add_commit(s, TUser(id="bad", score="five"))) is not None)
        await s.rollback()

    # ============================================================ update / delete / insert statements
    section("UPDATE / DELETE / INSERT statements")
    await wipe()
    async with Sess() as s:
        s.add(TUser(id="a"))
        for i in range(1, 6):
            s.add(TItem(user_id="a", n=i, status="open"))
        await s.commit()
    async with Sess() as s:
        loaded = (await s.execute(select(TItem).where(TItem.n <= 2).order_by(TItem.id))).scalars().all()
        r = await s.execute(update(TItem).where(TItem.n <= 2).values(status="done", label="x"))
        ok("update reports rowcount", r.rowcount == 2)
        ok("update synchronises instances already loaded (SQLAlchemy 'evaluate')", all(i.status == "done" and i.label == "x" for i in loaded))
        await s.commit()
        ok("update is committed", await store.core.coll("t_items").count_documents({"status": "done"}) == 2)
        ok("update with no match: rowcount 0", (await s.execute(update(TItem).where(TItem.n > 99).values(status="x"))).rowcount == 0)
        await s.execute(update(TItem).where(TItem.status == "open").values(n=TItem.n + 10))
        await s.commit()
        ok("update col = col + n increments atomically", sorted(d["n"] for d in await store.core.coll("t_items").find({"status": "open"}).to_list(None)) == [13, 14, 15])
        r = await s.execute(delete(TItem).where(TItem.status == "done"))
        ok("delete reports rowcount", r.rowcount == 2)
        await s.commit()
        ok("delete is committed", await store.core.coll("t_items").count_documents({}) == 3)
        a = (await s.execute(select(TItem).where(TItem.n == 13))).scalars().first()
        await s.execute(delete(TItem).where(TItem.n == 13))
        ok("a deleted row's loaded instance leaves the session", await s.get(TItem, a.id) is None)
        await s.commit()
    async with Sess() as s:                                                 # UPDATE ... RETURNING as an exactly-once claim
        r1 = await s.execute(update(TItem).where(TItem.n == 14, TItem.flag.is_(None)).values(flag=True).returning(TItem.id))
        r2 = await s.execute(update(TItem).where(TItem.n == 14, TItem.flag.is_(None)).values(flag=True).returning(TItem.id))
        await s.commit()
        ok("update ... returning claims once: the second try gets nothing", r1.scalar() is not None and r2.scalar() is None)
    async with Sess() as s:                                                 # INSERT ... ON CONFLICT
        s.add(TItem(user_id="a", client_key="ck", n=1))
        await s.commit()
        r = await s.execute(insert(TItem).values(user_id="a", client_key="ck", n=2).on_conflict_do_nothing(index_elements=["user_id", "client_key"]).returning(TItem.id))
        ok("insert ... on conflict do nothing: a duplicate returns no row and does not abort the session", r.scalar() is None)
        r = await s.execute(insert(TItem).values(user_id="a", client_key="ck2", n=3).on_conflict_do_nothing(index_elements=["user_id", "client_key"]).returning(TItem.id))
        new_id = r.scalar()
        ok("insert ... on conflict do nothing: a new row returns its id", new_id is not None)
        await s.commit()
        ck = await store.core.coll("t_items").find_one({"client_key": "ck"})
        ok("the existing row was left alone", ck["n"] == 1)
        ok("the inserted row has its defaults", (await store.core.coll("t_items").find_one({"client_key": "ck2"}))["status"] == "open")
    async with Sess() as s:
        await s.execute(insert(TDay).values(user_id="a", day="d1", requests=1).on_conflict_do_nothing(index_elements=["user_id", "day"]))
        await s.execute(insert(TDay).values(user_id="a", day="d1", requests=5).on_conflict_do_nothing(index_elements=["user_id", "day"]))
        await s.commit()
        ok("on conflict do nothing on a composite key keeps the first", (await store.core.coll("t_days").find_one({"user_id": "a", "day": "d1"}))["requests"] == 1)
        st = insert(TDay).values(user_id="a", day="d2", requests=1)
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded.requests}))
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded.requests}))
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded.requests}))
        await s.commit()
        ok("on conflict do update: insert, then increment twice", (await store.core.coll("t_days").find_one({"user_id": "a", "day": "d2"}))["requests"] == 3)
        st = insert(TDay).values(user_id="a", day="d3", requests=9)
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": st.excluded.requests}))
        await s.execute(insert(TDay).values(user_id="a", day="d3", requests=4).on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": 4}))
        await s.commit()
        ok("on conflict do update: set to a literal / the proposed value", (await store.core.coll("t_days").find_one({"user_id": "a", "day": "d3"}))["requests"] == 4)
    async with Sess() as s:                                                 # claim_one: atomic, outside any session
        for i in range(3):
            s.add(TItem(user_id="a", n=100 + i, status="scheduled"))
        await s.commit()
    got = [await claim_one(TItem, [TItem.status == "scheduled"], {"status": "sending"}, sort=[("n", 1)]) for _ in range(4)]
    ok("claim_one takes rows one at a time in sort order and then returns None", [g.n if g else None for g in got] == [100, 101, 102, None])
    ok("claim_one returns the row AFTER the update", all(g is None or g.status == "sending" for g in got))

    # ============================================================ foreign keys + the savepoint / advisory idioms
    section("foreign keys (app-level: Mongo has none) and insert_if_absent / advisory_lock")
    await wipe()
    async with Sess() as s:
        s.add(TItem(user_id="nobody"))
        err = await raises(IntegrityError, s.commit)
        await s.rollback()
        ok("a child whose parent does not exist is refused (IntegrityError), and nothing is stored", err is not None and await store.core.coll("t_items").count_documents({}) == 0)
        s.add(TItem(user_id="kid"))                                      # the child is added BEFORE its parent in the same flush ...
        s.add(TUser(id="kid"))
        await s.commit()
        ok("... and still works: parents are inserted before children (as SQLAlchemy's unit of work did)", await store.core.coll("t_items").count_documents({"user_id": "kid"}) == 1)
        err = await raises(IntegrityError, lambda: _del_user(s, "kid"))
        await s.rollback()
        ok("deleting a parent that still has children is refused (RESTRICT)", err is not None and await store.core.coll("t_users").find_one({"_id": "kid"}) is not None)
        err = await raises(IntegrityError, lambda: _bulk_del_users(s, ["kid"]))
        await s.rollback()
        ok("... also as a bulk DELETE", err is not None and await store.core.coll("t_users").find_one({"_id": "kid"}) is not None)
        await s.execute(delete(TItem).where(TItem.user_id == "kid"))
        await _del_user(s, "kid")
        await s.commit()
        ok("children first, then the parent, in one session: allowed", await store.core.coll("t_users").find_one({"_id": "kid"}) is None)
        s.add(TItem(user_id="kid"))
        ok("a parent deleted earlier in this session is no longer 'known to exist': a new child of it is refused", await raises(IntegrityError, s.commit) is not None)
        await s.rollback()
        s.add(TUser(id="k2"))
        await s.commit()
        s.add(TItem(user_id="k2"))
        await s.commit()                                                 # the parent is now 'known to exist' in this session
        await s.execute(delete(TItem).where(TItem.user_id == "k2"))
        await _del_user(s, "k2")
        await s.commit()
        s.add(TItem(user_id="k2"))
        ok("deleting the parent forgets that it was known: a child of it is refused right after", await raises(IntegrityError, s.commit) is not None)
        await s.rollback()
        err = await raises(IntegrityError, lambda: _upsert_orphan(s))
        await s.rollback()
        ok("an `insert ... on conflict` for a missing parent is refused too (the ledger relies on it for a deleted learner)", err is not None and await store.core.coll("t_days").count_documents({}) == 0)

        s.add(TUser(id="own"))
        await s.commit()
        a, b = TItem(user_id="own", client_key="k1", n=1), TItem(user_id="own", client_key="k1", n=2)
        ok("insert_if_absent: inserts when the key is free", await s.insert_if_absent(a, ["user_id", "client_key"]) is True and a.id is not None)
        ok("insert_if_absent: reports False when the key is taken, and leaves the new object out", await s.insert_if_absent(b, ["user_id", "client_key"]) is False and b._snap is None)
        await s.commit()
        row = await store.core.coll("t_items").find_one({"client_key": "k1"})
        ok("insert_if_absent: the first row is the one that stays", row["n"] == 1 and await store.core.coll("t_items").count_documents({"client_key": "k1"}) == 1)
        a.n = 5
        await s.commit()
        ok("insert_if_absent: the inserted object is persistent in the session (an edit is saved)", (await store.core.coll("t_items").find_one({"client_key": "k1"}))["n"] == 5)
        ok("insert_if_absent for a missing parent is an IntegrityError", await raises(IntegrityError, lambda: s.insert_if_absent(TItem(user_id="ghost", client_key="z"), ["user_id", "client_key"])) is not None)
        await s.rollback()
        st = insert(TDay).values(user_id="own", day="x", requests=2)
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded["requests"]}))
        await s.execute(st.on_conflict_do_update(index_elements=["user_id", "day"], set_={"requests": TDay.requests + st.excluded["requests"]}))
        await s.commit()
        ok("excluded['col'] (item access) works like excluded.col", (await store.core.coll("t_days").find_one({"user_id": "own", "day": "x"}))["requests"] == 4)

    # ============================================================ indexes
    section("indexes: creation is idempotent")
    before = await store.init()
    after = await store.init()
    ok("init() twice changes nothing", before == after)
    info = await store.core.coll("t_items").index_information()
    ok("the declared indexes exist", {"uq_t_items_client", "ix_t_items_user_status", "ix_t_items_user_id"} <= set(info))
    ok("the partial unique index kept its filter", info["uq_t_items_client"].get("partialFilterExpression") == {"client_key": {"$type": "string"}} and info["uq_t_items_client"].get("unique"))
    ok("the composite primary key became a unique index", info.get("x") is None and (await store.core.coll("t_days").index_information()).get("pk_t_days", {}).get("unique"))
    ok("the counters collection exists", "counters" in await store.core.database().list_collection_names())
    # a plain index whose definition changed is rebuilt; a changed unique one is refused
    from app.store.model import Index
    TWeek.__indexes__.append(Index("ix_t_weeks_xp", "-xp"))
    TWeek.__indexes__[:] = [i for i in TWeek.__indexes__ if not (i.name == "ix_t_weeks_xp" and i.cols == ["xp"])]
    await store.init([TWeek])
    ok("a changed plain index is replaced", (await store.core.coll("t_weeks").index_information())["ix_t_weeks_xp"]["key"] == [("xp", -1)])

    # ============================================================ guards
    section("configuration guards")
    import os
    keep = os.environ.get("DUSU_SCRATCH_ONLY")
    os.environ["DUSU_SCRATCH_ONLY"] = "1"
    try:
        ok("scratch-only refuses the shared Mongo", await raises(RuntimeError, lambda: _c(store.configure, "mongodb://u:p@rooted-mongo:27017/dusu?replicaSet=rs0")) is not None)
        ok("a postgres URL is refused with an explanation", await raises(RuntimeError, lambda: _c(store.configure, "postgresql://u:p@db/x")) is not None)
        ok("an empty URI means 'no database'", store.configure("") is False and not store.enabled())
    finally:
        if keep is None:
            os.environ.pop("DUSU_SCRATCH_ONLY", None)
        else:
            os.environ["DUSU_SCRATCH_ONLY"] = keep
        store.configure(os.environ["MONGODB_URI"])
    ok("a scratch host is accepted", store.configure(os.environ["MONGODB_URI"]) is True)


async def _c(fn, *a):
    fn(*a)


async def _ids(s, stmt, ordered=False, limit=None):
    rows = (await s.execute(stmt)).scalars().all()
    ids = [r.id for r in rows]
    return ids if ordered else sorted(ids)


async def _del_user(s, uid):
    u = await s.get(TUser, uid)
    await s.delete(u)
    await s.flush()


async def _bulk_del_users(s, ids):
    await s.execute(delete(TUser).where(TUser.id.in_(ids)))


async def _upsert_orphan(s):
    await s.execute(insert(TDay).values(user_id="ghost", day="d", requests=1).on_conflict_do_nothing(index_elements=["user_id", "day"]))
    await s.commit()


async def _add_commit(s, obj):
    s.add(obj)
    await s.commit()


run(main)
