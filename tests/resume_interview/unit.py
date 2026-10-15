"""Resume Interview - tier 1: pure unit checks (no database, no network, no real model).

Run inside the backend image with the working tree mounted (see README.md):
    docker run --rm -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/resume_interview/unit.py

Plain Python (no pytest in the image): every check prints PASS / FAIL, the exit status is non-zero on any failure. Fixtures are SYNTHETIC - no
real person's data is ever committed.
"""

import asyncio
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/resume_interview")
os.environ.setdefault("DATABASE_URL", "")

from app.resume_interview import docs, engine, prompts, rules          # noqa: E402
from app import practice as P                                           # noqa: E402

FAILS: list[str] = []
N = 0


def check(name: str, cond, detail: str = "") -> None:
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {detail}")


def section(t: str) -> None:
    print(f"\n== {t}")


from unit_fixtures import JD, RESUME, make_docx, make_pdf, verhoeff_check_digit   # noqa: E402


# ----------------------------------------------------------------------------- 1. cleaning + bands
section("cleaning, bands, constants")
check("clean_str strips NUL, control chars, lone surrogates and collapses space",
      rules.clean_str("a\x00b\x07 \ud800 c\n d", 50) == "ab c d")
check("clean_block keeps line breaks, collapses blank runs", rules.clean_block("a\r\n\r\n\r\n\r\nb \n c", 99) == "a\n\nb\n c")
check("safe_json drops NaN / bounds depth", rules.safe_json({"a": float("nan"), "b": [1, "x\x00"]}) == {"a": None, "b": [1, "x"]})
check("category weights sum to 100", sum(rules.CAT_WEIGHTS.values()) == 100)
check("band_match thresholds", [rules.band_match(x) for x in (90, 70, 50, 10, None)] == ["strong", "good", "fair", "weak", "unknown"])
check("band_cat thresholds", [rules.band_cat(x) for x in (85, 70, 55, 20)] == ["strong", "good", "fair", "needs_work"])
check("clean_settings coerces junk", rules.clean_settings({"type": "x", "level": 5, "feedback_lang": "fr"}) == {"type": "mixed", "level": "experienced", "feedback_lang": "hinglish"})

# ----------------------------------------------------------------------------- 2. documents: sniff, redact, finish
section("documents: sniff + redaction")
check("sniff pdf", docs.sniff(make_pdf(["hello"])) == "pdf")
check("sniff docx", docs.sniff(make_docx(["hello"])) == "docx")
check("sniff legacy doc (OLE)", docs.sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 100) == "doc")
check("sniff text", docs.sniff("plain résumé text".encode()) == "txt")
check("sniff binary junk", docs.sniff(b"\x00\x01\x02\xff" * 50) == "unknown")
try:
    docs.sniff(b"")
    check("sniff empty raises", False)
except docs.DocError as e:
    check("sniff empty raises", e.args[0] == "empty")

red, cnt = docs.redact(RESUME, "resume")
check("email removed -> [EMAIL]", "asha.verma@example.com" not in red and "[EMAIL]" in red and cnt["email"] == 1)
check("phone removed -> [PHONE]", "98765" not in red and "[PHONE]" in red and cnt["phone"] >= 1)
check("links removed, site kept as a typed placeholder", "linkedin.com/in" not in red and "[LINK:linkedin]" in red and "[LINK:github]" in red)
check("name-like first line dropped", "Asha Verma" not in red.split("\n")[0] and cnt["name"] == 1)
check("Personal details + declaration blocks removed", "Ramesh" not in red and "Marital" not in red and "1999" not in red and "hereby declare" not in red.lower())
check("address continuation removed", "Gandhi" not in red and "400053" not in red)
check("the real content survives", "Power BI dashboards" in red and "SQL queries on PostgreSQL" in red and "Customer churn analysis" in red and "SKILLS" in red)
check("section headings still present", all(h in red for h in ("EXPERIENCE", "EDUCATION", "PROJECTS")))
check("a job-title first line is NOT a name", docs.redact("Software Engineer\nBuilt things for 3 years at Acme.\n" + "x" * 300, "resume")[1]["name"] == 0)
check("single-word non-name first line kept (RESUME)", docs.redact("RESUME\nBuilt things.\n" + "x" * 300, "resume")[1]["name"] == 0)

aad = "2" + "34567890123"[:10]
aad = aad + verhoeff_check_digit(aad)
check("test fixture: generated Aadhaar passes Verhoeff", docs.verhoeff_ok(aad), aad)
t, c = docs.redact(f"My id is {aad[:4]} {aad[4:8]} {aad[8:]} end", "resume")
check("valid Aadhaar redacted", c["aadhaar"] == 1 and aad[:4] not in t, t)
t, c = docs.redact(f"Aadhaar No: {aad[:4]} {aad[4:8]} {aad[8:]}\nSKILLS\nSQL", "resume")
check("a labelled Aadhaar line is removed whole (and the next section survives)", aad[:4] not in t and "SQL" in t, t)
t, c = docs.redact("Worked 2019 2021 2023 across three roles", "resume")
check("year runs are NOT an Aadhaar", c["aadhaar"] == 0 and "2019 2021 2023" in t)
t, c = docs.redact("Order number 2345 6789 0123 shipped", "resume")
check("random 12 digits that fail Verhoeff are kept", (c["aadhaar"] == 0) == (not docs.verhoeff_ok("234567890123")) or c["aadhaar"] == 0)
t, c = docs.redact("PAN ABCDE1234F on file", "resume")
check("PAN redacted", c["pan"] == 1 and "ABCDE1234F" not in t)
phones = ["+91 98765 43210", "+91-9876543210", "09876543210", "9876543210", "98765 43210", "(022) 2345 6789", "011-23456789", "+1 415 555 0132", "00919876543210"]
for ph in phones:
    t, c = docs.redact(f"Call {ph} today", "jd")
    check(f"phone form redacted: {ph}", c["phone"] == 1 and "[PHONE]" in t, t)
t, c = docs.redact("Experience 2018-2022 and 12,000 users, salary 4.5 LPA, version 3.12", "resume")
check("years / counts / versions are not phones", c["phone"] == 0)
t, c = docs.redact("Contact recruiter: hr@acme.com or +91 99999 88888, see https://acme.com/jobs/12", "jd")
check("JD: recruiter email, phone and link redacted", c["email"] == 1 and c["phone"] == 1 and c["link"] == 1)
t, c = docs.redact("Name\nDate of Birth: 1 Jan 2000\nSkills: SQL", "jd")
check("JD: personal-line rules do not apply", "Date of Birth" in t)
check("redact_light handles phone + email only", docs.redact_light("mail a@b.co or call 9876543210 now") == "mail [EMAIL] or call [PHONE] now")

section("documents: finish_text limits")
try:
    docs.finish_text("too short", "resume")
    check("short resume rejected", False)
except docs.DocError as e:
    check("short resume rejected", e.args[0] == "doc_too_short")
big = ("A line of experience text that is long enough. " * 400)
tt, cc, ww = docs.finish_text(big, "resume")
check("resume capped to the model limit with a warning", len(tt) <= rules.RESUME_MODEL_CHARS and ww)
tt, cc, ww = docs.finish_text(JD + "x " * 8000, "jd")
check("JD cap is larger than the resume cap", rules.JD_STORE_CHARS > len(tt) >= 6000 or len(tt) <= rules.JD_STORE_CHARS)
check("NFKC + ligatures + soft hyphen", docs.normalize_extracted("ﬁnance­team manage-\nment") == "financeteam management")

# ----------------------------------------------------------------------------- 3. the extraction sandbox
section("extraction child process")


async def extraction_checks():
    pdf = make_pdf(["Experience", "Built Power BI dashboards for the sales team", "SQL and Python skills", "Education B.Sc. Statistics"] + ["filler line number %d about analytics work" % i for i in range(8)])
    r = await docs.extract(pdf, "pdf")
    check("PDF text extracted in the child", "Power BI dashboards" in r["text"] and r["pages"] == 1, r["text"][:80])
    dx = make_docx(["Experience", "Built dashboards &amp; reports", "SQL"], '<w:p><w:del><w:r><w:delText>DELETED TEXT</w:delText></w:r></w:del></w:p>'
                   '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    r = await docs.extract(dx, "docx")
    check("DOCX paragraphs + entities + table cells", "dashboards & reports" in r["text"] and "Cell A" in r["text"] and "Cell B" in r["text"], r["text"])
    check("DOCX tracked deletions are not text", "DELETED" not in r["text"])
    # encrypted
    enc = make_pdf(["secret text " * 20], encrypt_user="pw")
    try:
        await docs.extract(enc, "pdf")
        check("PDF with a real password -> 'encrypted'", False)
    except docs.DocError as e:
        check("PDF with a real password -> 'encrypted'", e.args[0] == "encrypted", str(e.args))
    enc0 = make_pdf(["Built Power BI dashboards for the sales team. " * 8], encrypt_user="")
    try:
        r = await docs.extract(enc0, "pdf")
        check("PDF encrypted with an EMPTY password is still read", "Power BI" in r["text"], r["text"][:60])
    except docs.DocError as e:
        check("PDF encrypted with an EMPTY password is still read", False, str(e.args))
    # scanned (no text)
    try:
        await docs.ingest(make_pdf([], blank=True), "resume")
        check("image-only PDF -> no_text", False)
    except docs.DocError as e:
        check("image-only PDF -> no_text", e.args[0] == "no_text", str(e.args))
    # a zip bomb: the declared sizes can lie, the READ is bounded
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:t>a</w:t>" * (14 * 1024 * 1024 // 12))
    try:
        await docs.extract(b.getvalue(), "docx")
        check("DOCX zip bomb refused", False)
    except docs.DocError as e:
        check("DOCX zip bomb refused", e.args[0] == "bad_file")
    try:
        await docs.ingest(b"PK\x03\x04 not really a docx, word/document.xml", "resume")
        check("corrupt DOCX -> bad_file", False)
    except docs.DocError as e:
        check("corrupt DOCX -> bad_file", e.args[0] == "bad_file", str(e.args))
    # legacy .doc and junk
    for payload, code in ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"y" * 50, "unsupported_doc"), (b"\x00\x01\x02\xff" * 80, "unsupported_other")):
        try:
            await docs.ingest(payload, "resume")
            check(f"ingest rejects {code}", False)
        except docs.DocError as e:
            check(f"ingest rejects {code}", e.args[0] == code)
    # the child gets an EMPTY environment (no secrets) and is killed at the deadline
    os.environ["SESSION_SECRET"] = "must-not-leak"
    env_script = os.path.join(tempfile.mkdtemp(), "envdump.py")
    open(env_script, "w").write("import json, os, sys\nsys.stdin.buffer.read()\nprint(json.dumps({'ok': True, 'text': json.dumps(dict(os.environ)), 'pages': 0}))\n")
    old = docs.EXTRACT_SCRIPT
    docs.EXTRACT_SCRIPT = env_script
    try:
        r = await docs._run_child(b"x", "pdf")
        envd = json.loads(r["text"])
        check("the child sees no SESSION_SECRET / keys / DATABASE_URL", "SESSION_SECRET" not in envd and "DATABASE_URL" not in envd and set(envd) <= {"PATH", "LC_CTYPE", "LANG"}, str(sorted(envd)))
    finally:
        docs.EXTRACT_SCRIPT = old
    slow = os.path.join(tempfile.mkdtemp(), "slow.py")
    open(slow, "w").write("import time\ntime.sleep(30)\n")
    orig_to = docs.PARSE_TIMEOUT_S
    docs.EXTRACT_SCRIPT, docs.PARSE_TIMEOUT_S = slow, 1.0
    t0 = time.monotonic()
    try:
        await docs._run_child(b"x", "pdf")
        check("a hung parse is killed at the deadline", False)
    except docs.DocError as e:
        check("a hung parse is killed at the deadline", e.args[0] == "bad_file" and time.monotonic() - t0 < 5, f"{time.monotonic() - t0:.1f}s")
    finally:
        docs.EXTRACT_SCRIPT, docs.PARSE_TIMEOUT_S = old, orig_to
    # the whole intake on a PDF resume
    pdf2 = make_pdf(RESUME.replace("•", "-").split("\n"))
    r = await docs.ingest(pdf2, "resume")
    check("ingest(PDF resume): redacted + still has the content", "asha.verma" not in r["text"] and "Power BI dashboards" in r["text"] and r["source"] == "pdf", r["text"][:100])
    r = await docs.ingest(RESUME.encode(), "resume")
    check("ingest(txt resume) works", r["source"] == "txt" and r["redactions"]["email"] == 1)


asyncio.run(extraction_checks())

# ----------------------------------------------------------------------------- 4. requirements, match, edits
section("match score, evidence ladder, edits")
check("kw_in_text whole tokens (c++, node.js, power bi)", rules.kw_in_text("c++", "I know C++ well") and rules.kw_in_text("node.js", "Node.js apps")
      and rules.kw_in_text("power bi", "built Power  BI dashboards") and not rules.kw_in_text("sql", "mysqldump"))
ok, line = rules.verify_evidence("Built Power BI dashboards for the sales team", RESUME)
check("evidence: exact words found and snapped to the real line", ok and "sales team" in line)
ok, _ = rules.verify_evidence("built power bi dashboards  for the SALES team", RESUME)
check("evidence: case / spacing differences are fine", ok)
ok, _ = rules.verify_evidence("Built Power BI dash boards for the sales team", RESUME)
check("evidence: PDF-broken word is caught by the compact form", ok)
ok, _ = rules.verify_evidence("sales team dashboards Power BI built for", RESUME)
check("evidence: reordered words caught by token overlap >= 0.8", ok)
ok, _ = rules.verify_evidence("Led a team of fifteen engineers in Berlin", RESUME)
check("evidence: an invented line is NOT found", not ok)
ok, _ = rules.verify_evidence("ﬁnance team reporting", "Reported to the finance team on weekly reporting.")
check("evidence: ligatures normalise", ok)

reqs = [{"id": f"r{i}", "text": t, "type": ty, "keywords": kw} for i, (t, ty, kw) in enumerate([
    ("2+ years of data analysis experience", "must", []), ("Strong SQL skills", "must", ["SQL"]), ("Power BI dashboards", "must", ["Power BI"]),
    ("Python for data cleaning", "must", ["Python"]), ("Explain insights to stakeholders", "nice", []), ("Snowflake or BigQuery", "nice", ["Snowflake", "BigQuery"])], 1)]
items = [{"id": "r1", "status": "met", "evidence": "Data analyst with 2 years of experience"},
         {"id": "r2", "status": "met", "evidence": "Wrote SQL queries on PostgreSQL"},
         {"id": "r3", "status": "met", "evidence": "Built dashboards on Tableau"},            # not in the resume -> unverifiable
         {"id": "r4", "status": "missing", "evidence": ""},                                   # but Python IS in the resume -> floor at partial
         {"id": "r6", "status": "missing", "evidence": ""}]                                   # r5 skipped by the model
final = rules.finalize_requirements(reqs, items, RESUME)
st = {r["id"]: r["status"] for r in final}
check("verified 'met' stays met", st["r1"] == "met" and st["r2"] == "met")
check("unverifiable 'met' becomes partial (never missing)", st["r3"] == "partial" and "No clear line" in [r for r in final if r["id"] == "r3"][0]["note"])
check("'missing' with every keyword present floors at partial", st["r4"] == "partial")
check("a requirement the model skipped is partial ('not clear'), not an invented missing", st["r5"] == "partial")
check("a truly absent requirement stays missing", st["r6"] == "missing")
sc = rules.match_score(final)
exp = round(100 * (3 * 1 + 3 * 1 + 3 * .5 + 3 * .5 + 1 * .5 + 1 * 0) / (3 + 3 + 3 + 3 + 1 + 1))
check("match score = weighted statuses", sc == exp, f"{sc} vs {exp}")
check("fewer than 4 requirements -> no score", rules.match_score(final[:3]) is None)
check("verdict text per band", all(rules.verdict(b) for b in ("strong", "good", "fair", "weak", "unknown")))

raw_edits = [{"priority": "high", "type": "add", "section": "Skills", "to": "Add Snowflake [only if you have used it]", "req": ["r6", "r99"]},
             {"priority": "low", "type": "reword", "from": "Presented monthly insights to the regional manager", "to": "Presented monthly insights to the regional manager, cutting follow-up questions by [X]%", "why": "adds a result", "req": ["r5"]},
             {"priority": "medium", "type": "reword", "from": "A line that is not in the resume at all", "to": "Rewritten line that is long enough"},
             {"priority": "medium", "type": "quantify", "to": "Quantify the dashboard impact: how many users?"}] + [{"type": "add", "to": f"Another suggestion number {i} that is long enough"} for i in range(6)]
eds = rules.validate_edits(raw_edits, RESUME, {r["id"] for r in reqs})
check("edits capped at 5 and sorted by priority", len(eds) == 5 and eds[0]["priority"] == "high")
check("add / quantify are ALWAYS 'only if true'", all(e["only_if_true"] for e in eds if e["type"] in ("add", "quantify")))
check("a reword with a real source line keeps it", any(e["type"] == "reword" and e["from"].startswith("Presented monthly") and not e["only_if_true"] for e in rules.validate_edits(raw_edits[:2], RESUME, set())) )
check("a reword whose `from` is not in the resume becomes an add", all(e["from"] == "" for e in eds if "Rewritten line" in e["to"]) and all(e["type"] != "reword" for e in eds if "Rewritten line" in e["to"]))
check("unknown requirement ids are dropped from edits", all(set(e["req"]) <= {r["id"] for r in reqs} for e in eds))
check("edit ids are e1..eN", [e["id"] for e in eds] == [f"e{i}" for i in range(1, len(eds) + 1)])

prev_reqs = [{"id": "r1", "text": "a", "type": "must", "status": "missing", "evidence": "", "note": ""}, {"id": "r2", "text": "b", "type": "must", "status": "partial", "evidence": "", "note": ""}]
cur_reqs = [{"id": "r1", "text": "a", "type": "must", "status": "met", "evidence": "x", "note": ""}, {"id": "r2", "text": "b", "type": "must", "status": "partial", "evidence": "", "note": ""}]
check("diff_requirements lists only changes", rules.diff_requirements(prev_reqs, cur_reqs) == [{"id": "r1", "text": "a", "from": "missing", "to": "met"}])
pe = [{"id": "e1", "req": ["r1"], "to": "x"}, {"id": "e2", "req": ["r2"], "to": "y"}]
check("addressed_edits: requirement moved up -> done; unchanged -> not", rules.addressed_edits(pe, prev_reqs, cur_reqs, "resume text") == ["e1"])
check("addressed_edits: the suggested wording now in the resume -> done",
      rules.addressed_edits([{"id": "e9", "req": [], "to": "Built Power BI dashboards for the sales team"}], prev_reqs, cur_reqs, RESUME) == ["e9"])

role, rq = rules.validate_requirements({"title": " Data Analyst ", "company": "Acme", "level": "mid", "requirements": [
    {"text": "SQL", "type": "must", "keywords": ["SQL", "sql", "PostgreSQL", "MySQL", "x"]}, {"text": "sql", "type": "must"}, {"text": "Python", "type": "weird"}, "junk", {"text": ""}]})
check("validate_requirements: ids, dedupe, keyword cap, type default", [r["id"] for r in rq] == ["r1", "r2"] and rq[1]["type"] == "nice" and len(rq[0]["keywords"]) == 3 and role["level"] == "mid")
check("validate_requirements: garbage -> empty", rules.validate_requirements({"error": "x"}) == ({"title": "", "company": "", "level": ""}, []))

# ----------------------------------------------------------------------------- 5. questions, protected topics, the bank
section("questions + bank")
for q, bad in (("How old are you?", True), ("Are you married?", True), ("Do you have children?", True), ("What is your religion?", True), ("Where are your parents from?", True),
               ("Are you planning to get married soon?", True), ("Do you have any disability?", True),
               ("How would you analyse customer age groups for a campaign?", False), ("Tell me about a healthcare dashboard you built.", False),
               ("Describe a time you managed a team of ten people.", False), ("Why do you want this role?", False)):
    check(f"protected_topic({q!r}) == {bad}", rules.protected_topic(q) == bad)
check("valid_question accepts a question and an imperative", rules.valid_question("Tell me about a project you are proud of.") and rules.valid_question("What tools do you use daily?"))
check("valid_question rejects short / protected / non-questions", not any(rules.valid_question(x) for x in ("Why?", "Are you married to your job or to the idea of a role?", "The weather is nice today and so it goes")))

plan_in = {"brief": {"summary": "s" * 500, "level": "fresher", "strengths": ["a", "a", "b"], "projects": [{"name": "Churn", "what": "pandas"}, {"name": ""}], "skills": ["SQL", "sql", "Power BI"]},
           "plan": [{"kind": "behavioral", "text": "Tell me about a time you faced a tight deadline.", "why": "w", "req": ["r2", "zz"]},
                    {"kind": "intro", "text": "Please introduce yourself and your background.", "why": "w"},
                    {"kind": "resume", "text": "tell me about a time you faced a tight deadline.", "why": "dup"},
                    {"kind": "gap", "text": "Are you married and do you plan to have children?", "why": "bad"},
                    {"kind": "weird", "text": "How did you build the Power BI dashboards at Acme?", "why": "x"}, "junk"]}
brief, qs = rules.validate_plan(plan_in, reqs, {"level": "experienced"})
check("plan: introduction first, duplicates and protected topics dropped", [q["kind"] for q in qs][0] == "intro" and len(qs) == 3 and all(not rules.protected_topic(q["text"]) for q in qs), str(qs))
check("plan: unknown kind -> resume; unknown requirement id dropped", any(q["kind"] == "resume" for q in qs) and all(set(q["req"]) <= {r["id"] for r in reqs} for q in qs))
check("plan: brief cleaned (summary cap, deduped lists, level)", len(brief["summary"]) <= 420 and brief["strengths"] == ["a", "b"] and brief["skills"] == ["SQL", "Power BI"] and len(brief["projects"]) == 1 and brief["level"] == "fresher")
check("bank has >= 30 distinct valid questions", len({P.norm(t) for _k, t, _s in rules.BANK}) >= 30)
ctx = rules.bank_ctx("Data Analyst", "Acme", ["SQL", "Power BI"])
seen, picks, last = set(), [], ""
for i in range(60):
    b = rules.pick_bank(ctx, seen, last, "mixed", seed=i)
    if b is None:
        break
    picks.append(b)
    seen.add(P.norm(b["text"]))
    last = b["kind"]
check("bank: never repeats a question, never a protected one, every one valid", len(picks) == len({P.norm(p['text']) for p in picks}) >= 30 and all(rules.valid_question(p["text"]) and not rules.protected_topic(p["text"]) for p in picks))
check("bank: personalised with role / company / skill", any("Data Analyst" in p["text"] for p in picks) and any("Acme" in p["text"] for p in picks) and any("SQL" in p["text"] or "Power BI" in p["text"] for p in picks))
check("bank: never two of the same kind in a row while others remain", all(picks[i]["kind"] != picks[i + 1]["kind"] for i in range(min(12, len(picks) - 1))))
check("bank: skill questions are skipped when no skill is known", all("{skill}" not in p["text"] and "  " not in p["text"] for p in [rules.pick_bank(rules.bank_ctx("", ""), set(), "", "technical", seed=s) for s in range(5)] if p))
check("bank: deterministic for a seed", rules.pick_bank(ctx, set(), "", "hr", seed=3) == rules.pick_bank(ctx, set(), "", "hr", seed=3))
exhausted = {P.norm(p["text"]) for p in picks}
check("bank: exhausted -> None", rules.pick_bank(ctx, {P.norm(t.format(role_phrase=ctx['role_phrase'], company_phrase=ctx['company_phrase'], skill=s)) for _k, t, _n in rules.BANK for s in ["SQL", "Power BI", ""]}, "", "mixed") is None)

# ----------------------------------------------------------------------------- 6. one answer
section("answer: floors, hallucination, delivery, evidence, scoring, feedback")
check("is_hallucination: 'Thank you.' and repeats", rules.is_hallucination("Thank you.") and rules.is_hallucination("Thank you. Thank you. Thank you. Thank you.") and rules.is_hallucination("   ") and rules.is_hallucination("Thanks for watching"))
check("is_hallucination: real speech is not", not rules.is_hallucination("I built dashboards for the sales team and reduced the reporting time a lot."))
check("is_hallucination: the recogniser's own doubt", rules.is_hallucination("so the thing about the project was interesting and good", [[0, 5, -1.4, 0.8]]))
check("answer_floor: 25 words and 10 s", rules.answer_floor(25, 10) and not rules.answer_floor(24, 30) and not rules.answer_floor(60, 9.9))

ANSWER = ("In my last role at Acme Analytics I built Power BI dashboards for the sales team. For example, the weekly report used to take two days, "
          "and I automated it with SQL and Python so it took three hours. This reduced the time by about 80 percent and the managers could review numbers every morning. "
          "I also presented the results to the regional manager, and basically the team started to trust the data more.")
words = []
t0 = 0.5
for w in ANSWER.split():
    words.append([w, round(t0, 2), round(t0 + 0.32, 2)])
    t0 += 0.42
dl = rules.delivery_block(ANSWER, words, [[0, 30, -0.2, 0.01]], 33)
check("delivery (timestamps): measured, wpm, fillers, score", dl["measured"] and 100 < dl["wpm"] < 170 and any(f["word"] == "basically" for f in dl["fillers"]) and 0 <= dl["score"] <= 100 and dl["genuine"], str(dl))
dl2 = rules.delivery_block(ANSWER, [], [], 33)
check("delivery (no timestamps): not measured, pauses None, pace from duration", not dl2["measured"] and dl2["pauses"] is None and dl2["wpm"] and dl2["score"] > 0)
fast = rules.delivery_block(" ".join(["word"] * 400), [], [], 60)
check("delivery: an impossible pace is not 'genuine'", not fast["genuine"])
fl = rules.evidence_flags(ANSWER, ["Power BI", "SQL"])
check("evidence flags: number, result, example, named item, sentences", fl["has_number"] and fl["has_result"] and fl["has_example"] and fl["named_item"] and fl["sentences"] >= 3)
fl0 = rules.evidence_flags("I did some work and it was good and I liked it a lot because it was nice work.", ["SQL"])
check("evidence flags: a vague answer has none", not (fl0["has_number"] or fl0["has_result"] or fl0["named_item"]))
check("specificity / structure points", rules.specificity_points(fl) == 100 and rules.specificity_points(fl0) == 0 and rules.structure_points(fl) >= 80)

good = rules.score_answer({"relevance": 5, "specificity": 5, "structure": 5, "language": 5}, fl, dl, 0)
bad = rules.score_answer({"relevance": 2, "specificity": 2, "structure": 1, "language": 2}, fl0, dl, 4)
check("score_answer: strong answer scores far above a weak one (>= 25 points)", good["overall"] - bad["overall"] >= 25, f"{good['overall']} vs {bad['overall']}")
check("score_answer: category set + bounds", set(good["scores"]) == set(rules.CATS) and all(0 <= v <= 100 for v in good["scores"].values()))
check("score_answer: a missing judgement renormalises, delivery always present", set(rules.score_answer({"relevance": 4}, fl, dl, 0)["scores"]) == {"relevance", "delivery"})
check("bands_for", rules.bands_for(good["scores"])["content"] == "strong")
check("bracket_unknown_numbers: only the learner's own numbers survive",
      rules.bracket_unknown_numbers("I cut time by 40% in 3 hours for 5 million rows, 2 days", "three hours, 2 days", "5 million rows") == "I cut time by [X]% in [X] hours for 5 million rows, 2 days")

FB_OK = {"scores": {"relevance": 4, "specificity": 3, "structure": 4, "language": 3}, "worked": ["Named the tool", "x"],
         "mistakes": [{"type": "tense", "said": "the weekly report used to take two days", "better": "the weekly report used to take two days", "why": "same"},
                      {"type": "grammar", "said": "basically the team started to trust", "better": "the team started to trust", "why": "filler"},
                      {"type": "grammar", "said": "this sentence was never spoken", "better": "x", "why": "y"},
                      {"type": "weird", "said": "I automated it with SQL and Python... took three hours", "better": "I automated it using SQL and Python; it then took three hours", "why": "wording"}],
         "content_notes": ["Add the business impact"], "improvements": [{"issue": "No question asked back", "how": "End with a question"}],
         "better_answer": "At Acme I automated the weekly report with SQL, cutting it from two days to 3 hours, about 90% faster.",
         "follow_up": "How did you validate the automated numbers?", "resume_check": {"note": "You said 2 years; the resume says 2.", "quote": "Data analyst with 2 years of experience"}, "genuine_effort": True}
fb = rules.build_feedback(FB_OK, transcript=ANSWER, resume_text=RESUME, jd_text=JD, flags=fl, delivery=dl, feedback_lang="hinglish")
check("feedback: valid reply builds", fb is not None and fb["bands"].keys() == {"content", "language", "delivery"} and 0 <= fb["overall"] <= 100)
check("feedback: a quote not in the transcript is dropped; same-as-better is dropped", fb and [m["said"] for m in fb["mistakes"]] == ["basically the team started to trust", "I automated it with SQL and Python... took three hours"], str(fb and fb["mistakes"]))
check("feedback: unknown mistake type -> other", fb and fb["mistakes"][-1]["type"] == "other")
check("feedback: invented number in the better answer is bracketed", fb and "[X]" in fb["better_answer"] and "90" not in fb["better_answer"] and "3 hours" in fb["better_answer"], fb and fb["better_answer"])
check("feedback: resume_check kept only with a verified resume quote", fb and fb["resume_check"] and "2 years" in fb["resume_check"]["quote"])
fb2 = rules.build_feedback({**FB_OK, "resume_check": {"note": "n", "quote": "a line that does not exist in the resume"}}, transcript=ANSWER, resume_text=RESUME, jd_text=JD, flags=fl, delivery=dl, feedback_lang="en")
check("feedback: unverifiable resume_check dropped", fb2 and fb2["resume_check"] is None)
check("feedback: follow_up validated", fb and fb["follow_up"] and rules.valid_question(fb["follow_up"]))
check("feedback: out-of-range / missing judgements -> None (retry rung)", rules.build_feedback({"scores": {"relevance": 9, "specificity": 3, "structure": 3, "language": 3}}, transcript=ANSWER, resume_text=RESUME, jd_text=JD, flags=fl, delivery=dl, feedback_lang="en") is None
      and rules.build_feedback({"error": "scoring_parse_failed"}, transcript=ANSWER, resume_text=RESUME, jd_text=JD, flags=fl, delivery=dl, feedback_lang="en") is None and rules.build_feedback(None, transcript="", resume_text="", jd_text="", flags=fl, delivery=dl, feedback_lang="en") is None)
check("feedback: code adds the 'no number' note when the answer had none", rules.build_feedback(FB_OK, transcript="I did some work and it was good and I liked it a lot because it was nice work indeed.", resume_text=RESUME, jd_text=JD, flags=fl0, delivery=dl, feedback_lang="en")["content_notes"][-1].startswith(("No number", "A short")))
do = rules.delivery_only_feedback(dl, fl, "en")
check("delivery-only feedback has the measured part and no judged categories", do["scores"] == {"delivery": dl["score"]} and "mistakes" not in do)

# ----------------------------------------------------------------------------- 7. the computed report
section("report")


def turn(i, overall, rel, spec, stru, lang, dlv, *, real=True, words=60, kind="behavioral", req=None, fillers=None, mist=None, measured=True, wpm=130, pauses=1, ev=None, better="A better answer."):
    fbk = {"worked": [f"Good point {i}"], "mistakes": mist or [], "improvements": [{"issue": f"Issue {i}", "how": "fix"}], "better_answer": better,
           "delivery": {"measured": measured, "words": words, "seconds": 40, "wpm": wpm, "pauses": pauses, "fillers": fillers or [], "restarts": 0},
           "evidence": ev or {"has_number": True, "has_result": True, "has_example": True, "named_item": True, "sentences": 5, "words": words}}
    return {"id": 100 + i, "idx": i, "kind": kind, "question": f"Question {i}?", "status": "answered", "real": real, "answer_sec": 40.0, "answer_words": words,
            "scores": {"relevance": rel, "specificity": spec, "structure": stru, "language": lang, "delivery": dlv}, "overall": overall, "feedback": fbk, "req_ids": req or []}


weakev = {"has_number": False, "has_result": False, "has_example": False, "named_item": False, "sentences": 2, "words": 30}
T = [turn(1, 80, 80, 78, 78, 80, 80, req=["r1"], mist=[{"type": "article", "said": "I built dashboard", "better": "I built a dashboard", "why": "article"}]), turn(2, 45, 42, 40, 42, 50, 60, words=30, req=["r2"], ev=weakev, fillers=[{"word": "basically", "n": 3}], wpm=180,
                                                          mist=[{"type": "tense", "said": "I make dashboard", "better": "I made a dashboard", "why": "past"}], better="Redo this way."),
     turn(3, 50, 50, 45, 50, 55, 62, words=35, req=["r3"], ev=weakev, fillers=[{"word": "basically", "n": 2}], wpm=175, mist=[{"type": "tense", "said": "he go", "better": "he goes", "why": "x"}]),
     {"id": 200, "idx": 4, "kind": "behavioral", "question": "Skipped one?", "status": "skipped", "real": False, "answer_sec": None, "answer_words": None, "scores": {}, "overall": None, "feedback": None, "req_ids": []},
     {**turn(5, None, 0, 0, 0, 0, 0, real=False, words=8), "scores": {}, "overall": None, "feedback": None, "answer_sec": None}]
reqs_r = [{"id": "r1", "text": "SQL"}, {"id": "r2", "text": "Power BI"}, {"id": "r3", "text": "Python"}, {"id": "r4", "text": "Snowflake"}]
rep = rules.build_report(T, requirements=reqs_r, feedback_lang="en")
check("report: overall = mean of real answers' overall", rep["overall"] == round((80 + 45 + 50) / 3) and rep["real"] == 3 and rep["answers"] == 4, str(rep["overall"]))
check("report: 5 categories with scores", [c["key"] for c in rep["categories"]] == list(rules.CATS) and all(c["score"] is not None for c in rep["categories"]))
check("report: JD coverage counts a requirement once a linked answer scored >= 60 on content", [c["id"] for c in rep["coverage"]["covered"]] == ["r1"] and rep["coverage"]["pct"] == 25)
keys = [p["key"] for p in rep["patterns"]]
check("report: patterns counted in code (no number, fillers, pace, repeated tense slip)", {"no_number", "fillers", "pace"} <= set(keys) and "grammar" in keys, str(keys))
check("report: significant patterns only (1 of 3 is not a pattern)", all(p["count"] >= 2 for p in rep["patterns"]))
check("report: fixes carry a fixed tip and real examples", rep["fixes"] and all(f["title"] and f["tip"] for f in rep["fixes"]) and any(f["examples"] for f in rep["fixes"]))
check("report: answer to redo = the weakest real answer", rep["redo"] and rep["redo"]["turn_id"] == 102 and rep["redo"]["better_answer"] == "Redo this way.")
check("report: per-question list includes skipped and not-counted", [q["short"] for q in rep["per_question"]][-2:] == ["Skipped.", "Not counted - it did not sound like a full answer."] and [q["band"] for q in rep["per_question"]][-2:] == [None, None])
check("report: strengths come from the best answers", rep["strengths"] and rep["strengths"][0] == "Good point 1")
check("report: not partial when every real answer has feedback; minutes use speaking time", not rep["partial"] and rep["seconds"] == 120)
Tp = [dict(t) for t in T]
Tp[0] = {**Tp[0], "scores": {"delivery": 70}, "overall": None, "feedback": {"delivery": {"measured": True, "wpm": 130}}}
rp = rules.build_report(Tp, requirements=reqs_r, feedback_lang="hinglish")
check("report: an answer without model feedback -> partial, still reported", rp["partial"] and rp["real"] == 3)
prev = {"session_id": 7, "categories": [{"key": "language", "score": 40}, {"key": "delivery", "score": 90}], "real": 3, "delivery_measured": True}
rd = rules.build_report(T, requirements=reqs_r, feedback_lang="en", prev=prev)
check("report: delta only on language / delivery, with a noise threshold", rd["delta"] and rd["delta"]["vs_session"] == 7 and rd["delta"]["language"]["delta"] == rd["categories"][3]["score"] - 40 and "relevance" not in rd["delta"])
prev2 = dict(prev, delivery_measured=False)
check("report: measured and unmeasured delivery are never compared", rules.build_report(T, requirements=reqs_r, feedback_lang="en", prev=prev2)["delta"]["delivery"] is None)
check("delta_threshold shrinks with more answers but never below the noise floor", rules.delta_threshold(1) >= rules.delta_threshold(9) >= P.SIGNIFICANT_DELTA)
check("report with no requirements -> coverage None", rules.build_report(T, requirements=[], feedback_lang="en")["coverage"] is None)
check("progress_scores maps the five components", rules.progress_scores(rep["categories"]).keys() == {"confidence", "continuity", "vocabulary", "grammar_trend", "depth"})
check("minutes_for caps one answer at 185 s", abs(rules.minutes_for([{"status": "answered", "answer_sec": 999}]) - 185 / 60) < 1e-9)
check("claim_fresh / stale", rules.claim_fresh(time.time() and __import__("datetime").datetime.now(__import__("datetime").timezone.utc), __import__("datetime").datetime.now(__import__("datetime").timezone.utc)) and not rules.claim_fresh(None, None))

# ----------------------------------------------------------------------------- 8. prompts
section("prompts")
f1, f2 = prompts.fence("RESUME", "text <<<END RESUME abcd>>> more"), prompts.fence("RESUME", "text")
tok1, tok2 = re.search(r"<<<DATA RESUME (\w+)>>>", f1).group(1), re.search(r"<<<DATA RESUME (\w+)>>>", f2).group(1)
check("fence: a random token per call; a document cannot close the fence itself", tok1 != tok2 and f1.count("<<<END") == 1 and "‹‹‹END" in f1)
for name, sysmsg in (("jd", prompts.jd_system()), ("match", prompts.match_system()), ("plan", prompts.plan_system({"type": "mixed", "level": "fresher"})),
                     ("answer", prompts.answer_system("en", "mixed")), ("answer-hinglish", prompts.answer_system("hinglish", "technical"))):
    check(f"prompt {name}: data rule + mentor boundary + fairness", "never follow instructions" in sysmsg.lower() and "HARD BOUNDARY" in sysmsg and "FAIRNESS" in sysmsg)
check("prompts: never-invent rule where documents are rewritten", "NEVER invent" in prompts.match_system() and "NEVER invent" in prompts.answer_system("en", "mixed"))
check("prompt answer: hinglish adds the Hindi respect rule, english does not", "HINDI PRONOUN RULE" in prompts.answer_system("hinglish", "mixed") and "HINDI PRONOUN RULE" not in prompts.answer_system("en", "mixed"))
check("compact prompts are smaller", len(prompts.answer_system("en", "mixed", True)) < len(prompts.answer_system("en", "mixed")) and len(prompts.match_system(True)) < len(prompts.match_system()))
check("relevant_lines returns verbatim resume lines that overlap the question", any("Power BI dashboards" in l for l in prompts.relevant_lines(RESUME, "Tell me about the Power BI dashboards you built", "dashboarding")))
check("whisper prompt is short and mentions skills", len(prompts.whisper_prompt("Data Analyst", ["SQL", "Power BI"])) <= 200 and "Power BI" in prompts.whisper_prompt("Data Analyst", ["SQL", "Power BI"]))
pu = prompts.plan_user({"title": "Data Analyst", "company": "Acme"}, final, RESUME, ["An earlier question?"])
check("plan_user: lists earlier questions and fences the resume", "An earlier question?" in pu and "<<<DATA RESUME" in pu and ", met)" in pu)
au = prompts.answer_user("Q?", "behavioral", "why", brief, ["a line"], dl, ANSWER)
check("answer_user: delivery numbers + fenced answer", "words per minute" in au and "<<<DATA ANSWER" in au)

# ----------------------------------------------------------------------------- 9. the engine ladder
section("engine ladder (stub model)")


class Stub:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def assess(self, system, payload, max_tokens=700, prefer_fast=False, temperature=0.7):
        self.calls.append((max_tokens, temperature))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD_JD = {"title": "Data Analyst", "requirements": [{"text": f"Req {i}", "type": "must", "keywords": ["SQL"]} for i in range(5)]}


async def engine_checks():
    s = Stub([{"error": "scoring_parse_failed"}, GOOD_JD])
    role, rq = await engine.extract_requirements(s, JD)
    check("ladder: an unusable first reply is retried with the compact schema (never a smaller cap)", len(rq) == 5 and len(s.calls) == 2 and s.calls[1][0] >= s.calls[0][0])
    s = Stub([RuntimeError("all providers/models unavailable: 429")])
    try:
        await engine.extract_requirements(s, JD)
        check("ladder: an exhausted chain is NOT retried", False)
    except engine.Unavailable as e:
        check("ladder: an exhausted chain is NOT retried", len(s.calls) == 1 and not e.parse_failed)
    s = Stub([{"x": 1}, {"y": 2}])
    try:
        await engine.extract_requirements(s, JD)
        check("ladder: two unusable replies -> Unavailable(parse_failed)", False)
    except engine.Unavailable as e:
        check("ladder: two unusable replies -> Unavailable(parse_failed)", e.parse_failed and len(s.calls) == 2)
    four = [{"id": "r1", "status": "met", "evidence": "Wrote SQL queries on PostgreSQL"}] + [{"id": f"r{i}", "status": "missing"} for i in (2, 3, 4)]
    m = await engine.analyze_match(Stub([{"items": four, "edits": [], "strengths": ["x"], "notes": []}]), RESUME, rq)
    check("analyze_match: statuses finalised in code, a skipped id (1 of 5) is 'not clear'", m["requirements"][0]["status"] == "met" and m["requirements"][4]["status"] == "partial" and len(m["requirements"]) == 5)
    plan4 = {"brief": {"summary": "x"}, "plan": plan_in["plan"] + [{"kind": "technical", "text": "What trade-offs did you make in your last project?"}]}
    brief_, qs_ = await engine.build_plan(Stub([{"brief": {"summary": "x"}, "plan": [{"kind": "intro", "text": "Please introduce yourself and your background."}]}, plan4]), role, rq, RESUME, {"type": "mixed"})
    check("build_plan: fewer than 4 valid questions -> next rung", len(qs_) == 4 and qs_[0]["kind"] == "intro")
    nointro = {"brief": {"summary": "x"}, "plan": [{"kind": "resume", "text": f"Tell me about project number {i} in detail please?"} for i in range(5)]}
    _b, qs_n = await engine.build_plan(Stub([nointro]), {"title": "Data Analyst", "company": "Acme"}, rq, RESUME, {"type": "mixed"})
    check("build_plan: a plan without an introduction gets one from the bank, first", qs_n[0]["kind"] == "intro" and "Data Analyst" in qs_n[0]["text"] and len(qs_n) == 6, [q["kind"] for q in qs_n])
    fbx = await engine.answer_feedback(Stub([{"scores": {"relevance": 4}}, FB_OK]), question="Q?", kind="behavioral", why="w", brief=brief, resume_text=RESUME, jd_text=JD,
                                       transcript=ANSWER, delivery=dl, flags=fl, feedback_lang="en", itype="mixed")
    check("answer_feedback: incomplete judgements -> compact rung -> validated feedback", fbx["overall"] > 0 and fbx["bands"])


asyncio.run(engine_checks())

# ----------------------------------------------------------------------------- 10. the shared cooldown fix
section("provider cooldown (_mark_cooldown)")
from app.providers import openrouter_provider as op        # noqa: E402

op._cooldown.clear()
op._mark_cooldown("groq", "Error code: 429 - Rate limit reached ... tokens per minute (TPM): Limit 8000, Used 4041, Requested 4500. Please try again in 4.0s")
d = op._cooldown["groq"] - time.time()
check("a rate-limit message containing '4041' is a SHORT cooldown (not 6 h)", 0 < d <= 95, f"{d:.0f}s")
op._cooldown.clear()
op._mark_cooldown("x", "Error code: 404 - model not found")
check("a real 404 is still a 6-hour cooldown", op._cooldown["x"] - time.time() > 20000)
op._cooldown.clear()
op._mark_cooldown("x", "Error code: 401 - invalid api key")
check("a real 401 is still a 6-hour cooldown", op._cooldown["x"] - time.time() > 20000)
op._cooldown.clear()
op._mark_cooldown("x", "Error code: 429 - You exceeded your current quota for the day")
check("a daily-quota 429 is still the 30-minute cooldown", 1700 < op._cooldown["x"] - time.time() <= 1800)
op._cooldown.clear()
op._mark_cooldown("x", "something rate-ish happened")
check("an unclassified rate-ish error is the 90 s cooldown", 0 < op._cooldown["x"] - time.time() <= 90)
op._cooldown.clear()

# ----------------------------------------------------------------------------- 11. the independent review's findings (2026-10-15)
section("review: every entry point is linear in its input (one uvicorn worker runs these on its event loop)")
from unit_fixtures import make_pdf_bomb      # noqa: E402

N60 = 60_000
SHAPES = {
    "spaces": " " * N60 + "x", "tabs": "\t" * N60 + "x", "nbsp": "\xa0" * N60 + "x", "newlines": "\n" * N60, "letters": "a" * N60, "letters + @": "a" * N60 + "@",
    "a@a@a@": "a@" * (N60 // 2), "a.a.a. + @": "a." * (N60 // 2) + "@b", "dashes": "-" * N60 + "x", "digits-dashes": "1-" * (N60 // 2),
    "address label + letters": "Address: " + "a" * N60, "heading + spaces": "Personal Details" + " " * N60 + "x", "label spam": "Date of Birth: " * 4000,
    "www. spam": "www." * (N60 // 4), "http:// spam": "http://" * (N60 // 7), "zeros": "0" * N60, "nines": "9" * N60, "spaced phone-ish": "98 " * (N60 // 3),
    "years": "2019 " * (N60 // 5), "+91 spam": "+91 " * (N60 // 4), "hosted domains": "a.github.io " * (N60 // 12), "bullets + spaces": ("•  " + " " * 100 + "\n") * 500,
    "name header + spaces": "Pranav Sharma" + " " * N60 + "x | y", "realistic x60": RESUME * 60, "job description x60": JD * 60,
}
ENTRY = {
    "ingest_text(resume)": lambda x: docs.ingest_text(x, "resume"), "ingest_text(jd)": lambda x: docs.ingest_text(x, "jd"),
    "redact(resume)": lambda x: docs.redact(x, "resume"), "redact(jd)": lambda x: docs.redact(x, "jd"), "redact_light": docs.redact_light,
    "clean_block": lambda x: rules.clean_block(x, N60), "clean_str": lambda x: rules.clean_str(x, 3500),
}
for shape, text in SHAPES.items():
    worst, where = 0.0, ""
    for name, fn in ENTRY.items():
        t0 = time.perf_counter()
        try:
            fn(text)
        except docs.DocError:
            pass                                  # "too short" and the like are fine - slowness is not
        dt = time.perf_counter() - t0
        if dt > worst:
            worst, where = dt, name
    check(f"linear: {shape!r} through every entry point (slowest {worst * 1000:.0f} ms, {where})", worst < 1.0, f"{worst:.2f}s in {where}")
DIRECT = {
    "verify_evidence on a 9k line": lambda: rules.verify_evidence("a" * 220, "a" * 9000), "evidence_flags on 3.5k": lambda: rules.evidence_flags("at " * 1200, ["SQL"]),
    "delivery_block on 3.5k": lambda: rules.delivery_block("word " * 700, [], [], 60), "protected_topic on 300k": lambda: rules.protected_topic("a" * 300000),
    "valid_question on 300k": lambda: rules.valid_question("a " * 150000), "bracket_unknown_numbers": lambda: rules.bracket_unknown_numbers("1," * 3000, "1" * 60000),
    "is_hallucination on 3.5k": lambda: rules.is_hallucination("a " * 1750), "looks_like_name on 100k": lambda: docs.looks_like_name("A" * 100000),
    "kw_in_text on 60k": lambda: rules.kw_in_text("power bi", "power " * 10000), "loose on 60k": lambda: rules.loose("a-" * 30000),
}
worst_d = 0.0
for label, fn in DIRECT.items():
    t0 = time.perf_counter()
    fn()
    dt = time.perf_counter() - t0
    worst_d = max(worst_d, dt)
    check(f"linear: {label} ({dt * 1000:.0f} ms)", dt < 1.0, f"{dt:.2f}s")
check("clean_block / clean_str slice their input FIRST (a 300 KB string is not walked to keep 80 characters)", rules.clean_str("x" * 300000 + " tail", 80) == "x" * 80 and len(rules.clean_block("y" * 300000, 100)) == 100)


section("review: extraction slots cannot be held for everyone")


async def slot_checks():
    sem = docs._slots()
    old_wait = docs.SLOT_WAIT_S
    docs.SLOT_WAIT_S = 0.3
    held = []
    try:
        for _ in range(docs._PARSE_SLOTS):
            await sem.acquire()
            held.append(1)
        t0 = time.monotonic()
        try:
            await docs._run_child(b"x", "pdf")
            check("both slots busy -> DocError('busy') quickly (no unbounded queue)", False)
        except docs.DocError as e:
            check("both slots busy -> DocError('busy') quickly (no unbounded queue)", e.args[0] == "busy" and time.monotonic() - t0 < 2, f"{e.args} {time.monotonic() - t0:.1f}s")
    finally:
        for _ in held:
            sem.release()
        docs.SLOT_WAIT_S = old_wait
    r = await docs.extract(make_pdf(["Built Power BI dashboards for the sales team. " * 4]), "pdf")
    check("a slot is released after a refusal: the next real PDF parses", "Power BI" in r["text"])
    t0 = time.monotonic()
    try:
        await docs.ingest(make_pdf_bomb(), "resume")
        check("a CPU-heavy PDF is cut off, not parsed", False)
    except docs.DocError as e:
        dt = time.monotonic() - t0
        check("a CPU-heavy PDF is cut off before the wall limit (limits: 5 s CPU, 8 s wall)", e.args[0] in ("bad_file", "no_text") and dt < 8.5, f"{e.args} {dt:.1f}s")
    t0 = time.monotonic()
    r = await docs.extract(make_pdf(["Experience", "Built dashboards"]), "pdf")
    check("... and the slot is free again immediately afterwards", time.monotonic() - t0 < 3 and "dashboards" in r["text"])


asyncio.run(slot_checks())

section("review: redaction is idempotent, finds more names, keeps more content")
for label, txt in (("the fixture", RESUME), ("a header line", "Pranav Sharma | pranav@example.com | +91 98765 43210 | Pune\n" + RESUME.split("\n", 3)[3]),
                   ("a CV title first", "CURRICULUM VITAE\nPranav Sharma\n" + RESUME.split("\n", 3)[3]), ("a Name: label", "Name: Ravi Kumar\n" + RESUME.split("\n", 3)[3]),
                   ("a second city line", "Mumbai, Maharashtra\n" + RESUME.split("\n", 3)[3])):
    once = docs.redact(txt, "resume")[0]
    check(f"redaction is idempotent: {label}", docs.redact(once, "resume")[0] == once, once[:60])
once = docs.redact(RESUME, "resume")[0]
check("an edited-and-saved preview keeps its content (the first line is the [NAME] placeholder, not a second 'name')", once.split("\n")[0] == "[NAME]" and "Mumbai" in once)
body = "SUMMARY\nData analyst with 2 years of experience in dashboards and reporting for sales teams.\n" + "Built dashboards for the sales team every week. " * 8
for label, txt, first in (("CURRICULUM VITAE then the name", "CURRICULUM VITAE\nPranav Sharma\n" + body, "Pranav"), ("a header joined by separators", "Pranav Sharma | pranav@example.com | +91 98765 43210 | Pune\n" + body, "Pranav"),
                          ("a Name: label", "Name: Ravi Kumar\nPhone: +91 98765 43210\n" + body, "Ravi"), ("an ALL-CAPS name", "PRANAV SHARMA\n" + body, "PRANAV"),
                          ("a lowercase Name: value", "Candidate Name - ravi kumar\n" + body, "ravi")):
    t, c = docs.redact(txt, "resume")
    check(f"name removed: {label}", first.lower() not in t.lower() and c["name"] == 1 and "Built dashboards for the sales team" in t, t[:80])
for label, txt in (("a Projects heading", "Projects\n" + body), ("a Certifications heading", "CERTIFICATIONS\n" + body), ("a job title", "Data Analyst\n" + body)):
    t, c = docs.redact(txt, "resume")
    check(f"not a name: {label}", c["name"] == 0 and txt.split("\n")[0] in t, t[:60])
t, c = docs.redact("Portfolio: pranavsharma.dev, pranav.github.io and pranav-portfolio.netlify.app\nSkills: ASP.NET, Socket.io, Node.js, Vue.js, Chart.js, Next.js, C#, .NET\n" + body, "resume")
check("personal domains are links, the name part included", "pranav" not in t.lower().replace("[link", "") and c["link"] >= 3, t[:120])
check("skills that look like domains are NOT links (ASP.NET, Socket.io, Node.js ...)", all(x in t for x in ("ASP.NET", "Socket.io", "Node.js", "Vue.js", "Chart.js", "Next.js")))
t, c = docs.redact("PERSONAL PROFILE\nResults-driven analyst with 3 years of experience in business intelligence.\nCORE SKILLS\nSQL, Excel\nWORK HISTORY\nAcme - Analyst\n" + body, "resume")
check("a 'Personal Profile' summary is NOT a personal block", "Results-driven analyst" in t and "SQL, Excel" in t and "Acme - Analyst" in t and c["personal_block"] == 0, t[:120])
t, c = docs.redact("EXPERIENCE\n• Pan-India distribution network for FMCG products\n• Category-wise sales analysis for 40 stores\n• Handled state-level distributors across 6 regions, 400053 outlets\n• Age-group segmentation of customers\n" + body, "resume")
check("'Pan-India', 'Category-wise', 'Age-group' and a state-level line are kept", all(x in t for x in ("Pan-India", "Category-wise", "state-level", "Age-group")) and c["personal_block"] == 0, t[:160])
t, c = docs.redact("SKILLS\nSpring Boot, @RestController, @Autowired, @pytest.fixture, @Component\n" + body, "resume")
check("code annotations are not social handles", all(x in t for x in ("@RestController", "@Autowired", "@pytest.fixture", "@Component")))
t, c = docs.redact("Twitter: @pranav_s  Instagram: @pranav.s\n" + body, "resume")
check("a real handle on a social line is redacted", "@pranav_s" not in t and "[HANDLE]" in t or "[LINK" in t, t[:60])
t, c = docs.redact("Skills\nSQL\n\nPERSONAL DETAILS\nDate of Birth: 1 Jan 2000\nNationality: Indian\n\nWORK HISTORY\nAcme - Data Analyst\n• Built dashboards for the sales team every week for two years\n" + body, "resume")
check("a personal block ends at a blank line + a heading: the experience after it survives", "Date of Birth" not in t and "Nationality" not in t and "Acme - Data Analyst" in t and "Built dashboards for the sales team every week" in t, t[:200])
t, c = docs.redact("PERSONAL DETAILS\nDate of Birth: 1 Jan 2000\n\nWork Experience Summary\n• Built dashboards for the sales team every week for two years\n" + body, "resume")
check("an unknown Title-Case heading after the block is not swallowed", "Work Experience Summary" in t and "Date of Birth" not in t, t[:120])
t, c = docs.redact("Gender: Male\nAge: 24\nNationality Indian\nMarital Status Single\nVoter ID: ABC1234567\nSkills: SQL\n" + body, "resume")
check("personal labels: gender, age, voter id, and 'label value' without a colon", all(x not in t for x in ("Gender", "Age:", "Nationality", "Marital", "Voter")) and "Skills: SQL" in t, t[:100])
t, c = docs.redact("Rohit Kumar Singh\nFlat 12, Shanti Apartments, Sector 21, Noida - 201301\nMobile: 98105 51234 | rohit@example.com\nObjective: A Java role.\n" + body, "resume")
check("an unlabelled address in the header becomes [ADDRESS] (a PIN code or a numbered flat / house / plot)", "Shanti" not in t and "201301" not in t and "[ADDRESS]" in t and "Objective: A Java role." in t and c["address"] == 1, t[:160])
t, c = docs.redact("Data Analyst\n" + body + "\nEXPERIENCE\nState Street Bank - Analyst (2020 - 2022)\nPost-graduate diploma in data science, 2019\nWorked on Block 3 of the 2021 migration, 400 users\n", "resume")
check("body lines with address-like words ('State Street', 'Post-graduate', 'Block 3') are never touched", all(x in t for x in ("State Street Bank", "Post-graduate diploma", "Block 3 of the 2021 migration")) and c["personal_block"] == 0 and c["address"] == 0, t[-200:])
for ph in ("98 76 54 32 10", "9876 543 210", "022 2345 6789", "415-555-2671", "(415) 555-2671"):
    t, c = docs.redact(f"Call {ph} today", "jd")
    check(f"more phone forms redacted: {ph}", c["phone"] == 1, t)
t, c = docs.redact("Experience 2018-2022, version 10.0.1234, 12,000 users, 120 000 units, dates 12-03-1999 and Q3 2019 2021 2023, CTC 4,50,000", "resume")
check("years, versions, counts, dates and CTC are still not phones", c["phone"] == 0 and c["aadhaar"] == 0, t)
t, c = docs.redact("recruiter " + "a" * 70 + "@example.com mail x.y@acme.co.in or hr@acme.com.", "jd")
check("emails: a normal address with subdomains is redacted, a 70-character local part is not an address", c["email"] == 2 and "acme.co.in" not in t, t)

import random                                                                                                          # noqa: E402
FRAGS = ["Rohit Kumar Singh", "PRIYA NAIR", "Name: Ravi Kumar", "CURRICULUM VITAE", "RESUME", "Data Analyst", "Mumbai, Maharashtra", "Projects", "Certifications",
         "Mobile: 98105 51234 | rohit@example.com | linkedin.com/in/rohit", "+91 98765 43210", "rohit.singh@mail.example.com", "github.com/rohit", "rohit.dev", "pranav.github.io",
         "PERSONAL DETAILS", "Personal Profile", "DECLARATION", "Declaration:", "Date of Birth: 14-02-1999", "Gender: Male", "Marital Status Single", "Nationality: Indian",
         "Father's Name: Mr. Suresh", "Permanent Address: Flat 12, Shanti Apartments,", "Sector 21, Noida, Uttar Pradesh - 201301", "Flat 12, Shanti Apartments, Noida - 201301",
         "I hereby declare that the above is true.", "Place: Noida", "(Rohit Kumar Singh)", "Pan-India distribution", "Category-wise analysis", "Age: 24", "Voter ID: ABC1234567",
         "EXPERIENCE", "EDUCATION", "SKILLS", "WORK HISTORY", "Core Skills", "AWARDS & HONOURS", "Work Experience Summary",
         "• Built dashboards for the sales team, reducing weekly reporting time from 2 days to 3 hours.", "- Wrote SQL queries on PostgreSQL for 5 million rows.",
         "Spring Boot, @RestController, @Autowired", "Twitter: @rohit_s", "Python, pandas, ASP.NET, Socket.io", "Infosys Ltd, Pune - Engineer (2021 - Present)",
         "B.Tech Computer Science, VIT, 2017 - 2021, CGPA 8.4", "", "", "   ", "98 76 54 32 10", "022 2345 6789", "415-555-2671", "2019 2021 2023", "x" * 300]
rng, viol, errs = random.Random(7), 0, 0
for _ in range(1500):                                  # random resume-like documents: shuffled labels, headings, names, addresses, contacts, bullets
    txt = "\n".join(rng.choice(FRAGS) for _ in range(rng.randint(1, 30)))
    for kind in ("resume", "jd"):
        try:
            a, _c = docs.redact(txt, kind)
            viol += docs.redact(a, kind)[0] != a
        except Exception:
            errs += 1
check("property: redact() never raises and is idempotent over 3000 random resume-like documents (seeded)", viol == 0 and errs == 0, f"{viol} not idempotent, {errs} errors")

section("review: scoring honesty")
check("has_example: 'at home' / 'at least' / 'good at coding' are not examples", not any(rules.evidence_flags(x)["has_example"] for x in ("He is at home all day.", "We met at least twice.", "I am good at coding.", "At the time it was hard.")))
check("has_example: 'at Acme' (a place of work) is", rules.evidence_flags("I worked at Acme on the dashboards.")["has_example"])
check("a JD number is not a source: '5+ years' / 'team of 12' are bracketed even though the job asks for them",
      "[X]" in rules.bracket_unknown_numbers("I have 5 years of experience and led a team of 12", "I worked for 2 years", "I led 3 people"), rules.bracket_unknown_numbers("I have 5 years", "2 years"))
fbj = rules.build_feedback({**FB_OK, "better_answer": "I have 7 years of experience, managed budgets above 90 crore and led a team of 17."}, transcript=ANSWER, resume_text=RESUME,
                           jd_text="7+ years of experience. Budgets above 90 crore. A team of 17.", flags=fl, delivery=dl, feedback_lang="en")
check("build_feedback does not whitelist the job's numbers (7+ years, 90 crore, a team of 17)", fbj and fbj["better_answer"].count("[X]") == 3 and "90 crore" not in fbj["better_answer"], fbj and fbj["better_answer"])
check("spelled-out numbers are checked like digits ('forty percent', 'five years')", rules.bracket_unknown_numbers("It improved by forty percent over five years.", "I worked here for 5 years") == "It improved by [X] percent over five years.")
check("a spelled-out number the learner said is kept", rules.bracket_unknown_numbers("It improved by forty percent", "we got forty percent better") == "It improved by forty percent")
forged = rules.delivery_block("banana apple orange", [[f"w{i}", 0.5 + i * 0.4, 0.8 + i * 0.4] for i in range(30)], [[0, 12, -0.2, 0.01]], 12)
check("fake timestamp rows cannot pass the word floor: the transcript decides (3 words, rows ignored -> unmeasured)",
      forged["words"] == 3 and not forged["measured"] and not rules.answer_floor(forged["words"], forged["seconds"]), str(forged))
ok_rows = rules.delivery_block(ANSWER, words, [[0, 30, -0.2, 0.01]], 33)
check("genuine timestamp rows (same count as the transcript) are still used", ok_rows["measured"] and ok_rows["words"] == len(ANSWER.split()))
check("band_cat(None) is 'unknown', never 'fair'", rules.band_cat(None) == "unknown" and rules.bands_for({"delivery": 70})["language"] == "unknown")
Tn = [{**t, "scores": {}, "overall": None, "feedback": None, "metrics": {"delivery": {"score": 72}}} for t in T[:3]]
rn = rules.build_report(Tn, requirements=reqs_r, feedback_lang="en")
check("report with NO judged answer (the model was down): overall is None / band 'unknown', never 0 or a delivery-only score", rn["overall"] is None and rn["band"] == "unknown" and rn["partial"])
check("... but delivery still comes from the metrics taken at answer time", [c["score"] for c in rn["categories"] if c["key"] == "delivery"] == [72] and [c["score"] for c in rn["categories"] if c["key"] == "language"] == [None])
check("... and per-question rows carry band 'unknown' (not 'fair') with no score", all(q["band"] == "unknown" and q["score"] is None for q in rn["per_question"]))
ps = rules.progress_scores(rn["categories"])
check("progress_scores: a component with no signal is None (the caller marks it UNSCORED)", ps["confidence"] == 72 and ps["vocabulary"] is None and ps["grammar_trend"] is None and ps["depth"] is None)
from app.resume_interview import life_lines          # noqa: E402
ln = life_lines.format_lines({"finished": 1, "last": {"title": "Data Analyst", "overall": None, "answers": 3, "finished_at": None, "weakest": ""}, "active": None})
check("DuSu's line for an unscored interview says so (no '0/100')", ln and "not scored" in ln[0] and "0/100" not in ln[0], ln)
for q, bad in (("Do you have a disability?", True), ("Are you suffering from any health issues?", True), ("Any medical condition we should know about?", False),
               ("How would you design the app for users with a disability?", False), ("Tell me about your community management experience.", False),
               ("What is your religion?", True), ("What are your hobbies?", False), ("How would you handle healthcare data privacy?", False),
               ("Do you have any health problems?", True), ("Are you disabled?", True)):
    check(f"protected_topic({q!r}) == {bad}", rules.protected_topic(q) == bad)

section("review: the match must judge (almost) every requirement")


async def coverage_checks():
    rq10 = [{"id": f"r{i}", "text": f"Requirement {i}", "type": "must", "keywords": []} for i in range(1, 9)]
    full = {"items": [{"id": f"r{i}", "status": "missing"} for i in range(1, 9)], "edits": [], "strengths": [], "notes": []}
    lazy = {"items": [{"id": "r1", "status": "met", "evidence": "Wrote SQL queries on PostgreSQL"}], "edits": [], "strengths": [], "notes": []}
    s_ = Stub([lazy, full])
    m = await engine.analyze_match(s_, RESUME, rq10)
    check("a reply that judges 1 of 8 requirements is not accepted: the compact rung runs and its full reply is used", len(s_.calls) == 2 and rules.match_score(m["requirements"]) == 0, str(rules.match_score(m["requirements"])))
    s_ = Stub([lazy, lazy])
    try:
        await engine.analyze_match(s_, RESUME, rq10)
        check("two lazy replies -> Unavailable (no inflated score is cached)", False)
    except engine.Unavailable as e:
        check("two lazy replies -> Unavailable (no inflated score is cached)", e.parse_failed)
    six = {"items": [{"id": f"r{i}", "status": "missing"} for i in range(1, 8)], "edits": [], "strengths": [], "notes": []}
    s_ = Stub([six])
    m = await engine.analyze_match(s_, RESUME, rq10)
    check("7 of 8 judged (>= 80%) is accepted; the skipped one is 'not clear'", len(s_.calls) == 1 and m["requirements"][7]["status"] == "partial")


asyncio.run(coverage_checks())
check("compact caps are never below the full caps", all(v[1] >= v[0] for v in engine.CAPS.values()), str(engine.CAPS))
check("claim TTL covers the slowest honest run (two calls x two 30 s chain walks)", rules.CLAIM_TTL_S >= 120)

section("review: provider cooldown - '429' is a token like the dead codes")
op._cooldown.clear()
op._mark_cooldown("x", "Error code: 401 - invalid api key (request id req_429abc)")
check("a real 401 whose request id contains '429' is still a 6-hour cooldown", op._cooldown["x"] - time.time() > 20000)
op._cooldown.clear()
op._mark_cooldown("x", "Error code: 429 - too many requests")
check("a plain 429 is still the 90 s cooldown", 0 < op._cooldown["x"] - time.time() <= 90)
op._cooldown.clear()

print(f"\n{N - len(FAILS)} / {N} checks passed")
if FAILS:
    print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1)
