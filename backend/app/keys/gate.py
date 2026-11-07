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


def reset_all() -> None:
    """Tests only."""
    _state.clear()
    _models.clear()


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


def gone_models(fps: set, now: float) -> list[tuple[str, str]]:
    """[(provider, model)] currently remembered as gone for any of these key fingerprints (the owner's /health asks it for DuSu's OWN keys only)."""
    out = {(k[0], k[2]) for k, st in _models.items() if k[1] in fps and st.status == "gone" and now < st.until}
    return sorted(out)
