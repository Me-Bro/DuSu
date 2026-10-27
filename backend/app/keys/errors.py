"""Keys - the structured failure the new walker raises when no key of the chain could answer.

It IS a RuntimeError with the SAME message text the old walker used ("all providers/models unavailable: <last error>"), so every existing `str(e)` check - the
old `_is_quota`, Resume Interview's and Grammar Coach's own quota tests, the log lines - keeps working unchanged. What it adds is what the old walker threw away:
which key failed HOW, so the learner can be told the exact reason.

state   no_keys       the chain was empty
        all_invalid   every key was rejected (wrong, revoked or expired)
        all_limited   no key can serve right now: limit hit, blocked, or out of credit (some may also be rejected)
        transient     at least one key failed for a reason that is not the key (timeout, provider trouble, a retired model) - "try again in a minute"
"""

from __future__ import annotations

import time

STATES = ("no_keys", "all_invalid", "all_limited", "transient")


class ProviderChainError(RuntimeError):
    def __init__(self, last_err, state: str, keys: list):
        super().__init__(f"all providers/models unavailable: {last_err}")
        self.last_error = last_err
        self.state = state
        self.keys = keys                       # [{provider, kind, scope, reset_at, approx, expired}]

    def kp(self, now: float | None = None) -> dict:
        """The learner-facing payload (`kp`) that rides on the existing error frames / HTTP error bodies. Never carries key text or provider error text."""
        out = []
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
            out.append(e)
        return {"state": self.state, "keys": out, "now": int(now if now is not None else time.time())}


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
