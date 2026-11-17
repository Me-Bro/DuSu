"""Keys - tier 2c: the validated walk (settings.chain_v3) through the REAL /ws/interview handler (uvicorn in-process, auth ON), every provider scripted.

What is proven for the modes that need a model's JSON (the Home companion, Daily Talk) and for prose (Face-to-Face):
  * with chain_v3 ON a reply that is not usable (prose where JSON was needed, JSON without the field, an empty answer) never reaches the learner while another model
    can answer: the next PROVIDER answers inside the same turn, and the learner gets that answer;
  * when NO model gives a usable reply the learner gets the same built-in answer as before - never a `quota` frame, never "your keys" - after exactly one pass over the
    models (not the old retry-the-same-first-model loop);
  * with chain_v3 OFF the turn is exactly what it was (the unusable reply is what the old code saw, and its own retry asked the same model again);
  * the two switches are independent per learner (key_health off -> the validated walk does nothing).
Run via tests/keys/run.sh chain_ws.py.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402

from world import World, install, ok, R, completion                  # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.keys import gate, ledger                                    # noqa: E402
from app.providers import openrouter_provider as op                  # noqa: E402

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


HOME_JSON = json.dumps({"reply": "Good evening, ready for a small practice?", "intent": "general_conversation", "suggest": []})
DAILY_JSON = json.dumps({"english": "I went to the market", "reply_hindi": "Bahut accha, aur market mein kya kya kharida tumne aaj?", "next_question_hindi": "Aur kya kiya?",
                         "tip": "", "mood": "ok", "context": {}})
BEHAVE = {"groq": "ok", "gemini": "ok", "openrouter": "ok"}


def reply(messages, provider, key):
    b = BEHAVE.get(provider, "ok")
    wants_json = bool(messages) and str(messages[-1].get("content", "")).endswith("Return ONLY the JSON object.")
    daily = wants_json and any("conversation so far" in str(m.get("content", "")) and "learner_name" in str(m.get("content", "")) for m in messages)
    if b == "prose":
        return ok("Sure! I would love to help you with that, here you go.")
    if b == "empty":
        return R(200, completion(""))
    if b == "nofield":
        return ok(json.dumps({"intent": "general_conversation", "suggest": []}))
    if b == "cut":
        return ok('{"reply": "Good evening, this was going to be a long answer that', finish="length")
    return ok((DAILY_JSON if daily else HOME_JSON) if wants_json else "Nice to meet you. Tell me more about that?")


WORLD = World()
WORLD.chat_reply = reply
install(WORLD)
TALK = "i am a software engineer and i like my work in pune"


async def drive(token, mode, behave, *, extra=None):
    """One session over a real websocket with every provider answering as `behave` says -> (frames, the learner-turn frame)."""
    for k in BEHAVE:
        BEHAVE[k] = "ok"
    kinds_first = {"home": {"home_ready", "error", "quota"}, "daily": {"daily_question", "error", "quota"}, "conversation": {"ai_text", "error", "quota"}}[mode]
    kinds_reply = {"home": {"home_turn", "home_error", "quota", "error"}, "daily": {"daily_turn", "translate_error", "quota", "error"}, "conversation": {"ai_text", "error", "quota"}}[mode]
    frames = []

    async def until(ws, kinds):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 30))
            frames.append(m)
            if m.get("type") in kinds:
                return m

    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        await ws.send(json.dumps({"type": "start", "mode": mode, "token": token, "name": "Ann", "hour": 20, **(extra or {})}))
        await until(ws, kinds_first)
        for k, v in behave.items():
            BEHAVE[k] = v
        before = len(WORLD.calls)
        await ws.send(json.dumps({"type": "user_text", "text": TALK}))
        got = await until(ws, kinds_reply)
        turn_calls = [c for c in WORLD.calls[before:] if c[2] == "chat"]          # taken NOW: closing the socket saves the chat (a model call of its own)
    await asyncio.sleep(0.3)
    return frames, got, turn_calls


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    M.auth.auth_enabled = True
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    for k, v in (("home_ai", "on"), ("key_health", "on"), ("keys_ui", "on"), ("chain_v3", "on")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    u = {"sub": "u-chain", "email": "chain@example.com", "name": "Learner Lee", "picture": ""}
    await db.login(u)
    await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
    token = auth.make_session(u)
    gk, mk = "gsk_chain" + "G" * 30 + "xGq", "AIzachain" + "M" * 30 + "xMq"
    await db.save_user_keys(u["sub"], {"groq": gk, "gemini": mk}, verified=True)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)
    models_of = lambda calls, p=None: [c[3] for c in calls if p is None or c[0] == p]       # noqa: E731

    async def set_sw(**kw):
        for k, v in kw.items():
            await db.set_setting(k, v)
        M.invalidate_access_cache()

    def fresh():
        gate.reset_all(); ledger.reset_all(); op._ring.clear(); op._fail_logged.clear()
        WORLD.calls.clear()

    BUILTIN = None
    # ------------------------------------------------------------------------------------------ chain_v3 ON
    section("chain_v3 ON: the Home companion")
    await set_sw(chain_v3="on", key_health="on")
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "prose"})
    check("Groq answers with prose where the Home turn needs JSON: the learner gets GEMINI's real reply, not the built-in one", got["type"] == "home_turn" and got["text"] == "Good evening, ready for a small practice?", got)
    check("... one request to Groq's first model, then Gemini: nothing was asked twice in a row", [(c[0], c[3]) for c in calls] == [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-flash-lite-latest")], calls)
    check("... and no frame of any other kind reached the learner (no quota, no error)", not [f for f in frames if f["type"] in ("quota", "home_error", "error")], frames)
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "nofield"})
    check("valid JSON without a `reply` is just as unusable: Gemini answers", got["type"] == "home_turn" and got["text"] == "Good evening, ready for a small practice?" and len(calls) == 2, (got, calls))
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "cut"})
    check("a JSON reply cut off by the token limit is not half-parsed: Gemini answers", got["type"] == "home_turn" and got["text"] == "Good evening, ready for a small practice?" and len(calls) == 2, (got, calls))
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "empty"})
    check("an empty answer: Gemini answers", got["type"] == "home_turn" and got["text"] == "Good evening, ready for a small practice?" and len(calls) == 2, (got, calls))
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "prose", "gemini": "prose"})
    BUILTIN = got.get("text")
    check("NO model gives a usable reply: the learner still gets an answer (the built-in one) - a home_turn, never a quota frame or an error", got["type"] == "home_turn" and BUILTIN and BUILTIN != "Good evening, ready for a small practice?"
          and not [f for f in frames if f["type"] in ("quota", "home_error", "error")], (got, [f["type"] for f in frames]))
    check("... after ONE pass over the models (Groq's two, Gemini's one = 3 requests) - the old caller loop would have asked the first model again", models_of(calls) == ["openai/gpt-oss-120b", "gemini-flash-lite-latest", "openai/gpt-oss-20b"], models_of(calls))
    fresh()
    frames, got2, calls2 = await drive(token, "home", {"groq": "prose", "gemini": "prose"})
    check("the models that just broke the contract are held back: an immediate second turn asks fewer of them, and still answers", got2["type"] == "home_turn" and len(calls2) <= len(calls), (len(calls2), len(calls)))
    await asyncio.sleep(0.1)

    section("chain_v3 ON: Daily Talk")
    fresh()
    frames, got, calls = await drive(token, "daily", {"groq": "prose"})
    check("Daily Talk: Groq's prose is unusable, Gemini's JSON is the reply the learner hears", got["type"] == "daily_turn" and got["reply"].startswith("Bahut accha") and got["english"] == "I went to the market", got)
    check("... the first provider once, the second once", [c[0] for c in calls] == ["groq", "gemini"], calls)

    section("chain_v3 ON: Face-to-Face (prose)")
    fresh()
    frames, got, calls = await drive(token, "conversation", {"groq": "empty"})
    check("an EMPTY answer from Groq's first model: the walk goes to Gemini at once (the old walker asked Groq's second model first)", got["type"] == "ai_text" and got["text"].startswith("Nice to meet you")
          and [c[0] for c in calls] == ["groq", "gemini"], (got, calls))

    # ------------------------------------------------------------------------------------------ chain_v3 OFF = the walker as it was
    section("chain_v3 OFF (key_health still on): exactly the old behaviour")
    await set_sw(chain_v3="off")
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "prose"})
    check("Home: the unusable reply is what the old code saw: it retried the SAME first model, and the learner got the built-in answer", got["type"] == "home_turn" and got["text"] == BUILTIN
          and models_of(calls, "groq") == ["openai/gpt-oss-120b", "openai/gpt-oss-120b"] and not models_of(calls, "gemini"), (got, calls))
    fresh()
    frames, got, calls = await drive(token, "daily", {"groq": "prose"})
    check("Daily Talk: the old behaviour (nothing usable -> an empty reply the page covers with its own line)", got["type"] == "daily_turn" and got["reply"] == "", got)
    fresh()
    frames, got, calls = await drive(token, "conversation", {"groq": "empty"})
    check("Face-to-Face: the old walker tried Groq's SECOND model before leaving Groq", got["type"] == "ai_text" and models_of(calls, "groq") == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], (got, calls))

    # ------------------------------------------------------------------------------------------ independence of the switches
    section("chain_v3 ON but key_health OFF: the validated walk does nothing (it needs the per-key engine)")
    await set_sw(chain_v3="on", key_health="off")
    fresh()
    frames, got, calls = await drive(token, "home", {"groq": "prose"})
    check("Home: the legacy walker answered - same as chain_v3 off", got["type"] == "home_turn" and got["text"] == BUILTIN and not models_of(calls, "gemini"), (got, calls))
    check("... and the engine level was 0", await M.engine_level("chain@example.com") == 0)
    await set_sw(key_health="on", chain_v3="owner")
    check("'owner' staging: an ordinary learner is level 1, the owner is level 2", await M.engine_level("chain@example.com") == 1 and await M.engine_level("david123rana@gmail.com") == 2)
    await set_sw(chain_v3="on")
    check("'on': everyone is level 2", await M.engine_level("chain@example.com") == 2)
    await set_sw(chain_v3="bogus")
    check("an unknown value reads as off", await M.chain_v3_mode() == "off" and await M.engine_level("chain@example.com") == 1)

    server.should_exit = True
    await asyncio.sleep(0.5)
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
