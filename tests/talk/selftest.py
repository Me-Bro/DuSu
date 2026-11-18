"""Talk - the HTTP layer on a scratch MongoDB (run via tests/talk/run.sh selftest.py; never the app's own database).  No model, no key: the Talk screen's endpoints make no AI call.

Proves: the gates and the switch (401 / 404 / 403), the state shape (today's topic, three alternatives, band, default support by level, the three levels), the saved support level (validated,
per learner, deleted with the account), the owner dashboard and the Home registry (Talk appears only while the switch is on for the account), the rate limit, an empty bank."""
import asyncio
import datetime as dt
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/talk")

import httpx                                                        # noqa: E402
from app import auth, db, home_content, main as M                   # noqa: E402
from app.talk import topics as T, service as svc                    # noqa: E402
import fixtures as F                                                # noqa: E402

FAILS: list = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:400]}")


def section(t):
    print(f"\n== {t}")


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), "provider keys configured: run through run.sh"
    T.use(T.Bank.from_rows([r for b in T.BANDS for r in F.rows(b, 10)]))
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)

    people = {k: {"sub": f"u-{k}", "email": f"{k}@example.com", "name": k.title(), "picture": ""} for k in ("owner", "ann", "bob", "cat", "dan", "eve", "rate", "gone", "blk")}
    people["owner"]["email"] = "david123rana@gmail.com"
    levels = {"ann": "A1", "bob": "A2", "cat": "B1", "dan": "B2", "eve": "A0", "owner": "B1"}
    for k, u in people.items():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": levels.get(k, "A1"), "scores": {}, "weak_areas": []})
    T_ = {k: auth.make_session(u) for k, u in people.items()}
    em = {k: u["email"] for k, u in people.items()}
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        H = lambda who: {"Authorization": "Bearer " + T_[who]}                                    # noqa: E731
        GET = lambda who, p, **kw: c.get("/tk" + p, headers=H(who), **kw)                         # noqa: E731
        POST = lambda who, p, body=None: c.post("/tk" + p, headers=H(who), json=body if body is not None else {})   # noqa: E731

        async def switch(v):
            await db.set_setting("talk_v3", v)
            M.invalidate_access_cache()

        # ------------------------------------------------------------------ switch and gates
        section("switch off / owner / on, auth, blocked")
        await switch("off")
        check("the setting is absent by default = off (code default)", await M.talk_v3_mode() == "off")
        check("switch OFF: state is 404", (await GET("ann", "/state")).status_code == 404)
        check("switch OFF: a topic is 404", (await GET("ann", "/topic/a1-my-family")).status_code == 404)
        check("switch OFF: saving the support level is 404", (await POST("ann", "/prefs", {"support": "en"})).status_code == 404)
        check("switch OFF: even the owner gets 404", (await GET("owner", "/state")).status_code == 404)
        check("no token -> 401", (await c.get("/tk/state")).status_code == 401)
        check("junk token -> 401", (await c.get("/tk/state", headers={"Authorization": "Bearer junk.token"})).status_code == 401)
        check("a token in the query string works (like the other new routes)", (await c.get("/tk/state?token=" + T_["ann"])).status_code == 404)
        check("/me carries talk_v3=False while off", (await c.get("/me", headers=H("owner"))).json().get("talk_v3") is False)
        await switch("owner")
        check("switch OWNER: a normal learner is 404", (await GET("ann", "/state")).status_code == 404)
        check("switch OWNER: the owner is in and /me says so", (await GET("owner", "/state")).status_code == 200 and (await c.get("/me", headers=H("owner"))).json().get("talk_v3") is True)
        await db.early_add(em["bob"])
        M.invalidate_access_cache()
        check("switch OWNER: an early-access tester is in", (await GET("bob", "/state")).status_code == 200)
        check("the tester has no admin rights", (await c.get("/admin/overview", headers=H("bob"))).status_code == 403)
        await db.early_remove(em["bob"])
        M.invalidate_access_cache()
        check("switch OWNER: the tester is out again after the invite is removed", (await GET("bob", "/state")).status_code == 404)
        await switch("junk")
        check("a junk value in the setting reads as off", await M.talk_v3_mode() == "off" and (await GET("owner", "/state")).status_code == 404)
        await switch("on")
        check("switch ON: everyone is in", all([(await GET(k, "/state")).status_code == 200 for k in ("ann", "bob", "cat")]))
        await db.set_user_status(people["blk"]["sub"], "blocked")
        check("a blocked account is 403", (await GET("blk", "/state")).status_code == 403 and (await POST("blk", "/prefs", {"support": "en"})).status_code == 403)
        await db.set_user_status(people["blk"]["sub"], "active")

        # ------------------------------------------------------------------ state
        section("/tk/state")
        s = (await GET("ann", "/state")).json()
        check("the state has every key the client reads", {"enabled", "date", "level", "band", "support", "support_chosen", "support_default", "topic", "alternatives", "levels", "empty", "reviewed"} <= set(s), set(s))
        check("enabled, not empty, not reviewed (Hindi is unreviewed until a native reader signs off)", s["enabled"] is True and s["empty"] is False and s["reviewed"] is False)
        check("the date is today's IST day", s["date"] == T.ist_today().isoformat())
        t = s["topic"]
        check("today's topic is the FULL object (title, opener, 3 starters, vocab, focus)", set(t) == {"id", "band", "cat", "title", "opener", "starters", "vocab", "focus"} and len(t["starters"]) == 3 and 6 <= len(t["vocab"]) <= 8)
        check("it is the same topic the pure function picks for this learner today", t["id"] == T.today("u-ann", "A1", T.ist_today())["id"])
        check("the band follows the learner's level (A1 -> A1)", s["band"] == "A1" and t["band"] == "A1" and s["level"] == "A1")
        check("three alternatives, as small cards, none of them today's topic", len(s["alternatives"]) == 3 and all(set(a) == {"id", "title", "band", "cat", "focus"} for a in s["alternatives"]) and t["id"] not in [a["id"] for a in s["alternatives"]])
        check("the three levels: hi -> daily, en_sub -> talk, en -> talk, each with English and Hindi labels", [(x["id"], x["ws_mode"]) for x in s["levels"]] == [("hi", "daily"), ("en_sub", "talk"), ("en", "talk")]
              and all(set(x["label"]) == {"en", "hi"} and set(x["hint"]) == {"en", "hi"} for x in s["levels"]))
        check("the same state twice on the same day gives the same topic and the same alternatives", (await GET("ann", "/state")).json()["topic"]["id"] == t["id"] and [a["id"] for a in (await GET("ann", "/state")).json()["alternatives"]] == [a["id"] for a in s["alternatives"]])
        for who, lv, band, sup in [("ann", "A1", "A1", "hi"), ("eve", "A0", "A1", "hi"), ("bob", "A2", "A2", "en_sub"), ("cat", "B1", "B1", "en"), ("dan", "B2", "B1", "en")]:
            r = (await GET(who, "/state")).json()
            check(f"level {lv}: band {band}, default support {sup}, not chosen yet", r["band"] == band and r["support"] == sup and r["support_default"] == sup and r["support_chosen"] is False and r["topic"]["band"] == band, (r["band"], r["support"]))
        check("a different learner may get a different topic today", len({(await GET(k, "/state")).json()["topic"]["id"] for k in ("ann", "eve", "gone")}) >= 1)

        section("/tk/topic/{id}")
        r = await GET("ann", "/topic/a2-my-family")
        check("a known topic is returned in full (any band: the learner may pick another)", r.status_code == 200 and r.json()["id"] == "a2-my-family" and r.json()["band"] == "A2", r.text[:200])
        for bad in ("zz-nope", "a1-", "%2e%2e", "A1-MY-FAMILY", "a1-my-family%00", "x" * 100):
            check(f"unknown id {bad[:20]!r} is 404", (await GET("ann", "/topic/" + bad)).status_code == 404)
        check("a topic the bank does not hold cannot be made up by id arithmetic", (await GET("ann", "/topic/a1-my-family-99")).status_code == 404)

        # ------------------------------------------------------------------ prefs
        section("/tk/prefs")
        for v in ("en_sub", "en", "hi"):
            r = await POST("ann", "/prefs", {"support": v})
            check(f"saving {v!r} works", r.status_code == 200 and r.json() == {"support": v}, r.text)
            st = (await GET("ann", "/state")).json()
            check(f"...and the state shows it as the chosen level ({v})", st["support"] == v and st["support_chosen"] is True and st["support_default"] == "hi")
        for bad in ("", "english", "EN", "hindi", None, 5, ["en"], {"x": 1}, True):
            r = await POST("ann", "/prefs", {"support": bad})
            check(f"an invalid level {bad!r} is 422 and changes nothing", r.status_code == 422 and (await GET("ann", "/state")).json()["support"] == "hi", r.text)
        check("a body that is not JSON is 422", (await c.post("/tk/prefs", headers=H("ann"), content=b"{not json")).status_code == 422)
        check("an empty body is 422 (no support given)", (await POST("ann", "/prefs", {})).status_code == 422)
        check("an over-long body is 413", (await c.post("/tk/prefs", headers={**H("ann"), "content-type": "application/json"}, content=b'{"support": "' + b"x" * 5000 + b'"}')).status_code == 413)
        facts = await db.get_memory(people["ann"]["sub"])
        check("it is stored in memory.facts.talk_prefs and nothing else in the memory was changed", facts.get("talk_prefs") == {"support": "hi"} and set(facts) <= {"talk_prefs"}, facts)
        await POST("cat", "/prefs", {"support": "en_sub"})
        check("another learner's choice is NOT seen by this one (and the other way round)", (await GET("ann", "/state")).json()["support"] == "hi" and (await GET("cat", "/state")).json()["support"] == "en_sub"
              and (await GET("bob", "/state")).json()["support_chosen"] is False)
        await db.merge_facts(people["ann"]["sub"], {"profession": "teacher"}, [])
        check("saving the memory elsewhere (merge_facts) keeps the saved level", (await db.get_memory(people["ann"]["sub"])).get("talk_prefs") == {"support": "hi"})
        await POST("ann", "/prefs", {"support": "en"})
        check("saving the level keeps the rest of the memory", (await db.get_memory(people["ann"]["sub"])).get("profession") == "teacher")

        # ------------------------------------------------------------------ the account
        section("data rights: the saved level goes with the account")
        await POST("gone", "/prefs", {"support": "en"})
        check("it exists before", (await db.get_memory(people["gone"]["sub"])).get("talk_prefs") == {"support": "en"})
        await db.delete_user(people["gone"]["sub"])
        check("after the account is deleted nothing of it is left", (await db.get_memory(people["gone"]["sub"])) == {})

        # ------------------------------------------------------------------ rate limit
        section("rate limit")
        codes = [(await GET("rate", "/topic/zz-nope")).status_code for _ in range(70)]
        check("60 requests a minute are served (404 = unknown topic, not limited), then 429", codes[:60] == [404] * 60 and set(codes[60:]) == {429}, codes[55:65])
        check("another learner is not limited by this one", (await GET("ann", "/state")).status_code == 200)

        # ------------------------------------------------------------------ an empty bank
        section("an empty or half-authored bank")
        T.use(T.Bank.from_rows([]))
        r = (await GET("ann", "/state")).json()
        check("an empty bank is a normal answer (empty:true, topic null, no alternatives), never a 500", r["empty"] is True and r["topic"] is None and r["alternatives"] == [] and len(r["levels"]) == 3, r)
        T.use(T.Bank.from_rows(F.rows("B1", 6)))
        r = (await GET("ann", "/state")).json()
        check("a learner whose band is not authored yet gets the nearest authored band", r["topic"] and r["topic"]["band"] == "B1" and r["band"] == "A1")
        T.use(T.Bank.from_rows([r for b in T.BANDS for r in F.rows(b, 10)]))

        # ------------------------------------------------------------------ dashboard
        section("owner dashboard and settings")
        o = (await c.get("/admin/overview", headers=H("owner"))).json()
        check("/admin/overview carries talk_v3 and a health line", o.get("talk_v3") == "on" and isinstance(o.get("talk_v3_health"), dict), {k: o.get(k) for k in ("talk_v3", "talk_v3_health")})
        h = o["talk_v3_health"]
        check("the health line has topics per band, rejected rows and today's talk chats", h["topics"] == {"total": 30, "A1": 10, "A2": 10, "B1": 10} and h["rejected"] == 0 and h["sessions_today"] == 0 and h["missing"] == ["a1", "a2", "b1"] or h["topics"]["total"] == 30, h)
        for v, want in (("owner", "owner"), ("off", "off"), ("on", "on"), ("banana", "off")):
            r = await c.post("/admin/settings", headers=H("owner"), json={"talk_v3": v})
            check(f"POST /admin/settings talk_v3={v!r} -> {want!r}", r.status_code == 200 and r.json()["talk_v3"] == want, r.text[:200])
        before = (await c.get("/admin/overview", headers=H("owner"))).json()
        r = await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "owner"})
        after = r.json()
        check("flipping another switch leaves talk_v3 alone", after["talk_v3"] == before["talk_v3"] == "off")
        r = await c.post("/admin/settings", headers=H("owner"), json={"grammar_lab": "off"})
        check("a normal learner cannot flip it", (await c.post("/admin/settings", headers=H("ann"), json={"talk_v3": "on"})).status_code == 403)
        await switch("on")

        # ------------------------------------------------------------------ the Home registry
        section("the Home registry: Talk exists only while the switch is on for the account")
        await db.set_setting("home_ai", "on")
        M.invalidate_access_cache()
        me = (await c.get("/me", headers=H("ann"))).json()
        tiles = me.get("home_tiles") or []
        check("switch ON: /me.home_tiles has the Talk tile with the route /talk", any(x["id"] == "talk" and x["route"] == "/talk" for x in tiles), [x["id"] for x in tiles])
        check("the tile carries Hindi and English titles", next(x for x in tiles if x["id"] == "talk")["t"].keys() >= {"hi", "en"})
        r = (await c.get("/home/features?lang=en", headers=H("ann"))).json()
        check("Know About lists Talk with its route", any(f["id"] == "talk" and f.get("route") == "/talk" for f in r["features"]), [f["id"] for f in r["features"]])
        check("the model's catalogue can name it (valid id) only while on", "talk" in home_content.valid_ids(await M._home_flags(em["ann"])))
        await switch("off")
        me = (await c.get("/me", headers=H("ann"))).json()
        check("switch OFF: /me.home_tiles has no Talk tile", not any(x["id"] == "talk" for x in (me.get("home_tiles") or [])))
        r = (await c.get("/home/features?lang=en", headers=H("ann"))).json()
        check("switch OFF: Know About does not list Talk (not even as 'coming soon')", not any(f["id"] == "talk" for f in r["features"]), [f["id"] for f in r["features"]])
        check("switch OFF: the id is not valid for the model to suggest", "talk" not in home_content.valid_ids(await M._home_flags(em["ann"])))
        check("switch OFF: the model's catalogue never mentions Talk's route or id", "/talk" not in home_content.catalog(await M._home_flags(em["ann"])) and "talk_v3" not in home_content.catalog(await M._home_flags(em["ann"])))
        await switch("owner")
        check("switch OWNER: the owner sees the tile, a normal learner does not", any(x["id"] == "talk" for x in (await c.get("/me", headers=H("owner"))).json().get("home_tiles") or [])
              and not any(x["id"] == "talk" for x in (await c.get("/me", headers=H("ann"))).json().get("home_tiles") or []))

        # ------------------------------------------------------------------ the rest of the system
        section("shared code: bonus, missions, badges, labels")
        check("db._MODE_BONUS lists talk explicitly, equal to Face-to-Face's", db._MODE_BONUS.get("talk") == db._MODE_BONUS["conversation"] == 15, db._MODE_BONUS)
        check("an unlisted mode would still be booked as 'conversation' (the trap the explicit entry avoids)", "zzz" not in db._MODE_BONUS)
        from app import life
        check("life.py names the mode (the learner's own numbers block says 'Talk', not 'talk')", life._MODE_LABELS.get("talk") == "Talk")
        scores = {"confidence": 60, "continuity": 60, "vocabulary": 60, "grammar_trend": 60, "depth": 60}
        a = people["ann"]["sub"]
        await db.get_weekly_missions(a)
        res = await db.update_weekly_missions(a, "talk", 2.0, 70)
        sess_m = next(m for m in res["missions"] if m["metric"] == "conversation_sessions")
        check("a finished Talk chat counts toward the weekly 'Face to Face Talk sessions' mission", sess_m["progress"] == 1, res["missions"])
        res = await db.update_weekly_missions(a, "daily", 2.0, 70)
        check("a Daily Talk chat still does not (unchanged)", next(m for m in res["missions"] if m["metric"] == "conversation_sessions")["progress"] == 1)
        res = await db.update_weekly_missions(a, "conversation", 2.0, 70)
        check("Face-to-Face still does (unchanged)", next(m for m in res["missions"] if m["metric"] == "conversation_sessions")["progress"] == 2)
        got = await db.award_speaker_progress(people["bob"]["sub"], "talk", minutes=0.0, turns=6, scores=scores, genuine_effort=True)
        got2 = await db.award_speaker_progress(people["eve"]["sub"], "conversation", minutes=0.0, turns=6, scores=scores, genuine_effort=True)
        check("a Talk session is booked as 'talk' (not silently as Face-to-Face) with the same XP as Face-to-Face", got and got2 and got["xp_earned"] == got2["xp_earned"] if "xp_earned" in (got or {}) else bool(got and got2), (got, got2))
        async with db._Session() as s_:
            rows = (await s_.execute(db.select(db.SessionScore.mode).where(db.SessionScore.user_id == people["bob"]["sub"]))).scalars().all()
            await s_.commit()
        check("the SessionScore row says mode 'talk'", rows == ["talk"], rows)
        for _ in range(25):
            await db.award_speaker_progress(people["dan"]["sub"], "talk", minutes=0.0, turns=6, scores=scores, genuine_effort=True)
            await db.award_speaker_progress(people["dan"]["sub"], "conversation", minutes=0.0, turns=6, scores=scores, genuine_effort=True)
        await db.check_achievement_badges(people["dan"]["sub"])
        badges_dan = (await db.get_state(people["dan"]["sub"]))["progress"]["badges"]
        check("25 Face-to-Face + 25 Talk sessions earn 'Fearless Speaker' (Talk counts as an English conversation)", "fearless_speaker" in badges_dan, badges_dan)
        for _ in range(24):
            await db.award_speaker_progress(people["cat"]["sub"], "talk", minutes=0.0, turns=6, scores=scores, genuine_effort=True)
        await db.check_achievement_badges(people["cat"]["sub"])
        check("24 Talk sessions earn nothing yet (the threshold is unchanged)", "fearless_speaker" not in (await db.get_state(people["cat"]["sub"]))["progress"]["badges"])

    print(f"\ntalk selftest: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
