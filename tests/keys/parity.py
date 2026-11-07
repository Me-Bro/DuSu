"""Keys - "old = old": today's walker, replayed.

The walker (`_complete` in providers/openrouter_provider.py) had NO test coverage - every suite stubs `llm` above it. This replays scripted provider answers through
  * HEAD's walker      tests/keys/.head/provider_head.py  (`git show 057e58c:backend/app/providers/openrouter_provider.py` - the commit before the per-key engine)
  * `_complete_legacy` the same code, kept verbatim in the new module (what every learner without `key_health` gets)
  * `_complete_v2`     the per-key walker on the SERVER chain (what the owner gets with `key_health` on)
and compares, per scenario and over three consecutive calls: the ORDER of (provider, model) attempts, the process-wide cooldown map (provider -> seconds), and the result.

  - legacy must be IDENTICAL to HEAD in every scenario (including the ones where the old behaviour is a bug).
  - v2 must be IDENTICAL to HEAD wherever the old behaviour was right (success, limits with no wait given, 5xx, a retired model, a bad request, an empty answer).
  - v2 must DIFFER, in exactly the documented way, where it is a fix: a rejected key is not retried on every call, a timeout leaves the provider, a limit lasts as long as the
    provider said - and (the "AI busy" work) Groq and Gemini limit PER MODEL, so a 429 on one model tries the provider's next model; a model the provider says does not exist
    (404) is remembered for 30 minutes instead of being asked on every turn.
  - The SAME scenarios are replayed with those two features switched off (`PER_MODEL_LIMITS` emptied, the model memory a no-op): v2 must then equal HEAD exactly, which proves
    they are the ONLY difference. Their own behaviour is pinned explicitly in "the documented differences".

Run:  mkdir -p tests/keys/.head && git show 057e58c:backend/app/providers/openrouter_provider.py > tests/keys/.head/provider_head.py && tests/keys/run.sh parity.py
"""

import asyncio
import importlib.util
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

from world import World, install, ok, err, timeout, conn, completion, R, GROQ_401, GROQ_429_PLAIN, GROQ_429_TPD, GEMINI_400_KEY, GEMINI_429_BARE, GEMINI_503, OPENROUTER_404, OPENROUTER_429_DAY   # noqa: E402

FAILS, N = [], 0


def check(name, cond, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {'' if cond else str(detail)[:400]}")
    if not cond:
        FAILS.append(name)


spec = importlib.util.spec_from_file_location("app.providers.provider_head", "/tests/keys/.head/provider_head.py")
head = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = head
spec.loader.exec_module(head)

from app.config import settings                       # noqa: E402
from app.providers import openrouter_provider as op    # noqa: E402
from app.keys import gate, ledger                      # noqa: E402

GK, MK, OK_ = "gsk_SERVER" + "q" * 30, "AIzaSERVER" + "q" * 30, "sk-or-v1-SERVER" + "q" * 30
settings.groq_api_key, settings.gemini_api_key, settings.openrouter_api_key = GK, MK, OK_
MSG = [{"role": "user", "content": "hi"}]
KEY = {"groq": GK, "gemini": MK, "openrouter": OK_}


def script(w: World, sc: dict):
    for prov, steps in sc.items():
        w.on(prov, KEY[prov], *steps)
    return w


SAME = {   # scenarios where the old behaviour was right: the per-key walker must reproduce it exactly
    "all healthy": {},
    "groq limited, no wait given": {"groq": [err(429, GROQ_429_PLAIN)]},
    "groq limited, then gemini limited": {"groq": [err(429, GROQ_429_PLAIN)], "gemini": [err(429, GEMINI_429_BARE)]},
    "groq 5xx on the first model, ok on the second": {"groq": [err(500, {"error": {"message": "boom"}}), ok()]},
    "groq 5xx on both models": {"groq": [err(500, {"error": {"message": "boom"}})]},
    "groq retired model (404), ok on the next": {"groq": [err(404, OPENROUTER_404), ok()]},
    "groq bad request (400), ok on the next model": {"groq": [err(400, {"error": {"message": "Unsupported value"}}), ok()]},
    "groq empty answer, then ok": {"groq": [R(200, completion("")), ok()]},
    "gemini 503 then ok next call": {"groq": [err(429, GROQ_429_PLAIN)], "gemini": [err(503, GEMINI_503), ok()]},
    "groq limited once then recovers": {"groq": [err(429, GROQ_429_PLAIN), ok()]},
}
DIFFERENT = {   # the documented fixes
    "ALL THREE limited": {"groq": [err(429, GROQ_429_PLAIN)], "gemini": [err(429, GEMINI_429_BARE)], "openrouter": [err(429, OPENROUTER_429_DAY)]},
    "groq REJECTED (401)": {"groq": [err(401, GROQ_401)]},
    "gemini REJECTED (400 api key not valid)": {"groq": [err(429, GROQ_429_PLAIN)], "gemini": [err(400, GEMINI_400_KEY)]},
    "groq TIMEOUT": {"groq": [timeout()]},
    "groq limited WITH a wait the provider named": {"groq": [err(429, GROQ_429_TPD)]},
}


async def replay(fn, sc, calls=3, prepare=None, **kw):
    is_head = fn is head_fn
    """-> list of per-call dicts {attempts: [(provider, model)], cooldown: {provider: seconds}, result}"""
    out = []
    w = script(World(), sc)
    install(w)
    op._cooldown.clear(); head._cooldown.clear(); gate.reset_all(); ledger.reset_all()
    if prepare:
        prepare()
    for _ in range(calls):
        n = len(w.calls)
        try:
            r = ("ok", await fn(MSG, 50, **kw))
        except Exception as e:
            r = ("err", str(e).split(":", 1)[0])                  # the message text is the contract; the class (RuntimeError / ProviderChainError) may differ
        cd = head._cooldown if is_head else op._cooldown
        now = time.time()
        out.append({"attempts": [(c[0], c[3]) for c in w.calls[n:]], "cooldown": {k: round((v - now) / 5) for k, v in cd.items() if v > now}, "result": r})
    return out


def head_fn(*a, **kw):
    head._client = lambda p: op.new_sdk_client(p)             # the HEAD copy keeps its own walker; only its transport is the fake world
    return head._complete(*a, **kw)


async def v2(*a, **kw):
    op.set_active_keys(None, uid="owner", engine=True)
    return await op._complete(*a, **kw)


async def v2_compat(*a, **kw):
    """The per-key walker with the two newest features switched off - it must then behave exactly like HEAD wherever HEAD was right."""
    saved = (op.PER_MODEL_LIMITS, gate.mark_model_gone)
    op.PER_MODEL_LIMITS = frozenset()
    gate.mark_model_gone = lambda *x, **y: None
    try:
        return await v2(*a, **kw)
    finally:
        op.PER_MODEL_LIMITS, gate.mark_model_gone = saved


async def legacy(*a, **kw):
    op.set_active_keys(None, uid="owner", engine=False)
    return await op._complete(*a, **kw)


async def main():
    print("\n== legacy (engine off) is HEAD, byte for byte in behaviour - every scenario")
    for name, sc in {**SAME, **DIFFERENT}.items():
        h = await replay(head_fn, sc)
        l = await replay(legacy, sc)
        check(f"legacy == HEAD: {name}", [(x["attempts"], x["cooldown"], x["result"]) for x in h] == [(x["attempts"], x["cooldown"], x["result"]) for x in l], (h, l))
    print("\n== the per-key walker == HEAD where HEAD was right (per-model limits and the model memory switched off: they are the ONLY difference)")
    for name, sc in SAME.items():
        h = await replay(head_fn, sc)
        n = await replay(v2_compat, sc)
        check(f"v2 == HEAD: {name}", [(x["attempts"], x["cooldown"], x["result"]) for x in h] == [(x["attempts"], x["cooldown"], x["result"]) for x in n], (h, n))
    print("\n== ... with prefer_fast / first / cool=False")
    for kw in ({"prefer_fast": True}, {"first": "gemini"}, {"cool": False}, {"prefer_fast": True, "cool": False}):
        for name in ("all healthy", "groq limited, no wait given", "groq limited, then gemini limited", "groq 5xx on both models"):
            h = await replay(head_fn, SAME[name], **kw)
            n = await replay(v2_compat, SAME[name], **kw)
            check(f"v2 == HEAD {kw}: {name}", [(x["attempts"], x["cooldown"], x["result"]) for x in h] == [(x["attempts"], x["cooldown"], x["result"]) for x in n], (h, n))
    print("\n== the documented differences")
    h = await replay(head_fn, DIFFERENT["groq REJECTED (401)"])
    n = await replay(v2, DIFFERENT["groq REJECTED (401)"])
    check("a REJECTED key: HEAD asked Groq (both models) on EVERY call; the per-key walker asks once", sum(1 for x in h for a in x["attempts"] if a[0] == "groq") == 6
          and sum(1 for x in n for a in x["attempts"] if a[0] == "groq") == 1, (h, n))
    check("... and the learner still got an answer every time", all(x["result"][0] == "ok" for x in h) and all(x["result"][0] == "ok" for x in n))
    h = await replay(head_fn, DIFFERENT["gemini REJECTED (400 api key not valid)"])
    n = await replay(v2, DIFFERENT["gemini REJECTED (400 api key not valid)"])
    check("a Gemini 400 'API key not valid': HEAD retried Gemini on every call; the per-key walker does not", sum(1 for x in h for a in x["attempts"] if a[0] == "gemini") >= 3
          and sum(1 for x in n for a in x["attempts"] if a[0] == "gemini") == 1, (h, n))
    h = await replay(head_fn, DIFFERENT["groq TIMEOUT"])
    n = await replay(v2, DIFFERENT["groq TIMEOUT"])
    check("a TIMEOUT: HEAD tried Groq's second model too; the per-key walker leaves the provider", [a[1] for a in h[0]["attempts"] if a[0] == "groq"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
          and [a[1] for a in n[0]["attempts"] if a[0] == "groq"] == ["openai/gpt-oss-120b"], (h[0], n[0]))
    h = await replay(head_fn, DIFFERENT["groq limited WITH a wait the provider named"])
    n = await replay(v2, DIFFERENT["groq limited WITH a wait the provider named"])
    hc = h[0]["cooldown"].get("groq", 0) * 5
    check("a limit that names its wait (6m45s): HEAD guessed 30 minutes (the word 'day' in the text); the per-key walker honours the provider's ~7 minutes - in the gate AND in the /health cooldown map",
          hc >= 1700 and abs(n[0]["cooldown"].get("groq", 0) * 5 - 405) <= 10, (h[0]["cooldown"], n[0]["cooldown"]))
    h = await replay(head_fn, SAME["groq limited, no wait given"])
    n = await replay(v2, SAME["groq limited, no wait given"])
    check("Groq limits PER MODEL: HEAD gave up on Groq after one 429; the per-key walker asks its second model too (once), then skips Groq whole - from call 2 the two are the same",
          [a[1] for a in h[0]["attempts"] if a[0] == "groq"] == ["openai/gpt-oss-120b"] and [a[1] for a in n[0]["attempts"] if a[0] == "groq"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
          and [x["attempts"] for x in h[1:]] == [x["attempts"] for x in n[1:]], (h, n))
    n = await replay(v2, {"groq": [err(429, GROQ_429_PLAIN), ok()]}, calls=3)
    check("... and when the second model answers, Groq is NOT gated (only the limited model is skipped next time): call 2 asks Groq's second model straight away",
          [a for a in n[0]["attempts"]] == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b")] and n[1]["attempts"] == [("groq", "openai/gpt-oss-20b")], n[:2])
    h = await replay(head_fn, SAME["groq retired model (404), ok on the next"])
    n = await replay(v2, SAME["groq retired model (404), ok on the next"])
    check("a retired model (404): HEAD asked it on EVERY call; the per-key walker asks once and then goes straight to the next model",
          sum(1 for x in h for a in x["attempts"] if a[1] == "openai/gpt-oss-120b") == 3 and sum(1 for x in n for a in x["attempts"] if a[1] == "openai/gpt-oss-120b") == 1
          and all(a[1] == "openai/gpt-oss-20b" for x in n[1:] for a in x["attempts"]), (h, n))
    h = await replay(head_fn, DIFFERENT["ALL THREE limited"])
    n = await replay(v2, DIFFERENT["ALL THREE limited"])
    check("EVERY key limited: HEAD sent all three requests again on every call (its 'try them anyway' pass); the per-key walker fails at once with nothing sent after the first call "
          "(that first call also asks Groq's second model: 4 requests)",
          [len(x["attempts"]) for x in h] == [3, 3, 3] and [len(x["attempts"]) for x in n] == [4, 0, 0], ([len(x["attempts"]) for x in h], [len(x["attempts"]) for x in n]))
    check("... both end in the same words (the message text is the contract)", [x["result"] for x in h] == [x["result"] for x in n] and h[0]["result"][0] == "err", (h[0]["result"], n[0]["result"]))
    print("\n== ordering: the chain order is the same")
    h = await replay(head_fn, DIFFERENT["ALL THREE limited"], calls=1)
    n = await replay(v2, DIFFERENT["ALL THREE limited"], calls=1)
    check("groq -> gemini -> openrouter in the same order; the per-key walker adds Groq's second model (its limits are per model)",
          [a[0] for a in h[0]["attempts"]] == ["groq", "gemini", "openrouter"] and [a[0] for a in n[0]["attempts"]] == ["groq", "groq", "gemini", "openrouter"]
          and [a for a in n[0]["attempts"] if a[0] != "groq" or a[1] == "openai/gpt-oss-120b"] == h[0]["attempts"], (h, n))
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
