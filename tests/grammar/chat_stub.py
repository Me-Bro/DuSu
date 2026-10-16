"""The chat / memory / report stub model shared by ws_harness.py and e2e_server.py (deterministic, records every call)."""

import json


class ChatStub:
    """The chat / memory / report model: deterministic, records every call (kind, system, transcript or payload)."""
    def __init__(self):
        self.log: list = []

    async def next_question(self, system, transcript, seed=None):
        self.log.append(("next_question", system, json.dumps(transcript, sort_keys=True), seed))
        return "That sounds interesting - tell me a little more about it, what happened next, and how did you feel about it?"

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7, first=None, cool=True):
        self.log.append(("assess", system[:80], payload[:400], max_tokens))
        return {"summary": "Practised speaking.", "facts": {}, "events": [], "no_hindi": True, "asked_question": False, "next_hook": "continue", "recent_questions": [],
                "scores": {"confidence": 60, "continuity": 60, "vocabulary": 60, "grammar_trend": 60, "depth": 60}, "genuine_effort": True,
                "english": "", "reply_hindi": "namaste, aaj ka din kaisa raha aapka, mujhe batao zara dhyan se", "next_question_hindi": "aaj kya kiya?", "tip": "", "mood": "", "context": {}}

    async def score(self, system, transcript, max_tokens=1200):
        self.log.append(("score", system[:80], json.dumps(transcript, sort_keys=True)))
        return {"overall": 70, "scores": {"grammar": 61, "fluency": 70, "confidence": 70, "communication": 70, "vocabulary": 70, "professionalism": 70},
                "filler_words": [], "strengths": ["clear"], "fixes": ["add examples"], "better_answer": {"question": "q", "their_answer": "a", "improved": "b"}}

    async def translate(self, system, text, max_tokens=120):
        self.log.append(("translate", text))
        return "ok"

    async def generate(self, system, prompt, max_tokens=500):
        self.log.append(("generate", prompt[:100]))
        return "ok"
