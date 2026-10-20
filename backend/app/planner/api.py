"""My Day - HTTP API (`/planner/*`, DUSU_GOALS_PLAN.md §8).

The gate is the Practice Room's, in the same order: a valid session -> the `planner` switch is on for THIS account (else 404, so the feature is
invisible while it is off) -> the account is not blocked. Every service call is scoped to the signed-in learner; an id that is not theirs is
a 404 (never 403, so ids cannot be probed). Bodies are plain JSON - the service validates and clamps everything, the client is never trusted
for status, ownership or dates.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Header, HTTPException, Request
from sqlalchemy.exc import DBAPIError

from .. import auth, db
from . import push, service as svc, timeutil as tu
from . import scheduler

router = APIRouter(prefix="/planner")

_hits: dict[str, list[float]] = {}          # /r/act rate limit: 60 / minute / IP (in memory is enough for one process)


async def _gate(authorization: str | None, token: str = "") -> tuple[dict, str, str]:
    from .. import main as M                 # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled or not await M.planner_enabled(email):
        raise HTTPException(404, "My Day is not available yet")
    uid = claims["sub"]
    try:
        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[planner] gate: {type(e).__name__}")
    return claims, uid, email


async def _run(coro):
    what = getattr(coro, "__qualname__", "") or "?"
    try:
        return await coro
    except svc.NotFound:
        raise HTTPException(404, "Not found")
    except svc.Invalid as e:
        code = str(e.args[0]) if e.args else "invalid"
        print(f"[planner] 422 {what}: {code}")           # which rule refused it (never the learner's words) - a refused add used to be invisible in the log
        raise HTTPException(422, {"error": code})
    except svc.LimitReached as e:
        code = str(e.args[0]) if e.args else ""
        print(f"[planner] 409 {what}: limit_{code}")
        raise HTTPException(409, {"error": "limit_" + code})
    except DBAPIError as e:
        # a number the database cannot even read (an id beyond a 32-bit integer, which the app itself never sends): it is nobody's, so it is not found - never a 500
        if type(getattr(getattr(e, "orig", None), "__cause__", None)).__name__ == "DataError":
            print(f"[planner] 404 {what}: unreadable number")
            raise HTTPException(404, "Not found")
        raise


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------- today / summary
@router.get("/today")
async def today(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.today(uid))


@router.get("/summary")
async def summary(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.summary(uid))


# ----------------------------------------------------------------------------- tasks
@router.get("/tasks")
async def tasks(view: str = "today", goal_id: int | None = None, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_tasks(uid, view, goal_id))


@router.post("/tasks")
async def task_create(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.create_task(uid, body))


@router.patch("/tasks/{tid}")
async def task_edit(tid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_task(uid, tid, body))


@router.post("/tasks/{tid}/complete")
async def task_complete(tid: int, body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.set_task_state(uid, tid, "complete"))


@router.post("/tasks/{tid}/reopen")
async def task_reopen(tid: int, body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.set_task_state(uid, tid, "reopen"))


@router.post("/tasks/{tid}/skip")
async def task_skip(tid: int, body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.set_task_state(uid, tid, "skip"))


@router.post("/tasks/{tid}/reschedule")
async def task_reschedule(tid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.reschedule_task(uid, tid, body))


@router.post("/tasks/{tid}/pin")
async def task_pin(tid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.pin_task(uid, tid, body.get("on") is not False))


@router.post("/tasks/{tid}/trigger")
async def task_trigger(tid: int, body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.trigger_task(uid, tid))


@router.delete("/tasks/{tid}")
async def task_delete(tid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.delete_task(uid, tid))


# ----------------------------------------------------------------------------- goals + milestones
@router.get("/goals")
async def goals(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_goals(uid))


@router.post("/goals")
async def goal_create(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.create_goal(uid, body))


@router.get("/goals/{gid}")
async def goal_get(gid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_goal(uid, gid))


@router.patch("/goals/{gid}")
async def goal_edit(gid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_goal(uid, gid, body))


@router.delete("/goals/{gid}")
async def goal_delete(gid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.delete_goal(uid, gid))


@router.post("/goals/{gid}/milestones")
async def milestone_add(gid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.add_milestone(uid, gid, body))


@router.patch("/milestones/{mid}")
async def milestone_edit(mid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_milestone(uid, mid, body))


# ----------------------------------------------------------------------------- habits
@router.get("/habits")
async def habits(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_habits(uid))


@router.post("/habits")
async def habit_create(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.create_habit(uid, body))


@router.patch("/habits/{hid}")
async def habit_edit(hid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_habit(uid, hid, body))


@router.delete("/habits/{hid}")
async def habit_delete(hid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.delete_habit(uid, hid))


@router.put("/habits/{hid}/log")
async def habit_log(hid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.log_habit(uid, hid, body))


# ----------------------------------------------------------------------------- reminders
@router.get("/due")
async def due(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.due_cards(uid))


@router.get("/reminders")
async def reminders(view: str = "upcoming", token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_reminders(uid, view if view in ("all", "history") else "upcoming"))


@router.post("/reminders")
async def reminder_create(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.create_custom_reminder(uid, body))


@router.patch("/reminders/{rid}")
async def reminder_update(rid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_custom_reminder(uid, rid, body))


@router.delete("/reminders/{rid}")
async def reminder_delete(rid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.delete_custom_reminder(uid, rid))


# Repeating reminders: set once, ring on the chosen weekdays until paused or deleted (the rings themselves are ordinary rows in /reminders)
@router.get("/reminder-rules")
async def reminder_rules(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_reminder_rules(uid))


@router.post("/reminder-rules")
async def reminder_rule_create(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.create_reminder_rule(uid, body))


@router.patch("/reminder-rules/{rid}")
async def reminder_rule_update(rid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.update_reminder_rule(uid, rid, body))


@router.delete("/reminder-rules/{rid}")
async def reminder_rule_delete(rid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.delete_reminder_rule(uid, rid))


@router.post("/reminders/{rid}/act")
async def reminder_act(rid: int, body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.act_reminder(uid, rid, str(body.get("action", "")), _int(body.get("minutes"), 0) or None))


@router.post("/r/act")
async def reminder_act_token(request: Request, body: dict = Body(...)):
    """The service worker's action buttons (Done / Later / Skip on the notification). It has no login, so the notification carries a signed,
    single-purpose, 24-hour token: it can do that one action on that one reminder and nothing else. Still 404 while the switch is off."""
    # behind the Cloudflare tunnel every request arrives from the proxy: the real address is in these headers
    ip = (request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 60]
    if len(hits) >= 60:
        raise HTTPException(429, "slow down")
    hits.append(now)
    _hits[ip] = hits
    if len(_hits) > 5000:                      # bound the table
        _hits.clear()
    got = push.read_token(body.get("t"))
    if not got:
        raise HTTPException(401, "Invalid or expired")
    rid, action = got
    owner = await svc.reminder_owner(rid)
    if not owner:
        raise HTTPException(404, "Not found")
    from .. import main as M
    u = None
    async with db._Session() as s:             # type: ignore[misc]
        u = await s.get(db.User, owner)
    if u is None or not db.db_enabled or not await M.planner_enabled(u.email or "") or (getattr(u, "status", "active") or "active") == "blocked":
        raise HTTPException(404, "Not found")
    return await _run(svc.act_reminder(owner, rid, action, None, by_token=True))


# ----------------------------------------------------------------------------- settings, push, data rights
@router.get("/prefs")
async def prefs_get(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_prefs(uid))


@router.put("/prefs")
async def prefs_put(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    await _run(svc.put_prefs(uid, body))
    return await _run(svc.get_prefs(uid))


@router.get("/push/key")
async def push_key(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    keys = await push.vapid_keys()
    return {"available": bool(keys), "key": keys[0] if keys else ""}


@router.post("/push/subscribe")
async def push_subscribe(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    sub = push.clean_subscription(body.get("subscription") if isinstance(body.get("subscription"), dict) else body)
    if sub is None:
        raise HTTPException(422, {"error": "subscription"})
    return await _run(svc.subscribe_push(uid, sub, str(body.get("ua", ""))))


@router.delete("/push/subscribe")
async def push_unsubscribe(body: dict = Body(default={}), token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token or str(body.get("token", "")))
    return await _run(svc.unsubscribe_push(uid, body.get("endpoint") if isinstance(body.get("endpoint"), str) else None))


@router.post("/push/test")
async def push_test(body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.test_reminder(uid))


@router.get("/export")
async def export(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.export_all(uid))


@router.post("/delete-all")
async def delete_all(body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    if body.get("confirm") is not True:
        raise HTTPException(422, {"error": "confirm"})
    return await _run(svc.delete_all(uid))
