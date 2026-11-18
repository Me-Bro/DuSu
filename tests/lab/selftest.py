"""Grammar Lab - the real HTTP layer on a scratch MongoDB (run via tests/lab/run.sh; never the app's own database). No model is involved: the Lab makes no AI call."""
import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/lab")

import httpx                                                        # noqa: E402
from app import auth, db, main as M, store                          # noqa: E402
from app.store import func, select                                  # noqa: E402
from app.lab import bank, catalog, service as svc                   # noqa: E402
from app.lab.models import GL_TABLES, GlAttempt, GlProgress, GlReview, GlSet   # noqa: E402
import _mut                                                         # noqa: E402

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


async def count(model, uid=None, **where):
    async with db._Session() as s:
        q = select(func.count()).select_from(model)
        if uid is not None:
            q = q.where(model.user_id == uid)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        n = (await s.execute(q)).scalar()
        await s.commit()
    return n


async def none_left(uid_):
    return all([await count(M_, uid_) == 0 for M_ in (GlSet, GlProgress, GlAttempt, GlReview)])


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys configured: run through run.sh"
    items = svc.items()
    check("the bank is loaded (576 items, 12 units x 4 levels x 12)", len(items) == 576, len(items))
    UNIT, LEVEL = "present_simple", "easy"
    pool = [i for i in items.values() if i.unit == UNIT and i.level == LEVEL]

    # OLD -> NEW rehearsal: production has every collection EXCEPT gl_*; init_db() must add them next to existing data, twice in a row
    await store.init([m for m in db.Base.models() if not m.__tablename__.startswith("gl_")])
    dbh = store.core.database()
    await db.login({"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""})
    check("rehearsal: the old database has no gl_* collections", not {n for n in await dbh.list_collection_names() if n.startswith("gl_")})
    await db.init_db()
    await db.init_db()
    post = {n for n in await dbh.list_collection_names() if n.startswith("gl_")}
    check("rehearsal: init_db() adds exactly the four gl_* collections next to the existing data, twice in a row", post == {"gl_sets", "gl_progress", "gl_attempts", "gl_review"} and await dbh["users"].count_documents({"_id": "u-old"}) == 1, post)

    people = {k: {"sub": f"u-{k}", "email": f"{k}@example.com", "name": k.title(), "picture": ""} for k in ("owner", "ann", "bob", "cat", "dan", "eve")}
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
        GET = lambda who, p, **kw: c.get("/lab" + p, headers=H(who), **kw)                      # noqa: E731
        POST = lambda who, p, body=None: c.post("/lab" + p, headers=H(who), json=body if body is not None else {})   # noqa: E731

        async def new_set(who, unit=UNIT, level=LEVEL):
            r = await POST(who, "/set", {"unit": unit, "level": level})
            return r, (r.json() if r.status_code == 200 else {})

        async def answer(who, sid, iid, said):
            return await POST(who, "/check", {"set": sid, "item": iid, "said": said})

        def right_answer(iid):
            return items[iid].en[0]

        def wrong_answer(iid):
            it = items[iid]
            from app.lab import checker
            for kind, w in _mut.wrongs(it.en[0], 30):
                if checker.check(w, bank.variants(it.en), it.unit)["verdict"] == "wrong":
                    return w
            raise AssertionError("no wrong version for " + iid)

        # ------------------------------------------------------------------ switch and gates
        section("switch off / auth / gates")
        await db.set_setting("grammar_lab", "off")
        M.invalidate_access_cache()
        check("switch OFF: state is 404", (await GET("ann", "/state")).status_code == 404)
        check("switch OFF: starting a set is 404", (await POST("ann", "/set", {"unit": UNIT, "level": LEVEL})).status_code == 404)
        check("switch OFF: export still works", (await GET("ann", "/export")).status_code == 200)
        check("switch OFF: delete-all still works", (await POST("ann", "/delete-all", {"confirm": True})).status_code == 200)
        check("delete-all needs confirm:true", (await POST("ann", "/delete-all", {})).status_code == 422)
        check("no token -> 401", (await c.get("/lab/state")).status_code == 401)
        check("junk token -> 401", (await c.get("/lab/state", headers={"Authorization": "Bearer junk.token"})).status_code == 401)
        me = (await c.get("/me", headers=H("owner"))).json()
        check("/me carries grammar_lab=False while off", me.get("grammar_lab") is False)
        await db.set_setting("grammar_lab", "owner")
        M.invalidate_access_cache()
        check("switch OWNER: a normal learner is 404", (await GET("ann", "/state")).status_code == 404)
        check("switch OWNER: the owner is in and /me says so", (await GET("owner", "/state")).status_code == 200 and (await c.get("/me", headers=H("owner"))).json().get("grammar_lab") is True)
        await db.early_add(em["bob"])
        M.invalidate_access_cache()
        check("switch OWNER: an early-access tester is in", (await GET("bob", "/state")).status_code == 200)
        check("the tester has no admin rights", (await c.get("/admin/overview", headers=H("bob"))).status_code == 403)
        await db.early_remove(em["bob"])
        await db.set_setting("grammar_lab", "on")
        M.invalidate_access_cache()
        check("switch ON: everyone is in", (await GET("ann", "/state")).status_code == 200)
        ov = (await c.get("/admin/overview", headers=H("owner"))).json()
        check("/admin/overview reports the switch and a health block", ov.get("grammar_lab") == "on" and isinstance(ov.get("grammar_lab_health"), dict) and ov["grammar_lab_health"].get("items") == 576, ov.get("grammar_lab_health"))
        r = await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "owner"})
        check("/admin/settings flips it", r.status_code == 200 and r.json()["grammar_lab"] == "owner")
        await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "on"})
        await c.post("/admin/settings", headers=H("owner"), json={"level_test": True})
        check("/admin/settings with the field absent leaves it alone", (await c.get("/admin/overview", headers=H("owner"))).json()["grammar_lab"] == "on")
        r = await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "banana"})
        check("a bad switch value falls back to off", r.json()["grammar_lab"] == "off")
        await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "on"})
        await db.set_user_status(uid["bob"], "blocked")
        check("a blocked account is 403", (await GET("bob", "/state")).status_code == 403)
        check("a blocked account can still export its data", (await GET("bob", "/export")).status_code == 200)
        await db.set_user_status(uid["bob"], "active")
        M.invalidate_access_cache()

        # ------------------------------------------------------------------ the hub
        section("state")
        st = (await GET("ann", "/state")).json()
        check("12 units x 4 levels, 12 items each", len(st["units"]) == 12 and all(l["items"] == 12 for u in st["units"] for l in u["levels"].values()), st["units"][0])
        check("the catalogue rides along (names, formulas, Hindi ending, example)", set(st["catalog"]["order"]) == set(catalog.UNITS) and st["catalog"]["units"]["present_simple"]["formula"]["aff"] and st["catalog"]["reviewed"] is False)
        check("a new learner: 0 stars, nothing to review, no open set", st["stars"] == 0 and st["review_due"] == 0 and st["open_set"] is None and st["stars_max"] == 144)

        # ------------------------------------------------------------------ a set
        section("a set")
        r, S1 = await new_set("ann")
        check("a set of 10 is served", r.status_code == 200 and S1["total"] == 10 and len(S1["items"]) == 10 and S1["answered"] == 0, r.text[:200])
        blob = json.dumps(S1, ensure_ascii=False)
        check("the payload has the Hindi sentence and NO English answer", all("hi" in i and "en" not in i for i in S1["items"]) and not any(a in blob for it in pool for a in it.en), blob[:200])
        check("every item belongs to the asked unit and level", all(items[i["id"]].unit == UNIT and items[i["id"]].level == LEVEL for i in S1["items"]))
        r2, S1b = await new_set("ann")
        check("asking again resumes the SAME open set", S1b["set"] == S1["set"])
        check("state shows the open set", (await GET("ann", "/state")).json()["open_set"]["id"] == S1["set"])
        check("a bad unit is 422", (await POST("ann", "/set", {"unit": "nope", "level": "easy"})).status_code == 422)
        check("a bad level is 422", (await POST("ann", "/set", {"unit": UNIT, "level": "nope"})).status_code == 422)
        check("junk body is 422", (await c.post("/lab/set", headers=H("ann"), content=b"{not json")).status_code == 422)
        check("an oversize body is 413", (await c.post("/lab/check", headers=H("ann"), content=b"x" * 30000)).status_code == 413)
        check("GET /lab/set/{id} returns the same items", (await GET("ann", f"/set/{S1['set']}")).json()["items"] == S1["items"])
        check("a set id of someone else is a 404", (await GET("cat", f"/set/{S1['set']}")).status_code == 404)

        # ------------------------------------------------------------------ answering
        section("answering: tries, reveals, repeats")
        ids = [i["id"] for i in S1["items"]]
        a = ids[0]
        r = await answer("ann", S1["set"], a, "")
        check("an empty answer is not an attempt", r.json()["verdict"] == "empty" and r.json()["tries"] == 0 and not r.json()["done"])
        r = await answer("ann", S1["set"], a, "वह क्रिकेट खेलता है")
        check("a Hindi answer is not an attempt either", r.json()["verdict"] == "lang" and r.json()["tries"] == 0)
        w = wrong_answer(a)
        r1 = (await answer("ann", S1["set"], a, w)).json()
        check("first wrong: the rule is shown, the exact change is NOT, the answer is NOT", r1["verdict"] == "wrong" and r1["tries"] == 1 and r1["left"] == 2 and not r1["done"] and r1["explain"]["hi"]["rules"] and not r1["explain"]["hi"]["changes"] and "target" not in r1, r1)
        r2_ = (await answer("ann", S1["set"], a, w)).json()
        check("second wrong: the exact change appears, the answer still does not", r2_["tries"] == 2 and r2_["explain"]["en"]["changes"] and "target" not in r2_ and not r2_["done"], r2_)
        r3 = (await answer("ann", S1["set"], a, w)).json()
        check("third wrong: finished, the answer is revealed with the other phrasings", r3["done"] and r3["verdict"] == "wrong" and r3["target"] == items[a].en[0] and r3["also"] == list(items[a].en[1:]), r3)
        check("a finished item answered again returns the stored outcome (never graded twice)", (await answer("ann", S1["set"], a, right_answer(a))).json().get("repeat") is True)
        check("exactly one attempt row for the item, verdict wrong, 3 tries, the error code kept", await count(GlAttempt, uid["ann"], item_id=a) == 1)
        async with db._Session() as s:
            row = (await s.execute(select(GlAttempt).where(GlAttempt.user_id == uid["ann"], GlAttempt.item_id == a))).scalars().first()
            await s.commit()
        check("the attempt row says wrong / 3 / a code and holds no text", row.verdict == "wrong" and row.tries == 3 and row.codes and all(isinstance(x, str) and len(x) < 40 for x in row.codes), (row.verdict, row.tries, row.codes))
        check("the missed item is now in the learner's review list", await count(GlReview, uid["ann"], item_id=a) == 1)
        b = ids[1]
        r = (await answer("ann", S1["set"], b, right_answer(b))).json()
        check("a correct answer: ok, done, the model answer, first try", r["verdict"] == "ok" and r["done"] and r["first_try"] and r["target"] and "explain" not in r, r)
        c_ = ids[2]
        r = (await answer("ann", S1["set"], c_, wrong_answer(c_))).json()
        r = (await answer("ann", S1["set"], c_, right_answer(c_))).json()
        check("wrong then right: ok but NOT a first try, 2 tries", r["verdict"] == "ok" and r["tries"] == 2 and r["first_try"] is False)
        d_ = ids[3]
        r = (await POST("ann", "/show", {"set": S1["set"], "item": d_})).json()
        check("'show answer': finished as shown with the target and the teaching lines", r["verdict"] == "shown" and r["done"] and r["target"] == items[d_].en[0] and r["explain"]["hi"]["formula"], r)
        check("...and it counts as a miss (review)", await count(GlReview, uid["ann"], item_id=d_) == 1)
        check("'show' twice returns the stored outcome", (await POST("ann", "/show", {"set": S1["set"], "item": d_})).json().get("repeat") is True)
        e_ = ids[4]
        from app.lab import checker
        unsure = None
        for cand in ("He plays football every day.", "She watches television every evening.", "They eat fruit every day.", "Rahul likes music a lot."):
            if checker.check(cand, bank.variants(items[e_].en), items[e_].unit)["verdict"] == "unsure":
                unsure = cand
                break
        if unsure:
            r = (await answer("ann", S1["set"], e_, unsure)).json()
            check("an 'unsure' answer finishes the item with no penalty and shows ours", r["verdict"] == "unsure" and r["done"] and r["target"] and await count(GlReview, uid["ann"], item_id=e_) == 0, r)
        else:
            r = (await answer("ann", S1["set"], e_, right_answer(e_))).json()
        check("an item that is not in the set is a 404", (await answer("ann", S1["set"], next(i.id for i in items.values() if i.id not in ids), "x")).status_code == 404)
        check("an unknown item id is a 404", (await answer("ann", S1["set"], "zz-q-99", "x")).status_code == 404)
        check("someone else's set is a 404 for check", (await answer("cat", S1["set"], ids[5], right_answer(ids[5]))).status_code == 404)
        check("someone else's set is a 404 for show", (await POST("cat", "/show", {"set": S1["set"], "item": ids[5]})).status_code == 404)
        check("a non-numeric set id is 422", (await POST("ann", "/check", {"set": "abc", "item": ids[5], "said": "x"})).status_code == 422)

        # ------------------------------------------------------------------ finishing: stars, best, next
        section("finishing a set: summary, stars, best, next step")
        last = None
        for iid in ids[5:]:
            last = (await answer("ann", S1["set"], iid, right_answer(iid))).json()
        sm = last["summary"]
        check("the last answer carries the summary", sm["total"] == 10 and sm["right"] + sm["wrong"] + sm["unsure"] == 10, sm)
        check("1 wrong + 1 shown among 10 = 80% over graded", sm["wrong"] == 2 and sm["graded"] == sm["right"] + 2 and sm["pct"] == round(100 * sm["right"] / sm["graded"]), sm)
        check("stars follow the percentage (80% = 2 stars, as 6+ graded)", sm["stars"] == (2 if sm["pct"] >= 80 and sm["pct"] < 90 else (3 if sm["pct"] >= 90 else (1 if sm["pct"] >= 60 else 0))), sm)
        check("the missed items are listed with Hindi and the answer", len(sm["missed"]) == 2 and all(m["hi"] and m["en"] for m in sm["missed"]))
        check("the weak rules are named in both languages", sm["weak"] and sm["weak"][0]["rule"]["hi"] and sm["weak"][0]["rule"]["en"], sm["weak"])
        check("new_best on the first set; a next step is suggested", sm["new_best"] is True and sm["next"]["reason"] in ("again", "next_level"), sm)
        check("the summary is stored: GET the set returns it", (await GET("ann", f"/set/{S1['set']}")).json().get("summary", {}).get("pct") == sm["pct"])
        st = (await GET("ann", "/state")).json()
        lv = next(u for u in st["units"] if u["unit"] == UNIT)["levels"][LEVEL]
        check("the hub shows the stars and the best", lv["stars"] == sm["stars"] and lv["best"] == sm["pct"] and lv["sets"] == 1 and st["open_set"] is None, lv)
        check("a finished set is closed: a new check on its items answers the stored outcome", (await answer("ann", S1["set"], ids[5], "x")).json().get("repeat") is True)

        # a perfect set: 3 stars; then a worse set does not lower the best
        _, S2 = await new_set("ann")
        check("the next set avoids the items served last time (recent)", len({i["id"] for i in S2["items"]} & set(ids)) <= 8, [i["id"] for i in S2["items"]])
        for i in S2["items"]:
            r = (await answer("ann", S2["set"], i["id"], right_answer(i["id"]))).json()
        sm2 = r["summary"]
        check("a perfect set: 100%, 3 stars, first_try 10, new best", sm2["pct"] == 100 and sm2["stars"] == 3 and sm2["first_try"] == 10 and sm2["new_best"] is True and sm2["best_stars"] == 3, sm2)
        check("3 stars at 'easy' suggest the next level", sm2["next"] == {"unit": UNIT, "level": "medium", "reason": "next_level"}, sm2["next"])
        last_u, last_l = catalog.UNITS[-1], catalog.LEVELS[-1]
        check("the next step after the end of one unit is the next unit, at easy",
              svc._next_step(catalog.UNITS[0], catalog.LEVELS[-1], 3, 100) == {"unit": catalog.UNITS[1], "level": "easy", "reason": "next_unit"})
        check("the next step after the LAST level of the LAST unit stays there (it never wraps to the first unit)",
              svc._next_step(last_u, last_l, 3, 100) == {"unit": last_u, "level": last_l, "reason": "path_end"}, svc._next_step(last_u, last_l, 3, 100))
        _, S3 = await new_set("ann")
        for i in S3["items"]:
            r = (await answer("ann", S3["set"], i["id"], wrong_answer(i["id"]))).json()
        for _ in range(2):
            for i in S3["items"]:
                r = (await answer("ann", S3["set"], i["id"], wrong_answer(i["id"]))).json()
        sm3 = r["summary"]
        check("an all-wrong set: 0%, 0 stars, not a new best, the best stays 3 stars", sm3["pct"] == 0 and sm3["stars"] == 0 and sm3["new_best"] is False and sm3["best_stars"] == 3 and sm3["best_pct"] == 100 and sm3["next"]["reason"] == "again", sm3)
        async with db._Session() as s:
            pr = (await s.execute(select(GlProgress).where(GlProgress.user_id == uid["ann"], GlProgress.unit == UNIT, GlProgress.level == LEVEL))).scalars().first()
            await s.commit()
        check("progress: 3 sets counted, best 100% / 3 stars kept", pr.sets == 3 and pr.stars == 3 and pr.best_pct == 100, (pr.sets, pr.stars, pr.best_pct))

        # star thresholds through the pure function
        check("stars: fewer than 6 graded = 0 stars", svc._stars(5, 5) == 0 and svc._stars(0, 0) == 0)
        check("stars: 90% = 3, 80% = 2, 60% = 1, 50% = 0 (over 10)", (svc._stars(9, 10), svc._stars(8, 10), svc._stars(6, 10), svc._stars(5, 10)) == (3, 2, 1, 0))
        check("stars: 89% is 2, 79% is 1, 59% is 0", (svc._stars(89, 100), svc._stars(79, 100), svc._stars(59, 100)) == (2, 1, 0))

        # ------------------------------------------------------------------ review
        section("review")
        st = (await GET("ann", "/state")).json()
        check("the missed items are waiting for review", st["review_due"] >= 2, st["review_due"])
        r, RV = await new_set("ann", "mixed", "review")
        check("a review set is made of the missed items", r.status_code == 200 and RV["unit"] == "mixed" and RV["level"] == "review" and 1 <= RV["total"] <= 10, r.text[:200])
        before = await count(GlReview, uid["ann"])
        for i in RV["items"]:
            r = (await answer("ann", RV["set"], i["id"], right_answer(i["id"]))).json()
        check("right answers in a review set take misses off; the progress rows are untouched", r["done"] and await count(GlReview, uid["ann"]) < before and await count(GlProgress, uid["ann"], unit="mixed") == 0)
        for _ in range(6):
            if (await GET("ann", "/state")).json()["review_due"] == 0:
                break
            _, RVx = await new_set("ann", "mixed", "review")
            for i in RVx["items"]:
                await answer("ann", RVx["set"], i["id"], right_answer(i["id"]))
        r = await POST("ann", "/set", {"unit": "mixed", "level": "review"})
        check("with nothing missed a review set is a 422", r.status_code == 422 and r.json()["detail"]["error"] == "nothing_to_review", r.text[:200])

        # ------------------------------------------------------------------ no text stored
        section("no learner text is stored anywhere")
        _, S4 = await new_set("bob")
        marker = "zzqq-private-words-xx"
        await answer("bob", S4["set"], S4["items"][0]["id"], f"He {marker} play")
        await answer("bob", S4["set"], S4["items"][1]["id"], f"{marker}")
        dump = ""
        for name in ("gl_sets", "gl_attempts", "gl_review", "gl_progress"):
            async for d in dbh[name].find({}):
                dump += json.dumps(d, default=str, ensure_ascii=False)
        check("what the learner typed is not in any gl_* document", marker not in dump and "private-words" not in dump)
        ex = json.dumps((await GET("bob", "/export")).json(), ensure_ascii=False)
        check("...nor in the export", marker not in ex)

        # ------------------------------------------------------------------ concurrency
        section("concurrency")
        _, S5 = await new_set("cat")
        iid = S5["items"][0]["id"]
        rs = await asyncio.gather(*[answer("cat", S5["set"], iid, right_answer(iid)) for _ in range(12)])
        check("12 simultaneous correct answers to one item: all 200", all(r.status_code == 200 for r in rs), [r.status_code for r in rs])
        check("...exactly ONE attempt row and ONE graded outcome", await count(GlAttempt, uid["cat"], item_id=iid) == 1 and sum(1 for r in rs if not r.json().get("repeat")) == 1, [r.json().get("repeat") for r in rs])
        rs = await asyncio.gather(*[POST("dan", "/set", {"unit": UNIT, "level": LEVEL}) for _ in range(8)])
        sets_made = {r.json()["set"] for r in rs if r.status_code == 200}
        check("8 simultaneous 'start a set' requests: no error and (almost always) one open set", all(r.status_code == 200 for r in rs) and len(sets_made) >= 1, [r.status_code for r in rs])
        open_n = await count(GlSet, uid["dan"], state="open")
        check("...and never more than one set left OPEN", open_n == 1, open_n)

        # ------------------------------------------------------------------ limits
        section("limits")
        old_cap = svc.MAX_SETS_PER_DAY
        svc.MAX_SETS_PER_DAY = 3
        made = 0
        r = None
        for u_ in catalog.UNITS[:6]:
            r = await POST("eve", "/set", {"unit": u_, "level": "easy"})
            made += r.status_code == 200
        svc.MAX_SETS_PER_DAY = old_cap
        check("the daily cap on new sets answers 429 too_many", made == 3 and r.status_code == 429 and r.json()["detail"]["error"] == "too_many", (made, r.status_code, r.text[:100]))
        _, S6 = await new_set("owner")
        codes = []
        for _ in range(100):
            codes.append((await answer("owner", S6["set"], S6["items"][0]["id"], "")).status_code)
        check("more than 90 checks a minute answers 429 slow_down", 429 in codes and codes.index(429) <= 91, codes[85:95])

        # ------------------------------------------------------------------ the unit with no authored items, and bad ids
        section("edge cases")
        _, S7 = await new_set("bob", "past_simple", "medium")
        async with db._Session() as s:
            row = await s.get(GlSet, S7["set"])
            import datetime as dt
            row.created_at = row.created_at - dt.timedelta(hours=7)
            await s.commit()
        _, S7b = await new_set("bob", "past_simple", "medium")
        check("...a new set is made", S7b["set"] != S7["set"])
        check("...and the old one is marked abandoned", (await GET("bob", f"/set/{S7['set']}")).status_code == 200 and (await check_state(S7["set"])) == "abandoned")
        r = (await answer("bob", S7["set"], S7["items"][0]["id"], "x"))
        check("a check on an abandoned set is 422 closed", r.status_code == 422 and r.json()["detail"]["error"] == "closed", r.text[:100])

        # ------------------------------------------------------------------ data rights
        section("export, delete, account deletion, owner wipe")
        for who in ("ann", "cat", "bob"):                                       # each learner that is about to be deleted has a MISS on record (a review row) - the table a careless delete forgets
            _, SM = await new_set(who, "past_simple", "hard")
            await POST(who, "/show", {"set": SM["set"], "item": SM["items"][0]["id"]})
            check(f"{who} has a review row before the delete", await count(GlReview, uid[who]) >= 1)
        ex = (await GET("ann", "/export")).json()
        check("export holds progress, sets, attempts and review", ex["progress"] and ex["sets"] and ex["attempts"] and "review" in ex and "private" not in json.dumps(ex))
        check("delete-all removes every Lab row of the learner", (await POST("ann", "/delete-all", {"confirm": True})).status_code == 200 and await none_left(uid["ann"]))
        check("...and nobody else's", await count(GlSet, uid["cat"]) >= 1 and await count(GlAttempt, uid["cat"]) >= 1)
        check("db.delete_user removes the Lab rows", await db.delete_user(uid["cat"]) and await none_left(uid["cat"]))
        await db.admin_wipe_users({em["owner"]})
        check("the owner's wipe removes the Lab rows of everyone else", await none_left(uid["bob"]))
        check("state works again for a learner with no rows", (await GET("owner", "/state")).status_code == 200)

        # ------------------------------------------------------------------ housekeeping
        section("housekeeping")
        import datetime as dt
        await db.login(people["ann"])
        async with db._Session() as s:
            s.add(GlSet(user_id=uid["ann"], unit=UNIT, level=LEVEL, items=[], results={}, state="done", summary={}, created_at=svc._utc() - dt.timedelta(days=120)))
            s.add(GlAttempt(user_id=uid["ann"], set_id=1, item_id="prs-e-01", unit=UNIT, level=LEVEL, verdict="ok", tries=1, codes=[], created_at=svc._utc() - dt.timedelta(days=120)))
            await s.commit()
        svc._last_prune = 0.0
        await GET("ann", "/state")
        check("rows older than 90 days are pruned", await count(GlSet, uid["ann"]) == 0 and await count(GlAttempt, uid["ann"]) == 0)
        check("column widths fit every value the code writes", all(len(x) <= 32 for x in catalog.UNITS) and all(len(x) <= 8 for x in list(catalog.LEVELS) + ["review"]) and all(len(i) <= 16 for i in items) and "mixed" in "mixed")

    print(f"\nlab selftest: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    return 1 if FAILS else 0


async def check_state(sid):
    async with db._Session() as s:
        row = await s.get(GlSet, sid)
        st = row.state
        await s.commit()
    return st


sys.exit(asyncio.run(main()))
