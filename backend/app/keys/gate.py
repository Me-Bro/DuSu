"""Keys - the per-key circuit breaker.

Keyed `(provider, fingerprint)`, NOT by provider name: the old cooldown map was keyed by provider name for the whole process, so one learner's rate limit made
every other learner skip that provider (and switched Grammar Coach off for all). A key's limit is that key's limit; two learners only share a gate when they
paste the very same key.

States: ok (no entry or `ok`) / limited (skip until `until`) / invalid (skip until re-added, re-checked, or INVALID_RECHECK_S) / forbidden (short skip).
When a gate expires the NEXT caller gets one half-open probe (`verdict == "probe"`) and everyone else keeps skipping until that probe settles - concurrent
callers can never hammer a key that is limited. When EVERY key of a chain is gated the walker may still ask for `soonest_probe` (one request per key per
PROBE_GAP_S) so a limit that ended early is noticed instead of being served 'limited' for the full 90 s.

In-memory by design (one uvicorn worker). A restart forgets the gates; the first call re-learns a dead key with ONE wasted request. The per-learner status that
the Keys screen shows is persisted separately (ledger.py -> kh_status).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

INVALID_RECHECK_S = 6 * 3600
FORBIDDEN_S = 300
PROBE_GAP_S = 60
INFLIGHT_STALE_S = 90               # a probe that never reported back (a bug, a killed task) must not gate a key forever
MAX_ENTRIES = 20000                 # the map is bounded: a long-running process must not grow it forever
MODEL_GONE_S = 1800                 # a model that answered 404 ("no such model / no endpoints") is not asked again for 30 minutes (per key)
MAX_MODEL_ENTRIES = 5000
BAD_BASE_S = 20.0                   # a model whose reply was unusable (not JSON, a missing field, empty, cut off) is not asked again for 20 s ...
BAD_MAX_S = 600.0                   # ... then 40 s, 80 s ... up to 10 minutes while it keeps failing; one good reply clears it
BAD_FORGET_S = 1800.0               # no new strike for this long: the next one counts as the first again
MAX_BAD_ENTRIES = 5000
PARAM_UNSUPPORTED_S = 6 * 3600      # a model that answered 400 to our extra request parameters (reasoning_effort ...) is sent without them for 6 hours
MAX_PARAM_ENTRIES = 500
BREAKER_AFTER = 3                   # consecutive TRANSIENT failures (a timeout, a 5xx, a connection error) of one model that open its breaker ...
BREAKER_BASE_S = 60.0               # ... for 60 s, then one probe; a probe that fails doubles it (120 s, 240 s) up to 5 minutes
BREAKER_MAX_S = 300.0
HEALTH_PRIOR = 0.9                  # what a model nobody has measured is assumed to be worth (a measured-good model outranks it, a measured-bad one does not)
HEALTH_ALPHA = 0.15                 # how fast the success rate follows what just happened (two unusable replies in a row from a fresh model drop it a band)
HEALTH_STALE_S = 600.0              # a reading this old drifts back toward the prior - so a provider that was demoted but is no longer asked is tried first again within about 40 minutes
HEALTH_BAND = 4                     # providers are ordered by score in this many bands, so two close scores keep their configured order (no flapping)
MAX_HEALTH_ENTRIES = 2000


@dataclass
class KeyState:
    status: str = "ok"              # ok | limited | invalid | forbidden
    kind: str = ""                  # the classifier kind that put it there
    scope: str = ""                 # limited: minute | day | upstream | ""
    since: float = 0.0
    until: float = 0.0              # skip until (epoch); 0 = not gated
    reset_at: float | None = None   # when the provider says (or its published rule says) the limit ends - display only
    evidence: bool = False
    approx: bool = False
    expired: bool = False
    http: int = 0
    probe_at: float = 0.0           # earliest next early probe when every key of a chain is gated
    inflight: bool = False          # a half-open probe is running
    inflight_at: float = 0.0


_state: dict[tuple[str, str], KeyState] = {}
# The same idea one level down, for the providers that limit PER MODEL (Gemini, Groq): (provider, fingerprint, model) -> why this ONE model is skipped for now
# ("limited" = its own bucket is empty, "gone" = the provider answered 404). Keyed by the key too: a 404 can come from one key's own settings (OpenRouter's
# "free endpoints" privacy switch), so it must never make a model look dead for everyone.
_models: dict[tuple[str, str, str], KeyState] = {}


@dataclass
class BadState:
    """A model whose reply was UNUSABLE for one class of call ("json" = a structured turn, "chat" = prose): the answer came back but could not be used. Not a limit, not
    a dead key - a quality failure, so it is remembered apart from `_models` and per call CLASS (a model that writes fine prose may still break JSON)."""
    strikes: int = 0
    since: float = 0.0
    until: float = 0.0
    last_at: float = 0.0
    reason: str = ""


_bad: dict[tuple[str, str, str, str], BadState] = {}        # (provider, fingerprint, model, class) -> why it is skipped for now
_noparam: dict[tuple[str, str], float] = {}                 # (provider, model) -> until: it answered 400 to our extra request parameters; send it plain


@dataclass
class Health:
    """How one MODEL is doing as a service (not one learner's key): shared by everyone, because a timeout or a 5xx is the provider's, not the key's."""
    ok: float = HEALTH_PRIOR        # smoothed share of its replies that were usable
    ms: float = 0.0                 # smoothed time of its answers (ms); 0 = nobody measured yet
    n: int = 0
    consec: int = 0                 # transient failures in a row
    opened: int = 0                 # times the breaker opened in a row (each one doubles the hold)
    until: float = 0.0              # breaker open until (epoch); 0 = closed
    last_at: float = 0.0
    inflight: bool = False          # a half-open probe is running
    inflight_at: float = 0.0


_health: dict[tuple[str, str, str], Health] = {}            # (provider, model, class)


def reset_all() -> None:
    """Tests only."""
    _state.clear()
    _models.clear()
    _bad.clear()
    _noparam.clear()
    _health.clear()


# --------------------------------------------------------------------------------------------- fingerprints and masks
def fingerprint(provider: str, key: str) -> str:
    """Stable and not reversible: HMAC(server secret, provider|key)[:12]. Identifies a key in the gate, the ledger and the status rows without ever storing it."""
    from ..db import _KEYS_SECRET
    return hmac.new(_KEYS_SECRET, f"{provider}|{key}".encode("utf-8"), hashlib.sha256).hexdigest()[:12]


_PREFIXES = ("sk-or-v1-", "sk-or-", "gsk_", "AIza", "AQ.")


def mask(key: str) -> str:
    """'gsk_abcdef...9fA2' -> 'gsk_••••9fA2'. Never more than the provider's own prefix and the last four characters."""
    k = str(key or "").strip()
    if len(k) < 12:
        return "••••" + k[-2:] if len(k) > 4 else "••••"
    pre = next((p for p in _PREFIXES if k.startswith(p)), k[:3])
    return f"{pre}••••{k[-4:]}"


def clean_key(provider: str, raw) -> str | None:
    """The key as it may be stored, or None when it cannot be a key at all (empty, spaces inside, control characters, absurd length). Does NOT judge
    whether the provider accepts it - only the provider can say that."""
    if not isinstance(raw, str):
        return None
    k = raw.strip()
    if not (8 <= len(k) <= 400):
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in k):
        return None
    return k


# --------------------------------------------------------------------------------------------- the gate
def get(provider: str, fp: str) -> KeyState | None:
    return _state.get((provider, fp))


def peek(provider: str, fp: str, now: float) -> str:
    """Like `verdict` but changes nothing (no probe slot is taken): 'go' | 'probe' (the gate expired and nobody holds the slot) | 'skip'."""
    st = _state.get((provider, fp))
    if st is None or st.status == "ok":
        return "go"
    if now < st.until:
        return "skip"
    if st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    return "probe"


def verdict(provider: str, fp: str, now: float) -> str:
    """'go' (not gated) | 'probe' (the gate expired and THIS caller is the one half-open probe) | 'skip'."""
    st = _state.get((provider, fp))
    if st is None or st.status == "ok":
        return "go"
    if now < st.until:
        return "skip"
    if st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    st.inflight, st.inflight_at = True, now
    return "probe"


def soonest_probe(candidates: list, now: float) -> tuple[str, str] | None:
    """Every key of the chain is gated and none has expired: the LIMITED one that ends soonest may take ONE early probe (at most one a minute). Invalid and
    forbidden keys never do (they cannot recover on their own)."""
    best, best_until = None, None
    for provider, fp in candidates:                           # ONE probe in flight per chain: while one runs, nobody else starts another
        st = _state.get((provider, fp))
        if st is not None and st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
            return None
    for provider, fp in candidates:
        st = _state.get((provider, fp))
        if st is None or st.status != "limited" or now < st.probe_at:
            continue
        if best is None or st.until < best_until:
            best, best_until = (provider, fp), st.until
    if best is None:
        return None
    st = _state[best]
    st.inflight, st.inflight_at = True, now
    st.probe_at = now + PROBE_GAP_S
    return best


def _put(provider: str, fp: str, st: KeyState) -> KeyState:
    if len(_state) >= MAX_ENTRIES and (provider, fp) not in _state:
        for k in sorted(_state, key=lambda k: _state[k].until)[:MAX_ENTRIES // 10]:     # the entries that end soonest go first
            _state.pop(k, None)
    _state[(provider, fp)] = st
    return st


def mark_ok(provider: str, fp: str, now: float) -> bool:
    """A call succeeded: the key is fine. Returns True when that CHANGED something (it was limited / invalid before)."""
    st = _state.get((provider, fp))
    if st is None:
        return False
    changed = st.status != "ok"
    _state.pop((provider, fp), None)
    return changed


def mark_limited(provider: str, fp: str, now: float, seconds: float, *, scope: str = "", reset_at: float | None = None, evidence: bool = False,
                 approx: bool = False, http: int = 429) -> KeyState:
    return _put(provider, fp, KeyState(status="limited", kind="limited", scope=scope, since=now, until=now + max(1.0, float(seconds)), reset_at=reset_at,
                                       evidence=evidence, approx=approx, http=http, probe_at=now + PROBE_GAP_S))


def mark_invalid(provider: str, fp: str, now: float, *, http: int = 401, expired: bool = False) -> KeyState:
    return _put(provider, fp, KeyState(status="invalid", kind="invalid", since=now, until=now + INVALID_RECHECK_S, http=http, expired=expired))


def mark_forbidden(provider: str, fp: str, now: float, *, http: int = 403) -> KeyState:
    return _put(provider, fp, KeyState(status="forbidden", kind="forbidden", since=now, until=now + FORBIDDEN_S, http=http))


def release(provider: str, fp: str) -> None:
    """A half-open probe ended without a verdict (cancelled, a transient error): let the next caller take the slot."""
    st = _state.get((provider, fp))
    if st is not None:
        st.inflight = False


def clear(provider: str, fp: str) -> None:
    """The key was just re-added or re-verified by the learner: forget whatever we believed about it (its models too)."""
    _state.pop((provider, fp), None)
    for k in [k for k in _models if k[0] == provider and k[1] == fp]:
        _models.pop(k, None)
    for k in [k for k in _bad if k[0] == provider and k[1] == fp]:
        _bad.pop(k, None)


def blocked(provider: str, fp: str, now: float) -> KeyState | None:
    """The gate entry while it still blocks (display and the 'cooling' question) - None when the key is usable."""
    st = _state.get((provider, fp))
    if st is not None and st.status != "ok" and now < st.until:
        return st
    return None


def chain_limited(chain: list, now: float) -> bool:
    """Is ANY key of this chain currently limited? (Grammar Coach skips its optional AI calls then - invalid keys do not count: they are not 'busy'.)"""
    for p in chain or []:
        st = blocked(p.get("name", ""), fingerprint(p.get("name", ""), p.get("key", "")), now)
        if st is not None and st.status == "limited":
            return True
    return False


# --------------------------------------------------------------------------------------------- per-model memory (Gemini and Groq limit PER MODEL)
def model_verdict(provider: str, fp: str, model: str, now: float) -> str:
    """'go' (nothing known against this model) | 'probe' (its skip time ended and THIS caller is the one half-open probe) | 'skip'. Same single-flight rule as `verdict`."""
    st = _models.get((provider, fp, model))
    if st is None:
        return "go"
    if now < st.until:
        return "skip"
    if st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    st.inflight, st.inflight_at = True, now
    return "probe"


def model_get(provider: str, fp: str, model: str) -> KeyState | None:
    return _models.get((provider, fp, model))


def model_blocked(provider: str, fp: str, model: str, now: float) -> KeyState | None:
    """Why this model is skipped right now (display / the 'all models limited' question) - None when it may be asked."""
    st = _models.get((provider, fp, model))
    if st is not None and now < st.until:
        return st
    return None


def _put_model(provider: str, fp: str, model: str, st: KeyState) -> KeyState:
    if len(_models) >= MAX_MODEL_ENTRIES and (provider, fp, model) not in _models:
        for k in sorted(_models, key=lambda k: _models[k].until)[:MAX_MODEL_ENTRIES // 10]:
            _models.pop(k, None)
    _models[(provider, fp, model)] = st
    return st


def mark_model_limited(provider: str, fp: str, model: str, now: float, seconds: float, *, scope: str = "", reset_at: float | None = None, evidence: bool = False,
                       approx: bool = False, http: int = 429) -> KeyState:
    return _put_model(provider, fp, model, KeyState(status="limited", kind="limited", scope=scope, since=now, until=now + max(1.0, float(seconds)), reset_at=reset_at,
                                                    evidence=evidence, approx=approx, http=http))


def mark_model_gone(provider: str, fp: str, model: str, now: float, seconds: float = MODEL_GONE_S, *, http: int = 404) -> KeyState:
    return _put_model(provider, fp, model, KeyState(status="gone", kind="model_gone", since=now, until=now + max(1.0, float(seconds)), http=http))


def model_ok(provider: str, fp: str, model: str) -> None:
    """This model just answered: whatever we believed about it is over."""
    _models.pop((provider, fp, model), None)


def model_release(provider: str, fp: str, model: str) -> None:
    """A half-open probe of a model ended without a verdict (cancelled, a passing error): let the next caller take the slot."""
    st = _models.get((provider, fp, model))
    if st is not None:
        st.inflight = False


def probe_soonest_model(provider: str, fp: str, models: list, now: float) -> None:
    """The EARLY probe of a key whose every model is limited: let the model that frees up soonest be asked now. Its memory would otherwise keep it skipped until its
    time is up - which is exactly what an early probe exists to cut short (a limit that ended before the provider's own estimate)."""
    best, best_until = None, None
    for m in models:
        st = _models.get((provider, fp, m))
        if st is None or st.status != "limited" or now >= st.until:
            continue
        if best is None or st.until < best_until:
            best, best_until = m, st.until
    if best is not None:
        _models[(provider, fp, best)].until = now


# --------------------------------------------------------------------------------------------- unusable replies (the validated walk, settings.chain_v3)
def bad_blocked(provider: str, fp: str, model: str, cls: str, now: float) -> BadState | None:
    """Why this model is skipped for this CLASS of call right now (its last replies were unusable) - None when it may be asked."""
    st = _bad.get((provider, fp, model, cls))
    if st is not None and now < st.until:
        return st
    return None


def bad_get(provider: str, fp: str, model: str, cls: str) -> BadState | None:
    return _bad.get((provider, fp, model, cls))


def mark_bad(provider: str, fp: str, model: str, cls: str, now: float, reason: str) -> BadState:
    """An UNUSABLE reply: skip this model for this class of call for 20 s, doubling while it keeps failing (cap 10 minutes). A model that goes a long time without a new
    strike starts again from the first."""
    k = (provider, fp, model, cls)
    st = _bad.get(k)
    if st is None or now - st.last_at > BAD_FORGET_S:
        st = BadState(strikes=0, since=now)
    st.strikes += 1
    st.last_at = now
    st.reason = str(reason)[:60]
    st.until = now + min(BAD_MAX_S, BAD_BASE_S * (2 ** min(st.strikes - 1, 10)))
    if len(_bad) >= MAX_BAD_ENTRIES and k not in _bad:
        for kk in sorted(_bad, key=lambda x: _bad[x].until)[:MAX_BAD_ENTRIES // 10]:
            _bad.pop(kk, None)
    _bad[k] = st
    return st


def bad_ok(provider: str, fp: str, model: str, cls: str) -> None:
    """This model just gave a USABLE reply for this class of call: whatever we held against it is over."""
    _bad.pop((provider, fp, model, cls), None)


def param_unsupported(provider: str, model: str, now: float) -> bool:
    """Did this model recently answer 400 to our extra request parameters (a reasoning setting it does not take)? Then they are left out."""
    until = _noparam.get((provider, model))
    return until is not None and now < until


def mark_param_unsupported(provider: str, model: str, now: float, seconds: float = PARAM_UNSUPPORTED_S) -> None:
    if len(_noparam) >= MAX_PARAM_ENTRIES and (provider, model) not in _noparam:
        _noparam.clear()
    _noparam[(provider, model)] = now + seconds


def bad_models(now: float) -> list[dict]:
    """What is held against which model right now (the owner's dashboard asks for DuSu's own keys + everyone's; counts only - no fingerprint, no learner)."""
    seen: dict = {}
    for (prov, _fp, model, cls), st in _bad.items():
        if now < st.until:
            e = seen.setdefault((prov, model, cls), {"provider": prov, "model": model, "class": cls, "keys": 0, "strikes": 0, "reason": st.reason})
            e["keys"] += 1
            e["strikes"] = max(e["strikes"], st.strikes)
    return sorted(seen.values(), key=lambda e: (e["provider"], e["model"], e["class"]))


# --------------------------------------------------------------------------------------------- model health (the validated walk): breaker + speed + success rate
def _drift(h: Health, now: float) -> None:
    """A reading that has not been refreshed for a while is only half believed: it drifts back toward the prior."""
    if h.last_at and now - h.last_at > HEALTH_STALE_S:
        h.ok = 0.5 * h.ok + 0.5 * HEALTH_PRIOR
        h.consec = 0
        h.last_at = now


def health_verdict(provider: str, model: str, cls: str, now: float) -> str:
    """'go' (the breaker is closed) | 'probe' (it opened, its hold is over and THIS caller is the one probe) | 'skip' (it is open, or somebody else is probing)."""
    h = _health.get((provider, model, cls))
    if h is None or h.consec < BREAKER_AFTER:
        return "go"
    if now < h.until:
        return "skip"
    if h.inflight and now - h.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    h.inflight, h.inflight_at = True, now
    return "probe"


def health_release(provider: str, model: str, cls: str) -> None:
    """A probe of a model ended without a verdict (cancelled, a limit, a rejected key): free its slot."""
    h = _health.get((provider, model, cls))
    if h is not None:
        h.inflight = False


def _health_for(provider: str, model: str, cls: str, now: float) -> Health:
    k = (provider, model, cls)
    h = _health.get(k)
    if h is None:
        if len(_health) >= MAX_HEALTH_ENTRIES:
            for kk in sorted(_health, key=lambda x: _health[x].last_at)[:MAX_HEALTH_ENTRIES // 10]:
                _health.pop(kk, None)
        h = _health[k] = Health()
    _drift(h, now)
    return h


def health_ok(provider: str, model: str, cls: str, ms: float, now: float) -> None:
    """A USABLE reply: the breaker closes and the success rate and speed follow."""
    h = _health_for(provider, model, cls, now)
    h.ok += HEALTH_ALPHA * (1.0 - h.ok)
    h.ms = ms if h.n == 0 or h.ms <= 0 else h.ms + HEALTH_ALPHA * (ms - h.ms)
    h.n += 1
    h.consec = h.opened = 0
    h.until = 0.0
    h.inflight = False
    h.last_at = now


def health_fail(provider: str, model: str, cls: str, kind: str, now: float) -> None:
    """kind 'transient' (a timeout, a 5xx, a connection error: it did not answer) or 'bad' (it answered, but not usably). Only 'transient' counts toward the breaker - a model
    that ANSWERS, however badly, is alive, and is held back per key and per kind of call instead (mark_bad)."""
    h = _health_for(provider, model, cls, now)
    h.ok += HEALTH_ALPHA * (0.0 - h.ok)
    h.n += 1
    h.inflight = False
    h.last_at = now
    if kind == "transient":
        h.consec += 1
        if h.consec >= BREAKER_AFTER:
            h.opened += 1
            h.until = now + min(BREAKER_MAX_S, BREAKER_BASE_S * (2 ** min(h.opened - 1, 6)))
    else:
        h.consec = h.opened = 0
        h.until = 0.0


def provider_score(provider: str, now: float) -> float:
    """How well this provider is doing right now, 0..1: the mean success rate of the models of it that were measured (HEALTH_PRIOR when none was). A provider whose
    every measured model has its breaker open is worth nothing."""
    vals, open_n = [], 0
    for (prov, _m, _c), h in _health.items():
        if prov != provider:
            continue
        _drift(h, now)
        vals.append(h.ok)
        if h.consec >= BREAKER_AFTER and now < h.until:
            open_n += 1
    if not vals:
        return HEALTH_PRIOR
    if open_n == len(vals):
        return 0.0
    return sum(vals) / len(vals)


def order_by_health(names: list[str], now: float) -> list[str]:
    """The providers best-first by score band (HEALTH_BAND bands); inside a band the order they came in (the configured one) is kept. Unmeasured = HEALTH_PRIOR."""
    def band(n):
        return int(provider_score(n, now) * HEALTH_BAND + 1e-9)
    return sorted(names, key=lambda n: -band(n))                 # sorted() is stable


def health_view(now: float) -> list[dict]:
    """The owner's dashboard: every measured model, counts and times only (no key, no fingerprint, no learner)."""
    out = []
    for (prov, model, cls), h in sorted(_health.items()):
        out.append({"provider": prov, "model": model, "class": cls, "ok": round(h.ok, 2), "ms": int(h.ms), "n": h.n, "breaker": bool(h.consec >= BREAKER_AFTER and now < h.until),
                    "reopen_in": max(0, int(h.until - now)) if h.consec >= BREAKER_AFTER else 0})
    return out


def gone_models(fps: set, now: float) -> list[tuple[str, str]]:
    """[(provider, model)] currently remembered as gone for any of these key fingerprints (the owner's /health asks it for DuSu's OWN keys only)."""
    out = {(k[0], k[2]) for k, st in _models.items() if k[1] in fps and st.status == "gone" and now < st.until}
    return sorted(out)
