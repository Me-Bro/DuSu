"""A test double of `llm` (providers/openrouter_provider.OpenRouterLLM) for the Talk tests.  It MIRRORS the interface it replaces - `assess(..., schema=, check=)`, `v3_active()`, `last_bad()` - and, like the
real validated walk, ENFORCES the schema and the `check` on every talk reply it is about to return (with `v3=True`: a reply the real walk would reject comes back as the parse-failure sentinel and
`last_bad()` holds a BadReplyError; with `v3=False`, the legacy walker, nothing is enforced and the raw object comes back).  A stub that did not enforce them would let a wrong schema or a wrong `check`
pass every test (the lesson of tests/grammar/chat_stub.py, which once did not even know the keywords).

Every call is recorded in `log` (kind, system, payload / transcript, keyword arguments); `talk_calls()` is the model calls a Talk turn made.
Scripting: `talk_script` is a queue of raw replies (dict or str) used one per talk call; when it is empty `talk_default(payload)` answers.  `raise_next` raises on the next talk call."""

import json
import re

TALK_PREFIX = "You are DuSu, a warm, patient English speaking coach"

MEMORY = {"summary": "Practised speaking about a topic.", "facts": {}, "events": [], "no_hindi": True, "asked_question": False, "next_hook": "", "recent_questions": [],
          "scores": {"confidence": 60, "continuity": 60, "vocabulary": 60, "grammar_trend": 60, "depth": 60}, "genuine_effort": True}


def default_reply(payload: str) -> dict:
    return {"reply": "That sounds nice! What did you do next?", "hi": "अच्छा लगा! फिर तुमने आगे क्या किया?", "fix": None}


class TalkStub:
    def __init__(self, v3: bool = False):
        from app.keys.errors import BadReplyError                      # noqa: F401  (imported lazily: the module needs the backend on sys.path)
        self.v3 = v3
        self.log: list = []
        self.talk_script: list = []
        self.raise_next = None
        self._bad = None
        self.talk_default = default_reply

    # ---- the interface of OpenRouterLLM
    def v3_active(self):
        return self.v3

    def last_bad(self):
        return self._bad

    def talk_calls(self) -> list:
        return [c for c in self.log if c.get("talk")]

    def chat_calls(self) -> list:
        return [c for c in self.log if c["kind"] in ("assess", "next_question", "score", "translate", "generate")]

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7, first=None, cool=True, schema=None, check=None):
        from app.keys.errors import BadReplyError
        from app.providers.openrouter_provider import json_accept, _extract_json
        is_talk = system.startswith(TALK_PREFIX)
        self.log.append({"kind": "assess", "talk": is_talk, "system": system, "payload": payload, "max_tokens": max_tokens, "prefer_fast": prefer_fast, "temperature": temperature,
                         "schema": schema, "has_check": check is not None, "first": first, "cool": cool})
        if not is_talk:
            return dict(MEMORY)
        if self.raise_next is not None:
            e, self.raise_next = self.raise_next, None
            raise e
        raw = self.talk_script.pop(0) if self.talk_script else self.talk_default(payload)
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        if self.v3:
            reason = json_accept(schema, check)(text, "stop")          # the real walk's own acceptance test
            if reason:
                self._bad = BadReplyError(reason, [], own=True, reasons=[reason])
                return {"error": "scoring_parse_failed", "raw": ""}
            self._bad = None
        return raw if isinstance(raw, dict) else _extract_json(text)

    async def next_question(self, system, transcript, seed=None):
        self.log.append({"kind": "next_question", "talk": False, "system": system, "payload": json.dumps(transcript, sort_keys=True), "seed": seed})
        return "That sounds interesting - tell me a little more about it, what happened next, and how did you feel about it?"

    async def score(self, system, transcript, max_tokens=1200):
        self.log.append({"kind": "score", "talk": False, "system": system, "payload": json.dumps(transcript, sort_keys=True)})
        return {"overall": 70, "scores": {"grammar": 61, "fluency": 70, "confidence": 70, "communication": 70, "vocabulary": 70, "professionalism": 70},
                "filler_words": [], "strengths": ["clear"], "fixes": ["add examples"], "better_answer": {"question": "q", "their_answer": "a", "improved": "b"}}

    async def translate(self, system, text, max_tokens=120):
        self.log.append({"kind": "translate", "talk": False, "system": system, "payload": text})
        return "ok"

    async def generate(self, system, prompt, max_tokens=500):
        self.log.append({"kind": "generate", "talk": False, "system": system, "payload": prompt})
        return "ok"


def learner_line(payload: str) -> str:
    m = re.search(r"learner just said: (.*)\Z", payload, re.S)
    return m.group(1).strip() if m else ""
