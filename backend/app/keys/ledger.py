"""Keys - the ledger: count every provider attempt, remember what each key last did, flush to Postgres in small batches.

Why in memory first: the walker runs on the hot path of every spoken turn. `begin` / `settle` / `note_*` are dict updates (microseconds); a background loop writes
the deltas every FLUSH_EVERY_S with `INSERT ... ON CONFLICT DO UPDATE SET n = n + excluded.n`, ONE ROW PER TRANSACTION - a row that cannot be written (the learner was
deleted a moment ago: a foreign-key error) is dropped and counted, it never poisons the batch; a row that failed because the database hiccuped is put back.
One uvicorn worker is the deployment, so the in-memory totals are exact; reads (`used_today`) add the not-yet-flushed deltas to what the database holds.

What is counted: every attempt that reached a provider, when it is DISPATCHED (so an attempt that is cancelled mid-flight still counts - the provider received it),
and how it ended: ok / limited / invalid / other (timeouts, 5xx, empty answers, cancellations). Tokens only for the attempts that returned usage.
The day is the PROVIDER's quota day (UTC; Pacific for Gemini) so "used today" lines up with "left today".
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError

from .. import db
from . import classify
from .models import KhStatus, KhUsage

FLUSH_EVERY_S = 5.0
PRUNE_DAYS = 90
MAX_PENDING = 20000
_FIELDS = ("requests", "ok", "limited", "invalid", "other", "tokens_in", "tokens_out")
_BUCKET = {"ok": "ok", "limited": "limited", "invalid": "invalid"}

_usage: dict[tuple, dict] = {}       # (uid, quota day, provider, fp) -> counters since the last flush
_status: dict[tuple, dict] = {}      # (uid, provider, fp) -> columns to upsert (epoch floats; converted at flush)
_seen: dict[tuple, tuple] = {}       # (uid, provider, fp) -> (status, kind, wrote_at): throttles repeat writes
_lock: asyncio.Lock | None = None
state = {"started": None, "flushed": 0, "dropped": 0, "requeued": 0, "last_error": "", "last_flush": None}


def reset_all() -> None:
    """Tests only."""
    _usage.clear(); _status.clear(); _seen.clear()
    for k in ("flushed", "dropped", "requeued"):
        state[k] = 0
    state["last_error"] = ""


# --------------------------------------------------------------------------------------------- counting (hot path: no I/O)
def begin(uid: str | None, provider: str, fp: str, now: float | None = None):
    """Count an attempt at DISPATCH. Returns the token to settle (None when there is no learner to count for)."""
    if not uid:
        return None
    k = (uid, classify.quota_day(provider, time.time() if now is None else now), provider, fp)
    d = _usage.get(k)
    if d is None:
        if len(_usage) >= MAX_PENDING:
            return None
        d = _usage[k] = dict.fromkeys(_FIELDS, 0)
    d["requests"] += 1
    return k


def settle(tok, outcome: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
    """How the attempt ended: 'ok' | 'limited' | 'invalid' | anything else counts as 'other'."""
    if tok is None:
        return
    d = _usage.get(tok)
    if d is None:                       # a flush took the row between begin and settle: counters are additive, a fresh row is fine
        if len(_usage) >= MAX_PENDING:
            return
        d = _usage[tok] = dict.fromkeys(_FIELDS, 0)
    d[_BUCKET.get(outcome, "other")] += 1
    d["tokens_in"] += max(0, int(tokens_in or 0))
    d["tokens_out"] += max(0, int(tokens_out or 0))


def note_ok(uid: str | None, provider: str, fp: str, now: float, rl: dict | None = None, changed: bool = False) -> None:
    """The key just answered. Written at most once a minute (once five minutes without allowance numbers) unless it CHANGED something."""
    if not uid:
        return
    k = (uid, provider, fp)
    prev = _seen.get(k)
    flipped = prev is None or prev[0] != "ok"
    if not (changed or flipped or (now - prev[2]) >= (60 if rl else 300)):
        return
    f = {"status": "ok", "kind": "", "scope": "", "reset_at": None, "evidence": False, "approx": False, "expired": False, "last_http": 200, "last_ok_at": now}
    if changed or flipped:
        f["since"] = now
    if rl:
        f.update(rl_limit=rl["limit"], rl_remaining=rl["remaining"], rl_reset_at=rl.get("reset_at"), rl_at=now)
    if len(_status) < MAX_PENDING:
        _status[k] = {**_status.get(k, {}), **f}
    _seen[k] = ("ok", "", now)


def note_bad(uid: str | None, provider: str, fp: str, status: str, kind: str, now: float, *, scope: str = "", http: int = 0, reset_at: float | None = None,
             evidence: bool = False, approx: bool = False, expired: bool = False) -> None:
    """The key failed in a way that changes what the learner should be told (limited / invalid / forbidden). Repeats within 30 s are not rewritten."""
    if not uid:
        return
    k = (uid, provider, fp)
    prev = _seen.get(k)
    if prev and prev[0] == status and prev[1] == kind and now - prev[2] < 30:
        return
    f = {"status": status, "kind": kind[:16], "scope": scope[:10], "last_http": int(http or 0), "last_error_at": now, "reset_at": reset_at,
         "evidence": bool(evidence), "approx": bool(approx), "expired": bool(expired)}
    if prev is None or prev[0] != status:
        f["since"] = now
    if len(_status) < MAX_PENDING:
        _status[k] = {**_status.get(k, {}), **f}
    _seen[k] = (status, kind, now)


def note_checked(uid: str, provider: str, fp: str, now: float, status: str, kind: str = "", *, http: int = 0, expired: bool = False, meta: dict | None = None,
                 reset_at: float | None = None, evidence: bool = False, approx: bool = False, scope: str = "", rl: dict | None = None) -> None:
    """A PROBE (not a chat turn) looked at the key: always written, it is what 'checked 2 minutes ago' means."""
    k = (uid, provider, fp)
    prev = _seen.get(k)
    f = {"status": status, "kind": kind[:16], "scope": scope[:10], "last_http": int(http or 0), "checked_at": now, "expired": bool(expired),
         "reset_at": reset_at, "evidence": bool(evidence), "approx": bool(approx)}
    if status == "ok":
        f["last_ok_at"] = now
    else:
        f["last_error_at"] = now
    if prev is None or prev[0] != status:
        f["since"] = now
    if meta is not None:
        f["meta"] = meta
    if rl:
        f.update(rl_limit=rl["limit"], rl_remaining=rl["remaining"], rl_reset_at=rl.get("reset_at"), rl_at=now)
    _status[k] = {**_status.get(k, {}), **f}
    _seen[k] = (status, kind, now)


def forget(uid: str) -> None:
    """The learner was deleted (account deletion / the owner's wipe): drop everything pending for them."""
    for d in (_usage, _status, _seen):
        for k in [k for k in d if k[0] == uid]:
            d.pop(k, None)


def forget_key(uid: str, provider: str, fp: str | None = None) -> None:
    """A key was removed or replaced: pending status for it must not resurrect the row."""
    for k in [k for k in _status if k[0] == uid and k[1] == provider and (fp is None or k[2] == fp)]:
        _status.pop(k, None)
    for k in [k for k in _seen if k[0] == uid and k[1] == provider and (fp is None or k[2] == fp)]:
        _seen.pop(k, None)


# --------------------------------------------------------------------------------------------- flushing
def _dt(x):
    return None if x is None else dt.datetime.fromtimestamp(float(x), dt.timezone.utc)


_TS_COLS = ("since", "reset_at", "last_ok_at", "last_error_at", "checked_at", "rl_reset_at", "rl_at")


def _status_values(d: dict) -> dict:
    return {c: (_dt(v) if c in _TS_COLS else v) for c, v in d.items()}


async def _write_usage(k: tuple, d: dict) -> None:
    uid, day, provider, fp = k
    try:
        vals = {f: int(d.get(f, 0)) for f in _FIELDS}
        ins = pg_insert(KhUsage).values(user_id=uid, day=day, provider=provider, fp=fp, **vals)
        ins = ins.on_conflict_do_update(index_elements=["user_id", "day", "provider", "fp"],
                                        set_={f: getattr(KhUsage, f) + ins.excluded[f] for f in _FIELDS})
        async with db._Session() as s:                      # type: ignore[misc]
            await s.execute(ins)
            await s.commit()
        state["flushed"] += 1
    except (IntegrityError, DataError):
        state["dropped"] += 1                               # nobody's row any more (a deleted learner): drop it, never retry it
    except Exception as e:
        state["last_error"] = type(e).__name__
        if len(_usage) < MAX_PENDING:                       # the database hiccuped: the counts are real, put them back
            cur = _usage.setdefault(k, dict.fromkeys(_FIELDS, 0))
            for f in _FIELDS:
                cur[f] += int(d.get(f, 0))
            state["requeued"] += 1
        else:
            state["dropped"] += 1


async def _write_status(k: tuple, d: dict) -> None:
    uid, provider, fp = k
    try:
        vals = _status_values(d)
        ins = pg_insert(KhStatus).values(user_id=uid, provider=provider, fp=fp, **vals)
        ins = ins.on_conflict_do_update(index_elements=["user_id", "provider", "fp"], set_={**vals, "updated_at": db._now()})
        async with db._Session() as s:                      # type: ignore[misc]
            await s.execute(ins)
            await s.commit()
        state["flushed"] += 1
    except (IntegrityError, DataError):
        state["dropped"] += 1
    except Exception as e:
        state["last_error"] = type(e).__name__
        if len(_status) < MAX_PENDING:
            _status[k] = {**d, **_status.get(k, {})}        # whatever is newer wins
            state["requeued"] += 1
        else:
            state["dropped"] += 1


async def flush(uid: str | None = None) -> None:
    """Write what is pending (everything, or one learner's - `/keys/status` flushes the caller's own so the screen is exact)."""
    global _lock
    if not db.db_enabled:
        if uid is None:
            _usage.clear(); _status.clear()
        return
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if uid is None:
            u, st = dict(_usage), dict(_status)
            _usage.clear(); _status.clear()
        else:
            u = {k: v for k, v in _usage.items() if k[0] == uid}
            st = {k: v for k, v in _status.items() if k[0] == uid}
            for k in u:
                _usage.pop(k, None)
            for k in st:
                _status.pop(k, None)
        for k, d in st.items():
            await _write_status(k, d)
        for k, d in u.items():
            await _write_usage(k, d)
        state["last_flush"] = time.time()


async def prune(now: float | None = None) -> int:
    """Usage older than PRUNE_DAYS goes (there is no cron in this stack). Returns the number of rows deleted."""
    if not db.db_enabled:
        return 0
    cutoff = (dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc).date() - dt.timedelta(days=PRUNE_DAYS)).isoformat()
    async with db._Session() as s:                          # type: ignore[misc]
        r = await s.execute(delete(KhUsage).where(KhUsage.day < cutoff))
        await s.commit()
        return int(r.rowcount or 0)


# --------------------------------------------------------------------------------------------- reading
async def used_today(uid: str, now: float | None = None) -> dict:
    """{(provider, fp): {requests, ok, limited, invalid, other, tokens_in, tokens_out}} for each key's CURRENT quota day: what the database holds + what is
    still pending in memory."""
    now = time.time() if now is None else now
    days = sorted({classify.quota_day(p, now) for p in classify.PROVIDERS})
    out: dict = {}
    if db.db_enabled:
        async with db._Session() as s:                      # type: ignore[misc]
            rows = (await s.execute(select(KhUsage).where(KhUsage.user_id == uid, KhUsage.day.in_(days)))).scalars().all()
        for r in rows:
            if r.day == classify.quota_day(r.provider, now):
                out[(r.provider, r.fp)] = {f: int(getattr(r, f) or 0) for f in _FIELDS}
    for (u, day, provider, fp), d in list(_usage.items()):
        if u == uid and day == classify.quota_day(provider, now):
            cur = out.setdefault((provider, fp), dict.fromkeys(_FIELDS, 0))
            for f in _FIELDS:
                cur[f] += d.get(f, 0)
    return out


async def run_forever(periodic: list | None = None) -> None:
    """The flusher: started from the app's startup hook. `periodic` = [(every_seconds, async_fn)] for the slow chores (the server chain's health probe).
    Catches everything and logs the class name only."""
    state["started"] = time.time()
    due = {id(fn): time.monotonic() - every + 30.0 for every, fn in (periodic or [])}      # the first run is 30 s after start-up
    last_prune = 0.0
    while True:
        try:
            await asyncio.sleep(FLUSH_EVERY_S)
            await flush()
            if time.monotonic() - last_prune > 86400:
                last_prune = time.monotonic()
                await prune()
            for every, fn in (periodic or []):
                if time.monotonic() - due[id(fn)] >= every:
                    due[id(fn)] = time.monotonic()
                    try:
                        await fn()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"[keys] periodic failed: {type(e).__name__}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state["last_error"] = type(e).__name__
            print(f"[keys] flush loop: {type(e).__name__}")


def snapshot() -> dict:
    return {**state, "pending_usage": len(_usage), "pending_status": len(_status)}
