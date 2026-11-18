"""Talk - the REAL app (uvicorn + a scratch MongoDB) for a REAL browser to talk to.

The model is the scripted TalkStub of tests/talk/talk_stub.py (the same double the WebSocket tier uses: it enforces the schema and the check of the real validated walk), so what a
learner sees is the REAL server code - the topic bank, the opener without a model call, the one-call turn, the fix verified by Grammar Coach's machinery, the refund, the reconnect,
the reward - with replies the spec scripts.  Every AI provider's HTTP is a scripted fake as well (tests/keys/world.py), so the key engine and the retry pop-up behave as in production.
No key exists anywhere; the network the container sits on is INTERNAL.

Seeds learners (the profile level decides the default support level: A1 -> Hindi to English, A2 -> English + Hindi subtitles, B1 -> English only), stores two keys for them, switches Talk,
the key screens and the Hindi / English choice ON, writes the session tokens to `$E2E_DIR/tokens.json` and serves on :8000.  Test-only routes (never in the app, they sit in front of the
app's catch-all):
  POST /__e2e/script  {replies:[...]}   the raw replies (dict or string) the next Talk model calls return, one each
  POST /__e2e/fail    {n}               the next n Talk model calls fail with a transient provider-chain error (the "AI did not answer" pop-up's case)
  POST /__e2e/delay   {seconds}         every Talk model call takes this long
  POST /__e2e/setting {key, value}      any setting (talk_v3, grammar_lab, home_ai ...), drops the access cache
  POST /__e2e/bank    {mode}            real | empty   the topic bank
  POST /__e2e/reset                     forget the script, the failures, the delay and the logs
  GET  /__e2e/log                       {talk_calls, calls:[{talk, payload_tail}], awards:[...], sessions:n}
Started by run_real.sh - never run against production."""
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/talk")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                      # noqa: E402
from fastapi import Request                                         # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.interview import engine as ienv                            # noqa: E402
from app.keys import gate                                           # noqa: E402
from app.keys.errors import ProviderChainError                      # noqa: E402
from app.talk import topics as T                                    # noqa: E402
from app.store import update                                        # noqa: E402
from talk_stub import TalkStub, TALK_PREFIX                         # noqa: E402
from world import World, install                                    # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys must be blank (run through run_real.sh)"


class Chat(TalkStub):
    """The Talk model double plus what a browser run needs: failures, a delay, and an answer for the Daily Talk opener / the memory pass."""

    def __init__(self):
        super().__init__(v3=False)
        self.fail_n = 0
        self.delay = 0.0

    async def assess(self, system, payload, *a, **kw):
        is_talk = system.startswith(TALK_PREFIX)
        if is_talk and self.delay:
            await asyncio.sleep(self.delay)
        if is_talk and self.fail_n > 0:
            self.fail_n -= 1
            self.log.append({"kind": "assess", "talk": True, "system": system, "payload": payload, "failed": True})
            raise ProviderChainError("busy", "transient", [{"provider": "groq", "kind": "transient", "retry_s": 6}], own=True)
        d = await super().assess(system, payload, *a, **kw)
        if is_talk:
            return d
        # not a Talk call: Daily Talk's turn and the end-of-chat memory pass share this reply (each reads its own keys)
        return {**d, "english": "I went to the market.", "reply_hindi": "अच्छा लगा! तुमने वहाँ क्या खरीदा? आज का दिन कैसा रहा, मुझे बताओ।",
                "next_question_hindi": "आज का दिन कैसा रहा?", "tip": "", "mood": "ok", "context": {}}


CHAT = Chat()
M.llm = CHAT
ienv.llm = CHAT

AWARDS: list = []
_orig_award = db.award_speaker_progress


async def _spy_award(uid, mode, *a, **kw):
    AWARDS.append({"uid": uid, "mode": mode, "turns": kw.get("turns")})
    return await _orig_award(uid, mode, *a, **kw)


db.award_speaker_progress = _spy_award
SESSIONS: list = []


class SpySession(ienv.Session):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        SESSIONS.append(self.mode)


M.Session = SpySession
install(World())                                                    # every provider HTTP call (the key checks) is answered by a fake

NAMES = [f"tk{i}" for i in range(1, 61)] + ["off", "a1", "b1", "early"]
LEVEL = {"a1": "A1", "b1": "B1"}


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {n: {"sub": f"e2e-{n}", "email": f"{n}@example.com", "name": f"{n.title()} Learner", "picture": ""} for n in NAMES}
    users["owner"] = {"sub": "e2e-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    for k, u in users.items():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": LEVEL.get(k, "A2"), "scores": {}, "weak_areas": []})
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()
    async with db._Session() as s:
        for n in list(NAMES) + ["owner"]:
            await s.execute(update(db.Progress).where(db.Progress.user_id == f"e2e-{n}").values(xp=40, streak_days=3, last_active=today - dt.timedelta(days=1)))
        await s.commit()
    keys = {}
    for n in NAMES:
        k = {"groq": f"gsk_{n}" + "G" * 28 + "9fA2", "gemini": f"AIza{n}" + "M" * 28 + "Xy71"}
        keys[n] = k
        await db.save_user_keys(f"e2e-{n}", k, verified=True)
    for k, v in (("talk_v3", "on"), ("grammar_lab", "on"), ("key_health", "on"), ("keys_ui", "on"), ("bilingual", "on"), ("home_ai", "off")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    await db.early_add("early@example.com")
    out = os.environ.get("E2E_DIR", "/tests/talk/.e2e")
    os.makedirs(out, exist_ok=True)
    json.dump({k: {"token": auth.make_session(u), "user": u, "keys": keys.get(k)} for k, u in users.items()}, open(out + "/tokens.json", "w"))
    await __import__('app.store', fromlist=['close']).close()        # the client made in THIS event loop must not be reused by uvicorn's own loop


@M.app.post("/__e2e/script")
async def _script(request: Request):
    CHAT.talk_script = list((await request.json()).get("replies") or [])
    return {"ok": True, "n": len(CHAT.talk_script)}


@M.app.post("/__e2e/fail")
async def _fail(request: Request):
    CHAT.fail_n = int((await request.json()).get("n") or 0)
    return {"ok": True}


@M.app.post("/__e2e/delay")
async def _delay(request: Request):
    CHAT.delay = float((await request.json()).get("seconds") or 0)
    return {"ok": True}


@M.app.post("/__e2e/setting")
async def _setting(request: Request):
    b = await request.json()
    await db.set_setting(str(b["key"]), str(b["value"]))
    M.invalidate_access_cache()
    return {"ok": True}


@M.app.post("/__e2e/bank")
async def _bank(request: Request):
    mode = (await request.json()).get("mode", "real")
    if mode == "empty":
        T.use(T.Bank.from_rows([]))
    else:
        T.reset()
    return {"ok": True, "total": T.count().get("total", 0)}


@M.app.post("/__e2e/reset")
async def _reset():
    CHAT.talk_script = []
    CHAT.fail_n = 0
    CHAT.delay = 0.0
    CHAT.log.clear()
    AWARDS.clear()
    SESSIONS.clear()
    gate.reset_all()
    T.reset()
    return {"ok": True}


@M.app.get("/__e2e/log")
async def _log():
    return {"talk_calls": len(CHAT.talk_calls()), "calls": [{"talk": c["talk"], "failed": bool(c.get("failed")), "payload_tail": str(c.get("payload", ""))[-300:]} for c in CHAT.log],
            "awards": AWARDS, "sessions": SESSIONS}


# routes added now sit AFTER the app's SPA catch-all, which would answer them with HTML - move them to the front
for _r in [r for r in M.app.router.routes if getattr(r, 'path', '').startswith('/__e2e/')]:
    M.app.router.routes.remove(_r)
    M.app.router.routes.insert(0, _r)

asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
