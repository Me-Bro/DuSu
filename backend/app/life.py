"""DuSu knows your data (CLAUDE.md §10).

main._facts_summary() tells DuSu who the learner IS (name, dream, moments, how the last chat ended)
but holds none of their NUMBERS, so "what's my streak?" or "which skill is my weakest?" had nothing to
read and the model made an answer up. build() reads what is already in Postgres - level check, streak,
XP and Speaker rank, this week's league spot, the learning roadmap, minutes and words, recent Practice
Room talks and mock interviews, weekly missions, badges - and renders ONE short block that main.py
appends to the session's memory text for Face-to-Face Talk and Daily Talk (not Interview, which is a
role-play, and not Learn, which is a translator).

Read-only and best-effort: every read is independent and a failing one is skipped, so a database
hiccup can never stop a conversation from starting. Everything in the block belongs to `uid`; the only
league data is the caller's own rank, never another learner's alias or score.

The block is built once when the conversation opens, so it is the picture at that moment - a lesson
finished mid-chat shows up in the next one.

Other modules add their own lines through EXTRA_LINES (the Goals planner will - DUSU_GOALS_PLAN.md §10).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Awaitable, Callable

from . import db

_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))   # the app's one fixed day boundary (db._ist_now)

# async fn(uid) -> list[str]: a few short plain sentences for the block (no leading dash). Each gets
# 1.5 s and may fail silently - see build().
EXTRA_LINES: list[Callable[[str], Awaitable[list[str]]]] = []

_MAX_CHARS = 1700            # the whole list of lines, before the heading and the rules

# Mirrors of client constants (CURRICULUM names, BADGE_LABELS without the emoji) - the same
# "mirror the client" arrangement db.LEVEL_LESSON_COUNTS already has.
_LEVEL_NAMES = {1: "Thinking in English", 2: "Simple Speaking", 3: "Daily Conversation", 4: "Confidence",
                5: "Interview", 6: "Professional English", 7: "Fluency"}
_RANK_LABELS = {"starter": "Starter", "speaker": "Speaker", "confident_speaker": "Confident Speaker",
                "fluent_communicator": "Fluent Communicator", "english_pro": "English Pro"}
_MODE_LABELS = {"conversation": "Face-to-Face", "daily": "Daily Talk", "interview": "Interview",
                "presentation": "Presentation", "viva": "Viva", "speech": "Speech", "seminar": "Seminar",
                "discussion": "Discussion", "custom": "Practice Room"}
_SKILLS = ("confidence", "pronunciation", "listening", "vocabulary", "grammar", "thinking")
_BADGES = {
    "first_lesson": "First Lesson", "first_converse": "First Chat", "streak_3": "Getting Started (3 days)",
    "streak_7": "Consistent Speaker (7 days)", "streak_30": "Serious Speaker (30 days)",
    "streak_100": "Dedicated Speaker (100 days)", "streak_180": "DUSU Speaker (180 days)",
    "sentences_100": "100 Sentences", "level_up": "Level Up", "courage_no_hindi": "Spoke without Hindi",
    "courage_question": "Asked a question", "courage_5min": "5-Minute Talk",
    "courage_first_convo": "First Conversation", "courage_confident": "Aced a Challenge",
    "consistent_speaker": "Consistent Speaker (50+ hrs)", "conversation_builder": "Conversation Builder (100 chats)",
    "fearless_speaker": "Fearless Speaker (50 Face-to-Face)", "interview_ready": "Interview Ready (50 interviews)",
    "vocabulary_explorer": "Vocabulary Explorer (1,000 words)", "first_presentation": "First Presentation",
    "presentation_10": "10 Presentations", "presentation_80": "Presentation 80+",
    "presentation_90": "Presentation 90+", "bridge_builder": "Bridge Builder"}

_HEAD = "THEIR NUMBERS - read live from DuSu's database just now; these are exact:"
_RULES = ("HOW TO USE THEM: when they ask about their own progress (level, streak, XP, rank, scores, minutes, "
          "words, lessons, missions, badges, how a practice went), answer from exactly the numbers above, in "
          "your own warm words - the one or two that matter, not a report. If what they ask is not listed, "
          "say you don't have that yet; never guess, round up or invent a number. Don't bring up stats "
          "unprompted unless celebrating one real win feels natural, and never use a number to scold them.")


def _clean(v, n: int = 80) -> str:
    """One short, single-line, quote-safe piece of text. Some of it is typed by the learner or written
    by a model (topics, roles, goals) and all of it lands inside a system prompt."""
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v or ""))
    return re.sub(r"\s+", " ", t).replace('"', "'").strip()[:n].rstrip()


def _n(v, default=None):
    """int(v) or `default` - the JSONB columns are schemaless, so never trust a type."""
    if isinstance(v, bool):
        return default
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _day(v) -> dt.date | None:
    """An ISO date or datetime (as the app stores them) -> the learner's IST calendar date."""
    try:
        if isinstance(v, dt.datetime):
            d = v
        else:
            s = str(v)
            if len(s) <= 10:
                return dt.date.fromisoformat(s)
            d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(_IST).date()
    except (TypeError, ValueError):
        return None


def _ago(d: dt.date | None, today: dt.date) -> str:
    if d is None:
        return ""
    n = (today - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"{n} days ago" if n < 14 else d.strftime("%d %b")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _fit(lines: list[tuple[int, str]], limit: int) -> list[str]:
    """Keep the block short: drop the least important lines (priority 4, then 3, then 2; later lines
    first) until it fits. Priority-1 lines are the essentials and never go."""
    keep = list(range(len(lines)))
    for prio in (4, 3, 2):
        while sum(len(lines[i][1]) + 3 for i in keep) > limit:
            drop = [i for i in keep if lines[i][0] == prio]
            if not drop:
                break
            keep.remove(drop[-1])
    return [lines[i][1] for i in keep]


def render(snap: dict, league=None, trend=None, practice=None, extra=(), now: dt.datetime | None = None) -> str:
    """Pure formatting - no I/O - so it can be checked without a database. `snap` is db.life_snapshot()."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(_IST)
    today = now.date()
    prof, pg = snap["profile"], snap["progress"]
    facts = snap.get("facts") if isinstance(snap.get("facts"), dict) else {}
    L: list[tuple[int, str]] = []

    # --- level check -------------------------------------------------------------------------
    if not prof["onboarded"]:
        L.append((1, "English level: not assessed yet - they haven't done the level check."))
    else:
        s = f"English level: {_clean(prof['level'], 6) or 'unknown'}"
        if prof["goal"]:
            s += f" (their goal: {_clean(prof['goal'], 40)})"
        scores = prof["scores"] if isinstance(prof["scores"], dict) else {}
        sk = {k: _n(scores.get(k)) for k in _SKILLS}
        sk = {k: v for k, v in sk.items() if v is not None}
        if sk:
            s += ". Level-check skill scores out of 100: " + ", ".join(f"{k} {v}" for k, v in sk.items())
            weak = [_clean(w, 24) for w in (prof["weak_areas"] if isinstance(prof["weak_areas"], list) else [])
                    if isinstance(w, str) and w.strip()][:3]
            s += ". Weakest: " + ", ".join(weak or [k for k, _v in sorted(sk.items(), key=lambda kv: kv[1])[:2]])
        L.append((1, s + "."))

    # --- streak + today. streak_days is only reset on the NEXT activity, so a lapsed streak still
    #     holds its old number: it is alive only if they were last active today or yesterday. ------
    la = pg["last_active"] if isinstance(pg["last_active"], dt.date) else None
    streak = int(pg["streak_days"]) if (la is not None and (today - la).days <= 1) else 0
    if streak:
        s = (f"Streak: {_plural(streak, 'day')} ("
             + ("they practised today" if la == today else "not practised yet today - practising today keeps it alive") + ")")
    else:
        s = "Streak: no active streak right now" + (f" (last practised {_ago(la, today)})" if la else "")
    if pg["longest_streak_days"]:
        s += f"; best ever {_plural(int(pg['longest_streak_days']), 'day')}"
    L.append((1, s + "."))

    stats = facts.get("daily_stats") if isinstance(facts.get("daily_stats"), dict) else {}
    ds = stats.get(today.isoformat()) if isinstance(stats.get(today.isoformat()), dict) else {}
    mins, sess, words = (_n(ds.get("seconds"), 0) or 0) // 60, _n(ds.get("sessions"), 0) or 0, _n(ds.get("new_words"), 0) or 0
    s = (f"Today so far: {mins} min spoken in {_plural(sess, 'session')}" if (mins or sess)
         else "Today so far: nothing practised yet")
    if words:
        s += f", {_plural(words, 'new word')}"
    done_today = int(pg["sessions_today"]) if la == today else 0      # the counter is only reset by the next activity too
    L.append((1, s + f". Daily goal: {done_today} of {int(pg['daily_goal'])} done today."))

    # --- rank / xp ---------------------------------------------------------------------------------
    ranks = list(db._SPEAKER_RANKS)
    names = [n for n, _need in ranks]
    rk = pg["speaker_rank"] if pg["speaker_rank"] in names else "starter"
    sx = int(pg["speaker_xp"])
    s = f"Speaker rank: {_RANK_LABELS.get(rk, rk)} ({sx:,} Speaker XP)"
    i = names.index(rk)
    if i + 1 < len(ranks):
        nn, need = ranks[i + 1]
        s += (f"; next rank {_RANK_LABELS.get(nn, nn)} at {need:,} XP ({need - sx:,} to go)" if sx < need
              else f"; next rank {_RANK_LABELS.get(nn, nn)} - the XP is there, a few more sessions (and a Confidence Check) unlock it")
    L.append((1, s + f". Lesson XP (the leaderboard number): {int(pg['xp']):,}; coins: {int(pg['coins']):,}."))

    you = league.get("you") if isinstance(league, dict) else None
    if isinstance(you, dict) and you.get("rank"):
        L.append((2, f"This week's league: #{you['rank']} - {_n(you.get('xp'), 0)} XP, "
                     f"{_n(you.get('minutes'), 0)} min, {_plural(_n(you.get('sessions'), 0) or 0, 'session')}."))

    # --- learning roadmap --------------------------------------------------------------------------
    j = pg["journey"] if isinstance(pg["journey"], dict) else {}
    cur = _n(j.get("current_level"), 1) or 1
    completed = j.get("completed") if isinstance(j.get("completed"), dict) else {}
    tests = j.get("test_scores") if isinstance(j.get("test_scores"), dict) else {}
    done = len(completed.get(str(cur)) or []) if isinstance(completed.get(str(cur)), list) else 0
    world = db._WORLD_NAMES[cur - 1] if 1 <= cur <= len(db._WORLD_NAMES) else ""
    s = f"Learning roadmap: level {cur} of {db.MAX_LEVEL}"
    if cur in _LEVEL_NAMES:
        s += f" ({_LEVEL_NAMES[cur]}, '{world}')"
    s += f"; {done} of {db.LEVEL_LESSON_COUNTS.get(cur, 5)} lessons done"
    ts = tests.get(str(cur)) if isinstance(tests.get(str(cur)), dict) else None
    if ts:
        s += f"; this level's test: best {_n(ts.get('best'), 0)}%, {_plural(_n(ts.get('attempts'), 0) or 0, 'attempt')}"
    passed = sorted(int(k) for k, v in tests.items() if str(k).isdigit() and isinstance(v, dict) and v.get("passed"))
    if passed:
        s += "; level tests passed: " + ", ".join(str(p) for p in passed)
    L.append((1, s + "."))

    # --- lifetime totals + session counts ----------------------------------------------------------
    secs, sent = _n(facts.get("total_seconds"), 0) or 0, _n(facts.get("total_sentences"), 0) or 0
    vocab, longest = _n(facts.get("vocab_total"), 0) or 0, _n(facts.get("longest_convo_sec"), 0) or 0
    if secs or sent or vocab:
        s = f"Lifetime: {secs // 60} min spoken, {_plural(sent, 'sentence')}, {vocab} different words used"
        if longest:
            s += f"; longest talk {longest // 60} min {longest % 60} s"
        L.append((2, s + "."))
    counts = snap.get("session_counts") if isinstance(snap.get("session_counts"), dict) else {}
    if sum(counts.values()):
        L.append((2, f"Scored sessions: {sum(counts.values())} ("
                     + ", ".join(f"{_MODE_LABELS.get(m, _clean(m, 16) or 'other')} {c}"
                                 for m, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]) + ")."))

    if (isinstance(trend, dict) and trend.get("recent") is not None and trend.get("baseline") is not None
            and not (trend.get("day1_fallback") and _n(trend.get("delta"), 0) == 0)):   # "62 -> 62 (+0)" says nothing
        L.append((3, f"Speaking score (0-100): {trend['baseline']} -> {trend['recent']} ({_n(trend.get('delta'), 0):+d}) "
                     + ("since their first session." if trend.get("day1_fallback") else "versus their first week.")))

    # --- Practice Room + interviews ------------------------------------------------------------------
    talks = []
    for r in (practice if isinstance(practice, list) else [])[:3]:
        if not isinstance(r, dict):
            continue
        nums = {k: _n(v) for k, v in (r.get("scores") if isinstance(r.get("scores"), dict) else {}).items()}
        nums = {k: v for k, v in nums.items() if v is not None}
        bits = [b for b in (_ago(_day(r.get("created_at")), today),
                            (lambda w: f"weakest {w[0]} {w[1]}")(min(nums.items(), key=lambda kv: kv[1])) if nums else "") if b]
        talks.append(f"'{_clean(r.get('topic'), 50)}' {_n(r.get('overall'), 0)}/100" + (f" ({'; '.join(bits)})" if bits else ""))
    if talks:
        L.append((2, "Recent Practice Room talks: " + "; ".join(talks) + "."))

    reps = [r for r in (facts.get("interview_reports") if isinstance(facts.get("interview_reports"), list) else [])
            if isinstance(r, dict) and _n(r.get("overall")) is not None]
    if reps:
        last = reps[-1]
        when = _ago(_day(last.get("date")), today)
        L.append((2, f"Mock interviews: {len(reps)} scored recently, average {round(sum(_n(r['overall']) for r in reps) / len(reps))}/100; "
                     f"the last was {_clean(last.get('role'), 40) or 'a general interview'} - {_n(last['overall'])}/100"
                     + (f" ({when})" if when else "") + "."))

    # --- career goal, missions, confidence check, badges, tenure ---------------------------------------
    rm = facts.get("career_roadmap") if isinstance(facts.get("career_roadmap"), dict) else None
    cg = _clean(facts.get("career_goal"), 60) or (_clean(rm.get("goal"), 60) if rm else "")
    stages = [x for x in (rm.get("stages") if rm and isinstance(rm.get("stages"), list) else []) if isinstance(x, dict)]
    if stages:
        L.append((3, f"Career goal: {cg or 'not named'} - roadmap {sum(1 for x in stages if x.get('done'))} of {len(stages)} stages done."))
    elif cg:
        L.append((3, f"Career goal: {cg}."))

    wm = facts.get("weekly_missions") if isinstance(facts.get("weekly_missions"), dict) else None
    if wm and wm.get("week_start") == (today - dt.timedelta(days=today.weekday())).isoformat():
        ms = [f"{_clean(m['text'], 60)} ({_n(m.get('progress'), 0)}/{_n(m.get('target'), 0)})"
              for m in (wm.get("missions") if isinstance(wm.get("missions"), list) else [])[:4]
              if isinstance(m, dict) and m.get("text")]
        if ms:
            L.append((3, "This week's missions: " + "; ".join(ms) + "."))

    lc = facts.get("last_confidence_check") if isinstance(facts.get("last_confidence_check"), dict) else None
    if lc and _n(lc.get("overall")) is not None:
        when = _ago(_day(lc.get("date")), today)
        L.append((3, f"Last Confidence Check: {_n(lc['overall'])}/100" + (f" ({when})" if when else "") + "."))

    bd = [b for b in (pg["badges"] if isinstance(pg["badges"], list) else []) if isinstance(b, str)]
    if bd:
        L.append((4, f"Badges: {len(bd)} earned; latest: "
                     + ", ".join(_BADGES.get(b, _clean(b.replace("_", " "), 30)) for b in bd[-3:]) + "."))
    ca = snap.get("created_at")
    if isinstance(ca, dt.datetime):
        L.append((4, f"This is day {max(1, (now - ca).days + 1)} since they joined DuSu."))

    for x in extra or ():
        if _clean(x, 300):
            L.append((2, _clean(x, 300)))

    return "\n".join([_HEAD] + [f"- {t}" for t in _fit(L, _MAX_CHARS)] + [_RULES])


async def _extra(fn: Callable[[str], Awaitable[list[str]]], uid: str) -> list[str]:
    try:
        out = await asyncio.wait_for(fn(uid), timeout=1.5)
        return [str(x) for x in out] if isinstance(out, list) else []
    except Exception as e:                      # a module's lines are a bonus - never a reason to fail
        print(f"[life] extra {getattr(fn, '__name__', 'fn')} failed: {type(e).__name__}")
        return []


async def build(uid: str) -> str:
    """The block for `uid`, or "" when there is nothing honest to say (no database, unknown user, the
    snapshot itself failed). The caller bounds the wait (main.py gives it 3 s)."""
    if not uid or not db.db_enabled:
        return ""
    res = await asyncio.gather(
        db.life_snapshot(uid), db.weekly_league(uid, limit=1), db.speaking_trend(uid),
        db.list_practice_attempts(uid, 3), *[_extra(fn, uid) for fn in EXTRA_LINES],
        return_exceptions=True)
    names = ("snapshot", "league", "trend", "practice")
    for name, r in zip(names, res):
        if isinstance(r, Exception):
            print(f"[life] {name} failed: {type(r).__name__}: {r}")
    snap, league, trend, practice = (None if isinstance(r, Exception) else r for r in res[:4])
    if not snap:
        return ""
    extra = [line for r in res[4:] if isinstance(r, list) for line in r]
    return render(snap, league, trend, practice, extra)
