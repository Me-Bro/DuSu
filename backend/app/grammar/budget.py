"""Call budget, the breaker and the process-wide concurrency guard for Grammar Coach model calls (plan Appendix A section A7).

A grammar call must never cost a learner's chat reply: it uses `cool=False` (a 429 never marks the process-global provider cooldown), it is skipped
while ANY provider is cooling, and at most two run at once in the whole process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

SESSION_CALLS = 10
SESSION_SENTS = 120
BATCH_SENTS = 12
DAILY_CALLS = 60
CALL_TIMEOUT_S = 35.0
MAX_TOKENS = 1500                    # both ladder rungs: a reasoning model spends the cap, so a retry must never get less

_sem: asyncio.Semaphore | None = None


def semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(2)
    return _sem


def cooling() -> list[str]:
    try:
        from ..providers.openrouter_provider import cooling_down
        return cooling_down()
    except Exception:
        return []


@dataclass
class Budget:
    session_calls: int = SESSION_CALLS
    session_sents: int = SESSION_SENTS
    calls: int = 0
    breaker: bool = False            # open = no more AI calls this session (quota, every provider failing, or a provider cooling)
    reason: str = ""
    charged: bool = False            # the ONE quota charge for this session analysis has been made
    log: list = field(default_factory=list)

    def can_call(self) -> bool:
        if self.breaker:
            return False
        if self.calls >= self.session_calls:
            self.trip("cap")
            return False
        if cooling():
            self.trip("cooling")
            return False
        return True

    def trip(self, why: str) -> None:
        self.breaker = True
        self.reason = self.reason or why
