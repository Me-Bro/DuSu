"""Where does a materialize pass spend its time? Seeds learners (like the soak), then profiles ONE notify pass and ONE planner pass with cProfile: time inside the event loop's
select (= waiting for MongoDB) vs Python functions (CPU). Prints the top entries only. Run: tests/store/prof_materialize.sh"""
import asyncio
import cProfile
import datetime as dt
import io
import os
import pstats
import sys
import time

sys.path.insert(0, "/app")

from app import db, main as M, store                                # noqa: E402
from app.notify import service as ntsvc                              # noqa: E402
from app.planner import push as ppush, service as plsvc              # noqa: E402

N = int(os.environ.get("PROF_LEARNERS", "150"))
IST = dt.timedelta(hours=5, minutes=30)


async def main():
    await db.init_db()
    await db.set_setting("planner", "on"); await db.set_setting("notifications", "on"); M.invalidate_access_cache()
    now = dt.datetime.now(dt.timezone.utc)
    sem = asyncio.Semaphore(8)

    async def one(i):
        async with sem:
            uid = f"pf-{i:04d}"
            await db.login({"sub": uid, "email": f"pf{i}@example.com", "name": f"P {i}", "picture": ""})
            await db.save_assessment(uid, {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
            await plsvc.put_prefs(uid, {"quiet_on": False})
            await plsvc.subscribe_push(uid, {"endpoint": f"https://fcm.googleapis.com/fcm/send/pf-{i}", "p256dh": "B" + "A" * 86, "auth": "A" * 22})
            t = (now + IST).strftime("%H:%M")
            await ntsvc.put_prefs(uid, {"enabled": True, "nudge_time": t})
    await asyncio.gather(*[one(i) for i in range(N)])
    for name, fn in (("notify.materialize_all (first pass: creates the rows)", lambda: ntsvc.materialize_all(M.notifications_enabled)),
                     ("notify.materialize_all (second pass: every row already exists)", lambda: ntsvc.materialize_all(M.notifications_enabled)),
                     ("planner.materialize_all", lambda: plsvc.materialize_all())):
        pr = cProfile.Profile()
        t = time.monotonic()
        pr.enable()
        r = await fn()
        pr.disable()
        el = (time.monotonic() - t) * 1000
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("tottime")
        ps.print_stats(9)
        wait = sum(v[2] for k, v in pr.getstats().__class__ and [] ) if False else 0
        print(f"\n=== {name}: {el:.0f} ms for {N} learners -> {r}")
        lines = s.getvalue().splitlines()
        for ln in lines[:24]:
            if ln.strip():
                print("   " + ln[:150])
    await store.close()


asyncio.run(main())
