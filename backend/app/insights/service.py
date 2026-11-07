"""Insights - what the owner can learn about the first-run path, without watching anyone.

Design rules (they are the privacy story, so they are tested):
  * a fixed ALLOW-LIST of event names - the client cannot invent one, and an unknown name is dropped silently;
  * a milestone is written ONCE per learner (the first time) and never again, so the table is bounded by (learners x ~10);
  * one row per learner per active day - bounded by (learners x days);
  * the hot path costs a set lookup: once a (learner, milestone) pair is known in memory nothing touches the database again in this process;
  * nothing here can fail a request: every write swallows its error and logs the CLASS NAME only (SQLAlchemy messages carry bound parameters);
  * no text, no key, no transcript, no IP - a name, a time and a learner id, deleted with the account.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import db
from .models import EvDay, EvMilestone, PlanInterest

PLANS = ("starter", "plus", "pro")
FEELS = ("", "too_high", "fair", "great")

# What only the CLIENT can know (a screen was opened). Everything else is recorded by the server where it happens.
CLIENT_EVENTS = ("keys_seen", "plans_seen", "install_accepted")
SERVER_EVENTS = ("key1_saved", "key2_saved", "first_sentence", "first_session", "plan_reserved")
MILESTONES = CLIENT_EVENTS + SERVER_EVENTS
# The order the owner reads the funnel in (install is a side branch, shown last).
FUNNEL_ORDER = ("keys_seen", "key1_saved", "key2_saved", "first_sentence", "first_session", "plans_seen", "plan_reserved", "install_accepted")
LABELS = {
    "keys_seen": "Saw the keys screen", "key1_saved": "Saved a first key", "key2_saved": "Saved a second key",
    "first_sentence": "Said a first sentence", "first_session": "Finished a first session",
    "plans_seen": "Opened the plans", "plan_reserved": "Reserved a plan", "install_accepted": "Installed the app",
}

_CAP = 50_000                                   # the in-memory dedupe sets are bounded; a clear only costs one extra (idempotent) write per learner
_seen: set[tuple[str, str]] = set()
_day_seen: dict[str, str] = {}
_tasks: set = set()
_failed = 0                                     # writes that could not be made (reported to the owner, never raised)


def seen() -> set:
    return _seen


def day_seen() -> dict:
    return _day_seen


def failures() -> int:
    return _failed


def _fail(e: Exception) -> None:
    global _failed
    _failed += 1
    print(f"[insights] write failed: {type(e).__name__}")


def spawn(coro) -> None:
    """Run a coroutine in the background with a retained reference (a bare create_task can be garbage collected mid-flight)."""
    try:
        t = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def milestone(uid: str | None, name: str) -> bool:
    """Record that this learner reached `name` for the first time. True only when a new row was written; never raises."""
    if not (uid and db.db_enabled) or name not in MILESTONES:
        return False
    k = (uid, name)
    if k in _seen:
        return False
    try:
        async with db._Session() as s:                      # type: ignore[misc]
            r = await s.execute(pg_insert(EvMilestone).values(user_id=uid, name=name, first_at=db._now())
                                .on_conflict_do_nothing(index_elements=["user_id", "name"]))
            await s.commit()
        fresh = bool(r.rowcount)
    except Exception as e:                                  # an FK violation (a learner deleted a moment ago) lands here too
        _fail(e)
        return False
    if len(_seen) >= _CAP:
        _seen.clear()
    _seen.add(k)
    return fresh


async def touch_day(uid: str | None, day: str) -> bool:
    """The learner opened the app on `day` (India time). One write per learner per day per process."""
    if not (uid and db.db_enabled) or not day or _day_seen.get(uid) == day:
        return False
    try:
        async with db._Session() as s:                      # type: ignore[misc]
            r = await s.execute(pg_insert(EvDay).values(user_id=uid, day=day).on_conflict_do_nothing(index_elements=["user_id", "day"]))
            await s.commit()
        fresh = bool(r.rowcount)
    except Exception as e:
        _fail(e)
        return False
    if len(_day_seen) >= _CAP:
        _day_seen.clear()
    _day_seen[uid] = day
    return fresh


# ------------------------------------------------------------------------------------------------------------------------- plan interest
def clean_plan(v) -> str | None:
    """One of the three plan names (any case, surrounding spaces trimmed) or None. Only a string counts: a list, a dict or a number is never a plan."""
    if not isinstance(v, str):
        return None
    p = v.strip().lower()
    return p if p in PLANS else None


def clean_feel(v) -> str | None:
    """'' (no opinion - also what a missing field means), too_high, fair or great; anything else is None (the endpoint answers 422). Only None or a string is accepted:
    `[]` or `{}` is a malformed request, not "no opinion"."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return None
    f = v.strip().lower()
    return f if f in FEELS else None


async def reserve_plan(uid: str, plan: str, feel: str = "") -> dict:
    """Store (or update) one learner's interest in one plan. Idempotent: tapping twice is one row. Returns what they have reserved."""
    now = db._now()
    async with db._Session() as s:                          # type: ignore[misc]
        stmt = pg_insert(PlanInterest).values(user_id=uid, plan=plan, price_feel=feel, created_at=now, updated_at=now)
        # a repeat tap keeps the first time; a price opinion only ever REPLACES a blank or an older opinion (never erases one)
        upd = {"updated_at": now}
        if feel:
            upd["price_feel"] = feel
        await s.execute(stmt.on_conflict_do_update(index_elements=["user_id", "plan"], set_=upd))
        await s.commit()
    return {"reserved": await my_plans(uid)}


async def my_plans(uid: str) -> list[dict]:
    async with db._Session() as s:                          # type: ignore[misc]
        rows = (await s.execute(select(PlanInterest).where(PlanInterest.user_id == uid).order_by(PlanInterest.created_at))).scalars().all()
    return [{"plan": r.plan, "price_feel": r.price_feel or ""} for r in rows]


# ------------------------------------------------------------------------------------------------------------------------- the owner's view
def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


async def funnel(days: int = 30) -> dict:
    """The owner's funnel for learners who signed up in the last `days` days AND after tracking began (so a ratio never divides by people we could not have seen)."""
    days = max(1, min(int(days), 365))
    now = db._now()
    window_start = now - dt.timedelta(days=days)
    async with db._Session() as s:                          # type: ignore[misc]
        first_ms = (await s.execute(select(func.min(EvMilestone.first_at)))).scalar()
        first_day = (await s.execute(select(func.min(EvDay.day)))).scalar()
        starts = [x for x in (first_ms,) if x]
        if first_day:
            starts.append(dt.datetime.fromisoformat(first_day).replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))))
        tracking_since = min(starts) if starts else None
        cohort_from = max(window_start, tracking_since) if tracking_since else window_start
        signups_all = (await s.execute(select(func.count()).select_from(db.User).where(db.User.created_at >= window_start))).scalar_one()
        cohort = (await s.execute(select(func.count()).select_from(db.User).where(db.User.created_at >= cohort_from))).scalar_one()
        rows = (await s.execute(
            select(EvMilestone.name, func.count()).join(db.User, db.User.id == EvMilestone.user_id)
            .where(db.User.created_at >= cohort_from).group_by(EvMilestone.name))).all()
        reached = {n: int(c) for n, c in rows}
        out_ms = [{"name": n, "label": LABELS.get(n, n), "learners": reached.get(n, 0), "pct": _pct(reached.get(n, 0), cohort)} for n in FUNNEL_ORDER]

        ret = {}
        for n in (1, 7):
            q = text("""
                SELECT count(*) AS eligible,
                       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ev_days d WHERE d.user_id = u.id
                            AND d.day = to_char((u.created_at AT TIME ZONE 'Asia/Kolkata')::date + CAST(:n AS integer), 'YYYY-MM-DD'))) AS returned
                FROM users u
                WHERE u.created_at >= :start
                  AND (u.created_at AT TIME ZONE 'Asia/Kolkata')::date + CAST(:n AS integer) < (now() AT TIME ZONE 'Asia/Kolkata')::date""")
            r = (await s.execute(q, {"n": n, "start": cohort_from})).one()
            ret[f"d{n}"] = {"eligible": int(r.eligible), "returned": int(r.returned), "pct": _pct(int(r.returned), int(r.eligible))}

        ist_today = (await s.execute(text("SELECT to_char((now() AT TIME ZONE 'Asia/Kolkata')::date, 'YYYY-MM-DD')"))).scalar_one()
        dau = (await s.execute(select(func.count()).select_from(EvDay).where(EvDay.day == ist_today))).scalar_one()
        wau = (await s.execute(text("SELECT count(DISTINCT user_id) FROM ev_days WHERE day >= to_char((now() AT TIME ZONE 'Asia/Kolkata')::date - 6, 'YYYY-MM-DD')"))).scalar_one()

        prows = (await s.execute(select(PlanInterest.plan, PlanInterest.price_feel, func.count()).group_by(PlanInterest.plan, PlanInterest.price_feel))).all()
        plans = {p: {"learners": 0, "too_high": 0, "fair": 0, "great": 0} for p in PLANS}
        for plan, feel, c in prows:
            if plan in plans:
                plans[plan]["learners"] += int(c)
                if feel in ("too_high", "fair", "great"):
                    plans[plan][feel] += int(c)
    return {"window_days": days, "tracking_since": tracking_since.isoformat() if tracking_since else None, "signups_in_window": int(signups_all), "cohort": int(cohort),
            "milestones": out_ms, "retention": ret, "active": {"today": int(dau), "last_7_days": int(wau)}, "plans": plans, "write_failures": _failed}


# ------------------------------------------------------------------------------------------------------------------------- data rights
async def delete_rows(s, uids: list) -> None:
    """Delete every insights row for these learners, inside the caller's transaction (account deletion and the owner's wipe call this)."""
    for M in (EvMilestone, EvDay, PlanInterest):
        await s.execute(delete(M).where(M.user_id.in_(uids)))
    for u in uids:
        _day_seen.pop(u, None)
        for n in MILESTONES:
            _seen.discard((u, n))
