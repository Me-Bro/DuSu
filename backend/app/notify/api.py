"""Notifications - HTTP API (`/notify/*`).

The gate is My Day's, in the same order: a valid session -> the `notifications` switch is on for THIS account (else 404, so the feature is invisible
while it is off) -> the account is not blocked. Every call is scoped to the signed-in learner. The two beacons are the exception by design:
`/ack` carries a signed single-purpose token instead of a login (a service worker cannot read the app's session) and is rate-limited per IP.
Subscribing a phone is here too (`/push/*`) so this feature never depends on My Day's switch, but it writes the SAME device table (`pl_push_subs`) through
the same function My Day uses: one device list, one "notifications on" switch for a phone, whichever screen turned it on.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Header, HTTPException, Request
from sqlalchemy.exc import DBAPIError

from .. import auth, db
from ..planner import push, service as plsvc
from . import service as svc, tokens

router = APIRouter(prefix="/notify")

_hits: dict[str, list[float]] = {}          # /ack rate limit: 60 / minute / IP (in memory is enough for one process)


async def _gate(authorization: str | None, token: str = "", need_switch: bool = True) -> tuple[dict, str, str]:
    from .. import main as M                 # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled or (need_switch and not await M.notifications_enabled(email)):
        raise HTTPException(404, "Notifications are not available yet")
    uid = claims["sub"]
    try:
        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[notify] gate: {type(e).__name__}")
    return claims, uid, email


async def _run(coro):
    what = getattr(coro, "__qualname__", "") or "?"
    try:
        return await coro
    except svc.Invalid as e:
        code = str(e.args[0]) if e.args else "invalid"
        print(f"[notify] 422 {what}: {code}")
        raise HTTPException(422, {"error": code})
    except svc.LimitReached as e:
        code = str(e.args[0]) if e.args else ""
        print(f"[notify] 409 {what}: limit_{code}")
        raise HTTPException(409, {"error": "limit_" + code})
    except DBAPIError as e:
        if type(getattr(getattr(e, "orig", None), "__cause__", None)).__name__ == "DataError":   # a number the database cannot read (> 32-bit): nobody's
            raise HTTPException(404, "Not found")
        raise


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@router.get("/prefs")
async def get_prefs(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_prefs(uid))


@router.patch("/prefs")
async def patch_prefs(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.put_prefs(uid, {k: v for k, v in body.items() if k != "token"}))


# ----------------------------------------------------------------------------- this phone: subscribe / unsubscribe (the same device table My Day uses)
@router.get("/push/key")
async def push_key(token: str = "", authorization: str | None = Header(None)):
    await _gate(authorization, token)
    keys = await push.vapid_keys()
    return {"available": bool(keys), "key": keys[0] if keys else ""}


@router.post("/push/subscribe")
async def push_subscribe(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    sub = push.clean_subscription(body.get("subscription") if isinstance(body.get("subscription"), dict) else body)
    if sub is None:
        raise HTTPException(422, {"error": "subscription"})
    return await _run(plsvc.subscribe_push(uid, sub, str(body.get("ua", ""))))


@router.delete("/push/subscribe")
async def push_unsubscribe(body: dict = Body(default={}), token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token or str(body.get("token", "")))
    return await _run(plsvc.unsubscribe_push(uid, body.get("endpoint") if isinstance(body.get("endpoint"), str) else None))


@router.post("/open")
async def opened(body: dict = Body(...), authorization: str | None = Header(None)):
    """The learner tapped a notification. An id that is not theirs is a silent no-op, never an error (ids cannot be probed)."""
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.record_open(uid, _int(body.get("id"), -1)))


@router.post("/ack")
async def ack(request: Request, body: dict = Body(default={})):
    """The phone's service worker: 'this notification arrived'. No login - the signed single-purpose token is the proof."""
    ip = (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "") or "?")[:64]
    now = time.time()
    hits = [t for t in _hits.get(ip, []) if now - t < 60]
    if len(hits) >= 60:
        raise HTTPException(429, "Too many requests")
    hits.append(now)
    _hits[ip] = hits
    if len(_hits) > 5000:                                        # keep the map bounded
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60]:
            _hits.pop(k, None)
    nid = tokens.read_ack(body.get("t"))
    if nid is None:
        raise HTTPException(400, "Invalid token")
    if not db.db_enabled:
        raise HTTPException(404, "Not found")
    return await _run(svc.record_ack(nid))


@router.post("/test")
async def test(body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await _run(svc.send_test(uid))


# ----------------------------------------------------------------------------- data rights (answered while the switch is off too)
@router.get("/export")
async def export(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_switch=False)
    return await _run(svc.export_all(uid))


@router.post("/delete-all")
async def delete_all(body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")), need_switch=False)
    if body.get("confirm") is not True:
        raise HTTPException(422, {"error": "confirm"})
    return await _run(svc.delete_all(uid))
