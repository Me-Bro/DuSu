"""A stub model for the Grammar Coach tests: no network, deterministic, counts every call.

`assess(system, payload, ...)` reads the numbered sentences out of the fenced payload and answers from a small table of seeded mistakes, so a test
can say exactly what the "model" found. Knobs: `calls` (a Counter per rung), `fail` (raise), `garbage` (unusable reply), `delay`, `rules` (extra
(substring, rule, quote, fix, conf) rows), `skip_words` (sentences containing these are verdict skip)."""

import asyncio
import re
from collections import Counter

SEEDS = [
    ("yesterday i go", "tn.past_marker", "go", "went", "s"),
    ("i buy some vegetable", "ag.quantifier_number", "some vegetable", "some vegetables", "s"),
    ("informations", "wd.noun_number", "informations", "information", "s"),
    ("i am engineer", "ar.missing_a", "engineer", "an engineer", "s"),
    ("discuss about", "pr.extra_prep", "discuss about", "discuss", "s"),
    ("he go to office", "ag.s_missing_3p", "he go", "he goes", "s"),
    ("what you want", "st.question_order", "what you want", "what do you want", "s"),
    ("do the needful", "ind.lexicon#do the needful", "do the needful", "please take care of it", "s"),
    ("a maybe mistake", "ar.a_an", "a maybe", "maybe", "l"),
]


class StubLLM:
    def __init__(self):
        self.calls = Counter()
        self.fail = None             # an exception instance to raise
        self.garbage = False
        self.delay = 0.0
        self.rules = list(SEEDS)
        self.skip_words = ("hai", "nahi")
        self.seen_payloads: list[str] = []
        self.seen_kwargs: list[dict] = []

    def reset(self):
        self.calls.clear()
        self.fail = None
        self.garbage = False
        self.delay = 0.0
        self.seen_payloads.clear()
        self.seen_kwargs.clear()

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7, first=None, cool=True):
        self.seen_payloads.append(payload)
        self.seen_kwargs.append({"max_tokens": max_tokens, "temperature": temperature, "first": first, "cool": cool, "prefer_fast": prefer_fast})
        rung = "compact" if "w = the reason" not in system else "full"
        self.calls[rung] += 1
        self.calls["total"] += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        if self.garbage:
            return {"error": "scoring_parse_failed", "raw": "nope"}
        sents = []
        for line in payload.splitlines():
            m = re.match(r"^(\d+)\. (.*)$", line)
            if m:
                sents.append((int(m.group(1)), m.group(2)))
        out = []
        for i, t in sents:
            low = t.lower()
            if any(w in low.split() for w in self.skip_words):
                out.append({"i": i, "v": "skip", "k": "not_english", "m": []})
                continue
            marks = []
            for sub, rule, q, f, c in self.rules:
                if sub in low:
                    qq = re.search(re.escape(q), t, re.I)
                    if qq:
                        marks.append({"r": rule, "q": qq.group(0), "f": f, "c": c, "w": "stub note"})
            out.append({"i": i, "v": "fix" if marks else "ok", "k": "", "m": marks})
        return {"s": out}
