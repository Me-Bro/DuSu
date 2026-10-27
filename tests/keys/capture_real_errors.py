"""Keys - OWNER-RUN, NEVER CI: record what the real providers actually answer, so tests/keys/world.py's synthetic bodies can be checked against reality.

It uses the SDK path the app uses (typed errors, `.body`, `.response.headers`) with YOUR keys from the environment. It never prints a key: every string that contains one
is redacted before it is written. A real 429 cannot be provoked on demand, so this records what CAN be recorded safely:
  * a deliberately WRONG key to each provider (the exact 401 / 400 body and which headers come back),
  * one tiny real call with each key you give it (the success headers - Groq's daily allowance headers, for instance),
  * with --burst N, up to N more tiny calls in a row per provider to try to reach a per-minute limit (free tiers allow roughly 15-30 a minute). It stops at the first 429 and
    records it. It uses a few requests of YOUR free quota; leave it off if you would rather not.
and it prints what keys/classify.py makes of each answer, so a wrong guess in the classifier shows up as a line you can read.

Run (the app image has the SDK; this needs the internet, unlike every other test here):
  docker run --rm -e GROQ_API_KEY -e GEMINI_API_KEY -e OPENROUTER_API_KEY -v "$PWD/backend":/app -v "$PWD/tests":/tests -v "$PWD":/out dusu-ri-test \
      python /tests/keys/capture_real_errors.py [--burst 20] --out /out/real-errors.json
Then paste the interesting bodies into tests/keys/world.py (a 429 body is the one worth having) and re-run tests/keys/run.sh unit.py.
"""

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/app")

from app.config import settings                   # noqa: E402
from app.keys import classify                      # noqa: E402
from app.providers import openrouter_provider as op   # noqa: E402

WANT = ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens", "x-ratelimit-reset", "x-ratelimit-limit", "x-ratelimit-remaining", "content-type")
WRONG = {"groq": "gsk_" + "0" * 52, "gemini": "AIza" + "0" * 35, "openrouter": "sk-or-v1-" + "0" * 64}


def redact(obj, secrets):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    for x in secrets:
        if x:
            s = s.replace(x, "<KEY>")
    return json.loads(s)


async def one(provider: str, key: str, label: str, secrets):
    chain = settings.providers_from({provider: key})
    p = chain[0]
    client = op.new_sdk_client(p, timeout=20.0)
    t0 = time.time()
    try:
        raw = await client.chat.completions.with_raw_response.create(model=p["models"][0], messages=[{"role": "user", "content": "Reply OK"}], max_tokens=8, temperature=0,
                                                                     extra_body=p.get("extra") or {})
        resp = raw.parse()
        rec = {"label": label, "provider": provider, "ok": True, "ms": int((time.time() - t0) * 1000), "headers": {k: raw.headers.get(k) for k in WANT if raw.headers.get(k)},
               "usage": getattr(resp, "usage", None) and resp.usage.model_dump(), "ratelimit_parsed": classify.parse_ratelimit(provider, raw.headers, time.time())}
    except Exception as e:                                       # the SDK's typed error is exactly what the walker classifies
        out = classify.classify(provider, e)
        hdrs = getattr(getattr(e, "response", None), "headers", None) or {}
        rec = {"label": label, "provider": provider, "ok": False, "ms": int((time.time() - t0) * 1000), "error_class": type(e).__name__, "status": getattr(e, "status_code", None),
               "body": getattr(e, "body", None), "headers": {k: hdrs.get(k) for k in WANT if hdrs.get(k)}, "classified_as": out.__dict__}
    finally:
        await client.close()
    return redact(rec, secrets)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--burst", type=int, default=0)
    ap.add_argument("--out", default="real-errors.json")
    a = ap.parse_args()
    keys = {"groq": os.getenv("GROQ_API_KEY", ""), "gemini": os.getenv("GEMINI_API_KEY", ""), "openrouter": os.getenv("OPENROUTER_API_KEY", "")}
    secrets = [k for k in keys.values() if k] + list(WRONG.values())
    results = []
    for prov in ("groq", "gemini", "openrouter"):
        results.append(await one(prov, WRONG[prov], "a deliberately wrong key", secrets))
        if keys[prov]:
            results.append(await one(prov, keys[prov], "your key, one tiny call", secrets))
            for i in range(a.burst):
                r = await one(prov, keys[prov], f"burst {i + 1}", secrets)
                results.append(r)
                if not r["ok"]:
                    break
    for r in results:
        c = r.get("classified_as") or {}
        print(f"{r['provider']:<11} {r['label']:<26} -> " + ("ok" if r["ok"] else f"{r['status']} {r['error_class']}: classified {c.get('kind')} scope={c.get('scope') or '-'} retry_after={c.get('retry_after')}"))
    json.dump(results, open(a.out, "w"), indent=2, ensure_ascii=False)
    print(f"\nwritten to {a.out} (no key is in it)")


asyncio.run(main())
