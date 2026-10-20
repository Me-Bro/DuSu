"""My Day - the REAL app (uvicorn + a scratch Postgres, the real reminder loop running on the real clock) for a REAL browser to talk to.

Seeds learners, switches My Day and the Hindi / English choice ON, writes the session tokens for the browser spec to `/tests/my_day/.e2e/tokens.json`
(git-ignored) and serves on :8000. Started by browser/run_real.sh - never run against production.
"""

import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "/app")

import uvicorn                                                      # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.planner import models as PM                                # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
    "provider keys must be blank (run through run_real.sh)"

NAMES = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal"]


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {n: {"sub": f"e2e-{n}", "email": f"{n}@example.com", "name": f"{n.title()} Learner", "picture": ""} for n in NAMES}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    await db.set_setting("planner", "on")
    await db.set_setting("bilingual", "on")
    M.invalidate_access_cache()
    # things ticked off DAYS ago (History, the Done chip): a learner must still be able to untick them, though they are no longer on the lists of the last two days
    now = dt.datetime.now(dt.timezone.utc)
    async with db._Session() as s:
        s.add(PM.PlReminder(user_id="e2e-hal", entity_type="custom", kind="time", title="Old ticked reminder", occurrence_key="seed-old-done-1", fire_at=now - dt.timedelta(days=4),
                            status="done", action="done", acted_at=now - dt.timedelta(days=4, minutes=-1), sent_at=now - dt.timedelta(days=4), tz="Asia/Kolkata", meta={}))
        s.add(PM.PlTask(user_id="e2e-hal", title="Old finished task", status="done", completed_at=now - dt.timedelta(days=5), tz="Asia/Kolkata"))
        await s.commit()
    os.makedirs("/tests/my_day/.e2e", exist_ok=True)
    json.dump({k: {"token": auth.make_session(u), "user": u} for k, u in users.items()}, open("/tests/my_day/.e2e/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
