"""Golden master for app/db.py. ONE deterministic scenario over (nearly) every public db.* function, with a fake clock, run on whichever tree is mounted at /app:
the OLD tree on Postgres, the NEW tree on Mongo. The outputs - every return value AND the final contents of every table - must be identical (golden.sh diffs them).

  GOLDEN_OUT=<file>   where to write the JSON            GOLDEN_PHASE=core|full   (full adds the cross-module cascades: delete_user / admin_wipe_users / pruning)
Needs PYTHONHASHSEED=0 (a set becomes a list in a few places; both runs must order it the same way).
"""

import asyncio
import datetime
import decimal
import json
import os
import sys
import types

sys.path.insert(0, "/app")

from app import db                                                           # noqa: E402

PHASE = os.environ.get("GOLDEN_PHASE", "core")
OUT = os.environ["GOLDEN_OUT"]
if PHASE == "full":                                                          # the cascades reach into every feature: register all their models BEFORE init_db() creates the tables (both trees)
    import app.planner.models, app.resume_interview.models, app.grammar.models, app.notify.models, app.keys.models, app.insights.models   # noqa: E401,F401
UTC = datetime.timezone.utc

# ---------------------------------------------------------------- the clock: db.py reads time only through its module-level `dt`
CLOCK = [datetime.datetime(2026, 3, 2, 4, 30, 0, tzinfo=UTC)]               # Monday 2026-03-02 10:00 in India


class FakeDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        c = CLOCK[0]
        return c.astimezone(tz) if tz is not None else c.replace(tzinfo=None)


_shim = types.SimpleNamespace(**{k: getattr(datetime, k) for k in ("date", "time", "timedelta", "timezone", "tzinfo", "UTC", "MINYEAR", "MAXYEAR") if hasattr(datetime, k)})
_shim.datetime = FakeDT
db.dt = _shim


def tick(**kw):
    CLOCK[0] = CLOCK[0] + datetime.timedelta(**kw)


def set_clock(y, mo, d, h=4, mi=30):
    CLOCK[0] = datetime.datetime(y, mo, d, h, mi, 0, tzinfo=UTC)


# ---------------------------------------------------------------- recording
CALLS: list = []


def norm(v):
    if isinstance(v, dict):
        return {str(k): norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted((norm(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True, default=str))
    if isinstance(v, datetime.datetime):
        return v.astimezone(UTC).isoformat(timespec="milliseconds")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return round(float(v), 9)
    if isinstance(v, float):
        return round(v, 9)
    return v


async def R(label, coro):
    try:
        v = await coro
    except Exception as e:                                                   # noqa: BLE001 - an exception is a result too (the same class must come out of both engines)
        v = {"EXC": type(e).__name__}
    CALLS.append([label, norm(v)])
    return v


def rec(label, v):
    CALLS.append([label, norm(v)])
    return v


def columns(M):
    if hasattr(M, "__columns__"):                                            # the store
        return list(M.__columns__)
    import sqlalchemy as sa
    return [a.key for a in sa.inspect(M).column_attrs]


def models():
    if hasattr(db.Base, "models"):
        return db.Base.models()
    return [m.class_ for m in db.Base.registry.mappers]


async def dump_all():
    out = {}
    async with db._Session() as s:
        for M in sorted(models(), key=lambda m: m.__tablename__):
            rows = (await s.execute(db.select(M))).scalars().all()
            names = columns(M)
            recs = []
            for r in rows:
                d = {n: norm(getattr(r, n)) for n in names}
                if M.__tablename__ == "user_keys" and d.get("blob"):
                    d["blob"] = "<sealed>"                                   # Fernet output is random per call
                recs.append(d)
            recs.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
            out[M.__tablename__] = recs
    return out


# ---------------------------------------------------------------- the scenario
SC = {"confidence": 62, "continuity": 55, "vocabulary": 48, "grammar_trend": 50, "depth": 40}


async def main():
    await db.init_db()
    if PHASE == "full":
        db._PRACTICE_KEEP = 3

    section = lambda t: CALLS.append(["== " + t, None])                       # noqa: E731

    # ---- accounts
    section("login")
    people = [("u1", "ann@x.com", "Ann"), ("u2", "bob@x.com", "Bob"), ("u3", "cy@x.com", "Cy"), ("u4", "di@x.com", "Di"), ("u5", "ed@x.com", "Ed")]
    for sub, email, name in people:
        await R(f"login {sub}", db.login({"sub": sub, "email": email, "name": name, "picture": f"https://p/{sub}"}))
        tick(seconds=30)
    await R("login u1 again (keeps what it has, moves last_seen)", db.login({"sub": "u1", "email": "ann@x.com", "name": "Ann B"}))
    await R("get_state u1", db.get_state("u1"))
    await R("get_state missing", db.get_state("nope"))

    # ---- onboarding + the journey
    section("assessment / lessons / level tests")
    await R("save_assessment u1 (hi)", db.save_assessment("u1", {"goal": "job", "comfort": "low", "practice_time": "20 min", "level": "A2", "scores": {"confidence": 40, "grammar": 55}, "weak_areas": ["confidence"]}, lang="hi"))
    await R("save_assessment u2", db.save_assessment("u2", {"goal": "talk", "comfort": "ok", "practice_time": "10 min", "level": "B1", "scores": {"confidence": 70}, "weak_areas": []}))
    await R("save_about u1", db.save_about("u1", {"nickname": "Annie", "native_lang": "Hindi", "profession": "student", "dream": "fluent speaker", "career_goal": "Engineer",
                                                  "interests": {"music": "pop"}, "intro_text": "Hello I am Ann"}))
    await R("save_about u1 again (merges interests, keeps day1 text)", db.save_about("u1", {"interests": {"sport": "cricket"}, "intro_text": "A different intro"}))
    for lid in ("l1", "l2", "l3", "l4", "l5", "l1"):
        tick(minutes=2)
        await R(f"complete_lesson u1 L2 {lid}", db.complete_lesson("u1", 2, lid, "converse" if lid == "l3" else ""))
    await R("complete_lesson u2 L3 (no assessment-start mismatch)", db.complete_lesson("u2", 3, "a1"))
    await R("complete_lesson for a user with no progress row yet", db.complete_lesson("u3", 1, "z1"))
    await R("complete_lesson u3 again (so no two learners tie on XP: a tie has no defined order in SQL)", db.complete_lesson("u3", 1, "z2"))
    await R("submit_level_test u1 L2 fail", db.submit_level_test("u1", 2, 65))
    await R("submit_level_test u1 L2 pass -> level up", db.submit_level_test("u1", 2, 75))
    await R("submit_level_test u1 L3 ace -> courage badge", db.submit_level_test("u1", 3, 95))
    await R("save_assessment u1 RE-TAKE (merge, never wipe)", db.save_assessment("u1", {"goal": "job", "comfort": "mid", "practice_time": "30 min", "level": "B1", "scores": {"confidence": 52}, "weak_areas": ["grammar"]}, lang="en"))
    await R("award_badges u1", db.award_badges("u1", ["alpha", "streak_7", "alpha"]))
    await R("award_badges nothing", db.award_badges("u1", []))
    await R("award_badges on a user with no progress row", db.award_badges("u4", ["first"]))
    await R("alias_for", asyncio.sleep(0, result=db.alias_for("u1")))
    await R("leaderboard u1", db.leaderboard("u1"))
    await R("leaderboard u3 limit 1", db.leaderboard("u3", limit=1))
    await R("leaderboard unknown", db.leaderboard("zzz"))

    # ---- speaker progression: XP formula, caps, ranks, streaks, weekly league, trend
    section("speaker progress")
    seq = [
        ("u1", "conversation", 6.5, 8, SC, True, 0, frozenset()),
        ("u1", "daily", 3.2, 4, SC, True, 5, frozenset()),
        ("u2", "interview", 12.0, 9, {**SC, "confidence": 80}, True, 0, frozenset()),
        ("u3", "conversation", 1.0, 2, SC, False, 0, frozenset()),                          # low effort: 0.3x, no streak
        ("u1", "presentation", 4.0, 6, SC, True, 0, frozenset({"vocabulary", "grammar_trend"})),   # unscored components -> NULL, renormalised
        ("u1", "weird-mode", 2.0, 3, SC, True, 0, frozenset()),                              # an unknown mode is logged as conversation
        ("u4", "conversation", 5.0, 6, SC, True, 0, frozenset()),
        ("u5", "conversation", 5.0, 6, SC, True, 0, frozenset()),                             # u4 and u5: the same week numbers -> the xp_reached_at tie-break decides
    ]
    for args in seq:
        tick(minutes=7)
        await R(f"award_speaker_progress {args[0]} {args[1]}", db.award_speaker_progress(*args[:6], thoughts_translated=args[6], unscored=args[7]))
    for i in range(4):                                                                      # big sessions: the per-session (300) and per-day (600) XP caps
        tick(minutes=40)
        await R(f"award_speaker_progress u1 big #{i}", db.award_speaker_progress("u1", "interview", 30.0, 12, SC, True))
    await R("speaker_progress_state u1", db.speaker_progress_state("u1"))
    await R("speaker_progress_state missing", db.speaker_progress_state("nope"))
    await R("weekly_league u1", db.weekly_league("u1"))
    await R("weekly_league u1 by level", db.weekly_league("u1", by_level=True))
    await R("weekly_league u5 (tie)", db.weekly_league("u5"))
    await R("weekly_league u4 limit 2", db.weekly_league("u4", limit=2))
    await R("weekly_league nobody", db.weekly_league("nope"))
    await R("speaking_trend u1", db.speaking_trend("u1"))
    await R("speaking_trend u3 (one session)", db.speaking_trend("u3"))
    await R("personal_best u1", db.personal_best("u1"))
    await R("check_achievement_badges u1", db.check_achievement_badges("u1"))
    await R("check_achievement_badges missing", db.check_achievement_badges("nope"))

    # the next days: a streak, missions, the Monday rollover
    section("days pass")
    for day in range(1, 4):
        set_clock(2026, 3, 2 + day, 5, 0)
        await R(f"day+{day} award u1", db.award_speaker_progress("u1", "conversation", 6.0, 8, SC, True))
        await R(f"day+{day} complete_lesson u2", db.complete_lesson("u2", 3, f"b{day}"))
        await R(f"day+{day} get_weekly_missions u1", db.get_weekly_missions("u1"))
        await R(f"day+{day} update_weekly_missions u1", db.update_weekly_missions("u1", "conversation", 6.0, 70))
        await R(f"day+{day} state u1", db.get_state("u1"))
    await R("speaker_progress_state u1 after the streak", db.speaker_progress_state("u1"))
    set_clock(2026, 3, 9, 5, 0)                                                              # next Monday: a new league week, new missions
    await R("next week: get_weekly_missions u1", db.get_weekly_missions("u1"))
    await R("next week: award u2", db.award_speaker_progress("u2", "daily", 3.0, 6, SC, True))
    await R("next week: weekly_league u2", db.weekly_league("u2"))
    await R("next week: update_weekly_missions u2", db.update_weekly_missions("u2", "daily", 3.0, 60))
    await R("next week: state u1 (the streak lapsed?)", db.get_state("u1"))
    await R("next week: speaking_trend u1", db.speaking_trend("u1"))

    # ---- confidence checks / interview reports
    section("confidence checks / interview reports")
    await R("save_confidence_check u1 #1 (vs the Day-1 baseline)", db.save_confidence_check("u1", 58, {"a": 1}))
    tick(days=1)
    await R("save_confidence_check u1 #2 (vs previous)", db.save_confidence_check("u1", 66, {"a": 2}))
    await R("save_confidence_check u3 (no profile scores)", db.save_confidence_check("u3", 40, {}))
    await R("get_confidence_check_history u1", db.get_confidence_check_history("u1"))
    await R("get_confidence_check_history none", db.get_confidence_check_history("u5"))
    await R("save_interview_report u1", db.save_interview_report("u1", "Analyst", {"overall": 71, "scores": {"x": 1}, "filler_words": ["um"], "strengths": ["s"], "fixes": ["f"], "better_answer": {"q": "?"}}))
    await R("save_interview_report error payload is ignored", db.save_interview_report("u1", "Analyst", {"error": "x"}))
    await R("get_interview_reports u1", db.get_interview_reports("u1"))
    await R("rank milestones after a check: speaker_progress_state", db.speaker_progress_state("u1"))

    # ---- memory / companion
    section("memory and the companion")
    await R("get_memory u1", db.get_memory("u1"))
    await R("merge_facts u1", db.merge_facts("u1", {"profession": "analyst", "interests": {"film": "drama"}, "notes": ["likes tea", "has a cat"], "relationship": {"tone": "warm"},
                                                    "moments": ["got a new job", {"text": "exam soon", "emotion": "nervous"}], "achievements": ["spoke for 5 minutes", "spoke for 5 minutes"]},
                                             [{"type": "interview", "date": "2026-03-12"}, {"type": "interview", "date": "2026-03-12"}]))
    await R("merge_facts with junk", db.merge_facts("u1", None, "nope"))
    await R("add_recent_questions", db.add_recent_questions("u1", ["What is your plan?", " ", "What is your plan?", "Why English?"]))
    await R("set_next_hook", db.set_next_hook("u1", "  tell me about the exam  "))
    await R("save_checkin", db.save_checkin("u1", "great", "high"))
    await R("save_checkin again same day replaces", db.save_checkin("u1", "tired"))
    await R("save_daily_context", db.save_daily_context("u1", {"mood": "good", "plans": "gym", "weather": "hot", "note": "n1", "events": [{"type": "x"}]}))
    await R("save_daily_context again", db.save_daily_context("u1", {"note": "n2", "events": [{"type": "x"}, {"type": "y"}]}))
    await R("record_practice u1", db.record_practice("u1", seconds=300, sentences=12))
    await R("record_practice u1 again", db.record_practice("u1", seconds=120, sentences=3, xp=10))
    await R("bump_daily_stat u2", db.bump_daily_stat("u2", sentences=4, seconds=90))
    await R("add_vocab u1", db.add_vocab("u1", ["Hello", "world,", "a", "x1", "SPEAKING", "hello", "tea."]))
    await R("add_vocab nothing new", db.add_vocab("u1", ["hello"]))
    await R("save_letter", db.save_letter("u1", "Dear Ann"))
    await R("set_nickname", db.set_nickname("u1", "  Annie B  "))
    await R("set_nickname empty removes it", db.set_nickname("u2", "   "))
    await R("save_future_me", db.save_future_me("u1", "I speak well"))
    await R("save_recent_turns", db.save_recent_turns("u1", [{"role": "user", "content": "hi", "mode": "daily"}, {"role": "assistant", "content": "hello " * 200, "mode": "daily"}, {"role": "x", "content": "bad"}, "junk"]))
    for i, mode in enumerate(["daily", "conversation", "interview", "daily", "learning"]):
        tick(minutes=3)
        await R(f"add_conversation u1 {mode} #{i}", db.add_conversation("u1", mode, f"summary {i} " + mode))
    await R("add_conversation empty is ignored", db.add_conversation("u1", "daily", "  "))
    await R("recent_summaries u1", db.recent_summaries("u1", 3))
    await R("recent_summaries u1 limit 10", db.recent_summaries("u1", 10))
    await R("mode_counts u1", db.mode_counts("u1"))
    await R("relationship_stage u1", db.relationship_stage("u1"))
    await R("relationship_stage u5", db.relationship_stage("u5"))
    await R("build_companion_context u1", db.build_companion_context("u1"))
    await R("build_growth u1", db.build_growth("u1"))
    await R("build_growth u1 again (the baseline moved)", db.build_growth("u1"))
    await R("build_opening u1", db.build_opening("u1"))
    await R("build_opening u5 (a stranger)", db.build_opening("u5"))
    await R("build_recommendations u1", db.build_recommendations("u1"))
    await R("build_recommendations u5", db.build_recommendations("u5"))
    await R("build_today u1", db.build_today("u1"))
    await R("build_today u5", db.build_today("u5"))
    await R("save_career_roadmap u1", db.save_career_roadmap("u1", "Data analyst", "A plan", [{"phase": "Basics", "title": "SQL", "description": "learn", "skills": ["sql", "excel"]},
                                                                                                  {"phase": "Basics", "title": "Stats", "skills": ["x"]}, {"phase": "Jobs", "title": "Apply"}, "junk"]))
    await R("set_career_stage_done u1", db.set_career_stage_done("u1", "p0_s1", True))
    await R("set_career_stage_done unknown stage", db.set_career_stage_done("u1", "zzz", True))
    await R("set_career_stage_done no roadmap", db.set_career_stage_done("u5", "p0_s0", True))
    await R("get_memory u1 at the end", db.get_memory("u1"))

    # ---- keys, quota, plan, feedback
    section("keys / quota / plan / feedback")
    await R("save_user_keys u1", db.save_user_keys("u1", {"groq": " gsk_one ", "gemini": "AIza_two", "github": "", "x": None}, True))
    await R("get_user_keys u1", db.get_user_keys("u1"))
    await R("has_user_keys u1", db.has_user_keys("u1"))
    await R("has_user_keys u1 strict", db.has_user_keys("u1", strict=True))
    await R("save_user_keys u2 (one key, unverified)", db.save_user_keys("u2", {"groq": "gsk_x"}, False))
    await R("has_user_keys u2", db.has_user_keys("u2"))
    await R("get_user_keys none", db.get_user_keys("u5"))
    await R("save_user_keys u1 empty clears", db.save_user_keys("u3", {}, False))
    await R("incr_request #1", db.incr_request("u1", "2026-03-12", 3))
    await R("incr_request #2", db.incr_request("u1", "2026-03-12", 3))
    await R("incr_request #3", db.incr_request("u1", "2026-03-12", 3))
    await R("incr_request #4 over the limit", db.incr_request("u1", "2026-03-12", 3))
    await R("incr_request unlimited", db.incr_request("u2", "2026-03-12", None))
    await R("refund_request", db.refund_request("u1", "2026-03-12"))
    await R("refund_request never below zero", db.refund_request("u5", "2026-03-12"))
    await R("usage_today", db.usage_today("u1", "2026-03-12"))
    await R("usage_total", db.usage_total("u1"))
    await R("signup_day_count u1", db.signup_day_count("u1"))
    await R("signup_day_count missing", db.signup_day_count("nope"))
    await R("get_plan u1", db.get_plan("u1"))
    await R("set_plan u1", db.set_plan("u1", "plus"))
    await R("set_plan missing", db.set_plan("nope", "plus"))
    await R("get_plan after", db.get_plan("u1"))
    tick(seconds=5)
    await R("add_feedback", db.add_feedback("u1", "ann@x.com", "help", "  it crashed  "))
    tick(seconds=5)
    await R("add_feedback kind coerced", db.add_feedback("u2", "bob@x.com", "other", "nice app"))
    await R("add_feedback empty is ignored", db.add_feedback("u2", "bob@x.com", "help", "  "))
    await R("list_feedback", db.list_feedback())
    await R("list_feedback limit 1", db.list_feedback(1))

    # ---- admin
    section("admin")
    await R("office_add", db.office_add("Free@Office.com"))
    tick(seconds=1)
    await R("office_add #2", db.office_add("two@office.com"))
    await R("office_add bad", db.office_add("nope"))
    await R("office_list", db.office_list())
    await R("office_has", db.office_has(" FREE@office.com "))
    await R("office_remove", db.office_remove("free@office.com"))
    await R("office_list after", db.office_list())
    await R("early_add", db.early_add("Tester@Mail.com"))
    tick(seconds=1)
    await R("early_add #2", db.early_add("t2@mail.com"))
    await R("early_add again", db.early_add("tester@mail.com"))
    await R("early_add bad", db.early_add("a b@c.d"))
    await R("early_has", db.early_has("TESTER@mail.com"))
    await R("early_list", db.early_list())
    await R("early_remove", db.early_remove("t2@mail.com"))
    await R("get_setting default", db.get_setting("k1", "dflt"))
    await R("set_setting", db.set_setting("k1", "v1"))
    await R("set_setting update", db.set_setting("k1", "v2"))
    await R("get_setting", db.get_setting("k1", "dflt"))
    await R("set_user_status", db.set_user_status("u3", "blocked"))
    await R("set_user_status bad value", db.set_user_status("u3", "weird"))
    await R("set_user_mode", db.set_user_mode("u2", "office", "pending"))
    await R("set_user_mode missing", db.set_user_mode("nope", "office"))
    await R("get_user_flags u3", db.get_user_flags("u3"))
    await R("get_user_flags u2", db.get_user_flags("u2"))
    await R("get_user_flags missing", db.get_user_flags("nope"))
    await R("admin_list_users", db.admin_list_users())

    # ---- seasons
    section("seasons")
    set_clock(2026, 3, 20, 5, 0)
    for i in range(5):
        tick(hours=1)
        await db.award_speaker_progress("u2", "conversation", 8.0 + i, 7, {**SC, "confidence": 60 + i * 5, "depth": 30 + i * 8}, True)
    for i in range(4):
        tick(hours=1)
        await db.award_speaker_progress("u5", "interview", 5.0, 7, SC, True)
    set_clock(2026, 11, 2, 5, 0)
    await R("previous_closed_season_id", asyncio.sleep(0, result=db.previous_closed_season_id()))
    await R("current_season_id", asyncio.sleep(0, result=db.current_season_id()))
    await R("compute_season_awards H1", db.compute_season_awards("2026-H1"))
    await R("compute_season_awards H1 again (idempotent)", db.compute_season_awards("2026-H1"))
    await R("compute_season_awards default (previous closed)", db.compute_season_awards())
    await R("get_my_season_awards u1", db.get_my_season_awards("u1"))
    await R("get_my_season_awards u2", db.get_my_season_awards("u2"))
    await R("interview_context u2", db.interview_context("u2"))
    await R("interview_context u1", db.interview_context("u1"))
    await R("interview_context missing", db.interview_context("nope"))

    # ---- practice room
    section("practice room")
    set_clock(2026, 11, 2, 6, 0)
    await R("get_practice_prefs defaults", db.get_practice_prefs("u1"))
    await R("save_practice_prefs", db.save_practice_prefs("u1", {"lang": "en", "feedback_lang": "hinglish", "english_invite": "on", "evil": "x"}))
    await R("practice_invite_action opened", db.practice_invite_action("u1", "opened"))
    await R("practice_invite_action dismissed #1", db.practice_invite_action("u1", "dismissed"))
    await R("practice_invite_action dismissed #2 -> snooze", db.practice_invite_action("u1", "dismissed"))
    await R("practice_invite_action off", db.practice_invite_action("u1", "off"))
    await R("practice_invite_action bad", db.practice_invite_action("u1", "zzz"))
    await R("save_practice_prefs on again clears the snooze", db.save_practice_prefs("u1", {"english_invite": "on"}))
    base = {"kind": "presentation", "topic": "My town", "lang": "hi", "feedback_lang": "en", "level": "beginner", "target_sec": 120, "actual_sec": 100, "pause_sec": 10, "words": 150, "wpm": 90,
            "overall": 77, "scores": {"clarity": 70}, "report": {"summary": "ok"}, "invite": "none", "genuine_effort": True}
    ids = []
    for i, d in enumerate([base, {**base, "lang": "en", "parent_id": None}, {**base, "kind": "viva", "overall": 85}, {**base, "kind": "speech"}, {**base, "kind": "seminar"},
                           {**base, "kind": "discussion"}, {**base, "kind": "custom", "overall": 91}]):
        tick(minutes=5)
        r = await R(f"save_practice_attempt #{i}", db.save_practice_attempt("u1", d))
        ids.append((r or {}).get("id"))
    tick(minutes=5)
    await R("save_practice_attempt retry (child of #0)", db.save_practice_attempt("u1", {**base, "lang": "hi", "parent_id": ids[0]}))
    tick(minutes=5)
    await R("save_practice_attempt bridge (English child of a Hindi one)", db.save_practice_attempt("u1", {**base, "lang": "en", "parent_id": ids[0]}))
    tick(minutes=5)
    await R("save_practice_attempt foreign parent is ignored", db.save_practice_attempt("u2", {**base, "parent_id": ids[0]}))
    await R("get_practice_parent", db.get_practice_parent("u1", ids[0]))
    await R("get_practice_parent foreign", db.get_practice_parent("u2", ids[0]))
    await R("get_practice_parent none", db.get_practice_parent("u1", None))
    await R("list_practice_attempts u1", db.list_practice_attempts("u1"))
    await R("list_practice_attempts u1 limit 3", db.list_practice_attempts("u1", 3))
    await R("get_practice_attempt", db.get_practice_attempt("u1", ids[2]))
    await R("get_practice_attempt foreign", db.get_practice_attempt("u2", ids[2]))
    await R("practice_today", db.practice_today("u1", "my town"))
    await R("mark_practice_invite", db.mark_practice_invite("u1", ids[0], "shown"))
    await R("mark_practice_invite bad state", db.mark_practice_invite("u1", ids[1], "zzz"))
    await R("practice_today after an invite", db.practice_today("u1", "My Town"))
    await R("check_practice_badges u1", db.check_practice_badges("u1"))
    await R("check_practice_badges u1 again", db.check_practice_badges("u1"))

    # ---- prefs + the life snapshot
    section("prefs / life snapshot")
    await R("save_lang_pref default", db.save_lang_pref("u1"))
    await R("save_lang_pref en", db.save_lang_pref("u1", lang="en"))
    await R("save_lang_pref learn bad", db.save_lang_pref("u1", learn="zz"))
    await R("save_home_prefs default", db.save_home_prefs("u1"))
    await R("save_home_prefs off", db.save_home_prefs("u1", personal=False))
    await R("life_snapshot u1", db.life_snapshot("u1"))
    await R("life_snapshot missing", db.life_snapshot("nope"))
    await R("final get_state u1", db.get_state("u1"))

    if PHASE == "full":
        section("cross-module cascades (full phase)")
        await R("delete_practice_attempt (child -> parent_id cleared)", db.delete_practice_attempt("u1", ids[0]))
        await R("delete_practice_attempt foreign", db.delete_practice_attempt("u2", ids[2]))
        await R("delete_user u5", db.delete_user("u5"))
        await R("delete_user missing", db.delete_user("nope"))
        await R("admin_wipe_users keeps u1 u2", db.admin_wipe_users({"ann@x.com", "bob@x.com", "TWO@office.com"}))
        await R("admin_list_users after the wipe", db.admin_list_users())

    tables = await dump_all()
    with open(OUT, "w") as f:
        json.dump({"calls": CALLS, "tables": tables}, f, sort_keys=True, indent=0, default=str)
    exc = [c for c in CALLS if isinstance(c[1], dict) and "EXC" in c[1]]
    print(f"{len(CALLS)} recorded calls, {sum(len(v) for v in tables.values())} rows in {len(tables)} tables, {len(exc)} call(s) raised: {[c[0] + ' -> ' + c[1]['EXC'] for c in exc][:8]}")


asyncio.run(main())
