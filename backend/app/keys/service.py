"""Keys - every read and write, scoped to the signed-in learner. The only place that touches `user_keys` for the new endpoints.

status_payload   what the Keys screen, the Home card and `/me.keys` show: per stored key a MASKED value (never the key), its status, when it began, when a limit
                 ends (only with provider evidence, or marked "about" when it is the published daily rule), what was used today and what is left (exact only where
                 the provider reports it - Groq; computed and marked so for OpenRouter's documented free cap; unknown for Gemini, which has no quota API).
verify_and_save  one key: a zero-quota auth probe, then ONE real call, then a race-safe MERGE into the sealed blob - an empty box or a second key can never wipe
                 the others. A key the provider rejects is never stored.
remove_key / recheck / export_all / delete_rows   the rest of the learner's rights over their own keys.

The stored blob is the source of truth (resolve_keys in main.py reads it first); this module never returns key text except through db.get_user_keys's existing
caller (`/keys/get`, kept for the phone-side Groq Whisper key).
"""

from __future__ import annotations

import asyncio
import json
import random
import time

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import db
from . import classify, gate, ledger, probe
from .models import KY_TABLES, KhStatus, KhUsage

PROVIDERS = classify.PROVIDERS
MIN_KEYS = db.MIN_STORED_KEYS                  # 2: keys needed to START (at runtime one working key keeps DuSu going)
OPENROUTER_FREE_DAILY = 50                     # OpenRouter's documented cap on :free models for an account that never bought credits ...
OPENROUTER_PAID_DAILY = 1000                   # ... and with at least $10 of credits
RECHECK_AFTER_S = 12 * 3600
RECHECK_EVERY_S = 6 * 3600                     # at most one background re-check per learner this often


def _ts(x):
    return None if x is None else int(x.timestamp())


# --------------------------------------------------------------------------------------------- the stored keys
async def stored_keys(uid: str | None) -> dict:
    """{provider: key} for the three providers a learner can bring (a legacy 'github' entry is ignored)."""
    if not (uid and db.db_enabled):
        return {}
    try:
        raw = await db.get_user_keys(uid)
    except Exception:
        return {}
    return {p: str(raw.get(p) or "").strip() for p in PROVIDERS if str(raw.get(p) or "").strip()}


async def _locked_update(uid: str, mutate) -> tuple[dict, dict]:
    """Read-modify-write of the sealed key blob under a ROW LOCK, so two saves at once (two tabs, two phones) cannot lose one another. Returns (before, after)."""
    async with db._Session() as s:                      # type: ignore[misc]
        await s.execute(pg_insert(db.UserKey).values(user_id=uid, blob="", verified=False).on_conflict_do_nothing(index_elements=["user_id"]))
        row = (await s.execute(select(db.UserKey).where(db.UserKey.user_id == uid).with_for_update())).scalar_one()
        try:
            cur = json.loads(db._unseal(row.blob)) if row.blob else {}
        except Exception:
            cur = {}
        before = {k: str(v).strip() for k, v in (cur or {}).items() if isinstance(k, str) and str(v or "").strip()}
        after = {k: v for k, v in mutate(dict(before)).items() if v}
        row.blob = db._seal(json.dumps(after)) if after else ""
        row.verified = sum(1 for p in PROVIDERS if after.get(p)) >= MIN_KEYS
        row.updated_at = db._now()
        await s.commit()
        return before, after


# --------------------------------------------------------------------------------------------- what a key's status is RIGHT NOW
def _from_gate(g) -> dict:
    credit = g.status == "limited" and g.scope == "credit"
    until = g.until if g.status in ("limited", "forbidden") else None
    return {"status": g.status, "kind": "needs_credit" if credit else g.kind, "scope": "" if credit else g.scope, "since": int(g.since), "reset_at": int(g.reset_at) if g.reset_at else None,
            "evidence": g.evidence, "approx": g.approx, "expired": g.expired, "until": until}


def _from_row(r) -> dict:
    return {"status": r.status, "kind": r.kind or "", "scope": r.scope or "", "since": _ts(r.since), "reset_at": _ts(r.reset_at), "evidence": bool(r.evidence),
            "approx": bool(r.approx), "expired": bool(r.expired), "until": None}


def _limited_until(c: dict) -> float | None:
    if c.get("until"):
        return c["until"]
    since = c.get("since") or 0
    if c["status"] == "forbidden":
        return since + gate.FORBIDDEN_S
    if c.get("evidence") and c.get("reset_at"):
        return c["reset_at"]
    return since + (90 if c.get("scope") in ("minute", "upstream") else 1800)


def effective(provider: str, fp: str, row, now: float) -> dict:
    """The status to SHOW for one stored key: the live gate if it knows something newer than the saved row, else the saved row, else 'unknown'. A limit that has
    run its course reads as ok (the next call - or a background re-check - confirms it)."""
    g = gate.get(provider, fp)
    cand = None
    if g is not None and g.status != "ok":
        if row is None or (row.since is None) or g.since >= row.since.timestamp() - 1:
            cand = _from_gate(g)
    if cand is None and row is not None:
        cand = _from_row(row)
    if cand is None:
        return {"status": "unknown", "kind": "", "scope": "", "since": None, "reset_at": None, "evidence": False, "approx": False, "expired": False, "stale": False}
    cand["stale"] = False
    if cand["status"] in ("limited", "forbidden"):
        until = _limited_until(cand)
        if until is not None and now > until:
            cand.update(status="ok", kind="", scope="", reset_at=None, stale=True)
    if cand["status"] == "ok":
        cand["reset_at"] = None
    return cand


def _allowance(provider: str, row, used: int, now: float) -> dict:
    if provider == "groq" and row is not None and row.rl_limit is not None and row.rl_remaining is not None:
        if row.rl_reset_at is None or row.rl_reset_at.timestamp() > now:
            return {"kind": "exact", "limit": int(row.rl_limit), "left": int(row.rl_remaining), "reset_at": _ts(row.rl_reset_at), "as_of": _ts(row.rl_at)}
        return {"kind": "unknown"}                              # the reading is older than its own reset: no number is better than a wrong one
    if provider == "openrouter":
        free = ((row.meta or {}).get("is_free_tier") if row is not None else None)
        cap = OPENROUTER_PAID_DAILY if free is False else OPENROUTER_FREE_DAILY
        return {"kind": "computed", "limit": cap, "left": max(0, cap - int(used)), "reset_at": int(classify.quota_day_end("openrouter", now))}
    return {"kind": "unknown"}                                   # Gemini has no quota API; DuSu says so rather than guess


def _state_of(stored: int, working: int, limited: int, invalid: int, unknown: int) -> str:
    if stored == 0:
        return "no_keys"
    if working >= 1:
        return "ok" if (limited + invalid) == 0 else "degraded"
    if unknown >= 1:
        return "unknown"
    return "all_invalid" if invalid == stored else "all_limited"


async def status_payload(uid: str, now: float | None = None, schedule: bool = True) -> dict:
    """The full, masked status of the learner's own keys (see the module docstring). Never contains key text."""
    now = time.time() if now is None else now
    stored = await stored_keys(uid)
    rows = {}
    if stored and db.db_enabled:
        async with db._Session() as s:                  # type: ignore[misc]
            for r in (await s.execute(select(KhStatus).where(KhStatus.user_id == uid))).scalars().all():
                rows[(r.provider, r.fp)] = r
    used = await ledger.used_today(uid, now) if stored else {}
    keys, w, l, i, u, total, resets, need_check = [], 0, 0, 0, 0, 0, [], False
    for p in PROVIDERS:
        key = stored.get(p)
        if not key:
            continue
        fp = gate.fingerprint(p, key)
        row = rows.get((p, fp))
        e = effective(p, fp, row, now)
        n = used.get((p, fp), {})
        total += int(n.get("requests", 0))
        if row is None or row.checked_at is None or now - row.checked_at.timestamp() > RECHECK_AFTER_S or e["stale"]:
            need_check = True
        st = e["status"]
        if st == "ok":
            w += 1
        elif st == "invalid":
            i += 1
        elif st in ("limited", "forbidden"):
            l += 1
            if e.get("reset_at") and e["reset_at"] > now:
                resets.append(e["reset_at"])
        else:
            u += 1
        keys.append({"provider": p, "masked": gate.mask(key), "status": st, "kind": e["kind"], "scope": e["scope"], "since": e["since"], "reset_at": e["reset_at"],
                     "approx": e["approx"], "expired": e["expired"], "checked_at": _ts(row.checked_at) if row is not None else None,
                     "last_ok_at": _ts(row.last_ok_at) if row is not None else None,
                     "used_today": {"requests": int(n.get("requests", 0)), "ok": int(n.get("ok", 0)), "limited": int(n.get("limited", 0)),
                                    "invalid": int(n.get("invalid", 0)), "other": int(n.get("other", 0))},
                     "allowance": _allowance(p, row, int(n.get("requests", 0)), now)})
    if need_check and schedule:
        schedule_recheck(uid)
    return {"now": int(now), "min": MIN_KEYS, "providers": list(PROVIDERS), "stored": len(keys), "working": w, "limited": l, "invalid": i, "unknown": u,
            "state": _state_of(len(keys), w, l, i, u), "used_today": total, "next_reset_at": min(resets) if resets else None, "keys": keys}


async def me_summary(uid: str, now: float | None = None) -> dict:
    """The compact form `/me.keys` carries (no per-key details): counts, the headline state, the soonest reset, today's requests."""
    p = await status_payload(uid, now)
    return {k: p[k] for k in ("min", "stored", "working", "limited", "invalid", "unknown", "state", "used_today", "next_reset_at")}


# --------------------------------------------------------------------------------------------- save / remove / re-check
async def verify_and_save(uid: str, provider: str, key: str) -> dict:
    """Check ONE key against its provider and, if the provider accepts it, MERGE it into the learner's stored keys."""
    from ..providers import openrouter_provider as op
    now = time.time()
    fp = gate.fingerprint(provider, key)
    pr = await probe.auth_probe(provider, key, now)
    if pr.kind in ("invalid", "forbidden"):
        return {"ok": False, "result": {"provider": provider, "status": pr.kind, "expired": pr.expired}}
    if pr.kind not in ("ok", "limited"):
        return {"ok": False, "result": {"provider": provider, "status": "unreachable"}}      # could not check: nothing is stored on a guess
    status, kind, out, rl = "ok", "", None, None
    if pr.kind == "ok":
        cp = await probe.chat_probe(provider, key, uid, now)             # a key can authenticate and still not chat; and it tells us the allowance
        if cp.kind in ("invalid", "forbidden"):
            return {"ok": False, "result": {"provider": provider, "status": cp.kind, "expired": cp.expired}}
        if cp.kind == "limited":
            status, kind, out = "limited", "limited", cp.out
        rl = cp.rl
    else:
        status, kind, out = "limited", "limited", pr.out
    before, _after = await _locked_update(uid, lambda d: {**d, provider: key})
    old = before.get(provider)
    if old and old != key:                                               # a REPLACED key: forget the old one everywhere
        op.evict_client(provider, old)
        ledger.forget_key(uid, provider, gate.fingerprint(provider, old))
    async with db._Session() as s:                                       # type: ignore[misc]
        await s.execute(delete(KhStatus).where(KhStatus.user_id == uid, KhStatus.provider == provider, KhStatus.fp != fp))
        await s.commit()
    gate.clear(provider, fp)                                             # freshly verified: whatever the gate believed about this key is stale
    reset_at = evidence = approx = scope = None
    if out is not None:
        reset_at, evidence, approx, scope = out.reset_at, out.evidence, out.approx, out.scope
        gate.mark_limited(provider, fp, now, classify.limit_seconds(out), scope=out.scope, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx, http=out.http)
    ledger.note_checked(uid, provider, fp, now, status, kind, http=(out.http if out else 200), meta=pr.meta or None, reset_at=reset_at, evidence=bool(evidence),
                        approx=bool(approx), scope=scope or "", rl=rl)
    await ledger.flush(uid)
    return {"ok": True, "result": {"provider": provider, "status": status, "masked": gate.mask(key)}, "status": await status_payload(uid, schedule=False)}


async def remove_key(uid: str, provider: str) -> dict:
    from ..providers import openrouter_provider as op
    before, _after = await _locked_update(uid, lambda d: {k: v for k, v in d.items() if k != provider})
    old = before.get(provider)
    if old:
        op.evict_client(provider, old)
    ledger.forget_key(uid, provider)
    async with db._Session() as s:                                       # type: ignore[misc]
        await s.execute(delete(KhStatus).where(KhStatus.user_id == uid, KhStatus.provider == provider))
        await s.commit()
    return await status_payload(uid, schedule=False)


async def recheck(uid: str, provider: str | None = None, deep: bool = False) -> dict:
    """Look at the stored keys again. Shallow = the zero-quota auth probe (is the key still accepted?); `deep` also makes one real call (Test). A key that is
    LIMITED stays limited until its time is up - an auth probe passing proves it is real, not that the limit ended. Returns the fresh status payload."""
    now = time.time()
    stored = await stored_keys(uid)
    rows = {}
    if stored and db.db_enabled:
        async with db._Session() as s:                  # type: ignore[misc]
            for r in (await s.execute(select(KhStatus).where(KhStatus.user_id == uid))).scalars().all():
                rows[(r.provider, r.fp)] = r
    results = {}
    for p in PROVIDERS:
        key = stored.get(p)
        if not key or (provider and p != provider):
            continue
        fp = gate.fingerprint(p, key)
        cur = effective(p, fp, rows.get((p, fp)), now)
        pr = await probe.auth_probe(p, key, now)
        if pr.kind not in ("ok", "invalid", "forbidden", "limited"):
            results[p] = "unreachable"                                   # no verdict: nothing changes
            continue
        status, out, rl, meta = pr.kind, pr.out, None, (pr.meta or None)
        if pr.kind == "ok" and deep:
            cp = await probe.chat_probe(p, key, uid, now)
            rl = cp.rl
            if cp.kind in ("invalid", "forbidden", "limited"):
                status, out = cp.kind, cp.out
        if status == "ok" and cur["status"] in ("limited", "forbidden") and not cur.get("stale") and not deep:
            status, out = cur["status"], None                            # the key is real, its limit is not over: keep what we knew
        if status == "ok":
            gate.clear(p, fp)
            ledger.note_checked(uid, p, fp, now, "ok", "", http=200, meta=meta, rl=rl)
        elif status == "invalid":
            gate.mark_invalid(p, fp, now, http=(out.http if out else 401), expired=bool(out and out.expired))
            ledger.note_checked(uid, p, fp, now, "invalid", "invalid", http=(out.http if out else 401), expired=bool(out and out.expired), meta=meta)
        elif status == "forbidden":
            gate.mark_forbidden(p, fp, now, http=(out.http if out else 403))
            ledger.note_checked(uid, p, fp, now, "forbidden", "forbidden", http=(out.http if out else 403), meta=meta)
        else:                                                            # limited
            if out is not None:
                gate.mark_limited(p, fp, now, classify.limit_seconds(out), scope=out.scope, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx, http=out.http)
                ledger.note_checked(uid, p, fp, now, "limited", "limited", http=out.http, scope=out.scope, reset_at=out.reset_at, evidence=out.evidence,
                                    approx=out.approx, meta=meta)
            else:
                ledger.note_checked(uid, p, fp, now, "limited", cur.get("kind") or "limited", scope=cur.get("scope") or "", reset_at=cur.get("reset_at"),
                                    evidence=bool(cur.get("evidence")), approx=bool(cur.get("approx")), meta=meta)
        results[p] = status
    await ledger.flush(uid)
    payload = await status_payload(uid, schedule=False)
    payload["checked"] = results
    return payload


# --------------------------------------------------------------------------------------------- the lazy background re-check
_bg: set = set()
_bg_sem: asyncio.Semaphore | None = None
_last_sched: dict[str, float] = {}


def schedule_recheck(uid: str) -> None:
    """A key we have not looked at for 12 hours (or never - a legacy key): re-check it in the background, jittered, two at a time, at most one run per learner
    every 6 hours. Fire-and-forget: the answer arrives with the next `/keys/status`."""
    if not (uid and db.db_enabled):
        return
    now = time.monotonic()
    if now - _last_sched.get(uid, -1e9) < RECHECK_EVERY_S:
        return
    if len(_last_sched) > 5000:
        for k in sorted(_last_sched, key=_last_sched.get)[:1000]:
            _last_sched.pop(k, None)
    _last_sched[uid] = now
    try:
        t = asyncio.get_running_loop().create_task(_bg_recheck(uid))
    except RuntimeError:
        return
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def _bg_recheck(uid: str) -> None:
    global _bg_sem
    if _bg_sem is None:
        _bg_sem = asyncio.Semaphore(2)
    await asyncio.sleep(random.uniform(0.0, 3.0))
    async with _bg_sem:
        try:
            out = await recheck(uid, None, deep=False)
            if out.get("unknown"):                                            # a provider could not be reached: look again in 5 minutes, not in 6 hours
                _last_sched[uid] = time.monotonic() - (RECHECK_EVERY_S - 300)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[keys] background re-check: {type(e).__name__}")


# --------------------------------------------------------------------------------------------- the learner's rights
async def export_all(uid: str) -> dict:
    """Everything this feature knows about the learner. The keys themselves are never exported (the learner has them; DuSu keeps them sealed)."""
    async with db._Session() as s:                      # type: ignore[misc]
        st = (await s.execute(select(KhStatus).where(KhStatus.user_id == uid))).scalars().all()
        us = (await s.execute(select(KhUsage).where(KhUsage.user_id == uid).order_by(KhUsage.day.desc()))).scalars().all()
    return {"note": "Your API keys are not included - DuSu keeps them sealed and only uses them to answer you.",
            "keys": [{"provider": r.provider, "status": r.status, "kind": r.kind, "since": _ts(r.since), "last_ok_at": _ts(r.last_ok_at), "checked_at": _ts(r.checked_at)} for r in st],
            "usage": [{"day": r.day, "provider": r.provider, "requests": r.requests, "ok": r.ok, "limited": r.limited, "invalid": r.invalid, "other": r.other,
                       "tokens_in": r.tokens_in, "tokens_out": r.tokens_out} for r in us]}


async def delete_rows(s, uids: list) -> None:
    """Delete every key-health row for these learners, inside the caller's transaction (account deletion and the owner's wipe call this)."""
    for M in KY_TABLES:
        await s.execute(delete(M).where(M.user_id.in_(uids)))
    for u in uids:
        ledger.forget(u)
