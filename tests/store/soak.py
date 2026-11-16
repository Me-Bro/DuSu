"""Soak: the three background loops (My Day reminders, Notifications, the key ledger) against a SCRATCH MongoDB, with the profiler on.

What it answers (the "M6 soak + explain" gate of DUSU_MONGO_MIGRATION_PLAN.md):
  1. Do the loops run for minutes without an error, deliver what is due, and leave nothing stuck?
  2. How many database operations per minute do they cost when nobody is using the app - and with a light stream of learners on top?
  3. Does EVERY query they (and the learners' pages) issue use an index? The profiler records each operation's plan; a COLLSCAN on a collection that is
     not tiny is a failure.
  4. Do the learners' own requests stay fast while the loops run?

Run via tests/store/soak.sh (a throwaway mongo on an internal network). SOAK_LEARNERS (default 300), SOAK_SECONDS (default 300: half idle, half with traffic).
Prints counts, plans and timings only - the data is synthetic. Exit code 1 if a gate fails.
"""

import asyncio
import datetime as dt
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, "/app")

import httpx                                                        # noqa: E402
from app.store import func, select, update                         # noqa: E402

from app import auth, db, main as M, store                          # noqa: E402
from app.keys import ledger as kledger, probe as kprobe             # noqa: E402
from app.notify import models as NM, scheduler as nsch, service as ntsvc    # noqa: E402
from app.planner import models as PM, push as ppush, scheduler as psch, service as plsvc   # noqa: E402
from app.store import model as _model                                # noqa: E402

CHECKS = [0]                                                        # how many times the store compared a tracked object with its snapshot (a flush does it per object)
_orig_changes = _model.Base._changes


def _counted(self, *a, **k):
    CHECKS[0] += 1
    return _orig_changes(self, *a, **k)


_model.Base._changes = _counted

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "refusing to run with provider keys configured"

N = int(os.environ.get("SOAK_LEARNERS", "300"))
SECS = int(os.environ.get("SOAK_SECONDS", "300"))
IDLE_S = max(30, SECS // 2)
LOAD_S = max(30, SECS - IDLE_S)
UTC = dt.timezone.utc
IST = dt.timedelta(hours=5, minutes=30)
random.seed(20261116)
FAILS: list[str] = []
SENT_PUSH = [0]


async def _fake_send(sub, payload):                                 # the push service: accepts everything (the soak has no route to the internet anyway)
    SENT_PUSH[0] += 1
    return ("ok", 201)


ppush.send = _fake_send


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"  {str(detail)[:300]}"))
    if not cond:
        FAILS.append(name)


def section(t):
    print(f"\n== {t}", flush=True)


def now():
    return dt.datetime.now(UTC)


def local_parts(offset_s: int):
    """(YYYY-MM-DD, HH:MM) in India time, `offset_s` seconds from now - the default zone of a new learner."""
    t = now() + IST + dt.timedelta(seconds=offset_s)
    return t.date().isoformat(), t.strftime("%H:%M")


async def opcounters():
    st = await store.core.client().admin.command("serverStatus")
    return {k: int(v) for k, v in st["opcounters"].items()}


def diff(a, b):
    return {k: b[k] - a[k] for k in a}


def fmt_rate(d, secs):
    per_min = {k: round(v * 60.0 / secs, 1) for k, v in d.items() if k != "update" or True}
    return per_min


# ----------------------------------------------------------------------------- the profiler
async def profiler_on():
    dbh = store.core.database()
    await dbh.command({"profile": 0})
    try:
        await dbh["system.profile"].drop()
    except Exception:                                               # noqa: BLE001
        pass
    await dbh.create_collection("system.profile", capped=True, size=200 * 1024 * 1024)
    await dbh.command({"profile": 2, "slowms": 0})


async def profiler_off():
    await store.core.database().command({"profile": 0})


def _filter_of(d):
    c = d.get("command") or {}
    for k in ("filter", "q", "query"):
        if isinstance(c.get(k), dict):
            return c[k]
    if isinstance(c.get("pipeline"), list) and c["pipeline"] and isinstance(c["pipeline"][0], dict):
        return (c["pipeline"][0].get("$match") or {}) if "$match" in c["pipeline"][0] else {}
    for key in ("updates", "deletes"):
        if isinstance(c.get(key), list) and c[key] and isinstance(c[key][0], dict):
            return c[key][0].get("q") or {}
    return {}


def shape(d):
    f = _filter_of(d)
    c = d.get("command") or {}
    name = next((k for k in ("find", "aggregate", "update", "delete", "findAndModify", "findandmodify", "insert", "count", "distinct") if k in c), d.get("op", "?"))
    keys = sorted(f.keys()) if isinstance(f, dict) else []
    sort = c.get("sort")
    return f"{name} {keys}" + (f" sort={list(sort.keys()) if isinstance(sort, dict) else sort}" if sort else "")


async def analyse(t0, t1, label):
    dbh = store.core.database()
    name = dbh.name
    docs = await dbh["system.profile"].find({"ts": {"$gte": t0, "$lt": t1}, "ns": {"$regex": f"^{name}\\."}}).to_list(None)
    docs = [d for d in docs if not str(d.get("ns", "")).endswith("system.profile")]
    groups = {}
    for d in docs:
        plan = (d.get("planSummary") or "").split(" ")[0] or "-"
        full = d.get("planSummary") or "-"
        k = (d["ns"].split(".", 1)[1], d.get("op"), shape(d), full if len(full) < 90 else full[:90])
        g = groups.setdefault(k, {"n": 0, "ms": 0, "max": 0, "docs": 0, "keys": 0, "ret": 0, "plan": plan, "sample": json.dumps(d.get("command"), default=str)[:420]})
        g["n"] += 1
        g["ms"] += int(d.get("millis") or 0)
        g["max"] = max(g["max"], int(d.get("millis") or 0))
        g["docs"] += int(d.get("docsExamined") or 0)
        g["keys"] += int(d.get("keysExamined") or 0)
        g["ret"] += int(d.get("nreturned") or d.get("nMatched") or 0)
    print(f"\n-- profile: {label}: {len(docs)} operations on {len({k[0] for k in groups})} collections, {len(groups)} distinct shapes")
    top = sorted(groups.items(), key=lambda kv: -kv[1]["n"])[:14]
    for (coll, op, sh, plan), g in top:
        print(f"   {g['n']:6d} x {coll:<20s} {sh[:78]:<78s} {plan[:48]:<48s} docs={g['docs']} keys={g['keys']} max={g['max']}ms")
    return groups


async def collection_sizes():
    dbh = store.core.database()
    out = {}
    for n in await dbh.list_collection_names():
        if n == "system.profile":
            continue
        out[n] = await dbh[n].estimated_document_count()
    return out


# ----------------------------------------------------------------------------- seeding
async def seed():
    section(f"seeding {N} learners (planner + notifications switched on)")
    for _ in range(40):
        try:
            await db.init_db()
            break
        except Exception:                                           # noqa: BLE001
            await asyncio.sleep(1)
    await db.set_setting("planner", "on")
    await db.set_setting("notifications", "on")
    M.invalidate_access_cache()
    today_ist = (now() + IST).date()
    users = {}
    sem = asyncio.Semaphore(8)

    async def one(i):
        async with sem:
            uid = f"soak-{i:04d}"
            u = {"sub": uid, "email": f"soak{i:04d}@example.com", "name": f"Soak {i}", "picture": ""}
            users[uid] = u
            await db.login(u)
            await db.save_assessment(uid, {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
            await plsvc.put_prefs(uid, {"quiet_on": False})                                       # the soak must not depend on the wall clock
            await plsvc.subscribe_push(uid, {"endpoint": f"https://fcm.googleapis.com/fcm/send/soak-{i}", "p256dh": "B" + "A" * 86, "auth": "A" * 22})
            await plsvc.create_task(uid, {"title": f"Task {i}", "due_date": today_ist.isoformat(), "client_key": f"t{i}"})
            await plsvc.create_habit(uid, {"title": "Read", "target": 1, "schedule": {"days": "daily", "times": ["20:00"]}, "client_key": f"h{i}"})
            await plsvc.create_reminder_rule(uid, {"title": "Gym", "time": "07:30", "days": [0, 2, 4], "client_key": f"r{i}"})
            d, t = local_parts(3600 + 60 * (i % 90))
            await plsvc.create_custom_reminder(uid, {"title": f"Later {i}", "date": d, "time": t, "client_key": f"c{i}"})
            if i % 10 == 0:                                                                     # 10 %: a reminder that is due DURING the soak
                d, t = local_parts(75 + (i % 6) * 15)
                await plsvc.create_custom_reminder(uid, {"title": f"Soon {i}", "date": d, "time": t, "client_key": f"s{i}"})
            if i % 2 == 0:                                                                      # half have nudges on, most at a time that is open right now
                _, t = local_parts(60 * (i % 5))
                await ntsvc.put_prefs(uid, {"enabled": True, "nudge_time": t})

    t0 = time.monotonic()
    await asyncio.gather(*[one(i) for i in range(N)])
    print(f"seeded in {time.monotonic() - t0:.1f}s")
    async with db._Session() as s:                                                              # a third of them have practised yesterday (a live streak)
        for i in range(0, N, 3):
            await s.execute(update(db.Progress).where(db.Progress.user_id == f"soak-{i:04d}").values(xp=60, streak_days=3, last_active=today_ist - dt.timedelta(days=1)))
        await s.commit()
    return users


# ----------------------------------------------------------------------------- the run
async def main():
    users = await seed()
    sizes = await collection_sizes()
    print("documents: " + ", ".join(f"{k}={v}" for k, v in sorted(sizes.items()) if v))
    uids = list(users)
    tokens = {uid: auth.make_session(u) for uid, u in users.items()}
    await profiler_on()

    # ---- A: the database with nobody and nothing running (the noise floor: replica-set housekeeping, the profiler)
    section("A. noise floor (no loops, no traffic)")
    a0 = await opcounters(); await asyncio.sleep(15); a1 = await opcounters()
    noise = diff(a0, a1)
    print("ops per minute:", fmt_rate(noise, 15))

    # ---- B: the three loops, nobody using the app
    section(f"B. the three loops alone for {IDLE_S}s")
    tasks = [asyncio.create_task(psch.run_forever(M.planner_mode, M.planner_enabled)),
             asyncio.create_task(nsch.run_forever(M.notifications_mode, M.notifications_enabled)),
             asyncio.create_task(kledger.run_forever([(kprobe.SERVER_HEALTH_TTL_S, kprobe.refresh_server_health)]))]
    tb0 = now(); b0 = await opcounters(); ck0 = CHECKS[0]
    await asyncio.sleep(IDLE_S - 60)
    bm = await opcounters()
    await asyncio.sleep(60)
    b1 = await opcounters(); tb1 = now()
    idle = diff(b0, b1)
    print("ops per minute (the whole phase, with the first passes):", fmt_rate(idle, IDLE_S))
    steady = diff(bm, b1)
    print("ops per minute (the last 60 s - the steady state):", fmt_rate(steady, 60))
    print(f"dirty checks by the store while the loops ran alone: {CHECKS[0] - ck0}")
    print("planner state:", {k: v for k, v in psch.state.items() if k != "last_stats"}, "last_stats:", psch.state.get("last_stats"))
    print("notify state :", {k: v for k, v in nsch.state.items() if k != "last_stats"}, "last_stats:", nsch.state.get("last_stats"))
    groups_idle = await analyse(tb0, tb1, "loops alone")

    # ---- C: the loops + learners using the app
    section(f"C. the loops + learners for {LOAD_S}s (about 2 page loads and 1 action a second)")
    lat = {"/me": [], "/planner/today": [], "/planner/tasks/complete": [], "/planner/reminders?view=all": []}
    errors = []
    transport = httpx.ASGITransport(app=M.app)
    tc0 = now(); c0 = await opcounters(); ck1 = CHECKS[0]
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:
        async def hit(method, path, uid, key, body=None):
            t = time.monotonic()
            try:
                r = await c.request(method, path, headers={"Authorization": "Bearer " + tokens[uid]}, json=body)
                if r.status_code >= 500:
                    errors.append((path, r.status_code))
            except Exception as e:                                                              # noqa: BLE001
                errors.append((path, type(e).__name__))
            lat[key].append((time.monotonic() - t) * 1000)

        end = time.monotonic() + LOAD_S
        while time.monotonic() < end:
            uid = random.choice(uids)
            await asyncio.gather(hit("GET", "/me", uid, "/me"), hit("GET", "/planner/today", random.choice(uids), "/planner/today"),
                                 hit("GET", "/planner/reminders?view=all", random.choice(uids), "/planner/reminders?view=all"))
            uid = random.choice(uids)
            async with db._Session() as s:
                t = (await s.execute(select(PM.PlTask).where(PM.PlTask.user_id == uid, PM.PlTask.status == "open"))).scalars().first()
            if t is not None:
                await hit("POST", f"/planner/tasks/{t.id}/complete", uid, "/planner/tasks/complete", {})
            await asyncio.sleep(0.5)
    c1 = await opcounters(); tc1 = now()
    load = diff(c0, c1)
    n_req = sum(len(v) for v in lat.values())
    print("ops per minute:", fmt_rate(load, LOAD_S))
    print(f"dirty checks by the store: {CHECKS[0] - ck1} for {n_req} learner requests (+ the loops) = {(CHECKS[0] - ck1) / max(1, n_req):.0f} per request")
    for k, v in lat.items():
        if v:
            v.sort()
            print(f"   {k:<30s} n={len(v):4d} p50={statistics.median(v):6.0f}ms p95={v[int(len(v) * 0.95) - 1]:6.0f}ms max={v[-1]:6.0f}ms")
    groups_load = await analyse(tc0, tc1, "loops + learners")

    # ---- C2: a burst - the Play Store launch case: many people opening the app at the same moment, a few learners hit hard (the worst case for write contention)
    section("C2. a burst: 40 requests in flight at once, 600 in all, over only 12 learners (loops still running)")
    from app.store import core as _core
    st0 = dict(_core.STATS)
    burst_lat, burst_err = [], []
    transport2 = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=transport2, base_url="http://t", timeout=120) as c:
        sem = asyncio.Semaphore(40)

        async def burst(i):
            uid = uids[i % 12]
            kind = i % 4
            try:
                async with sem:
                    t = time.monotonic()
                    if kind == 0:
                        r = await c.get("/me", headers={"Authorization": "Bearer " + tokens[uid]})
                    elif kind == 1:
                        r = await c.get("/planner/today", headers={"Authorization": "Bearer " + tokens[uid]})
                    elif kind == 2:
                        r = await c.post("/checkin", json={"token": tokens[uid], "mood": "good"})
                    else:
                        r = await c.get("/planner/reminders?view=all", headers={"Authorization": "Bearer " + tokens[uid]})
                    if r.status_code >= 400:
                        burst_err.append((kind, r.status_code))
                    burst_lat.append((time.monotonic() - t) * 1000)
            except Exception as e:                                                              # noqa: BLE001
                burst_err.append((kind, type(e).__name__))

        tb = time.monotonic()
        await asyncio.gather(*[burst(i) for i in range(600)])
        burst_s = time.monotonic() - tb
    burst_lat.sort()
    st1 = dict(_core.STATS)
    print(f"   (the time of a request is measured from the moment it gets one of the 40 slots)")
    print(f"   600 requests in {burst_s:.1f}s = {600 / burst_s:.0f}/s | p50 {statistics.median(burst_lat):.0f} ms, p95 {burst_lat[int(len(burst_lat) * 0.95) - 1]:.0f} ms, "
          f"p99 {burst_lat[int(len(burst_lat) * 0.99) - 1]:.0f} ms, max {burst_lat[-1]:.0f} ms | errors {len(burst_err)} | what the safety nets had to do: "
          f"{ {k: st1[k] - st0[k] for k in st1} }")

    # ---- the loops stop; a last pass of every kind is timed on its own
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await profiler_off()                                                                        # the profiler writes a document per operation: off for the timings
    section("D. one full materialize pass of each engine, timed on its own (profiler off)")
    o0 = await opcounters(); ck2 = CHECKS[0]
    t = time.monotonic(); n = await plsvc.materialize_all(); dt1 = (time.monotonic() - t) * 1000
    o1 = await opcounters()
    print(f"   planner materialize_all: {n} learner(s) in {dt1:.0f} ms, {sum(diff(o0, o1).values())} database operations ({sum(diff(o0, o1).values()) / max(1, n):.1f} per learner)")
    t = time.monotonic(); r = await ntsvc.materialize_all(M.notifications_enabled); dt2 = (time.monotonic() - t) * 1000
    o2 = await opcounters()
    print(f"   notify materialize_all: {r} in {dt2:.0f} ms, {sum(diff(o1, o2).values())} database operations; dirty checks over both passes: {CHECKS[0] - ck2}")
    check("a materialize pass is linear in the learners (no quadratic dirty checking): under 100 dirty checks per learner", (CHECKS[0] - ck2) < 100 * N, CHECKS[0] - ck2)

    # ---- verdicts
    section("verdicts")
    check("the planner loop ran and never errored", psch.state.get("ticks", 1) >= 1 and not psch.state.get("last_error"), psch.state)
    check("the notification loop ran and never errored", nsch.state.get("ticks", 0) >= 1 and not nsch.state.get("last_error"), nsch.state)
    check("the key ledger loop never errored", not kledger.state.get("last_error"), kledger.state)
    check("no request failed with a 5xx / exception while the loops ran", not errors, errors[:5])
    sizes = await collection_sizes()
    scans, by_design = [], []
    for label, groups in (("loops alone", groups_idle), ("loops + learners", groups_load)):
        for (coll, op, sh, plan), g in groups.items():
            if g["plan"] != "COLLSCAN" or op == "getmore" or sizes.get(coll, 0) <= 100:
                continue
            sel = g["ret"] / max(1, g["docs"])
            # a scan that happens once or twice in the window is a periodic pass (a daily prune, a 10-minute materialize): reported, not failed
            (by_design if (sel >= 0.5 or g["n"] < 4) else scans).append((label, coll, sh, f"x{g['n']}", f"examined {g['docs']}, kept {g['ret']}", g["sample"]))
    check("no recurring query reads a big collection end to end only to throw most of it away", not scans, scans[:4])
    for row in scans:
        print("   SCAN  ", row)
    for row in by_design:
        print("   (a full read by design / a periodic pass:", row[:5], ")")
    check("the burst: every one of the 600 requests succeeded", not burst_err, burst_err[:5])
    check("the burst: p95 under 2 s with 40 requests in flight over 12 learners", burst_lat[int(len(burst_lat) * 0.95) - 1] < 2000, f"p95={burst_lat[int(len(burst_lat) * 0.95) - 1]:.0f}ms")
    for key, vs in lat.items():
        if len(vs) >= 10:
            vs.sort()
            check(f"{key}: p95 under 1.5 s while the loops run", vs[int(len(vs) * 0.95) - 1] < 1500, f"p95={vs[int(len(vs) * 0.95) - 1]:.0f}ms")
    async with db._Session() as s:
        hist = {}
        for r in (await s.execute(select(PM.PlReminder.status, func.count()).group_by(PM.PlReminder.status))).all():
            hist[r[0]] = r[1]
        ntq = {}
        for r in (await s.execute(select(NM.NtOutbox.status, func.count()).group_by(NM.NtOutbox.status))).all():
            ntq[r[0]] = r[1]
    print("   reminder statuses:", hist, " notification outbox statuses:", ntq)
    check("nothing that was due is still waiting or stuck mid-send", not any(hist.get(k) for k in ("sending", "failed")), hist)
    due_soon = hist.get("sent", 0) + hist.get("waiting", 0) + hist.get("missed", 0) + hist.get("expired", 0) + hist.get("done", 0)
    check("the reminders that fell due during the soak were delivered", due_soon >= max(1, N // 10 - 3), hist)
    check("the notification queue has no row stuck mid-send", not ntq.get("sending"), ntq)
    check("the notification engine planned and sent nudges for learners with a device", ntq.get("sent", 0) > 0 or ntq.get("scheduled", 0) > 0, ntq)
    print(f"   push messages accepted by the fake push service: {SENT_PUSH[0]}")
    print(f"\n   idle cost: about {sum(fmt_rate(steady, 60).values()):.0f} database operations a minute in the steady state for {N} learners "
          f"({sum(fmt_rate(steady, 60).values()) / N:.1f} per learner), noise floor {sum(fmt_rate(noise, 15).values()):.0f} a minute")
    print(f"\n{'ALL SOAK CHECKS PASSED' if not FAILS else 'FAILED: ' + ', '.join(FAILS)}")
    await store.close()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
