"""Grammar Coach - HTTP API (`/gcoach/*`, plan section 8).

The gate is My Day's / Job Interview Practice's, in the same order: a valid session -> the `grammar_coach` switch is on for THIS account (else 404,
so the feature is invisible while it is off - EXCEPT export / delete, which keep working so a learner's data is never trapped behind a switch) ->
the account is not blocked. An LLM endpoint then resolves the learner's keys (402 `keys_required`). Every service call is scoped to the signed-in
learner; an id that is not theirs is a 404 (never 403). Error bodies never contain the learner's words.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Header, HTTPException, Request

from .. import auth, db
from ..providers.openrouter_provider import set_active_keys
from . import catalog, service as svc, tracker

router = APIRouter(prefix="/gcoach")

MAX_BODY = 400_000
_KEY = re.compile(r"^(ws|pa|ri):[A-Za-z0-9_-]{1,40}$")


async def _gate(authorization: str | None, token: str = "", need_enabled: bool = True) -> tuple[dict, str, str]:
    from .. import main as M                          # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled:
        raise HTTPException(404, "Grammar Coach is not available yet")
    if need_enabled and not await M.grammar_coach_enabled(email):
        raise HTTPException(404, "Grammar Coach is not available yet")
    uid = claims["sub"]
    if need_enabled:                                  # data rights stay open to a blocked account: blocking denies USE, never one's own data
        try:
            if (await db.get_user_flags(uid)).get("status") == "blocked":
                raise HTTPException(403, "Your access has been paused. Please contact the admin.")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[gcoach] gate: {type(e).__name__}")
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
        raise HTTPException(422, {"error": str(e.args[0]) if e.args else "invalid"})


def _key(v: str) -> str:
    v = str(v or "").strip()
    if not _KEY.match(v):
        raise HTTPException(422, {"error": "ref"})
    return v


# ----------------------------------------------------------------------------- reads
@router.get("/state")
async def state(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.hub(uid)


@router.get("/sessions")
async def sessions(before: int = 0, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.list_sessions(uid, before or None)


@router.get("/sessions/{sid}")
async def session_one(sid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    if not (0 < sid < 2 ** 31):
        raise HTTPException(404, "Not found")
    return await _run(svc.report(uid, sid))


@router.get("/by-ref")
async def by_ref(ref: str = "", token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.by_ref(uid, _key(ref))


@router.get("/rules")
async def rules_list(token: str = "", authorization: str | None = Header(None)):
    await _gate(authorization, token)
    from . import catalog_data
    return {"rules": svc.rules_index(), "groups": list(catalog.GROUP_ORDER), "flow_tips": getattr(catalog_data, "FLOW_TIPS", {})}


@router.get("/rules/{rule_id}")
async def rule_one(rule_id: str, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.rule_detail(uid, rule_id))


@router.get("/notebook")
async def notebook(rule: str = "", session: int = 0, before: int = 0, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.list_notebook(uid, rule=rule[:64], session_id=session or None, before=before or None)


@router.get("/drills/next")
async def drills_next(rule: str = "", n: int = 5, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.drill_items(uid, rule[:64], max(1, min(10, n)))


@router.get("/prefs")
async def prefs_get(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await svc.get_prefs(uid)


# ----------------------------------------------------------------------------- writes
@router.post("/prefs")
async def prefs_set(request: Request, authorization: str | None = Header(None)):
    body = await _json(request)
    _c, uid, _e = await _gate(authorization, str(body.get("token") or ""))
    return await svc.set_prefs(uid, body)


@router.post("/keep")
async def keep(request: Request, authorization: str | None = Header(None)):
    body = await _json(request)
    _c, uid, _e = await _gate(authorization, str(body.get("token") or ""))
    from ..resume_interview import docs
    try:
        sid = int(body.get("id"))
    except (TypeError, ValueError):
        raise HTTPException(422, {"error": "id"})
    if not (0 < sid < 2 ** 31):
        raise HTTPException(404, "Not found")
    return await _run(svc.keep(uid, sid, str(body.get("choice") or ""), redact=docs.redact_light))


@router.post("/sentences/{sid}/contest")
async def sentence_contest(sid: int, request: Request, authorization: str | None = Header(None)):
    body = await _json(request)
    _c, uid, _e = await _gate(authorization, str(body.get("token") or ""))
    if not (0 < sid < 2 ** 31):
        raise HTTPException(404, "Not found")
    return await _run(svc.contest(uid, sid, str(body.get("kind") or "")))


@router.post("/drills/result")
async def drills_result(request: Request, authorization: str | None = Header(None)):
    body = await _json(request)
    _c, uid, _e = await _gate(authorization, str(body.get("token") or ""))
    return await _run(svc.record_drills(uid, str(body.get("key") or ""), body.get("results") or []))


@router.post("/analyze")
async def analyze(request: Request, authorization: str | None = Header(None)):
    """Recorded Practice (the on-phone transcript) and Job Interview Practice (its stored answers). Claims, starts the detached analysis and answers
    202 - the client polls `GET /by-ref`. Idempotent: a finished or running analysis for the same ref is returned, never repeated."""
    from .. import main as M
    body = await _json(request)
    claims, uid, email = await _gate(authorization, str(body.get("token") or ""))
    ok, eff, _r = await M.resolve_keys(email, body.get("keys") if isinstance(body.get("keys"), dict) else {}, uid)
    if not ok:
        raise HTTPException(402, "keys_required")
    set_active_keys(eff)                              # contextvar: set in THIS task BEFORE the detached task is created
    source, key = str(body.get("source") or ""), _key(body.get("ref"))
    if source == "practice" and key.startswith("pa:"):
        return await _analyze_practice(uid, email, key, body)
    if source == "job_interview" and key.startswith("ri:"):
        return await _analyze_ri(uid, email, key)
    raise HTTPException(422, {"error": "source"})


async def _analyze_practice(uid: str, email: str, key: str, body: dict) -> dict:
    from .. import practice
    from . import segment
    from .text import clean_input
    try:
        att = await db.get_practice_attempt(uid, int(key.split(":", 1)[1]))
    except (ValueError, OverflowError):
        att = None
    if not att:
        raise HTTPException(404, "Not found")
    if att.get("lang") != "en" or att.get("kind") not in practice.MONOLOGUE_KINDS:
        raise HTTPException(422, {"error": "not_english"})           # the server decides the language, never the client
    text = clean_input(body.get("transcript"), 30000)
    if len(text.split()) < 6:
        raise HTTPException(422, {"error": "too_short"})
    words = practice.clean_words(body.get("words"))
    hints = segment.align_hints(text, [list(w) for w in words], None) if words else None
    fb = att.get("feedback_lang") if att.get("feedback_lang") in ("en", "hinglish") else None
    cur = await svc.by_ref(uid, key)
    if cur["state"] in ("done", "partial", "pending"):
        return {"pending": cur["state"] == "pending", **cur}
    tracker.spawn(tracker.run(uid, email, source="practice", kind=str(att.get("kind") or "")[:32], key=key,
                              turns=[{"turn": 1, "text": text, "conf": None, "hints": hints}], engine_src="whisper" if words else "gemini",
                              duration_sec=int(att.get("actual_sec") or 0), fb=fb))
    return {"pending": True, "state": "pending"}


async def _analyze_ri(uid: str, email: str, key: str) -> dict:
    try:
        sid = int(key.split(":", 1)[1])
    except (ValueError, OverflowError):
        raise HTTPException(404, "Not found")
    from sqlalchemy import select
    from ..resume_interview.models import RiSession, RiTurn
    async with db._Session() as s:
        sess = await s.get(RiSession, sid)
        if sess is None or sess.user_id != uid:
            raise HTTPException(404, "Not found")
        rows = (await s.execute(select(RiTurn.idx, RiTurn.answer, RiTurn.engine).where(RiTurn.session_id == sid, RiTurn.user_id == uid, RiTurn.status == "answered")
                                .order_by(RiTurn.idx.nulls_last()))).all()
        fb = (sess.settings or {}).get("feedback_lang")
        await s.commit()
    turns = [{"turn": int(i if i is not None else n + 1), "text": str(a or ""), "conf": None} for n, (i, a, _e) in enumerate(rows) if a]
    if not turns:
        raise HTTPException(422, {"error": "too_short"})
    engines = {e for _i, _a, e in rows if e}
    eng = "gemini" if engines == {"gemini"} else "whisper"
    cur = await svc.by_ref(uid, key)
    if cur["state"] in ("done", "partial", "pending"):
        return {"pending": cur["state"] == "pending", **cur}
    tracker.spawn(tracker.run(uid, email, source="job_interview", kind="", key=key, turns=turns, engine_src=eng, fb=fb if fb in ("en", "hinglish") else None))
    return {"pending": True, "state": "pending"}


# ----------------------------------------------------------------------------- data rights (work with the switch off)
@router.get("/export")
async def export(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    return await svc.export_all(uid)


@router.post("/delete-all")
async def delete_all(request: Request, authorization: str | None = Header(None)):
    body = await _json(request)
    _c, uid, _e = await _gate(authorization, str(body.get("token") or ""), need_enabled=False)
    if body.get("confirm") is not True:
        raise HTTPException(422, {"error": "confirm"})
    await svc.delete_all(uid)
    await svc.set_prefs(uid, {})                      # prefs stay (they hold no learner text); the choice can be changed in Settings
    return {"ok": True}


@router.delete("/sessions/{sid}")
async def session_delete(sid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    if not (0 < sid < 2 ** 31):
        raise HTTPException(404, "Not found")
    return await _run(svc.delete_session(uid, sid))
