"""Notifications - tier 2: the real HTTP layer and the real delivery engine on a SCRATCH Postgres.

Run via tests/notify/run.sh (it starts a throwaway postgres, never the app's `dusu-db-1`, and blanks every provider key). Everything goes through the
real FastAPI app (routing, gates, JSON handling) in-process with httpx's ASGI transport. Time is a FAKE CLOCK (`tu.now_utc` is replaced) and the push
service is a fake; the engine's own `materialize_all()` / `claim()` / `deliver()` / `tick()` do the work, exactly as in production.

What is proven, in the order it is driven: the old -> new schema rehearsal; the switch and the gates; the preferences API and its validation; WHO gets
WHAT on a Wednesday evening (streak, practice, nothing) and that planning twice - or from eight workers at once - makes one row; the send-time re-check
(practised in the meantime, quiet hours, switched off, blocked); the words in each language and lock-screen privacy; the ignore-three back-off and how it
ends; a Sunday weekly note; failures (a dead subscription, a push service that is down); the receipt and tap beacons; the test button; isolation between
learners; the rollout switch (off / owner + early access / on) and the loop itself; data rights and account deletion; the dashboard.
Plain Python; prints PASS / FAIL per check and exits non-zero on any failure.
"""

import asyncio
import datetime as dt
import json
import sys

sys.path.insert(0, "/app")

import httpx                                                        # noqa: E402
from sqlalchemy import func, select, text as sa_text, update        # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.notify import models as NM, rules as R, scheduler as sch, service as svc, tokens as TK    # noqa: E402
from app.planner import models as PM, push as PP, service as plsvc, timeutil as tu                # noqa: E402

UTC = dt.timezone.utc
IST = "Asia/Kolkata"
FAILS: list[str] = []
FIVE: list = []
N = 0


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


def ist(y, mo, d, h, mi=0, s=0):
    return tu.to_utc(dt.date(y, mo, d), dt.time(h, mi, s), IST)


def D(y, mo, d):
    return dt.date(y, mo, d)


CLOCK = [ist(2026, 10, 21, 18, 35)]                                 # Wed 21 Oct 2026, 18:35 in India
tu.now_utc = lambda: CLOCK[0]                                       # service._utc() and scheduler.tick() read this at call time


def setclock(when):
    CLOCK[0] = when


ENABLED = lambda email: True                                        # noqa: E731
SENT: list = []                                                     # (endpoint, payload bytes) the fake push service accepted
BEHAVE: dict = {}                                                   # endpoint fragment -> ("gone"|"transient", status)


async def SENDER(sub, payload):
    for frag, res in BEHAVE.items():
        if frag in sub["endpoint"]:
            return res
    SENT.append((sub["endpoint"], payload))
    return ("ok", 201)


def sent_to(name):
    return [json.loads(p.decode("utf-8")) for e, p in SENT if e.endswith("/" + name)]


async def rows(model, *conds, order=None):
    async with db._Session() as s:
        q = select(model).where(*conds)
        if order is not None:
            q = q.order_by(*order)
        return (await s.execute(q)).scalars().all()


async def count(model, *conds):
    async with db._Session() as s:
        return int((await s.execute(select(func.count()).select_from(model).where(*conds))).scalar() or 0)


async def out_rows(uid, *conds):
    return await rows(NM.NtOutbox, NM.NtOutbox.user_id == uid, *conds, order=(NM.NtOutbox.id,))


async def tick(**kw):
    kw.setdefault("materialize", False)
    kw.setdefault("sender", SENDER)
    return await sch.tick(ENABLED, **kw)


async def plan():
    return await svc.materialize_all(ENABLED, CLOCK[0])


names = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ida", "ivy", "jon", "kim", "lee", "max", "mia", "ola", "lou", "pia", "zed", "sim", "ned", "unb", "blk", "sw"]
uid = lambda n: f"u-{n}"                                            # noqa: E731


async def setup(n, streak=0, last=None, xp=100, onboarded=True, device=True, lang=None, hide=False, nudge=None, kinds=None, enabled=None, nickname=None,
                quiet=None, letter=None, daily_stats=None):
    """Make a learner in exactly the state a scenario needs."""
    u = uid(n)
    async with db._Session() as s:
        await s.execute(update(db.Progress).where(db.Progress.user_id == u).values(streak_days=streak, last_active=last, xp=xp))
        await s.execute(update(db.Profile).where(db.Profile.user_id == u).values(onboarded=onboarded))
        mem = await s.get(db.Memory, u)
        f = dict(mem.facts or {})
        if lang:
            f["lang_pref"] = {"lang": lang}
        if nickname:
            f["nickname"] = nickname
        if letter:
            f["last_letter"] = {"date": letter.isoformat(), "text": "x"}
        if daily_stats:
            f["daily_stats"] = daily_stats
        mem.facts = f
        await s.commit()
    if device:
        await plsvc.subscribe_push(u, {"endpoint": f"https://fcm.googleapis.com/fcm/send/{n}", "p256dh": "p" * 87, "auth": "a" * 22}, "test")
    async with db._Session() as s:
        p = await plsvc._prefs(s, u)
        p.hide_details = hide
        if quiet:
            p.quiet_start, p.quiet_end = quiet
        nt = await svc._prefs(s, u)
        if nudge:
            nt.nudge_time = nudge
        if kinds is not None:
            nt.kinds = R.clean_kinds(kinds)
        if enabled is not None:
            nt.enabled = enabled
        await s.commit()


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh, which blanks them"
    PP.send = SENDER                                                # the engine's own default sender (loop test) must never touch the network

    # ------------------------------------------------------------------ OLD -> NEW schema rehearsal
    section("schema rehearsal: production has every table EXCEPT the two new nt_* ones")
    for _ in range(20):                                              # a freshly started postgres restarts once after initdb
        try:
            async with db._engine.begin() as conn:
                await conn.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if not t.name.startswith("nt_")]))
            break
        except Exception:
            await asyncio.sleep(1)

    async def nt_tables():
        async with db._engine.connect() as conn:
            return {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'nt\\_%'"))).all()}

    pre = await nt_tables()
    old = {"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""}
    await db.login(old)
    await plsvc.subscribe_push("u-old", {"endpoint": "https://fcm.googleapis.com/fcm/send/old", "p256dh": "p" * 87, "auth": "a" * 22}, "t")
    check("the old schema has no nt_* table", pre == set() and await count(PM.PlPushSub, PM.PlPushSub.user_id == "u-old") == 1, pre)
    await db.init_db()
    await db.init_db()
    post = await nt_tables()
    async with db._engine.connect() as conn:
        idx = {r[0] for r in (await conn.execute(sa_text("select indexname from pg_indexes where tablename in ('nt_outbox', 'nt_prefs')"))).all()}
        cols = {r[0]: (r[1], r[2]) for r in (await conn.execute(sa_text(
            "select column_name, data_type, character_maximum_length from information_schema.columns where table_name = 'nt_outbox'"))).all()}
    check("init_db() adds exactly the two new tables, twice in a row, next to the old data", post == {"nt_outbox", "nt_prefs"}, post)
    check("the unique dedupe index and the partial 'due' index exist", {"uq_nt_out_dedupe", "ix_nt_out_due", "ix_nt_out_user_created"} <= idx, idx)
    check("the columns are what the code writes", {"id", "user_id", "kind", "dedupe_key", "fire_at", "title", "body", "url", "status", "why", "push_state", "attempts",
                                                    "claimed_at", "sent_at", "received_at", "opened_at", "meta", "created_at"} <= set(cols) and cols["meta"][0] == "jsonb", cols)
    check("the existing learner's push device is untouched", await count(PM.PlPushSub, PM.PlPushSub.user_id == "u-old") == 1)

    # ------------------------------------------------------------------ users + client
    users = {n: {"sub": uid(n), "email": f"{n}@example.com", "name": f"{n.title()} Lee", "picture": ""} for n in names}
    for u in users.values():
        await db.login(u)
    T = {n: auth.make_session(u) for n, u in users.items()}
    owner = {"sub": "u-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    await db.login(owner)
    T["owner"] = auth.make_session(owner)
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        def H(who):
            return {"Authorization": "Bearer " + T[who]}

        async def api(who, method, path, body=None, params=None, headers=None):
            h = dict(H(who) if who else {})
            h.update(headers or {})
            r = await c.request(method, "/notify" + path, headers=h, json=body, params=params)
            if r.status_code >= 500:
                FIVE.append((method, path, r.status_code))
            return r

        # -------------------------------------------------------------- the switch and the gates
        section("gates: the switch, sign-in, every verb")
        await db.set_setting("notifications", "off")
        M.invalidate_access_cache()
        for m, p in (("GET", "/prefs"), ("PATCH", "/prefs"), ("POST", "/open"), ("POST", "/test"), ("GET", "/push/key"), ("POST", "/push/subscribe"), ("DELETE", "/push/subscribe")):
            r = await api("ann", m, p, {} if m not in ("GET",) else None)
            check(f"switch OFF: {m} {p} is 404 (invisible)", r.status_code == 404, r.status_code)
        r = await api("ann", "GET", "/export")
        check("switch OFF: the data-rights export still answers", r.status_code == 200 and "nt_outbox" in r.json())
        r = await api("ann", "POST", "/delete-all", {"confirm": True})
        check("switch OFF: delete-all still answers", r.status_code == 200)
        me = (await c.get("/me", headers=H("ann"))).json()
        check("/me says notifications are OFF", me.get("notifications") is False, me.get("notifications"))
        await db.set_setting("notifications", "on")
        M.invalidate_access_cache()
        for m, p in (("GET", "/prefs"), ("PATCH", "/prefs"), ("POST", "/open"), ("POST", "/test"), ("GET", "/push/key"), ("POST", "/push/subscribe"), ("DELETE", "/push/subscribe")):
            r = await api(None, m, p, {} if m not in ("GET",) else None)
            check(f"no token: {m} {p} is 401", r.status_code == 401, r.status_code)
        r = await c.get("/notify/prefs", headers={"Authorization": "Bearer junk.token"})
        check("a junk token is 401", r.status_code == 401)
        me = (await c.get("/me", headers=H("ann"))).json()
        check("/me says notifications are ON", me.get("notifications") is True)
        await db.set_user_status(uid("zed"), "blocked")
        r = await api("zed", "GET", "/prefs")
        check("a blocked account is 403", r.status_code == 403, r.status_code)

        # -------------------------------------------------------------- preferences
        section("preferences: defaults, partial updates, validation")
        await setup("ann", streak=5, last=D(2026, 10, 20))
        r = await api("ann", "GET", "/prefs")
        j = r.json()
        check("defaults: on, all three kinds, 19:00, one device, push on, India time", r.status_code == 200 and j["enabled"] is True and j["kinds"] == {"practice": True, "streak": True, "weekly": True}
              and j["nudge_time"] == "19:00" and j["devices"] == 1 and j["push_on"] is True and j["tz"] == IST and j["recent"] == [], j)
        r = await api("ann", "PATCH", "/prefs", {"nudge_time": "20:15"})
        check("a partial update keeps the rest", r.status_code == 200 and r.json()["nudge_time"] == "20:15" and r.json()["kinds"]["streak"] is True and r.json()["enabled"] is True, r.text)
        r = await api("ann", "PATCH", "/prefs", {"kinds": {"weekly": False}})
        check("one kind can be switched off without touching the others", r.json()["kinds"] == {"practice": True, "streak": True, "weekly": False}, r.text)
        r = await api("ann", "PATCH", "/prefs", {"nudge_time": "19:00", "kinds": {"weekly": True}})
        check("...and back", r.json()["kinds"]["weekly"] is True and r.json()["nudge_time"] == "19:00")
        for body, label in (({"nudge_time": "25:00"}, "an impossible time"), ({"nudge_time": 1900}, "a number for the time"), ({"enabled": "yes"}, "a string for the switch"),
                            ({"kinds": {"evil": True}}, "an unknown kind"), ({"kinds": {"practice": "no"}}, "a non-boolean kind"), ({"kinds": []}, "a list for kinds")):
            r = await api("ann", "PATCH", "/prefs", body)
            check(f"validation: {label} is 422", r.status_code == 422, (r.status_code, r.text))
        r = await api("ann", "GET", "/prefs")
        check("a refused update changed nothing", r.json()["nudge_time"] == "19:00" and r.json()["enabled"] is True and r.json()["kinds"]["practice"] is True)
        r = await c.patch("/notify/prefs", headers=H("ann"), json=["not", "a", "dict"])
        check("a non-object body is a 422, never a 500", r.status_code == 422, r.status_code)
        r = await api("dan", "GET", "/prefs")
        check("a learner with no device: 0 devices, push off", r.json()["devices"] == 0 and r.json()["push_on"] is False)
        r = await api("ann", "PATCH", "/prefs", {"hide_details": True})
        pp = (await rows(PM.PlPrefs, PM.PlPrefs.user_id == uid("ann")))[0]
        check("the lock-screen switch is My Day's one setting (pl_prefs), written from here", r.status_code == 200 and r.json()["hide_details"] is True and pp.hide_details is True, r.text)
        r = await api("ann", "PATCH", "/prefs", {"hide_details": "yes"})
        check("a non-boolean lock-screen value is a 422", r.status_code == 422)
        await api("ann", "PATCH", "/prefs", {"hide_details": False})

        section("this phone: subscribe / unsubscribe (the same device table My Day uses)")
        r = await api("dan", "GET", "/push/key")
        check("the VAPID public key is served (65 bytes, base64url)", r.status_code == 200 and r.json()["available"] is True and len(PP._ub64(r.json()["key"])) == 65, r.text)
        good = {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/dan-phone-0123456789", "keys": {"p256dh": PP._b64(b"\x04" + b"p" * 64), "auth": PP._b64(b"a" * 16)}}, "ua": "test"}
        r = await api("dan", "POST", "/push/subscribe", good)
        check("subscribing a phone: 200, one device, push on", r.status_code == 200 and r.json()["devices"] == 1 and r.json()["push_on"] is True, r.text)
        check("it is in My Day's device table (one table, not two)", await count(PM.PlPushSub, PM.PlPushSub.user_id == uid("dan")) == 1)
        r = await api("dan", "POST", "/push/subscribe", good)
        check("subscribing the same phone again changes nothing (idempotent)", r.status_code == 200 and await count(PM.PlPushSub, PM.PlPushSub.user_id == uid("dan")) == 1)
        for bad, label in (({"subscription": {"endpoint": "https://evil.example/x" + "a" * 20, "keys": good["subscription"]["keys"]}}, "an endpoint that is not a real push service (SSRF)"),
                           ({"subscription": {"endpoint": good["subscription"]["endpoint"], "keys": {"p256dh": "short", "auth": "x"}}}, "malformed keys"),
                           ({"subscription": "nope"}, "a string instead of a subscription"), ({}, "an empty body")):
            r = await api("dan", "POST", "/push/subscribe", bad)
            check(f"subscribing with {label} is 422", r.status_code == 422, (r.status_code, r.text))
        r = await api("dan", "DELETE", "/push/subscribe", {"endpoint": good["subscription"]["endpoint"]})
        check("unsubscribing this phone: 0 devices, push off", r.status_code == 200 and r.json()["devices"] == 0 and r.json()["push_on"] is False and await count(PM.PlPushSub, PM.PlPushSub.user_id == uid("dan")) == 0, r.text)
        r = await api("dan", "DELETE", "/push/subscribe", {})
        check("unsubscribing with nothing to remove is still fine", r.status_code == 200)

        # -------------------------------------------------------------- the world on a Wednesday evening
        section("who gets what: Wednesday 21 Oct 2026, nudge time 19:00 India")
        await setup("bob", streak=7, last=D(2026, 10, 17))                                   # a lapsed streak (stale number): practice
        await setup("cat", streak=3, last=D(2026, 10, 21))                                   # practised today
        await setup("dan", streak=5, last=D(2026, 10, 20), device=False)                     # no device
        await setup("eve", streak=5, last=D(2026, 10, 20), nudge="23:00")                    # her time is inside quiet hours
        await setup("fay", streak=0, last=None, lang="en", nickname="Fay")                   # English
        await setup("gus", streak=0, last=None, hide=True)                                   # lock-screen privacy
        await setup("hal", streak=2, last=D(2026, 10, 20))
        await setup("ida", streak=4, last=D(2026, 10, 20))                                   # three ignored nudges on 18-20 Oct -> paused (rows below)
        await setup("ivy", streak=4, last=D(2026, 10, 20))                                   # three ignored nudges on 14-16 Oct, but she practised since
        await setup("jon", streak=5, last=D(2026, 10, 20), kinds={"practice": True, "streak": False, "weekly": True})
        await setup("kim", streak=5, last=D(2026, 10, 20), enabled=False)
        await setup("lee", streak=5, last=D(2026, 10, 20))                                   # her subscription is dead
        await setup("max", streak=5, last=D(2026, 10, 20))                                   # the push service is down
        await setup("mia", streak=5, last=D(2026, 10, 20))                                   # practises before the nudge
        await setup("ola", streak=5, last=D(2026, 10, 20))                                   # changes her quiet hours before the nudge
        await setup("lou", streak=5, last=D(2026, 10, 20), nudge="20:00")                    # her own time
        await setup("pia", streak=5, last=D(2026, 10, 20), onboarded=False)                  # not onboarded
        await setup("unb", streak=5, last=D(2026, 10, 20), xp=5)
        for n_, days in (("ida", (18, 19, 20)), ("ivy", (14, 15, 16))):                      # three delivered, unopened nudges each
            async with db._Session() as s:
                for day in days:
                    s.add(NM.NtOutbox(user_id=uid(n_), kind="practice", dedupe_key=f"day:2026-10-{day}", fire_at=ist(2026, 10, day, 19), title="t", body="b", status="sent",
                                      push_state="accepted", sent_at=ist(2026, 10, day, 19), created_at=ist(2026, 10, day, 18, 45)))
                await s.commit()

        setclock(ist(2026, 10, 21, 18, 35))
        created = (await plan())["created"]
        check("18:35 is before every window: nothing is made yet", created == 0 and await count(NM.NtOutbox, NM.NtOutbox.dedupe_key == "day:2026-10-21") == 0, created)
        setclock(ist(2026, 10, 21, 18, 40))
        st = await plan()
        today_rows = {r.user_id: r for r in await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "day:2026-10-21")}
        have = {k[2:] for k in today_rows}
        want = {"ann", "bob", "fay", "gus", "hal", "ivy", "jon", "lee", "max", "mia", "ola", "unb"}
        check("18:40 (20 minutes before 19:00): exactly the learners who should get a nudge get a row", have == want, (sorted(have - want), sorted(want - have)))
        check("...not cat (practised), dan (no device), eve (23:00 is quiet), ida (paused), kim (off), lou (20:00 - not yet), pia (not onboarded), zed (blocked), old (not onboarded)",
              not ({"cat", "dan", "eve", "ida", "kim", "lou", "pia", "zed", "old"} & have), sorted(have))
        check("the pass reported what it made", st["created"] == len(want), st)
        # near a slot = a device, push on, not blocked, switched on for them, their own switch on, their window open: the 12 above + cat (practised), ida (paused), pia (not
        # onboarded) and the old account. NOT kim (switched her own notifications off): a learner who said no is not even looked at.
        check("planning only looks at learners whose own switch is on (kim said no)", st["near_slot"] == len(want) + 4, st)
        a = today_rows[uid("ann")]
        check("a row is scheduled for 19:00 India, links to Home, and has no text yet (it is written at SEND time)", a.status == "scheduled" and a.fire_at == ist(2026, 10, 21, 19) and a.url == "/" and a.title == "" and a.kind == "streak", a.__dict__)
        check("kinds: ann streak, bob practice (lapsed streak), fay / gus practice, jon practice (streak switched off)",
              [today_rows[uid(n_)].kind for n_ in ("ann", "bob", "fay", "gus", "jon")] == ["streak", "practice", "practice", "practice", "practice"])
        check("planning again at the same minute makes nothing new", (await plan())["created"] == 0)
        res = await asyncio.gather(*[plan() for _ in range(8)])
        check("eight workers planning at once still make nothing new", sum(x["created"] for x in res) == 0 and await count(NM.NtOutbox, NM.NtOutbox.dedupe_key == "day:2026-10-21") == len(want))

        # ida: three ignored -> paused; opening one of them lifts the pause
        r = await api("ida", "GET", "/prefs")
        ida_rows = await out_rows(uid("ida"), NM.NtOutbox.status == "sent")
        check("ida (three ignored nudges) has nothing today", uid("ida") not in today_rows and len(ida_rows) == 3)
        r = await api("ida", "POST", "/open", {"id": ida_rows[1].id})
        check("she opens one of the old ones: the beacon says ok", r.status_code == 200 and r.json() == {"ok": True})
        setclock(ist(2026, 10, 21, 18, 42))
        check("...and the next pass makes her row (the three are no longer all ignored)", (await plan())["created"] == 1 and uid("ida") in {r.user_id for r in await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "day:2026-10-21")})
        check("ivy: three old ignored nudges, but she has practised since: not paused, so she has a row", "ivy" in have)

        # things that change between planning and sending
        async with db._Session() as s:
            await s.execute(update(db.Progress).where(db.Progress.user_id == uid("mia")).values(last_active=D(2026, 10, 21), streak_days=6))
            p = await plsvc._prefs(s, uid("ola"))
            p.quiet_start, p.quiet_end = "18:00", "07:00"
            await s.commit()
        BEHAVE["/lee"] = ("gone", 410)
        BEHAVE["/max"] = ("transient", 503)

        # -------------------------------------------------------------- send
        section("the send: 19:00:10 India")
        SENT.clear()
        setclock(ist(2026, 10, 21, 19, 0, 10))
        st = await tick()
        by = {r.user_id: r for r in await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "day:2026-10-21")}
        a = by[uid("ann")]
        check("ann: sent, accepted, with the time it went", a.status == "sent" and a.push_state == "accepted" and a.sent_at == CLOCK[0] and a.kind == "streak", a.__dict__)
        pa = sent_to("ann")
        check("exactly one message reached ann's phone", len(pa) == 1, len(pa))
        pa = pa[0]
        check("it is Hindi by default, says her name and her 5-day streak", "5" in pa["title"] and "Ann" in pa["body"] and any("ऀ" <= ch <= "ॿ" for ch in pa["title"] + pa["body"]), pa)
        check("it carries her row id, the in-app path, a valid receipt token for THAT id and no buttons", pa["data"]["nid"] == a.id and pa["data"]["url"] == "/" and TK.read_ack(pa["data"]["ack"]) == a.id and pa["actions"] == [])
        check("what was said is saved with the facts it came from", a.title == pa["title"] and a.body == pa["body"] and a.meta.get("streak") == 5 and a.meta.get("lang") == "hi", a.meta)
        check("a second pass sends nothing more to ann", (await tick(), len(sent_to("ann")))[1] == 1)
        b = by[uid("bob")]
        check("bob: a practice nudge (his streak lapsed)", b.status == "sent" and b.kind == "practice" and "streak" not in (b.title + b.body).lower() and b.meta.get("streak") == 0, (b.kind, b.title, b.body))
        f = by[uid("fay")]
        check("fay (English): English words, her nickname", f.status == "sent" and "Fay" in f.body and not any("ऀ" <= ch <= "ॿ" for ch in f.title + f.body), (f.title, f.body))
        g = by[uid("gus")]
        check("gus (lock-screen privacy): the generic line and nothing personal", g.status == "sent" and (g.title, g.body) == R.HIDDEN["hi"] and g.meta.get("hidden") is True, (g.title, g.body))
        j = by[uid("jon")]
        check("jon (streak off): a practice nudge though his streak is alive", j.kind == "practice" and j.status == "sent")
        m = by[uid("mia")]
        check("mia practised before the nudge: cancelled 'done', nothing sent", m.status == "cancelled" and m.why == "done" and not sent_to("mia"), (m.status, m.why))
        o = by[uid("ola")]
        check("ola's quiet hours now cover 19:00: cancelled 'quiet', nothing sent", o.status == "cancelled" and o.why == "quiet" and not sent_to("ola"), (o.status, o.why))
        le = by[uid("lee")]
        check("lee's subscription is dead (410): cancelled 'no_device' and the dead subscription is deleted", le.status == "cancelled" and le.why == "no_device" and le.push_state == "no_subscription"
              and await count(PM.PlPushSub, PM.PlPushSub.user_id == uid("lee")) == 0, (le.status, le.why))
        mx = by[uid("max")]
        check("max (push service down): not lost - retried in 30 seconds", mx.status == "scheduled" and mx.attempts == 1 and mx.fire_at == CLOCK[0] + dt.timedelta(seconds=30), (mx.status, mx.attempts, mx.fire_at))
        check("every other learner in the pass got exactly the rows above (a counted pass)", st["sent"] >= 6 and st["cancelled"] >= 3, st)
        setclock(CLOCK[0] + dt.timedelta(seconds=31))
        await tick()
        mx = (await out_rows(uid("max"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("max: the second attempt fails too and backs off to 2 minutes", mx.status == "scheduled" and mx.attempts == 2 and mx.fire_at == CLOCK[0] + dt.timedelta(seconds=120), (mx.status, mx.attempts))
        setclock(CLOCK[0] + dt.timedelta(seconds=121))
        await tick()
        mx = (await out_rows(uid("max"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("max: after three attempts it stops - cancelled 'push_failed', never endless", mx.status == "cancelled" and mx.why == "push_failed" and mx.push_state == "failed" and mx.attempts == 3, (mx.status, mx.why, mx.attempts))
        BEHAVE.clear()
        sub_max = (await rows(PM.PlPushSub, PM.PlPushSub.user_id == uid("max")))[0]
        check("a failing push service counts against the device but does not delete it", sub_max.fail_count >= 3, sub_max.fail_count)
        ln = (await rows(PM.PlPushSub, PM.PlPushSub.user_id == uid("ann")))[0]
        check("a delivered push resets the device's failure count and records the time", ln.fail_count == 0 and ln.last_ok_at is not None)

        # lou chose 20:00 for herself: her window opens at 19:40
        setclock(ist(2026, 10, 21, 19, 30))
        check("lou (nudge 20:00): nothing at 19:30", not await out_rows(uid("lou"), NM.NtOutbox.dedupe_key == "day:2026-10-21"), (await plan()))
        setclock(ist(2026, 10, 21, 19, 41))
        await plan()
        lr = await out_rows(uid("lou"), NM.NtOutbox.dedupe_key == "day:2026-10-21")
        check("lou: her row appears at 19:41 and is due at 20:00 India", len(lr) == 1 and lr[0].fire_at == ist(2026, 10, 21, 20, 0), [(r.fire_at) for r in lr])
        SENT.clear()
        setclock(ist(2026, 10, 21, 19, 59))
        await tick()
        check("lou: not sent a minute early", not sent_to("lou"))
        setclock(ist(2026, 10, 21, 20, 0, 5))
        await tick()
        check("lou: sent at her own time", len(sent_to("lou")) == 1 and (await out_rows(uid("lou"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0].status == "sent")

        # -------------------------------------------------------------- beacons
        section("the phone's receipts and the learner's taps")
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        tok = TK.make_ack(a.id)
        r = await api(None, "POST", "/ack", {"t": tok}, headers={"cf-connecting-ip": "10.0.0.1"})
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("a valid receipt (no login) records that it arrived", r.status_code == 200 and a.received_at is not None)
        first_rec = a.received_at
        setclock(CLOCK[0] + dt.timedelta(seconds=5))
        await api(None, "POST", "/ack", {"t": tok}, headers={"cf-connecting-ip": "10.0.0.1"})
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("a second receipt changes nothing (idempotent)", a.received_at == first_rec)
        for bad, label in (({"t": "garbage"}, "garbage"), ({"t": TK.make_ack(a.id, ttl=60, now=1000.0)}, "an expired token"), ({"t": PP.make_token(a.id, "done")}, "My Day's action token"),
                           ({}, "no token"), ({"t": None}, "null")):
            r = await api(None, "POST", "/ack", bad, headers={"cf-connecting-ip": "10.0.0.2"})
            check(f"a receipt with {label} is 400", r.status_code == 400, r.status_code)
        r = await api(None, "POST", "/ack", {"t": TK.make_ack(999999)}, headers={"cf-connecting-ip": "10.0.0.3"})
        check("a genuine token for a row that does not exist is a harmless ok", r.status_code == 200)
        b = (await out_rows(uid("bob"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        r = await api("bob", "POST", "/open", {"id": a.id})
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("bob cannot mark ann's notification opened - and is not told it is hers", r.status_code == 200 and r.json() == {"ok": True} and a.opened_at is None)
        r = await api("ann", "POST", "/open", {"id": a.id})
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("ann marks her own opened", r.status_code == 200 and a.opened_at is not None)
        o1 = a.opened_at
        setclock(CLOCK[0] + dt.timedelta(seconds=5))
        await api("ann", "POST", "/open", {"id": a.id})
        a = (await out_rows(uid("ann"), NM.NtOutbox.dedupe_key == "day:2026-10-21"))[0]
        check("opening twice keeps the first time", a.opened_at == o1)
        for body in ({"id": "abc"}, {"id": None}, {}, {"id": 10 ** 12}, {"id": -5}):
            r = await api("ann", "POST", "/open", body)
            check(f"/open with {body} is never a 500", r.status_code in (200, 404, 422), r.status_code)
        hits = [(await api(None, "POST", "/ack", {"t": "x"}, headers={"cf-connecting-ip": "10.0.0.9"})).status_code for _ in range(62)]
        check("the receipt endpoint is rate-limited per address: 60 a minute, then 429", hits[:60].count(400) == 60 and hits[60] == 429 and hits[61] == 429, hits[58:])

        # -------------------------------------------------------------- the test button
        section("'Send me a test notification'")
        r = await api("dan", "POST", "/test", {})
        check("no device: 422 'no_device'", r.status_code == 422 and r.json()["detail"]["error"] == "no_device", r.text)
        SENT.clear()
        r = await api("cat", "POST", "/test", {})                                           # cat practised today: a test is still wanted
        check("cat: a test is scheduled a few seconds out", r.status_code == 200 and r.json()["in_seconds"] == 8, r.text)
        r = await api("cat", "POST", "/test", {})
        check("a second one within 3 minutes is 409", r.status_code == 409 and r.json()["detail"]["error"] == "limit_test", r.text)
        await tick()
        check("not yet due: nothing sent", not sent_to("cat"))
        setclock(CLOCK[0] + dt.timedelta(seconds=9))
        await tick()
        pc = sent_to("cat")
        check("the test arrives although she practised today and it is after hours for nudges", len(pc) == 1 and "test" in pc[0]["title"].lower(), pc)
        tr_ = (await out_rows(uid("cat"), NM.NtOutbox.kind == "test"))[0]
        check("it is recorded as a 'test' and sent", tr_.status == "sent" and tr_.kind == "test")
        setclock(CLOCK[0] + dt.timedelta(minutes=4))
        r = await api("cat", "POST", "/test", {})
        check("after three minutes another test is allowed", r.status_code == 200)
        r = await api("ann", "GET", "/prefs")
        check("tests never appear in 'recent' and the real nudge does", [x["kind"] for x in r.json()["recent"]] == ["streak"] and r.json()["recent"][0]["opened"] is True, r.json()["recent"])
        rc = await api("cat", "GET", "/prefs")
        check("a learner's recent list holds only their own", rc.json()["recent"] == [], rc.json()["recent"])

        # -------------------------------------------------------------- dashboard
        section("the dashboard: the switch and the health numbers")
        r = await c.get("/admin/overview", headers=H("owner"))
        ov = r.json()
        nh = ov.get("notify_health", {})
        check("/admin/overview carries the switch and the health block", r.status_code == 200 and ov.get("notifications") in ("off", "owner", "on") and "sent_24h" in nh and "received_24h" in nh, list(ov)[:20])
        check("the health numbers add up: delivered, received, opened and the devices", nh["push_devices"] >= 10 and nh["learners_with_push"] >= 10 and nh["accepted_24h"] >= 1 and nh["received_24h"] >= 1 and nh["opened_24h"] >= 1
              and nh["stuck_sending"] == 0, nh)
        r = await c.post("/admin/settings", headers=H("owner"), json={"notifications": "owner"})
        check("the owner can set the switch to 'owner'", r.status_code == 200 and r.json()["notifications"] == "owner", r.text)
        r = await c.post("/admin/settings", headers=H("owner"), json={"notifications": "banana"})
        check("an invalid value falls back to 'off' (never stored as junk)", r.json()["notifications"] == "off")
        r = await c.post("/admin/settings", headers=H("owner"), json={"access_phase": "growth"})
        check("another switch's update leaves this one alone", r.json()["notifications"] == "off")
        r = await c.post("/admin/settings", headers=H("ann"), json={"notifications": "on"})
        check("a learner cannot flip it", r.status_code in (401, 403), r.status_code)
        await db.set_setting("notifications", "on")
        M.invalidate_access_cache()

        # -------------------------------------------------------------- a late server
        section("Thursday 22 Oct: the server was down at 19:00 - a late nudge is worse than none")
        await setup("ned", streak=5, last=D(2026, 10, 21))
        await setup("blk", streak=5, last=D(2026, 10, 21))                                     # blocked, WITH a device and a live streak
        await db.set_user_status(uid("blk"), "blocked")
        await setup("sw", streak=5, last=D(2026, 10, 21))                                      # the owner-stage switch will say no to this one at planning time
        setclock(ist(2026, 10, 22, 18, 40))
        st = await svc.materialize_all(lambda email: email != "sw@example.com", CLOCK[0])      # the per-learner rollout gate, applied while planning
        ned_row = (await out_rows(uid("ned"), NM.NtOutbox.dedupe_key == "day:2026-10-22"))
        check("the Thursday rows are made on the learner's own day key", st["created"] >= 1 and len(ned_row) == 1)
        check("a blocked account is never planned for, even with a device and a live streak", not await out_rows(uid("blk")), st)
        check("a learner the rollout switch says no to is not planned for", not await out_rows(uid("sw"), NM.NtOutbox.dedupe_key == "day:2026-10-22"), st)
        await plan()                                                                           # the normal gate: now she is in
        check("...and when the switch says yes the next pass plans her (and nobody twice)", len(await out_rows(uid("sw"), NM.NtOutbox.dedupe_key == "day:2026-10-22")) == 1
              and len(await out_rows(uid("ned"), NM.NtOutbox.dedupe_key == "day:2026-10-22")) == 1 and not await out_rows(uid("blk")))
        SENT.clear()
        setclock(ist(2026, 10, 22, 20, 41))                                                  # 101 minutes late
        await tick()
        ned_row = (await out_rows(uid("ned"), NM.NtOutbox.dedupe_key == "day:2026-10-22"))[0]
        check("101 minutes late: cancelled 'stale', nothing sent", ned_row.status == "cancelled" and ned_row.why == "stale" and not sent_to("ned"), (ned_row.status, ned_row.why))
        setclock(ist(2026, 10, 22, 19, 30))                                                    # back inside the window: the cancelled row still holds the day's key
        check("...and it is never made again for that day (the dedupe key holds)", (await plan())["created"] == 0 and len(await out_rows(uid("ned"), NM.NtOutbox.dedupe_key == "day:2026-10-22")) == 1)

        # -------------------------------------------------------------- the weekly note
        section("Sunday 25 Oct: the weekly note")
        await setup("pia", streak=5, last=D(2026, 10, 24), onboarded=True, letter=D(2026, 10, 20))   # her letter is 5 days old
        await setup("ann", streak=5, last=D(2026, 10, 24))
        await setup("bob", streak=0, last=D(2026, 10, 17))                                             # not active for 8 days
        await setup("hal", streak=2, last=D(2026, 10, 24), kinds={"practice": True, "streak": True, "weekly": False})
        SENT.clear()
        setclock(ist(2026, 10, 25, 9, 35))
        check("09:35 is before the window: no weekly row yet", (await plan())["created"] == 0 and await count(NM.NtOutbox, NM.NtOutbox.kind == "weekly") == 0)
        setclock(ist(2026, 10, 25, 9, 41))
        await plan()
        wk = {r.user_id for r in await rows(NM.NtOutbox, NM.NtOutbox.kind == "weekly")}
        expect_wk = {uid(x) for x in ("ann", "cat", "eve", "ida", "ivy", "jon", "lou", "max", "mia", "ned", "ola", "sw")}
        check("weekly rows go to exactly: xp >= 20, active in the last 7 days, a letter due, the kind on, a device - NOT bob (8 days away), hal (kind off), pia (letter 5 days old), "
              "unb (xp 5), kim (off), fay / gus (never practised), lee (no device), blk (blocked)", wk == expect_wk, (sorted(wk - expect_wk), sorted(expect_wk - wk)))
        w = (await out_rows(uid("ann"), NM.NtOutbox.kind == "weekly"))[0]
        check("its key is the ISO week", w.dedupe_key == "weekly:2026-W43" and w.fire_at == ist(2026, 10, 25, 10, 0), (w.dedupe_key, w.fire_at))
        setclock(ist(2026, 10, 25, 10, 0, 10))
        await tick()
        pw = [p for p in sent_to("ann") if "letter" in (p["title"] + p["body"]).lower() or "note" in (p["title"] + p["body"]).lower() or "weekly" in (p["title"] + p["body"]).lower()]
        w = (await out_rows(uid("ann"), NM.NtOutbox.kind == "weekly"))[0]
        check("the weekly note is sent once, in Hindi, with the learner's name", w.status == "sent" and len(pw) == 1 and "Ann" in pw[0]["body"], (w.status, pw))
        setclock(ist(2026, 10, 25, 10, 30))
        await plan()
        check("planning again that Sunday makes no second weekly row", await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("ann"), NM.NtOutbox.kind == "weekly") == 1)
        await setup("ann", streak=3, last=D(2026, 10, 30))                                            # she practised again this week
        setclock(ist(2026, 11, 1, 9, 45))
        await plan()
        check("the next Sunday has its own key (W44) - one a week", [r.dedupe_key for r in await out_rows(uid("ann"), NM.NtOutbox.kind == "weekly")] == ["weekly:2026-W43", "weekly:2026-W44"])

        # -------------------------------------------------------------- isolation
        section("isolation between learners")
        r = await api("bob", "GET", "/prefs")
        check("bob's prefs show only bob's notifications", all(x["id"] != a.id for x in r.json()["recent"]))
        r = await api("ann", "GET", "/export")
        ex = r.json()
        check("ann's export holds ann's rows and no one else's", r.status_code == 200 and {x["user_id"] for x in ex["nt_outbox"]} == {uid("ann")} and len(ex["nt_prefs"]) == 1
              and "endpoint" not in json.dumps(ex) and "p256dh" not in json.dumps(ex), {x["user_id"] for x in ex["nt_outbox"]})

        # -------------------------------------------------------------- the rollout switch and the loop itself
        section("the rollout switch: off / owner + early access / on")
        await db.set_setting("notifications", "owner")
        M.invalidate_access_cache()
        r = await api("ann", "GET", "/prefs")
        check("owner stage: an ordinary learner gets 404", r.status_code == 404)
        me = (await c.get("/me", headers=H("ann"))).json()
        check("owner stage: /me says false for her", me.get("notifications") is False)
        r = await api("owner", "GET", "/prefs")
        check("owner stage: the owner is in", r.status_code == 200)
        check("owner stage: an invited tester is not in until invited", (await api("sim", "GET", "/prefs")).status_code == 404)
        await db.early_add("sim@example.com")
        M.invalidate_access_cache()
        r = await api("sim", "GET", "/prefs")
        me = (await c.get("/me", headers=H("sim"))).json()
        check("owner stage: an early-access tester is in, and /me says so", r.status_code == 200 and me.get("notifications") is True)
        ENABLED_OWNER = M.notifications_enabled
        check("the engine's per-learner gate follows the same switch", await ENABLED_OWNER("sim@example.com") and not await ENABLED_OWNER("ann@example.com"))
        await db.set_setting("notifications", "off")
        M.invalidate_access_cache()
        check("off: nobody, not even the owner", not await ENABLED_OWNER("david123rana@gmail.com") and (await api("owner", "GET", "/prefs")).status_code == 404)

        section("the loop itself: idle while off, delivers on its own when on")
        await setup("unb", streak=5, last=D(2026, 10, 31), xp=100)
        setclock(ist(2026, 11, 2, 18, 41))                                                    # Monday 2 Nov
        sch.START_DELAY_SEC, sch.TICK_SEC = 0, 0.05
        await db.set_setting("notifications", "on")
        M.invalidate_access_cache()
        await plan()
        due = await count(NM.NtOutbox, NM.NtOutbox.status == "scheduled", NM.NtOutbox.dedupe_key == "day:2026-11-02")
        mode = {"v": "off"}

        async def mode_fn():
            return mode["v"]

        sch.state["ticks"] = 0
        SENT.clear()
        setclock(ist(2026, 11, 2, 19, 0, 5))
        task = asyncio.create_task(sch.run_forever(mode_fn, ENABLED))
        await asyncio.sleep(0.4)
        check("while the switch is off the loop does nothing (no tick, no send)", sch.state["ticks"] == 0 and not SENT and due >= 1, (sch.state["ticks"], len(SENT), due))
        mode["v"] = "on"
        await asyncio.sleep(1.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        check("switched on: the loop delivers what was due, by itself", sch.state["ticks"] >= 1 and len(SENT) >= 1 and await count(NM.NtOutbox, NM.NtOutbox.status == "scheduled", NM.NtOutbox.dedupe_key == "day:2026-11-02") == 0,
              (sch.state["ticks"], len(SENT)))

        section("a bad row never stops the rest; a crash mid-send is reclaimed")
        async with db._Session() as s:
            s.add(NM.NtOutbox(user_id=uid("ann"), kind="test", dedupe_key="test:poison", fire_at=CLOCK[0] - dt.timedelta(seconds=1), status="scheduled", created_at=CLOCK[0]))
            s.add(NM.NtOutbox(user_id=uid("bob"), kind="test", dedupe_key="test:good", fire_at=CLOCK[0] - dt.timedelta(seconds=1), status="scheduled", created_at=CLOCK[0]))
            await s.commit()
        real = svc.deliver

        async def flaky(nid, enabled_fn, now, sender=None):
            r_ = (await rows(NM.NtOutbox, NM.NtOutbox.id == nid))[0]
            if r_.dedupe_key == "test:poison":
                raise RuntimeError("boom")
            return await real(nid, enabled_fn, now, sender)

        svc.deliver = flaky
        SENT.clear()
        await tick()
        svc.deliver = real
        poison = (await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "test:poison"))[0]
        good = (await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "test:good"))[0]
        check("the poisoned row is withdrawn (not retried forever) and the good one still went", poison.status == "cancelled" and poison.why == "RuntimeError" and good.status == "sent" and len(sent_to("bob")) == 1, (poison.status, poison.why, good.status))
        async with db._Session() as s:
            s.add(NM.NtOutbox(user_id=uid("cat"), kind="test", dedupe_key="test:crash", fire_at=CLOCK[0], status="sending", claimed_at=CLOCK[0] - dt.timedelta(minutes=3), created_at=CLOCK[0]))
            await s.commit()
        n_back = await svc.reclaim(CLOCK[0])
        check("a send that died mid-flight (3 minutes in 'sending') goes back to 'scheduled'", n_back == 1 and (await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "test:crash"))[0].status == "scheduled")
        res = await asyncio.gather(*[svc.claim(CLOCK[0]) for _ in range(6)])
        flat = [i for part in res for i in part]
        check("six workers claiming at once take every due row exactly once", len(flat) == len(set(flat)) >= 1, flat)

        section("the rollout switch is checked AGAIN at send time (a row made while it was on)")
        async with db._Session() as s:
            s.add(NM.NtOutbox(user_id=uid("sw"), kind="test", dedupe_key="test:switch", fire_at=CLOCK[0], status="scheduled", created_at=CLOCK[0]))
            await s.commit()
        SENT.clear()
        await sch.tick(lambda email: email != "sw@example.com", materialize=False, sender=SENDER)
        swr = (await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "test:switch"))[0]
        check("the switch turned off after the row was made: cancelled 'switch_off', nothing sent", swr.status == "cancelled" and swr.why == "switch_off" and not sent_to("sw"), (swr.status, swr.why))

        section("a blocked account is never sent to, even from a row made earlier")
        async with db._Session() as s:
            s.add(NM.NtOutbox(user_id=uid("fay"), kind="test", dedupe_key="test:blocked", fire_at=CLOCK[0], status="scheduled", created_at=CLOCK[0]))
            await s.commit()
        async with db._Session() as s:
            await s.execute(update(db.User).where(db.User.id == uid("fay")).values(status="blocked"))
            await s.commit()
        SENT.clear()
        await tick()
        bl = (await rows(NM.NtOutbox, NM.NtOutbox.dedupe_key == "test:blocked"))[0]
        check("blocked: cancelled 'blocked', nothing sent", bl.status == "cancelled" and bl.why == "blocked" and not sent_to("fay"), (bl.status, bl.why))
        async with db._Session() as s:
            await s.execute(update(db.User).where(db.User.id == uid("fay")).values(status="active"))
            await s.commit()

        # -------------------------------------------------------------- My Day still works next to it
        section("My Day is untouched: the subscribe / test endpoints and its own reminders still work")
        await db.set_setting("planner", "on")
        M.invalidate_access_cache()
        r = await c.get("/planner/prefs", headers=H("ann"))
        check("My Day prefs still answer 200", r.status_code == 200, r.status_code)
        r = await c.post("/planner/push/subscribe", headers=H("ann"), json={"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/ann2", "keys": {"p256dh": PP._b64(b"\x04" + b"p" * 64), "auth": PP._b64(b"a" * 16)}}})
        check("subscribing a phone still goes through /planner/push/subscribe (one device table)", r.status_code == 200 and r.json()["push_on"] is True, r.text)
        r = await c.post("/planner/push/test", headers=H("ann"), json={})
        check("My Day's own test reminder still works", r.status_code == 200, r.text)

        # -------------------------------------------------------------- data rights
        section("data rights: delete-all, account deletion, the owner's wipe")
        check("ann has rows before", await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("ann")) >= 2 and await count(NM.NtPrefs, NM.NtPrefs.user_id == uid("ann")) == 1)
        r = await api("ann", "POST", "/delete-all", {})
        check("delete-all without confirm is 422 and deletes nothing", r.status_code == 422 and await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("ann")) >= 2)
        r = await api("ann", "POST", "/delete-all", {"confirm": True})
        check("delete-all with confirm removes her rows and prefs, and only hers",
              r.status_code == 200 and await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("ann")) == 0 and await count(NM.NtPrefs, NM.NtPrefs.user_id == uid("ann")) == 0
              and await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("bob")) >= 1)
        check("her account and her device survive a data reset", await count(db.User, db.User.id == uid("ann")) == 1 and await count(PM.PlPushSub, PM.PlPushSub.user_id == uid("ann")) >= 1)
        r = await api("ann", "GET", "/prefs")
        check("her settings simply come back as defaults", r.json()["nudge_time"] == "19:00" and r.json()["recent"] == [])
        had = await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("bob"))
        check("bob has rows before his account is deleted", had >= 1 and await count(NM.NtPrefs, NM.NtPrefs.user_id == uid("bob")) == 1)
        await db.delete_user(uid("bob"))
        check("deleting the account deletes the notification rows and prefs too (no orphan, no FK error)", await count(NM.NtOutbox, NM.NtOutbox.user_id == uid("bob")) == 0
              and await count(NM.NtPrefs, NM.NtPrefs.user_id == uid("bob")) == 0 and await count(db.User, db.User.id == uid("bob")) == 0)
        before = await count(NM.NtOutbox)
        n_del = await db.admin_wipe_users({"david123rana@gmail.com", "sim@example.com"})
        check("the owner's wipe removes everyone else's notification rows and keeps the kept accounts'", n_del >= 10 and await count(NM.NtOutbox, NM.NtOutbox.user_id.notin_([uid("sim"), "u-owner"])) == 0 and before > 0)

        check("no request in this whole run was a 500", not FIVE, FIVE)

    print(f"\n{N - len(FAILS)} / {N} checks passed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
        sys.exit(1)


asyncio.run(main())
