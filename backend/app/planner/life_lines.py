"""My Day -> DuSu: the learner's plan as a few exact lines for the "DuSu knows your data" block (life.EXTRA_LINES, DUSU_GOALS_PLAN.md §10).

DuSu READS the plan; it never claims to have changed it. Titles are the learner's own text, flattened to one quote-safe line (they land
inside a system prompt). Only registered lines for learners who have My Day (the switch is checked per learner).
"""

from __future__ import annotations

from .. import life
from . import service as svc, timeutil as tu


def _t12(iso: str | None, tz: str) -> str:
    """'6:00 PM' (the learner's local time) from an ISO instant."""
    import datetime as dt
    if not iso:
        return ""
    try:
        d = tu.to_local(dt.datetime.fromisoformat(iso), tz)
    except ValueError:
        return ""
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def format_lines(t: dict) -> list[str]:
    """Pure: the `today()` payload -> the lines (no I/O, so it can be checked offline)."""
    tz = t.get("tz") or tu.DEFAULT_TZ
    c = lambda s, n=60: life._clean(s, n)
    out: list[str] = []
    cnt = t.get("counts") or {}
    open_n, over_n, done_n = int(cnt.get("open_today", 0)), int(cnt.get("overdue", 0)), int(cnt.get("done_today", 0))
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
        out.append(s + ".")
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
    nr = t.get("next_reminder")
    if nr:
        out.append(f"Next reminder: {_t12(nr.get('fire_at'), tz)} - {c(nr.get('title'), 60)}.")
    out.append("You can NOT add, change or complete their tasks from a conversation. If they want to, tell them to open My Day and tap +; "
               "never say you added, saved or set a reminder.")
    return out


async def planner_lines(uid: str, email: str = "") -> list[str]:
    from .. import main as M          # lazy: main.py imports this module
    if not await M.planner_enabled(email):
        return []
    return format_lines(await svc.today(uid))


def register() -> None:
    if planner_lines not in life.EXTRA_LINES:
        life.EXTRA_LINES.append(planner_lines)
