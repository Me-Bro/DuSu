"""Resume Interview - tier 4b: the REAL app (uvicorn + scratch Postgres) with the stub model, for a REAL browser to talk to.

Seeds a learner and the owner, switches the feature ON, patches speech-to-text for the server-proxy path, writes the session tokens for the browser spec to
`/tests/resume_interview/.e2e/tokens.json` (git-ignored) and serves on :8000. Started by browser/run_real.sh - never run against production.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/resume_interview")

import uvicorn                                                      # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.resume_interview import api as ri_api                      # noqa: E402
from stub_llm import StubLLM                                        # noqa: E402
from unit_fixtures import ANSWER_GOOD, ANSWER_WEAK, JD, RESUME          # noqa: E402

assert not (M.settings.groq_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys must be blank (run through run_real.sh)"

STUB = StubLLM()
STUB.delay = float(os.environ.get("E2E_MODEL_DELAY", "0.4"))        # a little latency so loaders and "still working" states are real
ri_api.llm = STUB


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {"owner": {"sub": "e2e-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""},
             "ann": {"sub": "e2e-ann", "email": "ann@example.com", "name": "Ann Learner", "picture": ""},
             "bob": {"sub": "e2e-bob", "email": "bob@example.com", "name": "Bob Learner", "picture": ""},
             "cat": {"sub": "e2e-cat", "email": "cat@example.com", "name": "Cat Learner", "picture": ""},
             "dan": {"sub": "e2e-dan", "email": "dan@example.com", "name": "Dan Learner", "picture": ""}}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    await db.set_setting("resume_interview", "on")
    M.invalidate_access_cache()
    out = {k: {"token": auth.make_session(u), "user": u} for k, u in users.items()}
    out["fixtures"] = {"RESUME": RESUME, "RESUME2": RESUME.replace("Customer churn analysis", "Loaded data into Snowflake for the finance team.\nCustomer churn analysis"),
                       "JD": JD, "ANSWER_GOOD": ANSWER_GOOD, "ANSWER_WEAK": ANSWER_WEAK}
    os.makedirs("/tests/resume_interview/.e2e", exist_ok=True)
    json.dump(out, open("/tests/resume_interview/.e2e/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


asyncio.run(seed())
M.settings.gemini_api_key = "stub"                                   # the server-proxy speech-to-text path (learners without a Groq key of their own)


async def fake_gemini(data, mime, lang, key):
    return {"text": ANSWER_GOOD, "duration": 33.0, "words": [], "segments": [], "engine": "gemini"}


M._gemini_transcribe = fake_gemini


from fastapi import APIRouter                                         # noqa: E402

_r = APIRouter()


@_r.get("/__e2e/stats")                                              # the spec reads the stub's call counters through this
async def e2e_stats():
    return dict(STUB.n)


@_r.post("/__e2e/fail")                                              # ...and can make a stage fail (clear=true restores it)
async def e2e_fail(stage: str = "", clear: bool = False):
    if clear:
        STUB.fail.clear()
    elif stage:
        STUB.fail[stage] = RuntimeError("provider returned an unreadable reply")
    return {"ok": True}


@_r.post("/__e2e/reset")
async def e2e_reset():
    STUB.n.clear()
    STUB.fail.clear()
    return {"ok": True}


_before = len(M.app.router.routes)
M.app.include_router(_r)
_new = M.app.router.routes[_before:]
for _x in _new:
    M.app.router.routes.remove(_x)
M.app.router.routes[0:0] = _new                                      # before the SPA fallback, which would otherwise answer these GETs with the app shell

uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
