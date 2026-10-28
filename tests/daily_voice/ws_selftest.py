"""Daily Talk vs a locked screen - the server half: the REAL /ws/interview handler (uvicorn in-process, auth ON, scratch Postgres, scripted fake providers).

What is proven:
  * `ping` is answered with `pong` (before and after `start`), and an unknown frame type is still silently ignored (an old client that never pings is unaffected);
  * a Daily `start` with `reconnect: true` and a non-empty `resume` is a QUIET resume: the server answers `daily_resumed`, makes NO model call and sends no greeting, and the
    replayed turns reach the model as context for the next real turn;
  * ... and counts only what is said AFTER it: finishing straight away writes nothing (no XP, no summary row); one new turn is rewarded once;
  * everything else is exactly today's behaviour: no flag, a flag that is not the boolean `true`, an empty resume, another mode that is sent the flag.
Run via tests/daily_voice/run.sh ws_selftest.py.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402
from sqlalchemy import func, select                                  # noqa: E402

from world import World, install, ok                                 # noqa: E402

from app import auth, db, main as M                                  # noqa: E402

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


JSON_REPLY = json.dumps({"reply": "Hello there", "intent": "general_conversation", "suggest": [], "english": "I went to the market", "reply_hindi": "Bahut accha, aur batao kya chal raha hai aajkal?",
                         "next_question_hindi": "Aur batao?", "tip": "", "mood": "ok", "context": {}, "summary": "They chatted about their day.", "facts": {}, "events": [], "no_hindi": False,
                         "asked_question": False, "next_hook": "", "overall": 70, "categories": [], "genuine_effort": True})
SEEN: list = []                                                      # every prompt a chat call carried (what the model was told)


def reply(messages, provider, key):
    SEEN.append(json.dumps(messages, ensure_ascii=False))
    wants_json = bool(messages) and str(messages[-1].get("content", "")).endswith("Return ONLY the JSON object.")
    return ok(JSON_REPLY if wants_json else "Nice to meet you. Tell me more about that?")


WORLD = World()
WORLD.chat_reply = reply
install(WORLD)

RESUME = [{"role": "assistant", "content": "Namaste! Aaj ka din kaisa raha?"}, {"role": "user", "content": "mera din bahut accha tha purple elephant"},
          {"role": "assistant", "content": "Wah, ye sunkar achha laga!"}]


def chat_calls():
    return sum(1 for c in WORLD.calls if c[2] == "chat")


async def recv_until(ws, kinds, timeout=30):
    frames = []
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        frames.append(m)
        if m.get("type") in kinds:
            return frames


async def xp_of(sub):
    st = await db.get_state(sub)
    return (st.get("progress") or {}).get("xp", 0)


async def conv_rows(sub):
    async with db._Session() as s:
        return (await s.execute(select(func.count()).select_from(db.Conversation).where(db.Conversation.user_id == sub))).scalar_one()


def start_frame(tok, **extra):
    f = {"type": "start", "mode": "daily", "token": tok, "hour": 11, "day": "2026-10-28", "resume": [], "lang": "hi"}
    f.update(extra)
    return f


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    M.auth.auth_enabled = True
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    M.invalidate_access_cache()
    names = ["quiet", "noflag", "weird", "empty", "other", "reward0", "reward1", "plainresume", "pinger"]
    users, tok = {}, {}
    for n in names:
        users[n] = {"sub": f"u-{n}", "email": f"{n}@example.com", "name": "Learner Lee", "picture": ""}
        await db.login(users[n])
        await db.save_assessment(users[n]["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
        tok[n] = auth.make_session(users[n])
        await db.save_user_keys(users[n]["sub"], {"groq": f"gsk_{n}" + "G" * 30 + "xGq", "gemini": f"AIza{n}" + "M" * 30 + "xMq"}, verified=True)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)
    URL = f"ws://127.0.0.1:{PORT}/ws/interview"

    # ------------------------------------------------------------------------------------------ ping
    section("ping / pong")
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        m = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("a ping before `start` is answered with pong", m == {"type": "pong"}, m)
        await ws.send(json.dumps({"type": "zzz_unknown"}))                       # an unknown type must still be ignored ...
        await ws.send(json.dumps({"type": "ping"}))
        m = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("an unknown frame type is still silently ignored (the next frame is the pong)", m == {"type": "pong"}, m)
        await ws.send(json.dumps(start_frame(tok["pinger"])))
        await recv_until(ws, {"daily_question"})
        await ws.send(json.dumps({"type": "ping"}))
        m = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("a ping in the middle of a session is answered too", m == {"type": "pong"}, m)
        await ws.send(json.dumps({"type": "user_text", "text": "main theek hoon"}))
        fr = await recv_until(ws, {"daily_turn"})
        check("and the session carries on normally afterwards", fr[-1]["type"] == "daily_turn" and fr[-1]["reply"], fr)

    # ------------------------------------------------------------------------------------------ the quiet resume
    section("reconnect: a quiet resume (no greeting, no model call)")
    await asyncio.sleep(2.0)                                         # the previous session's own end-of-session save (a model call) must not land in this window
    c0 = chat_calls(); SEEN.clear()
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps(start_frame(tok["quiet"], resume=RESUME, reconnect=True)))
        fr = await recv_until(ws, {"daily_resumed", "daily_question", "error", "quota"})
        check("the server answers daily_resumed", fr[-1]["type"] == "daily_resumed" and fr[-1].get("lang") == "hi", fr)
        check("... and sends no greeting (no daily_question)", all(f["type"] != "daily_question" for f in fr), fr)
        await asyncio.sleep(0.4)
        check("... and makes NO model call for it", chat_calls() == c0, chat_calls() - c0)
        await ws.send(json.dumps({"type": "user_text", "text": "main ab ghar jaa rahi hoon"}))
        fr = await recv_until(ws, {"daily_turn", "translate_error", "quota", "error"})
        check("the next real turn works", fr[-1]["type"] == "daily_turn" and fr[-1]["reply"], fr)
        check("... and the model was told the replayed turns as context", any("purple elephant" in p for p in SEEN), len(SEEN))

    section("what the server counts after a quiet resume")
    for who, new_turn in (("reward0", False), ("reward1", True)):
        sub = users[who]["sub"]
        x0, r0 = await xp_of(sub), await conv_rows(sub)
        async with websockets.connect(URL) as ws:
            await ws.send(json.dumps(start_frame(tok[who], resume=RESUME, reconnect=True)))
            await recv_until(ws, {"daily_resumed"})
            if new_turn:
                await ws.send(json.dumps({"type": "user_text", "text": "main kal phir aaungi"}))
                await recv_until(ws, {"daily_turn"})
            await ws.send(json.dumps({"type": "end"}))
            fr = await recv_until(ws, {"ended"}, 60)
        await asyncio.sleep(0.5)
        x1, r1 = await xp_of(sub), await conv_rows(sub)
        if not new_turn:
            check("finishing straight after a quiet resume earns nothing (the replayed turns were rewarded when their socket closed)", x1 == x0, (x0, x1))
            check("... and writes no summary row", r1 == r0, (r0, r1))
            check("... and there is no speaker_progress frame (nothing new to show)", all(f["type"] != "speaker_progress" for f in fr), [f["type"] for f in fr])
        else:
            check("one new turn after a quiet resume is rewarded once (+20)", x1 - x0 == 20, (x0, x1))
            check("... with one summary row", r1 - r0 == 1, (r0, r1))

    # ------------------------------------------------------------------------------------------ what must NOT change
    section("everything else is exactly today's behaviour")
    for who, label, extra in (("noflag", "no flag", {}), ("weird", "reconnect that is not the boolean true", {"reconnect": "true"}),
                              ("weird", "reconnect = 1", {"reconnect": 1}), ("weird", "reconnect = false", {"reconnect": False})):
        c0 = chat_calls()
        async with websockets.connect(URL) as ws:
            await ws.send(json.dumps(start_frame(tok[who], resume=RESUME, **extra)))
            fr = await recv_until(ws, {"daily_question", "daily_resumed", "error", "quota"})
        check(f"[{label}] a resume still opens with a greeting (daily_question) and a model call", fr[-1]["type"] == "daily_question" and chat_calls() > c0, fr)
    c0 = chat_calls()
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps(start_frame(tok["empty"], resume=[], reconnect=True)))
        fr = await recv_until(ws, {"daily_question", "daily_resumed", "error", "quota"})
    check("reconnect with nothing to resume is a plain start (a greeting)", fr[-1]["type"] == "daily_question" and chat_calls() > c0, fr)
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["other"], "name": "Ann", "hour": 11, "reconnect": True, "resume": RESUME}))
        fr = await recv_until(ws, {"ai_text", "daily_resumed", "error", "quota"})
    check("another mode that is sent the flag ignores it", fr[-1]["type"] == "ai_text", fr)

    section("a plain resume (no flag) is unchanged: its replayed turns still count when the chat ends")
    sub = users["plainresume"]["sub"]
    x0 = await xp_of(sub)
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps(start_frame(tok["plainresume"], resume=RESUME)))
        await recv_until(ws, {"daily_question"})
        await ws.send(json.dumps({"type": "end"}))
        await recv_until(ws, {"ended"}, 60)
    await asyncio.sleep(0.5)
    check("(the pre-existing next-day resume behaviour: replayed user turns are counted)", (await xp_of(sub)) - x0 == 20, (x0, await xp_of(sub)))

    server.should_exit = True
    await task
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    if FAILS:
        print("FAILED:\n  " + "\n  ".join(FAILS))
        sys.exit(1)


asyncio.run(main())
