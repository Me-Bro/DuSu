"""Grammar Coach - tier 2: the real HTTP layer + the detached analysis task on a scratch Postgres, with a STUB model.

Run via tests/grammar/run.sh (throwaway postgres, never the app's `dusu-db-1`). The model is replaced by a stub that counts calls and records the
keyword arguments of every call (temperature, cool, max_tokens, first) - that is how "a grammar call never marks a provider cooldown" and "a duplicate
analysis = zero calls" are proven. Plain Python; non-zero exit on any failure."""

import asyncio
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/grammar")

import httpx                                                        # noqa: E402
from sqlalchemy import func, select, text as sa_text                # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.grammar import budget as B, service as svc, tracker        # noqa: E402
from app.grammar.models import GC_TABLES, GcDrill, GcMark, GcSentence, GcSession   # noqa: E402
from stub_llm import StubLLM                                        # noqa: E402

FAILS: list = []
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


STUB = StubLLM()
tracker.llm = STUB

TALK = ["yesterday i go to the market and i buy some vegetable", "i am engineer in a software company in pune",
        "we should discuss about the project tomorrow morning with the team", "my favourite food is dal and rice with some pickle",
        "he go to office every day by metro train", "informations about the new course were very useful for all of us"]


def turns_of(texts):
    return [{"turn": i + 1, "text": t, "conf": None} for i, t in enumerate(texts)]


async def count(model, uid, **where):
    async with db._Session() as s:
        q = select(func.count()).select_from(model).where(model.user_id == uid)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        n = (await s.execute(q)).scalar()
        await s.commit()
    return n


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys configured: run through run.sh"
    # OLD -> NEW rehearsal: production has every table EXCEPT gc_*; init_db() must add them next to existing data, twice in a row
    for _ in range(20):
        try:
            async with db._engine.begin() as conn:
                await conn.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if not t.name.startswith("gc_")]))
            break
        except Exception:
            await asyncio.sleep(1)
    await db.login({"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""})
    async with db._engine.connect() as conn:
        pre = {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'gc\\_%'"))).all()}
    check("rehearsal: the old schema has no gc_* tables", pre == set(), pre)
    await db.init_db()
    await db.init_db()
    async with db._engine.connect() as conn:
        post = {r[0] for r in (await conn.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'gc\\_%'"))).all()}
        idx = {r[0] for r in (await conn.execute(sa_text("select indexname from pg_indexes where tablename like 'gc\\_%'"))).all()}
        old_user = (await conn.execute(sa_text("select count(*) from users where id='u-old'"))).scalar()
    check("rehearsal: init_db() adds exactly the four gc_* tables next to the existing data, twice in a row", post == {"gc_sessions", "gc_sentences", "gc_marks", "gc_drills"} and old_user == 1, (post, old_user))
    check("rehearsal: the idempotency index exists", "uq_gc_session_client" in idx, idx)

    people = {k: {"sub": f"u-{k}", "email": f"{k}@example.com", "name": k.title(), "picture": ""} for k in ("owner", "ann", "bob", "cat", "dan")}
    people["owner"]["email"] = "david123rana@gmail.com"
    for u in people.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
    T = {k: auth.make_session(u) for k, u in people.items()}
    uid = {k: u["sub"] for k, u in people.items()}
    em = {k: u["email"] for k, u in people.items()}
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        H = lambda who: {"Authorization": "Bearer " + T[who]}                                   # noqa: E731
        GET = lambda who, p, **kw: c.get("/gcoach" + p, headers=H(who), **kw)                   # noqa: E731
        POST = lambda who, p, body=None: c.post("/gcoach" + p, headers=H(who), json=body if body is not None else {})   # noqa: E731

        # ------------------------------------------------------------------ switch and gates
        section("switch off / auth / gates")
        await db.set_setting("grammar_coach", "off")
        M.invalidate_access_cache()
        r = await GET("ann", "/state")
        check("switch OFF: state is 404", r.status_code == 404)
        r = await GET("ann", "/export")
        check("switch OFF: export still works", r.status_code == 200 and "sessions" in r.json())
        r = await POST("ann", "/delete-all", {"confirm": True})
        check("switch OFF: delete-all still works", r.status_code == 200)
        r = await POST("ann", "/delete-all", {})
        check("delete-all needs confirm:true", r.status_code == 422)
        check("no token -> 401", (await c.get("/gcoach/state")).status_code == 401)
        check("junk token -> 401", (await c.get("/gcoach/state", headers={"Authorization": "Bearer junk.token"})).status_code == 401)
        me = (await c.get("/me", headers=H("owner"))).json()
        check("/me carries grammar_coach=False while off", me.get("grammar_coach") is False)
        await db.set_setting("grammar_coach", "owner")
        M.invalidate_access_cache()
        check("switch OWNER: a normal learner is 404", (await GET("ann", "/state")).status_code == 404)
        check("switch OWNER: the owner is in", (await GET("owner", "/state")).status_code == 200)
        await db.early_add(em["bob"])
        M.invalidate_access_cache()
        check("switch OWNER: an early-access tester is in", (await GET("bob", "/state")).status_code == 200)
        check("the tester has no admin rights", (await c.get("/admin/overview", headers=H("bob"))).status_code == 403)
        await db.early_remove(em["bob"])
        await db.set_setting("grammar_coach", "on")
        M.invalidate_access_cache()
        check("switch ON: everyone is in", (await GET("ann", "/state")).status_code == 200)
        ov = (await c.get("/admin/overview", headers=H("owner"))).json()
        check("/admin/overview reports the switch and a health block", ov.get("grammar_coach") == "on" and isinstance(ov.get("grammar_coach_health"), dict), ov.get("grammar_coach_health"))
        r = await c.post("/admin/settings", headers=H("owner"), json={"grammar_coach": "owner"})
        check("/admin/settings flips it", r.status_code == 200 and r.json()["grammar_coach"] == "owner")
        await c.post("/admin/settings", headers=H("owner"), json={"grammar_coach": "on"})
        await c.post("/admin/settings", headers=H("owner"), json={"level_test": True})
        check("/admin/settings with the field absent leaves it alone", (await c.get("/admin/overview", headers=H("owner"))).json()["grammar_coach"] == "on")
        await db.set_user_status(uid["bob"], "blocked")
        check("a blocked account is 403", (await GET("bob", "/state")).status_code == 403)
        check("a blocked account can still export its data", (await GET("bob", "/export")).status_code == 200)
        await db.set_user_status(uid["bob"], "active")
        M.invalidate_access_cache()

        # ------------------------------------------------------------------ one analysis, before the learner's choice
        section("the detached analysis (stub model)")
        STUB.reset()
        out = await tracker.run(uid["ann"], em["ann"], source="talk", kind="", key="ws:annsession01", turns=turns_of(TALK), engine_src="chrome", duration_sec=240)
        check("a session of 6 English sentences = ONE model call", out is not None and STUB.calls["total"] == 1, (out, dict(STUB.calls)))
        kw = STUB.seen_kwargs[0]
        check("the call is low-temperature, cool=False, 1500 tokens, default order", kw["temperature"] == 0.1 and kw["cool"] is False and kw["max_tokens"] == 1500 and kw["first"] is None, kw)
        check("learner text is fenced as DATA in the prompt", "<<<DATA" in STUB.seen_payloads[0] and "<<<END" in STUB.seen_payloads[0])
        sid = out["id"]
        async with db._Session() as s:
            row = (await s.get(GcSession, sid))
            await s.commit()
        check("a session row exists, scoped to the learner, state done", row is not None and row.user_id == uid["ann"] and row.state in ("done", "partial") and row.client_key == "ws:annsession01", row and row.state)
        check("checked sentences are counted (5 of 6: two soft findings stay unsure) and per-100 is WITHHELD below 6 checked sentences", row.checked == 5 and row.per100 is None and row.marks_error >= 3, (row.checked, row.per100, row.marks_error))
        check("before the choice NO sentence text is stored", await count(GcSentence, uid["ann"]) == 0)
        marks = await count(GcMark, uid["ann"])
        check("...but the marks are stored as counts (rule + date, no text)", marks >= 4, marks)
        async with db._Session() as s:
            texts = (await s.execute(select(GcMark.quote, GcMark.fix, GcMark.why).where(GcMark.user_id == uid["ann"]))).all()
            await s.commit()
        check("mark rows carry no quote / fix / why before the choice", all(q == "" and f == "" and w == "" for q, f, w in texts), texts[:2])
        r = await GET("ann", f"/sessions/{sid}")
        rep = r.json()
        check("the report is served from memory (held) with the sentences to fix", r.status_code == 200 and rep["text"] == "held" and len(rep["sentences_list"]) >= 4 and rep["choice_needed"] is True, rep.get("text"))
        s0 = rep["sentences_list"][0]
        check("a corrected sentence is built by code from SURE marks only (vegetables yes; the soft go -> went is not applied)", "vegetables" in s0["fixed"] and " go " in s0["fixed"], s0)
        check("the held sentences cannot be contested yet (no row)", s0["id"] is None)
        r = await GET("ann", "/by-ref?ref=ws:annsession01")
        check("by-ref finds the finished session", r.json()["state"] in ("done", "partial") and r.json()["report"]["id"] == sid)
        STUB.reset()
        again = await tracker.run(uid["ann"], em["ann"], source="talk", kind="", key="ws:annsession01", turns=turns_of(TALK), engine_src="chrome")
        check("the same key again = zero model calls and the same session", STUB.calls["total"] == 0 and again["id"] == sid, (dict(STUB.calls), again))
        check("by-ref with a malformed ref is 422", (await GET("ann", "/by-ref?ref=bad")).status_code == 422)

        # ------------------------------------------------------------------ the learner's choice
        section("the one-time choice")
        r = await POST("ann", "/keep", {"id": sid, "choice": "keep"})
        check("keep -> 200", r.status_code == 200 and r.json()["choice"] == "keep", r.text)
        n_sent = await count(GcSentence, uid["ann"])
        check("keep writes the held sentences (only the ones with mistakes)", 4 <= n_sent <= 6, n_sent)
        async with db._Session() as s:
            m = (await s.execute(select(GcMark).where(GcMark.user_id == uid["ann"], GcMark.sentence_id.is_not(None)).limit(3))).scalars().all()
            await s.commit()
        check("marks now carry their words, linked to a sentence row", m and all(x.quote and x.fix for x in m), [(x.quote, x.fix) for x in m])
        rep = (await GET("ann", f"/sessions/{sid}")).json()
        check("the report is now served from the database", rep["text"] == "saved" and rep["choice_needed"] is False)
        sentence_id = rep["sentences_list"][0]["id"]
        check("a saved sentence has an id", sentence_id is not None)
        r = await POST("ann", f"/sentences/{sentence_id}/contest", {"kind": "is_correct"})
        check("contest 'That's correct English' -> 200", r.status_code == 200)
        rep2 = (await GET("ann", f"/sessions/{sid}")).json()
        check("a contested sentence stops counting (marks fall)", rep2["marks"] < rep["marks"], (rep["marks"], rep2["marks"]))
        r = await POST("ann", f"/sentences/{sentence_id}/contest", {"kind": "bogus"})
        check("contest with a bad kind is 422", r.status_code == 422)
        r = await POST("bob", f"/sentences/{sentence_id}/contest", {"kind": "not_said"})
        check("IDOR: another learner cannot contest it (404)", r.status_code == 404)

        # ------------------------------------------------------------------ isolation
        section("two-learner isolation (every probe is a 404, never a 403)")
        probes = [("GET", f"/sessions/{sid}"), ("DELETE", f"/sessions/{sid}"), ("POST", f"/sentences/{sentence_id}/contest"), ("POST", "/keep")]
        bad = []
        for meth, path in probes:
            body = {"id": sid, "choice": "keep", "kind": "not_said"}
            r = await c.request(meth, "/gcoach" + path, headers=H("bob"), json=body if meth in ("POST", "DELETE") else None)
            if r.status_code != 404:
                bad.append((meth, path, r.status_code))
        check("bob cannot read, delete, contest or choose for ann's session", not bad, bad)
        check("bob's by-ref of ann's key is 'none'", (await GET("bob", "/by-ref?ref=ws:annsession01")).json()["state"] == "none")
        check("bob's notebook is empty", (await GET("bob", "/notebook")).json()["sentences"] == [])
        for p in ("/sessions/0", "/sessions/99999999999", "/sessions/-1", "/rules/zzz", "/rules/..%2F..", "/sessions/abc"):
            r = await GET("ann", p)
            check(f"odd id {p} is a 404 / 422, never a 500", r.status_code in (404, 422), r.status_code)

        # ------------------------------------------------------------------ Hindi, outages, the cooldown rule
        section("Hindi / outage / cooldown rules")
        STUB.reset()
        out = await tracker.run(uid["bob"], em["bob"], source="talk", kind="", key="ws:bobhindi0001", turns=turns_of(["mera naam rahul hai aur main delhi se hoon", "मेरा नाम राहुल है और मैं दिल्ली से हूँ"]), engine_src="chrome")
        check("a Hindi / Hinglish session creates NO row and makes NO call", out is None and STUB.calls["total"] == 0 and await count(GcSession, uid["bob"]) == 0, (out, dict(STUB.calls)))
        STUB.reset()
        STUB.fail = RuntimeError("Error code: 429 - rate limit")
        out = await tracker.run(uid["bob"], em["bob"], source="talk", kind="", key="ws:bobdown00001", turns=turns_of(["he go to office every day by metro train", "i am happy to be here today with you all"]), engine_src="chrome")
        check("an AI outage never raises, is never retried (1 call) and degrades to rule checks", out is not None and STUB.calls["total"] == 1, (out, dict(STUB.calls)))
        async with db._Session() as s:
            bd = (await s.get(GcSession, out["id"]))
            await s.commit()
        check("the outage session is 'partial' and nothing is called correct without a verdict", bd.state == "partial" and bd.clean == 0, (bd.state, bd.clean))
        STUB.reset()
        orig = B.cooling
        B.cooling = lambda: ["groq"]
        try:
            out = await tracker.run(uid["bob"], em["bob"], source="talk", kind="", key="ws:bobcool00001", turns=turns_of(TALK), engine_src="chrome")
        finally:
            B.cooling = orig
        check("while ANY provider is cooling no grammar call is made (the chat comes first)", STUB.calls["total"] == 0 and out is not None, dict(STUB.calls))
        STUB.reset()

        # ------------------------------------------------------------------ counts only, delete cascades
        section("counts only, deletes")
        out = await tracker.run(uid["cat"], em["cat"], source="talk", kind="", key="ws:catsession001", turns=turns_of(TALK), engine_src="chrome")
        await POST("cat", "/keep", {"id": out["id"], "choice": "keep"})
        before = await count(GcSentence, uid["cat"])
        r = await POST("cat", "/prefs", {"choice": "counts"})
        check("choosing 'counts only' deletes the stored sentences and blanks the mark text", r.status_code == 200 and await count(GcSentence, uid["cat"]) == 0 < before and await count(GcMark, uid["cat"]) > 0)
        async with db._Session() as s:
            blank = (await s.execute(select(func.count()).select_from(GcMark).where(GcMark.user_id == uid["cat"], GcMark.quote != ""))).scalar()
            await s.commit()
        check("...every mark's text is gone", blank == 0, blank)
        out2 = await tracker.run(uid["cat"], em["cat"], source="talk", kind="", key="ws:catsession002", turns=turns_of(TALK), engine_src="chrome")
        check("with 'counts only' set, a new session stores counts and NO sentence text", await count(GcSentence, uid["cat"]) == 0 and out2["state"] in ("done", "partial"))
        a_id = await db.save_practice_attempt(uid["cat"], {"kind": "presentation", "lang": "en", "feedback_lang": "hinglish", "level": "intermediate", "overall": 60, "scores": {}, "report": {}})
        await tracker.run(uid["cat"], em["cat"], source="practice", kind="presentation", key=f"pa:{a_id['id']}", turns=turns_of(TALK), engine_src="whisper")
        n_before = await count(GcSession, uid["cat"], client_key=f"pa:{a_id['id']}")
        await db.delete_practice_attempt(uid["cat"], a_id["id"])
        check("deleting a Practice attempt deletes its Grammar Coach session", n_before == 1 and await count(GcSession, uid["cat"], client_key=f"pa:{a_id['id']}") == 0)
        r = await POST("cat", "/delete-all", {"confirm": True})
        check("delete-all empties every gc_* table for the learner", r.status_code == 200 and all([await count(M_, uid["cat"]) == 0 for M_ in (GcSession, GcSentence, GcMark, GcDrill)]))
        # a Practice attempt that is PRUNED (oldest beyond the keep limit) takes its Grammar Coach session with it
        keep0, db._PRACTICE_KEEP = db._PRACTICE_KEEP, 1
        try:
            pa1 = await db.save_practice_attempt(uid["cat"], {"kind": "presentation", "lang": "en", "feedback_lang": "hinglish", "level": "intermediate", "overall": 60, "scores": {}, "report": {}})
            await tracker.run(uid["cat"], em["cat"], source="practice", kind="presentation", key=f"pa:{pa1['id']}", turns=turns_of(TALK), engine_src="whisper")
            assert await count(GcSession, uid["cat"], client_key=f"pa:{pa1['id']}") == 1
            await db.save_practice_attempt(uid["cat"], {"kind": "presentation", "lang": "en", "feedback_lang": "hinglish", "level": "intermediate", "overall": 61, "scores": {}, "report": {}})
        finally:
            db._PRACTICE_KEEP = keep0
        check("a PRUNED Practice attempt deletes its Grammar Coach session too", await count(GcSession, uid["cat"], client_key=f"pa:{pa1['id']}") == 0)
        # deleting a Job Interview Practice interview deletes its Grammar Coach session
        from app.resume_interview import service as ri_svc
        from app.resume_interview.models import RiSession
        async with db._Session() as s_:
            ris = RiSession(user_id=uid["cat"], status="finished", client_key="gc-test-ri")
            s_.add(ris); await s_.commit(); ri_id = ris.id
        await tracker.run(uid["cat"], em["cat"], source="job_interview", kind="", key=f"ri:{ri_id}", turns=turns_of(TALK), engine_src="whisper")
        had = await count(GcSession, uid["cat"], client_key=f"ri:{ri_id}")
        await ri_svc.delete_session(uid["cat"], ri_id)
        check("deleting an interview deletes its Grammar Coach session", had == 1 and await count(GcSession, uid["cat"], client_key=f"ri:{ri_id}") == 0, had)
        out3 = await tracker.run(uid["dan"], em["dan"], source="talk", kind="", key="ws:dansession001", turns=turns_of(TALK), engine_src="chrome")
        await POST("dan", "/keep", {"id": out3["id"], "choice": "keep"})
        await db.delete_user(uid["dan"])
        async with db._Session() as s:
            left = [(await s.execute(select(func.count()).select_from(M_).where(M_.user_id == uid["dan"]))).scalar() for M_ in (GcSession, GcSentence, GcMark, GcDrill)]
            await s.commit()
        check("db.delete_user removes every gc_* row (FK-safe)", left == [0, 0, 0, 0], left)

        # ------------------------------------------------------------------ drills, prefs, hub, rules, analyze endpoint
        section("drills / prefs / hub / rules / analyze")
        r = await GET("ann", "/drills/next?n=5")
        items = r.json()["items"]
        check("drills are built from the learner's own sentences + the catalogue (5 items, pick and say)", r.status_code == 200 and len(items) == 5 and {i["kind"] for i in items} <= {"pick", "say"}, [i["kind"] for i in items])
        pick = next(i for i in items if i["kind"] == "pick")
        check("a pick item has one correct option inside range", 0 <= pick["answer"] < len(pick["options"]) and len(pick["options"]) >= 2)
        res = {"key": "drillbatch0001", "results": [{"rule": pick["rule"], "ok": True}, {"rule": pick["rule"], "ok": False}]}
        r1 = await POST("ann", "/drills/result", res)
        r2 = await POST("ann", "/drills/result", res)
        async with db._Session() as s:
            d = (await s.execute(select(GcDrill).where(GcDrill.user_id == uid["ann"], GcDrill.rule == pick["rule"].split("#")[0]))).scalars().first()
            await s.commit()
        check("a drill result batch is replay-safe (applied once)", r1.status_code == 200 and r2.status_code == 200 and d is not None and d.right == 1 and d.wrong == 1, d and (d.right, d.wrong))
        check("a drill batch with a bad key is 422", (await POST("ann", "/drills/result", {"key": "", "results": []})).status_code == 422)
        r = await POST("ann", "/prefs", {"feedback_lang": "en", "strict": "gentle", "natural_tips": False, "choice": "nonsense", "evil": "x"})
        p = r.json()
        check("prefs: valid values stick, junk is ignored", p["feedback_lang"] == "en" and p["strict"] == "gentle" and p["natural_tips"] is False and p["choice"] == "keep" and "evil" not in p, p)
        hub = (await GET("ann", "/state")).json()
        check("the hub carries the window, the mistakes by rule and no delta with one session", hub["has_data"] and hub["window"]["checked"] == 5 and hub["delta"] is None and isinstance(hub["mistakes"], list), {k: hub[k] for k in ("window", "delta")})
        check("per100 is withheld with 5 checked sentences (minimum evidence is 6 sentences and 40 words)", hub["window"]["per100"] is None and hub["window"]["words_checked"] >= 40)
        rl = (await GET("ann", "/rules")).json()
        check("the rules index has all 41 rules and the flow tips", len(rl["rules"]) == 41 and len(rl["flow_tips"]) == 6 and "Tense" in rl["groups"], len(rl["rules"]))
        rd = (await GET("ann", "/rules/ag.he_dont")).json()
        check("a rule page carries the lesson, the status and the learner's own sentences", rd["content"]["en"]["rule"] and rd["state"] and isinstance(rd["sentences"], list))
        check("an unknown rule is 404", (await GET("ann", "/rules/nope.nope")).status_code == 404)
        # analyze: recorded Practice
        at = await db.save_practice_attempt(uid["ann"], {"kind": "presentation", "lang": "en", "feedback_lang": "hinglish", "level": "intermediate", "overall": 60, "scores": {}, "report": {}, "actual_sec": 120})
        STUB.reset()
        r = await POST("ann", "/analyze", {"source": "practice", "ref": f"pa:{at['id']}", "transcript": " ".join(TALK) + ".", "keys": {"gemini": "stub-key"}})
        check("analyze (recorded Practice) answers pending", r.status_code == 200 and r.json().get("pending") is True, r.text)
        await tracker.drain()
        r = await GET("ann", f"/by-ref?ref=pa:{at['id']}")
        check("...and the detached task finishes it", r.json()["state"] in ("done", "partial") and STUB.calls["total"] >= 1, r.text[:200])
        r = await POST("ann", "/analyze", {"source": "practice", "ref": f"pa:{at['id']}", "transcript": "x " * 50, "keys": {"gemini": "stub-key"}})
        check("analyze again = idempotent (no second run)", r.json().get("state") in ("done", "partial"), r.text[:200])
        hi_at = await db.save_practice_attempt(uid["ann"], {"kind": "presentation", "lang": "hi", "feedback_lang": "hinglish", "level": "intermediate", "overall": 60, "scores": {}, "report": {}})
        r = await POST("ann", "/analyze", {"source": "practice", "ref": f"pa:{hi_at['id']}", "transcript": " ".join(TALK), "keys": {"gemini": "stub-key"}})
        check("analyze refuses a Hindi attempt (the server decides the language)", r.status_code == 422, r.text)
        r = await POST("bob", "/analyze", {"source": "practice", "ref": f"pa:{at['id']}", "transcript": " ".join(TALK), "keys": {"gemini": "stub-key"}})
        check("analyze on someone else's attempt is 404", r.status_code == 404, r.status_code)
        # Job Interview Practice: the stored answers are analysed on demand (claim pattern); a foreign interview is 404; no answers is 422
        from app.resume_interview.models import RiSession as _RS, RiTurn as _RT
        async with db._Session() as s_:
            rs = _RS(user_id=uid["ann"], status="finished", client_key="gc-test-ri-ann"); s_.add(rs); await s_.commit(); ann_ri = rs.id
            rs2 = _RS(user_id=uid["ann"], status="finished", client_key="gc-test-ri-empty"); s_.add(rs2); await s_.commit(); ann_ri_empty = rs2.id
            for i_, t_ in enumerate(TALK[:4]):
                s_.add(_RT(session_id=ann_ri, user_id=uid["ann"], idx=i_ + 1, status="answered", answer=t_, engine="groq"))
            await s_.commit()
        r = await POST("ann", "/analyze", {"source": "job_interview", "ref": f"ri:{ann_ri}", "keys": {"gemini": "stub-key"}})
        check("analyze (Job Interview Practice) answers pending", r.status_code == 200 and r.json().get("pending") is True, r.text)
        await tracker.drain(30)
        r = await GET("ann", f"/by-ref?ref=ri:{ann_ri}")
        check("...the stored answers are analysed (source job_interview)", r.status_code == 200 and r.json()["state"] in ("done", "partial") and r.json()["report"]["source"] == "job_interview", r.text[:200])
        n_calls = STUB.calls["total"]
        r = await POST("ann", "/analyze", {"source": "job_interview", "ref": f"ri:{ann_ri}", "keys": {"gemini": "stub-key"}})
        check("analyze (Job Interview Practice) again = idempotent, zero model calls", r.status_code == 200 and STUB.calls["total"] == n_calls, r.text[:120])
        r = await POST("bob", "/analyze", {"source": "job_interview", "ref": f"ri:{ann_ri}", "keys": {"gemini": "stub-key"}})
        check("analyze on someone else's interview is 404", r.status_code == 404, r.status_code)
        r = await POST("ann", "/analyze", {"source": "job_interview", "ref": f"ri:{ann_ri_empty}", "keys": {"gemini": "stub-key"}})
        check("an interview with no answers is 422 too_short", r.status_code == 422, r.status_code)
        r = await POST("ann", "/analyze", {"source": "practice", "ref": "pa:1", "transcript": "x"})
        check("analyze without keys is 402 (BYOK gate)", r.status_code in (402, 422), r.status_code)

        # ------------------------------------------------------------------ introspection
        section("introspection")
        used = {"state": ("pending", "done", "partial", "failed"), "source": ("talk", "interview", "practice", "job_interview"), "contest": ("none", "not_said", "is_correct"),
                "conf": ("sure", "likely"), "src": ("model", "rule", "both"), "status": ("fix", "natural", "unsure"), "severity": ("error", "natural", "polish")}
        widths = {}
        for T_ in GC_TABLES:
            for col in T_.__table__.columns:
                ln = getattr(col.type, "length", None)
                if ln and col.name in used:
                    widths[(T_.__tablename__, col.name)] = ln
        check("every enumerated value fits its column", all(len(v) <= w for (tb, cn), w in widths.items() for v in used[cn]), widths)
        mod_src = open("/app/app/db.py").read()
        check("both account-delete paths call the Grammar Coach hook", mod_src.count("_gc.delete_rows") == 2 and "delete_by_ref" in mod_src)
        check("every gc_* table has a user_id column (so the delete hook covers it)", all("user_id" in [c.name for c in T_.__table__.columns] for T_ in GC_TABLES))
    print(f"\ngrammar selftest: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
