"""Audit - the REAL app (uvicorn + a scratch Postgres) for a product / UI review. NOT a test: nothing asserts here, it only makes the app look and behave the way a learner meets it.

  * the rollout switches are set the way PRODUCTION has them (read 2026-10-30): bilingual / grammar_coach / home_ai / key_health / keys_ui / life_context / planner /
    practice_room / resume_interview ON, level_test OFF, install_mode + notifications unset (= off), access_phase unset (= growth: everyone brings their own keys);
    POST /__audit/settings flips any of them (the "features about to go live" pass turns install_mode / notifications on);
  * learners in the states a screen has to show: `newbie` (a brand-new Google account - nothing at all), `keyed` (keys saved, never practised), `active` (a month of practice:
    streak, lessons, badges, vocabulary, conversations, league standing), `lapsed` (streak broken a week ago), `owner`, and nine league rivals;
  * a fake model that answers each KIND of prompt in the shape the real one is meant to (Home JSON, Daily JSON, an interviewer's questions, a scored report, a translation ...),
    so every screen is drawn with believable content; the fake keys are accepted by the fake providers (there is no network route out of the scratch network);
  * the page is gzip-compressed like Cloudflare does in production, so a throttled load measures what a phone would download.

Started by tests/audit/up.sh - never run against production.
"""

import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                      # noqa: E402
from fastapi import Request                                         # noqa: E402
from sqlalchemy import update                                       # noqa: E402
from sqlalchemy.orm.attributes import flag_modified                 # noqa: E402
from starlette.middleware.gzip import GZipMiddleware                # noqa: E402

from world import World, install, ok                                # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.keys import gate                                           # noqa: E402
from app.interview import prompts as P                              # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
    "provider keys must be blank (run through up.sh)"

PRODUCTION_SWITCHES = {"bilingual": "on", "grammar_coach": "on", "home_ai": "on", "key_health": "on", "keys_ui": "on", "level_test": "off", "life_context": "on", "planner": "on",
                       "practice_room": "on", "resume_interview": "on"}


# ---------------------------------------------------------------------------------------------- the fake model
INTERVIEW_QS = ["Thanks for joining. Please tell me a little about yourself.", "Why are you interested in this role?", "Tell me about a project you are proud of and what you did in it.",
                "What would you say is your biggest strength, and can you give an example?", "Describe a time something went wrong and how you handled it.",
                "Where do you see yourself in three years?"]
CONV = ["That sounds interesting! What made you choose that?", "Nice. And how did that make you feel?", "I see. Can you tell me more about your day?",
        "Great answer. What is something you are looking forward to this week?"]
SCORER = {"overall": 71, "scores": {"grammar": 68, "fluency": 66, "confidence": 74, "communication": 72, "vocabulary": 65, "professionalism": 80}, "filler_words": ["um", "like", "basically"],
          "strengths": ["You introduced yourself clearly and calmly.", "You gave a real example from your college project."],
          "fixes": ["Add one number to each example (how many users, how much time saved).", "Slow down on your key point - pause, then say it."],
          "better_answer": {"question": "Tell me about yourself.", "their_answer": "I am student and I like computer very much.",
                            "improved": "I'm a final-year computer science student. I enjoy building small web apps - last semester I built a timetable app that 200 classmates use."}}
MEMORY = {"summary": "They practised speaking about their day and a college project.", "facts": {"profession": "student", "dream": "a software job", "interests": {"cricket": True},
          "notes": ["has a project demo next week"], "moments": [{"text": "project demo next week", "emotion": "nervous"}], "achievements": [], "relationship": {}},
          "events": [], "no_hindi": True, "asked_question": True, "next_hook": "Tell me how the project demo went."}
HOME = {"reply": "बहुत अच्छा! आज तुमने English में क्या practice किया?", "intent": "general_conversation", "suggest": []}
DAILY = {"english": "I went to the market today.", "reply_hindi": "Waah, market mein kya kharida? Mujhe bhi batao.", "next_question_hindi": "Aur kal ka kya plan hai?",
         "tip": "Say 'I went to the market', not 'I am going market'.", "mood": "good", "context": {"plans": "market", "weather": "", "events": []}}
ASSESS = {"level": "A2", "scores": {"confidence": 55, "pronunciation": 60, "listening": 65, "vocabulary": 50, "grammar": 48, "thinking": 52}, "weak_areas": ["grammar", "vocabulary"],
          "message": "You speak with courage - that is the hardest part. Let us work on grammar and vocabulary next."}
GEN = {"repeat": "I would like to book a table for two.", "think_hindi": "Mujhe kal subah doctor ke paas jaana hai.", "open": "Tell me about a person who inspires you."}
LESSON = {"pass": True, "correct_english": "My name is Rahul.", "feedback": "Great job - clear and confident.", "encouragement": "Keep going!"}
LEVELTEST = {"score": 82, "passed": True, "items": [{"pass": True, "feedback": "Good"}], "message": "Well done - you passed this level."}


class Audit(World):
    def __init__(self):
        super().__init__()
        self.chat_done = False
        self.chat_reply = self.reply

    def reply(self, messages, provider, key):
        msgs = messages or []
        sys_ = str((msgs[0] if msgs else {}).get("content", ""))
        last = str((msgs[-1] if msgs else {}).get("content", ""))
        users = sum(1 for m in msgs if m.get("role") == "user")
        wants_json = last.endswith("Return ONLY the JSON object.")
        if sys_ == P.DAILY_TURN_SYSTEM:
            return ok(json.dumps(DAILY, ensure_ascii=False))
        if sys_ == P.SESSION_MEMORY_SYSTEM:
            return ok(json.dumps(MEMORY))
        if sys_ == P.SCORER_SYSTEM:
            return ok(json.dumps(SCORER))
        if sys_ == P.ASSESS_SYSTEM:
            return ok(json.dumps(ASSESS))
        if sys_ == P.LESSON_EVAL_SYSTEM:
            return ok(json.dumps(LESSON))
        if sys_ == P.LEVEL_TEST_SYSTEM:
            return ok(json.dumps(LEVELTEST))
        if sys_ == P.TRANSLATE_SYSTEM:
            return ok("I will go to the market tomorrow morning.")
        if sys_ == P.GREETING_SYSTEM:
            return ok("Good morning Asha! आज का दिन कैसा शुरू हुआ? Kal tumne project demo ke baare mein bataya tha - kaisa raha?")
        if sys_ == P.LETTER_SYSTEM:
            return ok("Hi Asha,\n\nThis week you spoke on four days and your answers are getting longer. That is real progress. Keep your project story ready - one number, one result.\n\n- DuSu")
        if '"suggest": ["<id>"' in sys_ and wants_json:
            return ok(json.dumps(HOME, ensure_ascii=False))
        if "INTERVIEW_COMPLETE" in sys_ and "mock" in sys_.lower():
            if self.chat_done or users > len(INTERVIEW_QS):
                return ok("INTERVIEW_COMPLETE: Thank you - that was a thoughtful conversation. You did well.")
            return ok(INTERVIEW_QS[min(users, len(INTERVIEW_QS) - 1)])
        if "INTERVIEW_COMPLETE" in sys_:
            return ok(INTERVIEW_QS[min(users, len(INTERVIEW_QS) - 1)])
        if wants_json:
            return ok("{}")
        return ok(CONV[users % len(CONV)])


WORLD = Audit()
install(WORLD)
M.app.add_middleware(GZipMiddleware, minimum_size=500)               # Cloudflare compresses the page in production


# ---------------------------------------------------------------------------------------------- learners
RIVALS = ["Rohan", "Priya", "Aman", "Sneha", "Vikram", "Anjali", "Karan", "Divya", "Imran"]
KEYS = lambda n: {"groq": f"gsk_{n}" + "G" * 28 + "9fA2", "gemini": f"AIza{n}" + "M" * 28 + "Xy71", "openrouter": f"sk-or-v1-{n}" + "O" * 28 + "Q7xP"}      # noqa: E731
SCORES = lambda k: {"confidence": 60 + k, "continuity": 55 + k, "vocabulary": 50 + k, "grammar_trend": 52 + k, "depth": 48 + k}                            # noqa: E731


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    names = {"newbie": "Neha Verma", "keyed": "Kabir Shah", "active": "Asha Kumari", "lapsed": "Laxman Yadav"}
    users = {k: {"sub": f"aud-{k}", "email": f"{k}@example.com", "name": v, "picture": ""} for k, v in names.items()}
    users["owner"] = {"sub": "aud-owner", "email": "david123rana@gmail.com", "name": "David Rana", "picture": ""}
    for i, n in enumerate(RIVALS, 1):
        users[f"r{i}"] = {"sub": f"aud-r{i}", "email": f"r{i}@example.com", "name": f"{n} Learner", "picture": ""}
    for u in users.values():
        await db.login(u)
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()

    # --- learners with keys already saved the way the app saves them (sealed)
    keys = {}
    for who in ("keyed", "active", "lapsed", "owner") + tuple(f"r{i}" for i in range(1, 10)):
        keys[who] = KEYS(who)
        await db.save_user_keys(users[who]["sub"], {p: keys[who][p] for p in ("groq", "gemini")}, verified=True)

    # --- assessed learners (the level check is OFF in production: a new account is seeded a default profile by /me; these skip even that)
    for who in ("active", "lapsed", "owner") + tuple(f"r{i}" for i in range(1, 10)):
        await db.save_assessment(users[who]["sub"], {"goal": "job", "comfort": "ok", "practice_time": "20", "level": "A2",
                                                      "scores": {"confidence": 55, "pronunciation": 60, "listening": 65, "vocabulary": 50, "grammar": 48, "thinking": 52},
                                                      "weak_areas": ["grammar", "vocabulary"]})

    # --- the active learner: a month of practice
    uid = users["active"]["sub"]
    await db.save_about(uid, {"nickname": "Asha", "native_lang": "hi", "profession": "Final-year student", "dream": "A software engineer job",
                              "interests": {"cricket": True, "movies": True}})
    for lid in ("l1_1", "l1_2", "l1_3", "l1_4", "l1_5"):
        await db.complete_lesson(uid, 1, lid, "think")
    await db.submit_level_test(uid, 1, 84)
    for lid in ("l2_1", "l2_2", "l2_3"):
        await db.complete_lesson(uid, 2, lid, "speak")
    for mode, mins, k in (("daily", 6, 8), ("conversation", 9, 12), ("interview", 12, 6), ("daily", 5, 14), ("conversation", 11, 10)):
        await db.award_speaker_progress(uid, mode, mins, 10, SCORES(k), True)
    await db.award_badges(uid, ["first_lesson", "first_converse", "streak_3", "courage_first_convo", "level_up", "courage_no_hindi"])
    await db.add_vocab(uid, ["confident", "deadline", "responsibility", "improve", "schedule", "opportunity", "experience", "challenge", "colleague", "achieve"] * 1)
    for mode, text in (("daily", "She talked about her day and a college project demo."), ("conversation", "They practised introducing themselves."),
                       ("interview", "A mock HR interview: strong opening, needs numbers in examples."), ("daily", "She planned her weekend and talked about cricket."),
                       ("conversation", "They discussed a movie and practised past tense.")):
        await db.add_conversation(uid, mode, text)
    await db.save_checkin(uid, "good")
    await db.save_future_me(uid, "In one month I will answer interview questions without fear.")
    await db.save_letter(uid, "Hi Asha,\n\nThis week you spoke on four days and your answers are getting longer. Keep going.\n\n- DuSu")
    async with db._Session() as s:
        mem = await db._get_or_make_memory(s, uid)
        facts = dict(mem.facts or {})
        facts["daily_stats"] = {str(today - dt.timedelta(days=d)): {"sentences": 8 + (d * 3) % 9, "seconds": 300 + (d * 97) % 500, "sessions": 1 + d % 2, "new_words": d % 4}
                                for d in range(0, 10) if d not in (3, 7)}
        facts["total_sentences"] = 212
        facts["total_seconds"] = 5400
        mem.facts = facts
        flag_modified(mem, "facts")
        await s.commit()
    async with db._Session() as s:
        await s.execute(update(db.Progress).where(db.Progress.user_id == uid).values(xp=460, coins=120, streak_days=6, longest_streak_days=9, last_active=today - dt.timedelta(days=1)))
        await s.commit()

    # --- the lapsed learner: practised, then stopped a week ago
    lid_ = users["lapsed"]["sub"]
    for lesson in ("l1_1", "l1_2"):
        await db.complete_lesson(lid_, 1, lesson, "think")
    await db.award_speaker_progress(lid_, "conversation", 8, 8, SCORES(2), True)
    async with db._Session() as s:
        await s.execute(update(db.Progress).where(db.Progress.user_id == lid_).values(streak_days=4, last_active=today - dt.timedelta(days=8)))
        await s.commit()

    # --- the league: nine rivals with different amounts of practice, and the owner with a little
    for i in range(1, 10):
        r = users[f"r{i}"]["sub"]
        for _ in range(1 + i % 3):
            await db.award_speaker_progress(r, "conversation", 2 + i * 2, 9, SCORES(i), True)
    await db.award_speaker_progress(users["owner"]["sub"], "daily", 6, 7, SCORES(9), True)

    # --- DuSu's OWN chain (the owner rides it): fake keys, so the owner's chats work
    M.settings.groq_api_key = "gsk_SERVER" + "q" * 30
    M.settings.gemini_api_key = "AIzaSERVER" + "q" * 30
    M.settings.openrouter_api_key = "sk-or-v1-SERVER" + "q" * 30
    gate.reset_all()

    for k, v in PRODUCTION_SWITCHES.items():
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    os.makedirs("/tests/audit/.out", exist_ok=True)
    out = {k: {"token": auth.make_session(u), "user": u, "keys": keys.get(k)} for k, u in users.items()}
    json.dump(out, open("/tests/audit/.out/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


# ---------------------------------------------------------------------------------------------- control routes (test process only)
@M.app.post("/__audit/settings")
async def audit_settings(request: Request):
    b = await request.json()
    for k, v in (b.get("settings") or {}).items():
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    return {"ok": True}


@M.app.post("/__audit/reset")                                        # empty some tables so a spec can run twice on the same app (an allow-list: never a free-form table name)
async def audit_reset(request: Request):
    from sqlalchemy import text as _sql
    allowed = {"plan_interest", "ev_milestones", "ev_days"}
    tabs = [t for t in ((await request.json()).get("tables") or []) if t in allowed]
    async with db._Session() as s:
        for t in tabs:
            await s.execute(_sql(f"DELETE FROM {t}"))
        await s.commit()
    M.insights._seen.clear()
    M.insights._day_seen.clear()
    return {"ok": True, "cleared": tabs}


@M.app.post("/__audit/reset_learner")                                # a learner back to "never practised" (a spec can then be run twice on the same app)
async def audit_reset_learner(request: Request):
    from sqlalchemy import delete as _del
    who = (await request.json()).get("who", "")
    uid = f"aud-{who}"
    async with db._Session() as s:
        for tbl in (db.SessionScore, db.Conversation, db.WeeklyStat, db.UsageDaily):
            await s.execute(_del(tbl).where(tbl.user_id == uid))
        await s.execute(update(db.Progress).where(db.Progress.user_id == uid).values(xp=0, coins=0, streak_days=0, longest_streak_days=0, last_active=None, speaker_xp=0, speaker_rank="starter", journey={}, badges=[]))
        mem = await db._get_or_make_memory(s, uid)
        mem.facts = {}
        flag_modified(mem, "facts")
        await s.commit()
    return {"ok": True, "who": who}


@M.app.post("/__audit/hook")                                         # set (or clear) a learner's "continue next time" promise
async def audit_hook(request: Request):
    b = await request.json()
    await db.set_next_hook(f"aud-{b.get('who', '')}", b.get("hook", ""))
    return {"ok": True}


@M.app.post("/__audit/facts")                                        # merge memory facts / profile fields for a learner (the XSS canary plants hostile text with it)
async def audit_facts(request: Request):
    b = await request.json()
    uid = f"aud-{b.get('who', '')}"
    async with db._Session() as s:
        mem = await db._get_or_make_memory(s, uid)
        f = dict(mem.facts or {})
        f.update(b.get("facts") or {})
        mem.facts = f
        flag_modified(mem, "facts")
        if b.get("profile"):
            await s.execute(update(db.Profile).where(db.Profile.user_id == uid).values(**b["profile"]))
        if b.get("progress"):                                        # e.g. {"speaker_xp": 120}: a learner whose Journey XP is still 0
            await s.execute(update(db.Progress).where(db.Progress.user_id == uid).values(**b["progress"]))
        await s.commit()
    return {"ok": True}


_SAFE = {"s": list(SCORER["strengths"]), "f": list(SCORER["fixes"]), "m": LEVELTEST["message"], "fb": LEVELTEST["items"][0]["feedback"]}


@M.app.post("/__audit/hostile")                                      # the fake model starts (or stops) answering with markup: the XSS canary's model-written text
async def audit_hostile(request: Request):
    on = bool((await request.json()).get("on"))
    bad = '<img src=x onerror="window.__xss=(window.__xss||0)+1">'
    SCORER["strengths"] = [bad, "<svg onload=\"window.__xss=(window.__xss||0)+1\">"] if on else list(_SAFE["s"])
    SCORER["fixes"] = [bad] if on else list(_SAFE["f"])
    LEVELTEST["message"] = bad if on else _SAFE["m"]
    LEVELTEST["items"][0]["feedback"] = bad if on else _SAFE["fb"]
    return {"ok": True, "on": on}


@M.app.post("/__audit/chatdone")                                     # the next interviewer reply is the closing line
async def audit_chatdone(request: Request):
    WORLD.chat_done = bool((await request.json()).get("on"))
    return {"ok": True}


@M.app.post("/__audit/health")                                       # what the server says about itself (the page may use it)
async def audit_health():
    return {"ok": True}


asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
