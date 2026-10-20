"""Notifications - the pure rules: what to send, to whom, when, in which words. No database, no network, no clock except an argument.

Three growth notifications, each chosen from the learner's OWN rows (no model call, no cost):

    streak   they have a live streak of >= 2 days and have not practised today -> "your N-day streak ends tonight"
    practice they have not practised today and have no live streak              -> "today's practice is waiting"
    weekly   Sunday morning, the weekly note from DuSu is due                   -> "your weekly note is ready"

`streak` and `practice` share ONE slot per day (streak wins), so a learner never gets two nudges in a day. A learner who ignored the last three
nudges is left alone for a week (or until they practise again). Every row is re-checked at SEND time (`still_wanted`), so a learner who practised
in the meantime is never nudged.

Days: the app's one day boundary is IST (db._ist_now) - "practised today", the streak and the letter gap all use it - while the nudge TIME is the
learner's own wall clock (planner time zone, default Asia/Kolkata).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata

from ..planner import timeutil as tu

KINDS = ("practice", "streak", "weekly")
DEFAULT_NUDGE = "19:00"
MIN_STREAK = 2                    # a "streak" worth defending
LETTER_GAP_DAYS = 7               # the weekly letter regenerates at most once every 7 days (main.letter)
LETTER_MIN_XP = 20                # ... and only with some activity (main.letter)
WEEKLY_AT = "10:00"
WEEKLY_WEEKDAY = 6                # Sunday (Monday = 0)
LOOKAHEAD_MIN = 20                # a row is made this long before it is due (so it carries fresh facts)
LATE_GRACE_MIN = 90               # ... and never later than this after it was due (a late nudge is worse than none)
IGNORED_LIMIT = 3                 # unanswered nudges in a row -> pause
PAUSE_DAYS = 7
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
LIMITS = {"title": 60, "body": 160, "name": 20}


# ----------------------------------------------------------------------------- small cleaners
def clean_time(v) -> str | None:
    """'HH:MM' (24 h) or None."""
    t = tu.parse_hhmm(v) if isinstance(v, str) else None
    return tu.fmt_hhmm(t) if t is not None else None


def clean_kinds(v, current: dict | None = None) -> dict:
    """The per-kind switches. Unknown keys are ignored, non-booleans are ignored, missing kinds keep their current value (default on)."""
    out = {k: True for k in KINDS}
    if isinstance(current, dict):
        for k in KINDS:
            if isinstance(current.get(k), bool):
                out[k] = current[k]
    if isinstance(v, dict):
        for k in KINDS:
            if isinstance(v.get(k), bool):
                out[k] = v[k]
    return out


def first_name(raw) -> str:
    """A first name that is safe to put in a notification: letters (any script), marks, hyphen, apostrophe; at most 20 characters; '' if none."""
    if not isinstance(raw, str):
        return ""
    word = (raw.strip().split() or [""])[0]
    kept = "".join(c for c in unicodedata.normalize("NFC", word) if c.isalpha() or unicodedata.category(c).startswith("M") or c in "-'")
    return kept[:LIMITS["name"]]


def ist_date(when: dt.datetime) -> dt.date:
    return when.astimezone(IST).date()


# ----------------------------------------------------------------------------- the learner's facts -> what is wanted
def alive_streak(streak_days: int, last_active: dt.date | None, today: dt.date) -> int:
    """`progress.streak_days` is only reset by the NEXT activity, so a lapsed streak keeps its old number: it is alive only if the learner
    was last active today or yesterday (same rule as life.render)."""
    if last_active is None or not isinstance(streak_days, int) or streak_days <= 0:
        return 0
    return streak_days if (today - last_active).days in (0, 1) else 0


def pick_daily_kind(snap: dict, today: dt.date) -> str | None:
    """'streak' | 'practice' | None for today. None when they already practised, when the kind is switched off, or when they are not onboarded."""
    kinds = snap.get("kinds") or {}
    if not snap.get("onboarded") or snap.get("last_active") == today:
        return None
    if alive_streak(snap.get("streak_days") or 0, snap.get("last_active"), today) >= MIN_STREAK and kinds.get("streak", True):
        return "streak"
    return "practice" if kinds.get("practice", True) else None


def weekly_due(snap: dict, today: dt.date) -> bool:
    """Is the weekly note worth announcing? There is activity to write about, the last letter is at least a week old (or there is none), and the
    learner was around this week."""
    if not (snap.get("kinds") or {}).get("weekly", True) or not snap.get("onboarded"):
        return False
    if (snap.get("xp") or 0) < LETTER_MIN_XP:
        return False
    la = snap.get("last_active")
    if la is None or (today - la).days > 7:
        return False
    last_letter = snap.get("last_letter")
    return last_letter is None or (today - last_letter).days >= LETTER_GAP_DAYS


def is_paused(snap: dict, now: dt.datetime) -> bool:
    """The last three growth nudges were all ignored (not opened, and no practice that day): stop for a week - unless they practised since the
    newest one. `snap['recent']` = the delivered practice / streak rows, newest first: {sent_at, opened_at}."""
    recent = [r for r in (snap.get("recent") or []) if r.get("sent_at") is not None][:IGNORED_LIMIT]
    if len(recent) < IGNORED_LIMIT:
        return False
    active_days = snap.get("active_days") or set()
    for r in recent:
        if r.get("opened_at") is not None or ist_date(r["sent_at"]) in active_days:
            return False
    newest = recent[0]["sent_at"]
    la = snap.get("last_active")
    if la is not None and la > ist_date(newest):
        return False
    return (now - newest) < dt.timedelta(days=PAUSE_DAYS)


def slots(snap: dict, now: dt.datetime) -> dict:
    """Facts-free: which send slots are OPEN right now for this learner's clock, as {"daily": (fire_utc, dedupe_key) | None, "weekly": ... | None}.
    A slot is open from LOOKAHEAD_MIN before its time to LATE_GRACE_MIN after it. Needs only the time zone, the nudge time and the quiet hours -
    so the materializer can skip everyone who is not near a slot without loading their progress."""
    out = {"daily": None, "weekly": None}
    if not snap.get("enabled", True):
        return out
    tz = tu.norm_tz(snap.get("tz"))
    day = tu.local_now(tz, now).date()

    def window(fire: dt.datetime) -> bool:
        return fire - dt.timedelta(minutes=LOOKAHEAD_MIN) <= now <= fire + dt.timedelta(minutes=LATE_GRACE_MIN)

    t = tu.parse_hhmm(snap.get("nudge_time")) or tu.parse_hhmm(DEFAULT_NUDGE)
    fire = tu.to_utc(day, t, tz)
    if snap.get("quiet_on", True):
        qs, qe = tu.parse_hhmm(snap.get("quiet_start") or "22:00"), tu.parse_hhmm(snap.get("quiet_end") or "07:00")
        release = tu.quiet_release_utc(fire, tz, qs, qe) if (qs and qe) else None
        if release is not None:                          # their chosen time is inside their quiet hours: the end of quiet hours, if that is still today
            fire = release if tu.to_local(release, tz).date() == day else None
    if fire is not None and window(fire):
        out["daily"] = (fire, f"day:{day.isoformat()}")

    if tu.local_now(tz, now).weekday() == WEEKLY_WEEKDAY:
        wf = tu.to_utc(day, tu.parse_hhmm(WEEKLY_AT), tz)
        if window(wf):
            iso = day.isocalendar()
            out["weekly"] = (wf, f"weekly:{iso[0]}-W{iso[1]:02d}")
    return out


def plan_today(snap: dict, now: dt.datetime) -> list[dict]:
    """The notifications this learner should get TODAY (their local day) that are inside their window, each as {kind, fire_at (UTC), dedupe_key,
    url}. Idempotent: the dedupe key is unique per learner, so calling this every couple of minutes never makes a second row."""
    sl = slots(snap, now)
    today = ist_date(now)
    out: list[dict] = []
    if sl["daily"] is not None and not is_paused(snap, now):
        kind = pick_daily_kind(snap, today)
        if kind:
            out.append({"kind": kind, "fire_at": sl["daily"][0], "dedupe_key": sl["daily"][1], "url": "/"})
    if sl["weekly"] is not None and weekly_due(snap, today):
        out.append({"kind": "weekly", "fire_at": sl["weekly"][0], "dedupe_key": sl["weekly"][1], "url": "/"})
    return out


def still_wanted(kind: str, snap: dict, now: dt.datetime) -> tuple[bool, str]:
    """The send-time re-check. (True, kind-to-send) or (False, why). A `test` is always wanted. The kind can change: a streak nudge whose streak
    has lapsed since the row was made goes out as a plain practice nudge (or not at all)."""
    if kind == "test":
        return True, "test"
    if not snap.get("enabled", True):
        return False, "off"
    tz = tu.norm_tz(snap.get("tz"))
    if snap.get("quiet_on", True):
        qs, qe = tu.parse_hhmm(snap.get("quiet_start") or "22:00"), tu.parse_hhmm(snap.get("quiet_end") or "07:00")
        if qs and qe and tu.in_quiet(tu.local_now(tz, now).time(), qs, qe):
            return False, "quiet"
    today = ist_date(now)
    if kind == "weekly":
        return (True, "weekly") if weekly_due(snap, today) else (False, "not_due")
    if snap.get("last_active") == today:
        return False, "done"
    if is_paused(snap, now):
        return False, "paused"
    picked = pick_daily_kind(snap, today)
    return (True, picked) if picked else (False, "off")


# ----------------------------------------------------------------------------- the words
# Hindi copy follows the house rules: Devanagari with everyday English words in Latin (the voice mispronounces romanised Hindi), तुम never तू,
# imperatives instead of gendered verb forms toward the learner (no रहे हो / सकते हो), DuSu is feminine only about herself.
COPY = {
    "practice": {
        "hi": [("DuSu", "{n}आज की practice बाकी है। बस 5 minute बोलकर देखो?"),
               ("आज English बोलना बाकी है", "{n}DuSu इंतज़ार कर रही है - 5 minute काफ़ी हैं।"),
               ("DuSu", "{n}आज थोड़ी practice कर लो? बस 5 minute।")],
        "en": [("DuSu", "{n}today's practice is still waiting. Just 5 minutes of speaking?"),
               ("Your English is waiting", "{n}DuSu is ready when you are. Five minutes is plenty."),
               ("DuSu", "{n}a quick chat today keeps your English moving.")],
    },
    "streak": {
        "hi": [("{s} दिन की streak खतरे में", "{n}आज रात टूट सकती है। 5 minute बोलकर बचा लो।"),
               ("{s} दिन की streak", "{n}आज अभी तक practice नहीं हुई। बस 5 minute बोलो, streak बची रहेगी।")],
        "en": [("Your {s}-day streak is at risk", "{n}it ends tonight. Speak for 5 minutes to keep it."),
               ("{s}-day streak", "{n}no practice yet today. Five minutes keeps it alive.")],
    },
    "weekly": {
        "hi": [("DuSu का weekly letter", "{n}इस हफ़्ते का तुम्हारा letter तैयार है। देखो DuSu ने क्या लिखा।")],
        "en": [("Your weekly note from DuSu", "{n}it is ready. See what DuSu wrote about your week.")],
    },
    "test": {
        "hi": [("DuSu test notification", "अगर यह तुम्हें दिख रहा है, तो notifications इस phone तक पहुँच रहे हैं।")],
        "en": [("DuSu test notification", "If you can read this, notifications reach this phone.")],
    },
}
HIDDEN = {"hi": ("DuSu", "तुम्हारे लिए DuSu का एक message है।"), "en": ("DuSu", "You have a message from DuSu.")}


def _pick(uid: str, day: str, n: int) -> int:
    return int(hashlib.sha1(f"{uid}|{day}".encode()).hexdigest()[:8], 16) % max(1, n)


def render(kind: str, lang: str, name: str = "", streak: int = 0, hide: bool = False, uid: str = "", day: str = "") -> tuple[str, str]:
    """(title, body) for a notification. The wording varies by learner and day (never the same sentence every day), but is deterministic for one
    learner on one day, so tests are stable. With `hide` (lock-screen privacy) nothing personal - no name, no number - is shown."""
    lg = "hi" if lang != "en" else "en"
    if hide and kind != "test":
        return HIDDEN[lg]
    variants = COPY.get(kind, COPY["practice"])[lg]
    title, body = variants[_pick(uid, day, len(variants))]
    nm = first_name(name)
    lead = (nm + (", " if lg == "en" else "। ")) if nm else ""
    title = title.replace("{s}", str(int(streak or 0)))
    body = body.replace("{n}", lead).replace("{s}", str(int(streak or 0)))
    if lg == "en" and not lead:                           # "{n}today's practice ..." with no name starts the sentence
        body = body[:1].upper() + body[1:]
    return title[:LIMITS["title"]], body[:LIMITS["body"]]


# ----------------------------------------------------------------------------- the message that is pushed
def build_payload(nid: int, title: str, body: str, url: str, ack: str) -> bytes:
    """The encrypted web-push message. No action buttons: a tap opens the app. `ack` = a signed single-purpose token the service worker sends
    back as soon as the message reaches the phone (so the dashboard can tell 'the push service accepted it' from 'it arrived')."""
    p = {"title": title, "body": body, "tag": f"nt{nid}", "data": {"nid": nid, "url": url, "ack": ack}, "actions": []}
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


_URL_OK = re.compile(r"^/[A-Za-z0-9/_\-]*$")


def safe_url(u) -> str:
    """Only an in-app path ever goes into a notification."""
    return u if isinstance(u, str) and len(u) <= 60 and _URL_OK.match(u) else "/"
