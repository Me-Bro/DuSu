"""Keys - tier 2b: the REAL /ws/interview handler (uvicorn in-process, auth ON) with the per-key walker and a scripted provider world.

What is proven, for every mode that talks to a model (Face-to-Face, Daily Talk, Learn, the Home companion, a Practice viva):
  * with the engine ON, a failure frame carries `kp` - which key failed how - ADDED to the frame the old code already sent (`quota` / `error` / `translate_error` /
    `home_error` / `practice_error`): no new frame type, the old fields unchanged;
  * with the engine OFF the frames are exactly what they were (the old wording, no `kp`);
  * a healthy session is IDENTICAL with the engine on and off (frame by frame, text by text);
  * a socket's key chain is fixed at `start`; a learner with no keys is told `keys_required`; the old "Settings" wording is gone from what the engine says;
  * "the AI service did not answer" is NEVER a `quota` frame (even when its text says 429): every chat sends the feature's own error frame with kp 'transient'; on
    DuSu's own keys (`own: false`) the learner is never shown a key row, never told to fix a key, and the free daily turn the failed turn would have used is given back;
  * a failed Face-to-Face turn takes the unanswered line back, so the learner (or the page) saying it again is not said twice.
Run via tests/keys/run.sh ws_selftest.py.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402

from world import World, install, ok, err, GROQ_401, GROQ_429_TPD, GEMINI_400_KEY, GEMINI_429_DAY, GEMINI_503, OPENROUTER_401, OPENROUTER_429_DAY    # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.keys import gate, ledger                                    # noqa: E402

FAILS: list = []
N = 0
PORT = 8766


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


BEHAVE = {"groq": "ok", "gemini": "ok", "openrouter": "ok"}
ERRS = {
    "limited": {"groq": err(429, GROQ_429_TPD), "gemini": err(429, GEMINI_429_DAY), "openrouter": err(429, OPENROUTER_429_DAY)},
    "invalid": {"groq": err(401, GROQ_401), "gemini": err(400, GEMINI_400_KEY), "openrouter": err(401, OPENROUTER_401)},
    "down": {"groq": err(503, {"error": {"message": "boom"}}), "gemini": err(503, GEMINI_503), "openrouter": err(503, {"error": {"message": "boom"}})},
}
JSON_REPLY = json.dumps({"reply": "Hello there", "intent": "general_conversation", "suggest": [], "english": "I went to the market", "reply_hindi": "Bahut accha",
                         "next_question_hindi": "Aur batao?", "tip": "", "mood": "ok", "context": {}, "summary": "They chatted.", "facts": {}, "events": [],
                         "no_hindi": False, "asked_question": False, "next_hook": "", "overall": 70, "categories": [], "genuine_effort": True})


def reply(messages, provider, key):
    b = BEHAVE.get(provider, "ok")
    if b != "ok":
        return ERRS[b][provider]
    wants_json = bool(messages) and str(messages[-1].get("content", "")).endswith("Return ONLY the JSON object.")
    return ok(JSON_REPLY if wants_json else "Nice to meet you. Tell me more about that?")


WORLD = World()
WORLD.chat_reply = reply
install(WORLD)

TERMINAL = {"ai_text", "daily_turn", "translation", "home_turn", "error", "quota", "limit", "home_error", "translate_error", "practice_report", "practice_error", "ended",
            "daily_question", "ready", "home_ready", "keys_required", "auth_error"}
FIRST = {"conversation": {"ai_text", "error", "quota", "keys_required"}, "daily": {"daily_question", "error", "quota", "keys_required"},
         "learning": {"ready", "error", "quota", "keys_required"}, "home": {"home_ready", "error", "quota", "keys_required"},
         "practice": {"ai_text", "error", "quota", "keys_required"}}
REPLY = {"conversation": {"ai_text", "error", "quota"}, "daily": {"daily_turn", "translate_error", "quota", "error"},
         "learning": {"translation", "translate_error", "quota", "error"}, "home": {"home_turn", "home_error", "quota", "error"},
         "practice": {"ai_text", "error", "quota"}}
TALK = "i am a software engineer and i like my work in pune"
PRACTICE = {"kind": "viva", "topic": "machine learning basics", "plang": "en", "level": "intermediate", "rounds": 4, "feedback_lang": "hinglish"}


async def drive(token, mode, *, turns=1, fail_after_start=None, end=False, extra=None, keys=None, mid=None):
    """One scripted session over a real websocket -> (frames, the first frame's type). `fail_after_start` = a BEHAVE value to switch to once the session is open."""
    frames = []

    async def until(ws, kinds, timeout=30):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            frames.append(m)
            if m.get("type") in kinds:
                return m

    for k in BEHAVE:
        BEHAVE[k] = "ok"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        start = {"type": "start", "mode": mode, "token": token, "name": "Ann", "role": "developer", "hour": 11}
        if keys is not None:
            start["keys"] = keys
        start.update(extra or {})
        await ws.send(json.dumps(start))
        first = await until(ws, FIRST[mode])
        if first["type"] in ("keys_required", "error", "quota"):
            return frames, first["type"]
        if fail_after_start:
            for k in BEHAVE:
                BEHAVE[k] = fail_after_start
        for _ in range(turns):
            if mid:
                await mid()
            await ws.send(json.dumps({"type": "user_text", "text": TALK}))
            await until(ws, REPLY[mode])
        if end:
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, {"ended", "practice_report", "practice_error", "error"}, 60)
    await asyncio.sleep(0.4)
    return frames, first["type"]


def last(frames, kinds):
    return next((f for f in reversed(frames) if f.get("type") in kinds), None)


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    M.auth.auth_enabled = True                                       # the WS handler needs a signed-in learner
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    for k, v in (("home_ai", "on"), ("practice_room", "on"), ("key_health", "on"), ("keys_ui", "on")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    modes = ["conversation", "daily", "learning", "home", "practice"]
    who = {}
    for m_ in modes:
        for eng in ("on", "off"):
            who[(m_, eng)] = f"{m_}-{eng}"
    who["nokeys"], who["fixed"], who["ab-on"], who["ab-off"], who["spy"], who["srv"], who["owner"] = "nokeys", "fixed", "ab-on", "ab-off", "spy", "srv", "owner"
    users, tok, keys = {}, {}, {}
    for n in set(who.values()):
        users[n] = {"sub": f"u-{n}", "email": ("david123rana@gmail.com" if n == "owner" else f"{n}@example.com"), "name": "Learner Lee", "picture": ""}
        await db.login(users[n])
        await db.save_assessment(users[n]["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
        tok[n] = auth.make_session(users[n])
        keys[n] = {"groq": f"gsk_{n}" + "G" * 30 + "xGq", "gemini": f"AIza{n}" + "M" * 30 + "xMq"}
        if n != "nokeys":
            await db.save_user_keys(users[n]["sub"], keys[n], verified=True)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket (startup hooks ran: the keys loop is up)", server.started and getattr(M.app.state, "keys_task", None) is not None)

    OLD = "Your API keys hit their limit. Add or replace a key in Settings."
    for eng_label, switch in (("ON", "on"), ("OFF", "off")):
        await db.set_setting("key_health", switch)
        M.invalidate_access_cache()
        section(f"engine {eng_label}: what each mode sends when the keys fail")
        for mode in modes:
            n = who[(mode, switch)]
            extra = PRACTICE if mode == "practice" else None
            for beh, label in (("limited", "every key limited"), ("invalid", "every key rejected"), ("down", "the provider is down")):
                gate.reset_all()
                frames, _first = await drive(tok[n], mode, fail_after_start=beh, extra=extra, end=(mode == "practice"))
                fail = last(frames, {"quota", "error", "home_error", "translate_error", "practice_error"})
                kp = (fail or {}).get("kp")
                if eng_label == "ON":
                    expect_kp = "all_limited" if beh == "limited" else "all_invalid" if beh == "invalid" else "transient"
                    check(f"[{mode}] {label}: the failure frame ({(fail or {}).get('type')}) carries kp {expect_kp}", fail is not None and kp is not None and kp["state"] == expect_kp
                          and all(k["provider"] in ("groq", "gemini") for k in kp["keys"]) and kp["now"] > 1_700_000_000, (fail, ))
                    if fail and fail["type"] == "quota":
                        check(f"[{mode}] {label}: the old clients' text now names the real path, not 'Settings'", "Settings" not in fail["msg"] and "My AI keys" in fail["msg"], fail.get("msg"))
                    if fail and fail["type"] == "practice_error":
                        check(f"[{mode}] {label}: practice_error keeps its old msg word ({'quota' if beh == 'limited' else 'unavailable'})", fail["msg"] == ("quota" if beh == "limited" else "unavailable"), fail)
                    if kp:
                        check(f"[{mode}] {label}: kp carries no key text and no provider text", n not in json.dumps(kp) and "RESOURCE" not in json.dumps(kp) and "Rate limit" not in json.dumps(kp))
                else:
                    check(f"[{mode}] {label}: the frame is what it always was (no kp)", fail is not None and "kp" not in fail, fail)
                    if fail and fail["type"] == "quota":
                        check(f"[{mode}] {label}: ... with the old wording", fail["msg"] == OLD or fail["msg"] == "quota", fail.get("msg"))

    # ------------------------------------------------------------------------------------------ the very first model call failing (the opening)
    await db.set_setting("key_health", "on"); M.invalidate_access_cache()
    section("the opening itself fails (Face-to-Face asks the model at start)")
    for k in BEHAVE:
        BEHAVE[k] = "limited"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        gate.reset_all()
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["spy"], "name": "Ann", "hour": 11}))
        got = []
        for _ in range(4):
            try:
                got.append(json.loads(await asyncio.wait_for(ws.recv(), 10)))
            except Exception:
                break
    q = next((f for f in got if f["type"] == "quota"), None)
    check("a failure at the opening arrives as the usual `quota` frame with kp (the outer handler)", q is not None and q["kp"]["state"] == "all_limited" and "My AI keys" in q["msg"], got)
    for k in BEHAVE:
        BEHAVE[k] = "invalid"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        gate.reset_all()
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["spy"], "name": "Ann", "hour": 11}))
        got = []
        for _ in range(4):
            try:
                got.append(json.loads(await asyncio.wait_for(ws.recv(), 10)))
            except Exception:
                break
    e = next((f for f in got if f["type"] in ("quota", "error")), None)
    check("... rejected keys at the opening: a `quota` frame with kp all_invalid and the accurate words (it used to say 'All AI providers are busy' about REJECTED keys)",
          e is not None and e["type"] == "quota" and e["kp"]["state"] == "all_invalid" and "rejected" in e["msg"].lower() and "busy" not in e["msg"].lower(), got)
    for k in BEHAVE:
        BEHAVE[k] = "down"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        gate.reset_all()
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["spy"], "name": "Ann", "hour": 11}))
        got = []
        for _ in range(4):
            try:
                got.append(json.loads(await asyncio.wait_for(ws.recv(), 10)))
            except Exception:
                break
    e = next((f for f in got if f["type"] in ("quota", "error")), None)
    check("... the provider down at the opening: an `error` frame with kp transient (never `quota`), the old text kept for old clients",
          e is not None and e["type"] == "error" and e["kp"]["state"] == "transient" and e["kp"]["own"] is True and "busy" in e["msg"].lower(), got)

    # ------------------------------------------------------------------------------------------ "the AI did not answer" is never quota; DuSu's own keys
    section("DuSu's own keys (the owner / the quota phase): never a key row, never `quota`, the free turn is given back")
    M.settings.groq_api_key, M.settings.gemini_api_key, M.settings.openrouter_api_key = "gsk_SERVER" + "q" * 30, "AIzaSERVER" + "q" * 30, "sk-or-v1-SERVER" + "q" * 30
    await db.set_setting("access_phase", "quota"); M.invalidate_access_cache()
    srv_sub = users["srv"]["sub"]
    day = M._quota_day()
    OPEN = 1                       # opening a socket is itself charged once (TurnQuota.open -> charge_request); only the TURNS are given back
    for mode in ("conversation", "daily", "learning", "home"):
        for beh, label in (("limited", "every server key limited (its text says 429)"), ("invalid", "every server key rejected"), ("down", "the provider is down")):
            gate.reset_all()
            u0 = await db.usage_today(srv_sub, day)
            frames, _first = await drive(tok["srv"], mode, fail_after_start=beh)
            fail = last(frames, {"quota", "error", "home_error", "translate_error"})
            kp = (fail or {}).get("kp") or {}
            check(f"[{mode}] DuSu's keys, {label}: never a `quota` frame ({(fail or {}).get('type')}), kp = transient, own false, NO key rows",
                  fail is not None and fail["type"] != "quota" and kp.get("state") == "transient" and kp.get("own") is False and kp.get("keys") == [], fail)
            check(f"[{mode}] ... {label}: no key text and no provider text in what the learner is sent", "SERVER" not in json.dumps(frames) and "RESOURCE" not in json.dumps(fail) and "Rate limit" not in json.dumps(fail))
            await asyncio.sleep(0.3)
            check(f"[{mode}] ... {label}: the failed turn's free daily turn is given back (only the session opening was charged: {u0} -> {u0 + OPEN})", await db.usage_today(srv_sub, day) == u0 + OPEN, (u0, await db.usage_today(srv_sub, day)))
    gate.reset_all()
    u0 = await db.usage_today(srv_sub, day)
    await drive(tok["srv"], "conversation", turns=1)
    await asyncio.sleep(0.4)
    check("a turn the AI DID answer is charged as before (the opening + one turn)", await db.usage_today(srv_sub, day) == u0 + OPEN + 1, (u0, await db.usage_today(srv_sub, day)))
    for k in BEHAVE:
        BEHAVE[k] = "down"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        gate.reset_all()
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["srv"], "name": "Ann", "hour": 11}))
        got = []
        for _ in range(4):
            try:
                got.append(json.loads(await asyncio.wait_for(ws.recv(), 10)))
            except Exception:
                break
    e = next((f for f in got if f["type"] in ("quota", "error")), None)
    check("the opening fails on DuSu's keys: an `error` frame, kp transient / own false / no key rows", e is not None and e["type"] == "error" and e["kp"]["state"] == "transient" and e["kp"]["own"] is False and e["kp"]["keys"] == [], got)
    check("... and kp.retry_in says when it is worth asking again (a passing failure: the short default)", isinstance(e["kp"].get("retry_in"), int) and 3 <= e["kp"]["retry_in"] <= 600, e["kp"])

    # the OWNER, when it is DuSu's own keys that failed, is told which of them is valid or invalid (and the provider's own reason) in the frame itself - nobody else is
    import time as _t
    _now = int(_t.time())
    M.keys_probe._server["keys"] = {"groq": {"status": "invalid", "why": "Invalid API Key", "checked_at": _now},
                                    "gemini": {"status": "forbidden", "why": "The Gemini API free tier is not available for this project. To use the Gemini API, please set up billing.", "checked_at": _now},
                                    "openrouter": {"status": "ok", "checked_at": _now}}
    for mode in ("conversation", "home", "daily"):
        gate.reset_all()
        frames, _first = await drive(tok["owner"], mode, fail_after_start="down")
        fail = last(frames, {"quota", "error", "home_error", "translate_error"})
        kp = (fail or {}).get("kp") or {}
        sv = kp.get("server") or {}
        check(f"[{mode}] the OWNER's frame about DuSu's own keys carries `server`: Groq invalid, Gemini forbidden (with Google's own words), OpenRouter ok",
              kp.get("own") is False and kp.get("keys") == [] and sv.get("groq", {}).get("status") == "invalid" and sv.get("gemini", {}).get("status") == "forbidden" and sv.get("openrouter", {}).get("status") == "ok"
              and "free tier is not available" in sv.get("gemini", {}).get("why", ""), kp)
        check(f"[{mode}] ... no key text in it", "SERVER" not in json.dumps(frames) and "gsk_" not in json.dumps(kp) and "AIza" not in json.dumps(kp))
        gate.reset_all()
        frames, _first = await drive(tok["srv"], mode, fail_after_start="down")
        fail = last(frames, {"quota", "error", "home_error", "translate_error"})
        kp = (fail or {}).get("kp") or {}
        check(f"[{mode}] an ordinary learner's frame about the same failure has NO `server` and names no provider", "server" not in kp and not any(n in json.dumps(frames).lower() for n in ("groq", "gemini", "openrouter")), kp)
    M.keys_probe._server["keys"] = {}

    # a failed Face-to-Face turn takes the unanswered line back
    for k in BEHAVE:
        BEHAVE[k] = "ok"
    gate.reset_all()
    LINE = "this line is said twice by mistake unless the server takes it back"
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        await ws.send(json.dumps({"type": "start", "mode": "conversation", "token": tok["srv"], "name": "Ann", "hour": 11}))
        while json.loads(await asyncio.wait_for(ws.recv(), 20)).get("type") not in ("ai_text", "error", "quota"):
            pass
        for k in BEHAVE:
            BEHAVE[k] = "down"
        await ws.send(json.dumps({"type": "user_text", "text": LINE}))
        while (m := json.loads(await asyncio.wait_for(ws.recv(), 30))).get("type") not in ("error", "ai_text", "quota"):
            pass
        failed_type = m["type"]
        for k in BEHAVE:
            BEHAVE[k] = "ok"
        gate.reset_all()
        await ws.send(json.dumps({"type": "user_text", "text": LINE}))
        while (m := json.loads(await asyncio.wait_for(ws.recv(), 30))).get("type") not in ("error", "ai_text", "quota"):
            pass
        said = [x for x in (WORLD.last_messages or []) if x.get("role") == "user" and x.get("content") == LINE]
        check("a failed turn is an `error` frame, and saying the SAME line again reaches the model exactly ONCE (the unanswered line was taken back)",
              failed_type == "error" and m["type"] == "ai_text" and len(said) == 1, (failed_type, m["type"], len(said)))
    M.settings.groq_api_key = M.settings.gemini_api_key = M.settings.openrouter_api_key = ""
    await db.set_setting("access_phase", "growth"); M.invalidate_access_cache()
    for k in BEHAVE:
        BEHAVE[k] = "ok"

    # ------------------------------------------------------------------------------------------ healthy sessions are identical
    section("a healthy session: engine ON == engine OFF, frame by frame")
    outs = {}
    for label, switch in (("on", "on"), ("off", "off")):
        await db.set_setting("key_health", switch); M.invalidate_access_cache()
        outs[label] = {}
        for mode in ("conversation", "daily", "learning", "home"):
            n = who[(mode, switch)] if False else (f"ab-{label}")
            frames, _ = await drive(tok[n], mode, turns=2, end=(mode != "home"))
            outs[label][mode] = [{k: v for k, v in f.items() if k not in ("kp",)} for f in frames if f.get("type") not in ("status", "quota_update", "speaker_progress", "plan")]
    for mode in ("conversation", "daily", "learning", "home"):
        check(f"[{mode}] the same frames, in the same order, with the same text", outs["on"][mode] == outs["off"][mode], (outs["on"][mode][:3], outs["off"][mode][:3]))
        check(f"[{mode}] ... and no frame of a healthy session carries kp", not any("kp" in json.dumps(f) for f in outs["on"][mode]))

    # ------------------------------------------------------------------------------------------ keys: none / fixed at start
    section("no keys at all; the chain is fixed at start")
    await db.set_setting("key_health", "on"); M.invalidate_access_cache()
    frames, first = await drive(tok["nokeys"], "conversation")
    check("a learner with no keys is told keys_required (never served from DuSu's own keys)", first == "keys_required" and frames[-1].get("msg"), frames)
    for k in BEHAVE:
        BEHAVE[k] = "ok"
    n = "fixed"
    new = {"groq": "gsk_NEWKEY" + "N" * 30, "gemini": "AIzaNEWKEY" + "N" * 30}

    async def swap():
        await db.save_user_keys(users[n]["sub"], new, verified=True)

    before = len(WORLD.calls)
    frames, _ = await drive(tok[n], "conversation", turns=2, mid=swap)
    used = {c[1] for c in WORLD.calls[before:] if c[2] == "chat"}
    check("keys replaced while a session is open: that session keeps the chain it started with (the new keys serve the NEXT session)", keys[n]["groq"] in used and new["groq"] not in used, used)
    before = len(WORLD.calls)
    await drive(tok[n], "conversation", turns=1)
    used = {c[1] for c in WORLD.calls[before:] if c[2] == "chat"}
    check("... and the next session uses the new stored keys", new["groq"] in used and keys[n]["groq"] not in used, used)

    # ------------------------------------------------------------------------------------------ the ledger saw the sessions
    section("the ledger counted the sessions' requests")
    await ledger.flush()
    from sqlalchemy import func, select
    from app.keys.models import KhUsage
    async with db._Session() as s:
        total = int((await s.execute(select(func.coalesce(func.sum(KhUsage.requests), 0)).where(KhUsage.user_id == "u-ab-on"))).scalar() or 0)
    sent_ab_on = len([c for c in WORLD.calls if c[2] == "chat" and c[1] == keys["ab-on"]["groq"]]) + len([c for c in WORLD.calls if c[2] == "chat" and c[1] == keys["ab-on"]["gemini"]])
    check("a learner with the engine on has one ledger request per model call that reached a provider", total == sent_ab_on and total > 0, (total, sent_ab_on))
    async with db._Session() as s:
        off_rows = int((await s.execute(select(func.count()).select_from(KhUsage).where(KhUsage.user_id == "u-ab-off"))).scalar() or 0)
    check("a learner with the engine OFF has no ledger rows at all", off_rows == 0, off_rows)

    server.should_exit = True
    await asyncio.sleep(0.5)
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
