"""The detached after-session task (plan section 6, D5): analyse what the learner said, never in the learner's way.

Started from `_persist_session` / `_practice_finish` (Face-to-Face, Interview Prep, Practice conversations - from the server's own transcript) and
from `/gcoach/analyze` (recorded Practice, Job Interview Practice). A module-level set keeps the tasks alive; each one catches everything and logs
class names only (a provider error can echo the request, which is a learner's words). The BYOK keys follow into the task because a task copies
the context of the code that created it - always create it AFTER `set_active_keys`.
"""

from __future__ import annotations

import asyncio
import time

from ..providers import llm
from . import budget as B, engine, gating, segment, service as svc

_tasks: set = set()
_day: dict[str, tuple[str, int]] = {}                 # uid -> (IST day, AI calls today): the per-learner daily budget


def spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def drain(timeout: float = 30.0) -> None:
    """Wait for the running tasks (tests, shutdown)."""
    if _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)


def _make_charge(email: str, uid: str):
    async def charge() -> None:
        from .. import main as M
        snap = await M.charge_request(email, uid, M._quota_day())          # ONE request per session analysis, however many calls it takes
        if not snap.get("allowed", True):
            raise svc.QuotaExceeded()
    return charge


async def _calls_left(email: str, uid: str) -> int:
    """Today's AI-call allowance for this learner. BYOK / unlimited accounts spend their own free tiers and skip the daily cap."""
    try:
        from .. import main as M
        if await M.is_unlimited(email):
            return B.SESSION_CALLS
        day = M._quota_day()
    except Exception:
        return B.SESSION_CALLS
    d, n = _day.get(uid, (day, 0))
    if d != day:
        n = 0
    return max(0, min(B.SESSION_CALLS, B.DAILY_CALLS - n))


def _count_calls(uid: str, n: int) -> None:
    try:
        from .. import main as M
        day = M._quota_day()
    except Exception:
        return
    d, c = _day.get(uid, (day, 0))
    _day[uid] = (day, (c if d == day else 0) + n)
    if len(_day) > 5000:
        _day.clear()


def has_english(turns: list[dict], source: str, name: str = "") -> bool:
    """Cheap pure pre-check so a Hindi (or empty) session never creates a row."""
    for t in turns:
        for s in segment.segment(t.get("text", ""), turn=int(t.get("turn", 0)), source=source, conf=t.get("conf"), hints=t.get("hints")):
            if gating.sentence_gate(s, name=name).ok:
                return True
    return False


async def _level_of(uid: str) -> str:
    try:
        from .. import db
        return (await db.interview_context(uid)).get("level") or ""
    except Exception:
        return ""


async def run(uid: str, email: str, *, source: str, kind: str, key: str, turns: list[dict], engine_src: str, name: str = "", duration_sec: int = 0,
              prev_lines: dict | None = None, level: str | None = None, fb: str | None = None) -> dict | None:
    """Claim -> analyse -> persist. Returns {"id", "state"} or None. Never raises."""
    try:
        if not turns or not has_english(turns, engine_src, name):
            return None
        lvl = level if level is not None else await _level_of(uid)
        sid, st, stamp = await svc.claim(uid, source, kind, key, lvl)
        if st != "run":
            return {"id": sid, "state": st}
    except Exception as e:
        print(f"[gcoach] claim {type(e).__name__}")
        return None
    try:
        from ..resume_interview import docs
        prefs = await svc.get_prefs(uid)
        contested = await svc.contested_rules()
        bud = B.Budget(session_calls=await _calls_left(email, uid))
        t0 = time.monotonic()
        analysis = await engine.analyze(llm, turns, level=lvl, feedback_lang=fb or prefs["feedback_lang"], source=engine_src, name=name, bud=bud,
                                        charge=_make_charge(email, uid), prev_lines=prev_lines, contested=contested, duration_sec=duration_sec)
        _count_calls(uid, bud.calls)
        out = await svc.persist(uid, sid, stamp, analysis, duration_sec=duration_sec, redact=docs.redact_light)
        print(f"[gcoach] {source} {int((time.monotonic() - t0) * 1000)}ms calls={bud.calls} state={out.get('state', 'stale')}")
        return out
    except asyncio.CancelledError:
        await svc.fail(uid, sid, stamp)
        raise
    except Exception as e:
        print(f"[gcoach] analyse {type(e).__name__}")
        await svc.fail(uid, sid, stamp)
        return None


# ----------------------------------------------------------------------------- entry points
def turns_from_session(session) -> tuple[list[dict], dict]:
    """The learner's lines of an in-memory Session transcript (complete, includes lines whose reply failed) + the DuSu line before each."""
    turns, prev, last_ai = [], {}, ""
    n = 0
    for m in session.transcript:
        if m.get("role") == "assistant":
            last_ai = str(m.get("content") or "")
        elif m.get("role") == "user":
            n += 1
            turns.append({"turn": n, "text": str(m.get("content") or ""), "conf": None})
            if last_ai:
                prev[n] = last_ai
    return turns, prev


def schedule_ws(uid: str, email: str, gref: str, session, *, secs: int = 0, attempt_id=None) -> None:
    """Fire-and-forget from `_persist_session` (conversation / interview) and `_practice_finish` (practice conversations)."""
    mode = getattr(session, "mode", "")
    if mode == "interview":
        source, kind = "interview", ""
    elif mode == "practice":
        source, kind = "practice", str((getattr(session, "practice", None) or {}).get("kind", ""))[:32]
    elif mode == "conversation":
        source, kind = "talk", ""
    else:
        return
    if not gating.session_gate(mode, (getattr(session, "practice", None) or {}).get("plang"), getattr(session, "lang", "en")).ok:
        return
    key = f"pa:{int(attempt_id)}" if (mode == "practice" and attempt_id) else (f"ws:{gref}" if gref else "")
    if not key:
        return
    turns, prev = turns_from_session(session)
    spawn(run(uid, email, source=source, kind=kind, key=key, turns=turns, engine_src="chrome", name=getattr(session, "name", "") or "",
              duration_sec=secs, prev_lines=prev))


def valid_gref(v) -> str:
    v = str(v or "").strip()
    return v if 8 <= len(v) <= 40 and all(c.isalnum() or c in "-_" for c in v) else ""
