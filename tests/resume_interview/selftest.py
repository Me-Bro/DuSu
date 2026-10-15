"""Resume Interview - tier 2: the real HTTP layer + a scratch Postgres, with a STUB model and STUB speech-to-text.

Run via tests/resume_interview/run.sh (it starts a throwaway postgres, never the app's `dusu-db-1`). Everything goes through the real FastAPI app
(routing, gates, JSON handling) in-process with httpx's ASGI transport; the model is replaced by a stub that counts calls per stage, which is how
"a duplicate request = exactly one model call" is proven. Plain Python; non-zero exit on any failure.
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/resume_interview")

import httpx                                                       # noqa: E402

from app import auth, db, main as M                                # noqa: E402
from app.resume_interview import api as ri_api, rules, life_lines   # noqa: E402
from app.resume_interview.models import RI_TABLES                  # noqa: E402
from unit_fixtures import ANSWER_GOOD, ANSWER_WEAK, JD, RESUME, make_docx, make_pdf    # noqa: E402

FAILS: list[str] = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:300]}")


def section(t):
    print(f"\n== {t}")


from stub_llm import StubLLM                                         # noqa: E402


STUB = StubLLM()
ri_api.llm = STUB                                                  # the module-level name the endpoints call

PDF_RESUME = make_pdf(RESUME.replace("•", "-").split("\n"))
RESUME2 = RESUME.replace("Customer churn analysis", "Loaded data into Snowflake for the finance team.\nCustomer churn analysis")


def words_for(text, wpm_gap=0.42):
    out, t = [], 0.5
    for w in text.split():
        out.append([w, round(t, 2), round(t + 0.32, 2)])
        t += wpm_gap
    return out


def answer_body(text=ANSWER_GOOD, key=None, device="devA", keys=True, duration=None):
    ws = words_for(text)
    b = {"transcript": text, "words": ws, "segments": [[0, ws[-1][2], -0.2, 0.01]], "duration_sec": duration or ws[-1][2] + 1, "engine": "groq",
         "audio_device": device, "client_key": key or f"k{time.time_ns()}"}
    if keys:
        b["keys"] = {"gemini": "stub-key"}
    return b


# ----------------------------------------------------------------------------- harness
async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh, which blanks them (a test must never spend or reveal real keys)"
    # OLD -> NEW rehearsal: production has every table EXCEPT the ri_* ones. Build exactly that schema, put a learner in it, then run init_db() as the new code does
    # at start-up: it must add the four new tables (and their partial unique indexes) next to the existing data, and be safe to run twice.
    for _ in range(20):                                              # a freshly started postgres restarts once after initdb
        try:
            async with db._engine.begin() as conn:
                await conn.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if not t.name.startswith("ri_")]))
            break
        except Exception:
            await asyncio.sleep(1)
    from sqlalchemy import text as sa_text
    async with db._engine.connect() as conn:
        pre = {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'ri\\_%'"))).all()}
    await db.login({"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""})
    check("rehearsal: the old schema has no ri_* tables", pre == set(), pre)
    await db.init_db()
    await db.init_db()
    async with db._engine.connect() as conn:
        post = {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'ri\\_%'"))).all()}
        idx = {r[0] for r in (await conn.execute(sa_text("select indexname from pg_indexes where tablename like 'ri\\_%'"))).all()}
        users = (await conn.execute(sa_text("select count(*) from users where id='u-old'"))).scalar()
    check("rehearsal: init_db() adds exactly the four ri_* tables next to the existing data, twice in a row", post == {"ri_documents", "ri_analyses", "ri_sessions", "ri_turns"} and users == 1, (post, users))
    check("rehearsal: the partial unique indexes (idempotency keys, one analysis per pair) exist", {"uq_ri_analysis_pair"} <= idx and len([i for i in idx if i.startswith("uq_")]) >= 6, sorted(idx))
    owner = {"sub": "u-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    ann = {"sub": "u-ann", "email": "ann@example.com", "name": "Ann", "picture": ""}
    bob = {"sub": "u-bob", "email": "bob@example.com", "name": "Bob", "picture": ""}
    cat = {"sub": "u-cat", "email": "cat@example.com", "name": "Cat", "picture": ""}
    dan = {"sub": "u-dan", "email": "dan@example.com", "name": "Dan", "picture": ""}
    eve = {"sub": "u-eve", "email": "eve@example.com", "name": "Eve", "picture": ""}
    fay = {"sub": "u-fay", "email": "fay@example.com", "name": "Fay", "picture": ""}
    gus = {"sub": "u-gus", "email": "gus@example.com", "name": "Gus", "picture": ""}
    hal = {"sub": "u-hal", "email": "hal@example.com", "name": "Hal", "picture": ""}
    for u in (owner, ann, bob, cat, dan, eve, fay, gus, hal):
        await db.login(u)
    T = {k: auth.make_session(u) for k, u in (("owner", owner), ("ann", ann), ("bob", bob), ("cat", cat), ("dan", dan), ("eve", eve), ("fay", fay), ("gus", gus), ("hal", hal))}
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        def H(who, **extra):
            return {"Authorization": "Bearer " + T[who], **extra}

        async def GET(who, path, **kw):
            return await c.get("/rinterview" + path, headers=H(who), **kw)

        async def POST(who, path, body=None, **kw):
            return await c.post("/rinterview" + path, headers=H(who), json=body if body is not None else {}, **kw)

        async def upload(who, data, kind, name="My Resume", ctype="application/pdf"):
            return await c.post(f"/rinterview/documents/upload?kind={kind}", headers=H(who, **{"Content-Type": ctype, "X-RI-Name": name}), content=data)

        KEYS = {"keys": {"gemini": "stub-key"}}

        # ------------------------------------------------------------------ the switch and the gates
        section("switch off / auth / gates")
        await db.set_setting("resume_interview", "off")
        M.invalidate_access_cache()
        r = await GET("ann", "/state")
        check("switch OFF: state is 404", r.status_code == 404)
        r = await upload("ann", PDF_RESUME, "resume")
        check("switch OFF: upload is 404", r.status_code == 404)
        r = await GET("ann", "/export")
        check("switch OFF: export still works (data is never trapped)", r.status_code == 200 and "ri_documents" in r.json())
        r = await POST("ann", "/delete-all", {"confirm": True})
        check("switch OFF: delete-all still works", r.status_code == 200 and r.json() == {"ok": True})
        r = await c.get("/rinterview/state")
        check("no token -> 401", r.status_code == 401)
        r = await c.get("/rinterview/state", headers={"Authorization": "Bearer junk.token"})
        check("junk token -> 401", r.status_code == 401)
        me = (await c.get("/me", headers=H("owner"))).json()
        check("/me carries the new flags (False while off)", me.get("resume_interview") is False and me.get("ri_server_stt") is False)
        await db.set_setting("resume_interview", "owner")
        M.invalidate_access_cache()
        r = await GET("ann", "/state")
        check("switch OWNER: a normal learner still gets 404", r.status_code == 404)
        r = await GET("owner", "/state")
        check("switch OWNER: the owner is in", r.status_code == 200)
        await db.early_add("bob@example.com")
        M.invalidate_access_cache()
        r = await GET("bob", "/state")
        check("switch OWNER: an early-access tester is in (visibility only)", r.status_code == 200)
        me = (await c.get("/me", headers=H("bob"))).json()
        check("/me for the tester: flag true, not an admin", me.get("resume_interview") is True and me.get("role") == "user")
        r = await c.get("/admin/overview", headers=H("bob"))
        check("the tester has no admin rights", r.status_code == 403)
        await db.early_remove("bob@example.com")
        await db.set_setting("resume_interview", "on")
        M.invalidate_access_cache()
        r = await GET("ann", "/state")
        check("switch ON: everyone is in", r.status_code == 200 and r.json()["resumes"] == [])
        ov = (await c.get("/admin/overview", headers=H("owner"))).json()
        check("/admin/overview reports the switch and a health block", ov.get("resume_interview") == "on" and isinstance(ov.get("resume_interview_health"), dict))
        r = await c.post("/admin/settings", headers=H("owner"), json={"resume_interview": "owner"})
        check("/admin/settings flips it", r.status_code == 200 and r.json()["resume_interview"] == "owner")
        r = await c.post("/admin/settings", headers=H("owner"), json={"resume_interview": "on"})
        M.invalidate_access_cache()
        r = await c.post("/admin/settings", headers=H("owner"), json={"level_test": True})
        check("/admin/settings with the field absent leaves it alone", (await c.get("/admin/overview", headers=H("owner"))).json()["resume_interview"] == "on")
        await db.set_user_status("u-bob", "blocked")
        r = await GET("bob", "/state")
        check("a blocked account is 403", r.status_code == 403)
        await db.set_user_status("u-bob", "active")

        # ------------------------------------------------------------------ documents
        section("documents")
        r = await upload("ann", PDF_RESUME, "resume", name="Asha Resume")
        j = r.json()
        check("upload PDF -> 200, redacted preview, counts", r.status_code == 200 and "asha.verma" not in j["preview"] and j["redactions"]["email"] == 1 and j["document"]["source"] == "pdf", r.text[:200])
        resume_id = j["document"]["id"]
        check("the document row has no filename column and a safe default title", j["document"]["title"] == "Asha Resume" and "pdf" not in json.dumps({k: v for k, v in j["document"].items() if k != "source"}).lower())
        r = await upload("ann", PDF_RESUME, "resume", name="Other name")
        check("the same text again -> duplicate, same id", r.json()["duplicate"] is True and r.json()["document"]["id"] == resume_id)
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "jd", "text": JD, "title": "Data Analyst", "company": "Acme Corp", "client_key": "jdkey1"})
        check("paste a JD -> 200", r.status_code == 200 and r.json()["document"]["kind"] == "jd", r.text[:200])
        jd_id = r.json()["document"]["id"]
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "jd", "text": JD + " changed", "client_key": "jdkey1"})
        check("a repeated client_key replays the first document", r.json()["document"]["id"] == jd_id and r.json()["duplicate"] is True)
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "resume", "text": "too short"})
        check("too short -> 422 doc_too_short", r.status_code == 422 and r.json()["detail"] == {"error": "doc_too_short"})
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "other", "text": RESUME})
        check("bad kind -> 422", r.status_code == 422)
        r = await upload("ann", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"z" * 200, "resume", ctype="application/msword")
        check("legacy .doc -> 415 hint doc", r.status_code == 415 and r.json()["detail"] == {"error": "unsupported_type", "hint": "doc"})
        r = await upload("ann", b"\x00\x01\xff" * 400, "resume", ctype="application/octet-stream")
        check("binary junk -> 415 hint other", r.status_code == 415 and r.json()["detail"]["hint"] == "other")
        r = await upload("ann", make_pdf([], blank=True), "resume")
        check("image-only PDF -> 422 no_text", r.status_code == 422 and r.json()["detail"] == {"error": "no_text"}, r.text[:200])
        r = await upload("ann", make_pdf(["secret " * 40], encrypt_user="pw"), "resume")
        check("password-protected PDF -> 422 encrypted", r.status_code == 422 and r.json()["detail"] == {"error": "encrypted"}, r.text[:200])
        r = await upload("ann", make_docx(["Experience at Acme for 2 years as an analyst. " * 12]), "resume", ctype="application/octet-stream")
        check("DOCX works", r.status_code == 200 and r.json()["document"]["source"] == "docx", r.text[:200])
        r = await c.post("/rinterview/documents/upload?kind=resume", headers=H("ann", **{"Content-Type": "application/pdf", "Content-Length": str(rules.MAX_UPLOAD_BYTES + 1)}), content=b"x" * 10)
        check("Content-Length above the cap -> 413 before reading", r.status_code == 413)
        r = await c.post("/rinterview/documents/upload?kind=resume", headers=H("ann", **{"Content-Type": "application/pdf"}), content=b"%PDF-" + b"x" * (rules.MAX_UPLOAD_BYTES + 100))
        check("a streamed body above the cap -> 413", r.status_code == 413)
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), content=b'{"kind":"resume","text":"' + b"a" * (rules.MAX_JSON_BYTES + 10) + b'"}')
        check("an oversized JSON body -> 413", r.status_code == 413)
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), content=b"not json")
        check("malformed JSON -> 422", r.status_code == 422)
        nul_body = json.dumps({"kind": "resume", "text": ("Built dashboards for sales. \x00 with NUL and lone \ud800 chars. " * 12)}).encode()     # ensure_ascii: a lone surrogate travels as the escape \ud800
        r = await c.post("/rinterview/documents/paste", headers=H("ann", **{"Content-Type": "application/json"}), content=nul_body)
        got = (await GET("ann", f"/documents/{r.json()['document']['id']}")).json() if r.status_code == 200 else {}
        check("NUL / surrogates are stripped before storing", r.status_code == 200 and "\x00" not in got.get("text", "x\x00") and "\ud800" not in got.get("text", "\ud800"), r.text[:200])
        r = await GET("ann", f"/documents/{jd_id}")
        check("GET document returns the redacted text", r.status_code == 200 and "Requirements" in r.json()["text"])

        # ------------------------------------------------------------------ analysis: caching + the claim pattern
        section("sessions + analysis (stub model call counts)")
        r = await POST("ann", "/sessions", {"resume_id": resume_id, "jd_id": jd_id, "settings": {"type": "mixed", "feedback_lang": "en"}, "client_key": "sk1"})
        check("create session", r.status_code == 200 and r.json()["session"]["status"] == "draft", r.text[:200])
        sid = r.json()["session"]["id"]
        r2 = await POST("ann", "/sessions", {"resume_id": resume_id, "jd_id": jd_id, "client_key": "sk1"})
        check("create is idempotent by client_key", r2.json()["session"]["id"] == sid)
        STUB.n.clear()
        STUB.delay = 0.4
        r1, r2 = await asyncio.gather(POST("ann", f"/sessions/{sid}/analyze", KEYS), POST("ann", f"/sessions/{sid}/analyze", KEYS))
        codes = sorted([r1.status_code, r2.status_code])
        check("two simultaneous analyzes -> ONE model run per stage (claim pattern)", STUB.n["jd"] == 1 and STUB.n["match"] == 1, dict(STUB.n))
        check("...and one of them got the result, the other 202 pending or the same result", codes in ([200, 200], [200, 202]), codes)
        STUB.delay = 0
        r = await POST("ann", f"/sessions/{sid}/analyze", KEYS)
        an = r.json()["analysis"]
        check("analyze again -> cached, no new model call", r.status_code == 200 and STUB.n["jd"] == 1 and STUB.n["match"] == 1)
        reqs_by = {q["id"]: q for q in an["requirements"]}
        check("analysis: statuses, evidence snapped to real resume lines, score, band", an["state"] == "done" and reqs_by["r2"]["status"] == "met" and "SQL" in reqs_by["r2"]["evidence"]
              and reqs_by["r5"]["status"] == "missing" and isinstance(an["match_score"], int) and an["band"] in ("strong", "good", "fair", "weak"), json.dumps(an)[:300])
        check("analysis: edits flagged only-if-true; verdict; role", len(an["edits"]) == 2 and an["edits"][0]["only_if_true"] and an["verdict"] and an["role"]["title"] == "Data Analyst")
        check("the session title becomes the real job once it is known", (await GET("ann", f"/sessions/{sid}")).json()["session"]["title"] == "Data Analyst - Acme Corp")
        check("analysis: a computed note about the personal-details section the redactor removed", any("personal details" in n["issue"].lower() for n in an["notes"]), an["notes"])
        r = await GET("ann", f"/documents/{jd_id}")
        check("the job's requirements are stored with the JD (stable ids), title taken from the role", len(r.json()["requirements"]) == 6 and r.json()["role"]["company"] == "Acme Corp")
        r = await POST("ann", f"/sessions/{sid}/analyze", KEYS)
        r = await c.patch(f"/rinterview/sessions/{sid}/picks", headers=H("ann"), json={"edit_ids": ["e1", "e9", "e1"]})
        check("picks: valid ids kept once, unknown dropped", r.json() == {"ok": True, "picked": ["e1"]})
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("GET session: shape + picked flag + counts + can_finish", st["analysis"]["edits"][0]["picked"] is True and st["counts"]["asked"] == 0 and st["can_finish"] == {"ok": False, "need": 3, "reasons": ["need_real_answers"]}
              and st["open_turn_id"] is None and st["queued_count"] == 0 and "server_now" in st and st["report"] is None)
        # keys_required for a learner with no keys of their own (growth phase)
        r = await c.post(f"/rinterview/sessions/{sid}/analyze", headers=H("ann"), json={})
        check("an LLM endpoint without keys -> 402 keys_required (non-owner)", r.status_code == 402 and r.json()["detail"] == "keys_required")
        # model failures
        r = await POST("ann", "/sessions", {"resume_id": resume_id, "jd_id": jd_id, "client_key": "sk-fail"})
        sid_f = r.json()["session"]["id"]
        res2 = (await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "jd", "text": JD + " variant job", "title": "Other job"})).json()["document"]["id"]
        r = await POST("ann", "/sessions", {"resume_id": resume_id, "jd_id": res2, "client_key": "sk-fail2"})
        sid_f = r.json()["session"]["id"]
        STUB.fail["match"] = RuntimeError("all providers/models unavailable: Error code: 429 - quota exceeded")
        r = await POST("ann", f"/sessions/{sid_f}/analyze", KEYS)
        check("a quota failure -> 429 quota (and the claim is released)", r.status_code == 429 and r.json()["detail"] == "quota", r.text[:200])
        STUB.fail["match"] = RuntimeError("provider returned an unreadable reply")
        r = await POST("ann", f"/sessions/{sid_f}/analyze", KEYS)
        check("another failure -> 502 analysis_unavailable", r.status_code == 502 and r.json()["detail"] == {"error": "analysis_unavailable"}, r.text[:200])
        STUB.fail.clear()
        r = await POST("ann", f"/sessions/{sid_f}/analyze", KEYS)
        check("...and a retry works (state 'failed' is re-claimable)", r.status_code == 200 and r.json()["analysis"]["state"] == "done", r.text[:200])

        # ------------------------------------------------------------------ re-upload an improved resume
        section("swap-resume (re-upload)")
        r = await c.post("/rinterview/documents/paste", headers=H("ann"), json={"kind": "resume", "text": RESUME2, "title": "Resume v2", "parent_id": resume_id})
        v2 = r.json()["document"]["id"]
        check("a new version links to its parent", r.status_code == 200 and r.json()["document"]["parent_id"] == resume_id, r.text[:200])
        STUB.n.clear()
        r = await POST("ann", f"/sessions/{sid}/swap-resume", {"resume_id": v2, **KEYS})
        an2 = r.json()["analysis"]
        check("swap: only call B ran (the job's requirements are reused)", r.status_code == 200 and STUB.n["jd"] == 0 and STUB.n["match"] == 1, dict(STUB.n))
        check("swap: the change is reported (prev score / band / changed requirements)", an2["prev"] and an2["prev"]["match_score"] == an["match_score"] and {x["id"] for x in an2["prev"]["changed"]} == {"r5", "r6"}, json.dumps(an2.get("prev")))
        check("swap: the score went up", an2["match_score"] > an["match_score"])
        check("swap: earlier suggestions that now look done are carried over as addressed", "pe1" in an2["prev"]["addressed_edits"] and any(e["id"] == "pe1" and e["addressed"] and e["picked"] for e in an2["edits"]), json.dumps(an2["edits"])[:300])
        sess_now = (await GET("ann", f"/sessions/{sid}")).json()["session"]
        check("the session now points at the new resume", sess_now["resume_id"] == v2 and sess_now["status"] == "matched")
        r = await POST("ann", f"/sessions/{sid}/swap-resume", {"resume_id": 999999, **KEYS})
        check("swap with an unknown resume -> 404", r.status_code == 404)

        # ------------------------------------------------------------------ start
        section("start + the plan")
        STUB.n.clear()
        STUB.delay = 0.4
        r1, r2 = await asyncio.gather(POST("ann", f"/sessions/{sid}/start", KEYS), POST("ann", f"/sessions/{sid}/start", KEYS))
        check("two simultaneous starts -> ONE plan call", STUB.n["plan"] == 1, dict(STUB.n))
        STUB.delay = 0
        r = await POST("ann", f"/sessions/{sid}/start", KEYS)
        j = r.json()
        check("start again -> the already-open first question, no new call", r.status_code == 200 and STUB.n["plan"] == 1 and j["turn"]["idx"] == 1 and j["turn"]["kind"] == "intro", r.text[:200])
        t1 = j["turn"]
        check("the plan is queued rows (>= 8) and the counts add up", j["queued_count"] >= 6 and j["counts"]["asked"] == 1)
        r = await POST("ann", f"/sessions/{sid}/swap-resume", {"resume_id": resume_id, **KEYS})
        check("swap after Start -> 409 wrong_state", r.status_code == 409 and r.json()["detail"]["error"] == "wrong_state")
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("GET session: open turn + brief role; queued questions are NOT sent", st["open_turn_id"] == t1["id"] and len(st["turns"]) == 1 and "queued" not in json.dumps(st["turns"]))

        # ------------------------------------------------------------------ answers
        section("answers")
        tid = t1["id"]
        STUB.n.clear()
        r = await POST("ann", f"/sessions/{sid}/turns/{tid}/answer", answer_body("I did some work.", duration=3))
        check("too short -> too_short, no model call, nothing stored", r.status_code == 200 and r.json()["too_short"] is True and STUB.n["answer"] == 0)
        r = await POST("ann", f"/sessions/{sid}/turns/{tid}/answer", {**answer_body("Thank you. " * 14, duration=15), "segments": [[0, 15, -1.5, 0.9]]})
        check("a silence hallucination -> too_short reason no_speech", r.json().get("too_short") is True and r.json()["reason"] == "no_speech", r.text[:200])
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("...and the question is still open", st["turns"][0]["status"] == "asked")
        STUB.delay = 0.4
        body = answer_body(ANSWER_GOOD, key="same-key")
        r1, r2 = await asyncio.gather(POST("ann", f"/sessions/{sid}/turns/{tid}/answer", body), POST("ann", f"/sessions/{sid}/turns/{tid}/answer", body))
        check("the same answer sent twice at once -> ONE model call", STUB.n["answer"] == 1, dict(STUB.n))
        STUB.delay = 0
        r = await POST("ann", f"/sessions/{sid}/turns/{tid}/answer", body)
        j = r.json()
        check("replaying the same key returns the stored feedback (no new call)", r.status_code == 200 and STUB.n["answer"] == 1 and j["turn"]["feedback_state"] == "done" and j["turn"]["status"] == "answered", r.text[:300])
        fb = j["turn"]["feedback"]
        check("feedback has the contract's shape (bands, scores, delivery, worked...)", set(fb["bands"]) == {"content", "language", "delivery"} and fb["delivery"]["measured"] is True
              and fb["delivery"]["wpm"] and "better_answer" in fb and fb["follow_up"] and j["turn"]["real"] is True, json.dumps(fb)[:300])
        check("the transcript is stored (redacted lightly) and the audio device recorded", j["turn"]["answer"].startswith("In my last role") and j["turn"]["audio_device"] == "devA" and j["turn"]["engine"] == "groq")
        r = await POST("ann", f"/sessions/{sid}/turns/{tid}/answer", answer_body(ANSWER_GOOD, key="other-key"))
        check("a different key on an answered turn -> 409 already_answered + the stored turn", r.status_code == 409 and r.json()["detail"]["error"] == "already_answered" and r.json()["detail"]["turn"]["id"] == tid)
        # next: double tap
        r1, r2 = await asyncio.gather(POST("ann", f"/sessions/{sid}/next"), POST("ann", f"/sessions/{sid}/next"))
        check("double-tapping Next -> the same single open question", r1.json()["turn"]["id"] == r2.json()["turn"]["id"] and r1.json()["turn"]["idx"] == 2, (r1.text[:150], r2.text[:150]))
        t2 = r1.json()["turn"]
        check("the second question is the next planned one (strong answer: no follow-up)", t2["source"] == "plan" and t2["kind"] == "resume")
        # a weak answer -> a follow-up
        STUB.n.clear()
        r = await POST("ann", f"/sessions/{sid}/turns/{t2['id']}/answer", answer_body(ANSWER_WEAK))
        j = r.json()
        check("a weak answer scores in a lower band", r.status_code == 200 and j["turn"]["feedback"]["band"] in ("fair", "needs_work") and j["turn"]["feedback"]["mistakes"], r.text[:300])
        r = await POST("ann", f"/sessions/{sid}/next")
        t3 = r.json()["turn"]
        check("a weak answer gets ONE follow-up (from its feedback)", t3["source"] == "followup" and t3["question"].startswith("How did you check"), r.text[:200])
        r = await POST("ann", f"/sessions/{sid}/turns/{t3['id']}/skip")
        check("skip marks the turn skipped, not counted", r.status_code == 200 and r.json()["turn"]["status"] == "skipped" and r.json()["counts"]["real"] == 2)
        r = await POST("ann", f"/sessions/{sid}/next")
        t4 = r.json()["turn"]
        check("after a follow-up the plan continues (never two follow-ups in a row)", t4["source"] == "plan" and t4["idx"] == 4)
        # finish gate
        r = await POST("ann", f"/sessions/{sid}/finish")
        check("Finish with 2 real answers -> 409 need_more (need 1)", r.status_code == 409 and r.json()["detail"] == {"error": "need_more", "need": 1, "reasons": ["need_real_answers"]}, r.text[:200])
        # a failing model keeps the transcript
        STUB.fail["answer"] = RuntimeError("provider returned an unreadable reply")
        r = await POST("ann", f"/sessions/{sid}/turns/{t4['id']}/answer", answer_body(ANSWER_GOOD, key="fail-key"))
        d = r.json()["detail"]
        check("model down -> 502 feedback_unavailable with saved:true and the stored turn", r.status_code == 502 and d["error"] == "feedback_unavailable" and d["saved"] is True and d["turn"]["answer"].startswith("In my last role"), r.text[:300])
        check("...the turn is 'failed' with delivery-only feedback; it still counts as a real answer", d["turn"]["feedback_state"] == "failed" and set(d["turn"]["feedback"]) >= {"delivery", "scores"} and d["turn"]["real"] is True)
        STUB.fail["answer"] = RuntimeError("all providers/models unavailable: 429 quota")
        r = await POST("ann", f"/sessions/{sid}/turns/{t4['id']}/feedback", KEYS)
        check("retry while the quota is out -> 429 quota (transcript still saved)", r.status_code == 429 and r.json()["detail"] == "quota")
        STUB.fail.clear()
        STUB.n.clear()
        r = await POST("ann", f"/sessions/{sid}/turns/{t4['id']}/feedback", KEYS)
        check("retry feedback -> done", r.status_code == 200 and r.json()["turn"]["feedback_state"] == "done" and STUB.n["answer"] == 1, r.text[:200])
        r = await POST("ann", f"/sessions/{sid}/turns/{t4['id']}/feedback", KEYS)
        check("retry again on a finished feedback -> stored, no new call", r.status_code == 200 and STUB.n["answer"] == 1)
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("now 3 real answers -> can_finish", st["can_finish"] == {"ok": True, "need": 0, "reasons": []} and st["counts"]["real"] == 3)
        # the open question is dropped on finish
        r = await POST("ann", f"/sessions/{sid}/next")
        open_turn = r.json()["turn"]
        r1, r2 = await asyncio.gather(POST("ann", f"/sessions/{sid}/finish"), POST("ann", f"/sessions/{sid}/finish"))
        ok = [x for x in (r1, r2) if x.status_code == 200]
        check("two simultaneous Finishes both succeed with the same report", len(ok) == 2 and ok[0].json()["report"]["overall"] == ok[1].json()["report"]["overall"], (r1.text[:150], r2.text[:150]))
        rep = ok[0].json()["report"]
        progresses = [x.json().get("progress") for x in ok]
        check("XP is paid exactly ONCE (one Finish has progress, the other none)", sum(1 for p in progresses if p) == 1, progresses)
        async with db._Session() as s:
            from sqlalchemy import func, select
            n_scores = (await s.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == "u-ann", db.SessionScore.mode == "resume_interview"))).scalar()
        check("exactly one session_scores row in mode resume_interview", n_scores == 1, n_scores)
        check("the report: overall, 5 categories, coverage, per-question, no model was called", rep["real"] == 3 and len(rep["categories"]) == 5 and rep["coverage"] and len(rep["per_question"]) >= 3 and STUB.n["answer"] == 1)
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("the session is finished and the open question was dropped", st["session"]["status"] == "finished" and all(t["id"] != open_turn["id"] for t in st["turns"]) and st["report"]["overall"] == rep["overall"])
        r = await POST("ann", f"/sessions/{sid}/finish")
        check("finish again -> the stored report, no new XP", r.status_code == 200 and r.json()["progress"] is None and r.json()["report"]["overall"] == rep["overall"])
        r = await POST("ann", f"/sessions/{sid}/next")
        check("next after finish -> 409 finished", r.status_code == 409 and r.json()["detail"]["error"] == "finished")
        r = await POST("ann", f"/sessions/{sid}/turns/{t4['id']}/answer", answer_body(ANSWER_GOOD))
        check("answering after finish -> 409", r.status_code == 409)
        lines = await life_lines.resume_interview_lines("u-ann", "ann@example.com")
        check("DuSu's life lines: the last interview's role + score, no resume or job text", len(lines) >= 1 and "Data Analyst" in lines[0] and f"{rep['overall']}/100" in lines[0] and "Snowflake" not in " ".join(lines))
        await db.set_setting("resume_interview", "off")
        M.invalidate_access_cache()
        check("...and no lines at all while the switch is off for that learner", await life_lines.resume_interview_lines("u-ann", "ann@example.com") == [])
        await db.set_setting("resume_interview", "on")
        M.invalidate_access_cache()
        r = await GET("ann", "/state")
        j = r.json()
        fin = [x for x in j["sessions"] if x["id"] == sid]
        check("hub state: the finished interview with its counts and score", fin and fin[0]["status"] == "finished" and fin[0]["real"] == 3 and fin[0]["answered"] >= 3 and fin[0]["overall"] == rep["overall"], j["sessions"][:3])
        check("hub state: the newest unfinished session is the active one", j["active"] is not None and j["active"]["status"] != "finished" and j["active"]["id"] > sid)
        check("hub state: limits + today caps", j["limits"]["finish_min"] == 3 and j["today"]["sessions_cap"] == rules.SESSIONS_PER_DAY)

        # ------------------------------------------------------------------ the bank, the cap
        section("a long interview: plan -> bank, no repeats")
        r = await POST("ann", "/sessions", {"resume_id": resume_id, "jd_id": jd_id, "client_key": "long1"})
        sid2 = r.json()["session"]["id"]
        await POST("ann", f"/sessions/{sid2}/analyze", KEYS)
        STUB.n.clear()
        j = (await POST("ann", f"/sessions/{sid2}/start", KEYS)).json()
        check("a second interview for the same job asks the model not to repeat earlier questions (the plan call got them)", STUB.n["plan"] == 1 and j["turn"]["idx"] == 1)
        seen = [j["turn"]["question"]]
        await POST("ann", f"/sessions/{sid2}/turns/{j['turn']['id']}/skip")
        for i in range(2, 25):
            r = await POST("ann", f"/sessions/{sid2}/next")
            if r.status_code != 200:
                break
            t = r.json()["turn"]
            seen.append(t["question"])
            await POST("ann", f"/sessions/{sid2}/turns/{t['id']}/skip")
        check("24 questions in a row: plan then the bank, never a repeat", len(seen) >= 20 and len(set(seen)) == len(seen), (len(seen), len(set(seen))))
        check("...every one is valid and none is a protected topic", all(rules.valid_question(q) and not rules.protected_topic(q) for q in seen))
        check("...some came from the bank", any(q.startswith(("Why are you interested", "Where do you see", "What motivates", "Describe a time", "Tell me about a mistake")) for q in seen[6:]))

        # ------------------------------------------------------------------ two learners: isolation
        section("two learners: every endpoint 404s on someone else's ids")
        probes = [("GET", f"/documents/{resume_id}"), ("DELETE", f"/documents/{resume_id}"), ("GET", f"/sessions/{sid}"), ("DELETE", f"/sessions/{sid}"),
                  ("POST", f"/sessions/{sid}/analyze"), ("POST", f"/sessions/{sid}/swap-resume", {"resume_id": v2}), ("PATCH", f"/sessions/{sid}/picks", {"edit_ids": ["e1"]}),
                  ("POST", f"/sessions/{sid}/start"), ("POST", f"/sessions/{sid}/next"), ("POST", f"/sessions/{sid}/finish"),
                  ("POST", f"/sessions/{sid}/turns/{tid}/answer", answer_body()), ("POST", f"/sessions/{sid}/turns/{tid}/feedback"),
                  ("POST", f"/sessions/{sid}/turns/{tid}/skip"), ("GET", f"/sessions/{sid}/turns/{tid}")]
        bad = []
        for m, path, *b in probes:
            body = {**(b[0] if b else {}), "keys": {"gemini": "k"}}
            r = await c.request(m, "/rinterview" + path, headers=H("bob"), json=body if m != "GET" and m != "DELETE" else None)
            if r.status_code != 404:
                bad.append((m, path, r.status_code))
        check(f"Bob gets 404 on all {len(probes)} of Ann's ids", not bad, bad)
        r = await POST("bob", "/sessions", {"resume_id": resume_id, "jd_id": jd_id})
        check("Bob cannot create a session from Ann's documents", r.status_code == 422 and r.json()["detail"] == {"error": "no_resume"})
        bs = (await GET("bob", "/state")).json()
        check("Bob's hub is empty", bs["resumes"] == [] and bs["jds"] == [] and bs["sessions"] == [])
        r = await c.post("/rinterview/documents/paste", headers=H("bob"), json={"kind": "resume", "text": RESUME, "parent_id": resume_id})
        check("a foreign parent_id is ignored, not linked", r.status_code == 200 and r.json()["document"]["parent_id"] is None)
        r = await GET("bob", "/export")
        check("Bob's export holds only Bob's rows", all(row["user_id"] == "u-bob" for t in RI_TABLES for row in r.json()[t.__tablename__]))

        # ------------------------------------------------------------------ limits
        section("limits")
        for i in range(rules.MAX_RESUMES + 2):
            r = await c.post("/rinterview/documents/paste", headers=H("cat"), json={"kind": "resume", "text": f"Variant {i} " + RESUME})
            if r.status_code != 200:
                break
        check("the per-learner resume cap -> 409 limit_documents", i == rules.MAX_RESUMES and r.status_code == 409 and r.json()["detail"] == {"error": "limit_documents"}, f"{i} {r.status_code} {r.text[:120]}")
        old_cap = rules.SESSIONS_PER_DAY
        rules.SESSIONS_PER_DAY = 2
        r = await POST("bob", "/sessions", {"resume_id": r.json()["document"]["id"] if False else (await GET("bob", "/state")).json()["resumes"][0]["id"],
                                            "jd_id": (await c.post("/rinterview/documents/paste", headers=H("bob"), json={"kind": "jd", "text": JD})).json()["document"]["id"], "client_key": "b1"})
        bres = (await GET("bob", "/state")).json()["resumes"][0]["id"]
        bjd = (await GET("bob", "/state")).json()["jds"][0]["id"]
        r2 = await POST("bob", "/sessions", {"resume_id": bres, "jd_id": bjd, "client_key": "b2"})
        r3 = await POST("bob", "/sessions", {"resume_id": bres, "jd_id": bjd, "client_key": "b3"})
        check("sessions per day -> 429 daily_limit", r3.status_code == 429 and r3.json()["detail"] == "daily_limit", (r.status_code, r2.status_code, r3.status_code))
        rules.SESSIONS_PER_DAY = old_cap
        old_ans = rules.ANSWERS_PER_DAY
        rules.ANSWERS_PER_DAY = 1
        rules.ANSWERS_PER_DAY = old_ans

        # ------------------------------------------------------------------ transcribe (stubbed speech-to-text)
        section("transcribe")
        r = await c.post("/rinterview/transcribe?lang=en", headers=H("owner", **{"Content-Type": "audio/webm"}), content=b"\x1aE\xdf\xa3" + b"0" * 2000)
        check("no Groq / Gemini key anywhere -> 400 no_groq_key", r.status_code == 400 and r.json()["detail"] == "no_groq_key", r.text[:150])
        old_key = M.settings.gemini_api_key
        M.settings.gemini_api_key = "stub"

        async def fake_gemini(data, mime, lang, key):
            return {"text": "hello world " * 10, "duration": 7.5, "words": [], "segments": [], "engine": "gemini"}
        real_g = M._gemini_transcribe
        M._gemini_transcribe = fake_gemini
        r = await c.post("/rinterview/transcribe?lang=en", headers=H("owner", **{"Content-Type": "audio/webm"}), content=b"\x1aE\xdf\xa3" + b"0" * 2000)
        check("Gemini fallback -> the Groq-shaped JSON with engine", r.status_code == 200 and r.json()["engine"] == "gemini" and r.json()["words"] == [], r.text[:150])
        r = await c.post("/rinterview/transcribe?lang=en", headers=H("owner"), content=b"")
        check("empty audio -> 400", r.status_code == 400)
        old_cap_stt, ri_api._STT_PER_DAY = ri_api._STT_PER_DAY, 2
        ri_api._stt_day.clear()
        codes = []
        for _ in range(3):
            r = await c.post("/rinterview/transcribe?lang=en", headers=H("owner", **{"Content-Type": "audio/webm"}), content=b"\x1aE\xdf\xa3" + b"0" * 500)
            codes.append(r.status_code)
        check("every proxied transcription counts against the day (not just saved answers): the 3rd of a cap of 2 -> 429 daily_limit", codes[-1] == 429 and r.json()["detail"] == "daily_limit" and codes[:2] == [200, 200], codes)
        ri_api._STT_PER_DAY = old_cap_stt
        ri_api._stt_day.clear()
        r = await c.post("/rinterview/transcribe?lang=en", headers=H("owner", **{"Content-Length": str(9 * 1024 * 1024)}), content=b"x")
        check("audio above the cap -> 413", r.status_code == 413)
        M._gemini_transcribe = real_g
        M.settings.gemini_api_key = old_key
        me = (await c.get("/me", headers=H("owner"))).json()
        check("/me: ri_server_stt is computed only when the feature is on for the learner", me["resume_interview"] is True and isinstance(me["ri_server_stt"], bool))

        # ------------------------------------------------------------------ the registry
        section("home registry (the old behaviour is untouched when the switch is off)")
        from app import home_content as hc
        on, off = hc.tiles({"resume_interview": True}), hc.tiles({})
        check("a tile only when the switch is on", any(t["id"] == "resume_interview" and t["route"] == "/resume-interview" for t in on) and all(t["id"] != "resume_interview" for t in off))
        check("Know About page lists it only for learners who have it (both languages)",
              all(any(x["id"] == "resume_interview" for x in hc.page({"resume_interview": True}, lg)["features"]) and not any(x["id"] == "resume_interview" for x in hc.page({}, lg)["features"]) for lg in ("en", "hi")))
        check("its Know About card says what is different from the HR mock", "resume" in [x for x in hc.page({"resume_interview": True}, "en")["features"] if x["id"] == "resume_interview"][0]["desc"].lower())
        check("the model's catalogue names it only when on", "resume_interview" in hc.catalog({"resume_interview": True}) and "resume_interview" not in hc.catalog({}))
        check("the keyword fallback is untouched ('resume' is not an interview keyword)", hc.detect_intent("let me resume my lesson") != "interview_prep")

        # ------------------------------------------------------------------ the independent review's findings
        section("review: ids, deep JSON, one parse at a time, claims, awards, outages")

        async def new_session(who, start=False):
            """A resume + a job + a session (+ the analysis and the plan) for `who`, through the real endpoints."""
            rr = await c.post("/rinterview/documents/paste", headers=H(who), json={"kind": "resume", "text": RESUME})
            jj = await c.post("/rinterview/documents/paste", headers=H(who), json={"kind": "jd", "text": JD, "title": "Data Analyst", "company": "Acme Corp"})
            rid, jid = rr.json()["document"]["id"], jj.json()["document"]["id"]
            s_ = (await POST(who, "/sessions", {"resume_id": rid, "jd_id": jid, "client_key": f"ns-{who}-{time.time_ns()}"})).json()["session"]["id"]
            if not start:
                return rid, jid, s_, None
            await POST(who, f"/sessions/{s_}/analyze", KEYS)
            return rid, jid, s_, (await POST(who, f"/sessions/{s_}/start", KEYS)).json()["turn"]

        async def answer_n(who, sid_, turn, n=3, text=ANSWER_GOOD):
            codes_, t_ = [], turn
            for i in range(n):
                r_ = await POST(who, f"/sessions/{sid_}/turns/{t_['id']}/answer", answer_body(text, key=f"{who}-{sid_}-{i}"))
                codes_.append(r_.status_code)
                if i < n - 1:
                    t_ = (await POST(who, f"/sessions/{sid_}/next")).json()["turn"]
            return codes_

        for path in ("/documents/99999999999", "/sessions/99999999999", "/sessions/99999999999/turns/1", "/sessions/1/turns/99999999999"):
            r = await GET("dan", path)
            check(f"an out-of-range id is a 404, not a 500: {path}", r.status_code == 404, r.status_code)
        r = await GET("dan", "/sessions?before=99999999999")
        check("an out-of-range keyset cursor is harmless", r.status_code == 200 and r.json()["sessions"] == [])
        for body_ in ({"resume_id": "x", "jd_id": 1.5}, {"resume_id": True, "jd_id": 99999999999}, {"resume_id": [1], "jd_id": {"a": 1}}):
            r = await POST("dan", "/sessions", body_)
            check(f"create_session with odd id types {body_} -> 422, not a 500", r.status_code == 422 and r.json()["detail"] == {"error": "no_resume"}, r.text[:120])
        for raw in (b"[" * 100000, b'{"a":' * 60000):
            r = await c.post("/rinterview/documents/paste", headers=H("dan", **{"Content-Type": "application/json"}), content=raw)
            check(f"deeply nested JSON ({raw[:6]!r}...) -> 422 bad_input, not a 500", r.status_code == 422, r.status_code)

        # one parse in flight per learner; a busy server says so
        ri_api._parsing.add("u-dan")
        r = await upload("dan", PDF_RESUME, "resume")
        check("a second upload while one is being parsed -> 429 rate", r.status_code == 429 and r.json()["detail"] == "rate", r.text[:100])
        ri_api._parsing.discard("u-dan")
        r = await upload("dan", PDF_RESUME, "resume")
        check("...and the learner's slot is released afterwards (a normal upload works, nothing left in flight)", r.status_code == 200 and "u-dan" not in ri_api._parsing, r.text[:100])
        from app.resume_interview import docs as ri_docs
        sem, held, old_wait = ri_docs._slots(), 0, ri_docs.SLOT_WAIT_S
        ri_docs.SLOT_WAIT_S = 0.2
        try:
            for _ in range(ri_docs._PARSE_SLOTS):
                await sem.acquire()
                held += 1
            t0 = time.time()
            r = await upload("dan", make_pdf(["Built dashboards for the sales team. " * 12]), "resume")
            check("both parse slots busy -> 429 rate within a second (no unbounded queue)", r.status_code == 429 and r.json()["detail"] == "rate" and time.time() - t0 < 2.5, (r.status_code, r.text[:100]))
        finally:
            for _ in range(held):
                sem.release()
            ri_docs.SLOT_WAIT_S = old_wait
        r = await upload("dan", make_pdf(["Built dashboards for the sales team. " * 12]), "resume")
        check("...and the slots work again afterwards", r.status_code == 200, r.text[:100])

        # `force` is gone: it could re-run a finished analysis past the daily cap and flip a good result to 'failed'
        rid_d, jid_d, sid_d, _t = await new_session("dan")
        await POST("dan", f"/sessions/{sid_d}/analyze", KEYS)
        STUB.n.clear()
        r = await POST("dan", f"/sessions/{sid_d}/analyze", {**KEYS, "force": True})
        check("analyze with force:true is just analyze: cached, no model call, still 'done'", r.status_code == 200 and STUB.n["match"] == 0 and r.json()["analysis"]["state"] == "done")

        # claims: fresh = 202, within the TTL still pending, past the TTL re-taken
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update as sa_update
        from app.resume_interview.models import RiAnalysis
        rid_e, jid_e, sid_e, _t = await new_session("eve")
        async with db._Session() as s_:
            s_.add(RiAnalysis(user_id="u-eve", resume_id=rid_e, jd_id=jid_e, state="pending", claimed_at=datetime.now(timezone.utc), rules_version=rules.RULES_VERSION, picked=[], result={}))
            await s_.commit()
        STUB.n.clear()
        r = await POST("eve", f"/sessions/{sid_e}/analyze", KEYS)
        check("a FRESH claim held by someone else -> 202 pending, no model call", r.status_code == 202 and r.json()["pending"] is True and STUB.n["match"] == 0, r.text[:100])
        async with db._Session() as s_:
            await s_.execute(sa_update(RiAnalysis).where(RiAnalysis.user_id == "u-eve").values(claimed_at=datetime.now(timezone.utc) - timedelta(seconds=100)))
            await s_.commit()
        r = await POST("eve", f"/sessions/{sid_e}/analyze", KEYS)
        check("a claim 100 s old is STILL pending (the TTL covers the slowest honest run: %d s)" % rules.CLAIM_TTL_S, r.status_code == 202 and STUB.n["match"] == 0, r.text[:100])
        from app.resume_interview import service as svc_
        now_ = datetime.now(timezone.utc)
        check("the payload reads a claim as 'pending' inside the TTL and 'failed' past it",
              svc_._analysis_payload(RiAnalysis(state="pending", claimed_at=now_ - timedelta(seconds=100), picked=[], result={}), now_)["state"] == "pending"
              and svc_._analysis_payload(RiAnalysis(state="pending", claimed_at=now_ - timedelta(seconds=rules.CLAIM_TTL_S + 5), picked=[], result={}), now_)["state"] == "failed")
        async with db._Session() as s_:
            await s_.execute(sa_update(RiAnalysis).where(RiAnalysis.user_id == "u-eve").values(claimed_at=datetime.now(timezone.utc) - timedelta(seconds=rules.CLAIM_TTL_S + 10)))
            await s_.commit()
        r = await POST("eve", f"/sessions/{sid_e}/analyze", KEYS)
        check("a claim past the TTL is stale: the work is re-taken and finishes", r.status_code == 200 and r.json()["analysis"]["state"] == "done" and STUB.n["match"] == 1, r.text[:150])

        # two sessions, the same resume + job, analysed at the same moment: one model run, no 500
        rid_f, jid_f, sid_f1, _t = await new_session("fay")
        sid_f2 = (await POST("fay", "/sessions", {"resume_id": rid_f, "jd_id": jid_f, "client_key": "fay-2"})).json()["session"]["id"]
        STUB.n.clear()
        STUB.delay = 0.3
        ra, rb = await asyncio.gather(POST("fay", f"/sessions/{sid_f1}/analyze", KEYS), POST("fay", f"/sessions/{sid_f2}/analyze", KEYS))
        STUB.delay = 0
        check("two sessions with the same resume + job analysed together: no 500, one model run", {ra.status_code, rb.status_code} <= {200, 202} and STUB.n["match"] == 1, (ra.status_code, rb.status_code, dict(STUB.n)))

        # a blocked account keeps its data rights (and nothing else)
        await db.set_user_status("u-fay", "blocked")
        r1 = await GET("fay", "/state")
        r2 = await GET("fay", "/export")
        r3 = await c.delete("/rinterview/documents/999", headers=H("fay"))
        check("a blocked account: 403 on use, but export and a delete still answer (data rights are not denied)", r1.status_code == 403 and r2.status_code == 200 and r3.status_code == 404, (r1.status_code, r2.status_code, r3.status_code))
        await db.set_user_status("u-fay", "active")

        # forged word timestamps cannot get a 3-word answer past the floor
        rid_g, jid_g, sid_g, tg = await new_session("gus", start=True)
        forged = {"transcript": "banana apple orange", "words": [[f"w{i}", 0.5 + i * 0.4, 0.8 + i * 0.4] for i in range(30)], "segments": [[0, 12, -0.2, 0.01]], "duration_sec": 12,
                  "engine": "groq", "audio_device": "devA", "client_key": "forged-1", "keys": {"gemini": "stub-key"}}
        STUB.n.clear()
        r = await POST("gus", f"/sessions/{sid_g}/turns/{tg['id']}/answer", forged)
        check("30 fake word rows + 3 spoken words -> too_short, no model call, nothing counted", r.status_code == 200 and r.json().get("too_short") is True and STUB.n["answer"] == 0, r.text[:200])

        # an outage on every answer: Finish still works, and the report does not invent a score
        rid_h, jid_h, sid_h, th = await new_session("eve", start=True)
        STUB.fail["answer"] = RuntimeError("provider returned an unreadable reply")
        codes = await answer_n("eve", sid_h, th, 3)
        STUB.fail.clear()
        check("three answers while the model is down: each is saved (502 feedback_unavailable, saved:true)", codes == [502, 502, 502], codes)
        st = (await GET("eve", f"/sessions/{sid_h}")).json()
        check("...and they all count as real answers, so Finish unlocks", st["counts"]["real"] == 3 and st["can_finish"]["ok"], st["counts"])
        r = await POST("eve", f"/sessions/{sid_h}/finish")
        j = r.json()
        check("Finish works with no feedback at all: overall None / band 'unknown' (no made-up 0 or delivery-only score)", r.status_code == 200 and j["report"]["overall"] is None and j["report"]["band"] == "unknown" and j["report"]["partial"], r.text[:300])
        check("...the delivery category is still reported (measured at answer time); the judged ones are 'not measured'", {c["key"]: c["score"] for c in j["report"]["categories"]}["delivery"] is not None
              and {c["key"]: c["score"] for c in j["report"]["categories"]}["language"] is None)
        check("...per-question rows carry no invented band", all(q["band"] in ("unknown", None) for q in j["report"]["per_question"]))
        check("...the hub lists it without a score", [x for x in (await GET("eve", "/state")).json()["sessions"] if x["id"] == sid_h][0]["overall"] is None)
        async with db._Session() as s_:
            from sqlalchemy import func, select
            row = (await s_.execute(select(db.SessionScore).where(db.SessionScore.user_id == "u-eve", db.SessionScore.mode == "resume_interview").order_by(db.SessionScore.id.desc()))).scalars().first()
            convs = (await s_.execute(select(db.Conversation).where(db.Conversation.user_id == "u-eve", db.Conversation.mode == "resume_interview"))).scalars().all()
        check("XP was paid once with the unmeasured components UNSCORED (vocabulary / grammar NULL, not 0)", row is not None and row.vocabulary is None and row.grammar_trend is None and row.overall > 0, (row.vocabulary, row.grammar_trend, row.overall) if row else None)
        check("the memory line says the feedback was unavailable (never 'scored 0')", len(convs) == 1 and "not available" in convs[0].summary and "scored 0" not in convs[0].summary, [c_.summary for c_ in convs])
        mem = await db.get_memory("u-eve")
        check("the learner's spoken words reached the shared vocabulary counter (the post-finish steps ran)", int((mem or {}).get("vocab_total", 0)) > 0, (mem or {}).get("vocab_total"))
        lines = await life_lines.resume_interview_lines("u-eve", "eve@example.com")
        check("DuSu's life line for it says 'not scored' (never 0/100)", lines and "not scored" in lines[0] and "0/100" not in lines[0], lines)

        # a failure AFTER the XP row is committed must not make a retry pay twice; a failure BEFORE it may
        real_badges, real_award = db.check_achievement_badges, db.award_speaker_progress

        async def boom(*a, **k):
            raise RuntimeError("badge check failed")
        rid_i, jid_i, sid_i, ti = await new_session("gus", start=True)
        await answer_n("gus", sid_i, ti, 3)
        db.check_achievement_badges = boom
        try:
            r = await POST("gus", f"/sessions/{sid_i}/finish")
        finally:
            db.check_achievement_badges = real_badges
        r2_ = await POST("gus", f"/sessions/{sid_i}/finish")
        async with db._Session() as s_:
            n_rows = (await s_.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == "u-gus", db.SessionScore.mode == "resume_interview"))).scalar()
        check("a failure after the XP row was committed: Finish still answers, and a replayed Finish does NOT pay a second time", r.status_code == 200 and r2_.status_code == 200 and n_rows == 1, (r.status_code, r2_.status_code, n_rows))
        rid_k, jid_k, sid_k, tk = await new_session("gus", start=True)
        await answer_n("gus", sid_k, tk, 3)

        async def boom_first(*a, **k):
            raise RuntimeError("database hiccup before anything was written")
        db.award_speaker_progress = boom_first
        try:
            r = await POST("gus", f"/sessions/{sid_k}/finish")
        finally:
            db.award_speaker_progress = real_award
        check("a failure BEFORE any XP row: Finish still answers with the report", r.status_code == 200 and r.json()["report"]["real"] == 3, r.status_code)
        r = await POST("gus", f"/sessions/{sid_k}/finish")
        async with db._Session() as s_:
            n_rows2 = (await s_.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == "u-gus", db.SessionScore.mode == "resume_interview"))).scalar()
        check("...and the replayed Finish pays it (the flag was released because nothing had been paid)", r.status_code == 200 and r.json()["progress"] is not None and n_rows2 == 2, (r.status_code, n_rows2))

        # /state: the newest UNFINISHED interview is found even when 30 newer ones fill the page, and has_more says there is an older page
        from app.resume_interview.models import RiSession as RiSession_
        old_spd = rules.SESSIONS_PER_DAY
        rules.SESSIONS_PER_DAY = 1000
        cres = (await GET("cat", "/state")).json()["resumes"][0]["id"]
        cjd = (await c.post("/rinterview/documents/paste", headers=H("cat"), json={"kind": "jd", "text": JD})).json()["document"]["id"]
        ids_ = []
        for i in range(32):
            ids_.append((await POST("cat", "/sessions", {"resume_id": cres, "jd_id": cjd, "client_key": f"cat-{i}"})).json()["session"]["id"])
        rules.SESSIONS_PER_DAY = old_spd
        async with db._Session() as s_:
            await s_.execute(sa_update(RiSession_).where(RiSession_.user_id == "u-cat", RiSession_.id > ids_[0]).values(status="finished"))
            await s_.commit()
        st_ = (await GET("cat", "/state")).json()
        check("the hub's active interview is found even when 30 newer (finished) ones fill the page", st_["active"] and st_["active"]["id"] == ids_[0] and all(x["id"] != ids_[0] for x in st_["sessions"]), st_["active"])
        check("has_more is true when an older page exists (32 sessions: 30 listed) and false for a learner with a few", st_["has_more"] is True and len(st_["sessions"]) == 30 and (await GET("dan", "/state")).json()["has_more"] is False)
        r = await GET("cat", f"/sessions?before={st_['sessions'][-1]['id']}&limit=30")
        check("...and the older page is reachable (the keyset cursor)", r.status_code == 200 and [x["id"] for x in r.json()["sessions"]] == [i for i in (ids_[1], ids_[0])] and r.json()["next_before"] is None, r.text[:200])

        # delete-all removes the memory notes about these interviews; the shared XP stays
        async with db._Session() as s_:
            xp_before = (await s_.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == "u-eve"))).scalar()
        r = await POST("eve", "/delete-all", {"confirm": True})
        async with db._Session() as s_:
            convs_after = (await s_.execute(select(func.count()).select_from(db.Conversation).where(db.Conversation.user_id == "u-eve", db.Conversation.mode == "resume_interview"))).scalar()
            xp_after = (await s_.execute(select(func.count()).select_from(db.SessionScore).where(db.SessionScore.user_id == "u-eve"))).scalar()
        check("delete-all also removes DuSu's one-line notes about the interviews; XP (shared with the other modes) stays", r.status_code == 200 and convs_after == 0 and xp_after == xp_before >= 1, (convs_after, xp_before, xp_after))

        # ------------------------------------------------------------------ detailed weaknesses, saved focus points, "did it work?"
        section("coach: weaknesses in detail, focus points saved, the next interview checks them, old reports are upgraded")
        _r1, _j1, sid_h1, th1 = await new_session("hal", start=True)
        await answer_n("hal", sid_h1, th1, 3, text=ANSWER_WEAK)
        r = await POST("hal", f"/sessions/{sid_h1}/finish")
        rep1 = r.json()["report"]
        check("a finished interview carries the coaching fields (v2): habits, ranked weaknesses, at most 3 focus points", r.status_code == 200 and rep1["v"] == 2 and rep1["weaknesses"] and 0 < len(rep1["focus"]) <= 3 and rep1["habits"]["n"] == 3, json.dumps(rep1)[:300])
        w0 = rep1["weaknesses"][0]
        check("each weakness explains itself: what was seen, why it matters, three steps, a drill, a goal, the questions it happened in", all(w["seen"] and w["why"] and len(w["how"]) == 3 and w["drill"] and w["goal"] and w["answers"] is not None for w in rep1["weaknesses"]) and w0["title"], w0)
        check("the FIRST interview has nothing to compare with (progress is null, not invented)", rep1["progress"] is None)
        gs = (await GET("hal", f"/sessions/{sid_h1}")).json()
        check("opening the finished interview later returns the same report + every answer with its full feedback (so nothing is lost)", gs["report"]["focus"] == rep1["focus"] and len([t for t in gs["turns"] if t["status"] == "answered" and t["feedback"] and t["answer"]]) == 3)
        st = (await GET("hal", "/state")).json()
        check("the hub's 'focus for next time' = the points of the latest finished interview", st["focus"] and st["focus"]["session_id"] == sid_h1 and st["focus"]["points"] == rep1["focus"] and st["focus"]["title"], st.get("focus"))
        _r2, _j2, sid_h2, th2 = await new_session("hal", start=True)
        g2 = (await GET("hal", f"/sessions/{sid_h2}")).json()
        check("an interview in progress is handed the previous interview's focus points (before the first question, and for the per-answer check)", g2["focus_prev"] and g2["focus_prev"]["session_id"] == sid_h1 and g2["focus_prev"]["points"] == rep1["focus"], g2.get("focus_prev"))
        check("... a finished interview does not carry focus_prev (its report holds the comparison)", "focus_prev" not in gs)
        await answer_n("hal", sid_h2, th2, 3, text=ANSWER_GOOD)
        r = await POST("hal", f"/sessions/{sid_h2}/finish")
        rep2 = r.json()["report"]
        pg = rep2["progress"]
        check("the NEXT interview's report judges each tracked focus point of the previous one, with real numbers", pg and pg["vs"]["session_id"] == sid_h1 and pg["items"] and all(i["status"] in ("improved", "same", "worse") and i["was"] and i["now"] for i in pg["items"]), json.dumps(pg)[:300])
        check("... strong answers after weak ones: at least one point improved and none got worse", pg["improved"] >= 1 and not any(i["status"] == "worse" for i in pg["items"]), [(i["key"], i["status"]) for i in pg["items"]])
        check("... and the comparison is saved with the interview (reopening shows the same)", (await GET("hal", f"/sessions/{sid_h2}")).json()["report"]["progress"] == pg)
        lines = await life_lines.resume_interview_lines("u-hal", "hal@example.com")
        check("DuSu's life line carries the improvement points (titles only)", lines and "improvement points" in lines[0] and "resume" not in lines[0].lower().split("improvement points")[-1], lines)

        # a report written BEFORE the coaching fields existed is upgraded the first time it is read (computed from the stored answers - no model call)
        async with db._Session() as s_:
            row = (await s_.execute(select(RiSession_).where(RiSession_.id == sid_h1))).scalars().first()
            old_rep = {k: v for k, v in row.report.items() if k not in ("v", "habits", "weaknesses", "focus", "progress")}
            await s_.execute(sa_update(RiSession_).where(RiSession_.id == sid_h1).values(report=old_rep))
            await s_.commit()
        STUB.n.clear()
        up = (await GET("hal", f"/sessions/{sid_h1}")).json()["report"]
        async with db._Session() as s_:
            saved = (await s_.execute(select(RiSession_.report).where(RiSession_.id == sid_h1))).scalar()
        check("an old-format report is upgraded on read: v2 fields appear, the v1 fields are untouched, no model call, and it is SAVED", up["v"] == 2 and up["weaknesses"] and up["overall"] == rep1["overall"] and up["per_question"] == rep1["per_question"] and saved["v"] == 2 and STUB.n["answer"] == 0, up.get("v"))
        check("... the upgrade is idempotent (same focus points, same weaknesses on the next read)", (await GET("hal", f"/sessions/{sid_h1}")).json()["report"]["focus"] == up["focus"] == rep1["focus"])
        async with db._Session() as s_:
            row = (await s_.execute(select(RiSession_).where(RiSession_.id == sid_h2))).scalars().first()
            await s_.execute(sa_update(RiSession_).where(RiSession_.id == sid_h2).values(report={k: v for k, v in row.report.items() if k not in ("v", "habits", "weaknesses", "focus", "progress")}))
            await s_.commit()
        st = (await GET("hal", "/state")).json()
        check("/state upgrades the latest old-format report too (the hub's focus card works for interviews finished before this feature)", st["focus"] and st["focus"]["session_id"] == sid_h2 and "v" not in (st["focus"] or {}), st.get("focus"))

        # ------------------------------------------------------------------ data rights + deletion
        section("export, delete, wipe, account deletion")
        ex = (await GET("ann", "/export")).json()
        check("export holds every table, text included, and NO audio column", all(t.__tablename__ in ex for t in RI_TABLES) and len(ex["ri_turns"]) >= 4 and "audio" not in ex["ri_turns"][0] and "audio_blob" not in ex["ri_turns"][0])
        r = await POST("ann", "/delete-all", {})
        check("delete-all needs confirm:true", r.status_code == 422)
        r = await c.delete(f"/rinterview/documents/{v2}", headers=H("ann"))
        st = (await GET("ann", f"/sessions/{sid}")).json()
        check("deleting a document detaches its sessions (the report stays) and removes its analyses", r.status_code == 200 and st["session"]["resume_id"] is None and st["analysis"] is None and st["report"] is not None)
        r = await c.delete(f"/rinterview/sessions/{sid2}", headers=H("ann"))
        check("deleting a session removes its turns", r.status_code == 200 and (await GET("ann", f"/sessions/{sid2}")).status_code == 404)
        # the secret never reaches an exception message
        from sqlalchemy.exc import IntegrityError
        from app.resume_interview.models import RiDocument
        leak = None
        try:
            async with db._Session() as s:
                for _ in (1, 2):
                    s.add(RiDocument(user_id="u-bob", kind="resume", title="t", text="SECRET-TEXT-VALUE-98765", text_sha="dup-sha", client_key=None))
                    await s.flush()
        except IntegrityError as e:
            leak = str(e)
        check("an IntegrityError's text carries no bound values (hide_parameters)", leak is not None and "SECRET-TEXT-VALUE-98765" not in leak and "[parameters" not in leak, (leak or "")[:300])
        n_before = {}
        async with db._Session() as s:
            for t in RI_TABLES:
                n_before[t.__tablename__] = (await s.execute(select(func.count()).select_from(t).where(t.user_id == "u-ann"))).scalar()
        check("Ann still has rows before deletion", sum(n_before.values()) > 0, n_before)
        r = await c.post("/account/delete", headers=H("ann"), json={"token": T["ann"], "confirm": "delete"})
        async with db._Session() as s:
            left = {t.__tablename__: (await s.execute(select(func.count()).select_from(t).where(t.user_id == "u-ann"))).scalar() for t in RI_TABLES}
        check("account deletion removes every ri_* row", r.status_code == 200 and sum(left.values()) == 0, (r.status_code, left))
        r = await c.post("/rinterview/documents/paste", headers=H("owner"), json={"kind": "resume", "text": "Owner resume. " + RESUME})
        check("the owner has a document to keep through the wipe", r.status_code == 200)
        async with db._Session() as s:
            before = {t.__tablename__: (await s.execute(select(func.count()).select_from(t).where(t.user_id.in_(["u-bob", "u-cat"])))).scalar() for t in RI_TABLES}
        await db.admin_wipe_users({"david123rana@gmail.com"})
        async with db._Session() as s:
            gone = {t.__tablename__: (await s.execute(select(func.count()).select_from(t).where(t.user_id.in_(["u-bob", "u-cat"])))).scalar() for t in RI_TABLES}
            kept = (await s.execute(select(func.count()).select_from(RiDocument).where(RiDocument.user_id == "u-owner"))).scalar()
        check("the owner's wipe removes the other learners' ri_* rows and keeps the owner's", sum(before.values()) > 0 and sum(gone.values()) == 0 and kept == 1, (before, gone, kept))

    # ---------------------------------------------------------------------- introspection
    section("introspection")
    covered = {"ri_turns", "ri_sessions", "ri_analyses", "ri_documents"}
    have_user = [t.name for t in db.Base.metadata.sorted_tables if "user_id" in t.c]
    delete_src = open("/app/app/db.py").read()
    missing = [t for t in covered if t not in {m.__tablename__ for m in RI_TABLES}]
    check("every ri_* table is in RI_TABLES (so export / delete-rows cover it)", not missing and {m.__tablename__ for m in RI_TABLES} == covered)
    from app.resume_interview import service as S
    delete_tbls = {m.__tablename__ for m in (S.RiTurn, S.RiSession, S.RiAnalysis, S.RiDocument)}
    check("delete_rows deletes every table that has a user_id", covered <= delete_tbls)
    check("db.delete_user and db.admin_wipe_users both call the Resume Interview hook", delete_src.count("_ri.delete_rows") == 2)
    enum_values = {"ri_documents": {"kind": rules.DOC_KINDS, "source": ("pdf", "docx", "txt", "paste")},
                   "ri_analyses": {"state": ("pending", "done", "failed"), "band": ("strong", "good", "fair", "weak", "unknown")},
                   "ri_sessions": {"status": ("draft", "matched", "active", "finished"), "plan_state": ("none", "pending", "done")},
                   "ri_turns": {"kind": rules.QKINDS + ("followup",), "source": ("plan", "followup", "bank"), "status": ("queued", "asked", "answered", "skipped", "dropped"),
                                "engine": ("groq", "gemini"), "feedback_state": ("none", "pending", "done", "failed")}}
    tooWide = []
    for tn, cols in enum_values.items():
        tbl = db.Base.metadata.tables[tn]
        for col, vals in cols.items():
            width = tbl.c[col].type.length
            tooWide += [(tn, col, v) for v in vals if len(v) > width]
    check("every enumerated value fits its column width", not tooWide, tooWide)
    other = [t for t in have_user if t not in covered]
    print(f"   (info) other tables with user_id: {len(other)} - not part of this feature")

    print(f"\n{N - len(FAILS)} / {N} checks passed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
        sys.exit(1)


asyncio.run(main())
