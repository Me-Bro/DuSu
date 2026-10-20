"""Notifications - the engine: one asyncio loop in the web process, Postgres as the queue (the same design as My Day's reminder loop, and a
SEPARATE loop, so a bug here can never stop a reminder).

    reclaim -> claim (FOR UPDATE SKIP LOCKED) -> deliver (re-check, then push) -> materialize today's rows (every 2 minutes) -> prune (daily)

The loop catches every exception, logs the class name only (never a title, a name or a number) and sleeps. `tick()` takes the clock and the push
sender as arguments so the tests drive it with a fake clock and a fake sender.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

from ..planner import timeutil as tu
from . import service as svc

TICK_SEC = 20
START_DELAY_SEC = 12
MATERIALIZE_EVERY = 120
PRUNE_EVERY = 86400

state = {"started": None, "ticks": 0, "last_tick": None, "last_error": "", "last_stats": {}}
_mono = {"mat": 0.0, "prune": 0.0}


async def run_forever(mode_fn, enabled_fn) -> None:
    """Started from the app's startup hook. `mode_fn()` -> the `notifications` switch ('off' idles the loop); `enabled_fn(email)` -> may this
    learner receive them (the owner-only stage)."""
    state["started"] = tu.now_utc().isoformat()
    await asyncio.sleep(START_DELAY_SEC)
    while True:
        try:
            if await mode_fn() != "off":
                state["last_stats"] = await tick(enabled_fn)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state["last_error"] = type(e).__name__
            print(f"[notify] tick failed: {type(e).__name__}")
        await asyncio.sleep(TICK_SEC)


async def tick(enabled_fn, now: dt.datetime | None = None, sender=None, materialize: bool | None = None) -> dict:
    now = now or tu.now_utc()
    stats = {"reclaimed": 0, "claimed": 0, "sent": 0, "cancelled": 0, "retry": 0, "failed": 0, "created": 0}
    stats["reclaimed"] = await svc.reclaim(now)
    if materialize is None:
        materialize = (time.monotonic() - _mono["mat"]) >= MATERIALIZE_EVERY
    if materialize:
        _mono["mat"] = time.monotonic()
        try:
            stats["created"] = (await svc.materialize_all(enabled_fn, now)).get("created", 0)
        except asyncio.CancelledError:
            raise
        except Exception as e:                           # a failed planning pass must not stop delivery of what is already due
            state["last_error"] = type(e).__name__
            print(f"[notify] materialize failed: {type(e).__name__}")
    for nid in await svc.claim(now):
        stats["claimed"] += 1
        try:
            outcome = await svc.deliver(nid, enabled_fn, now, sender)
        except asyncio.CancelledError:
            raise
        except Exception as e:                           # one bad row never stops the rest
            print(f"[notify] deliver failed: {type(e).__name__}")
            await svc.fail_row(nid, type(e).__name__)
            outcome = "failed"
        if outcome in stats:
            stats[outcome] += 1
    if (time.monotonic() - _mono["prune"]) >= PRUNE_EVERY:
        _mono["prune"] = time.monotonic()
        await svc.prune(now)
    state["ticks"] += 1
    state["last_tick"] = now.isoformat()
    return stats


async def health() -> dict:
    out = await svc.health()
    out.update({"started": state["started"], "ticks": state["ticks"], "last_tick": state["last_tick"], "last_error": state["last_error"]})
    return out
