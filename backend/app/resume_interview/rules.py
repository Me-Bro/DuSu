"""Resume Interview - rules: limits, input cleaning, match score, answer scoring, question validation + bank, the computed report.

Pure functions (no database, no network): every number and every sentence the screens show is computed or checked here, so it can be
tested offline (DUSU_RESUME_INTERVIEW_PLAN.md §9). Two ideas run through the file:

* MEASURE what can be measured, and CHECK what the model says. The match score comes from per-requirement statuses; a status of "met" needs
  evidence that really occurs in the resume (a false "missing" is the most trust-damaging error, so unverifiable evidence is "partial", never
  "missing"); a quoted mistake is shown only if its words are in the transcript; numbers in a "better answer" must come from the learner's
  own words or documents, otherwise they are bracketed. The model only judges.
* The model's numbers wobble (a single score moved 12-15 points on the same speech, practice.py), so the per-answer judgements are an
  anchored 1-5 scale blended with code-computed evidence, and the screens show BANDS per answer, numbers only in aggregates.
"""

from __future__ import annotations

import math
import re
import statistics
import unicodedata

from .. import practice as P

RULES_VERSION = 1                      # bump when prompts / rules change meaning: cached analyses are recomputed

# ----------------------------------------------------------------------------- limits
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 300 * 1024
DOC_RAW_CAP = 60_000                   # cap BEFORE any regex runs
RESUME_MODEL_CHARS = 9_000
JD_STORE_CHARS = 12_000
RESUME_MIN_CHARS = 300
JD_MIN_CHARS = 200
MAX_RESUMES, MAX_JDS, MAX_SESSIONS = 10, 15, 100
SESSIONS_PER_DAY, ANSWERS_PER_DAY, ANALYSES_PER_DAY = 10, 120, 30
MAX_ANSWERS = 40
FINISH_MIN = 3
MIN_ANSWER_WORDS, MIN_ANSWER_SEC, MAX_ANSWER_SEC, MAX_WPM = 25, 10.0, 180, 230
MAX_TRANSCRIPT_CHARS = 3500
MINUTES_CAP_PER_ANSWER = 185           # the XP clock: speaking time, never wall-clock (a session spans days)
CLAIM_TTL_S = 150                      # a pending claim older than this can be re-taken. The slowest honest run is a job analysis: two model calls,
                                       # each up to two ladder rungs of a 30 s chain walk (~120 s); a shorter TTL showed "failed" - and let a retry
                                       # start a second run - while the first was still working
MIN_REQUIREMENTS = 4                   # fewer and the job text is too vague to score
MAX_EDITS, MAX_REQS, MAX_PLAN = 5, 10, 14

DOC_KINDS = ("resume", "jd")
INTERVIEW_TYPES = ("mixed", "hr", "technical")
LEVELS = ("fresher", "experienced")
FEEDBACK_LANGS = ("hinglish", "en")
QKINDS = ("intro", "walkthrough", "resume", "requirement", "gap", "behavioral", "situational", "motivation", "technical", "strengths", "closing")
CATS = ("relevance", "specificity", "structure", "language", "delivery")
CAT_LABEL = {"relevance": "Relevance", "specificity": "Specific examples", "structure": "Structure", "language": "Language", "delivery": "Delivery"}
CAT_WEIGHTS = {"relevance": 25, "specificity": 20, "structure": 15, "language": 20, "delivery": 20}
ORDINAL = {1: 22, 2: 42, 3: 62, 4: 78, 5: 92}    # the Practice Room's anchors (90+ excellent · 75 good · 60 understandable · 40 hard · <25 unusable)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SURR = re.compile(r"[\ud800-\udfff]")
_WS = re.compile(r"\s+")


# ----------------------------------------------------------------------------- cleaning
def strip_bad(s) -> str:
    """NUL / control characters / lone surrogates out (Postgres rejects NUL; surrogates break the JSON driver)."""
    return _SURR.sub("", _CTRL.sub("", s)) if isinstance(s, str) else ""


def clean_str(s, n: int) -> str:
    """One line of text: control characters out, whitespace collapsed, capped. Non-strings -> ''. The input is sliced FIRST: every pass below
    is linear, but a 300 KB string should never be walked to keep 80 characters of it."""
    if not isinstance(s, str):
        return ""
    return _WS.sub(" ", strip_bad(s[: max(4096, n * 20)])).strip()[:n]


def clean_block(s, n: int) -> str:
    """Text that keeps its line breaks (a resume): same stripping, blank runs collapsed, trailing spaces gone, capped. LINEAR in the input: the
    slice comes first and no regex can backtrack over a long run of spaces (the old trailing-space regex took 12 s on 100 KB of spaces)."""
    if not isinstance(s, str):
        return ""
    t = strip_bad(s[: 2 * n + 2000]).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    t = "\n".join(ln.rstrip(" \xa0") for ln in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:n]


def clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        if isinstance(v, bool):
            raise ValueError
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def safe_json(v, depth: int = 0):
    """A copy that JSONB will accept: strings cleaned of NUL / surrogates, floats finite, containers bounded."""
    if depth > 8:
        return None
    if isinstance(v, str):
        return strip_bad(v)
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (list, tuple)):
        return [safe_json(x, depth + 1) for x in v[:200]]
    if isinstance(v, dict):
        return {strip_bad(str(k))[:80]: safe_json(x, depth + 1) for k, x in list(v.items())[:200]}
    return None


def clean_settings(body, base: dict | None = None) -> dict:
    b = body if isinstance(body, dict) else {}
    cur = dict(base or {})
    t = b.get("type", cur.get("type"))
    lv = b.get("level", cur.get("level"))
    fl = b.get("feedback_lang", cur.get("feedback_lang"))
    return {"type": t if t in INTERVIEW_TYPES else "mixed", "level": lv if lv in LEVELS else "experienced",
            "feedback_lang": fl if fl in FEEDBACK_LANGS else "hinglish"}


# ----------------------------------------------------------------------------- bands
def band_match(score) -> str:
    if score is None:
        return "unknown"
    return "strong" if score >= 80 else "good" if score >= 65 else "fair" if score >= 45 else "weak"


def band_cat(score) -> str:
    if score is None:
        return "unknown"                          # "not scored" is not "fair": a missing judgement must never look like a middling one
    return "strong" if score >= 80 else "good" if score >= 65 else "fair" if score >= 50 else "needs_work"


def _mean(vals) -> float | None:
    v = [x for x in vals if x is not None]
    return (sum(v) / len(v)) if v else None


def _r(x) -> int | None:
    return None if x is None else int(round(x))


# ----------------------------------------------------------------------------- loose text matching (PDF text is messy)
def loose(s) -> str:
    """NFKC (ligatures), casefold, soft hyphens out, punctuation -> single spaces. What 'the same words' means across PDF quirks."""
    t = unicodedata.normalize("NFKC", str(s or "")).replace("­", "").casefold()
    return _WS.sub(" ", re.sub(r"[\W_]+", " ", t)).strip()


def compact(s) -> str:
    return loose(s).replace(" ", "")


def kw_in_text(kw, text) -> bool:
    """A keyword as a whole token / phrase in the text ('c++', 'node.js', 'power bi'), not as part of another word."""
    k = unicodedata.normalize("NFKC", str(kw or "")).casefold().strip()
    if not k:
        return False
    pat = r"(?<![0-9a-z])" + r"\s+".join(re.escape(p) for p in k.split()) + r"(?![0-9a-z])"
    return re.search(pat, unicodedata.normalize("NFKC", str(text or "")).casefold()) is not None


def _lines(text) -> list[str]:
    return [ln.strip() for ln in str(text or "").split("\n") if ln.strip()]


_BULLET = re.compile(r"^(?:[•\-\*·▪►➢●○]|o(?=\s))\s*")


def _snap(line: str) -> str:
    """A real resume line as evidence / a `from` quote: the bullet character is not part of the words."""
    return clean_str(_BULLET.sub("", line), 160)


def verify_evidence(evidence, resume_text) -> tuple[bool, str]:
    """(found, the real resume line it was found in). A ladder, because PDF extraction mangles spacing and ligatures:
    normalised containment -> compact form (all non-alphanumerics gone) -> token overlap >= 0.8 inside one line or two."""
    ev = clean_str(evidence, 220)
    if len(ev) < 3:
        return False, ""
    el = loose(ev)
    lines = _lines(resume_text)
    ll = [loose(x) for x in lines]
    padded = " " + el + " "
    for ln, l in zip(lines, ll):
        if padded in (" " + l + " "):
            return True, _snap(ln)
    if padded in (" " + " ".join(ll) + " "):
        return True, ev[:160]
    ec = compact(ev)
    if len(ec) >= 6:
        for ln, l in zip(lines, ll):
            if ec in l.replace(" ", ""):
                return True, _snap(ln)
        if ec in "".join(l.replace(" ", "") for l in ll):
            return True, ev[:160]
    et = [t for t in el.split() if len(t) >= 3]
    if len(et) >= 3:
        sets = [set(l.split()) for l in ll]
        for i, ln in enumerate(lines):
            for span in (sets[i], sets[i] | (sets[i + 1] if i + 1 < len(sets) else set())):
                if sum(1 for t in et if t in span) / len(et) >= 0.8:
                    return True, _snap(ln)
    return False, ""


# ----------------------------------------------------------------------------- job requirements (call A) + match (call B)
def _kw_list(v) -> list[str]:
    out = []
    for k in v if isinstance(v, list) else []:
        k = clean_str(k, 30)
        if k and k.casefold() not in [x.casefold() for x in out]:
            out.append(k)
    return out[:3]


def validate_requirements(d) -> tuple[dict, list[dict]]:
    """Model JSON -> ({title, company, level}, [{id, text, type, keywords}]) with ids r1..rN. Anything unusable is dropped."""
    d = d if isinstance(d, dict) and not d.get("error") else {}
    lv = d.get("level")
    role = {"title": clean_str(d.get("title"), 80), "company": clean_str(d.get("company"), 60),
            "level": lv if lv in ("fresher", "junior", "mid", "senior") else ""}
    reqs, seen = [], set()
    for it in d.get("requirements") if isinstance(d.get("requirements"), list) else []:
        if not isinstance(it, dict):
            continue
        text = clean_str(it.get("text"), 120)
        key = loose(text)
        if not text or key in seen:
            continue
        seen.add(key)
        reqs.append({"id": f"r{len(reqs) + 1}", "text": text, "type": "must" if it.get("type") == "must" else "nice",
                     "keywords": _kw_list(it.get("keywords"))})
        if len(reqs) >= MAX_REQS:
            break
    return role, reqs


_RANK = {"missing": 0, "partial": 1, "met": 2}


def finalize_requirements(reqs: list[dict], items, resume_text: str) -> list[dict]:
    """The model's per-requirement verdicts -> final statuses. 'met' needs verified evidence; if every keyword of a requirement is in
    the resume it is at least 'partial'; a requirement the model skipped is 'partial' ('not clear'), never an invented 'missing'."""
    by_id = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            by_id[str(it.get("id"))] = it
    out = []
    for r in reqs:
        it = by_id.get(r["id"])
        kws = r.get("keywords") or []
        kw_all = bool(kws) and all(kw_in_text(k, resume_text) for k in kws)
        note = clean_str((it or {}).get("note"), 90)
        if it is None:
            status, evidence, note = "partial", "", note or "Not clear from your resume."
        else:
            status = it.get("status") if it.get("status") in _RANK else "missing"
            ok, snapped = verify_evidence(it.get("evidence"), resume_text)
            evidence = snapped if ok else ""
            if status == "met" and not ok:
                status, note = "partial", note or "No clear line in your resume for this."
            if status == "missing" and kw_all:
                status, note = "partial", note or "The words appear, but no line shows you did it."
            if status == "partial" and not evidence and not note:
                note = "Mentioned, but not shown in detail."
        out.append({"id": r["id"], "text": r["text"], "type": r["type"], "status": status, "evidence": evidence, "note": note})
    return out


_W = {"must": 3, "nice": 1}
_CREDIT = {"met": 1.0, "partial": 0.5, "missing": 0.0}


def match_score(reqs: list[dict]) -> int | None:
    """Σ weight × status ÷ Σ weight (must 3, nice 1; met 1, partial ½, missing 0). Under MIN_REQUIREMENTS there is nothing to score."""
    if len(reqs) < MIN_REQUIREMENTS:
        return None
    tot = sum(_W.get(r["type"], 1) for r in reqs)
    got = sum(_W.get(r["type"], 1) * _CREDIT.get(r["status"], 0.0) for r in reqs)
    return int(round(100 * got / tot)) if tot else None


def verdict(band: str) -> str:
    return {"strong": "Your resume covers most of what this job asks for.",
            "good": "A good match - a few gaps are worth fixing before the interview.",
            "fair": "Partly matching - several requirements are missing or unclear in your resume.",
            "weak": "A big gap between this resume and this job. It is still good practice: DuSu will lean on your projects, education and skills you can transfer.",
            "unknown": "The job description is too short to compare. Paste the whole description, with its requirements."}.get(band, "")


EDIT_TYPES = ("add", "reword", "quantify")
SECTIONS = ("Summary", "Skills", "Experience", "Projects", "Education", "Other")
_PRIO = {"high": 0, "medium": 1, "low": 2}


def validate_edits(items, resume_text: str, req_ids: set[str]) -> list[dict]:
    """<= 5 suggestions. A claim-adding edit (add / quantify) is ALWAYS 'only if true for you'; a `from` quote not found in the resume is dropped
    (a reword with no real source line is just an 'add')."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        to = clean_str(it.get("to"), 260)
        if len(to) < 8:
            continue
        typ = it.get("type") if it.get("type") in EDIT_TYPES else "add"
        frm = clean_str(it.get("from"), 200)
        if frm:
            ok, snapped = verify_evidence(frm, resume_text)
            frm = snapped if ok else ""
        if typ == "reword" and not frm:
            typ = "add"
        prio = it.get("priority") if it.get("priority") in _PRIO else "medium"
        sec = it.get("section") if it.get("section") in SECTIONS else "Other"
        out.append({"priority": prio, "type": typ, "section": sec, "from": frm, "to": to, "why": clean_str(it.get("why"), 140),
                    "only_if_true": typ in ("add", "quantify") or bool(it.get("only_if_true")),
                    "req": [r for r in (it.get("req") if isinstance(it.get("req"), list) else []) if r in req_ids][:3]})
    out.sort(key=lambda e: _PRIO[e["priority"]])
    out = out[:MAX_EDITS]
    for i, e in enumerate(out, 1):
        e["id"] = f"e{i}"
    return out


def diff_requirements(prev: list[dict], cur: list[dict]) -> list[dict]:
    """Requirements whose status changed between two analyses of the same job (ids are stable: the job's requirements are stored once)."""
    pm = {r["id"]: r for r in prev}
    out = []
    for r in cur:
        p = pm.get(r["id"])
        if p and p["status"] != r["status"]:
            out.append({"id": r["id"], "text": r["text"], "from": p["status"], "to": r["status"]})
    return out


def addressed_edits(prev_edits: list[dict], prev_reqs: list[dict], cur_reqs: list[dict], new_resume: str) -> list[str]:
    """Which earlier suggestions now look done: every requirement they point at moved up, or their wording now appears in the new resume."""
    pm = {r["id"]: _RANK[r["status"]] for r in prev_reqs}
    cm = {r["id"]: _RANK[r["status"]] for r in cur_reqs}
    res_loose = " " + loose(new_resume) + " "
    out = []
    for e in prev_edits:
        reqs = [r for r in e.get("req", []) if r in pm and r in cm]
        moved = bool(reqs) and all(cm[r] > pm[r] for r in reqs)
        wording = bool(e.get("to")) and len(loose(e["to"])) >= 12 and (" " + loose(e["to"]) + " ") in res_loose
        if moved or wording:
            out.append(e["id"])
    return out


# ----------------------------------------------------------------------------- questions: validation, protected topics, the bank
# Interview questions about a person's age, marriage, children, religion, caste, nationality, health or looks are illegal or improper in many
# places and DuSu must never ask them - nor teach a learner that they are normal. Phrase-level on purpose: a role about "customer age groups"
# or "healthcare data" must still be askable.
_PROTECTED = re.compile(
    r"(how old (are|r) you|\byour age\b|\bdate of birth\b|\bwhen (were|was) you born\b|\bmarital status\b|\bare you (married|single|pregnant|engaged)\b|"
    r"\b(planning|plan|plans) (to|on) (get married|marry|have (a )?(baby|babies|children|kids)|start a family)\b|"
    r"\bdo you have (any )?(children|kids|a (wife|husband|girlfriend|boyfriend|spouse))\b|"
    r"\byour (religion|caste|nationality|gender|sexual orientation|political (views|party)|skin colou?r|height|weight)\b|"
    r"\bwhat (religion|caste)\b|"
    # health / disability only when it is ASKED OF THE PERSON ("do you have a disability", "your health issues"): a question about designing for
    # users with a disability, or about healthcare data, is a legitimate question for an accessibility or a health-tech role
    r"\b(do you have|have you (got|had)|are you (suffering|living) (from|with)|suffer from|any of your|your) (any |a |an )?(disabilit\w*|medical condition|"
    r"health (issue|problem|condition)s?|illness(es)?|chronic \w+)\b|\bare you (disabled|handicapped)\b|"
    r"\bsend (me )?(a |your )?photo\b|\bwhere (is|are) your (parents|family) from\b)", re.I)
_IMPERATIVE = re.compile(r"^(please|kindly|let'?s|let us|start|begin|recall|think|pick|choose|consider|i'?d|i would|i want|"
                         r"tell|walk|describe|explain|talk|give|share|introduce|take|summari[sz]e|outline|how|what|why|when|where|which|who|can|could|do|did|have|would|"
                         r"if|imagine|suppose|is|are|was|were|will|should)\b", re.I)


def protected_topic(text) -> bool:
    return bool(_PROTECTED.search(str(text or "")))


def valid_question(q) -> str | None:
    t = clean_str(q, 260)
    if len(t) < 15 or protected_topic(t):
        return None
    if not (t.endswith("?") or _IMPERATIVE.match(t)):
        return None
    return t


def _brief_list(v, n: int, limit: int) -> list[str]:
    out = []
    for x in v if isinstance(v, list) else []:
        s = clean_str(x, limit)
        if s and s.casefold() not in [o.casefold() for o in out]:
            out.append(s)
    return out[:n]


def validate_plan(d, reqs: list[dict], settings: dict) -> tuple[dict, list[dict]]:
    """Model JSON -> (brief, [{kind, text, why, req}]). The first question is always an introduction; duplicates and protected topics are dropped."""
    d = d if isinstance(d, dict) and not d.get("error") else {}
    b = d.get("brief") if isinstance(d.get("brief"), dict) else {}
    projects = []
    for p in b.get("projects") if isinstance(b.get("projects"), list) else []:
        if isinstance(p, dict) and clean_str(p.get("name"), 60):
            projects.append({"name": clean_str(p.get("name"), 60), "what": clean_str(p.get("what"), 140)})
    brief = {"summary": clean_str(b.get("summary"), 420), "level": b.get("level") if b.get("level") in LEVELS else settings.get("level", "experienced"),
             "strengths": _brief_list(b.get("strengths"), 4, 120), "gaps": _brief_list(b.get("gaps"), 4, 120),
             "projects": projects[:4], "skills": _brief_list(b.get("skills"), 12, 30)}
    req_ids = {r["id"] for r in reqs}
    qs, seen = [], set()
    for it in d.get("plan") if isinstance(d.get("plan"), list) else []:
        if not isinstance(it, dict):
            continue
        text = valid_question(it.get("text"))
        key = P.norm(text) if text else ""
        if not text or key in seen:
            continue
        seen.add(key)
        kind = it.get("kind") if it.get("kind") in QKINDS else "resume"
        qs.append({"kind": kind, "text": text, "why": clean_str(it.get("why"), 170),
                   "req": [r for r in (it.get("req") if isinstance(it.get("req"), list) else []) if r in req_ids][:3]})
        if len(qs) >= MAX_PLAN:
            break
    qs.sort(key=lambda q: 0 if q["kind"] == "intro" else 1)         # stable: the introduction first, the model's order otherwise
    return brief, qs


BANK = [
    # (kind, template, needs a skill?)   {role_phrase} / {company_phrase} / {skill} are filled from the learner's own documents
    ("intro", "Tell me about yourself and how your background fits {role_phrase}.", False),
    ("intro", "Walk me through your resume in about two minutes.", False),
    ("motivation", "Why are you interested in {role_phrase}?", False),
    ("motivation", "Why do you want to work at {company_phrase}?", False),
    ("motivation", "Where do you see yourself in five years?", False),
    ("motivation", "What motivates you most in your work?", False),
    ("behavioral", "Tell me about a time you faced a tight deadline. What did you do?", False),
    ("behavioral", "Describe a time you disagreed with a teammate. How did you handle it?", False),
    ("behavioral", "Tell me about a mistake you made at work or college and what you learned from it.", False),
    ("behavioral", "Describe a project you are proud of. What was your role and what was the result?", False),
    ("behavioral", "Tell me about a time you had to learn something new very quickly.", False),
    ("behavioral", "Give an example of a time you took the lead without being asked.", False),
    ("behavioral", "Describe a time you received difficult feedback. What did you do next?", False),
    ("behavioral", "Tell me about a time you helped a teammate who was struggling.", False),
    ("behavioral", "Describe a time you had to explain something complex to someone who was not an expert.", False),
    ("behavioral", "Tell me about a time you had to work with very limited information.", False),
    ("situational", "Imagine you are given a task you have never done before. How would you start?", False),
    ("situational", "If two urgent tasks arrive at the same time, how do you decide what to do first?", False),
    ("situational", "How would you handle a teammate who is not delivering on time?", False),
    ("situational", "Suppose a stakeholder keeps changing the requirements. What would you do?", False),
    ("situational", "What would you do in your first thirty days in {role_phrase}?", False),
    ("situational", "If you found an error in work you had already submitted, what would you do?", False),
    ("strengths", "What are your top three strengths for {role_phrase}?", False),
    ("strengths", "What is one weakness you are working on, and how?", False),
    ("strengths", "What would your teammates or professors say you do best?", False),
    ("strengths", "How do you handle stress and pressure?", False),
    ("resume", "How have you used {skill} in a real project? Walk me through it.", True),
    ("resume", "What is the hardest problem you solved using {skill}?", True),
    ("resume", "How would you explain {skill} to someone who is new to it?", True),
    ("resume", "How do you keep your {skill} skills up to date?", True),
    ("technical", "Walk me through one project from end to end: the problem, your approach, the tools and the outcome.", False),
    ("technical", "What trade-offs did you make in your last project, and why?", False),
    ("technical", "Tell me about a problem that took you the longest to fix. How did you find the cause?", False),
    ("technical", "Which tools or technologies do you want to learn next, and why?", False),
    ("closing", "Do you have any questions for us?", False),
    ("closing", "Is there anything about your background you would like to add?", False),
]
_TYPE_KINDS = {"mixed": ("behavioral", "resume", "situational", "strengths", "technical", "motivation", "closing", "intro"),
               "hr": ("behavioral", "situational", "motivation", "strengths", "closing", "intro", "resume", "technical"),
               "technical": ("resume", "technical", "behavioral", "situational", "strengths", "motivation", "closing", "intro")}


def bank_ctx(role: str = "", company: str = "", skills=None, resume_skills=None) -> dict:
    sk = [s for s in (skills or []) + (resume_skills or []) if isinstance(s, str) and s.strip()]
    return {"role_phrase": f"the {role} role" if role else "this role", "company_phrase": company or "this company", "skills": sk}


def bank_intro(ctx: dict, asked_norms: set[str]) -> dict | None:
    """The opening question from the bank (the model is asked for one, but a plan that skipped it still opens with 'tell me about yourself')."""
    for kind, tmpl, _needs in BANK:
        if kind != "intro":
            continue
        text = tmpl.format(role_phrase=ctx["role_phrase"], company_phrase=ctx["company_phrase"], skill="")
        if P.norm(text) not in asked_norms and valid_question(text):
            return {"kind": "intro", "text": text, "why": "A standard opening question.", "req": []}
    return None


def pick_bank(ctx: dict, asked_norms: set[str], last_kind: str = "", itype: str = "mixed", seed: int = 0) -> dict | None:
    """The next question from the built-in bank: not asked yet, valid for this learner, a different kind from the last one when possible,
    in the order the interview type prefers. Deterministic for a given seed (tests, and a replayed request picks the same question)."""
    order = _TYPE_KINDS.get(itype, _TYPE_KINDS["mixed"])
    cands = []
    for kind, tmpl, needs_skill in BANK:
        skills = ctx.get("skills") or []
        if needs_skill and not skills:
            continue
        for sk in (skills[:3] if needs_skill else [None]):
            text = tmpl.format(role_phrase=ctx["role_phrase"], company_phrase=ctx["company_phrase"], skill=sk or "")
            if P.norm(text) in asked_norms or valid_question(text) is None:
                continue
            cands.append((kind, text))
            break                      # one skill variant per template per call; the next call finds the next skill
    if not cands:
        return None
    pool = [c for c in cands if c[0] != last_kind] or cands
    pool.sort(key=lambda c: (order.index(c[0]) if c[0] in order else 99))
    # rotate within the preferred kind so two sessions do not open identically; `seed` makes it reproducible
    first_kind = pool[0][0]
    same = [c for c in pool if c[0] == first_kind]
    kind, text = same[seed % len(same)]
    return {"kind": kind, "text": text, "why": "A common interview question for this kind of role."}


# ----------------------------------------------------------------------------- one answer: floors, delivery, evidence, scoring, validation
_HALLU_TOKENS = {"thank", "you", "thanks", "bye", "okay", "ok", "so", "um", "uh", "yeah", "yes", "no", "the", "end", "subscribe", "watching", "for"}


def is_hallucination(text: str, segments_raw=None) -> bool:
    """Whisper invents 'Thank you.' / 'Thanks for watching' on silence. Caught by the text alone (a few filler tokens, or one phrase repeated)
    and by the recogniser's own doubt (mean no_speech_prob high and avg_logprob low)."""
    toks = P.norm(text).split()
    if not toks:
        return True
    if len(toks) <= 8 and all(t in _HALLU_TOKENS for t in toks):
        return True
    if len(toks) >= 6 and len(set(toks)) / len(toks) < 0.3:
        return True
    segs = P.clean_segments(segments_raw)
    if segs:
        ns = statistics.mean(s[3] for s in segs)
        lp = statistics.mean(s[2] for s in segs)
        if ns >= 0.6 and lp <= -1.0:
            return True
    return False


def delivery_block(transcript: str, words_raw, segments_raw, duration_sec) -> dict:
    """What can be MEASURED about how the answer was spoken. With word timestamps (Groq) pace / pauses / restarts are measured; without them
    (Gemini) pace comes from the duration, restarts / fillers from the text, and pauses are 'not measured' - never a fake 0."""
    text = str(transcript or "").strip()[:MAX_TRANSCRIPT_CHARS]
    n_words = len(text.split())                  # the TRANSCRIPT decides how many words were said (it is what the floor, the XP and Finish count)
    wl = P.clean_words(words_raw)
    if wl and abs(len(wl) - n_words) > max(10, 0.35 * n_words):
        wl = []                                  # timestamps only say WHEN words were spoken: rows that do not match the transcript are not trusted
    m = P.compute_metrics(wl) if wl else None
    try:
        dur = max(0.0, min(float(duration_sec or 0), MAX_ANSWER_SEC + 30))
    except (TypeError, ValueError):
        dur = 0.0
    if m:
        dur = max(dur, m["span"])
    tn = P.norm(text)
    toks = tn.split()
    wpm = m["wpm"] if m else (int(round(n_words / (dur / 60.0))) if dur >= 5 else None)
    restarts = m["restarts"] if m else P.count_restarts(toks)
    fillers = P.count_fillers(tn)
    fill_n = sum(f["n"] for f in fillers)
    per100 = max(1.0, n_words / 100.0)
    parts, weights = [], []
    if wpm is not None:
        flow = P.score_pace(wpm)
        if m:
            flow = (flow + P.score_pauses(m["pause_ratio"], m["long_pauses"])) / 2
        parts.append(flow); weights.append(0.45)
    parts.append(P.score_restarts(restarts / per100)); weights.append(0.2)
    parts.append(P.score_hedges(tn, n_words)); weights.append(0.15)
    parts.append(P._clamp(100 - 12 * (fill_n / per100))); weights.append(0.2)
    score = int(round(sum(p * w for p, w in zip(parts, weights)) / sum(weights)))
    genuine = (wpm is None or wpm <= MAX_WPM) and (not m or m["span"] >= 0.35 * dur)
    return {"measured": bool(m), "words": n_words, "seconds": round(dur, 1), "wpm": wpm,
            "pauses": m["pauses"] if m else None, "longest_pause": m["longest_pause"] if m else None,
            "restarts": restarts, "fillers": fillers[:5], "score": score, "genuine": bool(genuine)}


def answer_floor(n_words: int, seconds: float) -> bool:
    """Too short to analyse: below this the model is not called, nothing is stored, the question stays open."""
    return n_words >= MIN_ANSWER_WORDS and seconds >= MIN_ANSWER_SEC


_NUMWORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand|lakh|lakhs|crore|crores|million|percent|double|triple)\b", re.I)
_RESULT = re.compile(r"\b(result(ed|s)?|reduc(ed|tion)|increas(ed|e)|improv(ed|ement)|sav(ed|ing)|achiev(ed|ement)|deliver(ed)|launch(ed)|grew|growth|boost(ed)?|"
                     r"cut|won|award(ed)?|selected|outcome|impact|helped|led to|so that|which (led|helped|reduced|improved))\b|%", re.I)
_EXAMPLE = re.compile(r"\b(for example|for instance|such as|in my (last|previous|current|first) (project|job|role|internship|company)|when i|one time|once|"
                      r"during my|in (my )?(college|internship|final year)|(?-i:at [A-Z]\w+))\b", re.I)    # "at Acme" is a place of work; "at home" / "at least" are not


def evidence_flags(transcript: str, skills=None) -> dict:
    """Facts about the answer computed in code (the model's 'specific / structured' judgement is blended with these, 50 / 50)."""
    t = str(transcript or "")
    words = len(t.split())
    sentences = len(re.findall(r"[.!?]+(?:\s|$)", t)) or (words // 18)
    return {"words": words, "sentences": sentences,
            "has_number": bool(re.search(r"\d", t) or _NUMWORDS.search(t)),
            "has_result": bool(_RESULT.search(t)), "has_example": bool(_EXAMPLE.search(t)),
            "named_item": any(kw_in_text(s, t) for s in (skills or []) if s)}


def specificity_points(f: dict) -> int:
    return 30 * bool(f["has_number"]) + 30 * bool(f["named_item"]) + 20 * bool(f["has_example"]) + 20 * bool(f["has_result"])


def structure_points(f: dict) -> int:
    return 30 * (f["sentences"] >= 3) + 30 * (f["words"] >= 40) + 20 * bool(f["has_example"]) + 20 * bool(f["has_result"])


def ordinal_score(v) -> int | None:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return ORDINAL.get(n) if 1 <= n <= 5 else None


def score_answer(judged: dict, flags: dict, delivery: dict, n_language_mistakes: int) -> dict:
    """The five category scores (0-100) + overall. `judged` = the model's 1-5 values for relevance / specificity / structure / language."""
    rel = ordinal_score(judged.get("relevance"))
    spec = ordinal_score(judged.get("specificity"))
    stru = ordinal_score(judged.get("structure"))
    lang = ordinal_score(judged.get("language"))
    cats: dict[str, int] = {"delivery": int(delivery["score"])}
    if rel is not None:
        cats["relevance"] = rel
    if spec is not None:
        cats["specificity"] = int(round(0.5 * spec + 0.5 * specificity_points(flags)))
    if stru is not None:
        cats["structure"] = int(round(0.5 * stru + 0.5 * structure_points(flags)))
    if lang is not None:
        err_rate = n_language_mistakes / max(1.0, flags["words"] / 100.0)
        cats["language"] = int(round(0.5 * lang + 0.5 * P._clamp(100 - min(40, 10 * err_rate))))
    wsum = sum(CAT_WEIGHTS[k] for k in cats)
    overall = int(round(sum(CAT_WEIGHTS[k] * v for k, v in cats.items()) / wsum))
    return {"scores": cats, "overall": overall}


def bands_for(scores: dict) -> dict:
    content = _mean([scores.get(k) for k in ("relevance", "specificity", "structure")])
    return {"content": band_cat(_r(content)), "language": band_cat(scores.get("language")), "delivery": band_cat(scores.get("delivery"))}


_NUM_TOKEN = re.compile(r"(?<![\w\[])\d[\d,\.]*")
_WORD_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
           "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
           "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000}
# a spelled-out number that quantifies something ("forty percent", "five years") - the same claim as "40%" / "5 years", so it gets the same check
_NUMWORD_PHRASE = re.compile(r"\b((?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|"
                             r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                             r"hundred|thousand)\s+(percent|per\s?cent|crores?|lakhs?|million|billion|years?|months?|times)\b", re.I)


def _num_value(words: str) -> int:
    return sum(_WORD_N.get(w, 0) for w in re.split(r"[ -]+", words.casefold()))


def bracket_unknown_numbers(text: str, *sources: str) -> str:
    """A 'better answer' may only use numbers the learner (their own words or their resume) already gave; any other number - written in digits
    or spelled out before a unit - becomes [X]: the model must not put an invented '40%' into the mouth of someone who never said it. The JOB
    DESCRIPTION is deliberately not a source: its numbers are what the employer WANTS ('5+ years', 'a team of 12'), not what the learner did."""
    src = " ".join(str(s or "") for s in sources)
    known = {k.rstrip(",.") for k in re.findall(r"\d[\d,\.]*", src)}
    vals = set()
    for k in known:
        k = k.replace(",", "")
        if 0 < len(k) <= 15:                       # a 400-digit "number" overflowed float() - and is not a figure anyone said
            try:
                vals.add(int(float(k)))
            except (ValueError, OverflowError):
                pass
    low = src.casefold()

    def sub(m):
        tok = m.group(0).rstrip(",.")
        return m.group(0) if tok in known else "[X]" + m.group(0)[len(tok):]

    def sub_words(m):
        if m.group(0).casefold() in low or _num_value(m.group(1)) in vals:
            return m.group(0)
        return "[X] " + m.group(2)
    return _NUMWORD_PHRASE.sub(sub_words, _NUM_TOKEN.sub(sub, str(text or "")))


_MISTAKE_TYPES = ("grammar", "word_choice", "tense", "article", "other")


def build_feedback(d, *, transcript: str, resume_text: str, jd_text: str, flags: dict, delivery: dict, feedback_lang: str) -> dict | None:
    """Validate the model's per-answer JSON and merge it with the measured facts -> the FEEDBACK object (+ `_cats` / `_overall` for storage).
    None when the reply is unusable (missing / out-of-range judgements): the caller retries with the compact schema."""
    if not isinstance(d, dict) or d.get("error"):
        return None
    sc = d.get("scores") if isinstance(d.get("scores"), dict) else {}
    if any(ordinal_score(sc.get(k)) is None for k in ("relevance", "specificity", "structure", "language")):
        return None
    tn = P.norm(transcript)
    padded = " " + tn + " "
    mistakes, seen = [], set()
    for m in d.get("mistakes") if isinstance(d.get("mistakes"), list) else []:
        if not isinstance(m, dict):
            continue
        said, better = clean_str(m.get("said"), 160), clean_str(m.get("better"), 200)
        ns = P.norm(said)
        if not said or not better or not ns or ns == P.norm(better) or ns in seen:
            continue
        parts = [P.norm(x) for x in re.split(r"\.\.\.|…", said)]
        parts = [x for x in parts if x]
        if not parts or not all((" " + x + " ") in padded for x in parts):
            continue                                   # a quote that is not in the transcript is never shown (an ellipsis joins two real pieces)
        seen.add(ns)
        typ = m.get("type") if m.get("type") in _MISTAKE_TYPES else "other"
        mistakes.append({"type": typ, "said": said, "better": better, "why": clean_str(m.get("why"), 140)})
        if len(mistakes) >= 4:
            break
    notes = _brief_list(d.get("content_notes"), 3, 140)
    if not flags["has_number"] and not any("number" in n.lower() for n in notes):
        notes.append("No number or measurable result mentioned.")
    if flags["words"] < 40 and not any("short" in n.lower() for n in notes):
        notes.append("A short answer - add one concrete example.")
    imps = []
    for it in d.get("improvements") if isinstance(d.get("improvements"), list) else []:
        if isinstance(it, dict) and clean_str(it.get("issue"), 140):
            imps.append({"issue": clean_str(it.get("issue"), 140), "how": clean_str(it.get("how"), 220)})
    better = clean_str(d.get("better_answer"), 900)
    better = bracket_unknown_numbers(better, transcript, resume_text) if better else None
    rc = d.get("resume_check") if isinstance(d.get("resume_check"), dict) else None
    resume_check = None
    if rc:
        ok, snapped = verify_evidence(rc.get("quote"), resume_text)
        note = clean_str(rc.get("note"), 160)
        if ok and note:
            resume_check = {"note": note, "quote": snapped}
    sc_out = score_answer(sc, flags, delivery, sum(1 for m in mistakes if m["type"] != "other"))
    cats = sc_out["scores"]
    fb = {"bands": bands_for(cats), "scores": cats, "overall": sc_out["overall"], "band": band_cat(sc_out["overall"]),
          "worked": _brief_list(d.get("worked"), 2, 140), "mistakes": mistakes, "content_notes": notes[:4], "improvements": imps[:3],
          "better_answer": better, "follow_up": valid_question(d.get("follow_up")) if d.get("follow_up") else None,
          "resume_check": resume_check,
          "delivery": {k: delivery[k] for k in ("measured", "words", "seconds", "wpm", "pauses", "longest_pause", "restarts", "fillers")},
          "evidence": {k: flags[k] for k in ("has_number", "has_result", "has_example", "named_item", "sentences", "words")},
          "feedback_lang": feedback_lang, "genuine": bool(delivery["genuine"]) and d.get("genuine_effort") is not False}
    return fb


def delivery_only_feedback(delivery: dict, flags: dict, feedback_lang: str) -> dict:
    """When the model could not be reached: the measured part still ships (and the Retry button stays)."""
    return {"scores": {"delivery": int(delivery["score"])}, "bands": {"delivery": band_cat(delivery["score"])},
            "delivery": {k: delivery[k] for k in ("measured", "words", "seconds", "wpm", "pauses", "longest_pause", "restarts", "fillers")},
            "evidence": {k: flags[k] for k in ("has_number", "has_result", "has_example", "named_item", "sentences", "words")},
            "feedback_lang": feedback_lang, "genuine": bool(delivery["genuine"])}


# ----------------------------------------------------------------------------- the report (computed - no model)
_TIPS = {
    "no_number": {"en": ("Add a number", "Put one number or result in every project answer: how many, how much, how fast, how often."),
                  "hinglish": ("Number add karo", "Har project answer mein ek number ya result bolo: kitna, kitni tezi se, kitni baar.")},
    "no_result": {"en": ("End with the result", "Finish each story with what changed because of your work."),
                  "hinglish": ("Result se khatam karo", "Har story ke end mein bolo ki aapke kaam se kya badla.")},
    "short": {"en": ("Give one full example", "Aim for 45 to 90 seconds: the situation, what you did, and the result."),
              "hinglish": ("Ek poora example do", "45 se 90 second ka answer rakho: situation, aapne kya kiya, aur result.")},
    "fillers": {"en": ("Cut the filler words", "Pause quietly instead of saying the same filler word. A short silence sounds confident."),
                "hinglish": ("Filler words kam karo", "Filler word ki jagah chup-chaap ruk jao. Chhota pause confident lagta hai.")},
    "pace": {"en": ("Steady the pace", "Aim for about 110 to 150 words a minute: not rushed, not slow."),
             "hinglish": ("Speed steady rakho", "Lagbhag 110 se 150 words per minute rakho: na jaldi, na dheere.")},
    "pauses": {"en": ("Fewer long pauses", "Long gaps break the story. Take a breath, then continue with your next point."),
               "hinglish": ("Lambe pauses kam karo", "Lambe gap se story toot-ti hai. Saans lo aur agla point bolo.")},
    "grammar": {"en": ("Fix the repeating slip", "The same kind of slip came back. Say the corrected sentence aloud three times."),
                "hinglish": ("Baar-baar wali galti sudharo", "Ek hi type ki galti repeat hui. Sahi sentence teen baar bolkar practise karo.")},
    "named_item": {"en": ("Name your tools", "Say the tool, skill or method you used by name - it shows you really did it."),
                   "hinglish": ("Tools ka naam lo", "Jo tool, skill ya method use kiya uska naam lo - isse lagta hai aapne sach mein kiya.")},
}
_PATTERN_TEXT = {"no_number": "No number or result in {c} of {n} answers.", "no_result": "No clear result in {c} of {n} answers.",
                 "short": "{c} of {n} answers were under 40 words.", "fillers": "The filler word \"{w}\" came up {c} times.",
                 "pace": "The pace was outside the comfortable range in {c} of {n} answers.", "pauses": "Long pauses in {c} of {n} answers.",
                 "grammar": "The same kind of slip (\"{w}\") repeated in {c} answers.", "named_item": "No tool or skill named in {c} of {n} answers."}


def _significant(c: int, n: int) -> bool:
    return c >= 2 and c / max(1, n) >= 0.34


def delta_threshold(n: int) -> int:
    """A change smaller than this is noise. One answer's score wobbles ~10 points; a mean of n answers wobbles ~10/sqrt(n)."""
    return max(P.SIGNIFICANT_DELTA, int(round(12 / math.sqrt(max(1, n)))))


def build_report(turns: list[dict], *, requirements: list[dict], feedback_lang: str, prev: dict | None = None) -> dict:
    """The whole report from the stored turns. No model: Finish can never fail on quota, and every sentence traces to a counted fact.
    turns: dicts with id, idx, kind, question, status, real, answer_sec, scores, overall, feedback, req_ids."""
    tips = lambda key: _TIPS[key].get(feedback_lang, _TIPS[key]["en"])           # noqa: E731
    answered = [t for t in turns if t["status"] == "answered"]
    real = [t for t in answered if t.get("real")]
    judged = [t for t in real if isinstance(t.get("scores"), dict) and t["scores"].get("relevance") is not None]
    partial = len(judged) < len(real)
    cats = []
    meas = [t for t in real if (t.get("feedback") or {}).get("delivery", {}).get("measured")]
    deliv_pool = meas or real

    def delivery_of(t):
        """The delivery score of one answer: from its feedback, or - when the feedback never finished - from the metrics taken at answer time."""
        sc = t.get("scores") if isinstance(t.get("scores"), dict) else {}
        if sc.get("delivery") is not None:
            return sc["delivery"]
        return ((t.get("metrics") or {}).get("delivery") or {}).get("score")
    for key in CATS:
        if key == "delivery":
            v = _mean([delivery_of(t) for t in deliv_pool])
        else:
            v = _mean([t["scores"].get(key) for t in judged if isinstance(t.get("scores"), dict)])
        cats.append({"key": key, "label": CAT_LABEL[key], "score": _r(v)})
    delivery_measured = bool(meas)
    # the overall is the mean of the answers that were JUDGED. Delivery alone is not an interview score: with no judged answer (the model was down
    # for every answer) the overall is None - "not scored" - never a made-up 0 or a delivery-only 80
    overall = _r(_mean([t["overall"] for t in judged if t.get("overall") is not None]))

    # JD coverage: a requirement counts once an answer linked to it was good on content
    covered_ids = set()
    for t in judged:
        content = _mean([t["scores"].get(k) for k in ("relevance", "specificity", "structure")])
        if content is not None and content >= 60:
            covered_ids.update(t.get("req_ids") or [])
    cov = None
    if requirements:
        cov_list = [{"id": r["id"], "text": r["text"]} for r in requirements if r["id"] in covered_ids]
        not_list = [{"id": r["id"], "text": r["text"]} for r in requirements if r["id"] not in covered_ids]
        cov = {"covered": cov_list, "not_yet": not_list, "pct": int(round(100 * len(cov_list) / len(requirements)))}

    # patterns - counted, then phrased from a fixed table
    fb = lambda t: (t.get("feedback") or {})                                      # noqa: E731
    pats = []

    def add(key, count, word=""):
        if _significant(count, len(real)) and key in _PATTERN_TEXT:
            pats.append({"key": key, "count": count, "of": len(real), "text": _PATTERN_TEXT[key].format(c=count, n=len(real), w=word),
                         "_sev": count / max(1, len(real))})
    ev = lambda t: fb(t).get("evidence") or {}                                    # noqa: E731
    add("no_number", sum(1 for t in real if ev(t) and not ev(t).get("has_number")))
    add("no_result", sum(1 for t in real if ev(t) and not ev(t).get("has_result")))
    add("short", sum(1 for t in real if (t.get("answer_words") or 0) and t["answer_words"] < 40))
    add("named_item", sum(1 for t in real if ev(t) and not ev(t).get("named_item")))
    filler_tot: dict[str, int] = {}
    for t in real:
        for f in (fb(t).get("delivery") or {}).get("fillers") or []:
            filler_tot[f["word"]] = filler_tot.get(f["word"], 0) + f["n"]
    if filler_tot:
        w, c = max(filler_tot.items(), key=lambda kv: kv[1])
        if c >= 3:
            pats.append({"key": "fillers", "count": c, "of": len(real), "text": _PATTERN_TEXT["fillers"].format(w=w, c=c),
                         "_sev": min(1.0, c / (3.0 * max(1, len(real))))})          # three filler words per answer = every answer
    add("pace", sum(1 for t in real if (fb(t).get("delivery") or {}).get("wpm") and not 95 <= fb(t)["delivery"]["wpm"] <= 165))
    add("pauses", sum(1 for t in real if ((fb(t).get("delivery") or {}).get("pauses") or 0) >= 4))
    mtypes: dict[str, int] = {}
    for t in real:
        for m in fb(t).get("mistakes") or []:
            if m.get("type") in ("grammar", "tense", "article", "word_choice"):
                mtypes[m["type"]] = mtypes.get(m["type"], 0) + 1
    if mtypes:
        w, c = max(mtypes.items(), key=lambda kv: kv[1])
        if c >= 2:
            pats.append({"key": "grammar", "count": c, "of": len(real), "text": _PATTERN_TEXT["grammar"].format(w=w.replace("_", " "), c=c),
                         "_sev": c / max(1, len(real))})
    order = ("grammar", "no_number", "no_result", "named_item", "short", "fillers", "pace", "pauses")     # ties: the most actionable first (grammar has real examples)
    pats.sort(key=lambda p: (-min(1.0, p["_sev"]), order.index(p["key"]) if p["key"] in order else 99))
    for p in pats:
        p.pop("_sev", None)

    # strengths: what the best answers did well
    strengths = []
    for t in sorted(judged, key=lambda t: -(t.get("overall") or 0)):
        for w in fb(t).get("worked") or []:
            if w and w not in strengths:
                strengths.append(w)
        if len(strengths) >= 3:
            break
    if not strengths:
        strengths = [f"{c['label']} was a strength." for c in sorted([c for c in cats if c["score"] is not None], key=lambda c: -c["score"])[:2] if c["score"] >= 65]
    # fixes: the top patterns with a fixed tip and real examples
    fixes = []
    for p in pats[:3]:
        key = "grammar" if p["key"] == "grammar" else p["key"]
        title, tip = tips(key if key in _TIPS else "short")
        ex = []
        if key == "grammar":
            for t in judged:
                for m in fb(t).get("mistakes") or []:
                    if len(ex) < 2:
                        ex.append({"said": m["said"], "better": m["better"]})
        fixes.append({"title": title, "tip": tip, "examples": ex})
    # the answer to redo
    redo = None
    pool = [t for t in judged if fb(t).get("better_answer")]
    if pool:
        w = min(pool, key=lambda t: t.get("overall") or 0)
        redo = {"turn_id": w["id"], "idx": w["idx"], "question": w["question"], "score": w.get("overall"),
                "mistakes": (fb(w).get("mistakes") or [])[:3], "better_answer": fb(w).get("better_answer")}
    per_q = []
    for t in sorted([t for t in turns if t["status"] in ("answered", "skipped")], key=lambda t: (t.get("idx") or 0)):
        if t["status"] == "answered" and t.get("real"):
            f = fb(t)
            short = (f.get("improvements") or [{}])[0].get("issue") or (f.get("worked") or [""])[0] or ""
            per_q.append({"turn_id": t["id"], "idx": t["idx"], "question": t["question"], "band": band_cat(t.get("overall")),
                          "score": t.get("overall"), "short": short[:110]})
        else:
            per_q.append({"turn_id": t["id"], "idx": t["idx"], "question": t["question"], "band": None, "score": None,
                          "short": "Skipped." if t["status"] == "skipped" else "Not counted - it did not sound like a full answer."})
    seconds = int(sum(min(t.get("answer_sec") or 0, MINUTES_CAP_PER_ANSWER) for t in answered))
    delta = None
    if prev and prev.get("categories"):
        thr = delta_threshold(min(len(judged) or 1, int(prev.get("real") or 1)))
        pc = {c["key"]: c["score"] for c in prev["categories"]}
        cc = {c["key"]: c["score"] for c in cats}
        delta = {"vs_session": prev.get("session_id"), "language": None, "delivery": None}
        for key in ("language", "delivery"):
            if key == "delivery" and bool(prev.get("delivery_measured")) != delivery_measured:
                continue                                 # measured and unmeasured delivery are never compared
            if cc.get(key) is not None and pc.get(key) is not None:
                d = cc[key] - pc[key]
                delta[key] = {"delta": d, "significant": abs(d) >= thr}
    return {"overall": overall, "band": band_cat(overall), "categories": cats, "answers": len(answered), "real": len(real), "seconds": seconds,
            "partial": partial, "feedback_lang": feedback_lang, "delivery_measured": delivery_measured, "coverage": cov, "patterns": pats,
            "strengths": strengths[:3], "fixes": fixes, "redo": redo, "per_question": per_q, "delta": delta}


# ----------------------------------------------------------------------------- hand-off to the existing systems
def progress_scores(cats: list[dict]) -> dict:
    """The five Speaker-Progression components from the report's categories. A component with no signal is None (the caller passes it to
    `award_speaker_progress` as UNSCORED, which leaves it out of the overall instead of counting it as 0)."""
    c = {x["key"]: x["score"] for x in cats}
    content = _r(_mean([c.get("relevance"), c.get("specificity"), c.get("structure")]))
    return {"confidence": c.get("delivery"), "continuity": c.get("delivery"), "vocabulary": c.get("language"),
            "grammar_trend": c.get("language"), "depth": content}


def minutes_for(turns: list[dict]) -> float:
    return sum(min(t.get("answer_sec") or 0, MINUTES_CAP_PER_ANSWER) for t in turns if t["status"] == "answered") / 60.0


def claim_fresh(claimed_at, now) -> bool:
    """True while another request still holds the claim (younger than CLAIM_TTL_S)."""
    return claimed_at is not None and (now - claimed_at).total_seconds() < CLAIM_TTL_S


def session_title(role: str, company: str) -> str:
    r, c = clean_str(role, 80), clean_str(company, 60)
    return (f"{r} - {c}" if r and c else r or c or "Mock interview")[:160]
