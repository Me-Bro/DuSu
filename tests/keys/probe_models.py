"""Which AI models ACTUALLY answer, with DuSu's OWN keys - run by the owner (or with the owner's OK), NEVER in CI: it spends a few free-tier requests.

  docker run --rm -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/keys/probe_models.py [provider ...]

The keys come from backend/.env through the app's own settings; nothing is blanked here (the opposite of every other tool in this folder). It prints ONLY: which model ids each
provider lists (zero quota), and for every candidate model one real call with the Home companion's real system prompt in its real shape (a synthetic learner: no learner data) -
the status KIND (never provider text, never a key), the latency, whether the answer is the JSON object the Home chat needs, and how much of the reply is Devanagari (the Home
chat's Hindi). Use it when "AI busy" shows up, or once a month: provider model ids rot without notice.

A model is worth putting in the chain when it answers `ok` with valid JSON, a Hindi reply, in a few seconds - twice.
"""

import asyncio
import json
import re
import sys
import time

sys.path.insert(0, "/app")

from app.config import settings                                  # noqa: E402
from app.keys import classify                                    # noqa: E402
from app.keys.probe import list_models                           # noqa: E402
from app.providers import openrouter_provider as op              # noqa: E402
from app import home_content as hc                               # noqa: E402
from app.interview.prompts import home_system                    # noqa: E402

CANDIDATES = {
    "gemini": ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash"],
    "openrouter": ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-lightning:free"],
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
}
LINES = ["Hh", "what time is it now?"]                           # a nonsense first line (the one that failed on 28 Oct) and a real question
if len(sys.argv) > 1 and sys.argv[-1] == "--once":
    LINES = LINES[:1]
    sys.argv.pop()
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def system_prompt():
    flags = {"practice_room": True, "planner": True, "resume_interview": True, "grammar_coach": True, "life_context": True}
    return home_system("Asha", "hi", "evening", 19, "", False, True, hc.catalog(flags), hc.INTENTS, "", now_text=hc.now_text(), planner_on=True)


def judge(text):
    """-> (valid JSON with a non-empty reply?, share of the reply's letters that are Devanagari)."""
    try:
        d = op._extract_json(text)
    except Exception:
        return False, 0.0
    r = d.get("reply") if isinstance(d, dict) else None
    if not isinstance(r, str) or not r.strip():
        return False, 0.0
    letters = [c for c in r if c.isalpha()]
    return True, (sum(1 for c in letters if DEVANAGARI.match(c)) / len(letters)) if letters else 0.0


def why(e):
    """The provider's own one-line reason for a refusal (first message in the error body), bounded, with anything key-shaped removed. Safe to print: the prompt is synthetic."""
    body = getattr(e, "body", None)
    cur = body[0] if isinstance(body, list) and body else body
    msg = ""
    if isinstance(cur, dict):
        err = cur.get("error", cur)
        msg = str(err.get("message", "") if isinstance(err, dict) else err)
    return re.sub(r"(AIza|gsk_|sk-or-v1-|AQ\.)[A-Za-z0-9_\-.]+", "<key>", msg)[:170]


async def call(p, model, system, line):
    client = op.new_sdk_client(p, timeout=25.0)
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": f"conversation so far:\n(nothing yet)\n\nlearner just said (in Hindi/Hinglish): {line}\n\nReturn ONLY the JSON object."}]
    t0 = time.time()
    try:
        raw = await client.chat.completions.with_raw_response.create(model=model, messages=msgs, max_tokens=900, temperature=0.6, extra_body=p.get("extra") or {})
        resp = raw.parse()
        text = op.strip_reasoning(resp.choices[0].message.content or "").strip()
        ok, hi = judge(text)
        return {"kind": "ok" if text else "empty", "json": ok, "hindi": round(hi, 2), "ms": int((time.time() - t0) * 1000), "tokens": getattr(getattr(resp, "usage", None), "completion_tokens", 0)}
    except Exception as e:
        out = classify.classify(p["name"], e)
        return {"kind": out.kind, "http": out.http, "scope": out.scope, "ms": int((time.time() - t0) * 1000), "why": why(e)}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def main(only):
    system = system_prompt()
    chain = {p["name"]: p for p in settings.providers()}
    for name in (only or ["gemini", "openrouter", "groq"]):
        p = chain.get(name)
        print(f"\n== {name}")
        if p is None:
            print("   no key configured for it in backend/.env - skipped")
            continue
        have = await list_models(name, p["key"])
        print("   its own model list: " + (f"{len(have)} models" if have else "could not be read (a rejected key, or no list)"))
        if have is not None:
            for m in CANDIDATES[name]:
                print(f"   listed? {m}: {'yes' if m in have else 'NO'}")
        configured = list(p["models"])
        print(f"   DuSu is configured to use: {configured}")
        for m in CANDIDATES[name]:
            q = dict(p, models=[m])
            runs = []
            for line in LINES:
                runs.append(await call(q, m, system, line))
                await asyncio.sleep(1.0)
            tag = "  <- in use today" if m in configured else ""
            print(f"   {m}{tag}")
            for line, r in zip(LINES, runs):
                print(f"      {line!r:28} {json.dumps(r)}")


asyncio.run(main(sys.argv[1:]))
