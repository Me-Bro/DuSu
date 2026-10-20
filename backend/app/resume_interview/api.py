"""Job Interview Practice - HTTP API (`/rinterview/*`, DUSU_RESUME_INTERVIEW_PLAN.md §7).

The gate is My Day's, in the same order: a valid session -> the `resume_interview` switch is on for THIS account (else 404, so the feature is
invisible while it is off - EXCEPT export / delete, which must keep working so a learner's data is never trapped behind a switch) -> the account
is not blocked. An LLM endpoint then resolves the learner's keys (402 `keys_required`), and charges ONE request against the free quota right
before the first model call (a cached result or a too-short answer costs nothing). Every service call is scoped to the signed-in learner; an id
that is not theirs is a 404 (never 403). Error bodies never contain the learner's words.
"""

from __future__ import annotations

import json
import time
import urllib.parse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import auth, db
from ..config import settings
from ..providers import llm
from ..providers.openrouter_provider import set_active_keys
from . import docs, engine, rules, service as svc

router = APIRouter(prefix="/rinterview")

_hits: dict[str, list[float]] = {}                 # per-IP limiter for upload / transcribe (one process, so memory is enough)
_user_hits: dict[str, list[float]] = {}
_RATE_PER_MIN = 30
_parsing: set[str] = set()                         # learners with a file upload in flight: one at a time each (a parse is the most expensive request here)
_stt_day: dict[str, tuple[str, int]] = {}          # uid -> (IST day, transcriptions today): the answer rows cap SAVED answers; this one counts every request
_STT_PER_DAY = 2 * rules.ANSWERS_PER_DAY           # room for a re-record or a retry per answer


# ----------------------------------------------------------------------------- gate, body, limits
def _ip(request: Request) -> str:
    h = request.headers
    return (h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "") or "?")[:64]


def _rate(bucket: dict[str, list[float]], key: str) -> None:
    now = time.time()
    hits = [t for t in bucket.get(key, []) if now - t < 60]
    if len(hits) >= _RATE_PER_MIN:
        bucket[key] = hits
        raise HTTPException(429, "rate")
    hits.append(now)
    bucket[key] = hits
    if len(bucket) > 5000:                            # keep the dict small on a long-lived process
        for k in [k for k, v in bucket.items() if not v or now - v[-1] > 60][:2500]:
            bucket.pop(k, None)


async def _gate(authorization: str | None, token: str = "", need_enabled: bool = True) -> tuple[dict, str, str]:
    from .. import main as M                          # lazy: main.py imports this module at start-up
    claims = auth.read_session(M._bearer(authorization, token))
    if not claims:
        raise HTTPException(401, "Not signed in")
    email = claims.get("email", "")
    if not db.db_enabled:
        raise HTTPException(404, "Job Interview Practice is not available yet")
    if need_enabled and not await M.resume_interview_enabled(email):
        raise HTTPException(404, "Job Interview Practice is not available yet")
    uid = claims["sub"]
    if need_enabled:                                  # data rights (export / delete) stay open to a blocked account: blocking denies USE, never one's own data
        try:
            if (await db.get_user_flags(uid)).get("status") == "blocked":
                raise HTTPException(403, "Your access has been paused. Please contact the admin.")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[rinterview] gate: {type(e).__name__}")
    return claims, uid, email


async def _read_body(request: Request, limit: int) -> bytes:
    """The request body with a HARD limit: Content-Length first (cheap), then the stream is counted - uvicorn has no body cap of its own."""
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        raise HTTPException(413, "too_large")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, "too_large")
    return bytes(buf)


async def _json(request: Request) -> dict:
    raw = await _read_body(request, rules.MAX_JSON_BYTES)
    if not raw:
        return {}
    try:
        d = json.loads(raw.decode("utf-8", errors="replace"), parse_constant=lambda _c: None)    # NaN / Infinity -> null (JSONB rejects them)
    except (ValueError, RecursionError):               # 100 000 nested "[" raised RecursionError: a 500 for what is just bad input
        raise HTTPException(422, {"error": "bad_input"})
    return d if isinstance(d, dict) else {}


def _before_model(email: str, uid: str):
    async def hook() -> None:
        from .. import main as M
        snap = await M.charge_request(email, uid, M._quota_day())          # ONE request, however many model rungs it takes
        if not snap.get("allowed", True):
            raise svc.QuotaExceeded()
    return hook


async def _llm_gate(request: Request, authorization: str | None, token: str = "") -> tuple[dict, str, str, dict]:
    """Gate + body + the learner's keys for one LLM-backed endpoint -> (claims, uid, email, body)."""
    from .. import main as M
    claims, uid, email = await _gate(authorization, token)
    body = await _json(request)
    ok, eff, _r = await M.resolve_keys(email, body.get("keys") if isinstance(body.get("keys"), dict) else {}, uid)
    if not ok:
        raise HTTPException(402, "keys_required")
    set_active_keys(eff)                              # contextvar: must be set in THIS task before the model is awaited
    return claims, uid, email, body


_DOC_STATUS = {"unsupported_doc": (415, {"error": "unsupported_type", "hint": "doc"}), "unsupported_other": (415, {"error": "unsupported_type", "hint": "other"}),
               "extract_unavailable": (502, {"error": "extract_unavailable"}), "busy": (429, "rate")}


async def _run(coro, unavailable: str = "analysis_unavailable"):
    what = getattr(coro, "__qualname__", "") or "?"
    try:
        return await coro
    except svc.NotFound:
        raise HTTPException(404, "Not found")
    except svc.Invalid as e:
        code = str(e.args[0]) if e.args else "invalid"
        print(f"[rinterview] 422 {what}: {code}")
        raise HTTPException(422, {"error": code})
    except svc.LimitReached as e:
        code = str(e.args[0]) if e.args else ""
        if code == "daily":
            raise HTTPException(429, "daily_limit")
        print(f"[rinterview] 409 {what}: limit_{code}")
        raise HTTPException(409, {"error": "limit_" + code})
    except svc.Conflict as e:
        raise HTTPException(409, {"error": e.code, **e.extra})
    except svc.Pending:
        return JSONResponse({"pending": True}, status_code=202)
    except svc.QuotaExceeded:
        raise HTTPException(429, "quota")
    except svc.FeedbackFailed as e:
        if e.quota:
            raise HTTPException(429, "quota")
        raise HTTPException(502, {"error": "feedback_unavailable", "saved": True, "turn": e.turn})
    except engine.Unavailable as e:
        print(f"[rinterview] {what}: model unavailable ({type(e).__name__}, parse_failed={e.parse_failed})")
        if not e.parse_failed and svc.quotaish(e):
            raise HTTPException(429, "quota")
        raise HTTPException(502, {"error": unavailable})
    except docs.DocError as e:
        code = str(e.args[0]) if e.args else "bad_file"
        if code in _DOC_STATUS:
            st, detail = _DOC_STATUS[code]
            raise HTTPException(st, detail)
        raise HTTPException(422, {"error": code})


# ----------------------------------------------------------------------------- hub + documents
@router.get("/state")
async def state(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.state(uid))


def _doc_reply(doc: dict, ing: dict, dup: bool) -> dict:
    return {"document": doc, "preview": ing["text"][:12000], "redactions": ing["redactions"], "warnings": ing["warnings"], "duplicate": dup}


@router.post("/documents/upload")
async def upload(request: Request, kind: str = "", token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    if kind not in rules.DOC_KINDS:
        raise HTTPException(422, {"error": "bad_kind"})
    _rate(_hits, _ip(request))
    _rate(_user_hits, uid)
    if uid in _parsing:                               # one upload at a time per learner: a parse is the most expensive request in this feature
        raise HTTPException(429, "rate")
    _parsing.add(uid)
    try:
        data = await _read_body(request, rules.MAX_UPLOAD_BYTES)
        name = urllib.parse.unquote(request.headers.get("x-ri-name", ""))[:160]   # a display title typed / derived by the client; never a stored file name

        async def go():
            ing = await docs.ingest(data, kind)
            doc, dup = await svc.add_document(uid, kind, ing, title=name)
            return _doc_reply(doc, ing, dup)
        return await _run(go())
    finally:
        _parsing.discard(uid)


@router.post("/documents/paste")
async def paste(request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    _rate(_user_hits, uid)
    body = await _json(request)
    kind = body.get("kind")

    async def go():
        ing = docs.ingest_text(body.get("text"), kind)
        pid = body.get("parent_id") if isinstance(body.get("parent_id"), int) else None
        doc, dup = await svc.add_document(uid, kind, ing, title=body.get("title") or "", company=body.get("company") or "", parent_id=pid,
                                          client_key=body.get("client_key"))
        return _doc_reply(doc, ing, dup)
    return await _run(go())


@router.get("/documents/{did}")
async def document_get(did: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_document(uid, did))


@router.delete("/documents/{did}")
async def document_delete(did: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    return await _run(svc.delete_document(uid, did))


# ----------------------------------------------------------------------------- sessions
@router.post("/sessions")
async def session_create(request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    body = await _json(request)
    return await _run(svc.create_session(uid, body.get("resume_id"), body.get("jd_id"), body.get("settings"), body.get("client_key")))


@router.get("/sessions")
async def session_list(before: int | None = None, limit: int = 30, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.list_sessions(uid, before, limit))


@router.get("/sessions/{sid}")
async def session_get(sid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_state(uid, sid))


@router.delete("/sessions/{sid}")
async def session_delete(sid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    return await _run(svc.delete_session(uid, sid))


@router.post("/sessions/{sid}/analyze")
async def session_analyze(sid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, email, _b = await _llm_gate(request, authorization, token)
    return await _run(svc.analyze(uid, sid, llm, _before_model(email, uid)), "analysis_unavailable")


@router.post("/sessions/{sid}/swap-resume")
async def session_swap(sid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, email, body = await _llm_gate(request, authorization, token)
    rid = body.get("resume_id")
    if not isinstance(rid, int):
        raise HTTPException(422, {"error": "no_resume"})
    return await _run(svc.swap_resume(uid, sid, rid, llm, _before_model(email, uid)), "analysis_unavailable")


@router.patch("/sessions/{sid}/picks")
async def session_picks(sid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    body = await _json(request)

    async def go():
        return {"ok": True, "picked": await svc.set_picks(uid, sid, body.get("edit_ids"))}
    return await _run(go())


@router.post("/sessions/{sid}/start")
async def session_start(sid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, email, _b = await _llm_gate(request, authorization, token)
    return await _run(svc.start(uid, sid, llm, _before_model(email, uid)), "plan_unavailable")


@router.post("/sessions/{sid}/next")
async def session_next(sid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.next_question(uid, sid))


@router.post("/sessions/{sid}/finish")
async def session_finish(sid: int, token: str = "", authorization: str | None = Header(None)):
    claims, uid, _e = await _gate(authorization, token)

    async def go():
        res = await svc.finish(uid, sid)
        aw = await svc.award_for_finish(uid, claims, sid)
        return {"report": res["report"], "session": res["session"], "progress": aw["progress"], "mission": aw["mission"]}
    return await _run(go())


# ----------------------------------------------------------------------------- turns
@router.post("/sessions/{sid}/turns/{tid}/answer")
async def turn_answer(sid: int, tid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, email, body = await _llm_gate(request, authorization, token)
    return await _run(svc.answer(uid, sid, tid, body, llm, _before_model(email, uid)), "feedback_unavailable")


@router.post("/sessions/{sid}/turns/{tid}/feedback")
async def turn_feedback(sid: int, tid: int, request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, email, _b = await _llm_gate(request, authorization, token)
    return await _run(svc.retry_feedback(uid, sid, tid, llm, _before_model(email, uid)), "feedback_unavailable")


@router.post("/sessions/{sid}/turns/{tid}/skip")
async def turn_skip(sid: int, tid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.skip_turn(uid, sid, tid))


@router.get("/sessions/{sid}/turns/{tid}")
async def turn_get(sid: int, tid: int, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token)
    return await _run(svc.get_turn(uid, sid, tid))


# ----------------------------------------------------------------------------- speech-to-text for learners without a Groq key of their own
def _stt_count(uid: str) -> None:
    """Every proxied transcription counts against the learner's day (IST), whether it succeeds or not: the saved-answer rows alone would let a loop of
    requests that never saves an answer burn the server's speech-to-text keys."""
    day = db._ist_now().date().isoformat()
    d, n = _stt_day.get(uid, ("", 0))
    if d != day:
        n = 0
    if n >= _STT_PER_DAY:
        raise HTTPException(429, "daily_limit")
    _stt_day[uid] = (day, n + 1)
    if len(_stt_day) > 5000:
        for k in [k for k, v in _stt_day.items() if v[0] != day][:2500]:
            _stt_day.pop(k, None)


@router.post("/transcribe")
async def transcribe(request: Request, lang: str = "en", prompt: str = "", token: str = "", authorization: str | None = Header(None)):
    """Short answers only (<= ~3 minutes). The audio is held in memory for this request and never written anywhere. Groq (Whisper, word timestamps)
    when a Groq key exists, else - or when it is rejected / rate limited / down - Gemini (no word timestamps)."""
    from .. import main as M
    _c, uid, email = await _gate(authorization, token)
    ok, eff, _r = await M.resolve_keys(email, {}, uid)
    if not ok:
        raise HTTPException(402, "keys_required")
    gkey = (eff or {}).get("groq") if eff else settings.groq_api_key
    mkey = (eff or {}).get("gemini") if eff else settings.gemini_api_key
    if not gkey and not mkey:
        raise HTTPException(400, "no_groq_key")
    _rate(_hits, _ip(request))
    _rate(_user_hits, "stt:" + uid)
    async with svc._S() as s:                          # the day's cap comes from rows, so a restart cannot reset it
        n = (await svc._today_counts(s, uid))["answers"]
        await s.commit()
    if n >= rules.ANSWERS_PER_DAY:
        raise HTTPException(429, "daily_limit")
    _stt_count(uid)
    data = await _read_body(request, 8 * 1024 * 1024)
    if not data:
        raise HTTPException(400, "empty audio")
    mime = request.headers.get("content-type") or "audio/webm"
    if gkey:
        import httpx
        form = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "temperature": "0", "language": "en",
                "timestamp_granularities[]": ["word", "segment"]}
        seed = rules.clean_str(prompt, 200)
        if seed:
            form["prompt"] = seed
        status = None
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post("https://api.groq.com/openai/v1/audio/transcriptions", headers={"Authorization": f"Bearer {gkey}"},
                                 files={"file": ("answer.webm", data, mime)}, data=form)
            status = r.status_code
        except Exception as e:
            print(f"[rinterview] stt request failed: {type(e).__name__}")
        if status is not None and status < 400:
            out = r.json()
            out["engine"] = "groq"
            return JSONResponse(out)
        print(f"[rinterview] stt upstream {status}")
        if not mkey:
            if status == 429:
                raise HTTPException(429, "quota")
            raise HTTPException(502, {"error": "stt_failed"})
    out = await M._gemini_transcribe(data, mime, "en", mkey)
    return JSONResponse(out)


# ----------------------------------------------------------------------------- data rights (work with the switch OFF)
@router.get("/export")
async def export(token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    return JSONResponse(await _run(svc.export_all(uid)), headers={"Content-Disposition": 'attachment; filename="dusu-resume-interview.json"'})


@router.post("/delete-all")
async def delete_all(request: Request, token: str = "", authorization: str | None = Header(None)):
    _c, uid, _e = await _gate(authorization, token, need_enabled=False)
    body = await _json(request)
    if body.get("confirm") is not True:
        raise HTTPException(422, {"error": "confirm_required"})
    return await _run(svc.delete_all(uid))
