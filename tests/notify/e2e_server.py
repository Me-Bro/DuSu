"""Notifications - the REAL app (uvicorn + a scratch Postgres, the real delivery loop running) for a REAL browser to talk to.

Seeds learners, switches Notifications and the Hindi / English choice ON, writes the session tokens for the browser spec to `/tests/notify/.e2e/tokens.json`
(git-ignored) and serves on :8000. Started by browser/run_real.sh - never run against production.
"""

import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "/app")

import uvicorn                                                      # noqa: E402
from sqlalchemy import update                                       # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.notify import models as NM                                 # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
    "provider keys must be blank (run through run_real.sh)"

# who has practised (xp > 0 -> the Home prompt may show) and who has not
PRACTISED = ["ann", "cat", "dan", "eve", "fay", "gus", "hal", "ivy"]
NAMES = PRACTISED + ["bob"]


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {n: {"sub": f"e2e-{n}", "email": f"{n}@example.com", "name": f"{n.title()} Learner", "picture": ""} for n in NAMES}
    users["owner"] = {"sub": "e2e-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()
    async with db._Session() as s:
        for n in PRACTISED:
            await s.execute(update(db.Progress).where(db.Progress.user_id == f"e2e-{n}").values(xp=40, streak_days=3, last_active=today - dt.timedelta(days=1)))
        await s.commit()
    await db.set_setting("notifications", "on")
    await db.set_setting("bilingual", "on")
    await db.set_setting("planner", "on")
    M.invalidate_access_cache()
    # one delivered nudge for fay, so the spec can open the app the way a notification tap does (/?n=<id>)
    async with db._Session() as s:
        r = NM.NtOutbox(user_id="e2e-fay", kind="practice", dedupe_key="day:seed", fire_at=dt.datetime.now(dt.timezone.utc), title="DuSu", body="seed", status="sent",
                        push_state="accepted", sent_at=dt.datetime.now(dt.timezone.utc))
        s.add(r)
        await s.commit()
        fay_row = r.id
    os.makedirs("/tests/notify/.e2e", exist_ok=True)
    out = {k: {"token": auth.make_session(u), "user": u} for k, u in users.items()}
    out["_rows"] = {"fay": fay_row}
    json.dump(out, open("/tests/notify/.e2e/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
