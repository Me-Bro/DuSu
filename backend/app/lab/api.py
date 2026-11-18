"""Grammar Lab - HTTP API (`/lab/*`).

The gate is Grammar Coach's, in the same order: a valid session -> the `grammar_lab` switch is on for THIS account (else 404, so the feature is invisible while it is off - EXCEPT export / delete,
which keep working so a learner's data is never trapped behind a switch) -> the account is not blocked.  There is NO model call anywhere in the Lab, so no key is resolved and nothing is charged.
Every service call is scoped to the signed-in learner; an id that is not theirs is a 404 (never 403).  Error bodies never contain the learner's words.
The API prefix is `/lab` and the client route is `/grammar-lab`: they differ on purpose (an API prefix equal to a client route is shadowed by the SPA fallback).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Header, HTTPException, Request

from .. import auth, db
from . import service as svc

router = APIRouter(prefix="/lab")

MAX_BODY = 20_000
CHECKS_PER_MIN = 90
_hits: dict = defaultdict(deque)


async def _gate(authorization: str | None, token: str = "", need_enabled: bool = True) -> tuple[dict, str, str]:
    from .. import main as M                          # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled:
        raise HTTPException(404, "Grammar Lab is not available yet")
    if need_enabled and not await M.grammar_lab_enabled(email):
        raise HTTPException(404, "Grammar Lab is not available yet")
    uid = claims["sub"]
    if need_enabled:                                  # data rights stay open to a blocked account: blocking denies USE, never one's own data
        try:
            if (await db.get_user_flags(uid)).get("status") == "blocked":
                raise HTTPException(403, "Your access has been paused. Please contact the admin.")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[lab] gate: {type(e).__name__}")
    return claims, uid, email


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


async def _run(coro):
    try:
        return await coro
    except svc.NotFound:
        raise HTTPException(404, "Not found")
    except svc.Invalid as e:
        code = str(e.args[0]) if e.args else "invalid"
        raise HTTPException(429 if code == "too_many" else 422, {"error": code})


def _rate(uid: str) -> None:
    now = time.time()
    q = _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= CHECKS_PER_MIN:
        raise HTTPException(429, {"error": "slow_down"})
    q.append(now)
    if len(_hits) > 5000:                              # bounded: forget the learners who have been quiet for a minute
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60][:2500]:
            _hits.pop(k, None)


def _int(v, name: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(422, {"error": name})
    if not 0 < n < 2_000_000_000:
        raise HTTPException(422, {"error": name})
    return n


@router.get("/state")
async def lab_state(authorization: str | None = Header(None), token: str = ""):
    _, uid, _e = await _gate(authorization, token)
    return await _run(svc.state(uid))


@router.post("/set")
async def lab_set(request: Request, authorization: str | None = Header(None)):
    _, uid, _e = await _gate(authorization)
    d = await _json(request)
    return await _run(svc.make_set(uid, str(d.get("unit", ""))[:32], str(d.get("level", ""))[:8]))


@router.get("/set/{sid}")
async def lab_get_set(sid: str, authorization: str | None = Header(None), token: str = ""):
    _, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_set(uid, _int(sid, "set")))


@router.post("/check")
async def lab_check(request: Request, authorization: str | None = Header(None)):
    _, uid, _e = await _gate(authorization)
    d = await _json(request)
    _rate(uid)
    return await _run(svc.check(uid, _int(d.get("set"), "set"), str(d.get("item", ""))[:16], d.get("said", "")))


@router.post("/show")
async def lab_show(request: Request, authorization: str | None = Header(None)):
    _, uid, _e = await _gate(authorization)
    d = await _json(request)
    _rate(uid)
    return await _run(svc.show(uid, _int(d.get("set"), "set"), str(d.get("item", ""))[:16]))


@router.get("/export")
async def lab_export(authorization: str | None = Header(None), token: str = ""):
    _, uid, _e = await _gate(authorization, token, need_enabled=False)
    return await _run(svc.export_all(uid))


@router.post("/delete-all")
async def lab_delete_all(request: Request, authorization: str | None = Header(None)):
    _, uid, _e = await _gate(authorization, need_enabled=False)
    d = await _json(request)
    if d.get("confirm") is not True:
        raise HTTPException(422, {"error": "confirm"})
    return await _run(svc.delete_all(uid))
