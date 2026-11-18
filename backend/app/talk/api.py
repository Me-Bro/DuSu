"""Talk - HTTP API (`/tk/*`).  The chat itself is the `talk` mode of the WebSocket `/ws/interview`; this router serves the screen around it: today's topic, the other topics, and the
learner's chosen support level.

The gate is Grammar Lab's, in the same order: a valid session -> the `talk_v3` switch is on for THIS account (else 404, so the feature is invisible while it is off) -> the account is
not blocked (403).  There is NO model call anywhere here, so no key is resolved and nothing is charged.  Every service call is scoped to the signed-in learner.  Error bodies never
contain the learner's words.  The API prefix is `/tk` and the client route is `/talk`: they differ on purpose (an API prefix equal to a client route is shadowed by the SPA fallback).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Header, HTTPException, Request

from .. import auth, db
from . import service as svc

router = APIRouter(prefix="/tk")

MAX_BODY = 2_000
REQS_PER_MIN = 60
_hits: dict = defaultdict(deque)


async def _gate(authorization: str | None, token: str = "") -> tuple[dict, str, str]:
    from .. import main as M                          # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled:
        raise HTTPException(404, "Talk is not available yet")
    if not await M.talk_v3_enabled(email):
        raise HTTPException(404, "Talk is not available yet")
    uid = claims["sub"]
    try:
        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[talk] gate: {type(e).__name__}")
    return claims, uid, email


def _rate(uid: str) -> None:
    now = time.time()
    q = _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= REQS_PER_MIN:
        raise HTTPException(429, {"error": "slow_down"})
    q.append(now)
    if len(_hits) > 5000:                              # bounded: forget the learners who have been quiet for a minute
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60][:2500]:
            _hits.pop(k, None)


async def _json(request: Request) -> dict:
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        raise HTTPException(413, "too_large")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > MAX_BODY:
            raise HTTPException(413, "too_large")
    if not buf:
        return {}
    try:
        d = json.loads(bytes(buf).decode("utf-8", errors="replace"), parse_constant=lambda _c: None)
    except (ValueError, RecursionError):
        raise HTTPException(422, {"error": "bad_input"})
    return d if isinstance(d, dict) else {}


@router.get("/state")
async def talk_state(authorization: str | None = Header(None), token: str = ""):
    _, uid, _e = await _gate(authorization, token)
    _rate(uid)
    return await svc.state(uid)


@router.get("/topic/{tid}")
async def talk_topic(tid: str, authorization: str | None = Header(None), token: str = ""):
    _, uid, _e = await _gate(authorization, token)
    _rate(uid)
    try:
        return svc.topic(tid[:64])
    except svc.NotFound:
        raise HTTPException(404, "Not found")


@router.post("/prefs")
async def talk_prefs(request: Request, authorization: str | None = Header(None)):
    _, uid, _e = await _gate(authorization)
    _rate(uid)
    d = await _json(request)
    try:
        return await svc.save_support(uid, d.get("support"))
    except svc.Invalid as e:
        raise HTTPException(422, {"error": str(e.args[0]) if e.args else "invalid"})
