"""My Day - the reminder engine (DUSU_GOALS_PLAN.md §6).

One asyncio task in the web process (there is no scheduler anywhere else in this stack); Postgres is the queue, so a restart or a deploy
loses nothing: rows live in `pl_reminders`, a delivery that died mid-flight is reclaimed after two minutes, and a reminder more than 120
minutes late is shown in the app only - never as a stale push.

    claim (FOR UPDATE SKIP LOCKED) -> deliver (cancel checks, quiet hours, stale, push) -> follow-ups / expiry -> materialize -> prune

The loop catches every exception, logs the class name only (never a title or a note) and sleeps: it can never take the web server down.
`tick()` takes the clock and the push sender as arguments so the tests drive it with a fake clock and a fake sender.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import time

from sqlalchemy import delete, func, select, text, update

from .. import db
from . import push, rules, service as svc, timeutil as tu
from .models import PlEvent, PlPrefs, PlPushSub, PlReminder

TICK_SEC = 15
START_DELAY_SEC = 8
MATERIALIZE_EVERY = 600
PRUNE_EVERY = 86400
RECLAIM_AFTER_MIN = 2
CLAIM_BATCH = 50
BACKOFF_SEC = (30, 120, 600)
MAX_ATTEMPTS = 4
STALE_EXPIRE_H = 24

state = {"started": None, "ticks": 0, "last_tick": None, "last_error": "", "last_stats": {}}
_mono = {"mat": 0.0, "prune": 0.0}


def _S():
    return db._Session()          # type: ignore[misc]


# ----------------------------------------------------------------------------- the loop
async def run_forever(mode_fn, enabled_fn) -> None:
    """Started from the app's startup hook. `mode_fn()` -> the planner switch ('off' idles the loop); `enabled_fn(email)` -> may this learner
    use My Day (the owner-only stage)."""
    state["started"] = tu.now_utc().isoformat()
    await asyncio.sleep(START_DELAY_SEC)                     # let startup finish first
    while True:
        try:
            if await mode_fn() != "off":
                state["last_stats"] = await tick(enabled_fn)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state["last_error"] = type(e).__name__
            print(f"[planner] tick failed: {type(e).__name__}")
        await asyncio.sleep(TICK_SEC)


async def tick(enabled_fn, now: dt.datetime | None = None, sender=None, materialize: bool | None = None) -> dict:
    now = now or tu.now_utc()
    stats = {"reclaimed": 0, "claimed": 0, "delivered": 0, "deferred": 0, "cancelled": 0, "stale": 0, "followups": 0, "expired": 0, "failed": 0}
    stats["reclaimed"] = await reclaim(now)
    for rid in await claim(now):
        stats["claimed"] += 1
        try:
            outcome = await deliver(rid, enabled_fn, now, sender)
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # one bad row never stops the rest
            print(f"[planner] deliver failed: {type(e).__name__}")
            await _fail_row(rid, type(e).__name__)
            outcome = "failed"
        key = {"sent": "delivered", "deferred": "deferred", "cancelled": "cancelled", "stale": "stale", "retry": "failed", "failed": "failed"}.get(outcome)
        if key:
            stats[key] += 1
    stats["followups"], stats["expired"] = await followups(now)
    if materialize is None:
        materialize = (time.monotonic() - _mono["mat"]) >= MATERIALIZE_EVERY
    if materialize:
        _mono["mat"] = time.monotonic()
        await svc.materialize_all()
    if (time.monotonic() - _mono["prune"]) >= PRUNE_EVERY:
        _mono["prune"] = time.monotonic()
        await prune(now)
    state["ticks"] += 1
    state["last_tick"] = now.isoformat()
    return stats


# ----------------------------------------------------------------------------- queue operations
async def reclaim(now: dt.datetime) -> int:
    """A delivery that died mid-flight (crash, deploy) is `sending` for too long: put it back."""
    async with _S() as s:
        r = await s.execute(update(PlReminder).where(PlReminder.status == "sending", PlReminder.claimed_at < now - dt.timedelta(minutes=RECLAIM_AFTER_MIN))
                            .values(status="scheduled", claimed_at=None).execution_options(synchronize_session=False))
        await s.commit()
        return r.rowcount or 0


async def claim(now: dt.datetime, limit: int = CLAIM_BATCH) -> list[int]:
    """Take up to `limit` due reminders. SKIP LOCKED + the unique occurrence key mean two loops (ever) cannot send the same reminder twice."""
    async with _S() as s:
        rows = await s.execute(text(
            "WITH c AS (SELECT id FROM pl_reminders WHERE status = 'scheduled' AND fire_at <= :now ORDER BY fire_at LIMIT :n FOR UPDATE SKIP LOCKED) "
            "UPDATE pl_reminders r SET status = 'sending', claimed_at = :now, attempts = r.attempts + 1 FROM c WHERE r.id = c.id RETURNING r.id"),
            {"now": now, "n": limit})
        ids = [x[0] for x in rows.all()]
        await s.commit()
        return sorted(ids)


async def _fail_row(rid: int, why: str) -> None:
    """A reminder whose delivery raised: withdraw it (a poisoned row must not be retried forever) and say why."""
    async with _S() as s:
        await s.execute(update(PlReminder).where(PlReminder.id == rid, PlReminder.status == "sending")
                        .values(status="cancelled", last_error=why[:120]).execution_options(synchronize_session=False))
        await s.commit()


# ----------------------------------------------------------------------------- delivery
async def _entity_check(s, r: PlReminder, p: PlPrefs, now: dt.datetime) -> tuple[bool, str]:
    """Is the thing this reminder is about still alive and still worth a nudge? (ok, reason-if-not). Re-checked at SEND time, not just when
    the reminder was planned - a task completed or a habit met a second ago must not ping."""
    if r.entity_type == "task":
        t = await s.get(svc.PlTask, r.entity_id) if r.entity_id else None
        if t is None or t.user_id != r.user_id or t.deleted_at is not None or t.status != "open" or t.is_series:
            return False, "gone"
        if t.goal_id:
            g = await s.get(svc.PlGoal, t.goal_id)
            if g is not None and g.status != "active":
                return False, "goal_paused"
        return True, ""
    if r.entity_type == "habit":
        h = await s.get(svc.PlHabit, r.entity_id) if r.entity_id else None
        if h is None or h.user_id != r.user_id or h.deleted_at is not None or h.status != "active":
            return False, "gone"
        day = tu.parse_date((r.meta or {}).get("day")) or tu.local_today(p.tz, now)
        log = (await s.execute(select(svc.PlHabitLog).where(svc.PlHabitLog.habit_id == h.id, svc.PlHabitLog.day == day))).scalars().first()
        if log is not None and (log.state == "skipped" or log.count >= h.target_count):
            return False, "met"
        return True, ""
    if svc.is_rule_occurrence(r):
        # one ring of a repeating reminder: the rule must still exist, still be running, and still ring on THIS day at THIS time (it may have been
        # edited, paused or deleted after this ring was made - a ring the learner changed their mind about must not go off)
        rule = await s.get(svc.PlReminderRule, r.entity_id) if r.entity_id else None
        meta = r.meta if isinstance(r.meta, dict) else {}
        day = tu.parse_date(meta.get("day"))
        if (rule is None or rule.user_id != r.user_id or rule.status != "active" or day is None
                or not rules.days_scheduled(rule.days, day) or meta.get("time") != rule.time):
            return False, "gone"
        return True, ""
    return True, ""


async def _truthy(v) -> bool:
    """`enabled_fn` may be a plain function or a coroutine function."""
    if inspect.isawaitable(v):
        v = await v
    return bool(v)


async def _user_lang(s, uid: str) -> str:
    mem = await s.get(db.Memory, uid)
    lp = (mem.facts or {}).get("lang_pref") if (mem is not None and isinstance(mem.facts, dict)) else None
    return "en" if isinstance(lp, dict) and lp.get("lang") == "en" else "hi"


async def deliver(rid: int, enabled_fn, now: dt.datetime, sender=None) -> str:
    """Deliver one claimed reminder. Returns sent | deferred | cancelled | stale | retry | skip."""
    sender = sender or push.send
    # ---- phase A: decide (short transaction, row locked)
    async with _S() as s:
        r = (await s.execute(select(PlReminder).where(PlReminder.id == rid).with_for_update())).scalars().first()
        if r is None or r.status != "sending":
            await s.commit()
            return "skip"
        user = await s.get(db.User, r.user_id)
        p = await svc._prefs(s, r.user_id)
        ok, why = await _entity_check(s, r, p, now)
        if user is None or (getattr(user, "status", "active") or "active") == "blocked":
            ok, why = False, "blocked"
        elif not await _truthy(enabled_fn(user.email)):
            ok, why = False, "switch_off"
        elif p.paused_all:
            ok, why = False, "paused"
        if not ok:
            r.status, r.last_error, r.claimed_at = "cancelled", why[:120], None
            svc._ev(s, r.user_id, r.entity_type, r.entity_id, "cancelled", {"why": why})
            await s.commit()
            return "cancelled"
        if p.quiet_on:
            qs, qe = tu.parse_hhmm(p.quiet_start), tu.parse_hhmm(p.quiet_end)
            release = tu.quiet_release_utc(now, p.tz, qs, qe) if (qs and qe) else None
            if release is not None:
                r.status, r.fire_at, r.claimed_at, r.attempts = "scheduled", release, None, max(0, r.attempts - 1)
                svc._ev(s, r.user_id, r.entity_type, r.entity_id, "deferred_quiet")
                await s.commit()
                return "deferred"
        late_min = ((now - r.fire_at).total_seconds() / 60.0) if r.fire_at is not None else 0.0
        if late_min > svc.STALE_MIN:
            r.status, r.sent_at, r.push_state, r.claimed_at = "sent", now, "stale", None
            svc._ev(s, r.user_id, r.entity_type, r.entity_id, "stale", {"late_min": int(late_min)})
            await s.commit()
            return "stale"
        hour_ago = now - dt.timedelta(hours=1)
        sent_h = (await s.execute(select(func.count()).select_from(PlReminder).where(PlReminder.user_id == r.user_id, PlReminder.sent_at >= hour_ago))).scalar() or 0
        capped = sent_h >= rules.LIMITS["reminders_per_hour"]
        subs = []
        if p.push_on and not capped:
            subs = [{"id": x.id, "endpoint": x.endpoint, "p256dh": x.p256dh, "auth": x.auth} for x in
                    (await s.execute(select(PlPushSub).where(PlPushSub.user_id == r.user_id))).scalars().all()]
        lang = await _user_lang(s, r.user_id)
        title, body, hide, attempts = r.title, r.body or "", bool(p.hide_details), r.attempts
        push_on = bool(p.push_on)
        was_capped = bool(capped)
        await s.commit()

    # ---- phase B: the network, with no database lock held
    results: list[tuple[int, str, int]] = []
    if subs:
        tokens = {a: push.make_token(rid, a) for a in ("done", "later", "skip")}
        payload = push.build_payload(rid, title, body, lang, hide, tokens)
        for sub in subs:
            kind, code = await sender(sub, payload)
            results.append((sub["id"], kind, code))

    # ---- phase C: record what happened
    async with _S() as s:
        r = (await s.execute(select(PlReminder).where(PlReminder.id == rid).with_for_update())).scalars().first()
        if r is None:
            await s.commit()
            return "skip"
        if r.status != "sending":                                 # completed / cancelled while we were sending: leave that alone
            await s.commit()
            return "skip"
        gone = [i for i, k, _c in results if k == "gone"]
        if gone:
            await s.execute(delete(PlPushSub).where(PlPushSub.id.in_(gone)))
        okids = [i for i, k, _c in results if k == "ok"]
        if okids:
            await s.execute(update(PlPushSub).where(PlPushSub.id.in_(okids)).values(last_ok_at=now, fail_count=0))
        for i, k, _c in results:
            if k in ("transient", "error"):
                await s.execute(update(PlPushSub).where(PlPushSub.id == i).values(fail_count=PlPushSub.fail_count + 1))
        if subs:
            svc._ev(s, r.user_id, r.entity_type, r.entity_id, "push_attempt", {"n": len(subs)})
        outcome = "sent"
        if okids:
            r.push_state = "accepted"
            svc._ev(s, r.user_id, r.entity_type, r.entity_id, "push_accepted", {"n": len(okids)})
        elif subs and all(k == "gone" for _i, k, _c in results):
            r.push_state = "no_subscription"
        elif subs:                                                # every send failed: try again with a backoff, then fall back to in-app
            if attempts < MAX_ATTEMPTS:
                r.status, r.fire_at, r.claimed_at = "scheduled", now + dt.timedelta(seconds=BACKOFF_SEC[min(attempts - 1, len(BACKOFF_SEC) - 1)]), None
                r.last_error = "push_retry"
                await s.commit()
                return "retry"
            r.push_state = "failed"
            svc._ev(s, r.user_id, r.entity_type, r.entity_id, "push_failed", {"codes": [c for _i, _k, c in results][:3]})
        else:
            r.push_state = "no_subscription" if (push_on and not was_capped) else "none"
        r.status, r.sent_at, r.claimed_at = "sent", now, None
        r.last_error = "" if r.push_state != "failed" else "push_failed"
        await s.commit()
        return outcome


# ----------------------------------------------------------------------------- follow-ups, expiry
async def followups(now: dt.datetime) -> tuple[int, int]:
    """After a reminder was SENT and nobody acted: up to the learner's `followups` more, `gap` minutes apart (the same row, fired again);
    then it expires and the task simply shows as overdue - there is no endless pushing. Habits get no follow-ups; a stale (in-app only)
    reminder just expires after a day."""
    async with _S() as s:
        up = await s.execute(text(
            "UPDATE pl_reminders r SET status = 'scheduled', fire_at = :now, followups_sent = r.followups_sent + 1, attempts = 0, claimed_at = NULL, push_state = 'none' "
            "FROM (SELECT r2.id FROM pl_reminders r2 LEFT JOIN pl_prefs p ON p.user_id = r2.user_id "
            "      WHERE r2.status = 'sent' AND r2.entity_type IN ('task', 'custom') AND r2.kind <> 'test' AND r2.push_state <> 'stale' "
            "        AND r2.sent_at + make_interval(mins => COALESCE(p.followup_gap_min, 30)) <= :now "
            "        AND r2.followups_sent < COALESCE(p.followups, 1)) c WHERE r.id = c.id RETURNING r.id"), {"now": now})
        n_follow = len(up.all())
        ex = await s.execute(text(
            "UPDATE pl_reminders r SET status = 'expired' "
            "FROM (SELECT r2.id FROM pl_reminders r2 LEFT JOIN pl_prefs p ON p.user_id = r2.user_id WHERE r2.status = 'sent' AND ("
            "      (r2.push_state = 'stale' AND r2.sent_at + make_interval(hours => :sh) <= :now) "
            "   OR (r2.push_state <> 'stale' AND r2.sent_at + make_interval(mins => COALESCE(p.followup_gap_min, 30)) <= :now "
            "        AND (r2.entity_type = 'habit' OR r2.kind = 'test' OR r2.followups_sent >= COALESCE(p.followups, 1))))) c WHERE r.id = c.id RETURNING r.id"),
            {"now": now, "sh": STALE_EXPIRE_H})
        n_exp = len(ex.all())
        await s.commit()
        return n_follow, n_exp


async def prune(now: dt.datetime) -> None:
    """Bounded growth: events older than 180 days and long-finished reminders (90 days) go."""
    async with _S() as s:
        await s.execute(delete(PlEvent).where(PlEvent.at < now - dt.timedelta(days=180)))
        await s.execute(delete(PlReminder).where(PlReminder.status.in_(("done", "skipped", "expired", "cancelled", "sent")),
                                                 PlReminder.created_at < now - dt.timedelta(days=90)))
        await s.commit()


# ----------------------------------------------------------------------------- health (dashboard)
async def health() -> dict:
    now = tu.now_utc()
    async with _S() as s:
        async def count(*conds):
            return int((await s.execute(select(func.count()).select_from(PlReminder).where(*conds))).scalar() or 0)
        day = now - dt.timedelta(hours=24)
        out = {"ticks": state["ticks"], "last_tick": state["last_tick"], "last_error": state["last_error"],
               "queue_late": await count(PlReminder.status == "scheduled", PlReminder.fire_at < now - dt.timedelta(minutes=2)),
               "sending_stuck": await count(PlReminder.status == "sending", PlReminder.claimed_at < now - dt.timedelta(minutes=RECLAIM_AFTER_MIN)),
               "scheduled": await count(PlReminder.status == "scheduled"),
               "sent_24h": await count(PlReminder.sent_at >= day), "push_accepted_24h": await count(PlReminder.sent_at >= day, PlReminder.push_state == "accepted"),
               "push_failed_24h": await count(PlReminder.sent_at >= day, PlReminder.push_state == "failed"),
               "push_available": push.AVAILABLE}
        out["push_devices"] = int((await s.execute(select(func.count()).select_from(PlPushSub))).scalar() or 0)
        await s.commit()
        return out
