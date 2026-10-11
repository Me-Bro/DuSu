"""My Day - the service layer: every read / write of the planner tables (DUSU_GOALS_PLAN.md §5, §6).

Rules this file keeps (each is tested on a scratch Postgres):
  * every query filters on `user_id`; an id that is not yours is "not found" (never "forbidden", so ids cannot be probed);
  * create / log / complete / skip / act are IDEMPOTENT - a retried request returns the same state and writes no second event;
  * a completed / skipped / deleted / rescheduled / paused entity has its pending reminders CANCELLED in the same transaction;
  * titles, notes and goal text are the learner's own data and never reach a log line.
Functions open their own session and commit; they return plain dicts ready for JSON.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from .. import db
from . import rules, timeutil as tu
from .models import (PlEvent, PlGoal, PlHabit, PlHabitLog, PlMilestone, PlPrefs, PlPushSub, PlReminder, PlTask, PL_TABLES)

UTC = dt.timezone.utc
STALE_MIN = 120                 # a reminder this late (the server was down) is shown in the app only, never pushed
TERMINAL = ("done", "skipped", "expired", "cancelled")
OPEN_REMINDER = ("waiting", "scheduled", "sending", "sent")


class NotFound(Exception):
    pass


class Invalid(Exception):
    """A request the learner can fix. `args[0]` is a short code the client maps to its own words."""


class LimitReached(Exception):
    pass


def _S():
    return db._Session()          # type: ignore[misc]


def _utc() -> dt.datetime:
    return tu.now_utc()


def _iso(d) -> str | None:
    return d.isoformat() if d is not None else None


def _ev(s, uid: str, etype: str, eid: int | None, event: str, meta: dict | None = None) -> None:
    s.add(PlEvent(user_id=uid, entity_type=etype, entity_id=eid, event_type=event, meta=meta or {}))


async def _prefs(s, uid: str) -> PlPrefs:
    p = await s.get(PlPrefs, uid)
    if p is None:
        p = PlPrefs(user_id=uid, tz=tu.DEFAULT_TZ, quiet_on=True, quiet_start="22:00", quiet_end="07:00", followups=1, followup_gap_min=30,
                    snooze_min=30, push_on=False, hide_details=False, paused_all=False, english_habit=True, english_target_min=15, extra={})
        s.add(p)
        await s.flush()
    return p


def prefs_json(p: PlPrefs) -> dict:
    return {"tz": p.tz, "quiet_on": bool(p.quiet_on), "quiet_start": p.quiet_start, "quiet_end": p.quiet_end, "followups": p.followups,
            "followup_gap_min": p.followup_gap_min, "snooze_min": p.snooze_min, "push_on": bool(p.push_on), "hide_details": bool(p.hide_details),
            "paused_all": bool(p.paused_all), "english_habit": bool(p.english_habit), "english_target_min": p.english_target_min}


async def get_prefs(uid: str) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        subs = (await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid))).scalar() or 0
        out = prefs_json(p)
        out["push_devices"] = int(subs)
        await s.commit()
        return out


async def put_prefs(uid: str, body: dict) -> dict:
    """Update the learner's settings. Anything missing or invalid is left alone - a partial body is fine."""
    async with _S() as s:
        p = await _prefs(s, uid)
        old_tz = p.tz
        if "tz" in body:
            new_tz = tu.norm_tz(body.get("tz"))
            if isinstance(body.get("tz"), str) and new_tz != body["tz"]:
                raise Invalid("tz")
            p.tz = new_tz
        for k in ("quiet_on", "push_on", "hide_details", "paused_all", "english_habit"):
            if k in body and isinstance(body[k], bool):
                setattr(p, k, body[k])
        for k in ("quiet_start", "quiet_end"):
            if k in body:
                t = tu.parse_hhmm(body[k])
                if t is None:
                    raise Invalid(k)
                setattr(p, k, tu.fmt_hhmm(t))
        if "followups" in body:
            p.followups = rules.clamp_int(body["followups"], 0, 2, p.followups)
        if "followup_gap_min" in body:
            p.followup_gap_min = rules.clamp_int(body["followup_gap_min"], 10, 180, p.followup_gap_min)
        if "snooze_min" in body:
            p.snooze_min = rules.clamp_int(body["snooze_min"], 5, 240, p.snooze_min)
        if "english_target_min" in body:
            p.english_target_min = rules.clamp_int(body["english_target_min"], 5, 240, p.english_target_min)
        p.updated_at = _utc()
        if p.tz != old_tz:
            await _retz(s, uid, p)
        if body.get("paused_all") is True:
            await _cancel_reminders(s, uid, None, None)          # everything stops; the data stays
        elif body.get("paused_all") is False:
            await _resync_all(s, uid, p)
        await s.commit()
        return prefs_json(p)


async def _retz(s, uid: str, p: PlPrefs) -> None:
    """The learner moved: wall-clock times stay wall-clock. Open dated tasks are re-anchored to the new zone, series are regenerated,
    pending reminders are re-planned. Past and finished rows stay as they were."""
    now = _utc()
    rows = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.status == "open", PlTask.deleted_at.is_(None),
                                                 PlTask.due_date.is_not(None), PlTask.is_series.is_(False)))).scalars().all()
    for t in rows:
        if t.due_has_time and t.due_at is not None:
            local_t = tu.to_local(t.due_at, t.tz).time().replace(second=0, microsecond=0)
            t.due_at = tu.to_utc(t.due_date, local_t, p.tz)
        elif t.due_date is not None:
            t.due_at = tu.end_of_day_utc(t.due_date, p.tz)
        t.tz = p.tz
    await s.flush()
    await _cancel_reminders(s, uid, None, None)
    await _resync_all(s, uid, p)


# ----------------------------------------------------------------------------- reminders: planning
def _rkey(prefix: str, eid: int, fire: dt.datetime | None, extra: str = "") -> str:
    stamp = fire.astimezone(UTC).strftime("%Y%m%dT%H%M") if fire is not None else "wait"
    return f"{prefix}{eid}:{extra}{stamp}"[:96]


async def _upsert_reminder(s, uid: str, *, entity_type: str, entity_id: int | None, kind: str, title: str, body: str, key: str,
                           fire_at: dt.datetime | None, tz: str, status: str, meta: dict | None = None) -> PlReminder:
    r = (await s.execute(select(PlReminder).where(PlReminder.occurrence_key == key))).scalars().first()
    if r is not None:
        if r.user_id != uid:                                   # a key collision across users cannot happen by construction; never touch it
            raise Invalid("reminder")
        if r.status in ("cancelled", "expired"):               # the same moment was planned before and withdrawn: revive it
            r.status, r.fire_at, r.attempts, r.followups_sent, r.snooze_count = status, fire_at, 0, 0, 0
            r.push_state, r.last_error, r.sent_at, r.acted_at, r.action, r.claimed_at = "none", "", None, None, "", None
            r.title, r.body = title, body
        return r
    r = PlReminder(user_id=uid, entity_type=entity_type, entity_id=entity_id, kind=kind, title=title[:160], body=body[:300], occurrence_key=key,
                   fire_at=fire_at, tz=tz, status=status, meta=meta or {})
    s.add(r)
    await s.flush()
    return r


async def _cancel_reminders(s, uid: str, entity_type: str | None, entity_id: int | None, except_id: int | None = None) -> None:
    q = (update(PlReminder).where(PlReminder.user_id == uid, PlReminder.status.in_(OPEN_REMINDER))
         .values(status="cancelled", claimed_at=None))
    if entity_type is not None:
        q = q.where(PlReminder.entity_type == entity_type, PlReminder.entity_id == entity_id)
    if except_id is not None:
        q = q.where(PlReminder.id != except_id)
    await s.execute(q.execution_options(synchronize_session=False))


def _task_fire(t: PlTask, tz: str) -> dt.datetime | None:
    """When the task's own reminder fires, per `remind`. A date-only task nudges at 09:00 local on its day."""
    mode = t.remind
    if mode == "custom":
        return t.remind_at
    if mode == "none" or t.due_date is None:
        return None
    if t.due_has_time and t.due_at is not None:
        return {"at_due": t.due_at, "before_15": t.due_at - dt.timedelta(minutes=15), "before_60": t.due_at - dt.timedelta(minutes=60)}.get(mode)
    return tu.to_utc(t.due_date, dt.time(9, 0), tz)


async def _plan_task_reminders(s, t: PlTask, p: PlPrefs) -> None:
    """(Re)plan a task's reminders from its fields. Idempotent: the same plan twice leaves the same rows (unique occurrence key)."""
    if t.status != "open" or t.is_series or t.deleted_at is not None or p.paused_all:
        return
    if t.goal_id:
        g = await s.get(PlGoal, t.goal_id)
        if g is not None and g.status != "active":             # a paused goal's work does not nudge
            return
    now = _utc()
    floor = now - dt.timedelta(minutes=2)
    trig = t.trigger if isinstance(t.trigger, dict) else None
    if trig:
        # a condition task: nothing fires until the learner taps the chip; an optional fallback time makes sure it can never silently never fire
        await _upsert_reminder(s, t.user_id, entity_type="task", entity_id=t.id, kind="condition", title=t.title, body=trig.get("label", ""),
                               key=f"t{t.id}:cond", fire_at=now if trig.get("fired") else None, tz=p.tz,
                               status="scheduled" if trig.get("fired") else "waiting")
        fb = tu.parse_hhmm(trig.get("fallback_time"))
        if fb is not None:
            day = t.due_date or tu.local_today(p.tz, now)
            fire = tu.to_utc(day, fb, p.tz)
            if fire >= floor:
                await _upsert_reminder(s, t.user_id, entity_type="task", entity_id=t.id, kind="fallback", title=t.title, body="",
                                       key=_rkey("t", t.id, fire, "fb"), fire_at=fire, tz=p.tz, status="scheduled")
        return
    fire = _task_fire(t, p.tz)
    if fire is not None and fire >= floor:
        await _upsert_reminder(s, t.user_id, entity_type="task", entity_id=t.id, kind="time", title=t.title, body="",
                               key=_rkey("t", t.id, fire), fire_at=fire, tz=p.tz, status="scheduled")


async def _replan_task(s, t: PlTask, p: PlPrefs) -> None:
    await _cancel_reminders(s, t.user_id, "task", t.id)
    await s.flush()
    await _plan_task_reminders(s, t, p)


async def _resync_all(s, uid: str, p: PlPrefs) -> None:
    """After 'resume everything' / a timezone change: re-plan every open task and habit from their fields."""
    tasks = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.status == "open", PlTask.deleted_at.is_(None),
                                                  PlTask.is_series.is_(False)))).scalars().all()
    for t in tasks:
        await _plan_task_reminders(s, t, p)
    await _materialize_user(s, uid, p)


# ----------------------------------------------------------------------------- tasks
def _local_time_str(t: PlTask, tz: str) -> str | None:
    if not t.due_has_time or t.due_at is None:
        return None
    return tu.fmt_hhmm(tu.to_local(t.due_at, tz).time())


def task_json(t: PlTask, now: dt.datetime, tz: str, goal_titles: dict | None = None, snoozed: set | None = None) -> dict:
    today = tu.local_today(tz, now)
    trig = t.trigger if isinstance(t.trigger, dict) else None
    return {
        "id": t.id, "title": t.title, "notes": t.notes or "", "priority": t.priority, "minutes": t.minutes,
        "due_date": _iso(t.due_date), "due_time": _local_time_str(t, tz), "due_at": _iso(t.due_at),
        "status": t.status, "state": rules.derive_state(t.status, t.due_at, now),
        "pinned": bool(t.pin_date and t.pin_date == today and t.status == "open"),
        "goal_id": t.goal_id, "goal_title": (goal_titles or {}).get(t.goal_id), "milestone_id": t.milestone_id,
        "series_id": t.parent_id, "is_series": bool(t.is_series), "repeat": t.recurrence if t.is_series else None,
        "remind": t.remind, "remind_at": _iso(t.remind_at),
        "trigger": ({"label": trig.get("label", ""), "fired": bool(trig.get("fired")), "fallback_time": trig.get("fallback_time")} if trig else None),
        "snoozed": bool(snoozed and t.id in snoozed), "rescheduled": len(t.reschedules or []),
        "completed_at": _iso(t.completed_at), "created_at": _iso(t.created_at),
    }


async def _goal_titles(s, uid: str, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await s.execute(select(PlGoal.id, PlGoal.title).where(PlGoal.user_id == uid, PlGoal.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def _snoozed_ids(s, uid: str, ids: list) -> set:
    if not ids:
        return set()
    rows = (await s.execute(select(PlReminder.entity_id).where(PlReminder.user_id == uid, PlReminder.entity_type == "task",
                                                               PlReminder.entity_id.in_(ids), PlReminder.status == "scheduled",
                                                               PlReminder.snooze_count > 0))).scalars().all()
    return set(rows)


async def _owned_task(s, uid: str, tid: int, lock: bool = False) -> PlTask:
    q = select(PlTask).where(PlTask.id == tid, PlTask.user_id == uid, PlTask.deleted_at.is_(None))
    if lock:
        q = q.with_for_update()
    t = (await s.execute(q)).scalars().first()
    if t is None:
        raise NotFound("task")
    return t


async def _check_links(s, uid: str, goal_id, milestone_id) -> tuple[int | None, int | None]:
    gid = mid = None
    if goal_id not in (None, ""):
        g = await s.get(PlGoal, rules.clamp_int(goal_id, 1, 2 ** 31 - 1, 0))
        if g is None or g.user_id != uid or g.deleted_at is not None:
            raise Invalid("goal")
        gid = g.id
        if milestone_id not in (None, ""):
            m = await s.get(PlMilestone, rules.clamp_int(milestone_id, 1, 2 ** 31 - 1, 0))
            if m is None or m.user_id != uid or m.goal_id != gid or m.deleted_at is not None:
                raise Invalid("milestone")
            mid = m.id
    return gid, mid


async def _count_creates(s, uid: str) -> int:
    since = _utc() - dt.timedelta(hours=24)
    return (await s.execute(select(func.count()).select_from(PlEvent).where(PlEvent.user_id == uid, PlEvent.event_type == "created",
                                                                           PlEvent.at >= since))).scalar() or 0


async def create_task(uid: str, body: dict) -> dict:
    title = rules.clean_str(body.get("title"), 160)
    if not title:
        raise Invalid("title")
    async with _S() as s:
        p = await _prefs(s, uid)
        key = rules.clean_str(body.get("client_key"), 64) or None
        if key:
            ex = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.client_key == key))).scalars().first()
            if ex is not None and ex.deleted_at is None:                      # a retried create returns the first result
                titles = await _goal_titles(s, uid, {ex.goal_id})
                return task_json(ex, _utc(), p.tz, titles)
        open_n = (await s.execute(select(func.count()).select_from(PlTask).where(PlTask.user_id == uid, PlTask.status == "open",
                                                                                 PlTask.deleted_at.is_(None)))).scalar() or 0
        if open_n >= rules.LIMITS["tasks"] or await _count_creates(s, uid) >= rules.LIMITS["creates_per_day"]:
            raise LimitReached("tasks")
        gid, mid = await _check_links(s, uid, body.get("goal_id"), body.get("milestone_id"))
        due_date, has_time, due_at = rules.task_due(body.get("due_date"), body.get("due_time"), p.tz)
        rule = tu.clean_rule(body.get("repeat"))
        remind = rules.clean_remind(body.get("remind"))
        remind_at = None
        if remind == "custom":
            rd = tu.parse_date(body.get("remind_date")) or due_date or tu.local_today(p.tz)
            rt = tu.parse_hhmm(body.get("remind_time"))
            if rt is None:
                raise Invalid("remind_time")
            remind_at = tu.to_utc(rd, rt, p.tz)
        trig = None
        tg = body.get("trigger")
        if isinstance(tg, dict) and rules.clean_str(tg.get("label"), 60):
            fb = tu.parse_hhmm(tg.get("fallback_time"))
            trig = {"label": rules.clean_str(tg.get("label"), 60), "fired": False, "fallback_time": tu.fmt_hhmm(fb) if fb else None}
        if rule and trig:
            raise Invalid("repeat_trigger")                                    # a repeating series cannot also wait for a tap
        if rule:
            start = due_date or tu.local_today(p.tz)
            if has_time:
                rule["time"] = tu.fmt_hhmm(tu.to_local(due_at, p.tz).time())
            due_date, due_at = start, None
        mins = rules.clamp_int(body.get("minutes"), 1, 600, 0) or None
        t = PlTask(user_id=uid, goal_id=gid, milestone_id=mid, client_key=key, title=title, notes=rules.clean_notes(body.get("notes")),
                   priority=rules.clean_priority(body.get("priority")), minutes=mins, due_date=due_date, due_has_time=has_time,
                   due_at=due_at, orig_due_at=due_at, status="open", recurrence=rule, is_series=bool(rule), trigger=trig,
                   remind=remind, remind_at=remind_at, reschedules=[], tz=p.tz)
        s.add(t)
        try:
            await s.flush()
        except IntegrityError:                                                  # a concurrent create with the same client_key
            await s.rollback()
            ex = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.client_key == key))).scalars().first()
            if ex is None:
                raise
            return task_json(ex, _utc(), p.tz, {})
        if body.get("pin") is True and not rule:
            await _pin(s, uid, t, True, p)
        _ev(s, uid, "task", t.id, "created", {"series": bool(rule)})
        if rule:
            await _materialize_series(s, t, p)
        else:
            await _plan_task_reminders(s, t, p)
        if gid:
            await _recompute_goal(s, gid)
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, _utc(), p.tz, titles)


async def update_task(uid: str, tid: int, body: dict) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        t = await _owned_task(s, uid, tid, lock=True)
        old_goal = t.goal_id
        if "title" in body:
            title = rules.clean_str(body.get("title"), 160)
            if not title:
                raise Invalid("title")
            t.title = title
        if "notes" in body:
            t.notes = rules.clean_notes(body.get("notes"))
        if "priority" in body:
            t.priority = rules.clean_priority(body.get("priority"), t.priority)
        if "minutes" in body:
            t.minutes = rules.clamp_int(body.get("minutes"), 1, 600, 0) or None
        if "goal_id" in body or "milestone_id" in body:
            t.goal_id, t.milestone_id = await _check_links(s, uid, body.get("goal_id", t.goal_id), body.get("milestone_id"))
        if "remind" in body:
            t.remind = rules.clean_remind(body.get("remind"))
            if t.remind == "custom":
                rt = tu.parse_hhmm(body.get("remind_time"))
                if rt is None:
                    raise Invalid("remind_time")
                rd = tu.parse_date(body.get("remind_date")) or t.due_date or tu.local_today(p.tz)
                t.remind_at = tu.to_utc(rd, rt, p.tz)
            else:
                t.remind_at = None
        if "trigger" in body and not t.is_series:
            tg = body.get("trigger")
            if isinstance(tg, dict) and rules.clean_str(tg.get("label"), 60):
                fb = tu.parse_hhmm(tg.get("fallback_time"))
                prev = t.trigger if isinstance(t.trigger, dict) else {}
                t.trigger = {"label": rules.clean_str(tg.get("label"), 60), "fired": bool(prev.get("fired")), "fallback_time": tu.fmt_hhmm(fb) if fb else None}
            else:
                t.trigger = None
        due_changed = any(k in body for k in ("due_date", "due_time"))
        rule_changed = False
        if t.is_series and "repeat" in body:
            nr = tu.clean_rule(body.get("repeat"))
            if nr is None:
                raise Invalid("repeat")
            t.recurrence, rule_changed = nr, True
        if due_changed:
            dd = body.get("due_date", _iso(t.due_date))
            tt = body.get("due_time", _local_time_str(t, t.tz) if not t.is_series else (t.recurrence or {}).get("time"))
            due_date, has_time, due_at = rules.task_due(dd, tt, p.tz)
            if t.is_series:
                if due_date:
                    t.due_date = due_date
                rule = dict(t.recurrence or {})
                if has_time:
                    rule["time"] = tu.fmt_hhmm(tu.to_local(due_at, p.tz).time())
                elif "due_time" in body:
                    rule.pop("time", None)
                t.recurrence, rule_changed = rule, True
            else:
                if t.orig_due_at is None:
                    t.orig_due_at = t.due_at
                t.due_date, t.due_has_time, t.due_at = due_date, has_time, due_at
        t.updated_at = _utc()
        await s.flush()
        if t.is_series:
            await _reset_future_children(s, t, p, regenerate=True)
        else:
            await _replan_task(s, t, p)
        for g in {old_goal, t.goal_id}:
            if g:
                await _recompute_goal(s, g)
        _ev(s, uid, "task", t.id, "edited")
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, _utc(), p.tz, titles)


async def set_task_state(uid: str, tid: int, action: str) -> dict:
    """complete | skip | reopen. Idempotent: repeating the action returns the current task and writes no second event."""
    if action not in ("complete", "skip", "reopen"):
        raise Invalid("action")
    async with _S() as s:
        p = await _prefs(s, uid)
        t = await _owned_task(s, uid, tid, lock=True)
        if t.is_series:
            raise Invalid("series")
        now = _utc()
        changed = False
        if action == "complete" and t.status != "done":
            t.status, t.completed_at, t.skipped_at, changed = "done", now, None, True
        elif action == "skip" and t.status != "skipped":
            t.status, t.skipped_at, t.completed_at, changed = "skipped", now, None, True
        elif action == "reopen" and t.status != "open":
            t.status, t.completed_at, t.skipped_at, changed = "open", None, None, True
        if changed:
            t.updated_at = now
            await s.flush()
            if t.status == "open":
                await _plan_task_reminders(s, t, p)
            else:
                await _cancel_reminders(s, uid, "task", t.id)
            if t.goal_id:
                await _recompute_goal(s, t.goal_id)
            _ev(s, uid, "task", t.id, {"complete": "completed", "skip": "skipped", "reopen": "reopened"}[action])
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, now, p.tz, titles)


async def reschedule_task(uid: str, tid: int, body: dict) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        t = await _owned_task(s, uid, tid, lock=True)
        if t.is_series or t.status != "open":
            raise Invalid("not_open")
        due_date, has_time, due_at = rules.task_due(body.get("due_date"), body.get("due_time"), p.tz)
        if due_date is None:
            raise Invalid("due_date")
        if t.orig_due_at is None:
            t.orig_due_at = t.due_at
        hist = list(t.reschedules or [])
        hist.append({"from": _iso(t.due_at), "to": _iso(due_at), "at": _iso(_utc()), "why": rules.clean_str(body.get("reason"), 40)})
        t.reschedules = hist[-rules.LIMITS["reschedules"]:]
        t.due_date, t.due_has_time, t.due_at = due_date, has_time, due_at
        if t.pin_date and t.pin_date != due_date:
            t.pin_date = None
        if t.remind == "custom":
            t.remind, t.remind_at = "at_due", None               # a custom time belonged to the old date
        t.updated_at = _utc()
        await s.flush()
        await _replan_task(s, t, p)
        _ev(s, uid, "task", t.id, "rescheduled")
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, _utc(), p.tz, titles)


async def _pin(s, uid: str, t: PlTask, on: bool, p: PlPrefs) -> None:
    today = tu.local_today(p.tz)
    if not on:
        t.pin_date = None
        return
    if t.pin_date == today:
        return
    n = (await s.execute(select(func.count()).select_from(PlTask).where(PlTask.user_id == uid, PlTask.pin_date == today, PlTask.status == "open",
                                                                       PlTask.deleted_at.is_(None), PlTask.id != t.id))).scalar() or 0
    if n >= rules.LIMITS["pins_per_day"]:
        raise LimitReached("pins")
    t.pin_date = today


async def pin_task(uid: str, tid: int, on: bool) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        t = await _owned_task(s, uid, tid, lock=True)
        if t.is_series or t.status != "open":
            raise Invalid("not_open")
        await _pin(s, uid, t, bool(on), p)
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, _utc(), p.tz, titles)


async def trigger_task(uid: str, tid: int) -> dict:
    """The learner tapped the condition chip ('Trading finished'): the waiting reminder becomes due now. Idempotent."""
    async with _S() as s:
        p = await _prefs(s, uid)
        t = await _owned_task(s, uid, tid, lock=True)
        trig = t.trigger if isinstance(t.trigger, dict) else None
        if not trig or t.status != "open":
            raise Invalid("no_trigger")
        if not trig.get("fired"):
            t.trigger = dict(trig, fired=True)
            t.updated_at = _utc()
            await s.flush()
            r = (await s.execute(select(PlReminder).where(PlReminder.occurrence_key == f"t{t.id}:cond", PlReminder.user_id == uid))).scalars().first()
            now = _utc()
            if r is not None and r.status in ("waiting", "cancelled", "expired"):
                r.status, r.fire_at, r.attempts, r.followups_sent, r.snooze_count = "scheduled", now, 0, 0, 0
                r.push_state, r.sent_at, r.acted_at, r.action = "none", None, None, ""
            elif r is None:
                await _plan_task_reminders(s, t, p)
            _ev(s, uid, "task", t.id, "triggered")
        await s.commit()
        titles = await _goal_titles(s, uid, {t.goal_id})
        return task_json(t, _utc(), p.tz, titles)


async def delete_task(uid: str, tid: int) -> dict:
    async with _S() as s:
        t = await _owned_task(s, uid, tid, lock=True)
        now = _utc()
        t.deleted_at = now
        await _cancel_reminders(s, uid, "task", t.id)
        if t.is_series:
            kids = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.parent_id == t.id, PlTask.deleted_at.is_(None),
                                                         PlTask.status == "open"))).scalars().all()
            for k in kids:
                k.deleted_at = now
                await _cancel_reminders(s, uid, "task", k.id)
        if t.goal_id:
            await s.flush()
            await _recompute_goal(s, t.goal_id)
        _ev(s, uid, "task", t.id, "deleted")
        await s.commit()
        return {"ok": True, "id": tid}


async def list_tasks(uid: str, view: str = "today", goal_id: int | None = None) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        today = tu.local_today(p.tz, now)
        base = [PlTask.user_id == uid, PlTask.deleted_at.is_(None)]
        if goal_id:
            base.append(PlTask.goal_id == goal_id)
        order_open = (PlTask.due_at.asc().nulls_last(), PlTask.priority.desc(), PlTask.id.asc())
        if view == "repeating":
            q = select(PlTask).where(*base, PlTask.is_series.is_(True)).order_by(PlTask.id.desc())
        elif view == "done":
            since = now - dt.timedelta(days=14)
            q = select(PlTask).where(*base, PlTask.is_series.is_(False), PlTask.status.in_(("done", "skipped")),
                                     func.coalesce(PlTask.completed_at, PlTask.skipped_at) >= since)\
                .order_by(func.coalesce(PlTask.completed_at, PlTask.skipped_at).desc())
        else:
            conds = [*base, PlTask.is_series.is_(False), PlTask.status == "open"]
            if view == "today":
                conds.append(or_(PlTask.due_date == today, PlTask.pin_date == today))
            elif view == "overdue":
                conds.append(PlTask.due_at < now)
            elif view == "upcoming":
                conds.append(PlTask.due_date > today)
            elif view == "inbox":
                conds.append(PlTask.due_date.is_(None))
            elif view != "all":
                raise Invalid("view")
            q = select(PlTask).where(*conds).order_by((PlTask.pin_date == today).desc(), *order_open)
        rows = (await s.execute(q.limit(rules.LIMITS["list"]))).scalars().all()
        titles = await _goal_titles(s, uid, {r.goal_id for r in rows})
        snoozed = await _snoozed_ids(s, uid, [r.id for r in rows])
        await s.commit()
        return {"tasks": [task_json(r, now, p.tz, titles, snoozed) for r in rows], "view": view, "tz": p.tz, "date": today.isoformat()}


# ----------------------------------------------------------------------------- recurring tasks
async def _materialize_series(s, tpl: PlTask, p: PlPrefs, days: int = 2) -> int:
    """Concrete occurrences for the next `days` days (today + 2 = a rolling 48 h) of a repeat template. Unique (parent_id, occ_date): safe to
    run any number of times, from any number of loops."""
    if not tpl.is_series or tpl.deleted_at is not None or tpl.status != "open" or not isinstance(tpl.recurrence, dict) or p.paused_all:
        return 0
    rule = tpl.recurrence
    today = tu.local_today(p.tz)
    start = tpl.due_date or today
    dates = tu.occurrences(rule, start, max(start, today), today + dt.timedelta(days=days))
    if not dates:
        return 0
    have = set((await s.execute(select(PlTask.occ_date).where(PlTask.parent_id == tpl.id))).scalars().all())
    made = 0
    t_of_day = tu.parse_hhmm(rule.get("time"))
    for d in dates:
        if d in have:
            continue
        due_at = tu.to_utc(d, t_of_day, p.tz) if t_of_day else tu.end_of_day_utc(d, p.tz)
        child = PlTask(user_id=tpl.user_id, goal_id=tpl.goal_id, milestone_id=tpl.milestone_id, parent_id=tpl.id, occ_date=d, title=tpl.title,
                       notes=tpl.notes, priority=tpl.priority, minutes=tpl.minutes, due_date=d, due_has_time=bool(t_of_day), due_at=due_at,
                       orig_due_at=due_at, status="open", remind=tpl.remind if tpl.remind != "custom" else "at_due", reschedules=[], tz=p.tz)
        try:
            async with s.begin_nested():
                s.add(child)
                await s.flush()
        except IntegrityError:
            continue                                                            # another loop made it first
        await _plan_task_reminders(s, child, p)
        made += 1
    return made


async def _reset_future_children(s, tpl: PlTask, p: PlPrefs, regenerate: bool) -> None:
    """A series was edited: untouched open occurrences from today on are withdrawn (their reminders too) and re-made from the new rule."""
    today = tu.local_today(p.tz)
    kids = (await s.execute(select(PlTask).where(PlTask.user_id == tpl.user_id, PlTask.parent_id == tpl.id, PlTask.status == "open",
                                                 PlTask.deleted_at.is_(None), PlTask.occ_date >= today))).scalars().all()
    now = _utc()
    for k in kids:
        k.deleted_at = now
        await _cancel_reminders(s, tpl.user_id, "task", k.id)
    await s.flush()
    if regenerate:
        # a soft-deleted child still occupies its (parent, occ_date) slot, so re-use is by un-deleting the matching dates the new rule keeps
        rule = tpl.recurrence or {}
        keep = set(tu.occurrences(rule, tpl.due_date or today, today, today + dt.timedelta(days=2)))
        for k in kids:
            if k.occ_date in keep:
                t_of_day = tu.parse_hhmm(rule.get("time"))
                k.deleted_at = None
                k.title, k.notes, k.priority, k.minutes = tpl.title, tpl.notes, tpl.priority, tpl.minutes
                k.due_has_time = bool(t_of_day)
                k.due_at = tu.to_utc(k.occ_date, t_of_day, p.tz) if t_of_day else tu.end_of_day_utc(k.occ_date, p.tz)
                k.orig_due_at = k.due_at
                k.remind = tpl.remind if tpl.remind != "custom" else "at_due"
        await s.flush()
        for k in kids:
            if k.deleted_at is None:
                await _plan_task_reminders(s, k, p)
        await _materialize_series(s, tpl, p)


# ----------------------------------------------------------------------------- goals + milestones
def goal_json(g: PlGoal, ms: list, tasks_open: int, tasks_done: int, next_task: dict | None, today: dt.date) -> dict:
    behind = rules.behind_days(g.progress or 0, g.start_date or (g.created_at.date() if g.created_at else None), g.target_date, today)
    nxt = next((m for m in ms if m.status == "open"), None)
    return {"id": g.id, "title": g.title, "why": g.why or "", "target_date": _iso(g.target_date), "start_date": _iso(g.start_date),
            "daily_minutes": g.daily_minutes, "status": g.status, "progress": g.progress or 0, "behind_days": behind,
            "milestones": [{"id": m.id, "title": m.title, "detail": m.detail or "", "due_date": _iso(m.due_date), "status": m.status, "seq": m.seq} for m in ms],
            "next_milestone": ({"id": nxt.id, "title": nxt.title, "due_date": _iso(nxt.due_date)} if nxt else None),
            "tasks_open": tasks_open, "tasks_done": tasks_done, "next_task": next_task, "source": g.source}


async def _owned_goal(s, uid: str, gid: int, lock: bool = False) -> PlGoal:
    q = select(PlGoal).where(PlGoal.id == gid, PlGoal.user_id == uid, PlGoal.deleted_at.is_(None))
    if lock:
        q = q.with_for_update()
    g = (await s.execute(q)).scalars().first()
    if g is None:
        raise NotFound("goal")
    return g


async def _recompute_goal(s, gid: int) -> None:
    """Cached 0-100 progress: the mean of the milestone fractions (a milestone = done, or its done/non-skipped tasks); with no milestones, the
    goal's own tasks count as one."""
    g = await s.get(PlGoal, gid)
    if g is None:
        return
    ms = (await s.execute(select(PlMilestone).where(PlMilestone.goal_id == gid, PlMilestone.deleted_at.is_(None)).order_by(PlMilestone.seq))).scalars().all()
    tasks = (await s.execute(select(PlTask.milestone_id, PlTask.status).where(PlTask.goal_id == gid, PlTask.is_series.is_(False),
                                                                             PlTask.deleted_at.is_(None)))).all()

    def fraction(status: str, statuses: list) -> float:
        live = [st for st in statuses if st != "skipped"]
        return rules.milestone_fraction(status, sum(1 for st in live if st == "done"), len(live))
    if ms:
        fr = [fraction(m.status, [st for m_id, st in tasks if m_id == m.id]) for m in ms if m.status != "skipped"]
    else:
        fr = [fraction("open", [st for _m, st in tasks])] if any(st != "skipped" for _m, st in tasks) else []
    g.progress = rules.goal_progress(fr, g.status == "done")
    g.updated_at = _utc()


async def create_goal(uid: str, body: dict) -> dict:
    title = rules.clean_str(body.get("title"), 120)
    if not title:
        raise Invalid("title")
    async with _S() as s:
        p = await _prefs(s, uid)
        key = rules.clean_str(body.get("client_key"), 64) or None
        if key:
            ex = (await s.execute(select(PlGoal).where(PlGoal.user_id == uid, PlGoal.client_key == key))).scalars().first()
            if ex is not None and ex.deleted_at is None:
                return await _goal_full(s, ex, p)
        n = (await s.execute(select(func.count()).select_from(PlGoal).where(PlGoal.user_id == uid, PlGoal.deleted_at.is_(None),
                                                                           PlGoal.status.in_(("active", "paused"))))).scalar() or 0
        if n >= rules.LIMITS["goals"]:
            raise LimitReached("goals")
        today = tu.local_today(p.tz)
        target = tu.parse_date(body.get("target_date"))
        if target is not None and target < today:
            raise Invalid("target_date")
        g = PlGoal(user_id=uid, client_key=key, title=title, why=rules.clean_str(body.get("why"), 500), start_date=today, target_date=target,
                   daily_minutes=rules.clamp_int(body.get("daily_minutes"), 5, 600, 0) or None, status="active", progress=0, source="manual")
        s.add(g)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            ex = (await s.execute(select(PlGoal).where(PlGoal.user_id == uid, PlGoal.client_key == key))).scalars().first()
            if ex is None:
                raise
            return await _goal_full(s, ex, p)
        for i, m in enumerate((body.get("milestones") if isinstance(body.get("milestones"), list) else [])[:rules.LIMITS["milestones"]]):
            mt = rules.clean_str(m.get("title") if isinstance(m, dict) else m, 120)
            if mt:
                s.add(PlMilestone(goal_id=g.id, user_id=uid, seq=i, title=mt, detail="", due_date=None, status="open"))
        _ev(s, uid, "goal", g.id, "created")
        await s.flush()
        await _recompute_goal(s, g.id)
        await s.commit()
        return await _goal_full(s, g, p)


async def _goal_full(s, g: PlGoal, p: PlPrefs) -> dict:
    now = _utc()
    ms = (await s.execute(select(PlMilestone).where(PlMilestone.goal_id == g.id, PlMilestone.deleted_at.is_(None)).order_by(PlMilestone.seq, PlMilestone.id))).scalars().all()
    rows = (await s.execute(select(PlTask).where(PlTask.goal_id == g.id, PlTask.user_id == g.user_id, PlTask.is_series.is_(False), PlTask.deleted_at.is_(None))
                            .order_by(PlTask.due_at.asc().nulls_last(), PlTask.priority.desc()))).scalars().all()
    open_ = [t for t in rows if t.status == "open"]
    done_ = [t for t in rows if t.status == "done"]
    nxt = task_json(open_[0], now, p.tz, {g.id: g.title}) if open_ else None
    return goal_json(g, ms, len(open_), len(done_), nxt, tu.local_today(p.tz, now))


async def get_goal(uid: str, gid: int) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        g = await _owned_goal(s, uid, gid)
        out = await _goal_full(s, g, p)
        await s.commit()
        return out


async def list_goals(uid: str) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        gs = (await s.execute(select(PlGoal).where(PlGoal.user_id == uid, PlGoal.deleted_at.is_(None), PlGoal.status != "archived")
                              .order_by((PlGoal.status == "active").desc(), PlGoal.created_at.desc()))).scalars().all()
        out = [await _goal_full(s, g, p) for g in gs]
        await s.commit()
        return {"goals": out}


async def update_goal(uid: str, gid: int, body: dict) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        g = await _owned_goal(s, uid, gid, lock=True)
        if "title" in body:
            t = rules.clean_str(body.get("title"), 120)
            if not t:
                raise Invalid("title")
            g.title = t
        if "why" in body:
            g.why = rules.clean_str(body.get("why"), 500)
        if "target_date" in body:
            g.target_date = tu.parse_date(body.get("target_date"))
        if "daily_minutes" in body:
            g.daily_minutes = rules.clamp_int(body.get("daily_minutes"), 5, 600, 0) or None
        action = body.get("action")
        if action in ("pause", "resume", "done", "archive", "reopen"):
            prev = g.status
            g.status = {"pause": "paused", "resume": "active", "reopen": "active", "done": "done", "archive": "archived"}[action]
            if g.status == "done":
                g.completed_at = _utc()
            if prev != g.status:
                tasks = (await s.execute(select(PlTask).where(PlTask.goal_id == g.id, PlTask.user_id == uid, PlTask.status == "open",
                                                              PlTask.deleted_at.is_(None), PlTask.is_series.is_(False)))).scalars().all()
                await s.flush()
                for t in tasks:
                    await _cancel_reminders(s, uid, "task", t.id)
                    if g.status == "active":
                        await _plan_task_reminders(s, t, p)
                _ev(s, uid, "goal", g.id, "goal_" + action)
        g.updated_at = _utc()
        await s.flush()
        await _recompute_goal(s, g.id)
        await s.commit()
        return await _goal_full(s, g, p)


async def delete_goal(uid: str, gid: int) -> dict:
    async with _S() as s:
        g = await _owned_goal(s, uid, gid, lock=True)
        now = _utc()
        g.deleted_at = now
        tasks = (await s.execute(select(PlTask).where(PlTask.goal_id == g.id, PlTask.user_id == uid, PlTask.deleted_at.is_(None)))).scalars().all()
        for t in tasks:
            t.goal_id, t.milestone_id = None, None                  # the tasks stay (they are the learner's), just no longer under this goal
        for m in (await s.execute(select(PlMilestone).where(PlMilestone.goal_id == g.id))).scalars().all():
            m.deleted_at = now
        _ev(s, uid, "goal", g.id, "deleted")
        await s.commit()
        return {"ok": True, "id": gid}


async def add_milestone(uid: str, gid: int, body: dict) -> dict:
    title = rules.clean_str(body.get("title"), 120)
    if not title:
        raise Invalid("title")
    async with _S() as s:
        p = await _prefs(s, uid)
        g = await _owned_goal(s, uid, gid, lock=True)
        n = (await s.execute(select(func.count()).select_from(PlMilestone).where(PlMilestone.goal_id == g.id, PlMilestone.deleted_at.is_(None)))).scalar() or 0
        if n >= rules.LIMITS["milestones"]:
            raise LimitReached("milestones")
        s.add(PlMilestone(goal_id=g.id, user_id=uid, seq=n, title=title, detail=rules.clean_str(body.get("detail"), 300),
                          due_date=tu.parse_date(body.get("due_date")), status="open"))
        await s.flush()
        await _recompute_goal(s, g.id)
        await s.commit()
        return await _goal_full(s, g, p)


async def _owned_ms(s, uid: str, mid: int) -> PlMilestone:
    m = (await s.execute(select(PlMilestone).where(PlMilestone.id == mid, PlMilestone.user_id == uid, PlMilestone.deleted_at.is_(None)).with_for_update())).scalars().first()
    if m is None:
        raise NotFound("milestone")
    return m


async def update_milestone(uid: str, mid: int, body: dict) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        m = await _owned_ms(s, uid, mid)
        if "title" in body:
            t = rules.clean_str(body.get("title"), 120)
            if not t:
                raise Invalid("title")
            m.title = t
        if "detail" in body:
            m.detail = rules.clean_str(body.get("detail"), 300)
        if "due_date" in body:
            m.due_date = tu.parse_date(body.get("due_date"))
        act = body.get("action")
        if act in ("complete", "reopen", "skip", "delete"):
            now = _utc()
            if act == "complete" and m.status != "done":
                m.status, m.completed_at = "done", now
                _ev(s, uid, "goal", m.goal_id, "milestone_done", {"m": m.id})
            elif act == "reopen" and m.status != "open":
                m.status, m.completed_at = "open", None
            elif act == "skip":
                m.status = "skipped"
            elif act == "delete":
                m.deleted_at = now
        await s.flush()
        await _recompute_goal(s, m.goal_id)
        g = await s.get(PlGoal, m.goal_id)
        await s.commit()
        return await _goal_full(s, g, p)


# ----------------------------------------------------------------------------- habits
def _habit_logs_map(rows) -> dict:
    return {r.day: (int(r.count or 0), r.state or "logged") for r in rows}


def habit_json(h: PlHabit, logs: dict, today: dt.date) -> dict:
    sch = h.schedule if isinstance(h.schedule, dict) else {}
    cnt, st = logs.get(today, (0, "logged"))
    days = []
    for i in range(13, -1, -1):
        d = today - dt.timedelta(days=i)
        c, s_ = logs.get(d, (0, "logged"))
        sched = rules.habit_scheduled(sch, h.start_date, h.end_date, d)
        days.append({"d": d.isoformat(), "c": c, "s": rules.day_status(c, h.target_count, s_, sched, d, today)})
    return {"id": h.id, "title": h.title, "target": h.target_count, "unit": h.unit or "", "partial_ok": bool(h.partial_ok), "schedule": sch,
            "start_date": _iso(h.start_date), "end_date": _iso(h.end_date), "status": h.status, "goal_id": h.goal_id,
            "count_today": cnt, "state_today": ("skipped" if st == "skipped" else "done" if cnt >= h.target_count else "partial" if cnt > 0 else "none"),
            "scheduled_today": rules.habit_scheduled(sch, h.start_date, h.end_date, today), "days": days,
            "consistency": rules.consistency(logs, sch, h.start_date, h.end_date, h.target_count, bool(h.partial_ok), today),
            "streak": rules.streak(logs, sch, h.start_date, h.end_date, h.target_count, today), "auto": False}


async def _owned_habit(s, uid: str, hid: int, lock: bool = False) -> PlHabit:
    q = select(PlHabit).where(PlHabit.id == hid, PlHabit.user_id == uid, PlHabit.deleted_at.is_(None))
    if lock:
        q = q.with_for_update()
    h = (await s.execute(q)).scalars().first()
    if h is None:
        raise NotFound("habit")
    return h


async def _logs_for(s, uid: str, ids: list, today: dt.date, days: int = 400) -> dict:
    if not ids:
        return {}
    rows = (await s.execute(select(PlHabitLog).where(PlHabitLog.user_id == uid, PlHabitLog.habit_id.in_(ids),
                                                     PlHabitLog.day >= today - dt.timedelta(days=days)))).scalars().all()
    out: dict = {i: [] for i in ids}
    for r in rows:
        out[r.habit_id].append(r)
    return {i: _habit_logs_map(v) for i, v in out.items()}


async def create_habit(uid: str, body: dict) -> dict:
    title = rules.clean_str(body.get("title"), 100)
    if not title:
        raise Invalid("title")
    async with _S() as s:
        p = await _prefs(s, uid)
        key = rules.clean_str(body.get("client_key"), 64) or None
        today = tu.local_today(p.tz)
        if key:
            ex = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.client_key == key))).scalars().first()
            if ex is not None and ex.deleted_at is None:
                logs = (await _logs_for(s, uid, [ex.id], today)).get(ex.id, {})
                return habit_json(ex, logs, today)
        n = (await s.execute(select(func.count()).select_from(PlHabit).where(PlHabit.user_id == uid, PlHabit.deleted_at.is_(None)))).scalar() or 0
        if n >= rules.LIMITS["habits"]:
            raise LimitReached("habits")
        h = PlHabit(user_id=uid, client_key=key, title=title, target_count=rules.clamp_int(body.get("target"), 1, 100, 1),
                    unit=rules.clean_str(body.get("unit"), 24), partial_ok=bool(body.get("partial_ok", True)),
                    schedule=rules.clean_schedule(body.get("schedule")), start_date=tu.parse_date(body.get("start_date")) or today,
                    end_date=tu.parse_date(body.get("end_date")), status="active", tz=p.tz)
        s.add(h)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            ex = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.client_key == key))).scalars().first()
            if ex is None:
                raise
            return habit_json(ex, {}, today)
        _ev(s, uid, "habit", h.id, "created")
        await _materialize_habit(s, h, p)
        await s.commit()
        return habit_json(h, {}, today)


async def update_habit(uid: str, hid: int, body: dict) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        h = await _owned_habit(s, uid, hid, lock=True)
        today = tu.local_today(p.tz)
        if "title" in body:
            t = rules.clean_str(body.get("title"), 100)
            if not t:
                raise Invalid("title")
            h.title = t
        if "target" in body:
            h.target_count = rules.clamp_int(body.get("target"), 1, 100, h.target_count)
        if "unit" in body:
            h.unit = rules.clean_str(body.get("unit"), 24)
        if "partial_ok" in body and isinstance(body["partial_ok"], bool):
            h.partial_ok = body["partial_ok"]
        if "schedule" in body:
            h.schedule = rules.clean_schedule(body.get("schedule"))
        if "end_date" in body:
            h.end_date = tu.parse_date(body.get("end_date"))
        if body.get("action") in ("pause", "resume", "archive"):
            h.status = {"pause": "paused", "resume": "active", "archive": "archived"}[body["action"]]
        await s.flush()
        await _cancel_reminders(s, uid, "habit", h.id)
        if h.status == "active":
            await _materialize_habit(s, h, p)
        await s.commit()
        logs = (await _logs_for(s, uid, [h.id], today)).get(h.id, {})
        return habit_json(h, logs, today)


async def delete_habit(uid: str, hid: int) -> dict:
    async with _S() as s:
        h = await _owned_habit(s, uid, hid, lock=True)
        h.deleted_at = _utc()
        await _cancel_reminders(s, uid, "habit", h.id)
        _ev(s, uid, "habit", h.id, "deleted")
        await s.commit()
        return {"ok": True, "id": hid}


async def log_habit(uid: str, hid: int, body: dict) -> dict:
    """ABSOLUTE log for one local day: 'set that day's count to N' (or skipped). A retried tap changes nothing."""
    async with _S() as s:
        p = await _prefs(s, uid)
        h = await _owned_habit(s, uid, hid, lock=True)
        today = tu.local_today(p.tz)
        day = tu.parse_date(body.get("day")) or today
        if day > today or day < today - dt.timedelta(days=60):
            raise Invalid("day")
        skipped = body.get("skipped") is True
        count = 0 if skipped else rules.clamp_int(body.get("count"), 0, 1000, 0)
        if not skipped and "count" not in body:
            raise Invalid("count")
        row = (await s.execute(select(PlHabitLog).where(PlHabitLog.habit_id == h.id, PlHabitLog.day == day).with_for_update())).scalars().first()
        state = "skipped" if skipped else "logged"
        if row is None:
            if skipped or count > 0:
                s.add(PlHabitLog(habit_id=h.id, user_id=uid, day=day, count=count, state=state, note=rules.clean_str(body.get("note"), 200)))
                _ev(s, uid, "habit", h.id, "logged", {"count": count, "skipped": skipped})
        elif row.count != count or row.state != state:
            row.count, row.state, row.updated_at = count, state, _utc()
            if "note" in body:
                row.note = rules.clean_str(body.get("note"), 200)
            _ev(s, uid, "habit", h.id, "logged", {"count": count, "skipped": skipped})
        await s.flush()
        if day == today and (skipped or count >= h.target_count):
            # the day is settled: today's still-unsent reminders for this habit are withdrawn
            await s.execute(update(PlReminder).where(PlReminder.user_id == uid, PlReminder.entity_type == "habit", PlReminder.entity_id == h.id,
                                                     PlReminder.status.in_(("waiting", "scheduled", "sent")),
                                                     PlReminder.meta["day"].astext == today.isoformat())
                            .values(status="cancelled").execution_options(synchronize_session=False))
        await s.commit()
        logs = (await _logs_for(s, uid, [h.id], today)).get(h.id, {})
        return habit_json(h, logs, today)


async def _english_habit(s, uid: str, p: PlPrefs, today: dt.date) -> dict | None:
    """The built-in 'English practice (DuSu)' strip: minutes spoken today, read from the app's own daily stats (no logging)."""
    if not p.english_habit:
        return None
    mem = await s.get(db.Memory, uid)
    facts = (mem.facts if mem is not None and isinstance(mem.facts, dict) else {})
    stats = facts.get("daily_stats") if isinstance(facts.get("daily_stats"), dict) else {}
    ist_today = db._ist_now().date().isoformat()            # the app's own day boundary is IST
    ds = stats.get(ist_today) if isinstance(stats.get(ist_today), dict) else {}
    mins = int((ds.get("seconds") or 0) // 60) if isinstance(ds.get("seconds"), (int, float)) else 0
    tgt = max(1, int(p.english_target_min or 15))
    return {"id": "dusu", "title": "English practice (DuSu)", "target": tgt, "unit": "min", "partial_ok": True, "schedule": {"days": "daily", "times": []},
            "count_today": mins, "state_today": "done" if mins >= tgt else "partial" if mins > 0 else "none", "scheduled_today": True,
            "days": [], "consistency": None, "streak": 0, "auto": True, "status": "active"}


async def list_habits(uid: str) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        today = tu.local_today(p.tz)
        hs = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.deleted_at.is_(None), PlHabit.status != "archived").order_by(PlHabit.id))).scalars().all()
        logs = await _logs_for(s, uid, [h.id for h in hs], today)
        out = [habit_json(h, logs.get(h.id, {}), today) for h in hs]
        eng = await _english_habit(s, uid, p, today)
        await s.commit()
        return {"habits": ([eng] if eng else []) + out, "date": today.isoformat()}


# ----------------------------------------------------------------------------- habit + series materializer
async def _materialize_habit(s, h: PlHabit, p: PlPrefs, days: int = 1) -> int:
    """Habit reminders for today and tomorrow (a rolling window), one per scheduled time. Key (habit, day, time): safe to repeat."""
    if h.status != "active" or h.deleted_at is not None or p.paused_all:
        return 0
    sch = h.schedule if isinstance(h.schedule, dict) else {}
    times = [tu.parse_hhmm(x) for x in sch.get("times", [])]
    if not any(times):
        return 0
    now = _utc()
    floor = now - dt.timedelta(minutes=2)
    today = tu.local_today(p.tz, now)
    made = 0
    for off in range(days + 1):
        d = today + dt.timedelta(days=off)
        if not rules.habit_scheduled(sch, h.start_date, h.end_date, d):
            continue
        for t in times:
            if t is None:
                continue
            fire = tu.to_utc(d, t, p.tz)
            if fire < floor:
                continue
            key = f"h{h.id}:{d.isoformat()}:{t.hour:02d}{t.minute:02d}"
            before = (await s.execute(select(PlReminder.id).where(PlReminder.occurrence_key == key))).scalars().first()
            await _upsert_reminder(s, h.user_id, entity_type="habit", entity_id=h.id, kind="recurring", title=h.title,
                                   body=(f"{h.target_count} {h.unit}".strip() if h.target_count > 1 or h.unit else ""), key=key, fire_at=fire,
                                   tz=p.tz, status="scheduled", meta={"day": d.isoformat(), "time": f"{t.hour:02d}:{t.minute:02d}"})
            made += 0 if before else 1
    return made


async def _materialize_user(s, uid: str, p: PlPrefs) -> None:
    tpls = (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.is_series.is_(True), PlTask.deleted_at.is_(None),
                                                 PlTask.status == "open"))).scalars().all()
    for t in tpls:
        await _materialize_series(s, t, p)
    hs = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.deleted_at.is_(None), PlHabit.status == "active"))).scalars().all()
    for h in hs:
        await _materialize_habit(s, h, p)


async def materialize_all() -> int:
    """The scheduler's 10-minute pass: every learner with a repeat series or a timed habit gets the next 48 h planned."""
    async with _S() as s:
        uids = set((await s.execute(select(PlTask.user_id).where(PlTask.is_series.is_(True), PlTask.deleted_at.is_(None), PlTask.status == "open"))).scalars().all())
        uids |= set((await s.execute(select(PlHabit.user_id).where(PlHabit.deleted_at.is_(None), PlHabit.status == "active"))).scalars().all())
    n = 0
    for uid in uids:
        try:
            async with _S() as s:
                p = await _prefs(s, uid)
                if p.paused_all:
                    await s.commit()
                    continue
                await _materialize_user(s, uid, p)
                await s.commit()
                n += 1
        except Exception as e:                       # one learner's bad row never stops the rest
            print(f"[planner] materialize failed: {type(e).__name__}")
    return n


# ----------------------------------------------------------------------------- reminders: the learner's side
def reminder_json(r: PlReminder, task: PlTask | None = None, now: dt.datetime | None = None) -> dict:
    out = {"id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id, "kind": r.kind, "title": r.title, "body": r.body or "",
           "status": r.status, "fire_at": _iso(r.fire_at), "sent_at": _iso(r.sent_at), "push_state": r.push_state, "snooze_count": r.snooze_count,
           "followups_sent": r.followups_sent, "action": r.action or "", "stale": r.push_state == "stale"}
    if task is not None:
        out["task_state"] = task.status
        out["due_at"] = _iso(task.due_at)
    return out


def reminder_brief(r: PlReminder, tz: str) -> dict:
    """reminder_json + the learner's LOCAL day ('2026-10-11') and time ('20:00') of it, so a list can group and an edit sheet can prefill with no
    time-zone arithmetic in the client."""
    out = reminder_json(r)
    if r.fire_at is not None:
        loc = tu.to_local(r.fire_at, tz)
        out["day"], out["time"] = loc.date().isoformat(), f"{loc.hour:02d}:{loc.minute:02d}"
    return out


async def due_cards(uid: str) -> dict:
    """Reminders the app should show NOW: sent and not yet acted on (the in-app channel IS this list)."""
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        rows = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, or_(PlReminder.status == "sent",
                                                                                      and_(PlReminder.status == "scheduled", PlReminder.fire_at <= now)))
                                .order_by(PlReminder.fire_at.asc()).limit(20))).scalars().all()
        tids = [r.entity_id for r in rows if r.entity_type == "task" and r.entity_id]
        tasks = {}
        if tids:
            tasks = {t.id: t for t in (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.id.in_(tids)))).scalars().all()}
        await s.commit()
        return {"due": [reminder_json(r, tasks.get(r.entity_id), now) for r in rows], "now": now.isoformat(), "tz": p.tz}


async def list_reminders(uid: str, view: str = "upcoming") -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        if view == "history":
            since = now - dt.timedelta(days=30)
            q = select(PlReminder).where(PlReminder.user_id == uid, PlReminder.status.in_(("done", "skipped", "expired", "sent")),
                                         func.coalesce(PlReminder.sent_at, PlReminder.fire_at, PlReminder.created_at) >= since)\
                .order_by(func.coalesce(PlReminder.sent_at, PlReminder.fire_at).desc())
        else:
            q = select(PlReminder).where(PlReminder.user_id == uid, PlReminder.status.in_(("waiting", "scheduled"))).order_by(PlReminder.fire_at.asc().nulls_last())
        rows = (await s.execute(q.limit(60))).scalars().all()
        await s.commit()
        return {"reminders": [reminder_brief(r, p.tz) for r in rows], "view": view, "tz": p.tz, "today": tu.local_today(p.tz, now).isoformat()}


async def create_custom_reminder(uid: str, body: dict) -> dict:
    title = rules.clean_str(body.get("title"), 160)
    if not title:
        raise Invalid("title")
    async with _S() as s:
        p = await _prefs(s, uid)
        d = tu.parse_date(body.get("date")) or tu.local_today(p.tz)
        t = tu.parse_hhmm(body.get("time"))
        if t is None:
            raise Invalid("time")
        fire = tu.to_utc(d, t, p.tz)
        now = _utc()
        if fire < now - dt.timedelta(minutes=1):
            raise Invalid("past")
        # the same words at the same minute that are already waiting: the learner added it twice (a second tap, a retry, or not sure the
        # first one saved) - hand back the one that exists instead of piling up a copy
        dup = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, PlReminder.entity_type == "custom", PlReminder.kind == "time",
                                                        PlReminder.status.in_(("scheduled", "waiting")), PlReminder.fire_at == fire,
                                                        func.lower(PlReminder.title) == title.lower()))).scalars().first()
        if dup is not None:
            await s.commit()
            out = reminder_json(dup)
            out["duplicate"] = True
            return out
        n = (await s.execute(select(func.count()).select_from(PlReminder).where(PlReminder.user_id == uid, PlReminder.entity_type == "custom",
                                                                               PlReminder.status.in_(("scheduled", "waiting"))))).scalar() or 0
        if n >= rules.LIMITS["custom_reminders"] or await _count_creates(s, uid) >= rules.LIMITS["creates_per_day"]:
            raise LimitReached("reminders")
        key = rules.clean_str(body.get("client_key"), 48)
        r = await _upsert_reminder(s, uid, entity_type="custom", entity_id=None, kind="time", title=title, body=rules.clean_str(body.get("body"), 300),
                                   key=(f"c:{uid[:24]}:{key}" if key else f"c:{uid[:24]}:{fire:%Y%m%dT%H%M%S}:{abs(hash(title)) % 10**6}")[:96],
                                   fire_at=fire, tz=p.tz, status="scheduled")
        _ev(s, uid, "custom", r.id, "created")
        await s.commit()
        return reminder_json(r)


async def _own_custom_reminder(s, uid: str, rid: int) -> PlReminder:
    """The learner's own note-to-self reminder (never a task's or a habit's - those are managed from the task / habit), row-locked. A foreign id,
    a test reminder and a deleted one are all NotFound."""
    r = (await s.execute(select(PlReminder).where(PlReminder.id == rid, PlReminder.user_id == uid, PlReminder.entity_type == "custom")
                         .with_for_update())).scalars().first()
    if r is None or r.kind == "test" or r.status == "cancelled":
        raise NotFound("reminder")
    return r


async def update_custom_reminder(uid: str, rid: int, body: dict) -> dict:
    """Change the words and / or the time of one of the learner's own reminders. A new time (even for one that already fired or was missed)
    arms it again; nothing sent earlier is repeated. Past times are refused like on create."""
    async with _S() as s:
        p = await _prefs(s, uid)
        r = await _own_custom_reminder(s, uid, rid)
        title = r.title
        if "title" in body:
            title = rules.clean_str(body.get("title"), 160)
            if not title:
                raise Invalid("title")
        fire = r.fire_at
        if body.get("date") or body.get("time"):
            cur = tu.to_local(r.fire_at, p.tz) if r.fire_at is not None else tu.local_now(p.tz)
            d = tu.parse_date(body.get("date")) if body.get("date") else cur.date()
            if d is None:
                raise Invalid("date")
            tm = tu.parse_hhmm(body.get("time")) if body.get("time") else cur.time().replace(second=0, microsecond=0)
            if tm is None:
                raise Invalid("time")
            fire = tu.to_utc(d, tm, p.tz)
            if fire != r.fire_at and fire < _utc() - dt.timedelta(minutes=1):
                raise Invalid("past")
        if title != r.title or fire != r.fire_at:
            r.title = title
            if fire != r.fire_at:
                r.fire_at, r.tz, r.status = fire, p.tz, "scheduled"
                r.attempts, r.followups_sent, r.snooze_count, r.push_state, r.last_error = 0, 0, 0, "none", ""
                r.claimed_at = r.sent_at = r.acted_at = None
                r.action = ""
            _ev(s, uid, "custom", r.id, "edited")
        await s.commit()
        return reminder_json(r)


async def delete_custom_reminder(uid: str, rid: int) -> dict:
    """Remove one of the learner's own reminders: it is cancelled (so it never fires, the scheduler re-checks the status at send time) and
    leaves every list. A second call changes nothing."""
    async with _S() as s:
        r = (await s.execute(select(PlReminder).where(PlReminder.id == rid, PlReminder.user_id == uid, PlReminder.entity_type == "custom")
                             .with_for_update())).scalars().first()
        if r is None or r.kind == "test":
            raise NotFound("reminder")
        if r.status != "cancelled":
            r.status, r.acted_at, r.action = "cancelled", _utc(), "deleted"
            _ev(s, uid, "custom", r.id, "deleted")
        await s.commit()
        return reminder_json(r)


async def act_reminder(uid: str, rid: int, action: str, minutes: int | None = None, *, by_token: bool = False) -> dict:
    """done | later | skip. Idempotent: a repeated or stale action returns the current state and writes no second event."""
    if action not in ("done", "later", "skip"):
        raise Invalid("action")
    async with _S() as s:
        p = await _prefs(s, uid)
        r = (await s.execute(select(PlReminder).where(PlReminder.id == rid, PlReminder.user_id == uid).with_for_update())).scalars().first()
        if r is None:
            raise NotFound("reminder")
        now = _utc()
        if r.status in ("done", "skipped", "cancelled", "expired") and not (action == "later" and r.status == "expired"):
            await s.commit()
            return reminder_json(r)
        if action == "later":
            if r.status == "scheduled" and r.snooze_count > 0 and r.fire_at and r.fire_at > now:
                await s.commit()
                return reminder_json(r)                                          # already snoozed (a second tap, or the push + the app)
            gap = rules.clamp_int(minutes, 5, 240, p.snooze_min)
            r.status, r.fire_at, r.snooze_count, r.followups_sent = "scheduled", now + dt.timedelta(minutes=gap), r.snooze_count + 1, 0
            r.acted_at, r.action, r.push_state, r.claimed_at = now, "later", "none", None
            _ev(s, uid, r.entity_type, r.entity_id, "acted", {"a": "later", "by": "token" if by_token else "app"})
        else:
            r.status, r.acted_at, r.action = ("done" if action == "done" else "skipped"), now, action
            _ev(s, uid, r.entity_type, r.entity_id, "acted", {"a": action, "by": "token" if by_token else "app"})
            if r.entity_type == "task" and r.entity_id:
                t = (await s.execute(select(PlTask).where(PlTask.id == r.entity_id, PlTask.user_id == uid).with_for_update())).scalars().first()
                if t is not None and t.status == "open" and not t.is_series:
                    t.status = "done" if action == "done" else "skipped"
                    t.completed_at, t.skipped_at = (now, None) if action == "done" else (None, now)
                    t.updated_at = now
                    await s.flush()
                    await _cancel_reminders(s, uid, "task", t.id, except_id=r.id)
                    if t.goal_id:
                        await _recompute_goal(s, t.goal_id)
                    _ev(s, uid, "task", t.id, "completed" if action == "done" else "skipped", {"via": "reminder"})
            elif r.entity_type == "habit" and r.entity_id:
                h = (await s.execute(select(PlHabit).where(PlHabit.id == r.entity_id, PlHabit.user_id == uid))).scalars().first()
                day = tu.parse_date((r.meta or {}).get("day")) or tu.local_today(p.tz)
                if h is not None:
                    row = (await s.execute(select(PlHabitLog).where(PlHabitLog.habit_id == h.id, PlHabitLog.day == day).with_for_update())).scalars().first()
                    cnt, st = (h.target_count, "logged") if action == "done" else (0, "skipped")
                    if row is None:
                        s.add(PlHabitLog(habit_id=h.id, user_id=uid, day=day, count=cnt, state=st))
                    elif row.count < cnt or action == "skip":
                        row.count, row.state, row.updated_at = cnt, st, now
        await s.commit()
        return reminder_json(r)


async def reminder_owner(rid: int) -> str | None:
    """The owner of a reminder - used only by the token-authenticated endpoint, which has no session to take it from."""
    async with _S() as s:
        r = await s.get(PlReminder, rid)
        return r.user_id if r is not None else None


# ----------------------------------------------------------------------------- the Today dashboard
async def today(uid: str) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        td = tu.local_today(p.tz, now)
        lo, hi = tu.day_bounds_utc(td, p.tz)
        base = [PlTask.user_id == uid, PlTask.deleted_at.is_(None), PlTask.is_series.is_(False)]
        open_rows = (await s.execute(select(PlTask).where(*base, PlTask.status == "open", or_(PlTask.due_date <= td, PlTask.pin_date == td))
                                     .order_by(PlTask.due_at.asc().nulls_last(), PlTask.priority.desc()).limit(120))).scalars().all()
        done_rows = (await s.execute(select(PlTask).where(*base, PlTask.status == "done", PlTask.completed_at >= lo, PlTask.completed_at < hi)
                                     .order_by(PlTask.completed_at.desc()).limit(30))).scalars().all()
        titles = await _goal_titles(s, uid, {r.goal_id for r in open_rows + done_rows})
        snoozed = await _snoozed_ids(s, uid, [r.id for r in open_rows])
        tj = lambda r: task_json(r, now, p.tz, titles, snoozed)
        overdue = [r for r in open_rows if r.due_at is not None and r.due_at < now]
        due_today = [r for r in open_rows if r.due_date == td and not (r.due_at is not None and r.due_at < now)]
        pinned = [r for r in open_rows if r.pin_date == td]
        prio: list = []
        for r in sorted(pinned, key=lambda x: (x.due_at is None, x.due_at)) + sorted(overdue, key=lambda x: (-x.priority, x.due_at)) + sorted(due_today, key=lambda x: (-x.priority, x.due_at is None, x.due_at)):
            if r not in prio:
                prio.append(r)
        # habits
        hs = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.deleted_at.is_(None), PlHabit.status == "active").order_by(PlHabit.id))).scalars().all()
        logs = await _logs_for(s, uid, [h.id for h in hs], td, days=30)
        hj = [habit_json(h, logs.get(h.id, {}), td) for h in hs]
        eng = await _english_habit(s, uid, p, td)
        habits = ([eng] if eng else []) + hj
        sched_today = [h for h in habits if h["scheduled_today"]]
        # goals (active, with the next action)
        gs = (await s.execute(select(PlGoal).where(PlGoal.user_id == uid, PlGoal.deleted_at.is_(None), PlGoal.status == "active").order_by(PlGoal.created_at.desc()).limit(5))).scalars().all()
        goals = [await _goal_full(s, g, p) for g in gs]
        nxt = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, PlReminder.status == "scheduled", PlReminder.fire_at > now)
                               .order_by(PlReminder.fire_at.asc()).limit(1))).scalars().first()
        due = (await due_cards_in(s, uid, now))
        # the learner's own note-to-self reminders that are still ahead (a reminder is part of the day: Today lists them, DuSu reads them all)
        rem_rows = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, PlReminder.entity_type == "custom", PlReminder.kind != "test",
                                                             PlReminder.status.in_(("scheduled", "waiting")), PlReminder.fire_at > now)
                                    .order_by(PlReminder.fire_at.asc()).limit(12))).scalars().all()
        reminders = [reminder_brief(r, p.tz) for r in rem_rows]
        rem_today = sum(1 for x in reminders if x.get("day") == td.isoformat()) + sum(1 for x in due if x.get("entity_type") == "custom")
        await s.commit()
        return {"now": now.isoformat(), "tz": p.tz, "date": td.isoformat(), "dow": td.weekday(), "hour": tu.local_now(p.tz, now).hour,
                "counts": {"open_today": len(due_today) + len([r for r in pinned if r not in due_today and r not in overdue]), "overdue": len(overdue),
                           "done_today": len(done_rows), "pinned": len(pinned), "reminders_today": rem_today,
                           "habits_done": sum(1 for h in sched_today if h["state_today"] in ("done", "skipped")), "habits_total": len(sched_today)},
                "due": due, "reminders": reminders, "priorities": [tj(r) for r in prio[:3]], "today": [tj(r) for r in due_today], "overdue": [tj(r) for r in overdue[:20]],
                "done_today": [tj(r) for r in done_rows], "habits": habits, "goals": goals,
                "next_reminder": ({"title": nxt.title, "fire_at": _iso(nxt.fire_at), "kind": nxt.kind} if nxt else None), "prefs": prefs_json(p)}


async def due_cards_in(s, uid: str, now: dt.datetime) -> list:
    rows = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, or_(PlReminder.status == "sent", and_(PlReminder.status == "scheduled", PlReminder.fire_at <= now)))
                            .order_by(PlReminder.fire_at.asc()).limit(5))).scalars().all()
    tids = [r.entity_id for r in rows if r.entity_type == "task" and r.entity_id]
    tasks = {}
    if tids:
        tasks = {t.id: t for t in (await s.execute(select(PlTask).where(PlTask.user_id == uid, PlTask.id.in_(tids)))).scalars().all()}
    return [reminder_json(r, tasks.get(r.entity_id), now) for r in rows]


# ----------------------------------------------------------------------------- data rights
def _row_dict(r) -> dict:
    out = {}
    for c in r.__table__.columns:
        v = getattr(r, c.name)
        out[c.name] = v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v
    return out


async def export_all(uid: str) -> dict:
    """Every planner row the learner owns, as JSON (data rights). Push subscription keys are not exported - they are device secrets."""
    async with _S() as s:
        out: dict[str, Any] = {"exported_at": _utc().isoformat()}
        for M in PL_TABLES:
            if M is PlPushSub:
                n = (await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid))).scalar() or 0
                out["push_devices"] = int(n)
                continue
            col = M.user_id
            rows = (await s.execute(select(M).where(col == uid))).scalars().all()
            out[M.__tablename__] = [_row_dict(r) for r in rows]
        await s.commit()
        return out


async def delete_all(uid: str) -> dict:
    """Hard delete everything this learner has in My Day (children first). The account itself is untouched."""
    async with _S() as s:
        await delete_rows(s, [uid])
        await s.commit()
    return {"ok": True}


async def delete_rows(s, uids: list) -> None:
    """FK-safe delete of every planner row for these users, inside the caller's transaction (also used by delete_user / admin_wipe_users)."""
    for M in (PlEvent, PlReminder, PlHabitLog, PlHabit, PlMilestone, PlTask, PlGoal, PlPushSub, PlPrefs):
        await s.execute(delete(M).where(M.user_id.in_(uids)))


# ----------------------------------------------------------------------------- push subscriptions + the test reminder + the small summary
async def subscribe_push(uid: str, sub: dict, ua: str = "") -> dict:
    """Register one device (already validated by push.clean_subscription). At most 5 per learner (the oldest is dropped); an endpoint that was
    registered under another account (a shared phone) moves to this one. Registering = the learner chose push, so push_on is switched on."""
    async with _S() as s:
        p = await _prefs(s, uid)
        row = (await s.execute(select(PlPushSub).where(PlPushSub.endpoint == sub["endpoint"]).with_for_update())).scalars().first()
        if row is None:
            s.add(PlPushSub(user_id=uid, endpoint=sub["endpoint"], p256dh=sub["p256dh"], auth=sub["auth"], ua=rules.clean_str(ua, 200)))
        else:
            row.user_id, row.p256dh, row.auth, row.fail_count = uid, sub["p256dh"], sub["auth"], 0
        await s.flush()
        mine = (await s.execute(select(PlPushSub).where(PlPushSub.user_id == uid).order_by(PlPushSub.created_at.desc(), PlPushSub.id.desc()))).scalars().all()
        for old in mine[rules.LIMITS["push_devices"]:]:
            await s.delete(old)
        p.push_on = True
        _ev(s, uid, "push", None, "subscribed")
        await s.commit()
        return {"ok": True, "devices": min(len(mine), rules.LIMITS["push_devices"]), "push_on": True}


async def unsubscribe_push(uid: str, endpoint: str | None = None) -> dict:
    async with _S() as s:
        p = await _prefs(s, uid)
        q = delete(PlPushSub).where(PlPushSub.user_id == uid)
        if endpoint:
            q = q.where(PlPushSub.endpoint == endpoint)
        await s.execute(q)
        left = (await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid))).scalar() or 0
        if not left:
            p.push_on = False
        _ev(s, uid, "push", None, "unsubscribed")
        await s.commit()
        return {"ok": True, "devices": int(left), "push_on": bool(p.push_on)}


async def test_reminder(uid: str, seconds: int = 60) -> dict:
    """'Send me a test reminder': a custom reminder ~60 s out, so the owner can watch the whole path (scheduler -> push -> notification) on a
    real phone. One every 3 minutes per learner."""
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        recent = (await s.execute(select(func.count()).select_from(PlReminder).where(PlReminder.user_id == uid, PlReminder.kind == "test",
                                                                                    PlReminder.created_at >= now - dt.timedelta(minutes=3)))).scalar() or 0
        if recent:
            raise LimitReached("test")
        fire = now + dt.timedelta(seconds=max(15, min(300, int(seconds))))
        r = await _upsert_reminder(s, uid, entity_type="custom", entity_id=None, kind="test", title="DuSu test reminder",
                                   body="If you can read this, reminders reach you.", key=f"test:{uid[:24]}:{fire:%Y%m%dT%H%M%S}", fire_at=fire, tz=p.tz, status="scheduled")
        await s.commit()
        return reminder_json(r)


async def summary(uid: str) -> dict:
    """The few numbers for the Home card ('3 tasks left · 2 of 3 habits') - cheap, no lists."""
    async with _S() as s:
        p = await _prefs(s, uid)
        now = _utc()
        td = tu.local_today(p.tz, now)
        base = [PlTask.user_id == uid, PlTask.deleted_at.is_(None), PlTask.is_series.is_(False), PlTask.status == "open"]
        due_today = (await s.execute(select(func.count()).select_from(PlTask).where(*base, or_(PlTask.due_date == td, PlTask.pin_date == td)))).scalar() or 0
        overdue = (await s.execute(select(func.count()).select_from(PlTask).where(*base, PlTask.due_at < now))).scalar() or 0
        lo, hi = tu.day_bounds_utc(td, p.tz)
        done_today = (await s.execute(select(func.count()).select_from(PlTask).where(
            PlTask.user_id == uid, PlTask.deleted_at.is_(None), PlTask.is_series.is_(False), PlTask.status == "done",
            PlTask.completed_at >= lo, PlTask.completed_at < hi))).scalar() or 0
        hs = (await s.execute(select(PlHabit).where(PlHabit.user_id == uid, PlHabit.deleted_at.is_(None), PlHabit.status == "active"))).scalars().all()
        logs = await _logs_for(s, uid, [h.id for h in hs], td, days=2)
        sched = [h for h in hs if rules.habit_scheduled(h.schedule if isinstance(h.schedule, dict) else {}, h.start_date, h.end_date, td)]
        done = sum(1 for h in sched if (logs.get(h.id, {}).get(td, (0, "logged"))[1] == "skipped" or logs.get(h.id, {}).get(td, (0, "logged"))[0] >= h.target_count))
        nxt = (await s.execute(select(PlReminder).where(PlReminder.user_id == uid, PlReminder.status == "scheduled", PlReminder.fire_at > now)
                               .order_by(PlReminder.fire_at.asc()).limit(1))).scalars().first()
        due_cards = (await s.execute(select(func.count()).select_from(PlReminder).where(PlReminder.user_id == uid, or_(PlReminder.status == "sent",
                     and_(PlReminder.status == "scheduled", PlReminder.fire_at <= now))))).scalar() or 0
        rem_today = (await s.execute(select(func.count()).select_from(PlReminder).where(
            PlReminder.user_id == uid, PlReminder.entity_type == "custom", PlReminder.kind != "test", PlReminder.status.in_(("scheduled", "waiting", "sent")),
            PlReminder.fire_at >= lo, PlReminder.fire_at < hi))).scalar() or 0
        await s.commit()
        return {"open_today": int(due_today), "overdue": int(overdue), "done_today": int(done_today), "habits_done": done, "habits_total": len(sched), "due_reminders": int(due_cards),
                "reminders_today": int(rem_today), "next_reminder": ({"title": nxt.title, "fire_at": _iso(nxt.fire_at)} if nxt else None), "tz": p.tz}
