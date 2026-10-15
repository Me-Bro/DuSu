"""My Day - tier 2: REPEATING REMINDERS through the real HTTP layer and the real reminder engine, on a SCRATCH Postgres.

Run via tests/my_day/run.sh (it starts a throwaway postgres, never the app's `dusu-db-1`, and blanks every provider key). Everything goes through the real
FastAPI app (routing, gates, JSON handling) in-process with httpx's ASGI transport. Time is a FAKE CLOCK (`tu.now_utc` is replaced), so a month of days is
driven in seconds, and the push sender is a fake: the scheduler's own `tick()` / `materialize_all()` / `deliver()` do the work, exactly as in production.

The promise being proven: set a reminder ONCE for chosen weekdays and it rings on every one of those days - and only those - until it is paused or deleted.
Plain Python; prints PASS / FAIL per check and exits non-zero on any failure.
"""

import asyncio
import datetime as dt
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/my_day")

import httpx                                                        # noqa: E402
from sqlalchemy import func, select, text as sa_text                # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.planner import life_lines, models as PM, push, rules, scheduler as sch, service as svc, timeutil as tu    # noqa: E402

UTC = dt.timezone.utc
IST = "Asia/Kolkata"
FAILS: list[str] = []
FIVE: list = []
N = 0
ANN_RULES = 8                                                       # Gym x3 (different days / time), Every day, Daily word, Hindi, the long title, the control-character title


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


def at(y, mo, d, h=0, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def local(day, hhmm, tz=IST):
    return tu.to_utc(day, tu.parse_hhmm(hhmm), tz)


CLOCK = [at(2026, 10, 14, 6, 0)]                                    # Wed 14 Oct 2026, 11:30 in India
tu.now_utc = lambda: CLOCK[0]                                       # service._utc(), timeutil.local_today() and scheduler.tick() all read this


def setclock(when):
    CLOCK[0] = when


def advance(**kw):
    CLOCK[0] = CLOCK[0] + dt.timedelta(**kw)


ENABLED = lambda email: True                                        # noqa: E731
SENT: list = []


async def SENDER(sub, payload):                                     # the fake push service: accepts everything
    SENT.append((sub["endpoint"], payload))
    return ("ok", 201)


async def rows(model, *conds, order=None):
    async with db._Session() as s:
        q = select(model).where(*conds)
        if order is not None:
            q = q.order_by(*order)
        return (await s.execute(q)).scalars().all()


async def rings(uid, rule_id=None):
    conds = [PM.PlReminder.user_id == uid, PM.PlReminder.entity_type == "custom", PM.PlReminder.kind == "recurring"]
    if rule_id is not None:
        conds.append(PM.PlReminder.entity_id == rule_id)
    return await rows(PM.PlReminder, *conds, order=(PM.PlReminder.fire_at, PM.PlReminder.id))


def live(rs):
    return [r for r in rs if r.status in ("scheduled", "waiting", "sending", "sent")]


async def tick(**kw):
    kw.setdefault("materialize", False)
    kw.setdefault("sender", SENDER)
    return await sch.tick(ENABLED, **kw)


async def tick_user(uid, **kw):
    """Run one scheduler pass and return the rows of THIS learner that were sent by it (a pass is global: other learners' rings are due too)."""
    before = {r.id for r in await rows(PM.PlReminder, PM.PlReminder.user_id == uid, PM.PlReminder.sent_at.is_not(None))}
    before_t = {r.id: r.sent_at for r in await rows(PM.PlReminder, PM.PlReminder.user_id == uid, PM.PlReminder.sent_at.is_not(None))}
    await tick(**kw)
    after = await rows(PM.PlReminder, PM.PlReminder.user_id == uid, PM.PlReminder.sent_at.is_not(None))
    return [r for r in after if r.id not in before or r.sent_at != before_t.get(r.id)]


async def count(model, *conds):
    async with db._Session() as s:
        return int((await s.execute(select(func.count()).select_from(model).where(*conds))).scalar() or 0)


# ----------------------------------------------------------------------------- the run
async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh, which blanks them"

    # ------------------------------------------------------------------ OLD -> NEW schema rehearsal
    section("schema rehearsal: production has every pl_* table EXCEPT pl_reminder_rules")
    for _ in range(20):                                              # a freshly started postgres restarts once after initdb
        try:
            async with db._engine.begin() as conn:
                await conn.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if t.name != "pl_reminder_rules"]))
            break
        except Exception:
            await asyncio.sleep(1)

    async def tables():
        async with db._engine.connect() as conn:
            return {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'pl\\_%'"))).all()}

    pre = await tables()
    old = {"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""}
    await db.login(old)
    await db.set_setting("planner", "on")
    M.invalidate_access_cache()
    old_rem = await svc.create_custom_reminder("u-old", {"title": "Old reminder", "time": "20:00", "client_key": "old1"})
    check("the old schema has no pl_reminder_rules", "pl_reminder_rules" not in pre and "pl_reminders" in pre, pre)
    await db.init_db()
    await db.init_db()
    post = await tables()
    async with db._engine.connect() as conn:
        idx = {r[0] for r in (await conn.execute(sa_text("select indexname from pg_indexes where tablename = 'pl_reminder_rules'"))).all()}
        cols = {r[0]: (r[1], r[2]) for r in (await conn.execute(sa_text(
            "select column_name, data_type, character_maximum_length from information_schema.columns where table_name = 'pl_reminder_rules'"))).all()}
    check("init_db() adds exactly the one new table, twice in a row, next to the old data", "pl_reminder_rules" in post and post - pre == {"pl_reminder_rules"}, (pre, post))
    check("the partial unique index (idempotent create) exists", "uq_pl_rrules_client" in idx, idx)
    check("the columns are what the code writes", {"id", "user_id", "client_key", "title", "time", "days", "status", "tz", "created_at", "updated_at"} <= set(cols)
          and cols["days"][0] == "jsonb" and cols["time"][1] == 5, cols)
    check("the existing learner's reminder is untouched", (await count(PM.PlReminder, PM.PlReminder.user_id == "u-old")) == 1 and old_rem["id"] > 0)

    # ------------------------------------------------------------------ users + client
    names = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ida", "jon", "kim", "lee", "sim", "ned", "spr", "zed", "mia", "ola"]
    users = {n: {"sub": f"u-{n}", "email": f"{n}@example.com", "name": n.title(), "picture": ""} for n in names}
    for u in users.values():
        await db.login(u)
    T = {n: auth.make_session(u) for n, u in users.items()}
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        def H(who):
            return {"Authorization": "Bearer " + T[who]}

        async def api(who, method, path, body=None, params=None):
            r = await c.request(method, "/planner" + path, headers=H(who) if who else {}, json=body, params=params)
            if r.status_code >= 500:
                FIVE.append((method, path, r.status_code))
            return r

        async def mk(who, title, time, days, key=None, expect=200):
            body = {"title": title, "time": time, "days": days, "client_key": key or f"{who}-{title}-{time}-{json.dumps(days)}"}
            r = await api(who, "POST", "/reminder-rules", body)
            assert r.status_code == expect, (r.status_code, r.text)
            return r.json()

        uid = lambda n: f"u-{n}"                                    # noqa: E731

        # -------------------------------------------------------------- the switch and the gates
        section("gates: the switch, sign-in, every verb")
        await db.set_setting("planner", "off")
        M.invalidate_access_cache()
        for m, p in (("GET", "/reminder-rules"), ("POST", "/reminder-rules"), ("PATCH", "/reminder-rules/1"), ("DELETE", "/reminder-rules/1")):
            r = await api("ann", m, p, {} if m in ("POST", "PATCH") else None)
            check(f"switch OFF: {m} {p} is 404 (invisible)", r.status_code == 404, r.status_code)
        r = await api("ann", "GET", "/export")
        check("switch OFF: export still answers 404 like the rest of My Day", r.status_code == 404)
        await db.set_setting("planner", "on")
        M.invalidate_access_cache()
        for m, p in (("GET", "/reminder-rules"), ("POST", "/reminder-rules"), ("PATCH", "/reminder-rules/1"), ("DELETE", "/reminder-rules/1")):
            r = await api(None, m, p, {} if m in ("POST", "PATCH") else None)
            check(f"no token: {m} {p} is 401", r.status_code == 401, r.status_code)
        r = await c.get("/planner/reminder-rules", headers={"Authorization": "Bearer junk.token"})
        check("a junk token is 401", r.status_code == 401)
        me = (await c.get("/me", headers=H("ann"))).json()
        check("/me says My Day is on", me.get("planner") is True)

        # -------------------------------------------------------------- create + validation
        section("create: a reminder that repeats on chosen days")
        setclock(at(2026, 10, 14, 6, 0))
        r = await api("ann", "POST", "/reminder-rules", {"title": "Gym", "time": "20:00", "days": [1, 0, 1], "client_key": "ann-gym"})
        j = r.json()
        check("create answers 200 with the rule", r.status_code == 200 and j["title"] == "Gym" and j["time"] == "20:00" and j["status"] == "active", (r.status_code, j))
        check("days are sorted and de-duplicated: Mon + Tue", j["days"] == [0, 1], j)
        check("it says when it rings next (Mon 19 Oct 20:00), worked out from the rule", j["next_day"] == "2026-10-19" and j["next_time"] == "20:00"
              and j["next_at"] == "2026-10-19T14:30:00+00:00", j)
        gym_id = j["id"]
        r2 = await api("ann", "POST", "/reminder-rules", {"title": "Gym", "time": "20:00", "days": [0, 1], "client_key": "ann-gym"})
        check("a retried create (same client_key) returns the same rule, marked duplicate", r2.status_code == 200 and r2.json()["id"] == gym_id and r2.json().get("duplicate") is True, r2.text)
        r2b = await api("ann", "POST", "/reminder-rules", {"title": "Completely different words", "time": "11:11", "days": [3], "client_key": "ann-gym"})
        check("the same client_key with OTHER words still returns the first rule (a retry is idempotent by its key)", r2b.status_code == 200 and r2b.json()["id"] == gym_id
              and r2b.json()["title"] == "Gym" and r2b.json().get("duplicate") is True and (await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("ann"))) == 1, r2b.text)
        r3 = await api("ann", "POST", "/reminder-rules", {"title": "  gym ", "time": "20:00", "days": [0, 1], "client_key": "ann-gym-2"})
        check("the same words (any case) + time + days with a NEW key is the same reminder, not a copy", r3.json().get("id") == gym_id and r3.json().get("duplicate") is True, r3.text)
        check("...only one rule exists", (await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("ann"))) == 1)
        r4 = await api("ann", "POST", "/reminder-rules", {"title": "Gym", "time": "20:00", "days": [2], "client_key": "ann-gym-3"})
        check("the same words on OTHER days is a different reminder", r4.status_code == 200 and r4.json()["id"] != gym_id and not r4.json().get("duplicate"), r4.text)
        r5 = await api("ann", "POST", "/reminder-rules", {"title": "Gym", "time": "07:00", "days": [0, 1], "client_key": "ann-gym-4"})
        check("the same words and days at ANOTHER time is a different reminder", r5.status_code == 200 and r5.json()["id"] not in (gym_id, r4.json()["id"]), r5.text)
        r6 = await api("ann", "POST", "/reminder-rules", {"title": "Every day", "time": "09:00", "days": [0, 1, 2, 3, 4, 5, 6], "client_key": "ann-all"})
        check("all seven days are stored as 'daily'", r6.status_code == 200 and r6.json()["days"] == "daily", r6.text)
        r7 = await api("ann", "POST", "/reminder-rules", {"title": "Daily word", "time": "09:30", "days": "daily", "client_key": "ann-d"})
        check("'daily' is accepted as is", r7.status_code == 200 and r7.json()["days"] == "daily")
        r8 = await api("ann", "POST", "/reminder-rules", {"title": "Hindi शनिवार 🏋️", "time": "6:05", "days": ["5"], "client_key": "ann-hi"})
        check("Hindi, emoji, an unpadded time and digit-string days all work", r8.status_code == 200 and r8.json()["title"] == "Hindi शनिवार 🏋️" and r8.json()["time"] == "06:05"
              and r8.json()["days"] == [5], r8.text)
        r9 = await api("ann", "POST", "/reminder-rules", {"title": "x" * 10000, "time": "10:00", "days": [3], "client_key": "ann-long"})
        check("a 10 000-character title is cut to 160, not refused", r9.status_code == 200 and len(r9.json()["title"]) == 160)
        r10 = await api("ann", "POST", "/reminder-rules", {"title": "NUL\x00 and\ttab\nnewline", "time": "10:00", "days": [4], "client_key": "ann-ctl"})
        check("control characters (NUL!) are stripped, the title stays one line", r10.status_code == 200 and "\x00" not in r10.json()["title"] and "\n" not in r10.json()["title"], r10.text)
        for label, body, code in (
                ("no title", {"time": "20:00", "days": [0]}, "title"), ("a blank title", {"title": "   ", "time": "20:00", "days": [0]}, "title"),
                ("a numeric title", {"title": 123, "time": "20:00", "days": [0]}, "title"), ("no time", {"title": "A", "days": [0]}, "time"),
                ("time 25:00", {"title": "A", "time": "25:00", "days": [0]}, "time"), ("time '9'", {"title": "A", "time": "9", "days": [0]}, "time"),
                ("time '12:60'", {"title": "A", "time": "12:60", "days": [0]}, "time"), ("a time that is a number", {"title": "A", "time": 900, "days": [0]}, "time"),
                ("no days", {"title": "A", "time": "20:00"}, "days"), ("empty days", {"title": "A", "time": "20:00", "days": []}, "days"),
                ("day 7", {"title": "A", "time": "20:00", "days": [7]}, "days"), ("days 'weekly'", {"title": "A", "time": "20:00", "days": "weekly"}, "days"),
                ("days as a dict", {"title": "A", "time": "20:00", "days": {"0": 1}}, "days"), ("days None", {"title": "A", "time": "20:00", "days": None}, "days"),
                ("a 5000-digit day", {"title": "A", "time": "20:00", "days": ["9" * 5000]}, "days")):
            r = await api("ann", "POST", "/reminder-rules", body)
            err = (r.json().get("detail") or {}).get("error") if r.status_code == 422 and isinstance(r.json().get("detail"), dict) else None
            check(f"refused with 422 '{code}': {label}", r.status_code == 422 and err == code, (r.status_code, r.text[:200]))
        r = await c.post("/planner/reminder-rules", headers=H("ann"), content=b"not json", )
        check("a body that is not JSON is a 422, never a 500", r.status_code == 422, r.status_code)
        r = await c.post("/planner/reminder-rules", headers={**H("ann"), "Content-Type": "application/json"}, content=b"[1,2]")
        check("a JSON list instead of an object is a 422, never a 500", r.status_code == 422, r.status_code)
        check("none of the refused ones created anything", (await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("ann"))) == ANN_RULES)

        # -------------------------------------------------------------- the list
        section("list: the soonest first")
        lst = (await api("ann", "GET", "/reminder-rules")).json()
        check("the list holds this learner's rules, with tz and the learner's today", len(lst["rules"]) == ANN_RULES and lst["tz"] == IST and lst["today"] == "2026-10-14", lst.get("today"))
        nx = [x["next_at"] for x in lst["rules"] if x["next_at"]]
        check("soonest next ring first", nx == sorted(nx), nx)
        check("every rule carries its time, days and status", all({"id", "title", "time", "days", "status"} <= set(x) for x in lst["rules"]))

        # -------------------------------------------------------------- IDOR + odd ids
        section("another learner's rules are invisible; odd ids are 404, never 500")
        r = await api("bob", "GET", "/reminder-rules")
        check("bob sees none of ann's rules", r.status_code == 200 and r.json()["rules"] == [])
        for m, body in (("PATCH", {"title": "hijack"}), ("PATCH", {"action": "pause"}), ("DELETE", None)):
            r = await api("bob", m, f"/reminder-rules/{gym_id}", body)
            check(f"bob {m} on ann's rule is 404", r.status_code == 404, r.status_code)
        check("ann's rule is untouched", (await rows(PM.PlReminderRule, PM.PlReminderRule.id == gym_id))[0].title == "Gym")
        for oid in ("0", "-1", "99999999999", "2147483648", "4294967296", "123456789012345678901234567890"):
            for m in ("PATCH", "DELETE"):
                r = await api("ann", m, f"/reminder-rules/{oid}", {"title": "x"} if m == "PATCH" else None)
                check(f"{m} /reminder-rules/{oid} is 404", r.status_code == 404, r.status_code)
        for m in ("PATCH", "DELETE"):
            r = await api("ann", m, "/reminder-rules/abc", {"title": "x"} if m == "PATCH" else None)
            check(f"{m} /reminder-rules/abc is 422, not 500", r.status_code == 422, r.status_code)

        section("the older endpoints too: an id beyond a 32-bit integer is 404, never a 500")
        for m, p_, b in (("PATCH", "/tasks/99999999999", {"title": "x"}), ("DELETE", "/tasks/99999999999", None), ("POST", "/tasks/99999999999/complete", {}),
                         ("GET", "/goals/99999999999", None), ("PATCH", "/habits/99999999999", {"title": "x"}), ("DELETE", "/reminders/99999999999", None),
                         ("PATCH", "/reminders/99999999999", {"title": "x"}), ("POST", "/reminders/99999999999/act", {"action": "done"}),
                         ("PATCH", "/milestones/99999999999", {"action": "complete"}), ("PUT", "/habits/99999999999/log", {"count": 1})):
            r = await api("ann", m, p_, b)
            check(f"{m} {p_} is 404", r.status_code == 404, r.status_code)

        # -------------------------------------------------------------- patch validation
        section("edit: validation")
        for label, body, code in (("a blank title", {"title": " "}, "title"), ("a bad time", {"time": "7pm"}, "time"), ("no days", {"days": []}, "days"),
                                  ("an unknown action", {"action": "explode"}, "action"), ("a non-string action", {"action": 5}, "action")):
            r = await api("ann", "PATCH", f"/reminder-rules/{r4.json()['id']}", body)
            err = (r.json().get("detail") or {}).get("error") if r.status_code == 422 and isinstance(r.json().get("detail"), dict) else None
            check(f"edit refused 422 '{code}': {label}", r.status_code == 422 and err == code, (r.status_code, r.text[:160]))
        r = await api("ann", "PATCH", f"/reminder-rules/{r4.json()['id']}", {})
        check("an empty edit is a harmless no-op", r.status_code == 200 and r.json()["id"] == r4.json()["id"])

        # -------------------------------------------------------------- limit
        section("limit: thirty repeating reminders")
        for i in range(30):
            r = await api("cat", "POST", "/reminder-rules", {"title": f"Rule {i}", "time": "08:00", "days": [i % 7], "client_key": f"cat-{i}"})
            assert r.status_code == 200, (i, r.text)
        r = await api("cat", "POST", "/reminder-rules", {"title": "One too many", "time": "08:00", "days": [1], "client_key": "cat-31"})
        check("the 31st is 409 limit_repeating", r.status_code == 409 and r.json()["detail"]["error"] == "limit_repeating", r.text)
        one = (await api("cat", "GET", "/reminder-rules")).json()["rules"][0]["id"]
        await api("cat", "DELETE", f"/reminder-rules/{one}")
        r = await api("cat", "POST", "/reminder-rules", {"title": "Now there is room", "time": "08:00", "days": [1], "client_key": "cat-32"})
        check("after deleting one there is room again", r.status_code == 200, r.text)
        surv = (await api("cat", "GET", "/reminder-rules")).json()["rules"][0]
        r = await api("cat", "POST", "/reminder-rules", {"title": surv["title"], "time": surv["time"], "days": surv["days"], "client_key": "cat-dupfull"})
        check("at the limit, a duplicate still answers with the rule that exists (not a 409)", r.status_code == 200 and r.json()["id"] == surv["id"] and r.json().get("duplicate") is True, r.text)

        # -------------------------------------------------------------- materialization at creation
        section("the rings made at creation: only today and tomorrow, only on the chosen days, never one that has passed")
        setclock(at(2026, 10, 14, 6, 0))                             # Wed 11:30 IST
        mt = await mk("dan", "Mon Tue", "20:00", [0, 1])
        sat = await mk("dan", "Saturday", "18:00", [5])
        dly = await mk("dan", "Daily 9", "09:00", "daily")
        wed = await mk("dan", "Wednesday evening", "20:00", [2])
        late = await mk("dan", "Just passed", "11:29", "daily")
        old = await mk("dan", "Long passed", "07:00", [2])
        rs = await rings(uid("dan"))
        by = lambda rid: [r for r in rs if r.entity_id == rid]       # noqa: E731
        check("Mon+Tue on a Wednesday: no ring today or tomorrow", by(mt["id"]) == [])
        check("Saturday-only on a Wednesday: no ring yet", by(sat["id"]) == [])
        d9 = by(dly["id"])
        check("daily 09:00 (already passed today): only tomorrow's ring", len(d9) == 1 and d9[0].fire_at == at(2026, 10, 15, 3, 30) and d9[0].meta["day"] == "2026-10-15", [(r.fire_at, r.meta) for r in d9])
        wd = by(wed["id"])
        check("Wednesday 20:00 on a Wednesday morning: today's ring", len(wd) == 1 and wd[0].fire_at == at(2026, 10, 14, 14, 30), [(r.fire_at) for r in wd])
        lt = by(late["id"])
        check("a time one minute ago is still made (it rings now); tomorrow's too", sorted(r.fire_at for r in lt) == [at(2026, 10, 14, 5, 59), at(2026, 10, 15, 5, 59)], [(r.fire_at) for r in lt])
        check("a time hours ago is not made", [r for r in by(old["id"]) if r.fire_at < at(2026, 10, 14, 6, 0)] == [])
        r0 = wd[0]
        check("a ring is an ordinary custom reminder: entity_type custom, kind recurring, entity_id = the rule", (r0.entity_type, r0.kind, r0.entity_id) == ("custom", "recurring", wed["id"]))
        check("it is scheduled, in the learner's zone, with the day and the time in meta", r0.status == "scheduled" and r0.tz == IST and r0.meta == {"day": "2026-10-14", "time": "20:00", "rule": wed["id"]}, r0.meta)
        check("its key names the rule, the local day and the time", r0.occurrence_key == f"rr{wed['id']}:2026-10-14:2000", r0.occurrence_key)
        check("its title is the rule's", r0.title == "Wednesday evening" and r0.body == "")
        before = len(await rings(uid("dan")))
        for _ in range(3):
            await svc.materialize_all()
        check("running the materializer again and again makes no second ring", len(await rings(uid("dan"))) == before)

        # -------------------------------------------------------------- THE PROMISE: set once, rings forever
        section("the promise: 28 days, three rules set ONCE - every ring on its own days, nothing on the others")
        setclock(at(2026, 10, 14, 6, 0))
        await api("sim", "PUT", "/prefs", {"followups": 0})
        gymr = await mk("sim", "Gym", "20:00", [0, 1])
        calr = await mk("sim", "Call mom", "18:00", [5])
        watr = await mk("sim", "Drink water", "09:00", "daily")
        specs = {gymr["id"]: ([0, 1], "20:00"), calr["id"]: ([5], "18:00"), watr["id"]: ("daily", "09:00")}
        start_day, created_at = dt.date(2026, 10, 14), CLOCK[0]
        N_DAYS = 28
        expect = set()
        for i in range(N_DAYS):
            d = start_day + dt.timedelta(days=i)
            for rid, (days, hhmm) in specs.items():
                if rules.days_scheduled(days, d) and local(d, hhmm) >= created_at - dt.timedelta(minutes=2):
                    expect.add((rid, d.isoformat()))
        for i in range(N_DAYS):
            d = start_day + dt.timedelta(days=i)
            fires = sorted(local(d, hhmm) for rid, (days, hhmm) in specs.items() if rules.days_scheduled(days, d) and local(d, hhmm) >= created_at - dt.timedelta(minutes=2))
            for f in fires:
                setclock(f + dt.timedelta(seconds=10))
                await tick()
            setclock(local(d, "23:50"))
            await svc.materialize_all()                                  # once a day, late at night - the next day's rings must already exist
        got_rows = [r for r in await rings(uid("sim")) if r.sent_at is not None]
        got = {(r.entity_id, r.meta["day"]) for r in got_rows}
        check(f"exactly the expected {len(expect)} rings were delivered over {N_DAYS} days (Mon/Tue gym, Saturday call, daily water)", got == expect, (sorted(expect - got)[:5], sorted(got - expect)[:5]))
        check("none delivered twice: one row per (rule, day)", len(got_rows) == len(got), (len(got_rows), len(got)))
        check("each rang within seconds of its time", all(0 <= (r.sent_at - r.fire_at).total_seconds() <= 11 for r in got_rows), [(r.meta, r.fire_at, r.sent_at) for r in got_rows if not 0 <= (r.sent_at - r.fire_at).total_seconds() <= 11][:3])
        check("each was attempted exactly once, with no follow-up", all(r.attempts == 1 and r.followups_sent == 0 for r in got_rows))
        weekdays = {}
        for rid, day in got:
            weekdays.setdefault(rid, set()).add(dt.date.fromisoformat(day).weekday())
        check("the gym rang only on Mondays and Tuesdays", weekdays[gymr["id"]] == {0, 1}, weekdays.get(gymr["id"]))
        check("the call rang only on Saturdays", weekdays[calr["id"]] == {5}, weekdays.get(calr["id"]))
        check("the water rang on every weekday", weekdays[watr["id"]] == set(range(7)))
        check("the gym rang on 8 Mondays/Tuesdays in 28 days, the call on 4 Saturdays", sum(1 for r, d in got if r == gymr["id"]) == 8 and sum(1 for r, d in got if r == calr["id"]) == 4,
              {k: sum(1 for r, d in got if r == k) for k in specs})
        allrows = await rings(uid("sim"))
        pending = [r for r in allrows if r.sent_at is None]
        check("the table does not grow without bound: only the next two days are pending", len([r for r in pending if r.status in ("scheduled", "waiting")]) <= 2 * len(specs), len(pending))
        check("the unique keys held: no two rows share a key", len({r.occurrence_key for r in allrows}) == len(allrows))
        rl = (await api("sim", "GET", "/reminder-rules")).json()["rules"]
        check("after four weeks the three rules are still there, active, unchanged", len(rl) == 3 and all(x["status"] == "active" for x in rl), rl)

        # -------------------------------------------------------------- pause / resume / edit / delete
        section("pause and resume")
        setclock(at(2026, 10, 14, 6, 0))
        w = await mk("eve", "Water", "09:00", "daily")
        wid = w["id"]
        tomorrow = (await rings(uid("eve"), wid))
        check("a daily rule has tomorrow's ring waiting", len(live(tomorrow)) == 1 and tomorrow[0].fire_at == at(2026, 10, 15, 3, 30), [(r.fire_at, r.status) for r in tomorrow])
        row_id = tomorrow[0].id
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"action": "pause"})
        check("pause answers 200: status paused, no next ring", r.status_code == 200 and r.json()["status"] == "paused" and r.json()["next_at"] is None, r.text)
        check("pausing withdraws the ring that was waiting", (await rings(uid("eve"), wid))[0].status == "cancelled")
        await svc.materialize_all()
        check("while paused the materializer makes nothing", live(await rings(uid("eve"), wid)) == [])
        setclock(at(2026, 10, 15, 3, 30, 10))
        sent = await tick_user(uid("eve"))
        check("while paused nothing rings", sent == [] and not [r for r in await rings(uid("eve"), wid) if r.sent_at])
        setclock(at(2026, 10, 14, 6, 5))
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"action": "resume"})
        check("resume answers 200: active again with a next ring", r.status_code == 200 and r.json()["status"] == "active" and r.json()["next_day"] == "2026-10-15", r.text)
        rr = await rings(uid("eve"), wid)
        check("resuming brings tomorrow's ring back (the same row, revived)", len(live(rr)) == 1 and live(rr)[0].id == row_id and len(rr) == 1, [(r.id, r.status) for r in rr])
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"action": "resume"})
        check("resuming twice is harmless", r.status_code == 200 and len(live(await rings(uid("eve"), wid))) == 1)
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"action": "pause"})
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"action": "pause"})
        check("pausing twice is harmless", r.status_code == 200 and r.json()["status"] == "paused")
        r = await api("eve", "PATCH", f"/reminder-rules/{wid}", {"title": "Water (paused)", "action": "resume"})
        check("an edit and a resume in one request", r.status_code == 200 and r.json()["status"] == "active" and r.json()["title"] == "Water (paused)")
        setclock(at(2026, 10, 15, 3, 30, 10))
        sent = await tick_user(uid("eve"))
        check("after resuming it rings, once, with the new words", len(sent) == 1 and [r.title for r in await rings(uid("eve"), wid) if r.sent_at] == ["Water (paused)"], [(r.title) for r in sent])

        section("edit: the words, the time, the days")
        setclock(at(2026, 10, 14, 6, 0))
        e1 = await mk("fay", "Walk", "09:00", "daily")
        eid = e1["id"]
        base_rows = await rings(uid("fay"), eid)
        r = await api("fay", "PATCH", f"/reminder-rules/{eid}", {"title": "Evening walk"})
        rr = await rings(uid("fay"), eid)
        check("new words: the ring that was waiting keeps its row and takes the new words", len(rr) == len(base_rows) == 1 and rr[0].id == base_rows[0].id and rr[0].title == "Evening walk" and rr[0].status == "scheduled", [(x.id, x.title, x.status) for x in rr])
        r = await api("fay", "PATCH", f"/reminder-rules/{eid}", {"time": "10:15"})
        rr = await rings(uid("fay"), eid)
        check("a new time: the old ring is withdrawn and a new one is made", r.json()["time"] == "10:15" and len(rr) == 2 and sorted(x.status for x in rr) == ["cancelled", "scheduled"]
              and [x.fire_at for x in live(rr)] == [at(2026, 10, 15, 4, 45)], [(x.fire_at, x.status) for x in rr])
        check("the new ring knows its new time", live(rr)[0].meta["time"] == "10:15")
        r = await api("fay", "PATCH", f"/reminder-rules/{eid}", {"days": [4]})                # Friday only: tomorrow (Thursday) has no ring any more
        rr = await rings(uid("fay"), eid)
        check("new days (Friday only): Thursday's ring is withdrawn", live(rr) == [] and r.json()["days"] == [4], [(x.meta, x.status) for x in rr])
        setclock(local(dt.date(2026, 10, 15), "23:50"))
        await svc.materialize_all()
        rr = await rings(uid("fay"), eid)
        check("...and Friday's ring appears when Friday is tomorrow", [x.meta["day"] for x in live(rr)] == ["2026-10-16"], [(x.meta, x.status) for x in rr])
        r = await api("fay", "PATCH", f"/reminder-rules/{eid}", {"time": "10:15", "days": [4], "title": "Evening walk"})
        check("saving without changing anything changes nothing", len(await rings(uid("fay"), eid)) == len(rr))
        # a ring that was made BEFORE an edit and is claimed AFTER it must not go off
        setclock(at(2026, 10, 14, 6, 0))
        e2 = await mk("fay", "Stretch", "21:00", "daily")
        stale = (await rings(uid("fay"), e2["id"]))[0]                                       # today's 21:00 ring (15:30Z)
        await api("fay", "PATCH", f"/reminder-rules/{e2['id']}", {"time": "22:00"})
        async with db._Session() as s:                                                       # simulate the race: the scheduler had already claimed it
            await s.execute(sa_text("update pl_reminders set status='sending', claimed_at=:n where id=:i"), {"n": CLOCK[0], "i": stale.id})
            await s.commit()
        SENT.clear()
        setclock(at(2026, 10, 14, 15, 30, 5))
        out = await sch.deliver(stale.id, ENABLED, CLOCK[0], SENDER)
        after = (await rows(PM.PlReminder, PM.PlReminder.id == stale.id))[0]
        check("a stale ring (the rule's time changed since) is cancelled at send time, not sent", out == "cancelled" and after.status == "cancelled" and after.last_error == "gone" and not SENT, (out, after.status, after.last_error))

        # the same for PAUSE: a ring claimed by the scheduler a moment before the learner paused its rule must not go off
        setclock(at(2026, 10, 14, 6, 0))
        e3 = await mk("fay", "Pause race", "21:30", "daily")
        claimed = (await rings(uid("fay"), e3["id"]))[0]                                        # today's 21:30 ring (16:00Z)
        async with db._Session() as s:
            await s.execute(sa_text("update pl_reminders set status='sending', claimed_at=:n where id=:i"), {"n": CLOCK[0], "i": claimed.id})
            await s.commit()
        await api("fay", "PATCH", f"/reminder-rules/{e3['id']}", {"action": "pause"})
        check("a ring already being sent is not touched by the pause itself (only waiting ones are withdrawn)", (await rows(PM.PlReminder, PM.PlReminder.id == claimed.id))[0].status == "sending")
        setclock(at(2026, 10, 14, 16, 0, 5))
        SENT.clear()
        out = await sch.deliver(claimed.id, ENABLED, CLOCK[0], SENDER)
        after = (await rows(PM.PlReminder, PM.PlReminder.id == claimed.id))[0]
        check("...but at send time the paused rule stops it", out == "cancelled" and after.status == "cancelled" and after.last_error == "gone" and not SENT, (out, after.status, after.last_error))

        section("delete")
        setclock(at(2026, 10, 14, 6, 0))
        d1 = await mk("gus", "Delete me", "20:00", "daily")
        did = d1["id"]
        setclock(at(2026, 10, 14, 14, 30, 10))
        await tick()
        sent_one = [r for r in await rings(uid("gus"), did) if r.status == "sent"]
        check("one ring has rung and is waiting for a tap", len(sent_one) == 1)
        due = (await api("gus", "GET", "/due")).json()["due"]
        check("it is in the in-app due list", [x["id"] for x in due] == [sent_one[0].id] and due[0]["rule_id"] == did, due)
        r = await api("gus", "DELETE", f"/reminder-rules/{did}")
        check("delete answers 200", r.status_code == 200 and r.json() == {"ok": True, "id": did}, r.text)
        check("the rule is gone from the list", (await api("gus", "GET", "/reminder-rules")).json()["rules"] == [])
        check("its rows in the database are gone too (hard delete)", await count(PM.PlReminderRule, PM.PlReminderRule.id == did) == 0)
        rr = await rings(uid("gus"), did)
        check("every ring still open is withdrawn - including the card waiting for a tap", live(rr) == [] and all(x.status == "cancelled" for x in rr), [(x.meta, x.status) for x in rr])
        check("the card waiting for a tap left the due list", (await api("gus", "GET", "/due")).json()["due"] == [])
        await svc.materialize_all()
        check("nothing is ever made for a deleted rule", live(await rings(uid("gus"), did)) == [])
        setclock(at(2026, 10, 15, 14, 30, 10))
        sent = await tick_user(uid("gus"))
        check("and nothing rings the next day", sent == [] and live(await rings(uid("gus"), did)) == [])
        r = await api("gus", "DELETE", f"/reminder-rules/{did}")
        check("deleting twice is a 404 (it is gone)", r.status_code == 404)
        r = await api("gus", "PATCH", f"/reminder-rules/{did}", {"title": "zombie"})
        check("editing a deleted rule is a 404", r.status_code == 404)

        # -------------------------------------------------------------- acting on one ring
        section("a ring is ticked off, snoozed, skipped or undone - the rule carries on")
        setclock(at(2026, 10, 14, 6, 0))
        await api("hal", "PUT", "/prefs", {"followups": 0})
        h1 = await mk("hal", "Vitamins", "09:00", "daily")
        hid = h1["id"]
        setclock(at(2026, 10, 15, 3, 30, 10))                                                  # Thu 09:00:10 IST
        await tick()
        ring = [r for r in await rings(uid("hal"), hid) if r.sent_at][0]
        r = await api("hal", "POST", f"/reminders/{ring.id}/act", {"action": "done"})
        check("tick it off: done", r.status_code == 200 and r.json()["status"] == "done" and r.json()["rule_id"] == hid, r.text)
        td = (await api("hal", "GET", "/today")).json()
        check("today it stays on the day's list, struck through (reminders_done), with its repeat", [x["id"] for x in td["reminders_done"]] == [ring.id]
              and td["reminders_done"][0]["repeat"] == {"days": "daily", "status": "active"}, td["reminders_done"])
        r = await api("hal", "POST", f"/reminders/{ring.id}/act", {"action": "reopen"})
        check("untick: back to 'due now' (its time is past)", r.json()["status"] == "sent", r.text)
        r = await api("hal", "POST", f"/reminders/{ring.id}/act", {"action": "later", "minutes": 30})
        snz = (await rows(PM.PlReminder, PM.PlReminder.id == ring.id))[0]
        check("'later' moves THIS ring by 30 minutes, same row", snz.status == "scheduled" and snz.fire_at == CLOCK[0] + dt.timedelta(minutes=30) and snz.snooze_count == 1, (snz.status, snz.fire_at))
        n_thu = len([r for r in await rings(uid("hal"), hid) if r.meta["day"] == "2026-10-15"])
        await svc.materialize_all()
        rr = await rings(uid("hal"), hid)
        check("the materializer does not make a second ring for the snoozed one (Thursday still has exactly one)", n_thu == 1 and len([r for r in rr if r.meta["day"] == "2026-10-15"]) == 1, [(r.meta["day"], r.status) for r in rr])
        check("...it only made Friday's, the next day's", sorted(r.meta["day"] for r in rr) == ["2026-10-15", "2026-10-16"], [(r.meta["day"], r.status) for r in rr])
        setclock(CLOCK[0] + dt.timedelta(minutes=31))
        await tick()
        check("the snoozed ring rings again", (await rows(PM.PlReminder, PM.PlReminder.id == ring.id))[0].status == "sent")
        r = await api("hal", "POST", f"/reminders/{ring.id}/act", {"action": "skip"})
        check("skip: skipped", r.json()["status"] == "skipped")
        await svc.materialize_all()
        check("a skipped ring is not brought back by the materializer", (await rows(PM.PlReminder, PM.PlReminder.id == ring.id))[0].status == "skipped")
        r = await api("hal", "PATCH", f"/reminders/{ring.id}", {"title": "single edit"})
        check("one ring cannot be edited on its own (404): the rule is the unit", r.status_code == 404, r.text)
        r = await api("hal", "DELETE", f"/reminders/{ring.id}")
        check("one ring cannot be deleted on its own (404) - it would be made again", r.status_code == 404, r.text)
        r = await api("bob", "POST", f"/reminders/{ring.id}/act", {"action": "done"})
        check("another learner cannot act on it (404)", r.status_code == 404)
        setclock(at(2026, 10, 16, 3, 30, 10))                                                  # Fri 09:00:10
        sent = await tick_user(uid("hal"))
        check("the next day it rings again, whatever happened to today's", len(sent) == 1 and len([r for r in await rings(uid("hal"), hid) if r.sent_at]) == 2, len(sent))
        # follow-up path: a ring nobody acts on is followed up like any reminder, then expires
        await api("ida", "PUT", "/prefs", {"followups": 1, "followup_gap_min": 10})
        setclock(at(2026, 10, 14, 6, 0))
        i1 = await mk("ida", "Follow me", "09:00", "daily")
        setclock(at(2026, 10, 15, 3, 30, 10))
        await tick()
        first = [r for r in await rings(uid("ida"), i1["id"]) if r.sent_at][0]
        check("the ring rang at 09:00", first.status == "sent" and first.followups_sent == 0, (first.status, first.followups_sent))
        setclock(at(2026, 10, 15, 3, 41))
        await tick()                                                                         # sent + 10 min has passed: the follow-up is scheduled
        fr = (await rows(PM.PlReminder, PM.PlReminder.id == first.id))[0]
        check("an unanswered ring is followed up once, like any reminder", fr.followups_sent == 1 and fr.status == "scheduled", (fr.status, fr.followups_sent))
        setclock(at(2026, 10, 15, 3, 41, 30))
        await tick()                                                                         # ...and sent
        fr = (await rows(PM.PlReminder, PM.PlReminder.id == first.id))[0]
        check("the follow-up rings (the same row)", fr.status == "sent" and fr.followups_sent == 1, (fr.status, fr.followups_sent))
        setclock(at(2026, 10, 15, 3, 55))
        await tick()
        fr = (await rows(PM.PlReminder, PM.PlReminder.id == first.id))[0]
        check("...then it expires (no endless pushing)", fr.status == "expired", fr.status)
        r = await api("ida", "POST", f"/reminders/{fr.id}/act", {"action": "reopen"})
        check("an expired ring can be brought back by the learner", r.json()["status"] in ("sent", "scheduled"))

        # -------------------------------------------------------------- push
        section("push: the ring reaches the phone, and its action buttons work")
        await svc.subscribe_push(uid("jon"), {"endpoint": "https://fcm.googleapis.com/fcm/send/jon-device", "p256dh": "p" * 87, "auth": "a" * 22}, "test")
        await api("jon", "PUT", "/prefs", {"followups": 0})
        setclock(at(2026, 10, 14, 6, 0))
        jr = await mk("jon", "Push me", "09:00", "daily")
        SENT.clear()
        setclock(at(2026, 10, 15, 3, 30, 10))
        sent = await tick_user(uid("jon"))
        jring = [r for r in await rings(uid("jon"), jr["id"]) if r.sent_at][0]
        check("the fake push service got exactly one message, carrying the words", len(sent) == 1 and len(SENT) == 1 and b"Push me" in SENT[0][1], (len(sent), len(SENT)))
        check("the ring records the push was accepted", jring.push_state == "accepted", jring.push_state)
        tok = push.make_token(jring.id, "done")
        r = await c.post("/planner/r/act", json={"t": tok})
        check("the notification's Done button (a signed token, no login) ticks it off", r.status_code == 200 and r.json()["status"] == "done", r.text)

        # -------------------------------------------------------------- views
        section("Today, the reminder list and the summary show the rings and the rules")
        setclock(at(2026, 10, 14, 6, 0))
        v = {k: await mk("kim", *a) for k, a in {"w": ("Water", "09:00", "daily"), "g": ("Gym", "20:00", [0, 1, 2]), "s": ("Saturday call", "18:00", [5])}.items()}
        td = (await api("kim", "GET", "/today")).json()
        titles = [(x["title"], x.get("rule_id") == v[k]["id"]) for x in td["reminders"] for k in v if x.get("rule_id") == v[k]["id"]]
        check("Today lists the next rings (water tomorrow, gym today), not the Saturday one", sorted(t for t, _ in titles) == ["Gym", "Water"], titles)
        check("each ring says which rule and how it repeats", all(x.get("rule_id") and x.get("repeat") and "days" in x["repeat"] for x in td["reminders"]), td["reminders"])
        check("a daily ring says 'daily', a Wed one says [0,1,2]", {x["title"]: x["repeat"]["days"] for x in td["reminders"]} == {"Gym": [0, 1, 2], "Water": "daily"})
        check("Today carries every rule - including the Saturday one that has no ring yet", sorted(x["title"] for x in td["repeating"]) == ["Gym", "Saturday call", "Water"], td["repeating"])
        sat_rule = [x for x in td["repeating"] if x["title"] == "Saturday call"][0]
        check("...with its own next ring (Sat 17 Oct 18:00)", sat_rule["next_day"] == "2026-10-17" and sat_rule["next_time"] == "18:00", sat_rule)
        check("the day's reminder count includes today's gym ring", td["counts"]["reminders_today"] == 1, td["counts"])
        sm = (await api("kim", "GET", "/summary")).json()
        check("the Home card's summary counts it too", sm["reminders_today"] == 1, sm)
        ra = (await api("kim", "GET", "/reminders", params={"view": "all"})).json()
        check("the reminder list (All) shows the rings with their repeat", sorted(x["title"] for x in ra["reminders"]) == ["Gym", "Water"] and all(x["repeat"] for x in ra["reminders"]), ra["reminders"])
        ru = (await api("kim", "GET", "/reminders", params={"view": "upcoming"})).json()
        check("the same in Coming up", sorted(x["title"] for x in ru["reminders"]) == ["Gym", "Water"])
        check("each ring has the learner's local day and time", {x["title"]: (x["day"], x["time"]) for x in ra["reminders"]} == {"Gym": ("2026-10-14", "20:00"), "Water": ("2026-10-15", "09:00")}, ra["reminders"])
        gone_rule = v["w"]["id"]
        await api("kim", "DELETE", f"/reminder-rules/{gone_rule}")
        ra = (await api("kim", "GET", "/reminders", params={"view": "all"})).json()
        check("after deleting a rule its leftovers never show as upcoming", [x["title"] for x in ra["reminders"]] == ["Gym"], ra["reminders"])

        # -------------------------------------------------------------- DuSu's context from the real database
        section("DuSu reads the repeating reminders from the real database")
        lines = await life_lines.planner_lines(uid("kim"), users["kim"]["email"])
        rep = [x for x in lines if x.startswith("Repeating reminders")]
        check("the context has the repeating line with both rules and the count", len(rep) == 1 and "Gym - Mon, Tue, Wed at 8:00 PM" in rep[0] and "Saturday call - Sat at 6:00 PM" in rep[0] and "2 in all" in rep[0], rep)
        solo = await mk("lee", "Only Saturdays", "18:00", [5])
        lines = await life_lines.planner_lines(uid("lee"), users["lee"]["email"])
        check("with only a Saturday rule on a Wednesday DuSu is NOT told 'none set'", not any("Reminders: none set." in x for x in lines) and any("Only Saturdays - Sat at 6:00 PM" in x for x in lines), lines)
        check("the opening line (Start Speaking) says nothing about an empty day", await life_lines.opening_plan(uid("lee")) is None)

        # -------------------------------------------------------------- time zones, DST, pause-all, quiet hours
        section("time zones, DST, pause everything, quiet hours")
        setclock(at(2026, 10, 14, 6, 0))
        z = await mk("ned", "Zone", "09:00", "daily")
        zr = await rings(uid("ned"), z["id"])
        zid = zr[0].id
        r = await api("ned", "PUT", "/prefs", {"tz": "Asia/Dubai"})
        zr2 = await rings(uid("ned"), z["id"])
        check("moving to Dubai re-times the same ring (09:00 there = 05:00Z), no copy", len(zr2) == len(zr) == 1 and zr2[0].id == zid and zr2[0].fire_at == at(2026, 10, 15, 5, 0) and zr2[0].status == "scheduled", [(x.id, x.fire_at, x.status) for x in zr2])
        check("the rule's next ring follows the learner's zone", (await api("ned", "GET", "/reminder-rules")).json()["rules"][0]["next_at"] == "2026-10-15T05:00:00+00:00")
        await api("ned", "PUT", "/prefs", {"tz": "America/New_York"})
        setclock(local(dt.date(2026, 10, 31), "00:05", "America/New_York"))
        await svc.materialize_all()
        setclock(local(dt.date(2026, 11, 1), "00:05", "America/New_York"))
        await svc.materialize_all()
        fires = sorted(x.fire_at for x in live(await rings(uid("ned"), z["id"])) if x.meta["day"] >= "2026-10-31")
        check("DST ends on 1 Nov in New York: 09:00 is 13:00Z before the change and 14:00Z after, and each day has exactly one ring",
              fires == [at(2026, 10, 31, 13, 0), at(2026, 11, 1, 14, 0), at(2026, 11, 2, 14, 0)], fires)
        # spring forward: 02:30 on 8 March does not exist in New York
        await api("spr", "PUT", "/prefs", {"tz": "America/New_York"})
        setclock(local(dt.date(2026, 3, 7), "01:00", "America/New_York"))
        sp = await mk("spr", "Gap", "02:30", "daily")
        spr = sorted(live(await rings(uid("spr"), sp["id"])), key=lambda x: x.fire_at)
        check("the 02:30 that does not exist on 8 March rings once, at 03:30 local (07:30Z)", [x.fire_at for x in spr if x.meta["day"] == "2026-03-08"] == [at(2026, 3, 8, 7, 30)] and len(spr) == 2, [(x.meta["day"], x.fire_at) for x in spr])
        # pause everything
        setclock(at(2026, 10, 14, 6, 0))
        pa = await mk("mia", "Paused all", "09:00", "daily")
        await api("mia", "PUT", "/prefs", {"paused_all": True})
        check("'pause everything' withdraws every ring, rules included", live(await rings(uid("mia"), pa["id"])) == [])
        pa2 = await mk("mia", "Made while paused", "10:00", "daily")
        check("a repeating reminder made while everything is paused is stored, active, and makes no ring (nothing may ring)", pa2["status"] == "active" and live(await rings(uid("mia"), pa2["id"])) == [])
        await svc.materialize_all()
        check("...and the materializer makes none while it is on", live(await rings(uid("mia"), pa["id"])) == [])
        check("...but the rule itself is still there, still active", (await api("mia", "GET", "/reminder-rules")).json()["rules"][0]["status"] == "active")
        await api("mia", "PUT", "/prefs", {"paused_all": False})
        check("'resume everything' brings tomorrow's ring back", len(live(await rings(uid("mia"), pa["id"]))) == 1)
        check("...for the rule made while paused too", len(live(await rings(uid("mia"), pa2["id"]))) == 1)
        # quiet hours: 22:00-07:00 by default; a 23:30 ring waits until 07:00
        await api("ola", "PUT", "/prefs", {"followups": 0})
        q = await mk("ola", "Late night", "23:30", "daily")
        setclock(at(2026, 10, 14, 18, 0, 10))
        sent = await tick_user(uid("ola"))
        qr = [r for r in await rings(uid("ola"), q["id"]) if r.meta["day"] == "2026-10-14"][0]
        check("a ring inside quiet hours is deferred to 07:00, not sent", sent == [] and qr.status == "scheduled" and qr.fire_at == local(dt.date(2026, 10, 15), "07:00"), (qr.status, qr.fire_at))
        setclock(local(dt.date(2026, 10, 15), "07:00") + dt.timedelta(seconds=10))
        sent = await tick_user(uid("ola"))
        qr = (await rows(PM.PlReminder, PM.PlReminder.id == qr.id))[0]
        check("at 07:00 it rings, once", len(sent) == 1 and qr.status == "sent" and qr.attempts == 1, (qr.status, qr.attempts))

        # -------------------------------------------------------------- concurrency
        section("concurrency: taps and loops that arrive together")
        setclock(at(2026, 10, 14, 6, 0))
        res = await asyncio.gather(*[api("fay", "POST", "/reminder-rules", {"title": "Same key", "time": "12:00", "days": [1], "client_key": "race-key"}) for _ in range(12)])
        ids = {x.json()["id"] for x in res}
        check("12 simultaneous creates with one client_key: all 200, one rule", all(x.status_code == 200 for x in res) and len(ids) == 1 and await count(PM.PlReminderRule, PM.PlReminderRule.client_key == "race-key") == 1, [x.status_code for x in res])
        res = await asyncio.gather(*[api("fay", "POST", "/reminder-rules", {"title": "Same words", "time": "13:00", "days": [2], "client_key": f"race-w-{i}"}) for i in range(12)])
        check("12 simultaneous double-taps with DIFFERENT keys and the same words: one rule", all(x.status_code == 200 for x in res) and await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("fay"), PM.PlReminderRule.title == "Same words") == 1, [x.status_code for x in res])
        cc = await mk("zed", "Concurrent", "20:00", "daily")
        want = len(await rings(uid("zed"), cc["id"]))
        out = await asyncio.gather(*[svc.materialize_all() for _ in range(8)], return_exceptions=True)
        check("8 materializers at once: no exception, no duplicate row", not [o for o in out if isinstance(o, Exception)] and len(await rings(uid("zed"), cc["id"])) == want, [repr(o) for o in out if isinstance(o, Exception)][:2])
        # an edit racing the materializer must never leave a ring at the OLD time
        pr = await mk("zed", "Race edit", "08:00", "daily")
        for i in range(8):
            a, b = ("08:00", "09:00") if i % 2 == 0 else ("09:00", "08:00")
            await asyncio.gather(api("zed", "PATCH", f"/reminder-rules/{pr['id']}", {"time": b}), svc.materialize_all(), svc.materialize_all())
        now_rule = (await rows(PM.PlReminderRule, PM.PlReminderRule.id == pr["id"]))[0]
        stale_live = [x for x in live(await rings(uid("zed"), pr["id"])) if x.meta["time"] != now_rule.time]
        check("after 8 edits racing 16 materializer passes no live ring has an old time", stale_live == [], [(x.meta, x.status) for x in stale_live])
        check("...and every live ring is at the rule's time", live(await rings(uid("zed"), pr["id"])) != [])

        # the same race with the unlucky interleaving FORCED (the loop above only finds it by chance): the materializer has READ the rule and is parked just before
        # it writes; the edit then runs; only then does the materializer write. The rule row's lock is what makes the materializer's write see the NEW rule.
        fr = await mk("zed", "Forced race", "08:00", "daily")
        orig_upsert = svc._upsert_reminder
        parked, gate = asyncio.Event(), asyncio.Event()
        holder = {}

        async def parked_upsert(*a, **k):
            if asyncio.current_task() is holder.get("m"):
                parked.set()
                await gate.wait()
            return await orig_upsert(*a, **k)

        async def materialize_zed():
            async with db._Session() as s:
                pp = await svc._prefs(s, uid("zed"))
                await svc._materialize_user(s, uid("zed"), pp)
                await s.commit()

        svc._upsert_reminder = parked_upsert
        try:
            holder["m"] = asyncio.create_task(materialize_zed())
            await asyncio.wait_for(parked.wait(), 20)                                          # the materializer holds a read of the OLD rule
            edit = asyncio.create_task(api("zed", "PATCH", f"/reminder-rules/{fr['id']}", {"time": "09:30"}))
            try:
                await asyncio.wait_for(asyncio.shield(edit), 1.5)                              # unguarded, the edit finishes at once; guarded, it waits for the lock
            except asyncio.TimeoutError:
                pass
            gate.set()
            await holder["m"]
            er = await edit
        finally:
            svc._upsert_reminder = orig_upsert
        stale_live = [x for x in live(await rings(uid("zed"), fr["id"])) if x.meta["time"] != "09:30"]
        check("a materializer parked mid-write while the rule is edited never leaves a live ring at the OLD time", er.status_code == 200 and stale_live == [], [(x.meta, x.status) for x in stale_live])
        check("...and the rings that are live are at the NEW time", [x.meta["time"] for x in live(await rings(uid("zed"), fr["id"]))] != [])

        # -------------------------------------------------------------- tasks and habits (the rest of "auto, every day")
        section("tasks and habits repeat on chosen weekdays too, and everything is stored")
        setclock(local(dt.date(2026, 10, 19), "00:05"))                 # Monday 00:05 IST
        hb = (await api("sim", "POST", "/habits", {"title": "Read", "target": 1, "schedule": {"days": [0, 1], "times": ["07:00"]}, "client_key": "hb-1"})).json()
        hr = sorted([x for x in await rows(PM.PlReminder, PM.PlReminder.user_id == uid("sim"), PM.PlReminder.entity_type == "habit", PM.PlReminder.entity_id == hb["id"])], key=lambda x: x.fire_at)
        check("a habit on Mon+Tue at 07:00: Monday's and Tuesday's reminders exist", [x.meta["day"] for x in hr] == ["2026-10-19", "2026-10-20"], [x.meta for x in hr])
        setclock(local(dt.date(2026, 10, 21), "00:05"))                 # Wednesday
        await svc.materialize_all()
        hr = await rows(PM.PlReminder, PM.PlReminder.user_id == uid("sim"), PM.PlReminder.entity_type == "habit", PM.PlReminder.entity_id == hb["id"])
        check("on Wednesday the habit makes nothing for Wednesday or Thursday", sorted(x.meta["day"] for x in hr) == ["2026-10-19", "2026-10-20"], [x.meta for x in hr])
        setclock(local(dt.date(2026, 10, 22), "23:50"))                 # Thursday night: Friday is tomorrow, Monday is not
        await svc.materialize_all()
        setclock(local(dt.date(2026, 10, 25), "23:50"))                 # Sunday night: Monday is tomorrow
        await svc.materialize_all()
        hr = await rows(PM.PlReminder, PM.PlReminder.user_id == uid("sim"), PM.PlReminder.entity_type == "habit", PM.PlReminder.entity_id == hb["id"])
        check("the habit comes back by itself the next Monday (set once)", "2026-10-26" in {x.meta["day"] for x in hr}, sorted(x.meta["day"] for x in hr))
        setclock(local(dt.date(2026, 10, 19), "00:05"))
        tk = (await api("sim", "POST", "/tasks", {"title": "Weekly report", "due_date": "2026-10-19", "due_time": "10:00", "repeat": {"freq": "weekly", "byday": [0, 1], "interval": 1}, "client_key": "tk-1"})).json()
        kids = await rows(PM.PlTask, PM.PlTask.user_id == uid("sim"), PM.PlTask.parent_id == tk["id"], order=(PM.PlTask.occ_date,))
        check("a task repeating weekly on Mon+Tue: Monday's and Tuesday's tasks are made", [str(k.occ_date) for k in kids] == ["2026-10-19", "2026-10-20"], [str(k.occ_date) for k in kids])
        setclock(local(dt.date(2026, 10, 25), "23:50"))
        await svc.materialize_all()
        kids = await rows(PM.PlTask, PM.PlTask.user_id == uid("sim"), PM.PlTask.parent_id == tk["id"], order=(PM.PlTask.occ_date,))
        check("...and the next week's, by itself", {"2026-10-26"} <= {str(k.occ_date) for k in kids} and not ({"2026-10-21", "2026-10-22"} & {str(k.occ_date) for k in kids}), [str(k.occ_date) for k in kids])
        dtk = (await api("sim", "POST", "/tasks", {"title": "Every day", "due_date": "2026-10-25", "repeat": {"freq": "daily", "interval": 1}, "client_key": "tk-2"})).json()
        dk = await rows(PM.PlTask, PM.PlTask.user_id == uid("sim"), PM.PlTask.parent_id == dtk["id"], order=(PM.PlTask.occ_date,))
        check("a daily task has a task for every day ahead", len(dk) >= 2 and {str(k.occ_date) for k in dk} >= {"2026-10-25", "2026-10-26"}, [str(k.occ_date) for k in dk])
        # stored: a brand new session of the service sees everything
        async with db._Session() as s:
            n_rules = (await s.execute(select(func.count()).select_from(PM.PlReminderRule).where(PM.PlReminderRule.user_id == uid("sim")))).scalar()
            n_hab = (await s.execute(select(func.count()).select_from(PM.PlHabit).where(PM.PlHabit.user_id == uid("sim")))).scalar()
            n_tpl = (await s.execute(select(func.count()).select_from(PM.PlTask).where(PM.PlTask.user_id == uid("sim"), PM.PlTask.is_series.is_(True)))).scalar()
        check("rules, habits and repeating tasks are all in Postgres (they survive a restart: nothing lives in memory)", (n_rules, n_hab, n_tpl) == (3, 1, 2), (n_rules, n_hab, n_tpl))

        # -------------------------------------------------------------- old behaviour intact
        section("one-time reminders and habit reminders behave exactly as before")
        setclock(at(2026, 10, 14, 6, 0))
        one = (await api("ann", "POST", "/reminders", {"title": "One time", "time": "21:00", "client_key": "one-1"})).json()
        check("a one-time reminder is still kind 'time', with no rule", one["kind"] == "time" and "rule_id" not in one and one["entity_type"] == "custom", one)
        r = await api("ann", "PATCH", f"/reminders/{one['id']}", {"title": "One time (edited)"})
        check("it can still be edited", r.status_code == 200 and r.json()["title"] == "One time (edited)")
        dup = (await api("ann", "POST", "/reminders", {"title": "ONE TIME (edited)", "time": "21:00", "client_key": "one-2"})).json()
        check("the duplicate guard still works", dup.get("duplicate") is True and dup["id"] == one["id"])
        r = await api("ann", "DELETE", f"/reminders/{one['id']}")
        check("it can still be deleted", r.status_code == 200 and r.json()["status"] == "cancelled")
        hab_row = [x for x in await rows(PM.PlReminder, PM.PlReminder.user_id == uid("sim"), PM.PlReminder.entity_type == "habit")][0]
        check("a habit's row is not mistaken for a rule's ring", not svc.is_rule_occurrence(hab_row) and "rule_id" not in svc.reminder_json(hab_row))
        r = await api("sim", "PATCH", f"/reminders/{hab_row.id}", {"title": "x"})
        check("a habit's reminder is still not editable on its own (404, as before)", r.status_code == 404)
        lst_all = (await api("ann", "GET", "/reminders", params={"view": "all"})).json()["reminders"]
        check("a one-time reminder carries no 'repeat' key", all("repeat" not in x for x in lst_all if x["kind"] == "time"))

        # -------------------------------------------------------------- data rights
        section("data rights: export, delete-all, account deletion and the owner's wipe")
        ex = (await api("ann", "GET", "/export")).json()
        check("the export includes the learner's repeating reminders", len(ex["pl_reminder_rules"]) == ANN_RULES and all(x["user_id"] == uid("ann") for x in ex["pl_reminder_rules"]), len(ex.get("pl_reminder_rules", [])))
        check("...with their days and time", {x["title"]: (x["time"], x["days"]) for x in ex["pl_reminder_rules"]}["Gym"] in (("20:00", [0, 1]), ("20:00", [2]), ("07:00", [0, 1])))
        check("the export holds nobody else's", all(x["user_id"] == uid("ann") for x in ex["pl_reminder_rules"] + ex["pl_reminders"]))
        r = await api("ann", "POST", "/delete-all", {"confirm": True})
        check("delete-all answers 200", r.status_code == 200)
        check("...and every rule and ring of theirs is gone", await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("ann")) == 0 and len(await rings(uid("ann"))) == 0)
        check("...while another learner's rules are untouched", await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("kim")) >= 2)

        async def seed_everything(who):
            """one row in EVERY My Day table for this learner"""
            await api(who, "POST", "/tasks", {"title": "T", "client_key": f"{who}-t"})
            g = (await api(who, "POST", "/goals", {"title": "G", "milestones": ["m1"], "client_key": f"{who}-g"})).json()
            h = (await api(who, "POST", "/habits", {"title": "H", "client_key": f"{who}-h"})).json()
            await api(who, "PUT", f"/habits/{h['id']}/log", {"count": 1})
            await api(who, "POST", "/reminders", {"title": "R", "time": "20:00", "client_key": f"{who}-r"})
            await mk(who, "Rule", "20:00", "daily")
            await svc.subscribe_push(uid(who), {"endpoint": f"https://fcm.googleapis.com/fcm/send/{who}", "p256dh": "p" * 87, "auth": "a" * 22}, "t")
            return g

        await seed_everything("zed")
        seeded = {M_.__tablename__: await count(M_, M_.user_id == uid("zed")) for M_ in PM.PL_TABLES}
        check("the seed put at least one row in every My Day table", all(v > 0 for v in seeded.values()), seeded)
        async with db._Session() as s:
            await svc.delete_rows(s, [uid("zed")])
            await s.commit()
        left = {M_.__tablename__: await count(M_, M_.user_id == uid("zed")) for M_ in PM.PL_TABLES}
        check("delete_rows leaves nothing in ANY My Day table (a forgotten table would be orphaned personal data)", all(v == 0 for v in left.values()), left)
        await db.login(users["zed"])
        await seed_everything("zed")
        ok = await db.delete_user(uid("zed"))
        left = {M_.__tablename__: await count(M_, M_.user_id == uid("zed")) for M_ in PM.PL_TABLES}
        check("deleting the account leaves nothing either (and does not trip a foreign key)", ok and all(v == 0 for v in left.values()), left)
        for who in ("lee", "kim"):
            pass
        n = await db.admin_wipe_users({users["kim"]["email"]})
        check("the owner's wipe removes the rules of everyone it removes, and keeps the kept one's", await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("lee")) == 0
              and await count(PM.PlReminderRule, PM.PlReminderRule.user_id == uid("kim")) >= 2 and n > 0, n)

    # ------------------------------------------------------------------ the whole run
    section("the whole run")
    check("no request ended in a 5xx", not FIVE, FIVE[:5])
    print(f"\n{N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ")
        sys.exit(1)


asyncio.run(main())
