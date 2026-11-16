"""Shadow comparison: the SAME read-only questions, asked of whichever tree is mounted at /app, for EVERY learner in the database it points at.

Run it on the OLD tree against a restored Postgres dump, and on the NEW tree against the migrated Mongo: if the migration lost, moved or reshaped anything a learner can see,
an answer differs. Nothing here writes on purpose (a GET can touch `last_seen`; each side has its own copy of the data, and the clock is frozen so both write the same).

  SHADOW_OUT=<file>   where the answers go (JSON)      SHADOW_NOW=<iso>   the frozen "now" (default 2026-11-16T12:00:00+00:00)
Prints counts only - never an answer. Needs the app's own env (SESSION_SECRET etc.); every provider key must be blank.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import types

sys.path.insert(0, "/app")

import httpx                                                                 # noqa: E402

from app import auth, db, main as M                                           # noqa: E402
from app.planner import timeutil as tu                                        # noqa: E402

OUT = os.environ["SHADOW_OUT"]
UTC = datetime.timezone.utc
CLOCK = [datetime.datetime.fromisoformat(os.environ.get("SHADOW_NOW", "2026-11-16T12:00:00+00:00"))]
assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "refusing to run with provider keys configured"


class FakeDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        c = CLOCK[0]
        return c.astimezone(tz) if tz is not None else c.replace(tzinfo=None)


_shim = types.SimpleNamespace(**{k: getattr(datetime, k) for k in ("date", "time", "timedelta", "timezone", "tzinfo", "UTC", "MINYEAR", "MAXYEAR") if hasattr(datetime, k)})
_shim.datetime = FakeDT
db.dt = _shim
tu.now_utc = lambda: CLOCK[0]
try:
    from app.resume_interview import service as _ri
    _ri._utc = lambda: CLOCK[0]
except Exception:                                                            # noqa: BLE001
    pass

GETS = ["/me", "/leaderboard", "/league", "/missions", "/season-awards", "/confidence-check/history", "/interview/reports", "/home/features?lang=hi", "/practice/history",
        "/planner/today", "/planner/summary", "/planner/tasks?view=all", "/planner/goals", "/planner/habits", "/planner/due", "/planner/reminders?view=all",
        "/planner/reminder-rules", "/planner/prefs", "/planner/export", "/notify/prefs", "/notify/export", "/keys/export",
        "/gcoach/state", "/gcoach/sessions", "/gcoach/rules", "/gcoach/notebook", "/gcoach/prefs", "/gcoach/export",
        "/rinterview/state", "/rinterview/sessions", "/rinterview/export"]
OWNER_GETS = ["/admin/overview", "/admin/funnel"]
_TS = re.compile(r"(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?=[+-]\d{2}:\d{2}|Z)")      # a time of day with an optional fraction, followed by a UTC offset


def canon(path, body):
    """Orders that SQL leaves undefined (ties on XP, the rows of an export) are put in one canonical order, so a difference means a difference in DATA."""
    if path.startswith("/leaderboard") and isinstance(body, dict) and isinstance(body.get("top"), list):
        top = [{k: v for k, v in r.items() if k != "rank"} for r in body["top"]]
        top.sort(key=lambda r: (-(r.get("xp") or 0), json.dumps(r, sort_keys=True)))
        body = {**body, "top": top}
    if path.endswith("/export") and isinstance(body, dict):
        body = {k: (sorted(v, key=lambda r: json.dumps(r, sort_keys=True, default=str)) if isinstance(v, list) else v) for k, v in body.items()}
    return body


def norm(v):
    """JSON-ish normaliser: floats rounded, timestamps cut to milliseconds (the new store keeps milliseconds - an intended, documented difference)."""
    if isinstance(v, dict):
        return {k: norm(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str):
        return _TS.sub(lambda m: m.group(1) + "." + (m.group(2) or "")[:3].ljust(3, "0"), v)       # always exactly milliseconds (Python prints no fraction at all when it is zero)
    return v


async def main():
    await db.init_db()
    async with db._Session() as s:
        users = [(u.id, u.email or "", u.name or "") for u in (await s.execute(db.select(db.User).order_by(db.User.id))).scalars().all()]
    out, statuses = {}, {}
    transport = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:
        for uid, email, name in users:
            CLOCK[0] += datetime.timedelta(seconds=1)                        # a distinct last_seen per learner (a frozen clock would tie them all)
            tok = auth.make_session({"sub": uid, "email": email, "name": name})
            hdr = {"Authorization": "Bearer " + tok}
            paths = GETS + (OWNER_GETS if M.role_for(email) == "owner" else [])
            for p in paths:
                try:
                    r = await c.get(p, headers=hdr)
                    try:
                        body = r.json()
                    except Exception:                                        # noqa: BLE001
                        body = {"_text_len": len(r.text)}
                    out[f"{uid} {p}"] = {"status": r.status_code, "body": canon(p, norm(body))}
                    statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                except Exception as e:                                       # noqa: BLE001
                    out[f"{uid} {p}"] = {"EXC": type(e).__name__}
                    statuses["exc"] = statuses.get("exc", 0) + 1
    json.dump({"users": [u[0] for u in users], "answers": out}, open(OUT, "w"), sort_keys=True, default=str)
    print(f"{len(users)} learner(s), {len(out)} answers, status codes {dict(sorted(statuses.items(), key=lambda x: str(x[0])))}")


asyncio.run(main())
