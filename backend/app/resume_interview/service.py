"""Resume Interview - the service layer: every read / write of the `ri_*` tables (DUSU_RESUME_INTERVIEW_PLAN.md §7).

Rules this file keeps (each is tested on a scratch Postgres):
  * every query filters on `user_id`; an id that is not yours is "not found" (never "forbidden", so ids cannot be probed);
  * NO transaction or row lock is held across a model call (a pooled connection pinned for 10-50 s would starve every feature). The CLAIM PATTERN:
    lock -> validate -> mark `pending` + `claimed_at` -> commit; call the model; lock -> write only if the claim is still ours -> commit.
    A duplicate request (double tap, two devices, "retry" twice) finds `pending` and gets `Pending`; a claim older than CLAIM_TTL_S is stale;
  * create / answer / next / finish are IDEMPOTENT; XP is paid exactly once (compare-and-set on `awarded_at`);
  * resume / job / answer text and model output never reach a log line (class names only).
Functions open their own session and commit; they return plain dicts ready for JSON.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from .. import db, practice as P
from . import coach, docs, engine, rules
from .models import RI_TABLES, RiAnalysis, RiDocument, RiSession, RiTurn

UTC = dt.timezone.utc
Hook = Callable[[], Awaitable[None]]


class NotFound(Exception):
    pass


class Invalid(Exception):
    """A request the learner can fix. `args[0]` is a short code the client maps to its own words."""


class LimitReached(Exception):
    """args[0]: 'documents' | 'sessions' (a stored-data cap) or 'daily' (a per-day cap)."""


class Conflict(Exception):
    def __init__(self, code: str, **extra):
        super().__init__(code)
        self.code = code
        self.extra = extra


class Pending(Exception):
    """Another request already holds the claim for this work: poll."""


class QuotaExceeded(Exception):
    """Raised by the API's `before_model` hook when the learner's free quota is used up."""


class FeedbackFailed(Exception):
    """The transcript is saved but the model could not write feedback. `turn` is the stored turn; `quota` says why."""

    def __init__(self, turn: dict, quota: bool = False):
        super().__init__("feedback_failed")
        self.turn = turn
        self.quota = quota


def _S():
    return db._Session()          # type: ignore[misc]


def _ok_id(x) -> bool:
    """A usable row id: a real int inside Postgres' int4 range. Anything else (a string, a float, a bool, 99999999999) is 'not found' - handing it to the
    driver raised a DataError, i.e. an avoidable 500."""
    return isinstance(x, int) and not isinstance(x, bool) and 0 < x < 2 ** 31


def _utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def _iso(d) -> str | None:
    return d.isoformat() if d is not None else None


def _day_start() -> dt.datetime:
    """Midnight IST as an aware datetime: the day every cap in this app counts in (db._ist_day_start_utc)."""
    return db._ist_day_start_utc(db._ist_now().date())


def quotaish(e) -> bool:
    """Same test as main._is_quota (the service cannot import main): does this error mean 'the keys hit their limit'?"""
    s = str(e).lower()
    return any(k in s for k in ("429", "quota", "exhaust", "rate limit", "unavailable", "insufficient", "402"))


# ----------------------------------------------------------------------------- JSON builders
def doc_json(d) -> dict:
    return {"id": d.id, "kind": d.kind, "title": d.title, "company": d.company, "source": d.source, "chars": d.chars, "pages": d.pages,
            "parent_id": d.parent_id, "created_at": _iso(d.created_at)}


def turn_json(t: RiTurn, now: dt.datetime | None = None) -> dict:
    now = now or _utc()
    fs = t.feedback_state
    if fs == "pending" and not rules.claim_fresh(t.feedback_claimed_at, now):
        fs = "failed"                                       # a claim nobody finished (the server restarted mid-call): offer Retry
    return {"id": t.id, "idx": t.idx, "kind": t.kind, "source": t.source, "question": t.question, "why": t.why or "", "status": t.status,
            "answer": t.answer, "answer_sec": t.answer_sec, "answer_words": t.answer_words, "engine": t.engine, "audio_device": t.audio_device,
            "real": bool(t.real), "feedback_state": fs, "feedback": t.feedback, "asked_at": _iso(t.asked_at), "answered_at": _iso(t.answered_at)}


def session_json(s, answered: int = 0, real: int = 0) -> dict:
    return {"id": s.id, "title": s.title, "status": s.status, "settings": s.settings or {}, "resume_id": s.resume_id, "jd_id": s.jd_id,
            "overall": s.overall, "created_at": _iso(s.created_at), "started_at": _iso(s.started_at), "finished_at": _iso(s.finished_at),
            "answered": answered, "real": real}


def limits_json() -> dict:
    return {"max_upload_bytes": rules.MAX_UPLOAD_BYTES, "resume_min_chars": rules.RESUME_MIN_CHARS, "jd_min_chars": rules.JD_MIN_CHARS,
            "max_answer_sec": rules.MAX_ANSWER_SEC, "min_answer_words": rules.MIN_ANSWER_WORDS, "min_answer_sec": int(rules.MIN_ANSWER_SEC),
            "finish_min": rules.FINISH_MIN, "max_answers": rules.MAX_ANSWERS, "resumes": rules.MAX_RESUMES, "jds": rules.MAX_JDS}


def can_finish_of(counts: dict) -> dict:
    need = max(0, rules.FINISH_MIN - counts["real"])
    return {"ok": need == 0, "need": need, "reasons": ["need_real_answers"] if need else []}


async def _counts(s, sid: int) -> dict:
    rows = (await s.execute(select(RiTurn.status, RiTurn.real, func.count()).where(RiTurn.session_id == sid)
                            .group_by(RiTurn.status, RiTurn.real))).all()
    c = {"asked": 0, "answered": 0, "real": 0, "skipped": 0, "queued": 0}
    for st, rl, n in rows:
        if st == "queued":
            c["queued"] += n
            continue
        c["asked"] += n
        if st == "answered":
            c["answered"] += n
            c["real"] += n if rl else 0
        elif st == "skipped":
            c["skipped"] += n
    return c


# ----------------------------------------------------------------------------- ownership helpers
async def _own_session(s, uid: str, sid: int, lock: bool = False) -> RiSession:
    if not _ok_id(sid):
        raise NotFound()
    q = select(RiSession).where(RiSession.id == sid, RiSession.user_id == uid)
    if lock:
        q = q.with_for_update()
    r = (await s.execute(q)).scalars().first()
    if r is None:
        raise NotFound()
    return r


async def _own_doc(s, uid: str, did, kind: str | None = None) -> RiDocument | None:
    if not _ok_id(did):
        return None
    q = select(RiDocument).where(RiDocument.id == did, RiDocument.user_id == uid)
    if kind:
        q = q.where(RiDocument.kind == kind)
    return (await s.execute(q)).scalars().first()


async def _own_turn(s, uid: str, sid: int, tid: int, lock: bool = False) -> RiTurn:
    if not (_ok_id(sid) and _ok_id(tid)):
        raise NotFound()
    q = select(RiTurn).where(RiTurn.id == tid, RiTurn.session_id == sid, RiTurn.user_id == uid)
    if lock:
        q = q.with_for_update()
    r = (await s.execute(q)).scalars().first()
    if r is None:
        raise NotFound()
    return r


# ----------------------------------------------------------------------------- documents
def _default_title(kind: str, text: str) -> str:
    if kind == "jd":
        first = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
        if 4 < len(first) <= 80 and len(first.split()) <= 12 and not first.endswith((".", ":")):
            return rules.clean_str(first, 80)
    when = db._ist_now().strftime("%d %b")
    return ("Resume - " if kind == "resume" else "Job description - ") + when


async def add_document(uid: str, kind: str, ing: dict, *, title: str = "", company: str = "", parent_id: int | None = None,
                       client_key: str | None = None) -> tuple[dict, bool]:
    """Store one confirmed document (already extracted + redacted). -> (DOC, duplicate). Identical text returns the existing row; a repeated
    `client_key` returns the first one; the per-learner caps raise LimitReached('documents')."""
    text = ing["text"]
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ck = rules.clean_str(client_key, 64) or None
    async with _S() as s:
        if ck:
            ex = (await s.execute(select(RiDocument).where(RiDocument.user_id == uid, RiDocument.client_key == ck))).scalars().first()
            if ex is not None:
                return doc_json(ex), True
        ex = (await s.execute(select(RiDocument).where(RiDocument.user_id == uid, RiDocument.kind == kind, RiDocument.text_sha == sha))).scalars().first()
        if ex is not None:
            return doc_json(ex), True
        n = (await s.execute(select(func.count()).select_from(RiDocument).where(RiDocument.user_id == uid, RiDocument.kind == kind))).scalar() or 0
        if n >= (rules.MAX_RESUMES if kind == "resume" else rules.MAX_JDS):
            raise LimitReached("documents")
        if parent_id is not None and await _own_doc(s, uid, parent_id, kind) is None:
            parent_id = None
        doc = RiDocument(user_id=uid, kind=kind, title=rules.clean_str(title, 160) or _default_title(kind, text), company=rules.clean_str(company, 120),
                         source=ing.get("source", "paste"), chars=len(text), pages=int(ing.get("pages") or 0), text=text, text_sha=sha,
                         redactions=rules.safe_json(ing.get("redactions") or {}), meta={}, parent_id=parent_id, client_key=ck)
        s.add(doc)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            ex = (await s.execute(select(RiDocument).where(RiDocument.user_id == uid, RiDocument.kind == kind, RiDocument.text_sha == sha))).scalars().first()
            if ex is None:
                raise
            return doc_json(ex), True
        return doc_json(doc), False


async def get_document(uid: str, did: int) -> dict:
    async with _S() as s:
        d = await _own_doc(s, uid, did)
        if d is None:
            raise NotFound()
        meta = d.meta or {}
        return {"document": doc_json(d), "text": d.text, "redactions": d.redactions or {}, "role": meta.get("role"),
                "requirements": [{"id": r["id"], "text": r["text"], "type": r["type"]} for r in meta.get("requirements", [])] or None}


async def delete_document(uid: str, did: int) -> dict:
    """Delete one document: its analyses go with it and the sessions that used it are detached (they keep their brief and report, which are
    derived data and stay until that interview is deleted)."""
    async with _S() as s:
        d = await _own_doc(s, uid, did)
        if d is None:
            raise NotFound()
        an_ids = (await s.execute(select(RiAnalysis.id).where(RiAnalysis.user_id == uid, (RiAnalysis.resume_id == did) | (RiAnalysis.jd_id == did)))).scalars().all()
        if an_ids:
            await s.execute(update(RiSession).where(RiSession.user_id == uid, RiSession.analysis_id.in_(an_ids)).values(analysis_id=None))
            await s.execute(delete(RiAnalysis).where(RiAnalysis.id.in_(an_ids)))
        await s.execute(update(RiSession).where(RiSession.user_id == uid, RiSession.resume_id == did).values(resume_id=None))
        await s.execute(update(RiSession).where(RiSession.user_id == uid, RiSession.jd_id == did).values(jd_id=None))
        await s.execute(update(RiDocument).where(RiDocument.user_id == uid, RiDocument.parent_id == did).values(parent_id=None))
        await s.delete(d)
        await s.commit()
    return {"ok": True}


async def _store_jd_meta(uid: str, jd_id: int, role: dict, reqs: list[dict]) -> None:
    """The job's requirements are extracted ONCE and kept with the JD: every later analysis of any resume against it reuses them (stable ids)."""
    async with _S() as s:
        d = await _own_doc(s, uid, jd_id, "jd")
        if d is None:
            return
        d.meta = rules.safe_json({**(d.meta or {}), "role": role, "requirements": reqs, "rules_version": rules.RULES_VERSION})
        if role.get("title") and d.title.startswith("Job description"):
            d.title = role["title"][:160]
        if role.get("company") and not d.company:
            d.company = role["company"][:120]
        await s.commit()


# ----------------------------------------------------------------------------- the hub + sessions
async def _today_counts(s, uid: str) -> dict:
    ds = _day_start()
    n_s = (await s.execute(select(func.count()).select_from(RiSession).where(RiSession.user_id == uid, RiSession.created_at >= ds))).scalar() or 0
    n_a = (await s.execute(select(func.count()).select_from(RiTurn).where(RiTurn.user_id == uid, RiTurn.status == "answered", RiTurn.answered_at >= ds))).scalar() or 0
    return {"sessions": int(n_s), "answers": int(n_a), "sessions_cap": rules.SESSIONS_PER_DAY, "answers_cap": rules.ANSWERS_PER_DAY}


_SESSION_COLS = (RiSession.id, RiSession.title, RiSession.status, RiSession.settings, RiSession.resume_id, RiSession.jd_id, RiSession.overall,
                 RiSession.created_at, RiSession.started_at, RiSession.finished_at)


async def _session_rows(s, uid: str, before: int | None, limit: int) -> list[dict]:
    q = select(*_SESSION_COLS).where(RiSession.user_id == uid)
    if _ok_id(before):
        q = q.where(RiSession.id < before)
    rows = (await s.execute(q.order_by(RiSession.id.desc()).limit(limit))).all()
    if not rows:
        return []
    ids = [r.id for r in rows]
    cnt = {i: [0, 0] for i in ids}
    for sid, st, rl, n in (await s.execute(select(RiTurn.session_id, RiTurn.status, RiTurn.real, func.count())
                                           .where(RiTurn.session_id.in_(ids), RiTurn.status == "answered")
                                           .group_by(RiTurn.session_id, RiTurn.status, RiTurn.real))).all():
        cnt[sid][0] += n
        cnt[sid][1] += n if rl else 0
    return [session_json(r, *cnt[r.id]) for r in rows]


async def _active_row(s, uid: str) -> dict | None:
    """The newest UNFINISHED interview - asked for on its own, so an old one is still found when 30 newer ones fill the first page of the list."""
    r = (await s.execute(select(*_SESSION_COLS).where(RiSession.user_id == uid, RiSession.status != "finished").order_by(RiSession.id.desc()).limit(1))).first()
    if r is None:
        return None
    n_a, n_r = 0, 0
    for rl, n in (await s.execute(select(RiTurn.real, func.count()).where(RiTurn.session_id == r.id, RiTurn.status == "answered").group_by(RiTurn.real))).all():
        n_a += n
        n_r += n if rl else 0
    return session_json(r, n_a, n_r)


async def state(uid: str) -> dict:
    async with _S() as s:
        docs_ = (await s.execute(select(RiDocument.id, RiDocument.kind, RiDocument.title, RiDocument.company, RiDocument.source, RiDocument.chars,
                                        RiDocument.pages, RiDocument.parent_id, RiDocument.created_at)
                                 .where(RiDocument.user_id == uid).order_by(RiDocument.id.desc()))).all()
        sessions = await _session_rows(s, uid, None, 31)          # one more than a page: that is how "is there an older page?" is known
        today = await _today_counts(s, uid)
        active = await _active_row(s, uid)
        focus = await _focus_prev(s, uid)
        await s.commit()
    has_more = len(sessions) > 30
    return {"limits": limits_json(), "today": today, "resumes": [doc_json(d) for d in docs_ if d.kind == "resume"],
            "jds": [doc_json(d) for d in docs_ if d.kind == "jd"], "sessions": sessions[:30], "has_more": has_more, "active": active, "focus": focus}


async def list_sessions(uid: str, before: int | None = None, limit: int = 30) -> dict:
    limit = rules.clamp_int(limit, 1, 50, 30)
    async with _S() as s:
        rows = await _session_rows(s, uid, before, limit)
        await s.commit()
    return {"sessions": rows, "next_before": rows[-1]["id"] if len(rows) == limit else None}


async def create_session(uid: str, resume_id, jd_id, settings: dict | None, client_key: str | None) -> dict:
    ck = rules.clean_str(client_key, 64) or None
    async with _S() as s:
        if ck:
            ex = (await s.execute(select(RiSession).where(RiSession.user_id == uid, RiSession.client_key == ck))).scalars().first()
            if ex is not None:
                return {"session": session_json(ex)}
        resume = await _own_doc(s, uid, resume_id, "resume")
        jd = await _own_doc(s, uid, jd_id, "jd")
        if resume is None:
            raise Invalid("no_resume")
        if jd is None:
            raise Invalid("no_jd")
        total = (await s.execute(select(func.count()).select_from(RiSession).where(RiSession.user_id == uid))).scalar() or 0
        if total >= rules.MAX_SESSIONS:
            raise LimitReached("sessions")
        if (await _today_counts(s, uid))["sessions"] >= rules.SESSIONS_PER_DAY:
            raise LimitReached("daily")
        role = (jd.meta or {}).get("role") or {}
        sess = RiSession(user_id=uid, resume_id=resume.id, jd_id=jd.id, status="draft", plan_state="none",
                         title=rules.session_title(role.get("title") or jd.title, role.get("company") or jd.company),
                         settings=rules.clean_settings(settings), brief={}, rev=0, client_key=ck)
        s.add(sess)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            ex = (await s.execute(select(RiSession).where(RiSession.user_id == uid, RiSession.client_key == ck))).scalars().first()
            if ex is None:
                raise
            return {"session": session_json(ex)}
        return {"session": session_json(sess)}


def _analysis_payload(an: RiAnalysis | None, now: dt.datetime | None = None) -> dict | None:
    if an is None:
        return None
    now = now or _utc()
    res = an.result or {}
    picked = set(an.picked or [])
    state_ = an.state
    if state_ == "pending" and not rules.claim_fresh(an.claimed_at, now):
        state_ = "failed"
    edits = [{**e, "picked": e.get("id") in picked or bool(e.get("addressed")), "addressed": bool(e.get("addressed"))} for e in res.get("edits", [])]
    return {"state": state_, "match_score": an.match_score, "band": an.band, "verdict": res.get("verdict", ""),
            "role": res.get("role") or {"title": "", "company": "", "level": ""}, "requirements": res.get("requirements", []), "edits": edits,
            "strengths": res.get("strengths", []), "notes": res.get("notes", []), "low_match": an.band == "weak",
            "rules_version": an.rules_version, "prev": res.get("prev")}


async def get_state(uid: str, sid: int) -> dict:
    """Everything a (second) device needs to continue this interview at the exact open question."""
    async with _S() as s:
        sess = await _own_session(s, uid, sid)
        now = _utc()
        an = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
        if an is not None and an.user_id != uid:
            an = None
        turns = (await s.execute(select(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid, RiTurn.status != "queued")
                                 .order_by(RiTurn.idx))).scalars().all()
        counts = await _counts(s, sid)
        open_t = next((t for t in turns if t.status == "asked"), None)
        report = await _ensure_v2(s, uid, sess) if sess.status == "finished" else sess.report
        out = {"session": session_json(sess, counts["answered"], counts["real"]), "rev": sess.rev, "analysis": _analysis_payload(an, now),
               "turns": [turn_json(t, now) for t in turns if t.status != "dropped"], "queued_count": counts["queued"],
               "open_turn_id": open_t.id if open_t else None, "counts": counts, "can_finish": can_finish_of(counts), "report": report,
               "server_now": _iso(now)}
        if sess.status != "finished":                                   # an interview in progress carries the points from the PREVIOUS one: shown before the first question and checked per answer
            out["focus_prev"] = await _focus_prev(s, uid, exclude_id=sid)
        await s.commit()
        return out


async def delete_session(uid: str, sid: int) -> dict:
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        await s.execute(delete(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid))
        await s.delete(sess)
        await s.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- analysis (calls A + B)
async def _mark_analysis_failed(an_id: int, stamp: dt.datetime) -> None:
    try:
        async with _S() as s:
            await s.execute(update(RiAnalysis).where(RiAnalysis.id == an_id, RiAnalysis.state == "pending", RiAnalysis.claimed_at == stamp).values(state="failed"))
            await s.commit()
    except Exception as e:
        print(f"[rinterview] mark failed: {type(e).__name__}")


async def _compute_analysis(uid: str, llm, before_model: Hook, c: dict, prev: dict | None) -> dict:
    """Steps 2-3 of the claim pattern for an analysis: run the model with NO transaction open, then write if the claim is still ours."""
    import time
    t0 = time.monotonic()
    try:
        await before_model()
        meta = c["jd_meta"]
        if meta.get("rules_version") == rules.RULES_VERSION and meta.get("requirements"):
            role, reqs = meta.get("role") or {}, meta["requirements"]
        else:
            role, reqs = await engine.extract_requirements(llm, c["jd_text"])
            await _store_jd_meta(uid, c["jd_id"], role, reqs)
        m = await engine.analyze_match(llm, c["resume_text"], reqs)
    except Exception as e:
        await _mark_analysis_failed(c["an_id"], c["stamp"])
        print(f"[rinterview] analyze {int((time.monotonic() - t0) * 1000)}ms {type(e).__name__}")
        raise
    final = m["requirements"]
    score = rules.match_score(final)
    band = rules.band_match(score)
    notes = list(m["notes"])
    if (c.get("redactions") or {}).get("personal_block"):         # the model never sees these lines (they were removed on the way in), so this tip is computed
        notes.append({"issue": "A personal details section", "fix": "Date of birth, marital status and address are not needed on most resumes - consider removing them."})
    result: dict[str, Any] = {"role": role, "requirements": final, "edits": m["edits"], "strengths": m["strengths"], "notes": notes[:3],
                              "verdict": rules.verdict(band)}
    if prev:
        done = rules.addressed_edits(prev["edits"], prev["requirements"], final, c["resume_text"])
        carried = [{**e, "id": "p" + e["id"], "addressed": True} for e in prev["edits"] if e["id"] in done]
        result["edits"] = (carried + result["edits"])[:rules.MAX_EDITS + 3]
        result["prev"] = {"match_score": prev["score"], "band": prev["band"], "changed": rules.diff_requirements(prev["requirements"], final),
                          "addressed_edits": [e["id"] for e in carried]}
    async with _S() as s:
        sess = await _own_session(s, uid, c["sid"], lock=True)       # session first, then the analysis: the same lock order as every other path (no deadlock)
        an = (await s.execute(select(RiAnalysis).where(RiAnalysis.id == c["an_id"], RiAnalysis.user_id == uid).with_for_update())).scalars().first()
        if an is None or an.state != "pending" or an.claimed_at != c["stamp"]:
            payload = _analysis_payload(an)                      # someone else finished it (a stale claim was re-taken)
            await s.commit()
            return {"analysis": payload, "session": session_json(sess)}
        an.result = rules.safe_json(result)
        an.match_score, an.band, an.state, an.updated_at = score, band, "done", _utc()
        an.picked = [e["id"] for e in result["edits"] if e.get("addressed")]
        if sess.status in ("draft", "matched"):
            sess.analysis_id = an.id
            sess.status = "matched"
            if role.get("title"):                                    # now we know the real job: "Data Analyst - Acme Corp", not "Job description - 15 Oct"
                sess.title = rules.session_title(role["title"], role.get("company", ""))
            if c.get("set_resume_id"):
                sess.resume_id = c["set_resume_id"]
            sess.rev += 1
            sess.last_activity_at = _utc()
        out = {"analysis": _analysis_payload(an), "session": session_json(sess)}
        await s.commit()
    print(f"[rinterview] analyze {int((time.monotonic() - t0) * 1000)}ms ok")
    return out


async def _claim_analysis(s, uid: str, resume: RiDocument, jd: RiDocument, now: dt.datetime, prev_id: int | None):
    """-> ('cached', an) when a current analysis exists, else ('claimed', an). Raises Pending / LimitReached."""
    q = select(RiAnalysis).where(RiAnalysis.user_id == uid, RiAnalysis.resume_id == resume.id, RiAnalysis.jd_id == jd.id).with_for_update()
    an = (await s.execute(q)).scalars().first()
    if an is not None and an.state == "done" and an.rules_version == rules.RULES_VERSION:
        return "cached", an
    if an is not None and an.state == "pending" and rules.claim_fresh(an.claimed_at, now):
        raise Pending()
    if an is None:
        ds = _day_start()
        n = (await s.execute(select(func.count()).select_from(RiAnalysis).where(RiAnalysis.user_id == uid, RiAnalysis.created_at >= ds))).scalar() or 0
        if n >= rules.ANALYSES_PER_DAY:
            raise LimitReached("daily")
        an = RiAnalysis(user_id=uid, resume_id=resume.id, jd_id=jd.id, prev_id=prev_id, state="pending", claimed_at=now, rules_version=rules.RULES_VERSION,
                        picked=[], result={})
        try:
            async with s.begin_nested():             # a savepoint: two sessions with the same resume and job analysed at the same moment race on the unique pair
                s.add(an)
                await s.flush()
        except IntegrityError:
            an = (await s.execute(q)).scalars().first()       # the other request got there first: it holds the claim (or has finished)
            if an is None:
                raise
            if an.state == "done" and an.rules_version == rules.RULES_VERSION:
                return "cached", an
            raise Pending()
    else:
        an.state, an.claimed_at, an.rules_version = "pending", now, rules.RULES_VERSION
        if prev_id is not None:
            an.prev_id = prev_id
    return "claimed", an


async def analyze(uid: str, sid: int, llm, before_model: Hook) -> dict:
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status in ("active", "finished"):
            an = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
            if an is None or an.user_id != uid:
                raise Conflict("wrong_state")
            out = {"analysis": _analysis_payload(an, now), "session": session_json(sess)}
            await s.commit()
            return out
        resume = await _own_doc(s, uid, sess.resume_id, "resume")
        jd = await _own_doc(s, uid, sess.jd_id, "jd")
        if resume is None:
            raise Invalid("no_resume")
        if jd is None:
            raise Invalid("no_jd")
        how, an = await _claim_analysis(s, uid, resume, jd, now, None)
        if how == "cached":
            sess.analysis_id = an.id
            if sess.status == "draft":
                sess.status = "matched"
            sess.rev += 1
            sess.last_activity_at = now
            out = {"analysis": _analysis_payload(an, now), "session": session_json(sess)}
            await s.commit()
            return out
        ctx = {"an_id": an.id, "stamp": now, "resume_text": resume.text, "jd_text": jd.text, "jd_id": jd.id, "jd_meta": dict(jd.meta or {}), "sid": sid,
               "redactions": dict(resume.redactions or {})}
        sess.last_activity_at = now
        await s.commit()
    return await _compute_analysis(uid, llm, before_model, ctx, None)


async def swap_resume(uid: str, sid: int, new_resume_id: int, llm, before_model: Hook) -> dict:
    """The learner re-uploaded an improved resume: attach the new version and re-check ONLY that (the job's requirements are already stored)."""
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status not in ("draft", "matched"):
            raise Conflict("wrong_state")
        new = await _own_doc(s, uid, new_resume_id, "resume")
        if new is None:
            raise NotFound()
        jd = await _own_doc(s, uid, sess.jd_id, "jd")
        if jd is None:
            raise Invalid("no_jd")
        old = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
        if old is not None and old.user_id != uid:
            old = None
        prev = None
        if old is not None and old.state == "done":
            r = old.result or {}
            prev = {"score": old.match_score, "band": old.band, "requirements": r.get("requirements", []), "edits": r.get("edits", [])}
        how, an = await _claim_analysis(s, uid, new, jd, now, old.id if old else None)
        if how == "cached":
            sess.resume_id, sess.analysis_id, sess.status = new.id, an.id, "matched"
            sess.rev += 1
            sess.last_activity_at = now
            out = {"analysis": _analysis_payload(an, now), "session": session_json(sess)}
            await s.commit()
            return out
        ctx = {"an_id": an.id, "stamp": now, "resume_text": new.text, "jd_text": jd.text, "jd_id": jd.id, "jd_meta": dict(jd.meta or {}), "sid": sid,
               "set_resume_id": new.id, "redactions": dict(new.redactions or {})}
        sess.last_activity_at = now
        await s.commit()
    return await _compute_analysis(uid, llm, before_model, ctx, prev)


async def set_picks(uid: str, sid: int, edit_ids) -> list[str]:
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        an = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
        if an is None or an.user_id != uid:
            raise Conflict("wrong_state")
        valid = {e.get("id") for e in (an.result or {}).get("edits", [])}
        ids = edit_ids if isinstance(edit_ids, list) else []
        an.picked = [i for i in dict.fromkeys(str(x) for x in ids) if i in valid][:20]
        an.updated_at = _utc()
        out = list(an.picked)
        await s.commit()
        return out


# ----------------------------------------------------------------------------- the plan (call C) and the turns
def _bank_ctx(brief: dict) -> dict:
    role = (brief.get("role") or {})
    return rules.bank_ctx(role.get("title", ""), role.get("company", ""), brief.get("skills") or [])


def _fallback_brief(analysis: dict, role: dict, settings: dict) -> dict:
    gaps = [r["text"] for r in analysis.get("requirements", []) if r.get("status") == "missing"][:4]
    return {"summary": "", "level": settings.get("level", "experienced"), "strengths": (analysis.get("strengths") or [])[:4], "gaps": gaps,
            "projects": [], "skills": []}


def _merge_skills(brief: dict, requirements: list[dict], reqs_meta: list[dict]) -> list[str]:
    kws = {r["id"]: r.get("keywords") or [] for r in reqs_meta}
    out = list(brief.get("skills") or [])
    for r in requirements:
        if r.get("status") in ("met", "partial"):
            out.extend(kws.get(r["id"], []))
    seen, res = set(), []
    for k in out:
        if k and k.casefold() not in seen:
            seen.add(k.casefold())
            res.append(k)
    return res[:12]


async def _asked_before(s, uid: str, jd_id, exclude_sid: int) -> list[str]:
    if jd_id is None:
        return []
    ids = (await s.execute(select(RiSession.id).where(RiSession.user_id == uid, RiSession.jd_id == jd_id, RiSession.id != exclude_sid)
                           .order_by(RiSession.id.desc()).limit(3))).scalars().all()
    if not ids:
        return []
    qs = (await s.execute(select(RiTurn.question).where(RiTurn.user_id == uid, RiTurn.session_id.in_(ids), RiTurn.idx.is_not(None))
                          .order_by(RiTurn.id.desc()).limit(10))).scalars().all()
    return list(qs)


async def _next_turn(s, sess: RiSession, now: dt.datetime) -> RiTurn:
    """The open question, or the next one: a follow-up to a weak last answer (at most one in a row) -> the next queued plan row -> the bank.
    Runs inside the caller's transaction with the session row locked."""
    turns = (await s.execute(select(RiTurn).where(RiTurn.session_id == sess.id).order_by(RiTurn.idx.nulls_last(), RiTurn.plan_pos))).scalars().all()
    for t in turns:
        if t.status == "asked":
            return t
    answered = [t for t in turns if t.status == "answered"]
    if len(answered) >= rules.MAX_ANSWERS:
        raise Conflict("session_cap")
    asked = [t for t in turns if t.idx is not None]
    last = max(asked, key=lambda t: t.idx) if asked else None
    nxt = (last.idx if last else 0) + 1
    if last is not None and last.status == "answered" and last.source != "followup":
        fb = last.feedback or {}
        fu = fb.get("follow_up")
        if fu and not fb.get("follow_used") and (last.score or 0) < 70 and rules.valid_question(fu):
            last.feedback = {**fb, "follow_used": True}
            t = RiTurn(session_id=sess.id, user_id=sess.user_id, idx=nxt, kind="followup", source="followup", question=fu,
                       why="A follow-up to your last answer.", req_ids=[], status="asked", asked_at=now)
            s.add(t)
            await s.flush()
            return t
    queued = sorted([t for t in turns if t.status == "queued"], key=lambda t: (t.plan_pos or 0))
    if queued:
        t = queued[0]
        t.idx, t.status, t.asked_at = nxt, "asked", now
        await s.flush()
        return t
    asked_norms = {P.norm(t.question) for t in turns}
    b = rules.pick_bank(_bank_ctx(sess.brief or {}), asked_norms, last.kind if last else "", (sess.settings or {}).get("type", "mixed"), seed=sess.id + nxt)
    if b is None:
        raise Conflict("session_cap")
    t = RiTurn(session_id=sess.id, user_id=sess.user_id, idx=nxt, kind=b["kind"], source="bank", question=b["text"], why=b["why"], req_ids=[],
               status="asked", asked_at=now)
    s.add(t)
    await s.flush()
    return t


async def start(uid: str, sid: int, llm, before_model: Hook) -> dict:
    import time
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status == "finished":
            raise Conflict("finished")
        if sess.status == "active":
            t = await _next_turn(s, sess, now)
            counts = await _counts(s, sid)
            await s.commit()
            return {"turn": turn_json(t, now), "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}
        if sess.status != "matched":
            raise Conflict("wrong_state")
        an = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
        if an is None or an.user_id != uid or an.state != "done":
            raise Conflict("wrong_state")
        if sess.plan_state == "pending" and rules.claim_fresh(sess.plan_claimed_at, now):
            raise Pending()
        resume = await _own_doc(s, uid, sess.resume_id, "resume")
        if resume is None:
            raise Invalid("no_resume")
        res = an.result or {}
        jd = await _own_doc(s, uid, sess.jd_id, "jd")
        meta = (jd.meta or {}) if jd is not None else {}
        role = res.get("role") or meta.get("role") or {}
        asked_before = await _asked_before(s, uid, sess.jd_id, sid)
        sess.plan_state, sess.plan_claimed_at = "pending", now
        ctx = {"resume_text": resume.text, "analysis": res, "role": role, "reqs_meta": meta.get("requirements", []), "settings": dict(sess.settings or {}),
               "asked_before": asked_before}
        await s.commit()
    t0 = time.monotonic()
    try:
        await before_model()
        try:
            brief, qs = await engine.build_plan(llm, ctx["role"], ctx["analysis"].get("requirements", []), ctx["resume_text"], ctx["settings"], ctx["asked_before"])
        except engine.Unavailable as e:
            if not e.parse_failed:
                raise
            brief, qs = _fallback_brief(ctx["analysis"], ctx["role"], ctx["settings"]), []      # the model answered but nothing validated: bank questions
    except Exception as e:
        async with _S() as s:
            await s.execute(update(RiSession).where(RiSession.id == sid, RiSession.user_id == uid, RiSession.plan_state == "pending",
                                                    RiSession.plan_claimed_at == now).values(plan_state="none"))
            await s.commit()
        print(f"[rinterview] plan {int((time.monotonic() - t0) * 1000)}ms {type(e).__name__}")
        raise
    brief["skills"] = _merge_skills(brief, ctx["analysis"].get("requirements", []), ctx["reqs_meta"])
    brief["role"] = {"title": ctx["role"].get("title", ""), "company": ctx["role"].get("company", "")}
    brief["requirements"] = [{"id": r["id"], "text": r["text"], "type": r["type"]} for r in ctx["analysis"].get("requirements", [])]
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.plan_state != "pending" or sess.plan_claimed_at != now:
            t = await _next_turn(s, sess, _utc()) if sess.status == "active" else None
            counts = await _counts(s, sid)
            await s.commit()
            if t is None:
                raise Pending()
            return {"turn": turn_json(t), "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}
        sess.brief = rules.safe_json(brief)
        pos = 1
        asked_norms: set[str] = set()
        for q in qs:
            s.add(RiTurn(session_id=sid, user_id=uid, plan_pos=pos, kind=q["kind"], source="plan", question=q["text"], why=q["why"], req_ids=q["req"], status="queued"))
            asked_norms.add(P.norm(q["text"]))
            pos += 1
        bctx = _bank_ctx(sess.brief)
        last_kind = qs[-1]["kind"] if qs else ""
        while pos <= 8:                                          # a plan always has at least 8 questions: top up from the bank
            b = rules.pick_bank(bctx, asked_norms, last_kind, sess.settings.get("type", "mixed"), seed=sid + pos)
            if b is None:
                break
            s.add(RiTurn(session_id=sid, user_id=uid, plan_pos=pos, kind=b["kind"], source="bank", question=b["text"], why=b["why"], req_ids=[], status="queued"))
            asked_norms.add(P.norm(b["text"]))
            last_kind = b["kind"]
            pos += 1
        await s.flush()
        sess.status, sess.plan_state, sess.started_at, sess.last_activity_at = "active", "done", _utc(), _utc()
        sess.rev += 1
        t = await _next_turn(s, sess, _utc())
        counts = await _counts(s, sid)
        out = {"turn": turn_json(t), "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}
        await s.commit()
    print(f"[rinterview] plan {int((time.monotonic() - t0) * 1000)}ms ok")
    return out


async def next_question(uid: str, sid: int) -> dict:
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status == "finished":
            raise Conflict("finished")
        if sess.status != "active":
            raise Conflict("wrong_state")
        t = await _next_turn(s, sess, now)
        sess.last_activity_at = now
        sess.rev += 1
        counts = await _counts(s, sid)
        out = {"turn": turn_json(t, now), "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}
        await s.commit()
        return out


async def skip_turn(uid: str, sid: int, tid: int) -> dict:
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status != "active":
            raise Conflict("finished" if sess.status == "finished" else "wrong_state")
        t = await _own_turn(s, uid, sid, tid, lock=True)
        if t.status != "asked":
            raise Conflict("wrong_state")
        t.status = "skipped"
        sess.last_activity_at = _utc()
        sess.rev += 1
        counts = await _counts(s, sid)
        out = {"turn": turn_json(t), "counts": counts, "can_finish": can_finish_of(counts)}
        await s.commit()
        return out


async def get_turn(uid: str, sid: int, tid: int) -> dict:
    async with _S() as s:
        await _own_session(s, uid, sid)
        t = await _own_turn(s, uid, sid, tid)
        counts = await _counts(s, sid)
        out = {"turn": turn_json(t), "counts": counts, "can_finish": can_finish_of(counts)}
        await s.commit()
        return out


# ----------------------------------------------------------------------------- one answer (call D)
async def _fail_feedback(uid: str, c: dict, exc: Exception) -> dict:
    """Keep what was measured: the transcript is already saved; store a delivery-only feedback and mark the turn failed (Retry stays available)."""
    async with _S() as s:
        t = (await s.execute(select(RiTurn).where(RiTurn.id == c["tid"], RiTurn.user_id == uid).with_for_update())).scalars().first()
        if t is not None and t.feedback_state == "pending" and t.feedback_claimed_at == c["stamp"]:
            t.feedback = rules.safe_json(rules.delivery_only_feedback(c["delivery"], c["flags"], c["settings"].get("feedback_lang", "hinglish")))
            t.scores = {"delivery": int(c["delivery"]["score"])}
            t.feedback_state = "failed"
        out = turn_json(t) if t is not None else {}
        await s.commit()
    return out


async def _run_feedback(uid: str, c: dict, llm, before_model: Hook) -> dict:
    import time
    t0 = time.monotonic()
    try:
        await before_model()
        fb = await engine.answer_feedback(llm, question=c["question"], kind=c["kind"], why=c["why"], brief=c["brief"], resume_text=c["resume_text"],
                                          jd_text=c["jd_text"], transcript=c["transcript"], delivery=c["delivery"], flags=c["flags"],
                                          feedback_lang=c["settings"].get("feedback_lang", "hinglish"), itype=c["settings"].get("type", "mixed"))
    except Exception as e:
        turn = await _fail_feedback(uid, c, e)
        print(f"[rinterview] feedback {int((time.monotonic() - t0) * 1000)}ms {type(e).__name__}")
        raise FeedbackFailed(turn, quota=isinstance(e, QuotaExceeded) or quotaish(e)) from e
    async with _S() as s:
        sess = await _own_session(s, uid, c["sid"], lock=True)
        t = await _own_turn(s, uid, c["sid"], c["tid"], lock=True)
        if sess.status != "active" or t.feedback_state != "pending" or t.feedback_claimed_at != c["stamp"]:
            out = turn_json(t)                                   # finished meanwhile, or another request took over: never overwrite
            await s.commit()
            return out
        t.feedback = rules.safe_json(fb)
        t.scores = {k: int(v) for k, v in fb["scores"].items()}
        t.score = int(fb["overall"])
        t.feedback_state = "done"
        t.real = bool(t.real and fb.get("genuine", True))
        sess.last_activity_at = _utc()
        sess.rev += 1
        out = turn_json(t)
        await s.commit()
    print(f"[rinterview] feedback {int((time.monotonic() - t0) * 1000)}ms ok")
    return out


async def _feedback_ctx(s, sess: RiSession, t: RiTurn, uid: str, stamp: dt.datetime) -> dict:
    resume = await _own_doc(s, uid, sess.resume_id, "resume")
    jd = await _own_doc(s, uid, sess.jd_id, "jd")
    m = t.metrics or {}
    return {"sid": sess.id, "tid": t.id, "stamp": stamp, "question": t.question, "kind": t.kind, "why": t.why or "", "brief": sess.brief or {},
            "resume_text": resume.text if resume else "", "jd_text": jd.text if jd else "", "transcript": t.answer or "",
            "delivery": m.get("delivery") or {}, "flags": m.get("flags") or {}, "settings": dict(sess.settings or {})}


async def answer(uid: str, sid: int, tid: int, body: dict, llm, before_model: Hook) -> dict:
    """Save the transcript FIRST, then ask the model. -> {too_short: True, ...} | {turn, counts, can_finish, queued_count}. Raises Conflict /
    Pending / LimitReached / FeedbackFailed."""
    now = _utc()
    key = rules.clean_str(body.get("client_key"), 64) or None
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status != "active":
            raise Conflict("finished" if sess.status == "finished" else "wrong_state")
        t = await _own_turn(s, uid, sid, tid, lock=True)
        if t.status == "answered":
            if key and t.answer_key == key:
                return await _answer_replay(s, uid, sess, t, llm, before_model, now)
            raise Conflict("already_answered", turn=turn_json(t, now))
        if t.status != "asked":
            raise Conflict("wrong_state")
        transcript = docs.redact_light(rules.clean_str(body.get("transcript"), rules.MAX_TRANSCRIPT_CHARS))      # cap first, then redact: the request may carry 300 KB
        segs = body.get("segments")
        delivery = rules.delivery_block(transcript, body.get("words"), segs, body.get("duration_sec"))
        if not rules.answer_floor(delivery["words"], delivery["seconds"]):
            return {"too_short": True, "reason": "short", "words": delivery["words"], "seconds": delivery["seconds"],
                    "min_words": rules.MIN_ANSWER_WORDS, "min_seconds": int(rules.MIN_ANSWER_SEC)}
        if rules.is_hallucination(transcript, segs):
            return {"too_short": True, "reason": "no_speech", "words": delivery["words"], "seconds": delivery["seconds"],
                    "min_words": rules.MIN_ANSWER_WORDS, "min_seconds": int(rules.MIN_ANSWER_SEC)}
        if (await _today_counts(s, uid))["answers"] >= rules.ANSWERS_PER_DAY:
            raise LimitReached("daily")
        brief = sess.brief or {}
        skills = list(brief.get("skills") or [])
        flags = rules.evidence_flags(transcript, skills)
        eng = body.get("engine") if body.get("engine") in ("groq", "gemini") else None
        t.status, t.answer, t.answer_sec, t.answer_words = "answered", transcript, float(delivery["seconds"]), int(delivery["words"])
        t.answer_key, t.engine, t.audio_device = key, eng, rules.clean_str(body.get("audio_device"), 64) or None
        t.metrics = rules.safe_json({"delivery": delivery, "flags": flags})
        t.real = bool(delivery["genuine"])
        t.answered_at = now
        t.feedback_state, t.feedback_claimed_at = "pending", now
        t.feedback_attempts = (t.feedback_attempts or 0) + 1
        sess.last_activity_at = now
        sess.rev += 1
        ctx = await _feedback_ctx(s, sess, t, uid, now)
        await s.commit()
    turn = await _run_feedback(uid, ctx, llm, before_model)
    return await _turn_envelope(uid, sid, turn)


async def _turn_envelope(uid: str, sid: int, turn: dict) -> dict:
    async with _S() as s:
        counts = await _counts(s, sid)
        await s.commit()
    return {"turn": turn, "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}


async def _answer_replay(s, uid: str, sess: RiSession, t: RiTurn, llm, before_model: Hook, now: dt.datetime) -> dict:
    """The same answer sent again (a lost response): return what is stored; if its feedback never finished, finish it."""
    fs = t.feedback_state
    if fs == "pending" and rules.claim_fresh(t.feedback_claimed_at, now):
        await s.commit()
        raise Pending()
    if fs == "done":
        counts = await _counts(s, sess.id)
        out = {"turn": turn_json(t, now), "counts": counts, "can_finish": can_finish_of(counts), "queued_count": counts["queued"]}
        await s.commit()
        return out
    t.feedback_state, t.feedback_claimed_at = "pending", now
    t.feedback_attempts = (t.feedback_attempts or 0) + 1
    ctx = await _feedback_ctx(s, sess, t, uid, now)
    await s.commit()
    turn = await _run_feedback(uid, ctx, llm, before_model)
    return await _turn_envelope(uid, sess.id, turn)


async def retry_feedback(uid: str, sid: int, tid: int, llm, before_model: Hook) -> dict:
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status != "active":
            raise Conflict("finished" if sess.status == "finished" else "wrong_state")
        t = await _own_turn(s, uid, sid, tid, lock=True)
        if t.status != "answered":
            raise Conflict("wrong_state")
        return await _answer_replay(s, uid, sess, t, llm, before_model, now)


# ----------------------------------------------------------------------------- finish: computed report, XP exactly once
def _turn_dict(t: RiTurn) -> dict:
    return {"id": t.id, "idx": t.idx, "kind": t.kind, "question": t.question, "status": t.status, "real": bool(t.real), "answer_sec": t.answer_sec,
            "answer_words": t.answer_words, "scores": t.scores or {}, "overall": t.score, "feedback": t.feedback, "req_ids": t.req_ids or [],
            "metrics": t.metrics or {}}


async def _turn_dicts(s, uid: str, sid: int) -> list[dict]:
    rows = (await s.execute(select(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid).order_by(RiTurn.idx.nulls_last()))).scalars().all()
    return [_turn_dict(t) for t in rows]


async def _ensure_v2(s, uid: str, row: RiSession) -> dict:
    """The row's report WITH the coaching fields. A report written before they existed is upgraded the first time it is read - computed from the stored
    answers (no model, no cost) and saved; the caller's transaction commits it. Idempotent: two readers upgrading at once write the same thing."""
    rep = row.report or {}
    if not rep or rep.get("v") == coach.REPORT_VERSION:
        return rep
    new = rules.safe_json(coach.enrich_report(rep, await _turn_dicts(s, uid, row.id), prev_any=None))
    row.report = new
    return new


async def _latest_finished(s, uid: str, exclude_id: int | None = None) -> RiSession | None:
    q = select(RiSession).where(RiSession.user_id == uid, RiSession.status == "finished", RiSession.report.is_not(None))
    if exclude_id is not None:
        q = q.where(RiSession.id != exclude_id)
    return (await s.execute(q.order_by(RiSession.finished_at.desc(), RiSession.id.desc()).limit(1))).scalars().first()


def _info_of(row: RiSession, rep: dict) -> dict:
    return {"session_id": row.id, "title": row.title, "finished_at": _iso(row.finished_at), "overall": rep.get("overall"), "real": rep.get("real", 0),
            "habits": rep.get("habits"), "focus": rep.get("focus")}


async def _prev_info(s, uid: str, exclude_id: int | None = None) -> dict | None:
    """The learner's previous finished interview (any job) with its saved habits and focus points - what this interview's report compares itself with."""
    row = await _latest_finished(s, uid, exclude_id)
    if row is None:
        return None
    return _info_of(row, await _ensure_v2(s, uid, row))


async def _focus_prev(s, uid: str, exclude_id: int | None = None) -> dict | None:
    """The improvement points the learner was given after their previous interview: {session_id, title, finished_at, overall, points}."""
    row = await _latest_finished(s, uid, exclude_id)
    if row is None:
        return None
    rep = await _ensure_v2(s, uid, row)
    pts = rep.get("focus") or []
    return {"session_id": row.id, "title": row.title, "finished_at": _iso(row.finished_at), "overall": rep.get("overall"), "points": pts} if pts else None


async def finish(uid: str, sid: int) -> dict:
    """Close the interview and build the report from the stored turns - no model, so Finish cannot fail on quota. Idempotent: a second call
    returns the stored report."""
    now = _utc()
    async with _S() as s:
        sess = await _own_session(s, uid, sid, lock=True)
        if sess.status == "finished" and sess.report:
            counts = await _counts(s, sid)
            out = {"report": sess.report, "session": session_json(sess, counts["answered"], counts["real"]), "already": True}
            await s.commit()
            return out
        if sess.status != "active":
            raise Conflict("wrong_state")
        counts = await _counts(s, sid)
        cf = can_finish_of(counts)
        if not cf["ok"]:
            raise Conflict("need_more", need=cf["need"], reasons=cf["reasons"])
        await s.execute(update(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid, RiTurn.status.in_(("queued", "asked"))).values(status="dropped"))
        turns = (await s.execute(select(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid).order_by(RiTurn.idx.nulls_last()))).scalars().all()
        an = await s.get(RiAnalysis, sess.analysis_id) if sess.analysis_id else None
        reqs = [{"id": r["id"], "text": r["text"]} for r in ((an.result or {}).get("requirements", []) if an is not None and an.user_id == uid else [])]
        if not reqs:
            reqs = [{"id": r["id"], "text": r["text"]} for r in (sess.brief or {}).get("requirements", [])]
        prev = None
        if sess.jd_id is not None:
            pv = (await s.execute(select(RiSession).where(RiSession.user_id == uid, RiSession.jd_id == sess.jd_id, RiSession.status == "finished",
                                                         RiSession.id != sid).order_by(RiSession.finished_at.desc()).limit(1))).scalars().first()
            if pv is not None and pv.report:
                prev = {"session_id": pv.id, "categories": pv.report.get("categories", []), "real": pv.report.get("real", 0),
                        "delivery_measured": pv.report.get("delivery_measured", False)}
        fl = (sess.settings or {}).get("feedback_lang", "hinglish")
        report = rules.build_report([_turn_dict(t) for t in turns], requirements=reqs, feedback_lang=fl, prev=prev)
        report = coach.enrich_report(report, [_turn_dict(t) for t in turns], prev_any=await _prev_info(s, uid, exclude_id=sid))      # weaknesses, focus points, "since last time"
        report["generated_at"] = _iso(now)
        report["session_id"] = sid
        sess.report, sess.overall, sess.status, sess.finished_at, sess.last_activity_at = rules.safe_json(report), report["overall"], "finished", now, now
        sess.rev += 1
        counts = await _counts(s, sid)
        out = {"report": report, "session": session_json(sess, counts["answered"], counts["real"]), "already": False}
        await s.commit()
        return out


async def _xp_row_since(uid: str, since: dt.datetime) -> bool:
    """Did `award_speaker_progress` already commit a Resume Interview row for this learner since `since`? (Its XP row is committed BEFORE its badge check,
    so an error after that point must not make a retry pay a second time.) Unknown -> True: never risk paying twice."""
    try:
        async with _S() as s:
            n = (await s.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == uid, db.SessionScore.mode == "resume_interview",
                                                                                       db.SessionScore.created_at >= since))).scalar() or 0
            await s.commit()
        return n > 0
    except Exception:
        return True


async def award_for_finish(uid: str, claims: dict, sid: int) -> dict:
    """XP, streak, league, missions, daily stats, vocabulary and ONE cleaned memory line - once. The compare-and-set on `awarded_at` makes a replayed
    Finish harmless; a failure clears the flag so a retry can still pay - unless the XP row was already committed."""
    claim_time = _utc()
    async with _S() as s:
        got = (await s.execute(update(RiSession).where(RiSession.id == sid, RiSession.user_id == uid, RiSession.status == "finished",
                                                     RiSession.awarded_at.is_(None)).values(awarded_at=claim_time).returning(RiSession.id))).scalar()
        if not got:
            await s.commit()
            return {"progress": None, "mission": None}
        sess = await _own_session(s, uid, sid)
        turns = (await s.execute(select(RiTurn).where(RiTurn.session_id == sid, RiTurn.user_id == uid, RiTurn.status == "answered"))).scalars().all()
        rep = sess.report or {}
        role = ((sess.brief or {}).get("role") or {}).get("title") or sess.title
        await s.commit()
    td = [_turn_dict(t) for t in turns]
    minutes = rules.minutes_for(td)
    words = sum(int(t.get("answer_words") or 0) for t in td)
    real_td = [t for t in td if t["real"]]
    real_n = len(real_td)
    real_words = sum(int(t.get("answer_words") or 0) for t in real_td)
    # a component with no signal (the model was down for every answer: only delivery was measured) is UNSCORED, which the XP formula leaves out of the
    # overall - counting it as 0 made a finished interview look like a bad one
    sc = rules.progress_scores(rep.get("categories", []))
    unscored = frozenset(k for k, v in sc.items() if v is None)
    if sc.get("confidence") is None:                    # no signal at all (cannot happen with a real answer): keep the formula's divisor above zero
        unscored = unscored - {"confidence", "continuity"}
    scores = {k: (0 if v is None else v) for k, v in sc.items()}
    progress = mission = None
    try:
        await db.login(claims)
        sp = await db.award_speaker_progress(uid, "resume_interview", minutes=minutes, turns=max(1, words // 40), scores=scores,
                                             genuine_effort=real_n >= rules.FINISH_MIN and real_words / max(1, real_n) >= rules.MIN_ANSWER_WORDS, unscored=unscored)
        progress = sp or {}
        try:
            mr = await db.update_weekly_missions(uid, "resume_interview", minutes, (sp or {}).get("overall", 0))
            mission = mr if mr.get("completed") else None
        except Exception as e:
            print(f"[rinterview] missions failed: {type(e).__name__}")
        try:
            await db.bump_daily_stat(uid, sentences=max(1, words // 40), seconds=int(minutes * 60))
            await db.add_vocab(uid, " ".join((t.answer or "") for t in turns if t.real).split())
            ov = rep.get("overall")
            await db.add_conversation(uid, "resume_interview", f"Practised a mock interview for a {rules.clean_str(role, 60) or 'job'} role ({real_n} answers)"
                                      + (f" - scored {ov}." if ov is not None else " - the feedback was not available."))
        except Exception as e:
            print(f"[rinterview] post-finish steps failed: {type(e).__name__}")
    except Exception as e:
        print(f"[rinterview] award failed: {type(e).__name__}")
        if not await _xp_row_since(uid, claim_time):      # nothing was paid: a retry may pay. If the XP row exists, leave the flag set - no second payment
            async with _S() as s:
                await s.execute(update(RiSession).where(RiSession.id == sid, RiSession.user_id == uid).values(awarded_at=None))
                await s.commit()
    return {"progress": progress, "mission": mission}


# ----------------------------------------------------------------------------- DuSu's view of the learner's interviews, data rights, dashboard
async def life_data(uid: str) -> dict:
    """Scores and role titles only - never resume or job text (they flow into other modes' prompts)."""
    async with _S() as s:
        fin = (await s.execute(select(RiSession).where(RiSession.user_id == uid, RiSession.status == "finished").order_by(RiSession.finished_at.desc()).limit(3))).scalars().all()
        total = (await s.execute(select(func.count()).select_from(RiSession).where(RiSession.user_id == uid, RiSession.status == "finished"))).scalar() or 0
        act = (await s.execute(select(RiSession).where(RiSession.user_id == uid, RiSession.status == "active").order_by(RiSession.last_activity_at.desc()).limit(1))).scalars().first()
        act_n = 0
        if act is not None:
            act_n = (await s.execute(select(func.count()).select_from(RiTurn).where(RiTurn.session_id == act.id, RiTurn.status == "answered", RiTurn.real.is_(True)))).scalar() or 0
        out = {"finished": int(total), "last": None, "active": None}
        if fin:
            r = fin[0].report or {}
            cats = {c["key"]: c["score"] for c in r.get("categories", []) if c.get("score") is not None}
            weakest = min(cats.items(), key=lambda kv: kv[1])[0] if cats else ""
            out["last"] = {"title": fin[0].title, "overall": fin[0].overall, "answers": r.get("real", 0), "finished_at": fin[0].finished_at, "weakest": weakest,
                           "focus": [str(f.get("title") or "")[:60] for f in (r.get("focus") or [])][:3]}
            if len(fin) > 1 and fin[0].jd_id is not None and fin[0].jd_id == fin[1].jd_id and fin[1].overall is not None and fin[0].overall is not None:
                out["last"]["delta"] = fin[0].overall - fin[1].overall
        if act is not None:
            out["active"] = {"title": act.title, "answers": int(act_n)}
        await s.commit()
        return out


def _row_dict(r) -> dict:
    out = {}
    for c in r.__table__.columns:
        v = getattr(r, c.name)
        out[c.name] = v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v
    return out


async def export_all(uid: str) -> dict:
    """Every row the learner owns, as JSON (data rights). There is no audio to export: it never reached the server."""
    async with _S() as s:
        out: dict[str, Any] = {"exported_at": _utc().isoformat()}
        for M in RI_TABLES:
            rows = (await s.execute(select(M).where(M.user_id == uid))).scalars().all()
            out[M.__tablename__] = [_row_dict(r) for r in rows]
        await s.commit()
        return out


async def delete_all(uid: str) -> dict:
    """Everything the learner has in Resume Interview, plus the one-line memory notes DuSu kept about these interviews (role + score). XP, streak and
    the vocabulary counter are shared with the other practice modes and go only with the account (the privacy page says so)."""
    async with _S() as s:
        await delete_rows(s, [uid])
        await s.execute(delete(db.Conversation).where(db.Conversation.user_id == uid, db.Conversation.mode == "resume_interview"))
        await s.commit()
    return {"ok": True}


async def delete_rows(s, uids: list) -> None:
    """FK-safe delete of every Resume Interview row for these users, inside the caller's transaction (also used by delete_user / admin_wipe_users)."""
    for M in (RiTurn, RiSession, RiAnalysis, RiDocument):
        await s.execute(delete(M).where(M.user_id.in_(uids)))


async def health() -> dict:
    """A few counters for the owner dashboard."""
    try:
        async with _S() as s:
            ds = _day_start()
            docs_n = (await s.execute(select(func.count()).select_from(RiDocument))).scalar() or 0
            sess_n = (await s.execute(select(func.count()).select_from(RiSession))).scalar() or 0
            fin_n = (await s.execute(select(func.count()).select_from(RiSession).where(RiSession.status == "finished"))).scalar() or 0
            ans_n = (await s.execute(select(func.count()).select_from(RiTurn).where(RiTurn.status == "answered", RiTurn.answered_at >= ds))).scalar() or 0
            bad_n = (await s.execute(select(func.count()).select_from(RiTurn).where(RiTurn.feedback_state == "failed", RiTurn.answered_at >= ds))).scalar() or 0
            await s.commit()
        return {"documents": int(docs_n), "sessions": int(sess_n), "finished": int(fin_n), "answers_today": int(ans_n), "feedback_failed_today": int(bad_n)}
    except Exception as e:
        print(f"[rinterview] health failed: {type(e).__name__}")
        return {}
