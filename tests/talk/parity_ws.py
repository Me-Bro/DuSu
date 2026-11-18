"""Talk - "old = old", the recording half: drive the REAL /ws/interview handler with a recording stub model through one scripted scenario per pre-existing mode and write EVERYTHING that happened
(every frame the client received, every model call with its full input, the database effects, `/me`) to tests/talk/.out/parity_<label>.json.  parity_compare.py then proves the three runs equal:
  old      = the code before Talk (tests/.baselines/lab-done/backend)
  new_off  = the working tree with the `talk_v3` switch OFF
  new_on   = the working tree with the `talk_v3` switch ON for everyone
Run through tests/talk/run.sh with TALK_ENV="TALK_LABEL=<label> TALK_SWITCH=off|on|none"  (see parity.sh).  This file imports nothing from the Talk package, so it runs on the old code too."""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, "/app")

import httpx                                                         # noqa: E402
import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402
from app.store import func, select                                  # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.interview import engine as ienv                             # noqa: E402

LABEL = os.environ.get("TALK_LABEL", "x")
SWITCH = os.environ.get("TALK_SWITCH", "none")           # off | on | none (the old code has no such setting)
OUT = "/tests/talk/.out"
PORT = 8793


class Rec:
    """A recording stub of `llm`: deterministic answers, EVERY argument kept (callables by name)."""
    def __init__(self):
        self.log: list = []

    def v3_active(self):
        return False

    def last_bad(self):
        return None

    @staticmethod
    def _scrub(v):
        # the Home prompt carries the wall clock ("RIGHT NOW (...): Tuesday, 17 November 2026, 1:12 PM"): a run that crosses a minute would differ for no reason
        return re.sub(r"(RIGHT NOW \(the learner's own clock[^)]*\):)[^\n]*", r"\1 <clock>", v) if isinstance(v, str) else v

    def _rec(self, kind, **kw):
        self.log.append({"kind": kind, **{k: (self._scrub(v) if isinstance(v, (str, int, float, bool, type(None), list, dict)) else getattr(v, "__name__", str(type(v).__name__))) for k, v in kw.items()}})

    async def next_question(self, system, transcript, seed=None):
        self._rec("next_question", system=system, transcript=transcript, seed=seed)
        return "That sounds interesting - tell me a little more about it, what happened next, and how did you feel about it?"

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7, first=None, cool=True, schema=None, check=None):
        self._rec("assess", system=system, payload=payload, max_tokens=max_tokens, prefer_fast=prefer_fast, temperature=temperature, first=first, cool=cool, schema=schema, check=check)
        return {"summary": "Practised speaking.", "facts": {}, "events": [], "no_hindi": True, "asked_question": False, "next_hook": "continue", "recent_questions": [],
                "scores": {"confidence": 60, "continuity": 60, "vocabulary": 60, "grammar_trend": 60, "depth": 60}, "genuine_effort": True,
                "english": "I went to the market", "reply_hindi": "namaste, aaj ka din kaisa raha aapka, mujhe batao zara dhyan se", "next_question_hindi": "aaj kya kiya?", "tip": "", "mood": "ok",
                "context": {}, "reply": "Nice to hear that, tell me more about your day please.", "intent": "general_conversation", "suggest": [], "overall": 70, "scores_ok": True}

    async def score(self, system, transcript, max_tokens=1200):
        self._rec("score", system=system, transcript=transcript, max_tokens=max_tokens)
        return {"overall": 70, "scores": {"grammar": 61, "fluency": 70, "confidence": 70, "communication": 70, "vocabulary": 70, "professionalism": 70},
                "filler_words": [], "strengths": ["clear"], "fixes": ["add examples"], "better_answer": {"question": "q", "their_answer": "a", "improved": "b"}}

    async def translate(self, system, text, max_tokens=120):
        self._rec("translate", system=system, text=text, max_tokens=max_tokens)
        return "I went to the market yesterday."

    async def generate(self, system, prompt, max_tokens=500):
        self._rec("generate", system=system, prompt=prompt, max_tokens=max_tokens)
        return "ok"


REC = Rec()
M.llm = REC
ienv.llm = REC


async def drive(token, start, texts, end=True, until_first=("ai_text", "daily_question", "ready", "home_ready", "session_resumed", "daily_resumed", "error", "keys_required", "auth_error")):
    frames: list = []

    async def until(ws, kinds, timeout=30):
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            except (websockets.ConnectionClosed, asyncio.TimeoutError):
                return None
            frames.append(m)
            if m.get("type") in kinds:
                return m

    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview") as ws:
        await ws.send(json.dumps({"token": token, "keys": {"gemini": "stub-key"}, "name": "Ann", "role": "developer", "hour": 11, "tzmin": 330, **start}))
        first = await until(ws, set(until_first))
        if first is not None and first.get("type") not in ("error", "keys_required", "auth_error"):
            for t_ in texts:
                await ws.send(json.dumps({"type": "user_text", "text": t_}))
                if await until(ws, {"ai_text", "daily_turn", "translation", "home_turn", "error", "quota", "limit", "translate_error", "home_error", "practice_done"}) is None:
                    break
            if end:
                await ws.send(json.dumps({"type": "end"}))
                await until(ws, {"ended", "report", "practice_report", "practice_error"}, 60)
                await until(ws, set(), 2.0)          # keep reading until the server has gone quiet (an interview's speaker_progress comes AFTER its report: closing earlier would cut the end-of-session work short)
    await asyncio.sleep(0.4)
    return frames


async def settled(uid):
    """The database effects once the handler has finished its end-of-session work (it runs AFTER the client has its last frame): read until two reads 0.8 s apart agree."""
    prev = await effects(uid)
    for _ in range(12):
        await asyncio.sleep(0.8)
        cur = await effects(uid)
        if cur == prev:
            return cur
        prev = cur
    return prev


async def effects(uid):
    out = {}
    async with db._Session() as s:
        for n, M_ in (("session_scores", db.SessionScore), ("conversations", db.Conversation), ("weekly_stats", db.WeeklyStat)):
            out[n] = int((await s.execute(select(func.count()).select_from(M_).where(M_.user_id == uid))).scalar() or 0)
        rows = (await s.execute(select(db.Conversation.mode).where(db.Conversation.user_id == uid))).scalars().all()
        out["conversation_modes"] = sorted(rows)
        p = await s.get(db.Progress, uid)
        out["xp"] = ((p.speaker_xp or 0) if p is not None else None)
        out["badges"] = sorted(p.badges or []) if p is not None else None
        await s.commit()
    mem = await db.get_memory(uid)
    out["memory_keys"] = sorted(mem)
    out["recent_turn_modes"] = sorted({t.get("mode") for t in mem.get("recent_turns", [])})
    return out


REPLAY = [{"role": "assistant", "content": "Hi, nice to meet you. What do you do?"}, {"role": "user", "content": "I am a purple elephant trainer"}, {"role": "assistant", "content": "That sounds fun! Tell me more."}]
DAILY_REPLAY = [{"role": "assistant", "content": "Aaj ka din kaisa raha?"}, {"role": "user", "content": "theek raha"}]
SCENARIOS = [
    ("conversation", {"type": "start", "mode": "conversation", "mood": "good"}, ["yesterday i go to the market", "it was fine and I bought some fruit"], True),
    ("conversation_seed", {"type": "start", "mode": "conversation", "seed": "I want to talk about cricket", "mood": "great"}, ["i like batting the most"], True),
    ("conversation_reconnect", {"type": "start", "mode": "conversation", "reconnect": True, "resume": REPLAY}, ["i train them every morning"], True),
    ("interview", {"type": "start", "mode": "interview", "role": "Data Analyst"}, ["I have two years of experience with SQL", "my biggest strength is learning fast"], True),
    ("daily", {"type": "start", "mode": "daily", "mood": "ok"}, ["aaj mera din accha tha", "maine market se fruit khareede"], True),
    ("daily_reconnect", {"type": "start", "mode": "daily", "reconnect": True, "resume": DAILY_REPLAY}, ["phir maine chai pi"], True),
    ("learning", {"type": "start", "mode": "learning"}, ["mujhe kal market jaana hai"], True),
    ("home", {"type": "start", "mode": "home", "opening": "Good evening! How was your day?", "lang": "hi", "plan": False}, ["what time is it", "I want to practice speaking"], True),
    ("practice_viva", {"type": "start", "mode": "practice", "kind": "viva", "topic": "Operating systems", "plang": "en", "level": "intermediate", "rounds": 3, "feedback_lang": "en"},
     ["An operating system manages hardware and software resources of a computer", "A process is a running program with its own memory space and state", "Scheduling decides which process gets the processor next"], True),
    ("unknown_mode", {"type": "start", "mode": "notamode"}, ["hello there"], True),
    ("end_without_turns", {"type": "start", "mode": "conversation"}, [], True),
    # NOT part of the old = old comparison (the old code has no `talk` mode and silently turns it into an interview); recorded so parity_compare can assert the expected difference
    ("talk_start", {"type": "start", "mode": "talk", "topic_id": "a1-my-family", "support": "en_sub"}, ["hello there"], True),
]


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    try:                                   # the new tree only: a fixed small bank, so the `talk` scenario does not depend on what has been authored so far
        sys.path.insert(0, "/tests/talk")
        import fixtures as F
        from app.talk import topics as T
        T.use(T.Bank.from_rows(F.all_rows(9)))
    except ImportError:
        pass
    for k, v in (("home_ai", "on"), ("practice_room", "on"), ("grammar_coach", "off")):
        await db.set_setting(k, v)
    if SWITCH in ("on", "off"):
        await db.set_setting("talk_v3", SWITCH)
    M.invalidate_access_cache()
    users = {name: {"sub": f"u-{name}", "email": f"{name}@example.com", "name": "Learner", "picture": ""} for name, *_ in SCENARIOS}
    users["me"] = {"sub": "u-me", "email": "me@example.com", "name": "Learner", "picture": ""}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
    tok = {k: auth.make_session(u) for k, u in users.items()}
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    result: dict = {"label": LABEL, "switch": SWITCH, "scenarios": {}}
    for name, start, texts, end in SCENARIOS:
        REC.log.clear()
        frames = await drive(tok[name], start, texts, end)
        result["scenarios"][name] = {"frames": frames, "model_calls": list(REC.log), "effects": await settled(users[name]["sub"])}
        print(f"  recorded {name}: {len(frames)} frames, {len(REC.log)} model calls")
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=30) as c:
        r = await c.get("/me", headers={"Authorization": "Bearer " + tok["me"]})
        result["me"] = r.json()
        result["me_status"] = r.status_code
        r = await c.get("/home/features?lang=en", headers={"Authorization": "Bearer " + tok["me"]})
        result["home_features"] = r.json()
    server.should_exit = True
    await task
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/parity_{LABEL}.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, sort_keys=True, indent=1, default=str)
    print(f"wrote {OUT}/parity_{LABEL}.json")


asyncio.run(main())
