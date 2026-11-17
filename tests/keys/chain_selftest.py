"""Keys - tier 2d: the HTTP side of the validated walk (settings.chain_v3) and the fixes around it, on a scratch MongoDB, every provider scripted.

  * the owner's switch: /admin/settings accepts chain_v3 (off / owner / on, anything else reads as off), /admin/overview carries it and the per-model health card
  * /lesson/evaluate: nothing usable is no longer HTTP 200 with the parse-failure sentinel (the page only shows its "Good try!" default for a failed request)
  * /level/test/submit: the body is bounded (422), `passed` is the SAME rule the unlock uses (score >= 70), "eighty" is not a score of 0 (the validated walk asks the next model),
    and a reply nobody could use is a 502 that records NOTHING - never a failed 0% attempt
  * /leveltest/gen: one attempt when the validated walk is on (the walk already asked every model), the old three when it is off
  * saving a key: a provider that accepts the key but whose models answer with NOTHING stores it as 'unknown', not as working; a deep re-check says 'unreachable', not 'works'
Run via tests/keys/run.sh chain_selftest.py.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import httpx                                                        # noqa: E402

from world import World, install, ok, err, R, completion, GROQ_401   # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.keys import api as keys_api, gate, ledger, service as svc  # noqa: E402
from app.providers import openrouter_provider as op                 # noqa: E402

FAILS: list = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:500]}")


def section(t):
    print(f"\n== {t}")


PROSE = ok("Sure! I would love to help you with that, here you go.")
LESSON_OK = ok(json.dumps({"pass": True, "correct_english": "I went home.", "feedback": "good", "encouragement": "well done"}))
GEN_OK = ok(json.dumps({"repeat": "I usually walk to the market on Sunday morning.", "think_hindi": "Kal mujhe market jaana hai.", "open": "What is a small thing that made you smile this week?",
                        "mcqs": [{"field": "goal", "q": "Why English?", "options": ["Job", "Study", "Travel"]},
                                 {"field": "comfort", "q": "How comfortable?", "options": ["Not at all", "A little", "Okay", "Good", "Fluent"]},
                                 {"field": "practice_time", "q": "Daily time?", "options": ["10", "20", "30", "45"]}]}))
GK, MK = "gsk_chainhttp" + "G" * 26 + "xGq", "AIzachainhttp" + "M" * 26 + "xMq"


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh"
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    world = World()
    install(world)
    svc.schedule_recheck = lambda u: None

    async def sw(**kw):
        for k, v in kw.items():
            await db.set_setting(k, v)
        M.invalidate_access_cache()

    await sw(key_health="on", keys_ui="on", chain_v3="on")
    users = {"ann": {"sub": "u-ann", "email": "ann@example.com", "name": "Ann Lee", "picture": ""},
             "bob": {"sub": "u-bob", "email": "bob@example.com", "name": "Bob Lee", "picture": ""},
             "owner": {"sub": "u-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}}
    T = {}
    for n, u in users.items():
        await db.login(u)
        T[n] = auth.make_session(u)
    await db.save_user_keys("u-ann", {"groq": GK, "gemini": MK}, verified=True)
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        async def req(who, method, path, body=None, params=None):
            keys_api._hits.clear()
            return await c.request(method, path, headers={"Authorization": "Bearer " + T[who]} if who else {}, json=body, params=params)

        def fresh(w=None):
            nonlocal world
            gate.reset_all(); ledger.reset_all(); op._ring.clear(); op._cooldown.clear(); op._clients.clear()
            world = w or World()
            install(world)
            return world

        # -------------------------------------------------------------- the owner's switch
        section("the switch: /admin/settings and /admin/overview")
        r = await req("owner", "POST", "/admin/settings", {"chain_v3": "owner"})
        check("the owner can set chain_v3; the answer says so", r.status_code == 200 and r.json()["chain_v3"] == "owner", r.text)
        r = await req("owner", "POST", "/admin/settings", {"chain_v3": "zzz"})
        check("an unknown value is stored as off", r.status_code == 200 and r.json()["chain_v3"] == "off", r.text)
        r = await req("owner", "POST", "/admin/settings", {"key_health": "on"})
        check("a payload that leaves chain_v3 out leaves it alone (every switch defaults to None)", r.json()["chain_v3"] == "off" and r.json()["key_health"] == "on", r.text)
        r = await req("ann", "POST", "/admin/settings", {"chain_v3": "on"})
        check("an ordinary learner cannot flip it", r.status_code == 403, r.status_code)
        await sw(chain_v3="on")
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, LESSON_OK))
        await req("ann", "POST", "/lesson/evaluate", {"token": T["ann"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
        r = await req("owner", "GET", "/admin/overview", params={"token": T["owner"]})
        j = r.json()
        ch = j.get("chain_health") or {}
        check("the owner's dashboard carries the switch and the model-health card (per model, last hour: attempts and how they ended; what is being held back)",
              j.get("chain_v3") == "on" and isinstance(ch.get("models"), list) and isinstance(ch.get("held_back"), list)
              and any(m["provider"] == "groq" and m["bad"] == 1 for m in ch["models"]) and any(h["provider"] == "groq" and h["class"] == "json" for h in ch["held_back"]), j.get("chain_health"))
        check("... counts only: no key, no fingerprint, no learner id in it", GK not in json.dumps(ch) and "u-ann" not in json.dumps(ch) and gate.fingerprint("groq", GK) not in json.dumps(ch), ch)

        # -------------------------------------------------------------- /lesson/evaluate
        section("/lesson/evaluate")
        BODY = {"token": T["ann"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"}
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, LESSON_OK))
        r = await req("ann", "POST", "/lesson/evaluate", BODY)
        check("validated walk ON: Groq's prose is unusable, Gemini's verdict is the answer (HTTP 200, a real `pass`)", r.status_code == 200 and r.json().get("pass") is True and [c[0] for c in world.calls_for()] == ["groq", "gemini"], (r.status_code, r.text, world.calls))
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, PROSE))
        r = await req("ann", "POST", "/lesson/evaluate", BODY)
        j = r.json()
        check("nothing usable anywhere: HTTP 502 (not 200 with an error object the page would render as an empty verdict) and kp says the AI did not answer properly - never 'your keys'",
              r.status_code == 502 and j.get("kp", {}).get("state") == "transient" and j["kp"]["own"] is True and "evaluate" in str(j["detail"]).lower(), (r.status_code, j))
        await sw(chain_v3="off")
        fresh(World().on("groq", GK, PROSE))
        r = await req("ann", "POST", "/lesson/evaluate", BODY)
        check("validated walk OFF (per-key walker alone): the same sentinel is ALSO a 502 now (it was a 200 with an error object, for everyone)", r.status_code == 502 and "scoring_parse_failed" not in r.text, (r.status_code, r.text))
        await sw(key_health="off")
        fresh(World().on("groq", GK, PROSE))
        r = await req("ann", "POST", "/lesson/evaluate", BODY)
        check("the legacy walker: 502 as well", r.status_code == 502, (r.status_code, r.text))
        await sw(key_health="on", chain_v3="on")

        # -------------------------------------------------------------- /level/test/submit
        section("/level/test/submit")
        item = {"prompt": "Say: I like tea.", "target": "I like tea.", "said": "i like tea"}
        LT = {"token": T["ann"], "level": 1, "lang": "en", "items": [item]}
        for label, body in (("level 0", {**LT, "level": 0}), ("level 8", {**LT, "level": 8}), ("no items", {**LT, "items": []}), ("21 items", {**LT, "items": [item] * 21}),
                            ("a 2001-character answer", {**LT, "items": [{**item, "said": "x" * 2001}]}), ("a level that is not a number", {**LT, "level": "high"})):
            fresh()
            r = await req("ann", "POST", "/level/test/submit", body)
            check(f"{label}: 422, and no model was asked", r.status_code == 422 and not world.calls_for(), (r.status_code, len(world.calls)))
        fresh(World().on("groq", GK, ok(json.dumps({"score": 60, "passed": True, "items": [{"pass": True, "feedback": "f"}], "message": "m"}))))
        r = await req("ann", "POST", "/level/test/submit", LT)
        j = r.json()
        check("the model says passed:true but the score is 60: the learner is told what the UNLOCK decided (score >= 70 -> not passed)", r.status_code == 200 and j["score"] == 60 and j["passed"] is False, j)
        fresh(World().on("groq", GK, ok(json.dumps({"score": "70%", "passed": False, "items": [], "message": "m"}))))
        r = await req("ann", "POST", "/level/test/submit", LT)
        check("a score of '70%' (a string, as models do) counts as 70 and passes - the unlock and the screen agree", r.json()["score"] == 70 and r.json()["passed"] is True, r.text)
        fresh(World().on("groq", GK, ok(json.dumps({"score": "eighty", "message": "m"}))).on("gemini", MK, ok(json.dumps({"score": 85, "passed": False, "items": [], "message": "well done"}))))
        r = await req("ann", "POST", "/level/test/submit", LT)
        check("validated walk: 'eighty' is not a score - the next model scores it (85), where the old code recorded 0 for a learner who may have passed every item",
              r.status_code == 200 and r.json()["score"] == 85 and r.json()["passed"] is True and [c[0] for c in world.calls_for()] == ["groq", "gemini"], (r.status_code, r.text, world.calls))
        before = (await db.get_state("u-ann"))["progress"]["journey"].get("test_scores")
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, PROSE))
        r = await req("ann", "POST", "/level/test/submit", LT)
        after = (await db.get_state("u-ann"))["progress"]["journey"].get("test_scores")
        check("nothing usable anywhere: a 502, and NOTHING is recorded (no 0% attempt for a parse failure)", r.status_code == 502 and before == after, (r.status_code, before, after))
        await sw(chain_v3="off")
        fresh(World().on("groq", GK, ok(json.dumps({"score": "eighty", "message": "m"}))))
        r = await req("ann", "POST", "/level/test/submit", LT)
        check("validated walk OFF: today's reading of 'eighty' (it parses as 0) is unchanged - only the SOURCE of `passed` changed", r.status_code == 200 and r.json()["score"] == 0 and r.json()["passed"] is False, (r.status_code, r.text))
        await sw(chain_v3="on")

        # -------------------------------------------------------------- /leveltest/gen
        section("/leveltest/gen")
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, GEN_OK))
        r = await req("ann", "POST", "/leveltest/gen", {"token": T["ann"]})
        check("validated walk ON: ONE attempt - the walk asked Groq, then Gemini, and the learner gets a real level check", r.status_code == 200 and r.json()["repeat"].startswith("I usually walk")
              and len(r.json()["mcqs"]) == 3 and len(world.calls_for("groq")) == 1 and len(world.calls_for("gemini")) == 1, (r.status_code, world.calls))
        fresh(World().on("groq", GK, PROSE).on("gemini", MK, PROSE))
        r = await req("ann", "POST", "/leveltest/gen", {"token": T["ann"]})
        check("validated walk ON and nothing usable: ONE walk (Groq's two models + Gemini's = 3 requests, not the old 3 attempts x 1) and a 502 whose kp says the AI did not answer properly",
              r.status_code == 502 and len(world.calls_for()) == 3 and r.json().get("kp", {}).get("state") == "transient" and r.json()["detail"] == "gen_failed", (r.status_code, len(world.calls_for()), r.text))
        await sw(chain_v3="off")
        fresh(World().on("groq", GK, PROSE))
        r = await req("ann", "POST", "/leveltest/gen", {"token": T["ann"]})
        check("validated walk OFF: the old three attempts at the same first provider, then 502 gen_failed", r.status_code == 502 and len(world.calls_for("groq")) == 3, (r.status_code, len(world.calls_for("groq"))))
        await sw(chain_v3="on")

        # -------------------------------------------------------------- saving a key
        section("saving a key: a key counts as working only if one of its models ANSWERS")
        k1 = "gsk_save" + "S" * 30 + "xSq"
        fresh(World().on("groq", k1, R(200, completion("")), kind="chat"))
        r = await req("bob", "POST", "/keys/save", {"provider": "groq", "key": k1})
        j = r.json()
        st = (await req("bob", "GET", "/keys/status")).json()
        check("the provider accepts the key but BOTH its models answer with nothing: the key is stored - and is NOT 'working' (status unknown)", r.status_code == 200 and j["ok"] is True and j["result"]["status"] == "unknown"
              and st["stored"] == 1 and st["working"] == 0 and st["keys"][0]["status"] == "unknown", (r.status_code, j, st))
        check("... it tried the provider's second model before giving up", len(world.calls_for("groq", k1, "chat")) == 2, world.calls)
        r = await req("bob", "POST", "/keys/recheck", {"provider": "groq", "deep": True})
        check("a deep Test says 'unreachable', not 'works', and changes nothing", r.status_code == 200 and r.json()["checked"].get("groq") == "unreachable", r.text)
        world.on("groq", k1, ok("OK"), kind="chat")
        world.n.clear()
        r = await req("bob", "POST", "/keys/recheck", {"provider": "groq", "deep": True})
        st = (await req("bob", "GET", "/keys/status")).json()
        check("once a model really answers, the same key is working", r.json()["checked"].get("groq") == "ok" and st["working"] == 1 and st["keys"][0]["status"] == "ok", (r.text, st))
        k2 = "gsk_save2" + "T" * 30 + "xTq"
        fresh(World().on("groq", k2, R(200, completion("")), ok("OK"), kind="chat"))
        r = await req("bob", "POST", "/keys/save", {"provider": "groq", "key": k2})
        check("the first model empty, the second answers: working (one answer is enough)", r.json()["result"]["status"] == "ok" and len(world.calls_for("groq", k2, "chat")) == 2, (r.text, world.calls))
        bad = "gsk_bad" + "B" * 30 + "xBq"
        fresh(World().on("groq", bad, err(401, GROQ_401), kind="models"))
        r = await req("bob", "POST", "/keys/save", {"provider": "groq", "key": bad})
        check("a key the provider REJECTS is still never stored (unchanged)", r.status_code == 200 and r.json()["ok"] is False and r.json()["result"]["status"] == "invalid"
              and (await svc.stored_keys("u-bob")).get("groq") != bad, r.text)

    print(f"\n{N - len(FAILS)} / {N} checks passed")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
