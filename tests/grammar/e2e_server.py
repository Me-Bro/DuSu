"""Grammar Coach - the REAL app (uvicorn + a scratch Postgres) with STUB models, for a REAL browser to talk to.

Seeds learners, switches Grammar Coach ON, replaces the chat and grammar models with deterministic stubs, writes the session tokens for the browser spec to
`/tests/grammar/.e2e/tokens.json` (git-ignored) and serves on :8000. Adds two test-only routes: /__e2e/stats (calls per stub) and /__e2e/seed (analyse
a scripted session for a learner, as the detached task would). Started by browser/run_real.sh - never run against production."""

import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/grammar")

import uvicorn                                                      # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.grammar import tracker                                     # noqa: E402
from app.interview import engine as ienv                            # noqa: E402
from chat_stub import ChatStub                                      # noqa: E402
from stub_llm import StubLLM                                        # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys must be blank (run through run_real.sh)"

NAMES = ["ann", "bob", "cat", "dan"]
TALK = ["yesterday i go to the market and i buy some vegetable", "i am engineer in a software company in pune",
        "we should discuss about the project tomorrow morning with the team", "my favourite food is dal and rice with some pickle",
        "he go to office every day by metro train", "informations about the new course were very useful for all of us"]
CHAT, GC = ChatStub(), StubLLM()
tracker.llm = GC
M.llm = CHAT
ienv.llm = CHAT


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
    await db.set_setting("grammar_coach", "on")
    await db.set_setting("practice_room", "on")
    M.invalidate_access_cache()
    # ann already has two finished sessions (so the hub has history) - analysed through the real pipeline with the stub model
    for i in (1, 2):
        await tracker.run("e2e-ann", "ann@example.com", source="talk", kind="", key=f"ws:seedann{i:06d}", turns=[{"turn": k + 1, "text": t, "conf": None} for k, t in enumerate(TALK)], engine_src="chrome")
    os.makedirs("/tests/grammar/.e2e", exist_ok=True)
    json.dump({k: {"token": auth.make_session(u), "user": u} for k, u in users.items()}, open("/tests/grammar/.e2e/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


@M.app.get("/__e2e/stats")
async def _stats():
    return {"gc_calls": dict(GC.calls), "chat_calls": len(CHAT.log)}


@M.app.post("/__e2e/seed")
async def _seed(body: dict):
    out = await tracker.run(body["uid"], body["email"], source=body.get("source", "talk"), kind="", key=body["key"],
                            turns=[{"turn": k + 1, "text": t, "conf": None} for k, t in enumerate(body.get("texts") or TALK)], engine_src="chrome")
    return {"out": out}


# routes added now sit AFTER the app's SPA catch-all, which would answer them with HTML - move them to the front
for _r in [r for r in M.app.router.routes if getattr(r, 'path', '').startswith('/__e2e/')]:
    M.app.router.routes.remove(_r)
    M.app.router.routes.insert(0, _r)

asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
