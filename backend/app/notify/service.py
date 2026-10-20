"""Notifications - every read and write, scoped to the learner.

Reuses My Day's device table (`pl_push_subs`), its settings row (`pl_prefs`: time zone, quiet hours, lock-screen privacy, the push switch) and its
sender (`planner.push.send`). What is new here is only the decision of WHAT to say and WHEN (`rules.py`) and the outbox that records it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import db
from ..planner import push, service as plsvc, timeutil as tu
from ..planner.models import PlPrefs, PlPushSub
from . import rules, tokens
from .models import NtOutbox, NtPrefs

UTC = dt.timezone.utc
CLAIM_BATCH = 50
BACKOFF_SEC = (30, 120)
MAX_ATTEMPTS = 3
RECLAIM_AFTER_MIN = 2
TEST_GAP_MIN = 3
KEEP_DAYS = 90
RECENT_ROWS = 10


class Invalid(Exception):
    """A request the learner can fix. `args[0]` is a short code."""


class LimitReached(Exception):
    pass


def _S():
    return db._Session()          # type: ignore[misc]


def _utc() -> dt.datetime:
    return tu.now_utc()


# ----------------------------------------------------------------------------- prefs
async def _prefs(s, uid: str) -> NtPrefs:
    """The learner's notification settings, created on first use. INSERT ... ON CONFLICT DO NOTHING (not check-then-insert): the app opens with
    several requests at once and the losers of that race must not die with a duplicate key."""
    n = await s.get(NtPrefs, uid)
    if n is None:
        await s.execute(pg_insert(NtPrefs).values(user_id=uid, enabled=True, kinds={k: True for k in rules.KINDS}, nudge_time=rules.DEFAULT_NUDGE,
                                                  updated_at=_utc()).on_conflict_do_nothing(index_elements=["user_id"]))
        n = (await s.execute(select(NtPrefs).where(NtPrefs.user_id == uid).execution_options(populate_existing=True))).scalars().first()
    return n


def _prefs_json(n: NtPrefs) -> dict:
    return {"enabled": bool(n.enabled), "kinds": rules.clean_kinds(n.kinds), "nudge_time": rules.clean_time(n.nudge_time) or rules.DEFAULT_NUDGE}


async def get_prefs(uid: str) -> dict:
    async with _S() as s:
        n = await _prefs(s, uid)
        p = await plsvc._prefs(s, uid)
        devices = (await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid))).scalar() or 0
        recent = (await s.execute(select(NtOutbox).where(NtOutbox.user_id == uid, NtOutbox.status == "sent", NtOutbox.kind != "test")
                                  .order_by(NtOutbox.sent_at.desc()).limit(5))).scalars().all()
        out = _prefs_json(n)
        out.update({"devices": int(devices), "push_on": bool(p.push_on), "tz": p.tz, "hide_details": bool(p.hide_details),
                    "quiet_on": bool(p.quiet_on), "quiet_start": p.quiet_start, "quiet_end": p.quiet_end, "push_available": push.AVAILABLE,
                    "recent": [{"id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                                "opened": r.opened_at is not None} for r in recent]})
        await s.commit()
        return out


async def put_prefs(uid: str, body: dict) -> dict:
    """Update the learner's settings. A partial body is fine; an invalid value is a 422 (never silently ignored)."""
    if not isinstance(body, dict):
        raise Invalid("body")
    async with _S() as s:
        n = await _prefs(s, uid)
        if "enabled" in body:
            if not isinstance(body["enabled"], bool):
                raise Invalid("enabled")
            n.enabled = body["enabled"]
        if "kinds" in body:
            if not isinstance(body["kinds"], dict) or any(k not in rules.KINDS or not isinstance(v, bool) for k, v in body["kinds"].items()):
                raise Invalid("kinds")
            n.kinds = rules.clean_kinds(body["kinds"], n.kinds)
        if "nudge_time" in body:
            t = rules.clean_time(body["nudge_time"])
            if t is None:
                raise Invalid("nudge_time")
            n.nudge_time = t
        if "hide_details" in body:                                  # lock-screen privacy is My Day's one setting (pl_prefs): written here, not copied
            if not isinstance(body["hide_details"], bool):
                raise Invalid("hide_details")
            (await plsvc._prefs(s, uid)).hide_details = body["hide_details"]
        n.updated_at = _utc()
        await s.commit()
    return await get_prefs(uid)


# ----------------------------------------------------------------------------- the facts a decision needs
def _active_days(facts: dict) -> set[dt.date]:
    """The days the learner practised (memory.daily_stats, last ~14 days): any day with minutes, sentences or a session."""
    out: set[dt.date] = set()
    stats = facts.get("daily_stats") if isinstance(facts.get("daily_stats"), dict) else {}
    for k, v in stats.items():
        try:
            if isinstance(v, dict) and (v.get("seconds") or v.get("sentences") or v.get("sessions")):
                out.add(dt.date.fromisoformat(str(k)[:10]))
        except ValueError:
            continue
    return out


def _letter_date(facts: dict) -> dt.date | None:
    last = facts.get("last_letter") if isinstance(facts.get("last_letter"), dict) else {}
    try:
        return dt.date.fromisoformat(str(last.get("date"))[:10]) if last.get("date") else None
    except ValueError:
        return None


def _lang(facts: dict) -> str:
    lp = facts.get("lang_pref") if isinstance(facts, dict) else None
    return "en" if isinstance(lp, dict) and lp.get("lang") == "en" else "hi"


def _snap(uid: str, user, p: PlPrefs, n: NtPrefs | None, prog, prof, mem, recent: list) -> dict:
    facts = mem.facts if (mem is not None and isinstance(mem.facts, dict)) else {}
    nick = facts.get("nickname") if isinstance(facts.get("nickname"), str) else ""
    return {
        "uid": uid, "tz": p.tz, "quiet_on": bool(p.quiet_on), "quiet_start": p.quiet_start, "quiet_end": p.quiet_end, "hide": bool(p.hide_details),
        "enabled": True if n is None else bool(n.enabled), "kinds": rules.clean_kinds(n.kinds if n is not None else None),
        "nudge_time": (rules.clean_time(n.nudge_time) if n is not None else None) or rules.DEFAULT_NUDGE,
        "onboarded": bool(prof is not None and prof.onboarded), "streak_days": int(prog.streak_days or 0) if prog is not None else 0,
        "last_active": prog.last_active if prog is not None else None, "xp": int(prog.xp or 0) if prog is not None else 0,
        "last_letter": _letter_date(facts), "active_days": _active_days(facts), "lang": _lang(facts),
        "name": nick or (user.name if user is not None else "") or "", "recent": recent,
    }


async def _recent_growth(s, uids: list[str]) -> dict[str, list[dict]]:
    """The last RECENT_ROWS delivered practice / streak nudges per learner, newest first (for the 'they ignored three in a row' rule)."""
    out: dict[str, list[dict]] = {u: [] for u in uids}
    if not uids:
        return out
    rows = (await s.execute(select(NtOutbox.user_id, NtOutbox.sent_at, NtOutbox.opened_at)
                            .where(NtOutbox.user_id.in_(uids), NtOutbox.kind.in_(("practice", "streak")), NtOutbox.status == "sent",
                                   NtOutbox.push_state == "accepted", NtOutbox.sent_at.is_not(None))
                            .order_by(NtOutbox.sent_at.desc()))).all()
    for uid, sent, opened in rows:
        if len(out[uid]) < RECENT_ROWS:
            out[uid].append({"sent_at": sent, "opened_at": opened})
    return out


async def _snaps(s, uids: list[str]) -> dict[str, dict]:
    """The full decision snapshot for each learner, loaded in bulk (one query per table, not per learner)."""
    if not uids:
        return {}
    users = {u.id: u for u in (await s.execute(select(db.User).where(db.User.id.in_(uids)))).scalars().all()}
    pls = {x.user_id: x for x in (await s.execute(select(PlPrefs).where(PlPrefs.user_id.in_(uids)))).scalars().all()}
    nts = {x.user_id: x for x in (await s.execute(select(NtPrefs).where(NtPrefs.user_id.in_(uids)))).scalars().all()}
    progs = {x.user_id: x for x in (await s.execute(select(db.Progress).where(db.Progress.user_id.in_(uids)))).scalars().all()}
    profs = {x.user_id: x for x in (await s.execute(select(db.Profile).where(db.Profile.user_id.in_(uids)))).scalars().all()}
    mems = {x.user_id: x for x in (await s.execute(select(db.Memory).where(db.Memory.user_id.in_(uids)))).scalars().all()}
    recent = await _recent_growth(s, uids)
    out = {}
    for u in uids:
        if u in users and u in pls:
            out[u] = _snap(u, users[u], pls[u], nts.get(u), progs.get(u), profs.get(u), mems.get(u), recent.get(u, []))
    return out


# ----------------------------------------------------------------------------- deciding: who gets what, today
async def materialize_all(enabled_fn, now: dt.datetime | None = None) -> dict:
    """Make today's outbox rows. Step 1 reads only the cheap per-learner settings of everyone who has a push device and opted in, and keeps the
    ones whose clock is near a send slot; step 2 loads the facts for just those and asks `rules.plan_today`. Idempotent (unique dedupe key)."""
    now = now or _utc()
    stats = {"considered": 0, "near_slot": 0, "created": 0}
    async with _S() as s:
        rows = (await s.execute(
            select(db.User.id, db.User.email, db.User.status, PlPrefs.tz, PlPrefs.quiet_on, PlPrefs.quiet_start, PlPrefs.quiet_end,
                   NtPrefs.enabled, NtPrefs.nudge_time)
            .join(PlPrefs, PlPrefs.user_id == db.User.id).outerjoin(NtPrefs, NtPrefs.user_id == db.User.id)
            .where(PlPrefs.push_on.is_(True), exists().where(PlPushSub.user_id == db.User.id)))).all()
        near: list[str] = []
        for uid, email, status, tz, qon, qs, qe, enabled, nudge in rows:
            stats["considered"] += 1
            if (status or "active") == "blocked":
                continue
            mini = {"enabled": True if enabled is None else bool(enabled), "tz": tz, "quiet_on": qon, "quiet_start": qs, "quiet_end": qe, "nudge_time": nudge}
            sl = rules.slots(mini, now)
            if (sl["daily"] is None and sl["weekly"] is None) or not await _truthy(enabled_fn(email)):
                continue
            near.append(uid)
        stats["near_slot"] = len(near)
        for uid, snap in (await _snaps(s, near)).items():
            for c in rules.plan_today(snap, now):
                r = await s.execute(pg_insert(NtOutbox).values(user_id=uid, kind=c["kind"], dedupe_key=c["dedupe_key"], fire_at=c["fire_at"],
                                                               url=rules.safe_url(c["url"]), status="scheduled", created_at=now)
                                    .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"]).returning(NtOutbox.id))
                if r.first() is not None:
                    stats["created"] += 1
        await s.commit()
    return stats


async def _truthy(v) -> bool:
    import inspect
    if inspect.isawaitable(v):
        v = await v
    return bool(v)


# ----------------------------------------------------------------------------- the queue
async def reclaim(now: dt.datetime) -> int:
    """A delivery that died mid-flight (crash, deploy) has been `sending` for too long: put it back."""
    async with _S() as s:
        r = await s.execute(update(NtOutbox).where(NtOutbox.status == "sending", NtOutbox.claimed_at < now - dt.timedelta(minutes=RECLAIM_AFTER_MIN))
                            .values(status="scheduled", claimed_at=None).execution_options(synchronize_session=False))
        await s.commit()
        return r.rowcount or 0


async def claim(now: dt.datetime, limit: int = CLAIM_BATCH) -> list[int]:
    """Take up to `limit` due rows. SKIP LOCKED means two loops (ever) cannot send the same row twice."""
    async with _S() as s:
        rows = await s.execute(text(
            "WITH c AS (SELECT id FROM nt_outbox WHERE status = 'scheduled' AND fire_at <= :now ORDER BY fire_at LIMIT :n FOR UPDATE SKIP LOCKED) "
            "UPDATE nt_outbox r SET status = 'sending', claimed_at = :now, attempts = r.attempts + 1 FROM c WHERE r.id = c.id RETURNING r.id"),
            {"now": now, "n": limit})
        ids = sorted(x[0] for x in rows.all())
        await s.commit()
        return ids


async def fail_row(nid: int, why: str) -> None:
    """A row whose delivery raised: withdraw it (a poisoned row must not be retried forever)."""
    async with _S() as s:
        await s.execute(update(NtOutbox).where(NtOutbox.id == nid, NtOutbox.status == "sending")
                        .values(status="cancelled", why=why[:24], claimed_at=None).execution_options(synchronize_session=False))
        await s.commit()


def _cancel(r: NtOutbox, why: str) -> str:
    r.status, r.why, r.claimed_at = "cancelled", why[:24], None
    return "cancelled"


async def deliver(nid: int, enabled_fn, now: dt.datetime, sender=None) -> str:
    """Deliver one claimed row. Returns sent | cancelled | retry | skip. Phase A decides inside a short transaction with the row locked, phase B
    talks to the push services with NO database lock held, phase C records what happened."""
    sender = sender or push.send
    go = None
    # ---- phase A: decide
    async with _S() as s:
        r = (await s.execute(select(NtOutbox).where(NtOutbox.id == nid).with_for_update())).scalars().first()
        if r is None or r.status != "sending":
            await s.commit()
            return "skip"
        user = await s.get(db.User, r.user_id)
        if user is None or (getattr(user, "status", "active") or "active") == "blocked":
            out = _cancel(r, "blocked")
        elif not await _truthy(enabled_fn(user.email)):
            out = _cancel(r, "switch_off")
        elif r.kind != "test" and (now - r.fire_at) > dt.timedelta(minutes=rules.LATE_GRACE_MIN):
            out = _cancel(r, "stale")                              # the server was down: a late nudge is worse than none
        else:
            p = await plsvc._prefs(s, r.user_id)
            snap = (await _snaps(s, [r.user_id])).get(r.user_id)
            ok, kind = rules.still_wanted(r.kind, snap, now) if snap else (False, "no_data")
            subs = [{"id": x.id, "endpoint": x.endpoint, "p256dh": x.p256dh, "auth": x.auth} for x in
                    (await s.execute(select(PlPushSub).where(PlPushSub.user_id == r.user_id))).scalars().all()]
            if not ok:
                out = _cancel(r, kind)
            elif not subs or not (p.push_on or r.kind == "test"):
                r.push_state = "no_subscription"
                out = _cancel(r, "no_device")
            else:
                day = rules.ist_date(now).isoformat()
                streak = rules.alive_streak(snap["streak_days"], snap["last_active"], rules.ist_date(now))
                r.kind = kind
                r.title, r.body = rules.render(kind, snap["lang"], snap["name"], streak, snap["hide"], r.user_id, day)
                r.meta = {"lang": snap["lang"], "streak": streak, "hidden": bool(snap["hide"])}
                go = (subs, r.title, r.body, r.url, r.attempts)
                out = "sending"
        await s.commit()
    if go is None:
        return out
    return await _send_and_record(nid, *go, now, sender)             # phases B + C, with no session (and no database lock) held


async def _send_and_record(nid: int, subs: list[dict], title: str, body: str, url: str, attempts: int, now: dt.datetime, sender) -> str:
    # ---- phase B: the network, no lock held
    payload = rules.build_payload(nid, title, body, rules.safe_url(url), tokens.make_ack(nid))
    results: list[tuple[int, str, int]] = []
    for sub in subs:
        kind, code = await sender(sub, payload)
        results.append((sub["id"], kind, code))
    # ---- phase C: record
    async with _S() as s:
        r = (await s.execute(select(NtOutbox).where(NtOutbox.id == nid).with_for_update())).scalars().first()
        if r is None or r.status != "sending":
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
        if okids:
            r.status, r.push_state, r.sent_at, r.claimed_at = "sent", "accepted", now, None
            await s.commit()
            return "sent"
        if all(k == "gone" for _i, k, _c in results):
            r.push_state = "no_subscription"
            _cancel(r, "no_device")
            await s.commit()
            return "cancelled"
        if attempts < MAX_ATTEMPTS:                                # every send failed for a reason that may pass: retry with a backoff
            r.status, r.fire_at, r.claimed_at = "scheduled", now + dt.timedelta(seconds=BACKOFF_SEC[min(attempts - 1, len(BACKOFF_SEC) - 1)]), None
            await s.commit()
            return "retry"
        r.push_state = "failed"
        _cancel(r, "push_failed")
        await s.commit()
        return "cancelled"


# ----------------------------------------------------------------------------- beacons from the phone
async def record_open(uid: str, nid: int) -> dict:
    """The learner tapped a notification (the app was opened with ?n=<id>). Idempotent; an id that is not theirs is silently a no-op (so ids
    cannot be probed)."""
    async with _S() as s:
        await s.execute(update(NtOutbox).where(NtOutbox.id == nid, NtOutbox.user_id == uid, NtOutbox.opened_at.is_(None))
                        .values(opened_at=_utc()).execution_options(synchronize_session=False))
        await s.commit()
    return {"ok": True}


async def record_ack(nid: int) -> dict:
    """The phone's service worker says the message arrived (token already verified by the caller)."""
    async with _S() as s:
        await s.execute(update(NtOutbox).where(NtOutbox.id == nid, NtOutbox.received_at.is_(None), NtOutbox.status == "sent")
                        .values(received_at=_utc()).execution_options(synchronize_session=False))
        await s.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- the test button
async def send_test(uid: str) -> dict:
    """'Send me a test notification': a row due in a few seconds, so the learner can watch the whole path on their own phone. One every
    TEST_GAP_MIN minutes. Needs at least one device."""
    now = _utc()
    async with _S() as s:
        devices = (await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid))).scalar() or 0
        if not devices:
            raise Invalid("no_device")
        recent = (await s.execute(select(func.count()).select_from(NtOutbox).where(
            NtOutbox.user_id == uid, NtOutbox.kind == "test", NtOutbox.created_at >= now - dt.timedelta(minutes=TEST_GAP_MIN)))).scalar() or 0
        if recent:
            raise LimitReached("test")
        fire = now + dt.timedelta(seconds=8)
        r = NtOutbox(user_id=uid, kind="test", dedupe_key=f"test:{now:%Y%m%dT%H%M%S%f}", fire_at=fire, url="/", status="scheduled", created_at=now)
        s.add(r)
        await s.commit()
        return {"ok": True, "id": r.id, "in_seconds": 8}


# ----------------------------------------------------------------------------- health, pruning, data rights
async def health() -> dict:
    async with _S() as s:
        day = _utc() - dt.timedelta(hours=24)

        async def count(*where) -> int:
            return int((await s.execute(select(func.count()).select_from(NtOutbox).where(*where))).scalar() or 0)

        out = {"created_24h": await count(NtOutbox.created_at >= day),
               "sent_24h": await count(NtOutbox.sent_at >= day), "accepted_24h": await count(NtOutbox.sent_at >= day, NtOutbox.push_state == "accepted"),
               "received_24h": await count(NtOutbox.sent_at >= day, NtOutbox.received_at.is_not(None)),
               "opened_24h": await count(NtOutbox.sent_at >= day, NtOutbox.opened_at.is_not(None)),
               "cancelled_24h": await count(NtOutbox.created_at >= day, NtOutbox.status == "cancelled"),
               "failed_24h": await count(NtOutbox.created_at >= day, NtOutbox.push_state == "failed"),
               "overdue": await count(NtOutbox.status == "scheduled", NtOutbox.fire_at < _utc() - dt.timedelta(minutes=5)),
               "stuck_sending": await count(NtOutbox.status == "sending", NtOutbox.claimed_at < _utc() - dt.timedelta(minutes=5))}
        out["push_devices"] = int((await s.execute(select(func.count()).select_from(PlPushSub))).scalar() or 0)
        out["learners_with_push"] = int((await s.execute(select(func.count(func.distinct(PlPushSub.user_id))))).scalar() or 0)
        await s.commit()
        return out


async def prune(now: dt.datetime) -> None:
    async with _S() as s:
        await s.execute(delete(NtOutbox).where(NtOutbox.created_at < now - dt.timedelta(days=KEEP_DAYS), NtOutbox.status.in_(("sent", "cancelled"))))
        await s.commit()


def _row_dict(r) -> dict:
    out = {}
    for c in r.__table__.columns:
        v = getattr(r, c.name)
        out[c.name] = v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v
    return out


async def export_all(uid: str) -> dict:
    """Every notification row the learner owns, as JSON (data rights). Device keys are not exported - they live with My Day's push settings."""
    async with _S() as s:
        out: dict[str, Any] = {"exported_at": _utc().isoformat()}
        for M in (NtPrefs, NtOutbox):
            out[M.__tablename__] = [_row_dict(r) for r in (await s.execute(select(M).where(M.user_id == uid))).scalars().all()]
        await s.commit()
        return out


async def delete_rows(s, uids: list) -> None:
    """Delete every notification row for these users, inside the caller's transaction (also used by delete_user / admin_wipe_users)."""
    for M in (NtOutbox, NtPrefs):
        await s.execute(delete(M).where(M.user_id.in_(uids)))


async def delete_all(uid: str) -> dict:
    async with _S() as s:
        await delete_rows(s, [uid])
        await s.commit()
    return {"ok": True}
