"""OWNER-RUN check of Talk against the REAL model chain - Hindi quality of the subtitle, latency, and how often a fix is proposed / verified / dropped.

*** THIS SPENDS MODEL CALLS (a few dozen free-tier requests). It is never run by the test suites and it refuses to run unless TALK_REAL=1. ***
No key is stored anywhere: give your OWN keys in the environment, exactly as you would add them in More -> My AI keys.  The keys, and anything the providers say, are never printed;
the learner messages below are synthetic (no learner data).

    cd ~/Desktop/DuSu-mongo
    docker run --rm -e TALK_REAL=1 -e GROQ_API_KEY -e GEMINI_API_KEY -e OPENROUTER_API_KEY \\
        [-e CLOUDFLARE_ACCOUNT_ID -e CLOUDFLARE_API_TOKEN -e ZAI_API_KEY -e SARVAM_API_KEY] \\
        -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-mongo-test python /tests/talk/real_model.py

Environment:  TALK_ENGINE  0 = old walker, 1 = per-key walker, 2 = validated walk (default 2: what Talk is built for)      TALK_SLEEP  seconds between turns (default 1.5)
              TALK_ONLY    en_sub | en   (default both)                                                                   TALK_TURNS  how many of the synthetic messages (default all 10)

What it measures, per support level (en_sub = English + Hindi subtitle, en = English only), over 6 messages that contain ONE real slip and 4 that are clean:
  * latency of a turn (median / max) - the plan's target is a reply in a few seconds, the Hindi subtitle is the expensive part (en_sub vs en shows it)
  * the reply is English only; the subtitle is present, mostly Devanagari, and follows the writing rules (तुम not आप / तू, no verb that guesses the learner's gender) - RAW, before the server's filter
  * the fix: proposed on a slip / proposed on a clean message (the model's false-positive rate) / how many of the proposals the code VERIFIED / how many it dropped
  * failures of the walk (nothing usable from any model)
It prints three subtitle samples so you (or a native reader) can judge the Hindi by eye.  Exit 0 always when it ran (it reports, it does not gate); 2 = not run.
"""
import asyncio
import os
import statistics
import sys
import time

if os.environ.get("TALK_REAL") != "1":
    print("not run: set TALK_REAL=1 (this spends real model calls with YOUR keys)")
    sys.exit(2)

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/talk")

from app.interview import engine as E                    # noqa: E402
from app.providers import llm as REAL                    # noqa: E402
from app.providers.openrouter_provider import set_active_keys   # noqa: E402
from app.talk import reply as R, topics as T             # noqa: E402

KEYS = {k: os.environ.get(v, "").strip() for k, v in (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"), ("zai", "ZAI_API_KEY"), ("sarvam", "SARVAM_API_KEY"))}
if os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN"):
    KEYS["cloudflare"] = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip() + ":" + os.environ["CLOUDFLARE_API_TOKEN"].strip()
KEYS = {k: v for k, v in KEYS.items() if v}
if not KEYS:
    print("not run: no key in the environment (GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY / ...)")
    sys.exit(2)

# (message, the slip's quote or None)  - synthetic learners at A1-A2
MESSAGES = [
    ("yesterday i go to the market with my mother", "i go"),
    ("my brother have a new bike", "brother have"),
    ("she is go to school every day", "is go"),
    ("i am agree with you about this", "am agree"),
    ("we was very happy on the festival", "we was"),
    ("i buyed some sweets for my family", "buyed"),
    ("I like to watch cricket with my friends", None),
    ("My father works in a bank and he likes his job", None),
    ("We usually eat dinner at eight o'clock", None),
    ("I want to learn English for a better job", None),
]
N_TURNS = int(os.environ.get("TALK_TURNS", len(MESSAGES)))
SLEEP = float(os.environ.get("TALK_SLEEP", "1.5"))
ENGINE = int(os.environ.get("TALK_ENGINE", "2"))
ONLY = [s for s in (os.environ.get("TALK_ONLY") or "en_sub,en").split(",") if s in ("en_sub", "en")]


class Proxy:
    """The real llm, remembering the RAW object the model returned (before the server's filters) for each Talk call."""
    def __init__(self):
        self.raw: list = []

    def __getattr__(self, name):
        return getattr(REAL, name)

    async def assess(self, *a, **kw):
        d = await REAL.assess(*a, **kw)
        self.raw.append(d)
        return d


def topic():
    ts = T.for_band("A2") or T.for_band("A1") or T.for_band("B1")
    if ts:
        return ts[0]
    import fixtures as F
    return T.Bank.from_rows(F.rows("A2", 3)).topics[0]


async def run_level(support: str) -> dict:
    px = Proxy()
    E.llm = px
    set_active_keys(KEYS, uid="talk-real-model", engine=ENGINE)
    s = E.Session("talk", "Asha", "", level="A2", talk={"topic": topic(), "support": support, "note": ""})
    await s.talk_turn("", first=True)
    st = {"lat": [], "fail": 0, "reply_ok": 0, "hi_present": 0, "hi_dev_ok": 0, "hi_rule_ok": 0, "hi_n": 0, "slip_n": 0, "slip_found": 0, "slip_proposed": 0, "clean_n": 0, "clean_fix": 0,
          "clean_proposed": 0, "dropped": 0, "proposed": 0, "samples": []}
    for msg, slip in MESSAGES[:N_TURNS]:
        px.raw.clear()
        t0 = time.time()
        try:
            r = await s.talk_turn(msg)
        except Exception as e:                           # class name only: provider errors can echo the request
            st["fail"] += 1
            print(f"    [{support}] turn failed: {type(e).__name__}")
            await asyncio.sleep(SLEEP)
            continue
        st["lat"].append(time.time() - t0)
        raw = px.raw[-1] if px.raw and isinstance(px.raw[-1], dict) else {}
        rr = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
        st["reply_ok"] += int(bool(rr) and not any("ऀ" <= c <= "ॿ" for c in rr))
        if support == "en_sub":
            hi = raw.get("hi") if isinstance(raw.get("hi"), str) else ""
            st["hi_n"] += 1
            st["hi_present"] += int(bool(hi))
            st["hi_dev_ok"] += int(bool(hi) and T.dev_share(hi) >= 0.5)
            st["hi_rule_ok"] += int(bool(hi) and not T.hindi_problems(hi))
            if hi and len(st["samples"]) < 3:
                st["samples"].append((rr, hi))
        proposed = raw.get("fix") not in (None, "", [], {})
        shown = "fix" in r
        if slip:
            st["slip_n"] += 1
            st["slip_proposed"] += int(proposed)
            st["slip_found"] += int(shown and slip.split()[0] in r["fix"]["q"].lower())
        else:
            st["clean_n"] += 1
            st["clean_proposed"] += int(proposed)
            st["clean_fix"] += int(shown)
        st["proposed"] += int(proposed)
        st["dropped"] += int(proposed and not shown)
        await asyncio.sleep(SLEEP)
    return st


def pct(a, b):
    return f"{a}/{b}" + (f" ({100 * a // b}%)" if b else "")


async def main():
    print(f"Talk against the real chain: providers {sorted(KEYS)} (keys not shown), walk level {ENGINE}, {N_TURNS} messages per level\n")
    for sup in ONLY:
        st = await run_level(sup)
        lat = st["lat"]
        print(f"== support = {sup}")
        print(f"   turns answered {len(lat)}/{N_TURNS}, walk failures {st['fail']}")
        if lat:
            print(f"   latency  median {statistics.median(lat):.1f}s  max {max(lat):.1f}s")
        print(f"   reply is English only        {pct(st['reply_ok'], len(lat))}")
        if sup == "en_sub":
            print(f"   subtitle present             {pct(st['hi_present'], st['hi_n'])}")
            print(f"   ... mostly Devanagari        {pct(st['hi_dev_ok'], st['hi_n'])}")
            print(f"   ... passes the Hindi rules   {pct(st['hi_rule_ok'], st['hi_n'])}   (raw, before the server drops a bad one)")
        print(f"   slip messages: fix proposed  {pct(st['slip_proposed'], st['slip_n'])}, verified and shown on the right words {pct(st['slip_found'], st['slip_n'])}")
        print(f"   clean messages: fix proposed {pct(st['clean_proposed'], st['clean_n'])}, shown {pct(st['clean_fix'], st['clean_n'])}   <- the learner's false-positive rate")
        print(f"   proposals dropped by the code's verification: {pct(st['dropped'], st['proposed'])}")
        for rr, hi in st["samples"]:
            print(f"   sample  EN: {rr}\n           HI: {hi}")
        print()


asyncio.run(main())
