"""My Day -> DuSu: the learner's plan as a few exact lines for the "DuSu knows your data" block (life.EXTRA_LINES, DUSU_GOALS_PLAN.md §10).

DuSu READS the plan; it never claims to have changed it. Titles are the learner's own text, flattened to one quote-safe line (they land
inside a system prompt). Only registered lines for learners who have My Day (the switch is checked per learner).

Every reminder is in the context (not just the next one): a learner who asks "what are my reminders?" must hear all of them, and a day with
reminders but no tasks is not "nothing planned".
"""

from __future__ import annotations

import datetime as dt

from .. import life
from . import rules, service as svc, timeutil as tu


def _t12(iso: str | None, tz: str) -> str:
    """'6:00 PM' (the learner's local time) from an ISO instant."""
    if not iso:
        return ""
    try:
        d = tu.to_local(dt.datetime.fromisoformat(iso), tz)
    except ValueError:
        return ""
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def _hhmm12(hhmm) -> str:
    """'07:00' -> '7:00 AM'."""
    t = tu.parse_hhmm(hhmm)
    return "" if t is None else f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _day_name(iso_day: str, today_iso: str) -> str:
    """'tomorrow' / 'Mon 14 Oct' for a later day."""
    try:
        d = dt.date.fromisoformat(iso_day)
        t = dt.date.fromisoformat(today_iso)
    except (TypeError, ValueError):
        return iso_day or ""
    if d == t + dt.timedelta(days=1):
        return "tomorrow"
    return d.strftime("%a %d %b")


def _reminder_sets(t: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(waiting for their tap now, still ahead today, ahead on later days) - the learner's own reminders only, in time order."""
    today_iso = t.get("date") or ""
    rems = [x for x in (t.get("reminders") or []) if x.get("kind") != "test"]
    due = [x for x in (t.get("due") or []) if x.get("entity_type") == "custom" and x.get("kind") != "test"]
    return due, [x for x in rems if x.get("day") == today_iso], [x for x in rems if x.get("day") != today_iso]


def format_lines(t: dict) -> list[str]:
    """Pure: the `today()` payload -> the lines (no I/O, so it can be checked offline)."""
    tz = t.get("tz") or tu.DEFAULT_TZ
    c = lambda s, n=60: life._clean(s, n)
    out: list[str] = []
    cnt = t.get("counts") or {}
    open_n, over_n, done_n = int(cnt.get("open_today", 0)), int(cnt.get("overdue", 0)), int(cnt.get("done_today", 0))
    due, rem_today, rem_later = _reminder_sets(t)
    rem_n = len(due) + len(rem_today)
    items = []
    for x in (t.get("priorities") or [])[:3]:
        bit = c(x.get("title"))
        tm = x.get("due_time")
        if tm:
            bit += f" ({_t12(x.get('due_at'), tz)})"
        items.append(bit)
    if open_n or over_n or done_n:
        s = f"Today's plan (their own My Day - exact): {open_n} task{'s' if open_n != 1 else ''} left for today"
        if items:
            s += " - top: " + "; ".join(items)
        if over_n:
            s += f"; {over_n} overdue"
        if done_n:
            s += f"; {done_n} done so far today"
        if rem_n:
            s += f"; plus {rem_n} reminder{'s' if rem_n != 1 else ''} today (listed under Reminders)"
        out.append(s + ".")
    elif rem_n:
        out.append(f"Today's plan (their own My Day - exact): no tasks for today, but {rem_n} reminder{'s' if rem_n != 1 else ''} today (listed under Reminders).")
    else:
        out.append("Today's plan (their own My Day): nothing is planned for today yet.")
    # the routine in time order: timed tasks + timed habits
    timed = []
    for x in (t.get("today") or []):
        if x.get("due_time"):
            timed.append((x["due_time"], c(x.get("title"), 40)))
    for h in (t.get("habits") or []):
        for tm in ((h.get("schedule") or {}).get("times") or []):
            if h.get("scheduled_today") and h.get("state_today") not in ("done", "skipped"):
                timed.append((tm, c(h.get("title"), 40)))
    if timed:
        timed.sort()
        out.append("Today's routine in time order: " + "; ".join(f"{tm} {ti}" for tm, ti in timed[:6]) + ".")
    hb = [h for h in (t.get("habits") or []) if h.get("scheduled_today")]
    if hb:
        out.append("Habits today: " + "; ".join(f"{c(h.get('title'), 40)} {h.get('count_today', 0)} of {h.get('target', 1)}"
                                                  + (f" {c(h.get('unit'), 12)}" if h.get("unit") else "") for h in hb[:4]) + ".")
    gl = []
    for g in (t.get("goals") or [])[:2]:
        s = f"{c(g.get('title'), 50)} {g.get('progress', 0)}%"
        nm = g.get("next_milestone")
        if nm:
            s += f", next milestone '{c(nm.get('title'), 40)}'" + (f" due {nm['due_date']}" if nm.get("due_date") else "")
        if g.get("behind_days"):
            s += f", about {g['behind_days']} days behind"
        gl.append(s)
    if gl:
        out.append("Goals: " + "; ".join(gl) + ".")
    # EVERY reminder the learner set, in time order - the one rule is that none is left out when they ask for the list
    if due or rem_today or rem_later:
        parts = []
        if due:
            parts.append("waiting for their tap right now - " + "; ".join(f"{c(x.get('title'))} (was due {_t12(x.get('fire_at'), tz)})" for x in due[:5]))
        if rem_today:
            parts.append("still ahead today - " + "; ".join(f"{_t12(x.get('fire_at'), tz)} {c(x.get('title'))}" for x in rem_today[:8]))
        if rem_later:
            parts.append("later - " + "; ".join(f"{_day_name(x.get('day') or '', t.get('date') or '')} {_t12(x.get('fire_at'), tz)} {c(x.get('title'))}" for x in rem_later[:5]))
        out.append(f"Reminders (their own My Day - exact, {len(due) + len(rem_today) + len(rem_later)} in all; when asked, read EVERY one, in this order): " + ". ".join(parts) + ".")
    elif any(isinstance(x, dict) and x.get("status") == "active" for x in (t.get("repeating") or [])):
        out.append("Reminders: nothing is due in the next two days (their repeating reminders are listed next).")
    else:
        out.append("Reminders: none set.")
    # the repeating ones are set ONCE and ring on their days until the learner deletes or pauses them - listed whole, because only the next two days
    # of rings exist as individual reminders, so a Saturday-only one is not above on a Monday
    rep = [x for x in (t.get("repeating") or []) if isinstance(x, dict) and x.get("title")]
    if rep:
        bits = []
        for x in rep[:8]:
            bit = f"{c(x.get('title'))} - {rules.days_text(x.get('days'), 'en') or 'no days'} at {_hhmm12(x.get('time')) or '?'}"
            if x.get("status") != "active":
                bit += " (paused - not ringing)"
            bits.append(bit)
        out.append(f"Repeating reminders (their own, set once - each rings again on its days until they delete or pause it; exact, {len(rep)} in all): "
                   + "; ".join(bits) + ".")
    out.append("You can NOT add, change or complete their tasks or reminders from a conversation. If they want to, tell them to open My Day and tap +; "
               "never say you added, saved or set a reminder.")
    return out


def plan_text(t: dict, lang: str) -> str | None:
    """Pure: ONE short line DuSu says at the start of a Home conversation about the learner's day - exact, nothing invented, no model involved.
    None when there is nothing to say (an empty day is not announced). Hindi = Devanagari with everyday English words in Latin; the learner's own
    reminder / task titles are read as they typed them. No gendered forms toward the learner."""
    tz = t.get("tz") or tu.DEFAULT_TZ
    c = lambda s, n=48: life._clean(s, n)
    cnt = t.get("counts") or {}
    open_n, over_n = int(cnt.get("open_today", 0)), int(cnt.get("overdue", 0))
    due, rem_today, rem_later = _reminder_sets(t)
    waiting = [c(x.get("title")) for x in due]                                         # fired and still waiting for a tap
    ahead = [(_t12(x.get("fire_at"), tz), c(x.get("title"))) for x in rem_today]
    hi = lang != "en"
    end = "।" if hi else "."
    bits: list[str] = []
    if waiting:
        names = "; ".join(waiting[:2]) + (f" (+{len(waiting) - 2})" if len(waiting) > 2 else "")
        one = len(waiting) == 1
        bits.append(f"अभी {len(waiting)} reminder इंतज़ार में {'है' if one else 'हैं'}: {names}{end}" if hi
                    else f"{len(waiting)} reminder{' is' if one else 's are'} waiting for you right now: {names}{end}")
    if ahead:
        shown = ahead[:3]
        listed = "; ".join(f"{tm} - {ti}" if hi else f"{tm}, {ti}" for tm, ti in shown)
        more, one = len(ahead) - len(shown), len(ahead) == 1
        if hi:
            bits.append(f"आज आगे {len(ahead)} reminder{'' if one else 's'} {'है' if one else 'हैं'}: {listed}" + (f", और {more} और" if more else "") + end)
        else:
            bits.append(f"{len(ahead)} {'more ' if waiting else ''}reminder{'' if one else 's'} today: {listed}" + (f", and {more} more" if more else "") + end)   # "more" only after a waiting one was mentioned
    elif not waiting and rem_later:
        x = rem_later[0]
        when = f"{_day_name(x.get('day') or '', t.get('date') or '')} {_t12(x.get('fire_at'), tz)}".strip()
        bits.append(f"आज कोई reminder नहीं है; अगला {when} को है: {c(x.get('title'))}{end}" if hi
                    else f"No reminders today; the next one is {when}: {c(x.get('title'))}{end}")
    if open_n:
        bits.append(f"आज {open_n} task{'' if open_n == 1 else 's'} बाक़ी {'है' if open_n == 1 else 'हैं'}{end}" if hi
                    else f"{open_n} task{'s' if open_n != 1 else ''} left today{end}")
    if over_n:
        bits.append(f"{over_n} पुराना task भी बाक़ी {'है' if over_n == 1 else 'हैं'}{end}" if hi
                    else f"{over_n} task{'s' if over_n != 1 else ''} overdue{end}")
    if not bits:
        return None
    head = "तुम्हारे दिन की एक छोटी झलक: " if hi else "A quick look at your day: "
    tail = " चाहो तो पूरी list पूछ लो।" if hi else " Ask me for the full list any time."
    return head + " ".join(bits) + tail


async def planner_lines(uid: str, email: str = "") -> list[str]:
    from .. import main as M          # lazy: main.py imports this module
    if not await M.planner_enabled(email):
        return []
    return format_lines(await svc.today(uid))


async def opening_plan(uid: str) -> dict | None:
    """What DuSu says about the learner's day right after her greeting on Start Speaking: {"hi": ..., "en": ...} (each may be None) or None when the
    day is empty. The caller has already checked the My Day switch and the learner's privacy choice."""
    t = await svc.today(uid)
    hi, en = plan_text(t, "hi"), plan_text(t, "en")
    return {"hi": hi, "en": en} if (hi or en) else None


def register() -> None:
    if planner_lines not in life.EXTRA_LINES:
        life.EXTRA_LINES.append(planner_lines)
