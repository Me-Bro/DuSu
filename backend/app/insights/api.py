"""Insights - HTTP API: `POST /ev` (a screen beacon), `POST /plans/interest`, `GET /plans/interest`. The owner's `GET /admin/funnel` lives in main.py with the
other admin routes.

Everything is scoped to the signed-in learner. `/ev` NEVER answers an error to the learner (a beacon must not break a screen): unknown names, a switched-off
feature, a missing database and a repeated beacon are all a quiet 204. The plan endpoints validate strictly (a plan outside the three is a 422).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Header, HTTPException, Response

from .. import auth, db
from . import service as svc

router = APIRouter()

_hits: dict[str, list[float]] = {}


def _rate(uid: str, what: str, n: int, per: float) -> bool:
    """True when the call is allowed: at most `n` per `per` seconds per learner (in memory is enough for one process)."""
    now = time.time()
    k = f"{what}:{uid}"
    hits = [t for t in _hits.get(k, []) if now - t < per]
    if len(hits) >= n:
        _hits[k] = hits
        return False
    hits.append(now)
    _hits[k] = hits
    if len(_hits) > 5000:
        for kk in [kk for kk, v in _hits.items() if not v or now - v[-1] > 300]:
            _hits.pop(kk, None)
    return True


def _who(authorization: str | None, token: str = "") -> tuple[dict, str]:
    from .. import main as M                 # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    return claims, claims["sub"]


@router.post("/ev")
async def ev(body: dict = Body(default={}), authorization: str | None = Header(None)):
    from .. import main as M
    _c, uid = _who(authorization, str(body.get("token", "")))
    name = str(body.get("name") or "")
    if db.db_enabled and name in svc.CLIENT_EVENTS and _rate(uid, "ev", 30, 60.0) and await M.insights_on():
        await svc.milestone(uid, name)
    return Response(status_code=204)


async def _plan_gate(authorization: str | None, token: str = "") -> tuple[dict, str]:
    claims, uid = _who(authorization, token)
    if not db.db_enabled:
        raise HTTPException(404, "Not available yet")
    try:
        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[insights] gate: {type(e).__name__}")
    return claims, uid


@router.post("/plans/interest")
async def plans_interest(body: dict = Body(...), authorization: str | None = Header(None)):
    from .. import main as M
    claims, uid = await _plan_gate(authorization, str(body.get("token", "")))
    plan = svc.clean_plan(body.get("plan"))
    feel = svc.clean_feel(body.get("price_feel"))
    if plan is None or feel is None:
        raise HTTPException(422, {"error": "plan" if plan is None else "price_feel"})
    if not _rate(uid, "plan", 12, 60.0):
        raise HTTPException(429, {"error": "slow_down"})
    try:
        await db.login(claims)               # the user row must exist (the reservation references it) - same as /keys/save
    except Exception as e:
        print(f"[insights] login: {type(e).__name__}")
    out = await svc.reserve_plan(uid, plan, feel)
    if await M.insights_on():
        await svc.milestone(uid, "plan_reserved")
    return {"ok": True, **out}


@router.get("/plans/interest")
async def my_interest(token: str = "", authorization: str | None = Header(None)):
    _c, uid = await _plan_gate(authorization, token)
    return {"reserved": await svc.my_plans(uid)}
