"""Resume Interview - the four model calls (A requirements, B match, C plan, D answer feedback) with the retry ladder.

Pure orchestration, no database (service.py persists). `llm` is passed in (the real one in production, a stub in tests) like practice.analyze.

The ladder (plan §9): the chain trims a reply that hits its token cap to its last sentence - for JSON that is garbage, and ~1 reply in 9 from the
live Gemini model is syntactically broken. So a reply that does not VALIDATE is retried once with the compact schema (smaller expected output),
and after that the caller falls back to something deterministic. A call that RAISES (every provider failed or is rate limited) is NOT retried:
the chain already walked every provider, a second walk costs up to 50 s more and hits the same wall.
"""

from __future__ import annotations

import math

from .. import practice as P
from . import prompts, rules

# (full, compact) max_tokens. The compact rung expects a smaller reply but never gets LESS room than the first: when rung 1 failed because a reasoning
# model spent its tokens thinking (finish_reason=length), a smaller cap on the retry would only fail the same way.
CAPS = {"jd": (1600, 1600), "match": (2200, 2200), "plan": (2400, 2400), "answer": (1800, 1800)}
MATCH_COVERAGE = 0.8                # a match reply must judge at least this share of the requirements


class Unavailable(RuntimeError):
    """No usable reply. `parse_failed` is True when the chain DID answer but nothing validated (the caller may fall back to something
    deterministic); False when the chain itself failed (quota / every provider down), where a fallback would only hide a real outage."""

    def __init__(self, msg: str = "", parse_failed: bool = False):
        super().__init__(msg)
        self.parse_failed = parse_failed


async def _ladder(llm, rungs: list, temperature: float = 0.2):
    """rungs: [(system, user, max_tokens, validate)]; validate(reply) -> result | None. First valid result wins."""
    last: Exception | None = None
    for system, user, cap, validate in rungs:
        try:
            reply = await llm.assess(system, user, max_tokens=cap, temperature=temperature)
        except Exception as e:                                   # the chain is exhausted - do not walk it again
            raise Unavailable(str(e)) from e
        try:
            res = validate(reply)
        except Exception as e:                                   # a validator bug must not become a 500 on a learner
            last = e
            res = None
        if res is not None:
            return res
    raise Unavailable(str(last) if last else "no parseable reply", parse_failed=True)


async def extract_requirements(llm, jd_text: str) -> tuple[dict, list[dict]]:
    """A: job description -> ({title, company, level}, [{id, text, type, keywords}]). Needs at least one requirement to count."""
    def val(d):
        role, reqs = rules.validate_requirements(d)
        return (role, reqs) if reqs else None
    u = prompts.jd_user(jd_text)
    return await _ladder(llm, [(prompts.jd_system(), u, CAPS["jd"][0], val), (prompts.jd_system(True), u, CAPS["jd"][1], val)])


async def analyze_match(llm, resume_text: str, reqs: list[dict]) -> dict:
    """B: resume x requirements -> {requirements:[REQ], edits:[EDIT], strengths, notes}. Statuses are finalised in code (verified evidence)."""
    ids = {r["id"] for r in reqs}

    need = max(1, math.ceil(MATCH_COVERAGE * len(ids)))

    def val(d):
        if not isinstance(d, dict) or d.get("error") or not isinstance(d.get("items"), list) or not d["items"]:
            return None
        # a reply that skips most requirements (a truncated or lazy answer) is NOT a result: a skipped requirement counts as "partial" (half credit), so
        # accepting it would inflate the score - and the wrong score would be cached as done. The compact rung gets the next try.
        judged = {str(it.get("id")) for it in d["items"] if isinstance(it, dict) and str(it.get("id")) in ids and it.get("status") in ("met", "partial", "missing")}
        if len(judged) < need:
            return None
        return {"requirements": rules.finalize_requirements(reqs, d["items"], resume_text),
                "edits": rules.validate_edits(d.get("edits"), resume_text, ids),
                "strengths": rules._brief_list(d.get("strengths"), 3, 120),
                "notes": [{"issue": rules.clean_str(n.get("issue"), 80), "fix": rules.clean_str(n.get("fix"), 110)}
                          for n in (d.get("notes") if isinstance(d.get("notes"), list) else [])[:2]
                          if isinstance(n, dict) and rules.clean_str(n.get("issue"), 80)]}
    u = prompts.match_user(reqs, resume_text)
    return await _ladder(llm, [(prompts.match_system(), u, CAPS["match"][0], val), (prompts.match_system(True), u, CAPS["match"][1], val)])


async def build_plan(llm, role: dict, reqs: list[dict], resume_text: str, settings: dict, asked_before: list[str] | None = None) -> tuple[dict, list[dict]]:
    """C: -> (brief, [{kind, text, why, req}]). At least 4 valid questions or the rung does not count (service tops up from the bank)."""
    def val(d):
        brief, qs = rules.validate_plan(d, reqs, settings)
        if len(qs) < 4:
            return None
        if qs[0]["kind"] != "intro":                          # the interview always opens with an introduction
            intro = rules.bank_intro(rules.bank_ctx(role.get("title", ""), role.get("company", ""), brief["skills"]), {P.norm(q["text"]) for q in qs})
            if intro:
                qs.insert(0, intro)
        return brief, qs
    u = prompts.plan_user(role, reqs, resume_text, asked_before)
    return await _ladder(llm, [(prompts.plan_system(settings), u, CAPS["plan"][0], val), (prompts.plan_system(settings, True), u, CAPS["plan"][1], val)],
                         temperature=0.4)


async def answer_feedback(llm, *, question: str, kind: str, why: str, brief: dict, resume_text: str, jd_text: str, transcript: str,
                          delivery: dict, flags: dict, feedback_lang: str, itype: str) -> dict:
    """D: -> the FEEDBACK object (validated, quote-checked, scored). Raises Unavailable; the caller keeps the transcript and offers Retry."""
    lines = prompts.relevant_lines(resume_text, question, why)
    u = prompts.answer_user(question, kind, why, brief, lines, delivery, transcript)

    def val(d):
        return rules.build_feedback(d, transcript=transcript, resume_text=resume_text, jd_text=jd_text, flags=flags, delivery=delivery,
                                    feedback_lang=feedback_lang)
    return await _ladder(llm, [(prompts.answer_system(feedback_lang, itype), u, CAPS["answer"][0], val),
                               (prompts.answer_system(feedback_lang, itype, True), u, CAPS["answer"][1], val)])
