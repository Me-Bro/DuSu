"""Grammar Coach - the WebSocket harness (none existed): drives the REAL /ws/interview handler (uvicorn in-process, auth ON) with a STUB chat model.

The decisive proof is the A/B: the same scripted session with the switch OFF and with it ON must leave every NON-grammar model call, every frame and
every non-gc database write identical - the only differences allowed are the additive `gref` / `grammar_ref` keys, the extra grammar call(s) and the
gc_* rows. Also: Back / Home / tab-hide (a dropped socket) still gets analysed; Hindi modes never do; a bad gref switches it off for that session.
Run via tests/grammar/run.sh ws_harness.py."""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/grammar")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402
from sqlalchemy import func, select                                  # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.grammar import service as svc, tracker                      # noqa: E402
from app.grammar.models import GcMark, GcSession                     # noqa: E402
from app.interview import engine as ienv                             # noqa: E402
from chat_stub import ChatStub                                       # noqa: E402
from stub_llm import StubLLM                                         # noqa: E402

FAILS: list = []
N = 0
PORT = 8765


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:400]}")


def section(t):
    print(f"\n== {t}")


CHAT = ChatStub()
GC = StubLLM()
tracker.llm = GC
M.llm = CHAT
ienv.llm = CHAT

TALK = ["yesterday i go to the market and i buy some vegetable", "i am engineer in a software company in pune",
        "we should discuss about the project tomorrow morning with the team", "my favourite food is dal and rice with some pickle",
        "he go to office every day by metro train", "informations about the new course were very useful for all of us"]


async def table_counts(uid):
    names = ("session_scores", "conversations", "weekly_stats")
    out = {}
    async with db._engine.connect() as conn:
        from sqlalchemy import text as t
        for n in names:
            try:
                out[n] = (await conn.execute(t(f"select count(*) from {n} where user_id=:u"), {"u": uid})).scalar()
            except Exception:
                out[n] = -1
        out["xp"] = (await conn.execute(t("select coalesce(speaker_xp,0) from progress where user_id=:u"), {"u": uid})).scalar()
    return out


async def drive(token, mode, texts, *, gref, end="end", name="Ann", extra=None):
    """Run one scripted session over a real websocket; returns the frames received."""
    frames = []

    async def until(ws, kinds, timeout=30):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            frames.append(m)
            if m.get("type") in kinds:
                return m

    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        start = {"type": "start", "mode": mode, "token": token, "keys": {"gemini": "stub-key"}, "name": name, "role": "developer", "hour": 11}
        start.update(extra or {})
        if gref is not None:
            start["gref"] = gref
        await ws.send(json.dumps(start))
        first = {"conversation": "ai_text", "interview": "ai_text", "daily": "daily_question", "learning": "ready", "practice": "ai_text"}[mode]
        await until(ws, {first, "error", "keys_required", "auth_error"})
        for t_ in texts:
            await ws.send(json.dumps({"type": "user_text", "text": t_}))
            await until(ws, {"ai_text", "daily_turn", "translation", "error", "quota", "limit"})
        if end == "end":
            await ws.send(json.dumps({"type": "end"}))
            await until(ws, {"ended", "report", "practice_report", "practice_error"}, 60)
            if mode == "interview":
                await asyncio.sleep(0.3)
    await asyncio.sleep(0.3)
    await tracker.drain(30)
    return frames


def strip(frames):
    out = []
    for f in frames:
        f = json.loads(json.dumps(f))
        f.pop("grammar_ref", None)
        if isinstance(f.get("data"), dict):
            f["data"].pop("grammar_ref", None)
        out.append(f)
    return out


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key), "refusing to run with provider keys configured (run through run.sh)"
    assert M.auth.auth_enabled, "auth must be ON for this harness (GOOGLE_CLIENT_ID is set by run.sh)"
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {k: {"sub": f"u-{k}", "email": f"{k}@example.com", "name": "Learner", "picture": ""} for k in ("off", "on", "drop", "hindi", "intv", "bad")}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
    T = {k: auth.make_session(u) for k, u in users.items()}
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)

    # ----------------------------------------------------------------------------- A/B: Face-to-Face
    section("A/B Face-to-Face: switch OFF vs ON")
    await db.set_setting("grammar_coach", "off")
    M.invalidate_access_cache()
    CHAT.log.clear(); GC.reset()
    c0 = await table_counts("u-off")
    f_off = await drive(T["off"], "conversation", TALK, gref="offsession0001")
    log_off = list(CHAT.log); d_off = {k: v - c0[k] for k, v in (await table_counts("u-off")).items()}
    check("switch OFF: no grammar model call, no gc row, no grammar_ref", GC.calls["total"] == 0 and not any("grammar_ref" in json.dumps(f) for f in f_off)
          and (await select_count(GcSession)) == 0)
    await db.set_setting("grammar_coach", "on")
    M.invalidate_access_cache()
    CHAT.log.clear(); GC.reset()
    c0 = await table_counts("u-on")
    f_on = await drive(T["on"], "conversation", TALK, gref="onsession00001")
    log_on = list(CHAT.log); d_on = {k: v - c0[k] for k, v in (await table_counts("u-on")).items()}
    check("switch ON: every non-grammar model call is identical to OFF (system prompts, transcripts)", log_off == log_on, [(a[0], [(i, a[1][max(0,i-40):i+60], b[1][max(0,i-40):i+60]) for i in range(min(len(a[1]), len(b[1]))) if a[1][i] != b[1][i]][:1]) for a, b in zip(log_off, log_on) if a != b][:2] or (len(log_off), len(log_on)))
    check("switch ON: every frame is identical to OFF once the additive grammar_ref is removed", strip(f_off) == strip(f_on) or [x for x in zip(strip(f_off), strip(f_on)) if x[0] != x[1]][:1])
    check("switch ON: the non-gc database writes are identical (scores, conversations, XP)", d_off == d_on, (d_off, d_on))
    sp = next((f for f in f_on if f.get("type") == "speaker_progress"), None)
    check("switch ON: speaker_progress carries grammar_ref ws:<gref> and arrives BEFORE ended", sp is not None and sp["data"].get("grammar_ref") == "ws:onsession00001"
          and [f["type"] for f in f_on].index("speaker_progress") < [f["type"] for f in f_on].index("ended"))
    check("switch ON: exactly ONE grammar model call for the 6-sentence session", GC.calls["total"] == 1, dict(GC.calls))
    r = await svc.by_ref("u-on", "ws:onsession00001")
    check("switch ON: the analysis finished and is stored for that learner", r["state"] in ("done", "partial") and r["report"]["checked"] == 5, r.get("state"))
    check("no grammar_ref anywhere in the OFF frames", not any("grammar_ref" in json.dumps(f) for f in f_off))

    # ----------------------------------------------------------------------------- dropped socket (Back / Home / tab hide)
    section("a dropped socket still gets analysed")
    GC.reset()
    await drive(T["drop"], "conversation", TALK, gref="dropsession001", end="drop")
    r = await svc.by_ref("u-drop", "ws:dropsession001")
    check("closing the socket without End (Back / Home / tab hide) still produces the Grammar report", r["state"] in ("done", "partial"), r)

    # ----------------------------------------------------------------------------- interview
    section("Interview Prep")
    GC.reset()
    f_i = await drive(T["intv"], "interview", TALK[:5], gref="intvsession001")
    rep = next((f for f in f_i if f.get("type") == "report"), None)
    check("the interview report frame carries grammar_ref and the report's own grammar bar is untouched", rep is not None and rep["data"].get("grammar_ref") == "ws:intvsession001" and rep["data"]["scores"]["grammar"] == 61, rep and rep["data"])
    r = await svc.by_ref("u-intv", "ws:intvsession001")
    check("the interview's Grammar session exists", r["state"] in ("done", "partial") and r["report"]["source"] == "interview", r.get("state"))

    # ----------------------------------------------------------------------------- Practice conversations (viva): English is analysed, Hindi never
    section("Practice conversations")
    async def fake_talk(llm_, *, kind, topic, lang, feedback_lang, level, turns, rounds, seconds):
        return {"kind": kind, "lang": lang, "feedback_lang": feedback_lang or "hinglish", "level": level or "intermediate", "seconds": 120, "words": 90, "overall": 70,
                "categories": [{"key": "content", "score": 70}], "genuine_effort": True, "talk": {"answered": 3}, "too_short": False}
    real_talk = M.practice_talk.analyze_talk
    M.practice_talk.analyze_talk = fake_talk
    await db.set_setting("practice_room", "on"); M.invalidate_access_cache()
    try:
        GC.reset()
        px = {"kind": "viva", "topic": "machine learning basics", "plang": "en", "level": "intermediate", "rounds": 4, "feedback_lang": "hinglish"}
        f_p = await drive(T["on"], "practice", TALK[:4], gref="pracsession001", extra=px)
        pr = next((f for f in f_p if f.get("type") == "practice_report"), None)
        gref_out = (pr or {}).get("data", {}).get("grammar_ref", "")
        check("a viva in English: the report carries grammar_ref pa:<attempt id>", gref_out.startswith("pa:"), gref_out)
        r = await svc.by_ref("u-on", gref_out) if gref_out else {"state": "none"}
        check("...and the Grammar session exists, source practice", r["state"] in ("done", "partial") and r["report"]["source"] == "practice", r.get("state"))
        GC.reset()
        n_hi = await select_count(GcSession)
        px_hi = dict(px, plang="hi")
        f_h = await drive(T["on"], "practice", TALK[:4], gref="pracsession002", extra=px_hi)
        check("a viva in HINDI is never analysed: no grammar_ref, no model call, no row", not any("grammar_ref" in json.dumps(f) for f in f_h) and GC.calls["total"] == 0 and (await select_count(GcSession)) == n_hi)
    finally:
        M.practice_talk.analyze_talk = real_talk

    # ----------------------------------------------------------------------------- Hindi modes and a bad gref
    section("Hindi modes never; a bad gref switches it off")
    GC.reset()
    n0 = await select_count(GcSession)
    await drive(T["hindi"], "daily", ["aaj main office gaya aur kaam kiya bahut thak gaya", "kal main market jaunga"], gref="hindisession01")
    await drive(T["hindi"], "learning", ["mujhe kal market jana hai"], gref="hindisession02")
    check("Daily Talk and Learn (Hindi) create no Grammar Coach row and no call", await select_count(GcSession) == n0 and GC.calls["total"] == 0, dict(GC.calls))
    f_bad = await drive(T["bad"], "conversation", TALK[:3], gref="x")
    check("a malformed gref -> no grammar_ref, no analysis", not any("grammar_ref" in json.dumps(f) for f in f_bad) and GC.calls["total"] == 0)
    f_none = await drive(T["bad"], "conversation", TALK[:3], gref=None)
    check("a client that sends no gref (an old cached client) behaves exactly as before", not any("grammar_ref" in json.dumps(f) for f in f_none) and GC.calls["total"] == 0)

    server.should_exit = True
    await task
    print(f"\ngrammar ws_harness: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1 if FAILS else 0)


async def select_count(model):
    async with db._Session() as s:
        n = (await s.execute(select(func.count()).select_from(model))).scalar()
        await s.commit()
    return n


asyncio.run(main())
