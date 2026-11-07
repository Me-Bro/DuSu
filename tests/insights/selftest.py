"""Insights - tier 2: the real HTTP layer on a SCRATCH Postgres (run via tests/insights/run.sh selftest.py - it starts a throwaway postgres, never `dusu-db-1`,
and blanks every provider key).

What is proven, in the order it is driven:
  * the old -> new schema rehearsal: production has no ev_* / plan_interest table; init_db() adds exactly those, twice in a row, next to existing data;
  * POST /ev: needs a login; records only the three CLIENT events; a server-only or unknown name is dropped silently (a browser cannot fake a milestone); always a quiet
    204; idempotent (a repeat, a restart, 25 at once = one row); rate limited; the kill switch stops it; two learners never touch each other's rows;
  * the server-side hooks: GET /me records the active day once per day; a key saved through /keys/save records key1 then key2 (and a failed save records nothing);
  * "Reserve my plan": validation (a plan outside the three, a bad price opinion, wrong types), idempotent, a later opinion replaces a blank one but never erases one,
    GET returns only the caller's own, isolation between learners, a blocked account is refused, a rate limit, and plan_reserved is recorded;
  * the owner's funnel: the cohort rule (only learners who signed up after tracking began), per-step counts, Day-1 / Day-7 return computed exactly, plan interest, an empty
    database, clamped `days`, owner-only;
  * data rights: deleting an account and the owner's wipe remove every row (and the in-memory memory of it);
  * failure isolation: a database that fails never raises into a request;
  * GET /: ETag + `no-cache`, 304 on a match (strong, weak, list), 200 on a mismatch, a new ETag when the file changes; versioned assets are immutable, the rest are not.
Plain Python; prints PASS / FAIL per check and exits non-zero on any failure.
"""

import asyncio
import re
import datetime as dt
import sys

sys.path.insert(0, "/app")

import httpx                                                        # noqa: E402
from sqlalchemy import func, select, text as sa_text, update as sa_update   # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.insights import models as IM, service as svc              # noqa: E402
from app.keys import service as keys_svc                            # noqa: E402

FAILS: list = []
N = 0
UTC = dt.timezone.utc
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:400]}")


def section(t):
    print(f"\n== {t}")


async def count(model, *conds):
    async with db._Session() as s:
        return int((await s.execute(select(func.count()).select_from(model).where(*conds))).scalar() or 0)


async def rows(model, *conds):
    async with db._Session() as s:
        return (await s.execute(select(model).where(*conds))).scalars().all()


async def drain():
    """Wait for the fire-and-forget hooks (insights.spawn) to finish."""
    for _ in range(50):
        pending = [t for t in list(svc._tasks) if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0.05)


async def ms(uid):
    return sorted(r.name for r in await rows(IM.EvMilestone, IM.EvMilestone.user_id == uid))


async def days(uid):
    return sorted(r.day for r in await rows(IM.EvDay, IM.EvDay.user_id == uid))


def ist_noon(days_ago):
    d = dt.datetime.now(IST).date() - dt.timedelta(days=days_ago)
    return dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=IST)


def ist_day(days_ago):
    return (dt.datetime.now(IST).date() - dt.timedelta(days=days_ago)).isoformat()


names = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ida", "ivy", "jon", "kim", "lee", "max", "mia"]
uid = lambda n: f"u-{n}"                                            # noqa: E731


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh, which blanks them"

    # ------------------------------------------------------------------ OLD -> NEW schema rehearsal
    section("schema rehearsal: production has every table EXCEPT the three new ones")
    NEW = {"ev_milestones", "ev_days", "plan_interest"}
    for _ in range(20):                                              # a freshly started postgres restarts once after initdb
        try:
            async with db._engine.begin() as conn:
                await conn.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if t.name not in NEW]))
            break
        except Exception:
            await asyncio.sleep(1)

    async def new_tables():
        async with db._engine.connect() as conn:
            return {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and (table_name like 'ev\\_%' or table_name = 'plan_interest')"))).all()}

    pre = await new_tables()
    old = {"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""}
    await db.login(old)
    check("the old schema has none of the three tables, and an existing learner", pre == set() and await count(db.User, db.User.id == "u-old") == 1, pre)
    await db.init_db()
    await db.init_db()
    post = await new_tables()
    async with db._engine.connect() as conn:
        idx = {r[0] for r in (await conn.execute(sa_text("select indexname from pg_indexes where tablename in ('ev_milestones', 'ev_days', 'plan_interest')"))).all()}
        fks = (await conn.execute(sa_text("select count(*) from information_schema.table_constraints where constraint_type = 'FOREIGN KEY' and table_name in ('ev_milestones', 'ev_days', 'plan_interest')"))).scalar()
    check("init_db() adds exactly the three new tables, twice in a row", post == NEW, post)
    check("the funnel indexes exist and every table references the learner", {"ix_ev_milestones_name", "ix_ev_days_day"} <= idx and fks == 3, (idx, fks))
    check("the existing learner is untouched", await count(db.User, db.User.id == "u-old") == 1)

    # ------------------------------------------------------------------ users + client
    users = {n: {"sub": uid(n), "email": f"{n}@example.com", "name": f"{n.title()} Lee", "picture": ""} for n in names}
    for u in users.values():
        await db.login(u)
    T = {n: auth.make_session(u) for n, u in users.items()}
    owner = {"sub": "u-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    await db.login(owner)
    T["owner"] = auth.make_session(owner)
    await db.set_setting("key_health", "on")
    await db.set_setting("key_health", "on")
    M.invalidate_access_cache()
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        async def api(who, method, path, body=None, params=None, headers=None):
            h = dict(headers or {})
            if who:
                h["Authorization"] = "Bearer " + T[who]
            return await c.request(method, path, json=body, params=params, headers=h)

        # -------------------------------------------------------------- POST /ev
        section("POST /ev: a beacon for the three screens only a client can know")
        r = await c.post("/ev", json={"name": "keys_seen"})
        check("no login: 401", r.status_code == 401, r.status_code)
        r = await api("ann", "POST", "/ev", {"name": "keys_seen"})
        await drain()
        check("keys_seen: a quiet 204 with no body", r.status_code == 204 and r.content == b"", (r.status_code, r.content))
        check("... and it is recorded for that learner", await ms(uid("ann")) == ["keys_seen"], await ms(uid("ann")))
        for nm in ("plans_seen", "install_accepted"):
            await api("ann", "POST", "/ev", {"name": nm})
        await drain()
        check("the other two client events are recorded", await ms(uid("ann")) == ["install_accepted", "keys_seen", "plans_seen"], await ms(uid("ann")))
        for nm in ("first_session", "key1_saved", "key2_saved", "first_sentence", "plan_reserved", "keys_sene", "KEYS_SEEN", "", "x" * 200, "keys_seen; drop table users", None, 5, ["keys_seen"]):
            r = await api("bob", "POST", "/ev", {"name": nm})
            check(f"a server-only / unknown name is dropped silently, still 204 ({str(nm)[:24]!r})", r.status_code == 204, r.status_code)
        await drain()
        check("... and NOTHING was recorded for those (a browser cannot fake a milestone)", await ms(uid("bob")) == [], await ms(uid("bob")))
        for body in (None, {}, [], "text", {"name": {"a": 1}}):
            r = await c.post("/ev", json=body, headers={"Authorization": "Bearer " + T["bob"]})
            check(f"a malformed body is a quiet 204 or a validation 422, never a 5xx ({body!r})", r.status_code in (204, 422), r.status_code)
        before = await count(IM.EvMilestone)
        for _ in range(3):
            await api("ann", "POST", "/ev", {"name": "keys_seen"})
        await drain()
        check("a repeated beacon is one row", await count(IM.EvMilestone, IM.EvMilestone.user_id == uid("ann"), IM.EvMilestone.name == "keys_seen") == 1 and await count(IM.EvMilestone) == before)
        first_at = (await rows(IM.EvMilestone, IM.EvMilestone.user_id == uid("ann"), IM.EvMilestone.name == "keys_seen"))[0].first_at
        svc._seen.clear()                                            # a restart: the in-memory memory is gone
        await api("ann", "POST", "/ev", {"name": "keys_seen"})
        await drain()
        row = (await rows(IM.EvMilestone, IM.EvMilestone.user_id == uid("ann"), IM.EvMilestone.name == "keys_seen"))
        check("after a restart the database still holds ONE row and the ORIGINAL time (first time wins)", len(row) == 1 and row[0].first_at == first_at)
        res = await asyncio.gather(*[svc.milestone(uid("cat"), "keys_seen") for _ in range(25)])
        check("25 at once: exactly one wrote, one row", res.count(True) == 1 and await count(IM.EvMilestone, IM.EvMilestone.user_id == uid("cat")) == 1, (res.count(True), res.count(False)))
        check("another learner is not touched by any of this", await ms(uid("dan")) == [])

        calls = []
        real = svc.milestone

        async def spy(u, n):
            calls.append((u, n))
            return await real(u, n)
        svc.milestone = spy
        try:
            codes = [(await api("eve", "POST", "/ev", {"name": "keys_seen"})).status_code for _ in range(45)]
        finally:
            svc.milestone = real
        check("the rate limit (30 a minute per learner) stops the surplus reaching the service, and every answer is still 204", len(calls) == 30 and set(codes) == {204}, (len(calls), set(codes)))

        await db.set_setting("insights", "off")
        M.invalidate_access_cache()
        r = await api("fay", "POST", "/ev", {"name": "keys_seen"})
        await drain()
        check("the kill switch: still a quiet 204, nothing recorded", r.status_code == 204 and await ms(uid("fay")) == [])
        await db.set_setting("insights", "on")
        M.invalidate_access_cache()
        await api("fay", "POST", "/ev", {"name": "keys_seen"})
        await drain()
        check("switched back on: recording resumes", await ms(uid("fay")) == ["keys_seen"])

        # -------------------------------------------------------------- the server-side hooks
        section("the server-side hooks: the active day and the keys")
        real_day = M._quota_day
        M._quota_day = lambda: "2026-10-30"
        for _ in range(3):
            await api("gus", "GET", "/me")
        await drain()
        check("GET /me records the active day - once, however many times the app asks", await days(uid("gus")) == ["2026-10-30"], await days(uid("gus")))
        M._quota_day = lambda: "2026-10-31"
        await api("gus", "GET", "/me")
        await drain()
        check("the next day adds one more row", await days(uid("gus")) == ["2026-10-30", "2026-10-31"], await days(uid("gus")))
        await db.set_setting("insights", "off")
        M.invalidate_access_cache()
        M._quota_day = lambda: "2026-11-01"
        await api("hal", "GET", "/me")
        await drain()
        check("with the kill switch off /me records nothing", await days(uid("hal")) == [])
        await db.set_setting("insights", "on")
        M.invalidate_access_cache()
        check("an unauthenticated /me records nothing and is still a 401", (await c.get("/me")).status_code == 401)
        M._quota_day = real_day

        async def fake_verify(u, provider, key):                     # stands in for the live provider call: a key containing "good" passes, anything else is rejected
            if "good" in key:
                await keys_svc._locked_update(u, lambda d: {**d, provider: key})
                return {"ok": True, "provider": provider}
            return {"ok": False, "provider": provider}
        real_vs = keys_svc.verify_and_save
        keys_svc.verify_and_save = fake_verify
        try:
            r = await api("ida", "POST", "/keys/save", {"provider": "groq", "key": "gsk_bad" + "x" * 30})
            await drain()
            check("a key that failed verification records nothing", r.status_code == 200 and await ms(uid("ida")) == [], (r.status_code, await ms(uid("ida"))))
            ok_key = "gsk_good" + "x" * 30
            r = await api("ida", "POST", "/keys/save", {"provider": "groq", "key": ok_key})
            await drain()
            check("the first stored key records key1_saved", r.status_code == 200 and await ms(uid("ida")) == ["key1_saved"], (r.status_code, r.text[:200], await ms(uid("ida"))))
            r = await api("ida", "POST", "/keys/save", {"provider": "gemini", "key": "AIzagood" + "y" * 30})
            await drain()
            check("the second stored key records key2_saved (and key1 stays)", await ms(uid("ida")) == ["key1_saved", "key2_saved"], await ms(uid("ida")))
            await api("ida", "POST", "/keys/save", {"provider": "groq", "key": ok_key})
            await drain()
            check("saving again does not duplicate", await ms(uid("ida")) == ["key1_saved", "key2_saved"])
        finally:
            keys_svc.verify_and_save = real_vs

        # -------------------------------------------------------------- Reserve my plan
        section("Reserve my plan: POST + GET /plans/interest")
        r = await c.post("/plans/interest", json={"plan": "pro"})
        check("no login: 401", r.status_code == 401)
        r = await c.get("/plans/interest")
        check("GET without a login: 401", r.status_code == 401)
        for body, label in (({"plan": "free"}, "free is not a reservable plan"), ({"plan": ""}, "blank"), ({}, "missing"), ({"plan": ["pro"]}, "a list"), ({"plan": "pro; --"}, "SQL-ish"),
                            ({"plan": "pro", "price_feel": "cheap"}, "an unknown price opinion"), ({"plan": "pro", "price_feel": []}, "a list for the opinion"), ({"plan": 7}, "a number")):
            r = await api("jon", "POST", "/plans/interest", body)
            check(f"{label}: 422, nothing stored", r.status_code == 422 and await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("jon")) == 0, (r.status_code, r.text[:120]))
        r = await api("jon", "POST", "/plans/interest", {"plan": "Plus"})
        j = r.json()
        check("a valid reservation is stored (case-insensitive) and returned", r.status_code == 200 and j["ok"] is True and j["reserved"] == [{"plan": "plus", "price_feel": ""}], (r.status_code, r.text[:200]))
        r = await api("jon", "POST", "/plans/interest", {"plan": "plus"})
        check("tapping twice is one row", await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("jon")) == 1)
        r = await api("jon", "POST", "/plans/interest", {"plan": "plus", "price_feel": "too_high"})
        check("a price opinion is added to the existing row", r.json()["reserved"] == [{"plan": "plus", "price_feel": "too_high"}], r.text[:200])
        r = await api("jon", "POST", "/plans/interest", {"plan": "plus"})
        check("a later tap with no opinion never erases the opinion", r.json()["reserved"] == [{"plan": "plus", "price_feel": "too_high"}], r.text[:200])
        r = await api("jon", "POST", "/plans/interest", {"plan": "plus", "price_feel": "fair"})
        check("a new opinion replaces the old one", r.json()["reserved"] == [{"plan": "plus", "price_feel": "fair"}], r.text[:200])
        r = await api("jon", "POST", "/plans/interest", {"plan": "starter"})
        check("a second plan is a second row", [x["plan"] for x in r.json()["reserved"]] == ["plus", "starter"], r.text[:200])
        await drain()
        check("plan_reserved is recorded", "plan_reserved" in await ms(uid("jon")), await ms(uid("jon")))
        r = await api("jon", "GET", "/plans/interest")
        check("GET returns the caller's own reservations", r.status_code == 200 and {x["plan"] for x in r.json()["reserved"]} == {"plus", "starter"}, r.text[:200])
        r = await api("kim", "GET", "/plans/interest")
        check("another learner sees NONE of them", r.status_code == 200 and r.json()["reserved"] == [], r.text[:200])
        r = await api("kim", "POST", "/plans/interest", {"plan": "pro"})
        r2 = await api("jon", "GET", "/plans/interest")
        check("and a reservation by another learner never lands in this one's list", {x["plan"] for x in r2.json()["reserved"]} == {"plus", "starter"})
        await db.set_user_status(uid("lee"), "blocked")
        r = await api("lee", "POST", "/plans/interest", {"plan": "pro"})
        check("a blocked account is refused (403) and nothing is stored", r.status_code == 403 and await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("lee")) == 0, r.status_code)
        codes = [(await api("max", "POST", "/plans/interest", {"plan": "pro"})).status_code for _ in range(15)]
        check("the rate limit (12 a minute) answers 429 for the surplus", codes[:12] == [200] * 12 and codes[12:] == [429] * 3, codes)
        r = await c.post("/plans/interest", json={"plan": "pro", "user_id": uid("ann")}, headers={"Authorization": "Bearer " + T["mia"]})
        check("a body field cannot redirect a reservation to another learner", await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("ann")) == 0 and await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("mia")) == 1)

        # -------------------------------------------------------------- the owner's funnel
        section("the owner's funnel")
        r = await c.get("/admin/funnel")
        check("no login: 401", r.status_code == 401, r.status_code)
        r = await api("ann", "GET", "/admin/funnel")
        check("a normal learner: 403", r.status_code == 403, r.status_code)
        async with db._Session() as s:                               # a clean slate for exact numbers
            for m in (IM.EvMilestone, IM.EvDay, IM.PlanInterest):
                await s.execute(m.__table__.delete())
            await s.commit()
        r = await api("owner", "GET", "/admin/funnel")
        j = r.json()
        check("an empty funnel is zeros and Nones - no division by zero", r.status_code == 200 and j["tracking_since"] is None and all(m["learners"] == 0 for m in j["milestones"]) and j["retention"]["d1"]["pct"] is None or j["cohort"] > 0, r.text[:300])
        async with db._Session() as s:                               # everyone not in the scenario below signed up long ago, so they are outside the window
            for n in names:
                u = await s.get(db.User, uid(n))
                u.created_at = ist_noon(400)
            for other in ("u-owner", "u-old"):
                u = await s.get(db.User, other)
                u.created_at = ist_noon(400)
            await s.commit()
        svc._seen.clear()
        svc._day_seen.clear()
        check("the funnel lists every step with its label, in order", [m["name"] for m in j["milestones"]] == list(svc.FUNNEL_ORDER) and all(m["label"] for m in j["milestones"]))

        # cohort: A, B, C signed up 10 days ago; D, E 3 days ago; P 20 days ago (before tracking began); O 40 days ago (outside the window)
        cohort = {"ann": 10, "bob": 10, "cat": 10, "dan": 3, "eve": 3, "fay": 20, "gus": 40}
        async with db._Session() as s:
            for n, ago in cohort.items():
                u = await s.get(db.User, uid(n))
                u.created_at = ist_noon(ago)
            await s.commit()

        async def put_ms(n, name, ago):
            async with db._Session() as s:
                s.add(IM.EvMilestone(user_id=uid(n), name=name, first_at=ist_noon(ago) + dt.timedelta(hours=1)))
                await s.commit()

        async def put_day(n, ago):
            async with db._Session() as s:
                s.add(IM.EvDay(user_id=uid(n), day=ist_day(ago)))
                await s.commit()
        await put_ms("fay", "key1_saved", 12)                         # the earliest event: tracking began 12 days ago, so Fay (signed up 20 days ago) cannot be in the cohort
        for name in ("keys_seen", "key1_saved", "key2_saved", "first_sentence", "first_session"):
            await put_ms("ann", name, 10)
        for name in ("keys_seen", "key1_saved"):
            await put_ms("bob", name, 10)
        await put_ms("cat", "keys_seen", 10)
        for name in ("keys_seen", "key1_saved"):
            await put_ms("dan", name, 3)
        await put_day("ann", 9)      # D1
        await put_day("ann", 3)      # D7
        await put_day("ann", 0)      # today
        await put_day("bob", 9)      # D1
        await put_day("bob", 0)      # today
        await put_day("dan", 2)      # D1
        await put_day("cat", 5)      # active, but neither on day 1 nor day 7
        r = await api("owner", "GET", "/admin/funnel", params={"days": 30})
        j = r.json()
        by = {m["name"]: m for m in j["milestones"]}
        check("the cohort is the learners who signed up after tracking began (Ann, Bob, Cat, Dan, Eve) - not Fay (before), not Gus (outside the window)", j["cohort"] == 5 and j["signups_in_window"] == 6, (j["cohort"], j["signups_in_window"]))
        check("the step counts count the cohort only (Fay's early key is not in them)",
              [by[k]["learners"] for k in ("keys_seen", "key1_saved", "key2_saved", "first_sentence", "first_session")] == [4, 3, 1, 1, 1], {k: v["learners"] for k, v in by.items()})
        check("a step's percentage is of the cohort", by["keys_seen"]["pct"] == 80.0 and by["key1_saved"]["pct"] == 60.0 and by["key2_saved"]["pct"] == 20.0, by["keys_seen"])
        check("Day-1 return: eligible = the five whose day 1 has passed, returned = Ann, Bob, Dan", j["retention"]["d1"] == {"eligible": 5, "returned": 3, "pct": 60.0}, j["retention"]["d1"])
        check("Day-7 return: eligible = the three who signed up 10 days ago, returned = Ann only (Cat was active on day 5, not day 7)", j["retention"]["d7"] == {"eligible": 3, "returned": 1, "pct": 33.3}, j["retention"]["d7"])
        check("active today = Ann + Bob; the last 7 days = Ann, Bob, Dan (2 days ago) and Cat (5 days ago)", j["active"]["today"] == 2 and j["active"]["last_7_days"] == 4, j["active"])
        check("tracking_since is the time of the earliest recorded event", j["tracking_since"] is not None and dt.datetime.fromisoformat(j["tracking_since"]) == ist_noon(12) + dt.timedelta(hours=1), j["tracking_since"])
        await api("jon", "POST", "/plans/interest", {"plan": "pro", "price_feel": "great"})
        await api("kim", "POST", "/plans/interest", {"plan": "pro", "price_feel": "too_high"})
        await api("mia", "POST", "/plans/interest", {"plan": "starter"})      # (max is rate limited for the rest of this minute by the check above)
        j = (await api("owner", "GET", "/admin/funnel")).json()
        check("plan interest per plan, with the price opinions", j["plans"]["pro"] == {"learners": 2, "too_high": 1, "fair": 0, "great": 1} and j["plans"]["starter"]["learners"] == 1 and j["plans"]["plus"]["learners"] == 0, j["plans"])
        for d_, want in ((0, 1), (-5, 1), (9999, 365), ("abc", None)):
            r = await api("owner", "GET", "/admin/funnel", params={"days": d_})
            if want is None:
                check("a junk `days` is a validation error, not a crash", r.status_code == 422, r.status_code)
            else:
                check(f"days={d_} is clamped to {want}", r.status_code == 200 and r.json()["window_days"] == want, (r.status_code, r.text[:100]))

        # -------------------------------------------------------------- Ranks (audit UI-12)
        section("Ranks: only learners with XP are on the board (a brand-new account with 0 XP is not)")
        async with db._Session() as s:
            for who, xp_ in (("cat", 120), ("dan", 0), ("eve", 5)):
                await s.execute(sa_update(db.Progress).where(db.Progress.user_id == uid(who)).values(xp=xp_))
            await s.commit()
        lb = await db.leaderboard(uid("dan"))
        top_names = [r["alias"] for r in lb["top"]]
        check("the all-time board lists the learners with XP, best first, and never a 0-XP account", [r["xp"] for r in lb["top"]] == sorted([r["xp"] for r in lb["top"]], reverse=True) and all(r["xp"] > 0 for r in lb["top"]) and len(lb["top"]) >= 2, lb["top"])
        check("the podium cannot show 0 XP: the 0-XP learner is not in `top`", db._alias(uid("dan")) not in top_names, top_names)
        check("... but the learner still sees their own row, pinned, with the true rank (everyone with XP is above them)", lb["you"] and lb["you"]["xp"] == 0 and lb["you"]["rank"] == len(lb["top"]) + 1, lb["you"])
        r = await api("dan", "GET", "/leaderboard")
        check("over HTTP: 200, only learners with XP in `top`, the caller's own row in `you`", r.status_code == 200 and all(x["xp"] > 0 for x in r.json()["top"]) and r.json()["you"]["xp"] == 0, r.text[:300])
        r = await api("cat", "GET", "/leaderboard")
        check("a learner with XP is on the board and flagged as the caller", any(x["is_me"] for x in r.json()["top"]), r.text[:300])

        # -------------------------------------------------------------- the counters are today's (visual review VR-9)
        section("the counters are today's: a streak that died is 0, yesterday's sessions are not today's, and a read never writes")
        ist_today = dt.datetime.now(IST).date()

        async def stamp(last_days_ago):
            async with db._Session() as s:
                await s.execute(sa_update(db.Profile).where(db.Profile.user_id == uid("cat")).values(onboarded=True))
                await s.execute(sa_update(db.Progress).where(db.Progress.user_id == uid("cat")).values(streak_days=4, sessions_today=2, last_active=ist_today - dt.timedelta(days=last_days_ago)))
                await s.commit()

        async def mine():
            me = (await api("cat", "GET", "/me")).json()
            dash = (await api("owner", "GET", "/admin/overview")).json()
            row = next((u for u in dash.get("users", []) if u["id"] == uid("cat")), {})
            return me, row

        await stamp(8)
        me, row = await mine()
        check("last practised 8 days ago: /me says streak 0 and 0 sessions today (4 and 2 are stored)", me["progress"]["streak_days"] == 0 and me["progress"]["sessions_today"] == 0, me.get("progress"))
        check("... the growth block the Home chip reads says streak 0", (me.get("growth") or {}).get("streak") == 0, me.get("growth"))
        check("... and the owner's dashboard card says the same", row.get("streak_days") == 0 and row.get("sessions_today") == 0, row)
        async with db._Session() as s:
            stored = (await s.get(db.Progress, uid("cat")))
            check("reading the numbers never rewrites the stored ones (still 4 and 2)", stored.streak_days == 4 and stored.sessions_today == 2, (stored.streak_days, stored.sessions_today))
        await stamp(1)
        me, row = await mine()
        check("practised yesterday: the streak lives (4), today starts at 0 sessions - in /me, in growth and on the dashboard", me["progress"]["streak_days"] == 4 and me["progress"]["sessions_today"] == 0 and (me.get("growth") or {}).get("streak") == 4 and row.get("streak_days") == 4 and row.get("sessions_today") == 0, (me.get("progress"), me.get("growth"), row))
        await stamp(0)
        me, row = await mine()
        check("practised today: the stored numbers stand (4 and 2) everywhere", me["progress"]["streak_days"] == 4 and me["progress"]["sessions_today"] == 2 and (me.get("growth") or {}).get("streak") == 4 and row.get("streak_days") == 4 and row.get("sessions_today") == 2, (me.get("progress"), me.get("growth"), row))

        # -------------------------------------------------------------- data rights
        section("data rights: deleting an account or wiping removes every row")
        await svc.milestone(uid("hal"), "keys_seen")
        await svc.touch_day(uid("hal"), "2026-10-01")
        await svc.reserve_plan(uid("hal"), "pro", "fair")
        check("a learner with all three kinds of row", await ms(uid("hal")) == ["keys_seen"] and await days(uid("hal")) == ["2026-10-01"] and await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("hal")) == 1)
        check("... and the in-memory memory of them", (uid("hal"), "keys_seen") in svc._seen and uid("hal") in svc._day_seen)
        await db.delete_user(uid("hal"))
        check("delete_user removes every row from the three tables", await ms(uid("hal")) == [] and await days(uid("hal")) == [] and await count(IM.PlanInterest, IM.PlanInterest.user_id == uid("hal")) == 0)
        check("... and forgets them in memory", (uid("hal"), "keys_seen") not in svc._seen and uid("hal") not in svc._day_seen)
        await db.login(users["hal"])
        check("the same person signing up again can record the milestone afresh", await svc.milestone(uid("hal"), "keys_seen") is True)
        n_before = await count(IM.EvMilestone)
        wiped = await db.admin_wipe_users({"david123rana@gmail.com"})
        check("the owner's wipe removes everyone's rows (and keeps the owner's)", wiped > 0 and await count(IM.EvMilestone) == 0 and await count(IM.EvDay) == 0 and await count(IM.PlanInterest) == 0, (wiped, n_before))

        # -------------------------------------------------------------- failure isolation
        section("a failing database never raises into a request")
        await db.login(users["ann"])
        await db.login(owner)
        T["ann"] = auth.make_session(users["ann"])
        failed_before = svc.failures()
        check("an unknown learner (a foreign key that cannot be satisfied) is False, counted, not raised", await svc.milestone("u-ghost", "keys_seen") is False and svc.failures() == failed_before + 1)
        check("the same for the active day", await svc.touch_day("u-ghost", "2026-10-30") is False and svc.failures() == failed_before + 2)
        check("a name outside the allow-list is False and not even counted as a failure", await svc.milestone(uid("ann"), "made_up") is False and svc.failures() == failed_before + 2)
        check("no learner / no day: False", await svc.milestone(None, "keys_seen") is False and await svc.touch_day(uid("ann"), "") is False and await svc.touch_day(None, "2026-10-30") is False)
        real_sess = db._Session

        def boom(*a, **k):
            raise RuntimeError("database is down")
        db._Session = boom
        try:
            r = await api("ann", "POST", "/ev", {"name": "plans_seen"})
            check("POST /ev with the database down is still a quiet 204", r.status_code == 204, r.status_code)
            check("milestone() with the database down returns False and counts a failure", await svc.milestone(uid("ann"), "keys_seen") is False)
            M._ev(uid("ann"), "first_sentence")                     # the fire-and-forget hook: must not raise or hang
            await drain()
        finally:
            db._Session = real_sess
        check("after the database is back, recording works again", await svc.milestone(uid("ann"), "plans_seen") is True)
        check("a first active day is written once", await svc.touch_day(uid("ann"), "2026-12-01") is True)
        db._Session = boom
        try:
            fb = svc.failures()
            check("a milestone the process already knows never touches the database (a set lookup on the hot path)", await svc.milestone(uid("ann"), "plans_seen") is False and svc.failures() == fb)
            check("neither does an active day it already knows", await svc.touch_day(uid("ann"), "2026-12-01") is False and svc.failures() == fb)
        finally:
            db._Session = real_sess

        # -------------------------------------------------------------- GET / and /assets
        section("GET /: validators, 304, and the cache headers of versioned assets")
        r = await c.get("/")
        etag = r.headers.get("etag")
        check("GET / is 200 with an ETag and Cache-Control: no-cache (keep a copy, but ask first)", r.status_code == 200 and etag and re.fullmatch(r'W/"[0-9a-f]{24}"', etag) is not None and r.headers.get("cache-control") == "no-cache", (r.status_code, dict(r.headers)))
        check("the ETag is WEAK (Cloudflare drops a strong one when it re-encodes the page - measured live 2026-10-31 - so no browser would ever hold it and repeat opens could never be a 304)", etag.startswith('W/"'), etag)
        check("the body is the page with its config injected", "<title>DuSu" in r.text and "__AUTH_ENABLED__" not in r.text and 'const GOOGLE_CLIENT_ID = "ins-client"' in r.text)
        _mail_re = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|mailto:"
        _markup = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", "", r.text, flags=re.S | re.I)
        check("the page's MARKUP carries no email address and no mailto: link (Cloudflare rewrites one, injects a blocking decoder script ahead of the app's script and drops the page's ETag - measured live 2026-10-31)", not re.search(_mail_re, _markup, re.I), re.findall(_mail_re, _markup, re.I)[:4])
        r2 = await c.get("/", headers={"If-None-Match": etag})
        check("If-None-Match with the same tag: 304, no body, the validators repeated", r2.status_code == 304 and r2.content == b"" and r2.headers.get("etag") == etag and r2.headers.get("cache-control") == "no-cache", (r2.status_code, len(r2.content)))
        r3 = await c.get("/", headers={"If-None-Match": etag[2:]})
        check("a STRONG copy of the tag (an older client, or a proxy that normalises it): 304", r3.status_code == 304, r3.status_code)
        r4 = await c.get("/", headers={"If-None-Match": '"nope", ' + etag})
        check("a list that contains it: 304", r4.status_code == 304, r4.status_code)
        r4b = await c.get("/", headers={"If-None-Match": 'W/"nope"'})
        check("a different WEAK tag: 200 with the full page", r4b.status_code == 200 and len(r4b.content) > 100000, r4b.status_code)
        r5 = await c.get("/", headers={"If-None-Match": '"nope"'})
        check("a different tag: 200 with the full page", r5.status_code == 200 and len(r5.content) > 100000, (r5.status_code, len(r5.content)))
        r6 = await c.get("/", headers={"If-None-Match": "*"})
        check("* : 304", r6.status_code == 304, r6.status_code)
        r7 = await c.get("/", headers={"Accept": "text/html", "If-None-Match": ""})
        check("an empty If-None-Match: 200", r7.status_code == 200)
        f = await c.get("/assets/fonts/inter-latin-v1.woff2")
        check("a versioned font: 200, woff2, cacheable for a year and immutable", f.status_code == 200 and f.headers.get("cache-control") == "public, max-age=31536000, immutable" and len(f.content) > 10000 and f.content[:4] == b"wOF2", (f.status_code, dict(f.headers)))
        check("... and it says what it is: font/woff2 (the slim image has no mime table; Starlette would answer text/plain)", f.headers.get("content-type") == "font/woff2", f.headers.get("content-type"))
        f = await c.get("/assets/icons/dusu-logo-300-v1.webp")
        check("the small logo: 200, immutable, and under 40 KB (the old one was 1.7 MB)", f.status_code == 200 and "immutable" in f.headers.get("cache-control", "") and len(f.content) < 40000, (f.status_code, len(f.content)))
        check("... and it is image/webp (not text/plain)", f.headers.get("content-type") == "image/webp", f.headers.get("content-type"))
        f = await c.get("/assets/icons/dusu-192-v1.png")
        check("the install icon: 200, image/png, immutable", f.status_code == 200 and f.headers.get("content-type") == "image/png" and "immutable" in f.headers.get("cache-control", ""), dict(f.headers))
        f = await c.get("/assets/assistant/idle.png")
        check("an unversioned asset keeps the default (no immutable)", f.status_code == 200 and "immutable" not in f.headers.get("cache-control", ""), dict(f.headers))
        # the other doors to the same shell: the SPA fallback (every deep link) and a signed-out visit to two routes that are also API paths
        for deep in ("/my-day", "/resume-interview/match", "/practice-room", "/some/unknown/screen"):
            d1 = await c.get(deep)
            check(f"a deep link ({deep}) is the shell, with the same validators", d1.status_code == 200 and d1.headers.get("etag") == etag and d1.headers.get("cache-control") == "no-cache" and "<title>DuSu" in d1.text, (d1.status_code, dict(d1.headers)))
            d2 = await c.get(deep, headers={"If-None-Match": etag})
            check(f"... and re-opening it is a 304 ({deep})", d2.status_code == 304 and d2.content == b"", d2.status_code)
        for api_path in ("/leaderboard", "/league"):
            n1 = await c.get(api_path, headers={"Sec-Fetch-Mode": "navigate", "Accept": "text/html"})
            check(f"a signed-out NAVIGATION to {api_path} is the shell", n1.status_code == 200 and n1.headers.get("etag") == etag and "<title>DuSu" in n1.text, (n1.status_code, n1.headers.get("content-type")))
            n2 = await c.get(api_path, headers={"Sec-Fetch-Mode": "navigate", "Accept": "text/html", "If-None-Match": etag})
            check(f"... and it revalidates to a 304 ({api_path})", n2.status_code == 304, n2.status_code)
            n3 = await c.get(api_path)
            check(f"an API call to {api_path} with no login is still a JSON 401", n3.status_code == 401 and n3.headers.get("content-type", "").startswith("application/json"), (n3.status_code, n3.headers.get("content-type")))
            n4 = await api("owner", "GET", api_path)
            check(f"an API call to {api_path} with a login is still JSON data, never the shell", n4.status_code == 200 and "<title>" not in n4.text, n4.status_code)
        d3 = await c.get("/does/not/exist.js")
        check("a path that looks like a file is still a plain 404", d3.status_code == 404, d3.status_code)
        f = await c.get("/assets/fonts/inter-latin-v1.woff2", headers={"If-None-Match": '"x"'})
        check("versioned assets still revalidate normally (200 for a stale tag)", f.status_code == 200)
        f = await c.get("/assets/fonts/not-there-v1.woff2")
        check("a missing versioned asset is a plain 404 (no immutable header on an error)", f.status_code == 404 and "immutable" not in f.headers.get("cache-control", ""), dict(f.headers))
        f = await c.get("/logo.png")
        check("/logo.png is still served (external references: the Play listing, old caches)", f.status_code == 200 and len(f.content) > 1_000_000)

    print(f"\n{N - len(FAILS)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
