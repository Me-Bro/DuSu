"""My Day - time helpers: the learner's own IANA timezone, DST-safe wall clock -> UTC, recurrence, quiet hours.

Pure functions: no database, no network, no clock except the optional `now` argument (so every rule can be tested with a fake clock).
The rest of DuSu runs on one fixed IST day boundary; a reminder is a wall-clock promise ("9:00 PM, wherever I am"), so the planner keeps
a per-user timezone of its own (DUSU_GOALS_PLAN.md D7) and leaves the app-wide IST logic alone.

DST policy (documented and tested): a local time that does not exist (the spring-forward gap) is read with the offset in force just
BEFORE the gap, i.e. it lands one gap-length later (02:30 -> 03:30); a local time that happens twice (the fall-back overlap) is the
EARLIER occurrence, so a reminder fires once.
"""

from __future__ import annotations

import calendar
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Kolkata"
UTC = dt.timezone.utc
END_OF_DAY = dt.time(23, 59, 59)          # a date-only task is due at the end of its local day
MAX_INTERVAL = 30
MAX_SCAN_DAYS = 3660                      # a `count` rule is evaluated over at most ten years


def norm_tz(name) -> str:
    """A valid IANA name, or the default. Never raises (the value comes from a browser / a request body)."""
    if isinstance(name, str) and 1 < len(name) <= 64 and not name.startswith("/") and ".." not in name:
        try:
            ZoneInfo(name)
            return name
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return DEFAULT_TZ


def zone(name) -> ZoneInfo:
    return ZoneInfo(norm_tz(name))


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def local_now(tz, now=None) -> dt.datetime:
    return (now or now_utc()).astimezone(zone(tz))


def local_today(tz, now=None) -> dt.date:
    return local_now(tz, now).date()


def parse_hhmm(s) -> dt.time | None:
    """'9:30', '09:30', '21:05' -> time; anything else -> None."""
    if isinstance(s, dt.time):
        return s.replace(second=0, microsecond=0, tzinfo=None)
    if not isinstance(s, str):
        return None
    p = s.strip().split(":")
    if len(p) != 2 or not (p[0].isdigit() and p[1].isdigit()) or len(p[0]) > 2 or len(p[1]) != 2:
        return None
    h, m = int(p[0]), int(p[1])
    return dt.time(h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def fmt_hhmm(t: dt.time | None) -> str | None:
    return None if t is None else f"{t.hour:02d}:{t.minute:02d}"


def parse_date(s) -> dt.date | None:
    if isinstance(s, dt.datetime):
        return s.date()
    if isinstance(s, dt.date):
        return s
    if isinstance(s, str):
        try:
            return dt.date.fromisoformat(s.strip()[:10])
        except ValueError:
            return None
    return None


def to_utc(day: dt.date, t: dt.time, tz) -> dt.datetime:
    """A local wall-clock moment in `tz` -> UTC (DST policy above)."""
    return dt.datetime.combine(day, t, tzinfo=zone(tz)).astimezone(UTC)


def resolve_fire(day_in: dt.date | None, t: dt.time, tz, now: dt.datetime | None = None) -> tuple[dt.datetime, bool]:
    """When a reminder entered as (day, time of day) fires (UTC), and whether it was moved to the next day it comes round. A learner who types 7:00
    at 15:00 means the NEXT 7:00 - that is not a mistake to refuse (it used to be a 422 "That time has already passed", nine times in one afternoon).
    So: when the day is today (or missing, or yesterday because the phone is in another zone) and the time has passed, it is the next day's;
    only an explicit day before that is "past" (ValueError)."""
    now = now or now_utc()
    today = local_today(tz, now)
    d = day_in or today
    if d < today - dt.timedelta(days=1):
        raise ValueError("past")
    fire = to_utc(d, t, tz)
    if fire >= now - dt.timedelta(minutes=1):
        return fire, False
    nd = d + dt.timedelta(days=1)
    while to_utc(nd, t, tz) < now - dt.timedelta(minutes=1) and nd <= today + dt.timedelta(days=1):
        nd += dt.timedelta(days=1)
    return to_utc(nd, t, tz), True


def end_of_day_utc(day: dt.date, tz) -> dt.datetime:
    return to_utc(day, END_OF_DAY, tz)


def to_local(when: dt.datetime, tz) -> dt.datetime:
    return when.astimezone(zone(tz))


def day_bounds_utc(day: dt.date, tz) -> tuple[dt.datetime, dt.datetime]:
    """[start, end) of a local calendar day, in UTC (a DST day is 23 or 25 hours long - that is why this is not 'start + 24 h')."""
    return to_utc(day, dt.time(0, 0), tz), to_utc(day + dt.timedelta(days=1), dt.time(0, 0), tz)


# ----------------------------------------------------------------------------- quiet hours
def in_quiet(local_t: dt.time, start: dt.time, end: dt.time) -> bool:
    """Is a local clock time inside [start, end)? A window that crosses midnight (22:00-07:00) is handled; start == end = no window."""
    if start == end:
        return False
    if start < end:
        return start <= local_t < end
    return local_t >= start or local_t < end


def quiet_release_utc(fire_utc: dt.datetime, tz, start: dt.time, end: dt.time) -> dt.datetime | None:
    """If `fire_utc` falls in the learner's quiet hours, the UTC moment the quiet window ends (when to send instead); else None."""
    loc = to_local(fire_utc, tz)
    if not in_quiet(loc.time().replace(second=0, microsecond=0), start, end):
        return None
    day = loc.date()
    if start >= end and loc.time() >= start:        # evening part of a midnight-crossing window -> release tomorrow morning
        day = day + dt.timedelta(days=1)
    release = to_utc(day, end, tz)
    return release if release > fire_utc else release + dt.timedelta(days=1)


# ----------------------------------------------------------------------------- recurrence
FREQS = ("daily", "weekly", "monthly")


def clean_rule(rule) -> dict | None:
    """A repeat rule from a request body -> a clamped, canonical rule, or None (not a repeat / unusable).
    {freq: daily|weekly|monthly, interval: 1..30, byday: [0..6 Mon=0], bymonthday: 1..31, until: 'YYYY-MM-DD', count: 1..1000, time: 'HH:MM'}"""
    if not isinstance(rule, dict) or rule.get("freq") not in FREQS:
        return None
    try:
        interval = int(rule.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 1
    out: dict = {"freq": rule["freq"], "interval": max(1, min(MAX_INTERVAL, interval))}
    by = rule.get("byday")
    if isinstance(by, (list, tuple)):
        days = sorted({int(x) for x in by if isinstance(x, (int, str)) and str(x).isdigit() and 0 <= int(x) <= 6})
        if days:
            out["byday"] = days
    try:
        bm = int(rule["bymonthday"]) if rule.get("bymonthday") not in (None, "") else None
    except (TypeError, ValueError):
        bm = None
    if bm is not None and 1 <= bm <= 31:
        out["bymonthday"] = bm
    u = parse_date(rule.get("until"))
    if u:
        out["until"] = u.isoformat()
    try:
        c = int(rule["count"]) if rule.get("count") not in (None, "") else None
    except (TypeError, ValueError):
        c = None
    if c is not None and c >= 1:
        out["count"] = min(c, 1000)
    t = parse_hhmm(rule.get("time"))
    if t:
        out["time"] = fmt_hhmm(t)
    return out


def _months_between(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def occurs_on(rule: dict, start: dt.date, day: dt.date) -> bool:
    """Does the rule produce an occurrence on `day`, ignoring `count` (see occurrences() for that)?"""
    if day < start:
        return False
    until = parse_date(rule.get("until"))
    if until and day > until:
        return False
    interval = max(1, int(rule.get("interval") or 1))
    f = rule["freq"]
    if f == "daily":
        return (day - start).days % interval == 0
    if f == "weekly":
        by = rule.get("byday") or [start.weekday()]
        monday0 = start - dt.timedelta(days=start.weekday())
        weeks = (day - dt.timedelta(days=day.weekday()) - monday0).days // 7
        return day.weekday() in by and weeks % interval == 0
    if f == "monthly":
        bm = int(rule.get("bymonthday") or start.day)
        last = calendar.monthrange(day.year, day.month)[1]
        return _months_between(start, day) % interval == 0 and day.day == min(bm, last)
    return False


def occurrences(rule: dict, start: dt.date, lo: dt.date, hi: dt.date, limit: int = 400) -> list[dt.date]:
    """The occurrence dates in [lo, hi], honouring `count` (counted from `start`) and `until`. A day-31 monthly rule clamps to the month end."""
    out: list[dt.date] = []
    count = rule.get("count")
    d, n = start, 0
    end = min(hi, start + dt.timedelta(days=MAX_SCAN_DAYS))
    if not count:
        d = max(start, lo)                       # no need to walk from `start` when nothing is being counted
    while d <= end and len(out) < limit:
        if occurs_on(rule, start, d):
            n += 1
            if count and n > int(count):
                break
            if d >= lo:
                out.append(d)
        d += dt.timedelta(days=1)
    return out


def describe_rule(rule: dict | None, lang: str = "en") -> str:
    """A short human label for a rule ('Every day', 'Every 2 weeks on Mon, Wed') - the UI has its own copy; this is for notifications / DuSu."""
    if not rule:
        return ""
    hi = lang == "hi"
    names = (("सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि") if hi else ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    n = int(rule.get("interval") or 1)
    f = rule["freq"]
    if f == "daily":
        return (("हर दिन" if n == 1 else f"हर {n} दिन") if hi else ("Every day" if n == 1 else f"Every {n} days"))
    if f == "weekly":
        days = ", ".join(names[i] for i in (rule.get("byday") or []))
        base = ("हर हफ़्ते" if n == 1 else f"हर {n} हफ़्ते") if hi else ("Every week" if n == 1 else f"Every {n} weeks")
        return base + (f" ({days})" if days else "")
    return ("हर महीने" if n == 1 else f"हर {n} महीने") if hi else ("Every month" if n == 1 else f"Every {n} months")
