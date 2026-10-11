"""My Day - rules: input cleaning, limits, task status, goal progress, habit schedule / consistency.

Pure functions (no database, no network): every number the screens and DuSu show is computed here from plain values, so it can be checked
offline (DUSU_GOALS_PLAN.md §5.2 / §5.5). Missed is a neutral word - nothing here produces "failed".
"""

from __future__ import annotations

import datetime as dt
import re

from . import timeutil as tu

LIMITS = {"goals": 10, "tasks": 500, "habits": 30, "creates_per_day": 100, "push_devices": 5, "reschedules": 20,
          "pins_per_day": 3, "list": 100, "milestones": 12, "reminders_per_hour": 20, "custom_reminders": 50}
DUE_SOON_HOURS = 3
DEFAULT_TASK_MINUTES = 25
PRIORITIES = (1, 2, 3)                         # 1 low · 2 normal · 3 high
REMIND_MODES = ("none", "at_due", "before_15", "before_60", "custom")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ----------------------------------------------------------------------------- cleaning
def clean_str(s, n: int) -> str:
    """One line of user text: control characters out, whitespace collapsed, capped. Non-strings -> ''."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", _CTRL.sub("", s)).strip()[:n]


def clean_notes(s, n: int = 1000) -> str:
    """Notes may span lines; everything else is stripped the same way."""
    if not isinstance(s, str):
        return ""
    return _CTRL.sub("", s).replace("\r\n", "\n").replace("\r", "\n").strip()[:n]


def clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        if isinstance(v, bool):
            raise ValueError
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def clean_priority(v, default: int = 2) -> int:
    p = clamp_int(v, 1, 3, default)
    return p


def clean_remind(v) -> str:
    return v if v in REMIND_MODES else "none"


# ----------------------------------------------------------------------------- tasks
def derive_state(status: str, due_at: dt.datetime | None, now: dt.datetime) -> str:
    """done | skipped | overdue | due_soon | upcoming (a snooze is a chip on top of 'upcoming', not a state)."""
    if status in ("done", "skipped"):
        return status
    if due_at is None:
        return "upcoming"
    if due_at < now:
        return "overdue"
    if due_at <= now + dt.timedelta(hours=DUE_SOON_HOURS):
        return "due_soon"
    return "upcoming"


def task_due(due_date, due_time, tz) -> tuple[dt.date | None, bool, dt.datetime | None]:
    """(local date, has_time, UTC due moment) from a request's date + 'HH:MM'. No date -> no due. A date without a time = end of that local day."""
    d = tu.parse_date(due_date)
    if d is None:
        return None, False, None
    t = tu.parse_hhmm(due_time)
    if t is None:
        return d, False, tu.end_of_day_utc(d, tz)
    return d, True, tu.to_utc(d, t, tz)


# ----------------------------------------------------------------------------- goals
def milestone_fraction(status: str, done: int, total: int) -> float:
    if status == "done":
        return 1.0
    if status == "skipped":
        return 0.0
    return (done / total) if total > 0 else 0.0


def goal_progress(fractions: list[float], goal_done: bool = False) -> int:
    """round(100 * mean(fractions)), capped at 99 until the goal itself is marked done."""
    if goal_done:
        return 100
    if not fractions:
        return 0
    return min(99, int(round(100.0 * sum(fractions) / len(fractions))))


def expected_progress(start: dt.date | None, target: dt.date | None, today: dt.date) -> float | None:
    if not start or not target or target <= start:
        return None
    return max(0.0, min(1.0, (today - start).days / (target - start).days))


def behind_days(actual_pct: int, start: dt.date | None, target: dt.date | None, today: dt.date) -> int:
    """How many days behind the straight-line pace, shown only when >= 2 (a smaller gap is noise); 0 otherwise."""
    exp = expected_progress(start, target, today)
    if exp is None or not start or not target:
        return 0
    gap = (exp - actual_pct / 100.0) * (target - start).days
    return int(round(gap)) if gap >= 2 else 0


# ----------------------------------------------------------------------------- habits
def clean_schedule(sch) -> dict:
    """{"days": "daily" | [0..6] (Mon=0), "times": ["HH:MM", ...] up to 4}. Unusable input -> daily, no times."""
    sch = sch if isinstance(sch, dict) else {}
    days = sch.get("days")
    if isinstance(days, (list, tuple)):
        ds = sorted({int(x) for x in days if isinstance(x, (int, str)) and str(x).isdigit() and 0 <= int(x) <= 6})
        days = ds if 0 < len(ds) < 7 else "daily"
    else:
        days = "daily"
    times = []
    for x in (sch.get("times") if isinstance(sch.get("times"), (list, tuple)) else []):
        t = tu.parse_hhmm(x)
        if t and tu.fmt_hhmm(t) not in times:
            times.append(tu.fmt_hhmm(t))
    return {"days": days, "times": sorted(times)[:4]}


def habit_scheduled(schedule: dict, start: dt.date | None, end: dt.date | None, day: dt.date) -> bool:
    if start and day < start:
        return False
    if end and day > end:
        return False
    days = (schedule or {}).get("days", "daily")
    return True if days == "daily" else day.weekday() in days


def day_value(count: int, target: int, partial_ok: bool, state: str) -> float | None:
    """What one scheduled day contributes to consistency: 1.0 met, a fraction when partial credit is on, 0 otherwise; None = a day the
    learner chose to skip (left out of the average - skipping on purpose is not a miss)."""
    if state == "skipped":
        return None
    target = max(1, target)
    if count >= target:
        return 1.0
    return (count / target) if (partial_ok and count > 0) else 0.0


def consistency(logs: dict, schedule: dict, start: dt.date | None, end: dt.date | None, target: int, partial_ok: bool,
                today: dt.date, window: int = 14) -> int | None:
    """Consistency % over the last `window` days (today included): the mean of day_value over scheduled days. None when nothing was scheduled.
    `logs` = {date: (count, state)}. Today only counts once it is met - an open day is not a miss yet."""
    vals: list[float] = []
    for i in range(window):
        d = today - dt.timedelta(days=i)
        if not habit_scheduled(schedule, start, end, d):
            continue
        count, state = logs.get(d, (0, "logged"))
        v = day_value(int(count), target, partial_ok, state)
        if v is None:
            continue
        if d == today and v < 1.0 and not (partial_ok and count > 0):
            continue                      # today is still open
        vals.append(v)
    return None if not vals else int(round(100.0 * sum(vals) / len(vals)))


def day_status(count: int, target: int, state: str, scheduled: bool, day: dt.date, today: dt.date) -> str:
    """off (not scheduled) | future | skipped | done | partial | missed | open (today, not met yet)."""
    if not scheduled:
        return "off"
    if day > today:
        return "future"
    if state == "skipped":
        return "skipped"
    if count >= max(1, target):
        return "done"
    if count > 0:
        return "partial" if day != today else "open"
    return "open" if day == today else "missed"


def streak(logs: dict, schedule: dict, start: dt.date | None, end: dt.date | None, target: int, today: dt.date, cap: int = 400) -> int:
    """Consecutive scheduled days, newest first, on which the target was met. Today does not break the run while it is still open; a day
    the learner skipped on purpose neither extends nor breaks it."""
    n = 0
    for i in range(cap):
        d = today - dt.timedelta(days=i)
        if start and d < start:
            break
        if not habit_scheduled(schedule, start, end, d):
            continue
        count, state = logs.get(d, (0, "logged"))
        if state == "skipped":
            continue
        if int(count) >= max(1, target):
            n += 1
        elif d == today:
            continue
        else:
            break
    return n
