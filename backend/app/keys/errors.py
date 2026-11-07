"""Keys - the structured failure the new walker raises when no key of the chain could answer.

It IS a RuntimeError with the SAME message text the old walker used ("all providers/models unavailable: <last error>"), so every existing `str(e)` check - the
old `_is_quota`, Resume Interview's and Grammar Coach's own quota tests, the log lines - keeps working unchanged. What it adds is what the old walker threw away:
which key failed HOW, so the learner can be told the exact reason.

state   no_keys       the chain was empty
        all_invalid   every key was rejected (wrong, revoked or expired)
        all_limited   no key can serve right now: limit hit, blocked, or out of credit (some may also be rejected)
        transient     at least one key failed for a reason that is not the key (timeout, provider trouble, a retired model) - "try again in a minute"

`own` says whose keys these were: True = the learner's OWN keys (they can fix them), False = DuSu's own chain (they cannot, and must never be shown DuSu's providers).
"""

from __future__ import annotations

import time

STATES = ("no_keys", "all_invalid", "all_limited", "transient")

DEFAULT_RETRY_S = 6          # a hiccup with no wait time from the provider: a short, honest countdown
_MIN_RETRY_S, _MAX_RETRY_S = 3, 600


class ProviderChainError(RuntimeError):
    def __init__(self, last_err, state: str, keys: list, own: bool = True):
        super().__init__(f"all providers/models unavailable: {last_err}")
        self.last_error = last_err
        self.state = state
        self.keys = keys                       # [{provider, kind, scope, reset_at, approx, expired, retry_s}]
        self.own = bool(own)

    def retry_in(self) -> int | None:
        """Seconds until it is worth asking again: the soonest key that can recover by itself (a passing failure, or a limit that ends in minutes). None when nothing
        can - every key rejected, blocked, out of credit, or limited for the day."""
        best = None
        for k in self.keys:
            kind = k.get("kind")
            if kind == "transient":
                cand = k.get("retry_s")
                cand = DEFAULT_RETRY_S if cand is None else cand
            elif kind == "limited" and k.get("scope") in ("minute", "upstream", ""):
                cand = k.get("retry_s")
            else:
                continue
            if cand is None:
                continue
            best = cand if best is None else min(best, cand)
        if best is None:
            return None
        return int(min(_MAX_RETRY_S, max(_MIN_RETRY_S, round(best))))

    def kp(self, now: float | None = None) -> dict:
        """The learner-facing payload (`kp`) that rides on the existing error frames / HTTP error bodies. Never carries key text or provider error text.
        For DuSu's own keys the learner can do nothing about a key, so whatever the real reason, from their side the AI service is simply not answering: state
        'transient', no key rows (a free learner must never be told to fix a Groq key they never added)."""
        now_i = int(now if now is not None else time.time())
        if not self.own:
            out = {"state": "transient", "own": False, "keys": [], "now": now_i}
            r = self.retry_in()
            if r is not None:
                out["retry_in"] = r
            return out
        keys = []
        for k in self.keys:
            e = {"provider": k.get("provider", ""), "kind": k.get("kind", "")}
            if k.get("scope"):
                e["scope"] = k["scope"]
            if k.get("reset_at"):
                e["reset_at"] = int(k["reset_at"])
                if k.get("approx"):
                    e["approx"] = True
            if k.get("expired"):
                e["expired"] = True
            keys.append(e)
        out = {"state": self.state, "own": True, "keys": keys, "now": now_i}
        if self.state == "transient":
            r = self.retry_in()
            if r is not None:
                out["retry_in"] = r
        return out


def chain_state(records: list) -> str:
    """The headline state from the per-key records of one walk (see the module docstring). `records` = [{kind, scope}] - kind in invalid / limited /
    forbidden / needs_credit / transient."""
    if not records:
        return "no_keys"
    kinds = []
    for r in records:
        k = r.get("kind", "transient")
        if k == "limited" and r.get("scope") == "upstream":
            k = "transient"                    # the provider's shared free pool is busy - not this key's own limit
        kinds.append(k)
    if all(k == "invalid" for k in kinds):
        return "all_invalid"
    if all(k in ("invalid", "limited", "forbidden", "needs_credit") for k in kinds):
        return "all_limited"
    return "transient"


def engine_kp(e) -> dict | None:
    """The per-key engine's own words (`kp`) for this failure when `e` - or anything it was raised from - is a ProviderChainError, else None. Wrappers (practice.AnalysisUnavailable,
    resume_interview's engine.Unavailable ...) keep the original as `__cause__` / `__context__`; this walks them, never forever."""
    cur, seen = e, set()
    for _ in range(6):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        if isinstance(cur, ProviderChainError):
            return cur.kp()
        cur = cur.__cause__ or cur.__context__
    return None


def is_keys_problem(kp: dict | None) -> bool:
    """Is this the learner's OWN keys being rejected / at their limit / missing - the only thing "quota" may mean? A busy or unreachable AI service never is, and nothing on DuSu's own
    keys is (the learner can do nothing about those)."""
    return bool(kp) and kp.get("state") in ("all_limited", "all_invalid", "no_keys") and bool(kp.get("own", True))
