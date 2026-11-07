"""Insights - tier 2b: the two hooks that live in the REAL /ws/interview handler (uvicorn in-process, auth ON) with a scripted provider world (tests/keys/world.py).

What is proven:
  * the first spoken sentence of ANY chat records `first_sentence` (Daily Talk, Face-to-Face, Learn) - once, whatever happens next;
  * `first_session` is recorded only when a session that had at least one real turn is finished and saved - not by opening a chat, not by a session with no turn, and
    not by Learn (a translator that is never saved);
  * a second session never duplicates either row; a different learner's rows are untouched;
  * with the kill switch off nothing is recorded; a failing database never breaks the chat.
Run via tests/insights/run.sh ws_selftest.py.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402
from sqlalchemy import select                                        # noqa: E402

from world import World, install, ok                                 # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.insights import models as IM, service as svc                # noqa: E402

FAILS: list = []
N = 0
PORT = 8767


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:500]}")


def section(t):
    print(f"\n== {t}")


JSON_REPLY = json.dumps({"reply": "Hello there", "intent": "general_conversation", "suggest": [], "english": "I went to the market", "reply_hindi": "Bahut accha",
                         "next_question_hindi": "Aur batao?", "tip": "", "mood": "ok", "context": {}, "summary": "They chatted.", "facts": {}, "events": [],
                         "no_hindi": False, "asked_question": False, "next_hook": "", "overall": 70, "categories": [], "genuine_effort": True})


def reply(messages, provider, key):
    wants_json = bool(messages) and str(messages[-1].get("content", "")).endswith("Return ONLY the JSON object.")
    return ok(JSON_REPLY if wants_json else "Nice to meet you. Tell me more about that?")


WORLD = World()
WORLD.chat_reply = reply
install(WORLD)

TALK = "i am a software engineer and i like my work in pune"
FIRST = {"conversation": {"ai_text", "error", "quota", "keys_required"}, "daily": {"daily_question", "error", "quota", "keys_required"}, "learning": {"ready", "error", "quota", "keys_required"}}
REPLY = {"conversation": {"ai_text", "error", "quota"}, "daily": {"daily_turn", "translate_error", "quota", "error"}, "learning": {"translation", "translate_error", "quota", "error"}}


async def ms(uid):
    async with db._Session() as s:
        return sorted(r.name for r in (await s.execute(select(IM.EvMilestone).where(IM.EvMilestone.user_id == uid))).scalars().all())


async def session(token, mode, *, turns=1, end=True, hold=0.0, blank=False):
    """One scripted session over a real websocket. `end` = the learner taps End (otherwise the socket is simply closed, as a dropped phone would)."""
    async def until(ws, kinds, timeout=30):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if m.get("type") in kinds:
                return m
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        await ws.send(json.dumps({"type": "start", "mode": mode, "token": token, "name": "Ann", "role": "developer", "hour": 11}))
        first = await until(ws, FIRST[mode])
        if first["type"] in ("keys_required", "error", "quota"):
            return first["type"]
        if blank:                                                    # an empty / whitespace line is not a sentence: the server ignores it
            await ws.send(json.dumps({"type": "user_text", "text": "   "}))
            await asyncio.sleep(0.3)
        for _ in range(turns):
            await ws.send(json.dumps({"type": "user_text", "text": TALK}))
            await until(ws, REPLY[mode])
        if hold:
            await asyncio.sleep(hold)
        if end:
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, {"ended", "error"}, 60)
    await asyncio.sleep(0.5)
    for _ in range(40):                                              # the fire-and-forget hooks
        if not [t for t in list(svc._tasks) if not t.done()]:
            break
        await asyncio.sleep(0.05)
    return "ok"


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    M.auth.auth_enabled = True
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    for k, v in (("key_health", "on"), ("home_ai", "on")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    who = ["daily", "f2f", "learn", "empty", "twice", "other", "off", "dbdown", "blank"]
    tok = {}
    for n in who:
        u = {"sub": f"u-{n}", "email": f"{n}@example.com", "name": "Learner Lee", "picture": ""}
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
        await db.save_user_keys(u["sub"], {"groq": f"gsk_{n}" + "G" * 30 + "xGq", "gemini": f"AIza{n}" + "M" * 30 + "xMq"}, verified=True)
        tok[n] = auth.make_session(u)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)

    section("Daily Talk: the first sentence, then the finished session")
    r = await session(tok["daily"], "daily", turns=1, end=False, hold=0.3)
    # (the socket was closed without End: a dropped phone - the server still saves the session when the socket closes)
    got = await ms("u-daily")
    check("one spoken turn records first_sentence, and a dropped socket still saves the session -> first_session", r == "ok" and got == ["first_sentence", "first_session"], got)

    section("Face-to-Face: End after one turn")
    r = await session(tok["f2f"], "conversation", turns=2, end=True)
    check("first_sentence + first_session after End", r == "ok" and await ms("u-f2f") == ["first_sentence", "first_session"], await ms("u-f2f"))

    section("Learn: a translator - a sentence, but never a saved session")
    r = await session(tok["learn"], "learning", turns=1, end=True)
    check("first_sentence is recorded, first_session is NOT (Learn is never persisted)", r == "ok" and await ms("u-learn") == ["first_sentence"], await ms("u-learn"))

    section("opening a chat without saying anything")
    r = await session(tok["empty"], "daily", turns=0, end=True)
    check("nothing is recorded: no sentence, no session", r == "ok" and await ms("u-empty") == [], await ms("u-empty"))

    section("a blank line is not a sentence")
    r = await session(tok["blank"], "daily", turns=0, blank=True, end=True)
    check("only whitespace was sent: nothing is recorded", r == "ok" and await ms("u-blank") == [], await ms("u-blank"))

    section("a second session, and other learners")
    await session(tok["twice"], "daily", turns=1, end=True)
    first = {x.name: x.first_at for x in (await _rows("u-twice"))}
    await session(tok["twice"], "conversation", turns=1, end=True)
    again = {x.name: x.first_at for x in (await _rows("u-twice"))}
    check("a second session adds no rows and leaves the ORIGINAL times alone", sorted(again) == ["first_sentence", "first_session"] and again == first, (first, again))
    check("another learner's rows are not touched", await ms("u-other") == [])

    section("the kill switch and a failing database")
    await db.set_setting("insights", "off")
    M.invalidate_access_cache()
    r = await session(tok["off"], "daily", turns=1, end=True)
    check("with the kill switch off the chat works and nothing is recorded", r == "ok" and await ms("u-off") == [], await ms("u-off"))
    await db.set_setting("insights", "on")
    M.invalidate_access_cache()
    real = svc.milestone

    async def boom(u, n):
        raise RuntimeError("insights is broken")
    svc.milestone = boom
    try:
        r = await session(tok["dbdown"], "daily", turns=1, end=True)
    finally:
        svc.milestone = real
    check("a hook that raises never breaks the chat (the session still completes)", r == "ok", r)
    check("... and the learner's real data is intact (the session was saved)", len(await _conv("u-dbdown")) >= 1, await _conv("u-dbdown"))

    server.should_exit = True
    await asyncio.sleep(0.3)
    print(f"\n{N - len(FAILS)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


async def _rows(uid):
    async with db._Session() as s:
        return (await s.execute(select(IM.EvMilestone).where(IM.EvMilestone.user_id == uid))).scalars().all()


async def _conv(uid):
    async with db._Session() as s:
        return (await s.execute(select(db.Conversation).where(db.Conversation.user_id == uid))).scalars().all()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
