"""Keys - HTTP API (`/keys/status`, `/keys/save`, `/keys/remove`, `/keys/recheck`, `/keys/export`).

The gate is the other staged features' gate, in the same order: a valid session -> the `key_health` switch is on for THIS account (else 404, so the feature is
invisible while it is off; export is answered either way) -> the account is not blocked. Every call is scoped to the signed-in learner and nothing returns key
text: a key is shown masked (`gsk_••••9fA2`) and travels only learner -> server.

The older `/keys/verify` and `/keys/get` stay in main.py (old clients and the phone-side Groq Whisper key still use them).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Header, HTTPException
from sqlalchemy.exc import DBAPIError

from .. import auth, db
from . import classify, gate, ledger, service as svc

router = APIRouter(prefix="/keys")

_hits: dict[str, list[float]] = {}          # per-learner rate limits (in memory is enough for one process)


async def _gate(authorization: str | None, token: str = "", need_switch: bool = True) -> tuple[dict, str, str]:
    from .. import main as M                 # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled or (need_switch and not await M.key_health_enabled(email)):
        raise HTTPException(404, "Not available yet")
    uid = claims["sub"]
    try:
        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[keys] gate: {type(e).__name__}")
    return claims, uid, email


def _rate(uid: str, what: str, n: int, per: float) -> None:
    """At most `n` calls of `what` per `per` seconds per learner, else 429 {"error": "slow_down"}."""
    now = time.time()
    k = f"{what}:{uid}"
    hits = [t for t in _hits.get(k, []) if now - t < per]
    if len(hits) >= n:
        raise HTTPException(429, {"error": "slow_down"})
    hits.append(now)
    _hits[k] = hits
    if len(_hits) > 5000:
        for kk in [kk for kk, v in _hits.items() if not v or now - v[-1] > 300]:
            _hits.pop(kk, None)


def _provider(v) -> str:
    p = str(v or "").strip().lower()
    if p not in classify.PROVIDERS:
        raise HTTPException(422, {"error": "provider"})
    return p


@router.get("/status")
async def status(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    await ledger.flush(uid)                                  # the learner's own pending counts, so the screen is exact
    return await svc.status_payload(uid)


@router.post("/save")
async def save(body: dict = Body(...), authorization: str | None = Header(None)):
    claims, uid, _e = await _gate(authorization, str(body.get("token", "")))
    provider = _provider(body.get("provider"))
    key = gate.clean_key(provider, body.get("key"))
    if key is None:
        raise HTTPException(422, {"error": "key_shape"})
    _rate(uid, "save", 8, 60.0)
    try:
        await db.login(claims)                               # the user row must exist (the stored keys reference it) - same as the older /keys/verify
    except Exception as e:
        print(f"[keys] login: {type(e).__name__}")
    res = await svc.verify_and_save(uid, provider, key)
    from .. import main as M
    await M._ev_keys(uid)                                    # insights: first / second key saved (a milestone is written once)
    return res


@router.post("/remove")
async def remove(body: dict = Body(...), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    return await svc.remove_key(uid, _provider(body.get("provider")))


@router.post("/recheck")
async def recheck(body: dict = Body(default={}), authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, str(body.get("token", "")))
    provider = _provider(body["provider"]) if body.get("provider") else None
    _rate(uid, "recheck", 4, 60.0)
    return await svc.recheck(uid, provider, deep=bool(body.get("deep")) and provider is not None)


@router.get("/export")
async def export(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_switch=False)
    try:
        return await svc.export_all(uid)
    except DBAPIError:
        raise HTTPException(404, "Not found")
