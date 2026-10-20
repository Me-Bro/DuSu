"""A stub model for the Resume Interview tests: answers each stage with canned JSON and counts the calls (so "a duplicate request = one model call" is provable)."""

import asyncio
from collections import Counter


class StubLLM:
    """Answers each stage with canned JSON and counts the calls. `fail[stage]` raises; `delay` simulates a slow provider (so concurrent requests overlap)."""

    def __init__(self):
        self.n = Counter()
        self.fail: dict[str, Exception] = {}
        self.delay = 0.0
        self.weak_marker = "ANSWER_WEAK"

    def stage(self, system: str) -> str:
        if "You read a job description" in system:
            return "jd"
        if "You compare a candidate's resume" in system:
            return "match"
        if "Prepare a mock interview" in system:
            return "plan"
        return "answer"

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7):
        st = self.stage(system)
        self.n[st] += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if st in self.fail:
            raise self.fail[st]
        if st == "jd":
            return {"title": "Data Analyst", "company": "Acme Corp", "level": "mid", "requirements": [
                {"text": "2+ years of data analysis experience", "type": "must", "keywords": []},
                {"text": "Strong SQL skills", "type": "must", "keywords": ["SQL"]},
                {"text": "Dashboards in Power BI or Tableau", "type": "must", "keywords": ["Power BI", "Tableau"]},
                {"text": "Python or R for data cleaning", "type": "must", "keywords": ["Python"]},
                {"text": "Explain insights to non-technical stakeholders", "type": "nice", "keywords": []},
                {"text": "Snowflake or BigQuery", "type": "nice", "keywords": ["Snowflake", "BigQuery"]}]}
        if st == "match":
            improved = "Loaded data into Snowflake" in payload          # only the improved resume says it (the requirement text mentions Snowflake too)
            items = [{"id": "r1", "status": "met", "evidence": "Data analyst with 2 years of experience"},
                     {"id": "r2", "status": "met", "evidence": "Wrote SQL queries on PostgreSQL"},
                     {"id": "r3", "status": "met", "evidence": "Built Power BI dashboards for the sales team"},
                     {"id": "r4", "status": "partial", "evidence": ""},
                     {"id": "r5", "status": "met" if improved else "missing", "evidence": "Presented monthly insights to the regional manager" if improved else ""},
                     {"id": "r6", "status": "met" if improved else "missing", "evidence": "Loaded data into Snowflake for the finance team" if improved else ""}]
            edits = [{"priority": "high", "type": "add", "section": "Skills", "to": "Snowflake or BigQuery - add only if you have used them", "why": "The job asks for it", "req": ["r6"]},
                     {"priority": "medium", "type": "reword", "section": "Experience", "from": "Presented monthly insights to the regional manager",
                      "to": "Presented monthly insights to the regional manager, which [X]", "why": "show the result", "req": ["r5"]}]
            return {"items": items, "edits": [] if improved else edits, "strengths": ["Dashboards for sales"], "notes": []}
        if st == "plan":
            qs = [{"kind": "intro", "text": "Please introduce yourself and your background in data analysis.", "why": "A standard opener", "req": []},
                  {"kind": "resume", "text": "Tell me about the Power BI dashboards you built for the sales team.", "why": "Your resume mentions Power BI dashboards", "req": ["r3"]},
                  {"kind": "requirement", "text": "How have you used SQL on large tables?", "why": "The job needs strong SQL", "req": ["r2"]},
                  {"kind": "gap", "text": "The job asks for Snowflake and I did not see it on your resume. How would you get up to speed?", "why": "A requirement missing from your resume", "req": ["r6"]},
                  {"kind": "behavioral", "text": "Tell me about a time you explained a complex finding to a non-technical manager.", "why": "Stakeholder communication", "req": ["r5"]},
                  {"kind": "motivation", "text": "Why do you want to work as a data analyst at Acme?", "why": "Motivation", "req": []},
                  {"kind": "situational", "text": "If two urgent reports were due together, how would you decide what to do first?", "why": "Prioritising", "req": []}]
            return {"brief": {"summary": "Data analyst, two years, dashboards and SQL.", "level": "experienced", "strengths": ["SQL", "Dashboards"], "gaps": ["Snowflake"],
                              "projects": [{"name": "Churn analysis", "what": "pandas on telecom data"}], "skills": ["SQL", "Power BI", "Python"]}, "plan": qs}
        weak = self.weak_marker in payload
        return {"scores": {"relevance": 2 if weak else 4, "specificity": 2 if weak else 4, "structure": 2 if weak else 4, "language": 2 if weak else 4},
                "worked": ["Named the tool"], "mistakes": [{"type": "tense", "said": "I make dashboard", "better": "I made a dashboard", "why": "past tense"}] if weak else [],
                "content_notes": ["Add the business impact"], "improvements": [{"issue": "No result", "how": "End with a number"}],
                "better_answer": "At Acme I built dashboards for the sales team and cut the weekly report from 2 days to 3 hours.",
                "follow_up": "How did you check that the new numbers were right?", "resume_check": None, "genuine_effort": True}


