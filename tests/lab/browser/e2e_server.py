"""Grammar Lab - the REAL app (uvicorn + a scratch MongoDB) for a REAL browser to talk to.

Seeds learners, switches the Lab ON, writes the session tokens for the browser spec to `$E2E_DIR/tokens.json` (a directory per run, removed by run_real.sh) and serves on :8000.
The Lab makes no model call, so nothing is stubbed: the checker, the bank and the explanations are the real ones.  Test-only routes (never in the app):
  GET  /__e2e/lookup?hi=<hindi>        -> {id, unit, level, en:[...], wrong, wrong_changes, unsure}   the item behind a Hindi sentence, its accepted answers, and one answer the
                                          checker calls "wrong" (preferably one whose explanation names an exact change) and one it calls "unsure" (found by mutating the answer
                                          and asking the real checker)
  POST /__e2e/switch {mode}            -> flips the `grammar_lab` setting (off | owner | on) and drops the access cache
  POST /__e2e/setting {key, value}     -> any other setting (e.g. home_ai, for the Home tile) and drops the access cache
  GET  /__e2e/stats                    -> {check_calls, show_calls}   how many times the check / show handlers ran (a double tap must make ONE)
Started by run_real.sh - never run against production."""

import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")

import uvicorn                                                      # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.lab import api as lab_api, bank, checker, service as svc   # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys must be blank (run through run_real.sh)"

NAMES = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ivy"]
CALLS = {"check": 0, "show": 0}

# count the handler runs without touching the app's code: wrap the service functions
_check, _show = svc.check, svc.show


async def _count_check(*a, **k):
    CALLS["check"] += 1
    return await _check(*a, **k)


async def _count_show(*a, **k):
    CALLS["show"] += 1
    return await _show(*a, **k)


svc.check, svc.show = _count_check, _count_show


def _mutations(target: str):
    toks = target.rstrip(".?! ").split()
    swaps = {"is": "are", "are": "is", "was": "were", "were": "was", "has": "have", "have": "has", "does": "do", "do": "does", "will": "would", "had": "has"}
    out = []
    for i, tok in enumerate(toks):
        lo = tok.lower()
        pre, post = toks[:i], toks[i + 1:]
        if lo in swaps:
            out.append(" ".join(pre + [swaps[lo]] + post))
        out.append(" ".join(pre + [tok[:-3] if lo.endswith("ing") and len(lo) > 4 else tok + "ing"] + post))
        if lo.endswith("s") and len(lo) > 3:
            out.append(" ".join(pre + [tok[:-1]] + post))
        if lo.endswith("ed") and len(lo) > 3:
            out.append(" ".join(pre + [tok[:-2]] + post))
        out.append(" ".join(pre + ["did"] + [tok] + post))
    return out


def _unsure(target: str):
    toks = target.rstrip(".?! ").split()
    out = []
    for i in range(len(toks) - 1, -1, -1):
        out.append(" ".join(toks[:i] + ["zork"] + toks[i + 1:]))
    out.append("Really " + target)
    return out


def _probe(it):
    """(wrong, wrong_has_changes, unsure): a wrong answer the real checker calls wrong (preferably one whose explanation names an exact change), one it calls unsure."""
    from app.lab import explain
    var = svc._variants(it)
    wrong = fallback = unsure = None
    has_changes = False
    for m in _mutations(it.en[0]):
        r = checker.check(m, var, it.unit)
        if r["verdict"] != "wrong":
            continue
        if fallback is None:
            fallback = m
        if explain.build(r, it.unit, it.trap)["en"]["changes"]:
            wrong, has_changes = m, True
            break
    wrong = wrong or fallback
    for m in _unsure(it.en[0]):
        if checker.check(m, var, it.unit)["verdict"] == "unsure":
            unsure = m
            break
    return wrong, has_changes, unsure


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {n: {"sub": f"e2e-{n}", "email": f"{n}@example.com", "name": f"{n.title()} Learner", "picture": ""} for n in NAMES}
    users["own"] = {"sub": "e2e-own", "email": sorted(M.OWNER_EMAILS)[0], "name": "The Owner", "picture": ""}       # the owner: for the dashboard switch
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    await db.set_setting("grammar_lab", "on")
    await db.set_setting("practice_room", "on")
    M.invalidate_access_cache()
    out = os.environ.get("E2E_DIR", "/tests/lab/browser/.e2e")
    os.makedirs(out, exist_ok=True)
    json.dump({k: {"token": auth.make_session(u), "user": u} for k, u in users.items()}, open(out + "/tokens.json", "w"))
    await __import__('app.store', fromlist=['close']).close()        # the client made in THIS event loop must not be reused by uvicorn's own loop


@M.app.get("/__e2e/lookup")
async def _lookup(hi: str):
    for it in svc.items().values():
        if it.hi == hi:
            wrong, has_changes, unsure = _probe(it)
            return {"id": it.id, "unit": it.unit, "level": it.level, "en": list(it.en), "wrong": wrong, "wrong_changes": has_changes, "unsure": unsure}
    return {"id": None}


@M.app.post("/__e2e/switch")
async def _switch(body: dict):
    await db.set_setting("grammar_lab", body.get("mode", "on"))
    M.invalidate_access_cache()
    return {"ok": True}


@M.app.post("/__e2e/setting")
async def _setting(body: dict):
    await db.set_setting(str(body["key"]), str(body["value"]))
    M.invalidate_access_cache()
    return {"ok": True}


@M.app.get("/__e2e/stats")
async def _stats():
    return {"check_calls": CALLS["check"], "show_calls": CALLS["show"]}


# routes added now sit AFTER the app's SPA catch-all, which would answer them with HTML - move them to the front
for _r in [r for r in M.app.router.routes if getattr(r, 'path', '').startswith('/__e2e/')]:
    M.app.router.routes.remove(_r)
    M.app.router.routes.insert(0, _r)

asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
