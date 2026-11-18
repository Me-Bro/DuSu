"""Talk through the REAL provider walk (run via tests/talk/run.sh wire_walk.py): the real /ws/interview handler, the real `llm.assess` with its schema / check, the real walker with scripted FAKE providers
(tests/keys/world.py) - no stub of `llm`.  It proves at the wire what ws_selftest.py proves against a stub: one provider request for one good turn, and what the validated walk (settings.chain_v3) does with
the unusable replies Talk can get (prose where JSON is needed, a Hindi-only `reply`) - the next PROVIDER answers inside the same turn; nothing usable from anyone is the retry pop-up's `error` frame (`kp`
transient, never "your keys") with the free turn given back and the line not kept; with chain_v3 OFF the old walker behaves as it did and Talk retries once itself."""
import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")
sys.path.insert(0, "/tests/talk")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402

from world import World, install, ok                                 # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.keys import gate, ledger                                    # noqa: E402
from app.providers import openrouter_provider as op                  # noqa: E402
from app.talk import topics as T                                     # noqa: E402
import fixtures as F                                                 # noqa: E402

FAILS: list = []
N = 0
PORT = 8795
TALK_PREFIX = "You are DuSu, a warm, patient English speaking coach"
GOOD = {"reply": "Nice! What time do you usually wake up?", "hi": "अच्छा! आमतौर पर तुम्हारे जागने का समय क्या है?", "fix": None}
BEHAVE = {"groq": "ok", "gemini": "ok", "openrouter": "ok"}
DEV = lambda s: any("ऀ" <= c <= "ॿ" for c in s)            # noqa: E731


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


def reply(messages, provider, key):
    b = BEHAVE.get(provider, "ok")
    talk = bool(messages) and str(messages[0].get("content", "")).startswith(TALK_PREFIX)
    wants_json = bool(messages) and str(messages[-1].get("content", "")).endswith("Return ONLY the JSON object.")
    if not wants_json:
        return ok("Nice to meet you. Tell me more about that?")
    if not talk:                                                   # the end-of-chat memory pass
        return ok(json.dumps({"summary": "Talked about mornings.", "facts": {}, "events": [], "no_hindi": True, "asked_question": False, "next_hook": "", "recent_questions": [],
                              "scores": {"confidence": 60, "continuity": 60, "vocabulary": 60, "grammar_trend": 60, "depth": 60}, "genuine_effort": True}))
    if b == "prose":
        return ok("Sure! I would love to help you with that, here you go.")
    if b == "nofield":
        return ok(json.dumps({"hi": "अच्छा! तुम्हारा क्या हाल है?", "fix": None}, ensure_ascii=False))
    if b == "hindi":
        return ok(json.dumps({"reply": "बहुत अच्छा, आगे बताओ, तुम्हारी सुबह कैसी होती है?", "fix": None}, ensure_ascii=False))
    if b == "junk":
        return ok(json.dumps({"reply": "Nice! What time do you usually wake up?", "hi": "आपने क्या खाया?", "fix": {"q": "market", "f": "bazaar", "r": "x"}}, ensure_ascii=False))
    if b == "slip":
        return ok(json.dumps({"reply": "Good! What did you buy there?", "hi": "अच्छा! तुमने वहाँ क्या खरीदा?", "fix": {"q": "i go", "f": "I went", "r": "Yesterday means past."}}, ensure_ascii=False))
    return ok(json.dumps(GOOD, ensure_ascii=False))


WORLD = World()
WORLD.chat_reply = reply
install(WORLD)
REFUNDS: list = []
_orig_refund = M.TurnQuota.refund


async def spy_refund(self):
    REFUNDS.append(1)
    return await _orig_refund(self)


M.TurnQuota.refund = spy_refund
SESSIONS: list = []
OPENER_REQUESTS: list = []                                           # the provider chat requests that had been made when the opener arrived


class SpySession(M.Session):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        SESSIONS.append(self)


M.Session = SpySession


async def drive(token, behave, said="yesterday i go to the market", support="en_sub"):
    """One Talk chat over a real websocket with every provider answering as `behave` says -> (frames, the turn's last frame, the provider chat requests of that turn)."""
    for k in BEHAVE:
        BEHAVE[k] = "ok"
    frames: list = []

    async def until(ws, kinds):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 30))
            frames.append(m)
            if m.get("type") in kinds:
                return m

    topic = T.get("a1-morning-routine")
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        await ws.send(json.dumps({"type": "start", "mode": "talk", "token": token, "topic_id": topic["id"], "support": support, "name": "Ann", "hour": 11}))
        first = await until(ws, {"ai_text", "error", "quota", "keys_required"})
        OPENER_REQUESTS[:] = [c for c in WORLD.calls if c[2] == "chat"]
        for k, v in behave.items():
            BEHAVE[k] = v
        before = len(WORLD.calls)
        await ws.send(json.dumps({"type": "user_text", "text": said}))
        got = await until(ws, {"ai_text", "error", "quota"})
        turn_calls = [c for c in WORLD.calls[before:] if c[2] == "chat"]            # taken NOW: closing the socket saves the chat (a model call of its own)
    await asyncio.sleep(0.3)
    return frames, first, got, turn_calls


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    M.auth.auth_enabled = True
    T.use(T.Bank.from_rows([r for b in T.BANDS for r in F.rows(b, 9)]))
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    for k, v in (("talk_v3", "on"), ("key_health", "on"), ("keys_ui", "on"), ("chain_v3", "on")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    u = {"sub": "u-wire", "email": "wire@example.com", "name": "Learner Lee", "picture": ""}
    await db.login(u)
    await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    token = auth.make_session(u)
    gk, mk = "gsk_wire" + "G" * 30 + "xGq", "AIzawire" + "M" * 30 + "xMq"
    await db.save_user_keys(u["sub"], {"groq": gk, "gemini": mk}, verified=True)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)

    async def set_sw(**kw):
        for k, v in kw.items():
            await db.set_setting(k, v)
        M.invalidate_access_cache()

    def fresh():
        gate.reset_all(); ledger.reset_all(); op._ring.clear(); op._fail_logged.clear()
        WORLD.calls.clear()

    section("chain_v3 ON: a good turn is ONE provider request")
    await set_sw(chain_v3="on", key_health="on")
    fresh()
    frames, first, got, calls = await drive(token, {})
    check("the opener made NO provider request (the whole chat so far: zero)", first["type"] == "ai_text" and first["hi"] and OPENER_REQUESTS == [], (first, OPENER_REQUESTS))
    check("a good reply: one `ai_text` with the English reply and the Hindi subtitle", got["type"] == "ai_text" and got["text"] == GOOD["reply"] and got["hi"] == GOOD["hi"] and "fix" not in got, got)
    check("...for exactly ONE request to ONE provider (Groq's first model)", [(c[0], c[3]) for c in calls] == [("groq", "openai/gpt-oss-120b")], calls)
    check("no `quota` / `error` frame, nothing secret in anything the page received", not [f for f in frames if f["type"] in ("quota", "error")] and gk not in json.dumps(frames) and mk not in json.dumps(frames))
    fresh()
    frames, first, got, calls = await drive(token, {"groq": "slip"})
    check("a real slip: the fix arrives verified (q, f, r, c, full)", got["type"] == "ai_text" and got["fix"]["q"] == "i go" and got["fix"]["f"] == "I went" and got["fix"]["full"] == "yesterday I went to the market", got)
    check("...still one request", len(calls) == 1, calls)
    fresh()
    frames, first, got, calls = await drive(token, {"groq": "junk"})
    check("a reply with a bad subtitle (आप) and a free-swap fix: ONE request, the English reply goes out, subtitle and fix are dropped by the server", got["type"] == "ai_text" and got["text"].startswith("Nice!")
          and "hi" not in got and "fix" not in got and len(calls) == 1, (got, calls))

    section("chain_v3 ON: an unusable reply moves to the next provider INSIDE the same turn")
    fresh()
    frames, first, got, calls = await drive(token, {"groq": "prose"})
    check("Groq answers prose where Talk needs JSON: GEMINI's real reply reaches the learner", got["type"] == "ai_text" and got["text"] == GOOD["reply"] and got["hi"] == GOOD["hi"], got)
    check("...one request to Groq's first model, then Gemini - nothing was asked twice in a row", [(c[0], c[3]) for c in calls] == [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-flash-lite-latest")], calls)
    check("...and no other frame (no quota, no error) reached the learner", not [f for f in frames if f["type"] in ("quota", "error")], frames)
    fresh()
    frames, first, got, calls = await drive(token, {"groq": "hindi"})
    check("Groq's `reply` is Hindi only: the walk's check rejects it and Gemini's English reply is what the learner gets (never a Hindi line spoken by the English voice)",
          got["type"] == "ai_text" and got["text"] == GOOD["reply"] and not DEV(got["text"]) and [c[0] for c in calls] == ["groq", "gemini"], (got, calls))

    fresh()
    frames, first, got, calls = await drive(token, {"groq": "nofield"})
    check("valid JSON with no `reply` is unusable too: Gemini's answer reaches the learner in the same turn", got["type"] == "ai_text" and got["text"] == GOOD["reply"] and [c[0] for c in calls] == ["groq", "gemini"], (got, calls))

    section("chain_v3 ON: NOTHING usable from anyone")
    fresh()
    r0 = len(REFUNDS)
    n_sess = len(SESSIONS)
    frames, first, got, calls = await drive(token, {"groq": "prose", "gemini": "prose"})
    S = SESSIONS[n_sess]
    check("the learner gets the retry pop-up's frame: `error` with kp.state 'transient' and own keys - never a `quota` frame, never 'your keys'", got["type"] == "error" and got.get("kp", {}).get("state") == "transient"
          and not [f for f in frames if f["type"] == "quota"], got)
    check("...after ONE pass over the models (Groq's two, Gemini's one) - not the old retry-the-first-model loop", [(c[0], c[3]) for c in calls][:1] == [("groq", "openai/gpt-oss-120b")] and len(calls) == 3, [(c[0], c[3]) for c in calls])
    check("...the free turn was given back and the learner's line was NOT kept by the server", len(REFUNDS) == r0 + 1 and S.turns == 0 and [m["role"] for m in S.transcript] == ["assistant"], (len(REFUNDS) - r0, S.turns, S.transcript))

    section("chain_v3 OFF (key_health on): the walker as it was; Talk retries once itself")
    await set_sw(chain_v3="off", key_health="on")
    fresh()
    frames, first, got, calls = await drive(token, {})
    check("a good reply is still one request and the same frame", got["type"] == "ai_text" and got["text"] == GOOD["reply"] and len(calls) == 1, (got, calls))
    fresh()
    frames, first, got, calls = await drive(token, {"groq": "prose"})
    check("prose from the first model: the old walker accepts it, Talk's own single retry asks again (2 requests, both to Groq) and then reports the failure",
          got["type"] == "error" and len(calls) == 2 and {c[0] for c in calls} == {"groq"}, (got, [(c[0], c[3]) for c in calls]))
    await set_sw(chain_v3="on", key_health="on")

    server.should_exit = True
    await task
    print(f"\ntalk wire-walk: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
