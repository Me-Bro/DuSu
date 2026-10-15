"""Resume Interview - documents: sniff the type, extract text in a sandboxed child, clean it, take contact and personal details OUT.

Everything except `ingest` / `extract` is pure and tested offline. Two promises this file keeps:
* the server never parses an untrusted file in-process: PDF / DOCX go to `extract_child.py` (empty environment, own limits, wall-clock kill);
* what is stored - and what any model ever sees - has had emails, phones, links, Aadhaar / PAN numbers, a name-like first line and the
  "Personal details / Declaration" block removed. This is best effort, and the privacy page says so: names elsewhere in the text, employers and
  the content of answers are not guaranteed to be removed. The learner sees exactly what was kept and what was taken out.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unicodedata

from . import rules

EXTRACT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract_child.py")
PARSE_TIMEOUT_S = 8.0               # a real 3-8 page resume parses in well under a second; a crafted PDF can burn CPU until it is killed
SLOT_WAIT_S = 3.0                   # ... and must not be able to hold the two slots (and a queue behind them) for everyone else
_PARSE_SLOTS = 2
_sem: asyncio.Semaphore | None = None


class DocError(Exception):
    """A document the learner can fix. `args[0]` is a short code the API maps to a status and the client maps to its own words."""


# ----------------------------------------------------------------------------- sniffing
def sniff(data: bytes) -> str:
    """pdf | docx | doc (legacy Word) | txt | unknown - from the bytes, never from the file name or the declared type."""
    if not data:
        raise DocError("empty")
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "docx" if b"word/document.xml" in data else "unknown"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    if b"\x00" in data[:4096]:
        return "unknown"
    try:
        data[:200000].decode("utf-8-sig")
        return "txt"
    except UnicodeDecodeError:
        sample = data[:4000].decode("utf-8", errors="replace")
        return "txt" if sample.count("�") / max(1, len(sample)) < 0.02 else "unknown"


# ----------------------------------------------------------------------------- extraction
def _slots() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_PARSE_SLOTS)
    return _sem


async def _run_child(data: bytes, kind: str) -> dict:
    sem = _slots()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=SLOT_WAIT_S)       # no unbounded queue: a busy server says so instead of making everyone wait
    except asyncio.TimeoutError:
        raise DocError("busy")
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-B", EXTRACT_SCRIPT, kind,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin"})         # an EMPTY secret surface: no SESSION_SECRET, keys or DATABASE_URL
        except Exception:
            raise DocError("extract_unavailable")
        try:
            out, _ = await asyncio.wait_for(proc.communicate(data), timeout=PARSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            raise DocError("bad_file")
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise DocError("bad_file")
    finally:
        sem.release()
    try:
        res = json.loads(out.decode("ascii", errors="replace"))
    except Exception:
        raise DocError("bad_file")
    if not isinstance(res, dict) or not res.get("ok"):
        raise DocError(str((res or {}).get("error") or "bad_file") if isinstance(res, dict) else "bad_file")
    return res


async def extract(data: bytes, kind: str) -> dict:
    """{text, pages, warnings} for kind in pdf / docx / txt."""
    if kind == "txt":
        return {"text": data[:rules.DOC_RAW_CAP * 4].decode("utf-8-sig", errors="replace"), "pages": 0, "warnings": []}
    res = await _run_child(data, kind)
    return {"text": str(res.get("text") or ""), "pages": int(res.get("pages") or 0), "warnings": [str(w)[:120] for w in (res.get("warnings") or [])][:3]}


# ----------------------------------------------------------------------------- cleaning
def normalize_extracted(text: str) -> str:
    """What PDF text looks like after extraction -> what it means: NFKC (ligatures, full-width), soft hyphens out, icon-font bullets -> '•',
    words split by a line-end hyphen re-joined."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = t.replace("­", "")
    t = re.sub(r"[-]", "•", t)
    t = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "", t)
    return t


# ----------------------------------------------------------------------------- redaction
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_PERM = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
         [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(num: str) -> bool:
    """The check-digit scheme Aadhaar numbers use. A random 12-digit run (a year range, an order number) passes only 1 time in 10."""
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_PERM[i % 8][int(ch)]]
    return c == 0


# Every pattern below is BOUNDED (no unbounded repeat that can backtrack over a long run of one character) and anchored with a look-behind or a start-of-
# line, so the work is linear in the text. This matters: the server has ONE worker, these run on its event loop, and the input is attacker-controlled -
# the first version took 12 s on an 8 KB paste of spaces and 5 s on 30 KB of plain letters. tests/resume_interview/unit.py times every entry point.
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]{1,64}@[\w\-]{1,63}(?:\.[\w\-]{1,63}){1,8}")
_KNOWN_SITES = r"linkedin|github|gitlab|bitbucket|behance|dribbble|twitter|instagram|facebook|medium|kaggle|leetcode|hackerrank|hackerearth|codechef|codeforces|stackoverflow|naukri|portfolio"
_HOSTED = r"github\.io|netlify\.app|vercel\.app|herokuapp\.com|web\.app|pages\.dev|wordpress\.com|blogspot\.com|wixsite\.com|notion\.site|carrd\.co"
_URL = re.compile(r"(?:https?://|www\.)\S+"
                  r"|\b[A-Za-z0-9][A-Za-z0-9\-]{0,40}\.(?:" + _HOSTED + r")\S*"                  # pranav.github.io - the whole address, the name part included
                  r"|\b(?:" + _KNOWN_SITES + r")\.(?:com|in|io|me|net|org)\S*"
                  r"|\b[A-Za-z0-9][A-Za-z0-9\-]{2,40}\.(?:dev|me)\b\S*", re.I)                    # a personal domain (pranavsharma.dev)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{3,30}(?![\w(])")
# an "@word" is a social handle only on a line that talks about a social network: "@RestController", "@Autowired", "@pytest.fixture" are code, and they are
# exactly the keywords a job description asks for
_SOCIAL = re.compile(r"twitter|instagram|insta\b|telegram|tiktok|snapchat|discord|skype|\bhandle\b|\bx\.com|whatsapp|social", re.I)
_AADHAAR = re.compile(r"(?<!\d)([2-9]\d{3})[\s\-]?(\d{4})[\s\-]?(\d{4})(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PHONE = re.compile(
    r"(?<![\d\w])(?:"
    r"(?:\+|00)\s?91[\s\-.]?\(?0?\)?[6-9]\d{4}[\s\-.]?\d{5}"            # +91 98765 43210 · +91-9876543210 · 0091...
    r"|(?:\+|00)\s?\d{1,3}[\s\-.]?\(?\d{2,5}\)?[\s\-.]?\d{3,5}[\s\-.]?\d{3,5}"   # another country code
    r"|0?[6-9]\d{4}[\s\-.]\d{5}"                                         # 98765 43210
    r"|0?[6-9]\d{9}"                                                     # 9876543210 · 09876543210
    r"|[6-9]\d(?:[\s\-.]\d{2}){4}"                                       # 98 76 54 32 10
    r"|[6-9]\d{3}[\s\-.]\d{3}[\s\-.]\d{3}"                              # 9876 543 210
    r"|\(0\d{2,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,5}"                      # (022) 2345 6789
    r"|0\d{2,4}[\s\-]\d{6,8}"                                            # 011-23456789
    r"|0\d{2,4}[\s\-]\d{3,4}[\s\-]\d{3,4}"                              # 022 2345 6789
    r"|\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"                             # 415-555-2671 · (415) 555-2671
    r")(?![\d\w])")

_SP = r"[^\S\n]"                                    # horizontal whitespace only
# Personal-detail LABELS. STRONG ones mean only one thing and may be followed by a value after a colon, a dash or just a space ("Nationality Indian" -
# PDF tables lose the colons); the rest could start a legitimate line ("Religion and politics reporting", "Pan-India distribution", "Category-wise
# analysis"), so they need a colon (or a dash with spaces on both sides) - a hyphen glued to the word is not a label separator.
_STRONG_SP = r"date\s+of\s+birth|d\.?\s?o\.?\s?b\b\.?|birth\s?date|marital\s+status|nationality|father'?s?\s+name|mother'?s?\s+name|husband'?s?\s+name"
_STRONG = (r"born\s+on|religion|caste|passport(?:\s+(?:no\.?|number))?|(?:permanent|current|present|residential|correspondence|home)\s+address|"
           r"aadhaa?r(?:\s+(?:no\.?|number|card))?|voter\s+id|driving\s+licen[cs]e(?:\s+(?:no\.?|number))?")
_WEAK = r"gender|sex|category|address|pan(?:\s+(?:no\.?|number|card))?|age"
_PERSONAL_LINE = re.compile(
    r"^" + _SP + r"{0,8}[•\-*·▪►➢]?" + _SP + r"{0,8}(?:"
    r"(?:" + _STRONG_SP + r")(?:" + _SP + r"{0,3}[:\-–—.]" + _SP + r"{0,3}|" + _SP + r"{1,3}(?=\S))"
    r"|(?:" + _STRONG + r")" + _SP + r"{0,3}[:\-–—.]" + _SP + r"{0,3}"
    r"|(?:" + _WEAK + r")" + _SP + r"{0,2}(?::|" + _SP + r"[\-–—]" + _SP + r")"
    r")", re.I)
_PERSONAL_HEAD = re.compile(r"^(?:personal\s+(?:details|information|particulars|data)|declaration)\s*[:\-–—]*$", re.I)
_DECL = re.compile(r"^(?:i\s+(?:hereby\s+)?(?:declare|certify|confirm|solemnly)|(?:place|date|signature|signed|sincerely|yours\s+(?:faithfully|sincerely|truly))\b|\(signature\))", re.I)
_LABEL_VALUE = re.compile(r"^[A-Za-z][A-Za-z .'/&\-]{0,34}:\s*\S")
_HEADINGS = {"education", "experience", "work experience", "professional experience", "employment", "employment history", "projects", "academic projects",
             "skills", "technical skills", "key skills", "core skills", "core competencies", "summary", "professional summary", "objective", "career objective",
             "achievements", "certifications", "certificates", "interests", "hobbies", "languages", "references", "internships", "internship",
             "academics", "academic qualification", "academic qualifications", "profile", "extracurricular", "extra curricular activities", "awards",
             "training", "courses", "publications", "responsibilities", "strengths", "work history", "personal projects", "volunteering",
             "volunteer experience", "activities", "technical proficiency", "tools", "tools and technologies", "career summary"}
_ADDR_CONT = re.compile(r"\b(?:road|rd\.?|street|st\.?|nagar|colony|sector|block|plot|flat|house|dist(?:rict)?|tehsil|taluk|post|state|india|pin(?:code)?|"
                        r"apartment|apt|lane|marg|chowk|village|vill)\b|\b\d{6}\b", re.I)
_TITLE_LINES = {"curriculum vitae", "resume", "résumé", "cv", "bio data", "biodata", "curriculum vitae of", "resume of"}
_NAME_LABEL = re.compile(r"^(?:candidate\s+name|full\s+name|name\s+of\s+(?:the\s+)?candidate|name)" + _SP + r"{0,3}[:\-–—]" + _SP + r"{0,3}(.{1,60})$", re.I)
_NAME_BAD = {"resume", "curriculum", "vitae", "cv", "engineer", "developer", "analyst", "manager", "designer", "intern", "consultant", "student", "profile",
             "summary", "objective", "software", "data", "senior", "junior", "lead", "officer", "executive", "associate", "specialist", "administrator",
             "architect", "scientist", "teacher", "accountant", "fresher", "experience", "education", "skills", "contact", "details", "personal", "web",
             "full", "stack", "java", "python", "marketing", "sales", "finance", "hr", "business", "digital", "project", "product", "technical",
             "customer", "support", "assistant", "trainee", "graduate", "bachelor", "master", "of", "and", "the", "for", "in", "at", "with",
             "projects", "certifications", "achievements", "languages", "interests", "hobbies", "references", "awards", "training", "courses"}


def looks_like_name(line: str) -> bool:
    """A line that is just a person's name: 1-4 capitalised words, no digits, nothing that reads like a job title or a section name."""
    t = line.strip()
    if not t or len(t) > 40 or re.search(r"[\d@:/|\[\]]", t):
        return False
    toks = t.replace(",", " ").split()
    if not 1 <= len(toks) <= 4:
        return False
    for tok in toks:
        if not re.fullmatch(r"[A-Z][A-Za-z'.\-]*", tok):
            return False
        if tok.casefold().strip(".") in _NAME_BAD:
            return False
    return len(toks) >= 2 or len(toks[0]) >= 3


def _name_value(v: str) -> bool:
    """The value after a 'Name:' label: any case ('ravi kumar'), 1-4 words of letters."""
    t = v.strip()
    toks = t.split()
    return 1 <= len(toks) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z'.\-]*", x) for x in toks) and not any(x.casefold().strip(".") in _NAME_BAD for x in toks)


def _is_known_heading(line: str) -> bool:
    s = line.strip()
    return 0 < len(s) <= 60 and s.casefold().rstrip(":-–—• \t") in _HEADINGS


def _is_heading(line: str, caps: bool = True) -> bool:
    """A section heading: one of the known names, or (caps) a short ALL-CAPS line with no digits."""
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if _is_known_heading(s):
        return True
    if caps:
        letters = [c for c in s if c.isalpha()]
        return len(letters) >= 3 and all(c.isupper() for c in letters) and len(s.split()) <= 4 and not re.search(r"\d", s)
    return False


def _strip_name(lines: list[str], counts: dict) -> None:
    """Remove the candidate's name from the top of a resume: a 'Name: X' line, a bare name line, or a name leading a header joined by separators
    ('Pranav Sharma | pune | pranav@x.com'). Title lines ('Curriculum Vitae') are skipped. The removed name becomes [NAME], which is NOT name-like,
    so a second pass over already-redacted text (the learner edits the preview and saves) leaves it alone: redaction is idempotent."""
    seen = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        seen += 1
        if seen > 6 or len(s) > 240:
            return
        k = re.sub(r"[^a-zà-ÿ]+", " ", s.casefold()).strip()
        if k in _TITLE_LINES or _PERSONAL_LINE.match(ln):
            continue                                        # a title ("Curriculum Vitae") or a personal-label line above the name: look at the next line
        if _is_known_heading(s):
            return                                          # a SECTION heading: the name, if there was one, is above it - never "the first skill under Skills"
        m = _NAME_LABEL.match(s)
        if m and _name_value(m.group(1)):
            lines[i] = "[NAME]"
            counts["name"] += 1
            return
        if looks_like_name(s):
            lines[i] = "[NAME]"
            counts["name"] += 1
            return
        segs = re.split(r"\s*[|•·●▪►➢]\s*|\s+[—–\-]\s+|\t+|\s{3,}", s)
        if len(segs) >= 2 and len(segs[0].split()) >= 2 and looks_like_name(segs[0]):
            lines[i] = "[NAME]" + s[len(segs[0]):]
            counts["name"] += 1
        return                                          # the first real line is not a name: do not wander into the body


_PIN = re.compile(r"(?<!\d)\d{6}(?!\d)")
_HOUSE_NO = re.compile(r"\b(?:flat|house|plot|door|room|h\.?\s?no\.?)\b[\s.#\-:]{0,3}\d+", re.I)


def _strip_header_address(lines: list[str], counts: dict) -> None:
    """An UNLABELLED postal address in the header ("Flat 12, Shanti Apartments, Sector 21, Noida - 201301"): inside the first 8 non-empty lines, a short
    line that is not a bullet and has a 6-digit PIN code or a numbered flat / house / plot. Deliberately narrow: header only, and years, counts and
    employer names ("State Street Bank (2020 - 2022)", "Block 3 of the 2021 migration", "400053 outlets") must never be hit."""
    seen = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        seen += 1
        if seen > 8:
            return
        if len(s) > 120 or "[NAME]" in s or s[0] in "•-*·▪►➢":
            continue
        if _PIN.search(s) or _HOUSE_NO.search(s):
            lines[i] = "[ADDRESS]"                # a placeholder, not a deletion: the window of "first 8 lines" must be the same on a second pass (idempotency)
            counts["address"] += 1


def _personalish(s: str, loose: bool = True) -> bool:
    """A line that can belong to a Personal-details / Declaration block. `loose` also accepts a short line (a wrapped value, a signature) - only
    allowed straight after another line of the block: after a blank line the next line must look personal ON ITS OWN, or an unknown Title-Case
    heading ("Work Experience Summary") would be swallowed as a 'short line'."""
    t = s.strip().lstrip("•-*·▪►➢ \t")
    if not t or len(t) > 240:
        return False
    if _PERSONAL_LINE.match(t) or _PERSONAL_HEAD.match(t) or _DECL.match(t):
        return True
    if len(t) < 90 and _ADDR_CONT.search(t):
        return True
    if _LABEL_VALUE.match(t) and len(t) <= 120:
        return True
    return loose and len(t) <= 40 and not t.endswith((".", "?", "!"))


def _consume_block(lines: list[str], i: int, decl: bool) -> int:
    """From the line after a Personal-details / Declaration heading: drop lines while they still look personal. Ends at a real heading, at the
    first line that is not personal-looking, or after 18 lines - never 'everything up to the next known heading'."""
    budget = 18
    while i < len(lines) and budget > 0:
        s = lines[i].strip()
        if not s:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _personalish(lines[j], loose=False) and not _is_known_heading(lines[j]):
                i = j
                continue
            return j if j >= len(lines) else i + 1
        if _is_heading(s, caps=not decl) and not _PERSONAL_HEAD.match(s):
            return i
        if not _personalish(s):
            return i
        i += 1
        budget -= 1
    return i


def redact(text: str, kind: str = "resume") -> tuple[str, dict]:
    """(text without contact / personal details, counts of what was removed). Order matters: ids before phones (a 12-digit Aadhaar must not be
    eaten as a 10-digit phone), links before handles. For a job description only the contact patterns apply (recruiter emails / phones).
    Idempotent: redact(redact(x)) == redact(x) (tests prove it) - the learner's edit-and-save runs this again over the stored text."""
    counts = {"email": 0, "phone": 0, "link": 0, "aadhaar": 0, "pan": 0, "name": 0, "personal_block": 0, "address": 0}
    t = rules.clean_block(text, rules.DOC_RAW_CAP)

    def n_sub(pat, repl, key, s):
        out, n = pat.subn(repl, s)
        counts[key] += n
        return out

    if kind == "resume":
        lines = t.split("\n")
        out, i = [], 0
        while i < len(lines):
            ln = lines[i]
            s = ln.strip().lstrip("•-*·▪►➢ \t")
            if len(s) <= 60 and _PERSONAL_HEAD.match(s):
                counts["personal_block"] += 1
                i = _consume_block(lines, i + 1, s.casefold().startswith("declaration"))
                continue
            if len(ln) <= 240 and _PERSONAL_LINE.match(ln):
                counts["personal_block"] += 1
                is_addr = re.search(r"address", ln[:40], re.I) is not None
                i += 1
                if is_addr:                                    # the continuation lines of a multi-line address (at most three)
                    for _ in range(3):
                        if i < len(lines) and lines[i].strip() and len(lines[i]) < 90 and _ADDR_CONT.search(lines[i]) and not _is_heading(lines[i], caps=False):
                            i += 1
                        else:
                            break
                continue
            out.append(ln)
            i += 1
        # the name and the header address are looked for in what is LEFT after the personal blocks are gone: a second pass over the redacted text then sees
        # exactly the same lines in exactly the same window (idempotency), and a personal-label line above the name cannot hide it
        _strip_name(out, counts)
        _strip_header_address(out, counts)
        t = "\n".join(out)

    def link_repl(m):
        counts["link"] += 1
        host = re.search(r"(" + _KNOWN_SITES + r")", m.group(0), re.I)
        return f"[LINK:{host.group(1).lower()}]" if host else "[LINK]"

    t = n_sub(_EMAIL, "[EMAIL]", "email", t)
    t = _URL.sub(link_repl, t)
    if "@" in t:
        ls = t.split("\n")
        for j, ln in enumerate(ls):
            if "@" in ln and _SOCIAL.search(ln):
                ls[j], n = _HANDLE.subn("[HANDLE]", ln)
                counts["link"] += n
        t = "\n".join(ls)

    def aadhaar_repl(m):
        groups = [m.group(1), m.group(2), m.group(3)]
        if all(re.fullmatch(r"(?:19|20)\d\d", g) for g in groups):     # "2019 2021 2023" is three years, not an id
            return m.group(0)
        if not verhoeff_ok("".join(groups)):
            return m.group(0)
        counts["aadhaar"] += 1
        return "[ID]"

    t = _AADHAAR.sub(aadhaar_repl, t)
    t = n_sub(_PAN, "[ID]", "pan", t)
    t = n_sub(_PHONE, "[PHONE]", "phone", t)
    return rules.clean_block(t, rules.DOC_RAW_CAP), counts


def redact_light(text) -> str:
    """For spoken transcripts: only emails and phone numbers (a learner may say them aloud). Never raises, never walks more than 20 000 characters."""
    try:
        return _PHONE.sub("[PHONE]", _EMAIL.sub("[EMAIL]", str(text or "")[:20000]))
    except Exception:
        return str(text or "")[:20000]


# ----------------------------------------------------------------------------- the whole intake
def finish_text(raw: str, kind: str) -> tuple[str, dict, list[str]]:
    """Cleaned + redacted text, the removal counts, and warnings. Raises DocError('doc_too_short') when there is too little to work with."""
    cap = rules.JD_STORE_CHARS if kind == "jd" else rules.RESUME_MODEL_CHARS
    # bounded BEFORE any pass over the text (plan 8.3 "cap before any regex"): what survives the redaction is cut to `cap` anyway, so twice the cap
    # is all the redactor ever needs to look at
    t = rules.clean_block(normalize_extracted(str(raw or "")[: cap * 4]), cap * 2)
    t, counts = redact(t, kind)
    warnings = []
    if len(t) > cap:
        t = t[:cap].rsplit("\n", 1)[0] if "\n" in t[:cap] else t[:cap]
        warnings.append("long document: only the first part is used" if kind == "resume" else "long job description: only the first part is used")
    need = rules.JD_MIN_CHARS if kind == "jd" else rules.RESUME_MIN_CHARS
    if len(t) < need:
        raise DocError("doc_too_short")
    return t, counts, warnings


async def ingest(data: bytes, kind: str) -> dict:
    """An uploaded file -> {text, source, pages, redactions, warnings}. Raises DocError with the code to show."""
    if kind not in rules.DOC_KINDS:
        raise DocError("bad_kind")
    ftype = sniff(data)
    if ftype == "doc":
        raise DocError("unsupported_doc")
    if ftype == "unknown":
        raise DocError("unsupported_other")
    ext = await extract(data, ftype)
    if len(ext["text"].strip()) < 150:
        raise DocError("no_text")                      # a scanned PDF / an image-only document: nothing to read
    text, counts, warns = finish_text(ext["text"], kind)
    return {"text": text, "source": ftype, "pages": ext["pages"], "redactions": counts, "warnings": (ext["warnings"] + warns)[:4]}


def ingest_text(text: str, kind: str) -> dict:
    if kind not in rules.DOC_KINDS:
        raise DocError("bad_kind")
    if not isinstance(text, str) or not text.strip():
        raise DocError("empty")
    t, counts, warns = finish_text(text, kind)
    return {"text": t, "source": "paste", "pages": 0, "redactions": counts, "warnings": warns[:4]}
