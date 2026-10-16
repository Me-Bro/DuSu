"""Grammar Coach - every read / write, scoped to the learner (plan sections 8 and 11).

Rules of the road (the My Day / Job Interview Practice ones): every query filters on user_id; a foreign id is a 404, never a 403; creation is
idempotent (a unique client_key per learner); a model call is NEVER made inside a transaction - the claim pattern is claim -> commit -> work ->
lock -> write only if the claim is still ours; error messages never contain the learner's words; enumerated columns fit their String(32).
Text rule (D6): the learner's sentences are written ONLY after their one-time choice ("keep" / "counts"); until then the first result is held in
memory (<= 30 min) and only counts - marks without text - are written.
"""

from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import db
from ..db import _now
from . import RULES_VERSION, catalog, scoring
from .models import GC_TABLES, GcDrill, GcMark, GcSentence, GcSession

_S = lambda: db._Session()          # noqa: E731 - resolved at call time so tests can swap the engine

CLAIM_TTL_S = 150
HELD_TTL_S = 1800
MAX_SENTENCE_ROWS = 1500
MAX_MARK_ROWS = 3000
PAGE = 30
SOURCES = ("talk", "interview", "practice", "job_interview")
DEFAULT_PREFS = {"choice": "", "feedback_lang": "hinglish", "strict": "auto", "natural_tips": True, "drill_days": []}
_held: dict[tuple, tuple[float, dict]] = {}          # (uid, client_key) -> (expires, payload)


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


class Pending(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def _utc() -> dt.datetime:
    return _now()


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------- preferences (memory.facts["gc_prefs"], no migration)
async def get_prefs(uid: str) -> dict:
    async with _S() as s:
        mem = await s.get(db.Memory, uid)
        p = dict(((mem.facts or {}).get("gc_prefs") or {}) if mem else {})
    out = dict(DEFAULT_PREFS)
    for k in DEFAULT_PREFS:
        if k in p:
            out[k] = p[k]
    out["choice"] = out["choice"] if out["choice"] in ("keep", "counts") else ""
    out["feedback_lang"] = out["feedback_lang"] if out["feedback_lang"] in ("hinglish", "en") else "hinglish"
    out["strict"] = out["strict"] if out["strict"] in ("auto", "gentle", "standard", "strict") else "auto"
    out["natural_tips"] = bool(out["natural_tips"])
    out["drill_days"] = [d for d in (out.get("drill_days") or []) if isinstance(d, str)][-60:]
    return out


async def set_prefs(uid: str, patch: dict) -> dict:
    clean: dict = {}
    if patch.get("choice") in ("keep", "counts"):
        clean["choice"] = patch["choice"]
    if patch.get("feedback_lang") in ("hinglish", "en"):
        clean["feedback_lang"] = patch["feedback_lang"]
    if patch.get("strict") in ("auto", "gentle", "standard", "strict"):
        clean["strict"] = patch["strict"]
    if "natural_tips" in patch:
        clean["natural_tips"] = bool(patch["natural_tips"])
    if not clean:
        return await get_prefs(uid)
    async with _S() as s:
        mem = await db._get_or_make_memory(s, uid)
        f = dict(mem.facts or {})
        p = dict(f.get("gc_prefs") or {})
        p.update(clean)
        f["gc_prefs"] = p
        mem.facts = f
        db.flag_modified(mem, "facts")
        if clean.get("choice") == "counts":
            await _strip_text(s, uid)
        await s.commit()
    if clean.get("choice") == "counts":
        for k in [k for k in _held if k[0] == uid]:
            _held.pop(k, None)
    return await get_prefs(uid)


async def _strip_text(s, uid: str) -> None:
    """"Counts only": delete every stored sentence, blank the text of every mark; the counts survive."""
    await s.execute(delete(GcSentence).where(GcSentence.user_id == uid))
    await s.execute(update(GcMark).where(GcMark.user_id == uid).values(sentence_id=None, quote="", fix="", why=""))
    await s.execute(update(GcSession).where(GcSession.user_id == uid).values(text_saved=False))


# ----------------------------------------------------------------------------- the claim pattern
async def claim(uid: str, source: str, kind: str, key: str, level: str, lang: str = "en") -> tuple[int, str, dt.datetime]:
    """-> (session id, "run" | "done" | "pending", stamp). "run": this caller now owns the analysis; "done": a finished one exists; "pending": a fresh
    claim by someone else (poll). A claim older than CLAIM_TTL_S is stale and can be re-taken, so a crash never blocks a session."""
    if source not in SOURCES or not key or len(key) > 64:
        raise Invalid("source")
    now = _utc()
    async with _S() as s:
        ins = pg_insert(GcSession).values(user_id=uid, source=source, kind=(kind or "")[:32], client_key=key, lang=lang, level=(level or "")[:8],
                                          state="pending", claimed_at=now, rules_version=RULES_VERSION, created_at=now)
        res = await s.execute(ins.on_conflict_do_nothing(index_elements=["user_id", "client_key"], index_where=GcSession.client_key.is_not(None)).returning(GcSession.id))
        created = res.scalar()
        row = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.client_key == key).with_for_update())).scalars().first()
        if row is None:
            raise NotFound()
        if created is not None:
            await s.commit()
            return row.id, "run", now
        if row.state in ("done", "partial"):
            await s.commit()
            return row.id, "done", row.claimed_at or now
        if row.state == "pending" and row.claimed_at and (now - row.claimed_at).total_seconds() < CLAIM_TTL_S:
            await s.commit()
            return row.id, "pending", row.claimed_at
        row.state, row.claimed_at, row.level = "pending", now, (level or "")[:8]
        await s.commit()
        return row.id, "run", now


async def fail(uid: str, sid: int, stamp: dt.datetime) -> None:
    try:
        async with _S() as s:
            await s.execute(update(GcSession).where(GcSession.id == sid, GcSession.user_id == uid, GcSession.state == "pending", GcSession.claimed_at == stamp)
                            .values(state="failed"))
            await s.commit()
    except Exception as e:
        print(f"[gcoach] mark failed: {type(e).__name__}")


# ----------------------------------------------------------------------------- persist one analysis
async def persist(uid: str, sid: int, stamp: dt.datetime, analysis: dict, *, duration_sec: int = 0, redact=None) -> dict:
    """Write the analysis if the claim is still ours. Counts and mark rows always; sentence text only when the learner chose "keep"."""
    prefs = await get_prefs(uid)
    keep = prefs["choice"] == "keep"
    counts = analysis["counts"]
    redact = redact or (lambda t: t)
    flagged = [r for r in analysis["sentences"] if r["marks"] and r["status"] in ("fix", "natural", "unsure")]
    async with _S() as s:
        row = (await s.execute(select(GcSession).where(GcSession.id == sid, GcSession.user_id == uid).with_for_update())).scalars().first()
        if row is None or row.state != "pending" or row.claimed_at != stamp:
            await s.commit()
            return {"stale": True}
        c = counts
        row.units = analysis.get("units", [])[:400]
        row.timeline = (c.get("timeline") or "")[:600]
        row.words = sum(r["words"] for r in analysis["sentences"])
        row.words_checked = int(c.get("words_checked", 0))
        row.sentences = len(analysis["sentences"])
        row.checked = int(c.get("checked", 0))
        row.skipped = int(c.get("skipped_total", 0))
        row.clean = int(c.get("clean", 0))
        row.marks_error = int(c.get("errors", 0))
        row.marks_natural = int(sum(1 for r in analysis["sentences"] for m in r["marks"] if m["severity"] == "natural" and m["conf"] == "sure"))
        row.per100 = c.get("per100") if scoring.enough(c) else None
        row.rule_counts = c.get("rule_counts") or {}
        row.family_counts = c.get("family_counts") or {}
        row.flow = analysis.get("flow")
        row.top = []
        row.best_run = int(c.get("best_run", 0))
        row.duration_sec = int(duration_sec or 0)
        row.rules_version = analysis.get("rules_version", RULES_VERSION)
        row.level = str(analysis.get("level") or row.level)[:8]
        row.lang = "en"
        row.engine = analysis.get("engine") or {}
        row.finished_at = _utc()
        partial = int(c.get("unchecked_total", 0)) > 0
        row.state = "partial" if partial or (analysis.get("engine") or {}).get("degraded") else "done"
        row.text_saved = bool(keep and flagged)
        for r in flagged:
            sent_id = None
            if keep:
                sr = GcSentence(user_id=uid, session_id=sid, unit=r["turn"], pos=r["pos"], said=redact(r["text"])[:320], fixed=redact(r["fixed"] or "")[:480],
                                status=r["status"] if r["status"] in ("fix", "natural", "unsure") else "fix")
                s.add(sr)
                await s.flush()
                sent_id = sr.id
            for m in r["marks"]:
                s.add(GcMark(user_id=uid, session_id=sid, sentence_id=sent_id, rule=str(m["rule"])[:64], family=str(m.get("family") or "")[:32],
                             severity=str(m["severity"])[:32], conf=str(m["conf"])[:32], src=str(m.get("src") or "model")[:32],
                             quote=redact(m["quote"])[:160] if keep else "", fix=redact(m["fix"])[:200] if keep else "",
                             why=str(m.get("why") or "")[:200] if keep else ""))
        await _prune(s, uid)
        await s.commit()
    if prefs["choice"] == "":
        _hold(uid, analysis, sid)
    return {"id": sid, "state": row.state}


def _hold(uid: str, analysis: dict, sid: int) -> None:
    now = time.time()
    for k in [k for k, (exp, _p) in _held.items() if exp < now]:
        _held.pop(k, None)
    if len(_held) > 500:
        _held.clear()
    _held[(uid, sid)] = (now + HELD_TTL_S, analysis)


async def _prune(s, uid: str) -> None:
    n = (await s.execute(select(func.count()).select_from(GcSentence).where(GcSentence.user_id == uid))).scalar() or 0
    if n > MAX_SENTENCE_ROWS:
        old = (await s.execute(select(GcSentence.id).where(GcSentence.user_id == uid).order_by(GcSentence.created_at, GcSentence.id).limit(n - MAX_SENTENCE_ROWS))).scalars().all()
        await s.execute(update(GcMark).where(GcMark.user_id == uid, GcMark.sentence_id.in_(old)).values(sentence_id=None, quote="", fix="", why=""))
        await s.execute(delete(GcSentence).where(GcSentence.id.in_(old), GcSentence.user_id == uid))
    m = (await s.execute(select(func.count()).select_from(GcMark).where(GcMark.user_id == uid))).scalar() or 0
    if m > MAX_MARK_ROWS:
        old = (await s.execute(select(GcMark.id).where(GcMark.user_id == uid).order_by(GcMark.created_at, GcMark.id).limit(m - MAX_MARK_ROWS))).scalars().all()
        await s.execute(delete(GcMark).where(GcMark.id.in_(old), GcMark.user_id == uid))


async def keep(uid: str, sid: int, choice: str, redact=None) -> dict:
    """The learner's one-time choice. "keep" writes the held result's sentences (if it is still in memory); "counts" strips and remembers."""
    if choice not in ("keep", "counts"):
        raise Invalid("choice")
    async with _S() as s:
        row = await s.get(GcSession, sid)
        if row is None or row.user_id != uid:
            raise NotFound()
    prefs = await set_prefs(uid, {"choice": choice})
    if choice == "keep":
        hit = _held.pop((uid, sid), None)
        if hit and hit[0] >= time.time():
            await _write_held(uid, sid, hit[1], redact or (lambda t: t))
    return {"ok": True, "choice": prefs["choice"]}


async def _write_held(uid: str, sid: int, analysis: dict, redact) -> None:
    flagged = [r for r in analysis["sentences"] if r["marks"] and r["status"] in ("fix", "natural", "unsure")]
    async with _S() as s:
        row = (await s.execute(select(GcSession).where(GcSession.id == sid, GcSession.user_id == uid).with_for_update())).scalars().first()
        if row is None or row.text_saved:
            await s.commit()
            return
        await s.execute(delete(GcMark).where(GcMark.user_id == uid, GcMark.session_id == sid))
        await s.execute(delete(GcSentence).where(GcSentence.user_id == uid, GcSentence.session_id == sid))
        for r in flagged:
            sr = GcSentence(user_id=uid, session_id=sid, unit=r["turn"], pos=r["pos"], said=redact(r["text"])[:320], fixed=redact(r["fixed"] or "")[:480],
                            status=r["status"] if r["status"] in ("fix", "natural", "unsure") else "fix")
            s.add(sr)
            await s.flush()
            for m in r["marks"]:
                s.add(GcMark(user_id=uid, session_id=sid, sentence_id=sr.id, rule=str(m["rule"])[:64], family=str(m.get("family") or "")[:32],
                             severity=str(m["severity"])[:32], conf=str(m["conf"])[:32], src=str(m.get("src") or "model")[:32],
                             quote=redact(m["quote"])[:160], fix=redact(m["fix"])[:200], why=str(m.get("why") or "")[:200]))
        row.text_saved = bool(flagged)
        await _prune(s, uid)
        await s.commit()


# ----------------------------------------------------------------------------- reading
def _title(rule: str) -> str:
    return catalog.title_of(rule, "en")


def _session_json(r: GcSession) -> dict:
    return {"id": r.id, "source": r.source, "kind": r.kind, "state": r.state, "created_at": _iso(r.created_at), "finished_at": _iso(r.finished_at),
            "level": r.level, "sentences": r.sentences, "checked": r.checked, "clean": r.clean, "skipped": r.skipped, "words": r.words,
            "words_checked": r.words_checked, "marks": r.marks_error, "per100": r.per100, "timeline": r.timeline, "best_run": r.best_run,
            "duration_sec": r.duration_sec, "text_saved": r.text_saved, "tally": (r.engine or {}).get("tally", ""), "source_engine": (r.engine or {}).get("source", ""),
            "degraded": bool((r.engine or {}).get("degraded"))}


async def _sentences_of(s, uid: str, sid: int) -> list[dict]:
    srows = (await s.execute(select(GcSentence).where(GcSentence.user_id == uid, GcSentence.session_id == sid).order_by(GcSentence.pos))).scalars().all()
    ids = [x.id for x in srows]
    marks: dict = {}
    if ids:
        for m in (await s.execute(select(GcMark).where(GcMark.user_id == uid, GcMark.sentence_id.in_(ids)).order_by(GcMark.id))).scalars().all():
            marks.setdefault(m.sentence_id, []).append({"id": m.id, "rule": m.rule, "title": _title(m.rule), "quote": m.quote, "fix": m.fix, "why": m.why, "conf": m.conf,
                                                         "severity": m.severity, "family": m.family, "contest": m.contest})
    return [{"id": x.id, "pos": x.pos, "turn": x.unit, "said": x.said, "fixed": x.fixed, "status": x.status, "contest": x.contest, "marks": marks.get(x.id, [])} for x in srows]


def _top_of(r: GcSession) -> list[dict]:
    out = []
    for rule, v in sorted((r.rule_counts or {}).items(), key=lambda kv: -int((kv[1] or {}).get("hits", 0))):
        h = int((v or {}).get("hits", 0))
        if h >= 1 and len(out) < 5:
            rl = catalog.get(rule)
            out.append({"rule": rule, "title": _title(rule), "hits": h, "weight": rl.weight if rl else 1, "group": rl.group if rl else ""})
    return out


async def report(uid: str, sid: int) -> dict:
    async with _S() as s:
        r = await s.get(GcSession, sid)
        if r is None or r.user_id != uid:
            raise NotFound()
        sents = await _sentences_of(s, uid, sid) if r.text_saved else []
        out = _session_json(r)
        out.update({"flow": r.flow, "top": _top_of(r), "family_counts": r.family_counts or {}, "text": "saved" if r.text_saved else "none"})
        await s.commit()
    held = _held.get((uid, sid))
    if not sents and held and held[0] >= time.time():
        a = held[1]
        sents = [{"id": None, "pos": x["pos"], "turn": x["turn"], "said": x["text"], "fixed": x["fixed"], "status": x["status"], "contest": "none",
                  "marks": [{"id": None, "rule": m["rule"], "title": m["title"], "quote": m["quote"], "fix": m["fix"], "why": m["why"], "conf": m["conf"],
                             "severity": m["severity"], "family": m["family"], "contest": "none"} for m in x["marks"] if m.get("shown", True)]}
                 for x in a["sentences"] if x["marks"] and x["status"] in ("fix", "natural", "unsure")]
        out["text"] = "held"
    prefs = await get_prefs(uid)
    out["sentences_list"] = sents
    out["choice_needed"] = prefs["choice"] == "" and (bool(sents) or out.get("marks", 0) > 0)
    out["enough"] = out["per100"] is not None
    return out


async def by_ref(uid: str, key: str) -> dict:
    async with _S() as s:
        r = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.client_key == key))).scalars().first()
        await s.commit()
    if r is None:
        return {"state": "none"}
    if r.state == "pending":
        stale = bool(r.claimed_at) and (_utc() - r.claimed_at).total_seconds() > CLAIM_TTL_S
        return {"state": "failed" if stale else "pending", "id": r.id}
    if r.state == "failed":
        return {"state": "failed", "id": r.id}
    return {"state": r.state, "id": r.id, "report": await report(uid, r.id)}


async def list_sessions(uid: str, before: int | None = None, limit: int = PAGE) -> dict:
    async with _S() as s:
        q = select(GcSession).where(GcSession.user_id == uid, GcSession.state.in_(("done", "partial")))
        if before:
            q = q.where(GcSession.id < before)
        rows = (await s.execute(q.order_by(GcSession.id.desc()).limit(limit + 1))).scalars().all()
        await s.commit()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"sessions": [_session_json(r) | {"top": _top_of(r)[:3]} for r in rows], "next": rows[-1].id if more and rows else None}


# ----------------------------------------------------------------------------- marks, contest, rule pages
async def list_notebook(uid: str, rule: str = "", session_id: int | None = None, before: int | None = None, limit: int = PAGE) -> dict:
    async with _S() as s:
        q = select(GcSentence).where(GcSentence.user_id == uid)
        if session_id:
            q = q.where(GcSentence.session_id == session_id)
        if rule:
            rid = catalog.base_id(rule)
            sub = select(GcMark.sentence_id).where(GcMark.user_id == uid, GcMark.rule.like(rid + "%"), GcMark.sentence_id.is_not(None))
            q = q.where(GcSentence.id.in_(sub))
        if before:
            q = q.where(GcSentence.id < before)
        rows = (await s.execute(q.order_by(GcSentence.id.desc()).limit(limit + 1))).scalars().all()
        more = len(rows) > limit
        rows = rows[:limit]
        ids = [x.id for x in rows]
        marks: dict = {}
        if ids:
            for m in (await s.execute(select(GcMark).where(GcMark.user_id == uid, GcMark.sentence_id.in_(ids)).order_by(GcMark.id))).scalars().all():
                marks.setdefault(m.sentence_id, []).append({"id": m.id, "rule": m.rule, "title": _title(m.rule), "quote": m.quote, "fix": m.fix, "why": m.why,
                                                             "conf": m.conf, "severity": m.severity, "family": m.family, "contest": m.contest})
        await s.commit()
    return {"sentences": [{"id": x.id, "session_id": x.session_id, "said": x.said, "fixed": x.fixed, "status": x.status, "contest": x.contest,
                           "created_at": _iso(x.created_at), "marks": marks.get(x.id, [])} for x in rows], "next": rows[-1].id if more and rows else None}


async def contest(uid: str, sentence_id: int, kind: str) -> dict:
    """"I didn't say that" (not_said) or "That's correct English" (is_correct): the sentence's marks stop counting everywhere."""
    if kind not in ("not_said", "is_correct", "none"):
        raise Invalid("kind")
    async with _S() as s:
        sr = await s.get(GcSentence, sentence_id)
        if sr is None or sr.user_id != uid:
            raise NotFound()
        sr.contest = kind
        await s.execute(update(GcMark).where(GcMark.user_id == uid, GcMark.sentence_id == sentence_id).values(contest=kind))
        await _recount(s, uid, sr.session_id)
        await s.commit()
    return {"ok": True}


async def _recount(s, uid: str, sid: int) -> None:
    """Recompute a session's counted marks and per-rule hits from its (un-contested) mark rows; the "opportunities" half of rule_counts is kept."""
    r = (await s.execute(select(GcSession).where(GcSession.id == sid, GcSession.user_id == uid).with_for_update())).scalars().first()
    if r is None:
        return
    rows = (await s.execute(select(GcMark).where(GcMark.user_id == uid, GcMark.session_id == sid, GcMark.contest == "none", GcMark.conf == "sure",
                                                 GcMark.severity == "error"))).scalars().all()
    hits: dict = {}
    fam: dict = {}
    for m in rows:
        hits[m.rule] = hits.get(m.rule, 0) + 1
        fam[m.family] = fam.get(m.family, 0) + 1
    rc = {}
    for k, v in (r.rule_counts or {}).items():
        rc[k] = {"hits": hits.pop(k, 0), "opp": int((v or {}).get("opp", 0))}
    for k, n in hits.items():
        rc[k] = {"hits": n, "opp": 0}
    r.rule_counts = rc
    r.family_counts = fam
    r.marks_error = len(rows)
    if r.words_checked and r.per100 is not None:
        r.per100 = round(100.0 * len(rows) / r.words_checked, 2)


async def delete_session(uid: str, sid: int) -> dict:
    async with _S() as s:
        r = await s.get(GcSession, sid)
        if r is None or r.user_id != uid:
            raise NotFound()
        await s.execute(delete(GcMark).where(GcMark.user_id == uid, GcMark.session_id == sid))
        await s.execute(delete(GcSentence).where(GcSentence.user_id == uid, GcSentence.session_id == sid))
        await s.delete(r)
        await s.commit()
    _held.pop((uid, sid), None)
    return {"ok": True}


async def delete_by_ref(uid: str, key: str) -> None:
    """Deleting a Practice attempt or an interview also deletes the Grammar Coach session made from it (and its sentences)."""
    try:
        async with _S() as s:
            r = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.client_key == key))).scalars().first()
            if r is not None:
                await s.execute(delete(GcMark).where(GcMark.user_id == uid, GcMark.session_id == r.id))
                await s.execute(delete(GcSentence).where(GcSentence.user_id == uid, GcSentence.session_id == r.id))
                await s.delete(r)
                _held.pop((uid, r.id), None)
            await s.commit()
    except Exception as e:
        print(f"[gcoach] delete_by_ref: {type(e).__name__}")


async def delete_all(uid: str) -> dict:
    async with _S() as s:
        await delete_rows(s, [uid])
        await s.commit()
    for k in [k for k in _held if k[0] == uid]:
        _held.pop(k, None)
    return {"ok": True}


async def delete_rows(s, uids: list) -> None:
    """FK-safe delete of every Grammar Coach row for these users, inside the caller's transaction (db.delete_user / admin_wipe_users call it)."""
    for M in (GcMark, GcSentence, GcDrill, GcSession):
        await s.execute(delete(M).where(M.user_id.in_(uids)))


async def export_all(uid: str) -> dict:
    async with _S() as s:
        sess = (await s.execute(select(GcSession).where(GcSession.user_id == uid).order_by(GcSession.id))).scalars().all()
        sents = (await s.execute(select(GcSentence).where(GcSentence.user_id == uid).order_by(GcSentence.id))).scalars().all()
        marks = (await s.execute(select(GcMark).where(GcMark.user_id == uid).order_by(GcMark.id))).scalars().all()
        drills = (await s.execute(select(GcDrill).where(GcDrill.user_id == uid))).scalars().all()
        await s.commit()
    return {"sessions": [_session_json(r) | {"rule_counts": r.rule_counts, "flow": r.flow, "client_key": r.client_key} for r in sess],
            "sentences": [{"id": x.id, "session_id": x.session_id, "said": x.said, "fixed": x.fixed, "status": x.status, "contest": x.contest, "created_at": _iso(x.created_at)} for x in sents],
            "marks": [{"id": m.id, "session_id": m.session_id, "sentence_id": m.sentence_id, "rule": m.rule, "quote": m.quote, "fix": m.fix, "why": m.why, "conf": m.conf,
                       "severity": m.severity, "contest": m.contest, "created_at": _iso(m.created_at)} for m in marks],
            "drills": [{"rule": d.rule, "right": d.right, "wrong": d.wrong, "last_at": _iso(d.last_at)} for d in drills],
            "prefs": await get_prefs(uid)}


# ----------------------------------------------------------------------------- the hub
def _window(rows: list[GcSession]) -> dict:
    checked = sum(r.checked for r in rows)
    clean = sum(r.clean for r in rows)
    words = sum(r.words_checked for r in rows)
    errors = sum(r.marks_error for r in rows)
    srcs = {(r.engine or {}).get("source", "") for r in rows}
    ok = checked >= 6 and words >= 40
    return {"sessions": len(rows), "checked": checked, "clean": clean, "words_checked": words, "errors": errors,
            "per100": round(100.0 * errors / words, 2) if ok else None, "clean_share": round(100.0 * clean / checked) if checked else None,
            "source": srcs.pop() if len(srcs) == 1 else None, "rules_version": RULES_VERSION,
            "level": scoring_band(rows)}


def scoring_band(rows) -> str:
    lv = {r.level for r in rows if r.level}
    return lv.pop() if len(lv) == 1 else None


async def hub(uid: str) -> dict:
    now = _utc()
    d30, d60 = now - dt.timedelta(days=30), now - dt.timedelta(days=60)
    async with _S() as s:
        rows = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.state.in_(("done", "partial")), GcSession.created_at >= d60)
                                .order_by(GcSession.created_at))).scalars().all()
        recent_rows = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.state.in_(("done", "partial")))
                                       .order_by(GcSession.id.desc()).limit(30))).scalars().all()
        drills = (await s.execute(select(GcDrill).where(GcDrill.user_id == uid))).scalars().all()
        await s.commit()
    cur = [r for r in rows if r.created_at >= d30]
    prev = [r for r in rows if r.created_at < d30]
    wc, wp = _window(cur), _window(prev)
    hist = [{"ts": _iso(r.created_at), "words_checked": r.words_checked, "rules": r.rule_counts or {}} for r in reversed(recent_rows)]
    states = scoring.rule_states(hist)
    weeks: dict = {}
    for r in rows:
        k = r.created_at.isocalendar()[:2]
        w = weeks.setdefault(k, [0, 0])
        w[0] += r.marks_error
        w[1] += r.words_checked
    trend = [{"week": f"{k[0]}-W{k[1]:02d}", "per100": round(100.0 * e / w, 2) if w >= 40 else None, "words": w} for k, (e, w) in sorted(weeks.items())][-8:]
    fam: dict = {}
    for r in cur:
        for k, v in (r.family_counts or {}).items():
            fam[k] = fam.get(k, 0) + int(v)
    by_src: dict = {}
    for r in cur:
        by_src[r.source] = by_src.get(r.source, 0) + 1
    focus = scoring.top_focus(states, limit=scoring.focus_limit(wc.get("level") or (recent_rows[0].level if recent_rows else "")))
    mistakes = []
    for k, v in states.items():
        rl = catalog.get(k)
        if v.get("hits", 0) > 0 and (rl is None or rl.severity == "error"):
            mistakes.append({"rule": k, "title": _title(k), "group": rl.group if rl else "", "hits": v["hits"], "state": v.get("state", ""), "regressed": bool(v.get("regressed")),
                             "weight": rl.weight if rl else 1})
    mistakes.sort(key=lambda m: (-m["hits"] * m["weight"], m["rule"]))
    mistaken = {k.split("#")[0] for k, v in states.items() if v.get("hits", 0) > 0 and v.get("state") in ("needs_work", "new", "improving")}
    today = now.date().isoformat()
    practised = {d.rule for d in drills if d.last_at and d.last_at.date().isoformat() == today}
    return {"window": wc, "previous": wp, "delta": scoring.delta(wp, wc), "trend": trend, "families": fam, "by_source": by_src,
            "focus": [{"rule": f["rule"], "title": _title(f["rule"]), "hits": f.get("hits", 0), "state": f.get("state", "")} for f in focus],
            "wins": [{"rule": k, "title": _title(k)} for k, v in states.items() if v.get("state") == "fixed"][:5],
            "best_run": max([r.best_run for r in cur] or [0]), "latest": [_session_json(r) for r in recent_rows[:5]],
            "mistakes": mistakes[:40], "practice_due": len(mistaken - practised), "prefs": await get_prefs(uid), "has_data": bool(recent_rows)}


async def rule_detail(uid: str, rule: str) -> dict:
    r = catalog.get(rule)
    if r is None:
        raise NotFound()
    c = catalog.content(r.id)
    async with _S() as s:
        recent = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.state.in_(("done", "partial"))).order_by(GcSession.id.desc()).limit(30))).scalars().all()
        await s.commit()
    hist = [{"ts": _iso(x.created_at), "words_checked": x.words_checked, "rules": x.rule_counts or {}} for x in reversed(recent)]
    st = scoring.rule_states(hist).get(r.id) or {"state": "unknown", "hits": 0}
    note = await list_notebook(uid, rule=r.id, limit=10)
    return {"rule": r.id, "group": r.group, "severity": r.severity, "weight": r.weight, "cefr_min": r.cefr_min, "content": c, "state": st, "sentences": note["sentences"]}


def rules_index() -> list[dict]:
    out = []
    for r in catalog.RULES.values():
        c = catalog.content(r.id)
        out.append({"rule": r.id, "group": r.group, "title": {"en": catalog.title_of(r.id, "en"), "hi": catalog.title_of(r.id, "hi")}, "severity": r.severity,
                    "weight": r.weight, "cefr_min": r.cefr_min, "starred": r.starred, "rule_text": {"en": (c.get("en") or {}).get("rule", ""), "hi": (c.get("hi") or {}).get("rule", "")}})
    return out


# ----------------------------------------------------------------------------- rule health (auto-demotion) for the analysis and the dashboard
_health_cache: tuple[float, dict] = (0.0, {})


async def rule_health(force: bool = False) -> dict:
    """{rule: {shown, contested}} over every learner's marks (counts only, no text). Cached 10 minutes."""
    global _health_cache
    if not force and _health_cache[0] > time.time() and _health_cache[1] is not None:
        return _health_cache[1]
    try:
        async with _S() as s:
            rows = (await s.execute(select(GcMark.rule, func.count(), func.count().filter(GcMark.contest == "is_correct")).where(GcMark.conf == "sure").group_by(GcMark.rule))).all()
            await s.commit()
        h = {r: {"shown": int(n), "contested": int(c)} for r, n, c in rows}
    except Exception as e:
        print(f"[gcoach] rule_health: {type(e).__name__}")
        h = {}
    _health_cache = (time.time() + 600, h)
    return h


async def contested_rules() -> frozenset:
    """Rules contested ("That's correct English") in > 25 % of >= 20 shows: auto-demoted to soft-only."""
    h = await rule_health()
    return frozenset(r for r, v in h.items() if v["shown"] >= 20 and v["contested"] / max(1, v["shown"]) > 0.25)


# ----------------------------------------------------------------------------- drills
async def record_drills(uid: str, key: str, results: list) -> dict:
    """results: [{rule, ok}]. A rule's row skips a batch whose key equals its last_key (replay-safe)."""
    if not key or len(key) > 64 or not isinstance(results, list):
        raise Invalid("key")
    per: dict = {}
    for it in results[:100]:
        if isinstance(it, dict) and isinstance(it.get("rule"), str) and catalog.get(it["rule"]):
            p = per.setdefault(catalog.base_id(it["rule"]), [0, 0])
            p[0 if it.get("ok") else 1] += 1
    now = _utc()
    applied = 0
    async with _S() as s:
        for rule, (ok, bad) in per.items():
            await s.execute(pg_insert(GcDrill).values(user_id=uid, rule=rule, right=0, wrong=0, streak=0, last_key="").on_conflict_do_nothing(index_elements=["user_id", "rule"]))
            d = (await s.execute(select(GcDrill).where(GcDrill.user_id == uid, GcDrill.rule == rule).with_for_update())).scalars().first()
            if d is None or d.last_key == key:
                continue
            d.right += ok
            d.wrong += bad
            d.streak = (d.streak + ok) if not bad else 0
            d.last_at, d.last_key = now, key
            applied += 1
        mem = await db._get_or_make_memory(s, uid)
        f = dict(mem.facts or {})
        p = dict(f.get("gc_prefs") or {})
        days = [d for d in (p.get("drill_days") or []) if isinstance(d, str)]
        today = now.date().isoformat()
        if applied and today not in days:
            days.append(today)
        p["drill_days"] = days[-60:]
        f["gc_prefs"] = p
        mem.facts = f
        db.flag_modified(mem, "facts")
        await s.commit()
    return {"ok": True, "applied": applied}


async def drill_progress(uid: str) -> dict:
    async with _S() as s:
        rows = (await s.execute(select(GcDrill).where(GcDrill.user_id == uid))).scalars().all()
        await s.commit()
    return {d.rule: {"right": d.right, "wrong": d.wrong, "streak": d.streak} for d in rows}


async def health() -> dict:
    """A few counters for the owner dashboard."""
    try:
        async with _S() as s:
            n = (await s.execute(select(func.count()).select_from(GcSession))).scalar() or 0
            f = (await s.execute(select(func.count()).select_from(GcSession).where(GcSession.state == "failed"))).scalar() or 0
            q = (await s.execute(select(func.count()).select_from(GcSession).where(GcSession.state == "partial"))).scalar() or 0
            await s.commit()
        h = await rule_health()
        noisy = sorted(((r, v) for r, v in h.items() if v["shown"] >= 20), key=lambda kv: -kv[1]["contested"] / max(1, kv[1]["shown"]))[:5]
        return {"sessions": int(n), "failed": int(f), "partial": int(q), "noisy": [{"rule": r, "shown": v["shown"], "contested": v["contested"]} for r, v in noisy]}
    except Exception as e:
        return {"error": type(e).__name__}


async def drill_items(uid: str, rule: str = "", n: int = 5) -> dict:
    """Deterministic drill items (no model): *pick the right one* and *say it right* built from the learner's OWN corrected sentences, topped up
    with the catalogue's drills. A rule is offered when it was recently mistaken and not yet practised today (weakest first)."""
    now = _utc()
    today = now.date().isoformat()
    async with _S() as s:
        q = select(GcMark).where(GcMark.user_id == uid, GcMark.contest == "none", GcMark.conf == "sure", GcMark.severity == "error",
                                 GcMark.sentence_id.is_not(None), GcMark.created_at >= now - dt.timedelta(days=45))
        if rule:
            q = q.where(GcMark.rule.like(catalog.base_id(rule) + "%"))
        marks = (await s.execute(q.order_by(GcMark.id.desc()).limit(200))).scalars().all()
        done = {d.rule for d in (await s.execute(select(GcDrill).where(GcDrill.user_id == uid))).scalars().all() if d.last_at and d.last_at.date().isoformat() == today}
        sent_ids = list({m.sentence_id for m in marks})[:80]
        sents = {x.id: x for x in (await s.execute(select(GcSentence).where(GcSentence.user_id == uid, GcSentence.id.in_(sent_ids)))).scalars().all()} if sent_ids else {}
        await s.commit()
    by_rule: dict = {}
    for m in marks:
        sr = sents.get(m.sentence_id)
        if sr and sr.fixed and sr.contest == "none":
            by_rule.setdefault(catalog.base_id(m.rule), []).append(sr)
    order = sorted(by_rule, key=lambda r: (r in done and not rule, -len(by_rule[r]) * (catalog.get(r).weight if catalog.get(r) else 1)))
    items: list = []
    seen: set = set()
    for r in order:
        for sr in by_rule[r]:
            if sr.id in seen or len(items) >= n:
                continue
            seen.add(sr.id)
            opts = [sr.fixed, sr.said]
            flip = (sr.id % 2) == 1
            if flip:
                opts.reverse()
            if len(items) % 2 == 0:
                items.append({"kind": "pick", "rule": r, "title": _title(r), "prompt": "Which sentence is correct?", "options": opts,
                              "answer": opts.index(sr.fixed), "explain": ""})
            else:
                items.append({"kind": "say", "rule": r, "title": _title(r), "sentence": sr.fixed})
    pool = [rule] if rule else (order or [rid for rid, x in catalog.RULES.items() if x.starred][:6])
    k = 0
    while len(items) < n and pool and k < 40:
        r = catalog.base_id(pool[k % len(pool)])
        drills = (catalog.content(r) or {}).get("drills") or []
        if drills:
            d = drills[(k // len(pool)) % len(drills)]
            items.append({"kind": "pick", "rule": r, "title": _title(r), "prompt": d.get("q", "Which sentence is correct?"), "options": list(d["options"]),
                          "answer": int(d["answer"]), "explain": {"en": d.get("explain_en", ""), "hi": d.get("explain_hi", "")}})
        k += 1
    return {"items": items[:n], "own": sum(1 for i in items if i["kind"] == "say" or i.get("explain") == "")}
