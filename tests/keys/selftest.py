"""Keys - tier 2: the real HTTP layer, the real database and the real walker, with every provider scripted (tests/keys/world.py). NO network, NO real key.

Run via tests/keys/run.sh (a scratch Postgres on an INTERNAL docker network; every provider key blanked). The app is driven in-process through httpx's ASGI transport.

What is proven, in the order it is driven: the old -> new schema rehearsal (the two new kh_* tables next to old data, init_db twice); the switch and the gates (404 while it is
off, 401, 403 blocked, early-access testers); saving ONE key (auth probe, one real call, masked answer, the provider's allowance numbers, a rejected key never stored, an
unreachable provider never stored, a limited key stored as limited, a replaced key forgets the old one, shape validation, rate limit); a merge that can never wipe (twelve
concurrent saves, an empty save); the status payload (used today, exact / computed / unknown allowance, never a key); stored-keys-first precedence; what a learner is told
when every key is limited / rejected / the provider is down (HTTP bodies with `kp`, old clients' `detail` unchanged, a learner without the switch unchanged); /me; the legacy
/keys/verify (replace-all for a learner without the switch, merge with it); re-check (shallow keeps a limit, deep tests, a rejected key can come back); remove; the ledger
(rows == requests incl. a cancelled one, a deleted learner's rows dropped without poisoning the batch, a database hiccup re-queues); the lazy background re-check of a legacy
key; data rights; /health; the owner dashboard; Grammar Coach's cooling question. No key text in any response and none in any log line.
"""

import asyncio
import contextlib
import io
import json
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import httpx                                                        # noqa: E402
from sqlalchemy import func, select, text as sa_text                # noqa: E402
from sqlalchemy.exc import OperationalError                         # noqa: E402

from world import (World, install, ok, err, timeout, conn, completion, R, GROQ_401, GROQ_429_TPD, GROQ_429_PLAIN, GEMINI_400_KEY, GEMINI_400_AUTH_KEY, GEMINI_429_DAY, GEMINI_503,   # noqa: E402
                   OPENROUTER_401, OPENROUTER_429_DAY)

from app import auth, db, main as M                                 # noqa: E402
from app.keys import api as keys_api, classify, gate, ledger, probe, service as svc  # noqa: E402
from app.keys import models as KM                                   # noqa: E402
from app.providers import openrouter_provider as op                 # noqa: E402

FAILS: list = []
FIVE: list = []
N = 0
LEAKS: list = []


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


class Tee(io.TextIOBase):
    """Everything the app prints is also kept, so the end of the run can prove no key text was ever logged."""

    def __init__(self, real):
        self.real, self.buf = real, io.StringIO()

    def write(self, s):
        self.buf.write(s)
        return self.real.write(s)

    def flush(self):
        self.real.flush()


TEE = Tee(sys.stdout)
sys.stdout = TEE

# a distinct, searchable, secret-looking key per learner and provider: the MIDDLE part is what must never appear in a response or a log
SECRET: list = []


def GK(n, v=1):
    k = f"gsk_{n}{v}" + "G" * 24 + f"{n}{v}xGq"
    SECRET.append(k[8:-6]); return k


def MK(n, v=1):
    k = f"AIza{n}{v}" + "M" * 24 + f"{n}{v}xMq"
    SECRET.append(k[8:-6]); return k


def OK_(n, v=1):
    k = f"sk-or-v1-{n}{v}" + "O" * 24 + f"{n}{v}xOq"
    SECRET.append(k[14:-6]); return k


names = ["ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ida", "ivy", "jon", "kim", "lee", "max", "mia", "ola", "lou", "pia", "zed", "sim", "ned", "tes", "uni"]
uid = lambda n: f"u-{n}"                                            # noqa: E731
JSONOK = lambda: ok('{"pass": true, "feedback": "good"}')           # noqa: E731

WORLD = World()
WORLD.default_chat = JSONOK
install(WORLD)
svc.schedule_recheck = lambda u: None                               # no background re-checks unless a test asks for one (they would add provider calls to every count)


def reset_world():
    global WORLD
    WORLD = World()
    WORLD.default_chat = JSONOK
    install(WORLD)
    gate.reset_all()


async def rows(model, *conds):
    async with db._Session() as s:
        return (await s.execute(select(model).where(*conds))).scalars().all()


async def count(model, *conds):
    async with db._Session() as s:
        return int((await s.execute(select(func.count()).select_from(model).where(*conds))).scalar() or 0)


async def stored(u):
    return await svc.stored_keys(uid(u))


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
        "refusing to run: provider keys are configured - run through run.sh, which blanks them"

    # ------------------------------------------------------------------ OLD -> NEW schema rehearsal
    section("schema rehearsal: production has every table EXCEPT the two new kh_* ones")
    for _ in range(20):
        try:
            async with db._engine.begin() as cx:
                await cx.run_sync(lambda sc: db.Base.metadata.create_all(sc, tables=[t for t in db.Base.metadata.sorted_tables if not t.name.startswith("kh_")]))
            break
        except Exception:
            await asyncio.sleep(1)

    async def kh_tables():
        async with db._engine.connect() as cx:
            return {r[0] for r in (await cx.execute(sa_text("select table_name from information_schema.tables where table_schema='public' and table_name like 'kh\\_%'"))).all()}

    pre = await kh_tables()
    old = {"sub": "u-old", "email": "old@example.com", "name": "Old", "picture": ""}
    await db.login(old)
    OLD_G, OLD_H = GK("old"), "ghp_" + "H" * 36
    await db.save_user_keys("u-old", {"groq": OLD_G, "github": OLD_H}, verified=True)
    check("the old schema has no kh_* table and the learner's legacy keys are stored", pre == set() and (await db.get_user_keys("u-old")).get("groq") == OLD_G, pre)
    await db.init_db()
    await db.init_db()
    post = await kh_tables()
    async with db._engine.connect() as cx:
        cols = {(r[0], r[1]): (r[2], r[3]) for r in (await cx.execute(sa_text(
            "select table_name, column_name, data_type, character_maximum_length from information_schema.columns where table_name in ('kh_status','kh_usage')"))).all()}
        idx = {r[0] for r in (await cx.execute(sa_text("select indexname from pg_indexes where tablename in ('kh_status','kh_usage')"))).all()}
    check("init_db() adds exactly the two new tables, twice in a row, next to the old data", post == {"kh_status", "kh_usage"}, post)
    check("the columns are what the code writes", cols[("kh_status", "meta")][0] == "jsonb" and cols[("kh_status", "fp")][1] == 16 and cols[("kh_usage", "day")][1] == 10
          and ("kh_usage", "tokens_out") in cols and ("kh_status", "rl_remaining") in cols, cols)
    check("the day index exists", "ix_kh_usage_day" in idx, idx)
    check("the existing learner's keys are untouched", (await db.get_user_keys("u-old")).get("groq") == OLD_G)

    # ------------------------------------------------------------------ users + client
    users = {n: {"sub": uid(n), "email": f"{n}@example.com", "name": f"{n.title()} Lee", "picture": ""} for n in names}
    for u in users.values():
        await db.login(u)
    T = {n: auth.make_session(u) for n, u in users.items()}
    owner = {"sub": "u-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    await db.login(owner)
    T["owner"] = auth.make_session(owner)
    tr = httpx.ASGITransport(app=M.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        def H(who):
            return {"Authorization": "Bearer " + T[who]}

        async def req(who, method, path, body=None, params=None, leak_ok=False, expect5xx=False):
            r = await c.request(method, path, headers=H(who) if who else {}, json=body, params=params)
            if r.status_code >= 500 and not expect5xx:
                FIVE.append((method, path, r.status_code))
            if not leak_ok and r.status_code != 404:
                for s_ in SECRET:
                    if s_ in r.text:
                        LEAKS.append((method, path, "response"))
                        break
            return r

        async def api(who, method, path, body=None, params=None, keep=False):
            if not keep:
                keys_api._hits.clear()                              # the per-learner rate limits are tested on purpose, once; everywhere else they must not get in the way
            return await req(who, method, "/keys" + path, body, params)

        async def save(who, provider, key, keep=False):
            return await api(who, "POST", "/save", {"provider": provider, "key": key}, keep=keep)

        async def set_mode(**kw):
            for k, v in kw.items():
                await db.set_setting(k, v)
            M.invalidate_access_cache()

        # -------------------------------------------------------------- the switch and the gates
        section("gates: the switch, sign-in, every verb")
        await set_mode(key_health="off", keys_ui="off", install_mode="off")
        for m, p in (("GET", "/status"), ("POST", "/save"), ("POST", "/remove"), ("POST", "/recheck")):
            r = await api("ann", m, p, {} if m == "POST" else None)
            check(f"switch OFF: {m} /keys{p} is 404 (invisible)", r.status_code == 404, r.status_code)
        r = await api("ann", "GET", "/export")
        check("switch OFF: the data-rights export still answers", r.status_code == 200 and "usage" in r.json(), r.text)
        me = (await req("ann", "GET", "/me")).json()
        check("/me says the engine and the screens are OFF and carries no `keys` block", me.get("key_health") is False and me.get("keys_ui") is False and "keys" not in me, {k: me.get(k) for k in ("key_health", "keys_ui", "keys")})
        await set_mode(key_health="on")
        for m, p in (("GET", "/status"), ("POST", "/save"), ("POST", "/remove"), ("POST", "/recheck")):
            r = await api(None, m, p, {} if m == "POST" else None)
            check(f"no token: {m} /keys{p} is 401", r.status_code == 401, r.status_code)
        r = await c.get("/keys/status", headers={"Authorization": "Bearer junk.token"})
        check("a junk token is 401", r.status_code == 401)
        await db.set_user_status(uid("zed"), "blocked")
        r = await api("zed", "GET", "/status")
        check("a blocked account is 403", r.status_code == 403, r.status_code)
        await set_mode(key_health="owner")
        r = await api("ann", "GET", "/status")
        check("'owner' stage: an ordinary learner still gets 404", r.status_code == 404, r.status_code)
        r = await api("owner", "GET", "/status")
        check("... the owner gets through", r.status_code == 200, r.status_code)
        await db.early_add("ann@example.com")
        M.invalidate_access_cache()
        r = await api("ann", "GET", "/status")
        check("... and an invited early-access tester gets through too (visibility only)", r.status_code == 200, r.status_code)
        await db.early_remove("ann@example.com")
        await set_mode(key_health="on")
        me = (await req("ann", "GET", "/me")).json()
        check("/me says the engine is ON (screens still off: the second switch)", me.get("key_health") is True and me.get("keys_ui") is False, (me.get("key_health"), me.get("keys_ui")))
        await set_mode(keys_ui="on")
        me = (await req("ann", "GET", "/me")).json()
        check("/me says the screens are ON when both switches are", me.get("keys_ui") is True)
        await set_mode(key_health="off")
        me = (await req("ann", "GET", "/me")).json()
        check("the screens need the engine: keys_ui on + key_health off = no screens", me.get("keys_ui") is False)
        await set_mode(key_health="on")

        # -------------------------------------------------------------- saving ONE key
        section("saving one key: probe, one real call, masked answer, merge")
        g1, m1, o1 = GK("ann"), MK("ann"), OK_("ann")
        hdr = {"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14399", "x-ratelimit-reset-requests": "1m30s"}
        WORLD.on("groq", g1, ok("OK", headers=hdr), kind="chat")
        r = await save("ann", "groq", g1)
        j = r.json()
        calls = [(x[2]) for x in WORLD.calls if x[1] == g1]
        check("save: the auth probe (zero quota) runs first, then exactly ONE real call", r.status_code == 200 and j["ok"] is True and calls == ["models", "chat"], (r.status_code, calls))
        check("save: the answer is masked - provider prefix + dots + last four, never the key", j["result"]["masked"] == "gsk_••••" + g1[-4:] and g1 not in r.text and g1[8:-6] not in r.text, j)
        st = j["status"]
        k0 = st["keys"][0]
        check("save: the status says groq works, its allowance is EXACT (the provider's own headers), and the verification call is counted as 1 request used",
              k0["provider"] == "groq" and k0["status"] == "ok" and k0["allowance"]["kind"] == "exact" and k0["allowance"]["limit"] == 14400 and k0["allowance"]["left"] == 14399
              and k0["used_today"]["requests"] == 1 and k0["masked"] == j["result"]["masked"], k0)
        check("save: one key stored = 'ok' with 1 of 2 (the app still needs a second key to START)", st["state"] == "ok" and st["stored"] == 1 and st["working"] == 1 and st["min"] == 2, st)
        check("save: it is really stored (sealed), and has_keys is still false (needs 2)", (await stored("ann")).get("groq") == g1 and not await db.has_user_keys(uid("ann")))
        row = (await rows(KM.KhStatus, KM.KhStatus.user_id == uid("ann")))[0]
        check("save: a status row exists with the fingerprint, never the key", row.fp == gate.fingerprint("groq", g1) and row.status == "ok" and row.rl_limit == 14400 and g1 not in json.dumps(row.meta), row.fp)
        r = await save("ann", "gemini", m1)
        st = r.json()["status"]
        check("a second key MERGES with the first (both are in the answer, in the app's fixed order)", [k["provider"] for k in st["keys"]] == ["groq", "gemini"] and st["working"] == 2 and st["state"] == "ok", st)
        check("... and now the learner is SET UP (has_keys)", await db.has_user_keys(uid("ann")) and (await stored("ann")) == {"groq": g1, "gemini": m1})
        check("... Gemini has no quota API: its allowance is 'unknown', not a guess", st["keys"][1]["allowance"] == {"kind": "unknown"}, st["keys"][1])
        r = await save("ann", "openrouter", o1)
        st = r.json()["status"]
        a = st["keys"][2]["allowance"]
        check("a third key: OpenRouter's allowance is COMPUTED from its documented free cap minus what DuSu counted (marked so)", a["kind"] == "computed" and a["limit"] == 50 and a["left"] == 49, a)
        check("... all three work", st["state"] == "ok" and st["working"] == 3 and st["stored"] == 3)

        # -------------------------------------------------------------- what is refused
        section("refusals: a key the provider rejects is never stored")
        bad = GK("ann", 9)
        WORLD.on("groq", bad, err(401, GROQ_401), kind="models")
        r = await save("ann", "groq", bad)
        check("a rejected key (the auth probe says 401): not ok, status 'invalid', and NOTHING was stored or changed", r.json()["ok"] is False and r.json()["result"]["status"] == "invalid"
              and (await stored("ann"))["groq"] == g1 and not [x for x in WORLD.calls if x[1] == bad and x[2] == "chat"], r.text)
        bad2 = MK("ann", 9)
        WORLD.on("gemini", bad2, err(400, GEMINI_400_KEY), kind="models")
        r = await save("ann", "gemini", bad2)
        check("a Gemini 'API key not valid' (a 400 with a LIST body) is rejected the same way", r.json()["ok"] is False and r.json()["result"]["status"] == "invalid", r.text)
        bad_aq = "AQ.Ab8RN6" + "w" * 40 + "ann9"
        WORLD.on("gemini", bad_aq, err(400, GEMINI_400_AUTH_KEY), kind="models")
        r = await save("ann", "gemini", bad_aq)
        check("a wrong AQ. key (Google: 400 'Invalid Auth key.') is 'invalid', never 'unreachable', and is not stored", r.json()["ok"] is False and r.json()["result"]["status"] == "invalid"
              and (await stored("ann"))["gemini"] == m1, r.text)
        good_aq = "AQ.Ab8RN6" + "v" * 40 + "ann8"
        r = await save("ann", "gemini", good_aq)
        check("a good AQ. key (the only kind AI Studio hands out since 2026-05-28) is saved and shown as AQ.••••<last four>", r.json()["ok"] is True and r.json()["result"]["masked"] == "AQ.••••ann8"
              and (await stored("ann"))["gemini"] == good_aq, r.text)
        await save("ann", "gemini", m1)                                    # put the earlier key back: the sections below expect it
        bad3 = OK_("ann", 9)
        WORLD.on("openrouter", bad3, err(401, OPENROUTER_401), kind="key")
        r = await save("ann", "openrouter", bad3)
        check("an OpenRouter 401 on /key is rejected", r.json()["ok"] is False and r.json()["result"]["status"] == "invalid")
        exp = GK("ann", 8)
        WORLD.on("groq", exp, err(401, {"error": {"message": "API key expired", "code": "invalid_api_key"}}), kind="models")
        r = await save("ann", "groq", exp)
        check("an EXPIRED key says so", r.json()["result"].get("expired") is True, r.text)
        unreach = GK("ann", 7)
        WORLD.on("groq", unreach, timeout(), kind="models")
        r = await save("ann", "groq", unreach)
        check("a provider we cannot reach: 'unreachable' - nothing is stored on a guess", r.json()["ok"] is False and r.json()["result"]["status"] == "unreachable" and (await stored("ann"))["groq"] == g1, r.text)
        authok_chat_bad = GK("ann", 6)
        WORLD.on("groq", authok_chat_bad, err(401, GROQ_401), kind="chat")
        r = await save("ann", "groq", authok_chat_bad)
        check("a key that authenticates but is rejected on the real call is not stored either", r.json()["ok"] is False and r.json()["result"]["status"] == "invalid" and (await stored("ann"))["groq"] == g1, r.text)
        lim = GK("ann", 5)
        WORLD.on("groq", lim, err(429, GROQ_429_TPD), kind="chat")
        r = await save("ann", "groq", lim)
        j = r.json()
        check("a REAL key that is over its limit right now IS stored - as 'limited', with the provider's own reset time", j["ok"] is True and j["result"]["status"] == "limited"
              and (await stored("ann"))["groq"] == lim and j["status"]["keys"][0]["status"] == "limited" and j["status"]["keys"][0]["reset_at"] and not j["status"]["keys"][0]["approx"], j)
        check("... and the replaced key's status row is gone (one row per provider)", len(await rows(KM.KhStatus, KM.KhStatus.user_id == uid("ann"), KM.KhStatus.provider == "groq")) == 1)
        WORLD.on("groq", g1, ok("OK"), kind="chat")
        r = await save("ann", "groq", g1)
        check("putting the good key back replaces the limited one, status ok, and the gate forgot the limit", r.json()["status"]["keys"][0]["status"] == "ok" and gate.get("groq", gate.fingerprint("groq", g1)) is None)
        r = await api("ann", "POST", "/save", {"provider": "github", "key": "ghp_" + "x" * 36})
        check("a provider we do not support (github) is 422", r.status_code == 422, r.text)
        for key in ("", "short", "has space inside the key here", "k" * 500, None, 12):
            r = await api("ann", "POST", "/save", {"provider": "groq", "key": key})
            check(f"key shape {str(key)[:12]!r} is 422, never a probe", r.status_code == 422 and r.json()["detail"]["error"] == "key_shape", (r.status_code, r.text))
        r = await api("ann", "POST", "/save", {"provider": "groq", "key": "x" * 20, "token": "ignored"})
        check("a body without a usable token field still uses the header's login", r.status_code == 200, r.status_code)
        before = len(WORLD.calls)
        statuses = []
        keys_api._hits.clear()
        for _ in range(10):
            statuses.append((await save("ann", "groq", g1, keep=True)).status_code)
        check("saving is rate limited (8 a minute per learner) with a plain 'slow_down'", statuses.count(429) >= 2 and statuses[:3] == [200, 200, 200], statuses)

        # -------------------------------------------------------------- merge can never wipe
        section("merge: twelve concurrent saves and an empty save lose nothing")
        reset_world()
        gs = [GK("cat", v) for v in range(1, 5)]
        ms = [MK("cat", v) for v in range(1, 5)]
        os_ = [OK_("cat", v) for v in range(1, 5)]
        real_rate = keys_api._rate
        keys_api._rate = lambda *a, **k: None                       # the limiter is tested on its own; here the merge is
        jobs = [save("cat", "groq", k) for k in gs] + [save("cat", "gemini", k) for k in ms] + [save("cat", "openrouter", k) for k in os_]
        res = await asyncio.gather(*jobs)
        keys_api._rate = real_rate
        codes = [r.status_code for r in res]
        blob = await stored("cat")
        check("12 saves at once (3 providers x 4 keys): every provider is present afterwards and each holds ONE of the keys that was submitted (no lost update, no torn blob)",
              set(blob) == {"groq", "gemini", "openrouter"} and blob["groq"] in gs and blob["gemini"] in ms and blob["openrouter"] in os_, (codes, blob and {k: v[:8] for k, v in blob.items()}))
        check("... every one of the 12 answered 200 (none was a 5xx, a deadlock or a lost row)", codes == [200] * 12, codes)
        check("... and the learner is SET UP afterwards", await db.has_user_keys(uid("cat")) and (await svc.status_payload(uid("cat"), schedule=False))["stored"] == 3)
        before = await stored("cat")
        r = await req("cat", "POST", "/keys/verify", {"keys": {}})
        check("(the older /keys/verify) an EMPTY request cannot wipe the stored set when the engine is on", r.status_code == 200 and await stored("cat") == before, r.text)

        # -------------------------------------------------------------- status, usage, honest numbers
        section("status + usage: what the Keys screen and the Home card show")
        reset_world()
        a_g, a_m = GK("dan"), MK("dan")
        WORLD.on("groq", a_g, ok("OK", headers=hdr), kind="chat")
        await save("dan", "groq", a_g)
        await save("dan", "gemini", a_m)
        WORLD.on("groq", a_g, ok('{"pass": true}', headers={"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14380", "x-ratelimit-reset-requests": "1m0s"}), kind="chat")
        ledger._seen.clear()
        for _ in range(3):
            r = await req("dan", "POST", "/lesson/evaluate", {"token": T["dan"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
            check("a real LLM-backed endpoint answers through the per-key walker with the STORED keys (the body carries no keys at all)", r.status_code == 200, r.text)
        st = (await api("dan", "GET", "/status")).json()
        g = st["keys"][0]
        check("status: Groq has used 1 (the check) + 3 (real) = 4 requests today, all ok", g["used_today"]["requests"] == 4 and g["used_today"]["ok"] == 4, g["used_today"])
        check("status: the allowance is the provider's latest exact number (the first real call wrote it; later ones inside a minute do not rewrite)", g["allowance"]["kind"] == "exact" and g["allowance"]["left"] in (14380, 14399), g["allowance"])
        check("status: Gemini used 1 (its check) and the total adds up", st["keys"][1]["used_today"]["requests"] == 1 and st["used_today"] == 5 and st["working"] == 2 and st["limited"] == 0 and st["invalid"] == 0 and st["now"] > 1_700_000_000, st)
        check("status carries no key text anywhere", all(s_ not in json.dumps(st) for s_ in SECRET))
        n_chat = len(WORLD.calls_for("groq", a_g, "chat"))
        check("the walker used Groq (first in the chain) for those 3 turns", n_chat == 4, n_chat)
        ledger_rows = await rows(KM.KhUsage, KM.KhUsage.user_id == uid("dan"))
        check("kh_usage rows are keyed by the PROVIDER's quota day and the key fingerprint", {(x.provider, x.fp) for x in ledger_rows} == {("groq", gate.fingerprint("groq", a_g)), ("gemini", gate.fingerprint("gemini", a_m))}
              and all(x.day == classify.quota_day(x.provider, time.time()) for x in ledger_rows), [(x.provider, x.day) for x in ledger_rows])

        # -------------------------------------------------------------- stored keys first
        section("precedence: the keys the learner SAVED win; a browser-sent key only fills a provider with nothing stored")
        reset_world()
        s_g, s_m = GK("eve"), MK("eve")
        await save("eve", "groq", s_g)
        await save("eve", "gemini", s_m)
        browser_g, browser_o = GK("eve", 4), OK_("eve", 4)
        n0 = len(WORLD.calls)
        await req("eve", "POST", "/lesson/evaluate", {"token": T["eve"], "keys": {"groq": browser_g, "openrouter": browser_o}, "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
        used = [x[1] for x in WORLD.calls[n0:] if x[2] == "chat"]
        check("a stale key in the browser does NOT beat the stored one (a key replaced on phone A used to look 'invalid' on phone B)", used == [s_g], used)
        WORLD.on("groq", s_g, err(429, GROQ_429_PLAIN), kind="chat")
        WORLD.on("gemini", s_m, err(429, GEMINI_429_DAY), kind="chat")
        n0 = len(WORLD.calls)
        r = await req("eve", "POST", "/lesson/evaluate", {"token": T["eve"], "keys": {"openrouter": browser_o}, "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
        used = [x[1] for x in WORLD.calls[n0:] if x[2] == "chat"]
        check("a browser key fills a provider with nothing stored (OpenRouter answers when both stored keys are limited)", r.status_code == 200 and used[-1] == browser_o, (r.status_code, used))
        r = await req("fay", "POST", "/lesson/evaluate", {"token": T["fay"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
        check("a learner with no stored keys and none in the browser is told keys_required (402) - never served from DuSu's keys", r.status_code == 402 and r.json()["detail"] == "keys_required", (r.status_code, r.text))
        await set_mode(key_health="off")
        reset_world()
        legacy_stored, legacy_browser = GK("gus"), GK("gus", 3)
        await db.save_user_keys(uid("gus"), {"groq": legacy_stored, "gemini": MK("gus")}, verified=True)
        n0 = len(WORLD.calls)
        await req("gus", "POST", "/lesson/evaluate", {"token": T["gus"], "keys": {"groq": legacy_browser}, "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"})
        used = [x[1] for x in WORLD.calls[n0:] if x[2] == "chat"]
        check("engine OFF for that learner: today's precedence (the browser key wins) and today's walker - nothing changes until the switch is on", used and used[0] == legacy_browser, used)
        check("... and the engine-off path counted nothing", not [x for x in ledger._usage if x[0] == uid("gus")])
        await set_mode(key_health="on")

        # -------------------------------------------------------------- what a learner is told
        section("failures: the exact reason, in the HTTP body, beside the unchanged `detail`")
        reset_world()
        h_g, h_m = GK("hal"), MK("hal")
        await save("hal", "groq", h_g)
        await save("hal", "gemini", h_m)
        BODY = {"token": T["hal"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"}
        WORLD.on("groq", h_g, err(429, GROQ_429_TPD), kind="chat")
        WORLD.on("gemini", h_m, err(429, GEMINI_429_DAY), kind="chat")
        r = await req("hal", "POST", "/lesson/evaluate", BODY)
        j = r.json()
        check("every key limited: 429 with the OLD detail 'quota' AND kp {state all_limited, per-key kind + reset}", r.status_code == 429 and j["detail"] == "quota" and j["kp"]["state"] == "all_limited"
              and [k["provider"] for k in j["kp"]["keys"]] == ["groq", "gemini"] and j["kp"]["keys"][0]["reset_at"] and j["kp"]["now"] > 1_700_000_000, j)
        check("... kp carries no key text and no provider error text", all(s_ not in r.text for s_ in SECRET) and "Rate limit reached" not in r.text and "RESOURCE_EXHAUSTED" not in r.text)
        n0 = len(WORLD.calls)
        r = await req("hal", "POST", "/lesson/evaluate", BODY)
        check("... asked again: the same answer at once, with nothing sent to any provider", r.status_code == 429 and len(WORLD.calls) == n0 and r.json()["kp"]["state"] == "all_limited", (r.status_code, len(WORLD.calls) - n0))
        r = await req("hal", "POST", "/leveltest/gen", {"token": T["hal"]})
        check("a site that always tested for quota (the level check): 429 quota + kp", r.status_code == 429 and r.json()["detail"] == "quota" and r.json()["kp"]["state"] == "all_limited", (r.status_code, r.text))
        reset_world()
        WORLD.on("groq", h_g, err(401, GROQ_401), kind="chat")
        WORLD.on("gemini", h_m, err(400, GEMINI_400_KEY), kind="chat")
        r = await req("hal", "POST", "/lesson/evaluate", BODY)
        j = r.json()
        check("every key rejected: 429 quota + kp all_invalid (a site that never tested for quota now says why)", r.status_code == 429 and j["detail"] == "quota" and j["kp"]["state"] == "all_invalid"
              and all(k["kind"] == "invalid" for k in j["kp"]["keys"]), (r.status_code, j))
        st = (await api("hal", "GET", "/status")).json()
        check("... and the Keys screen now shows both as rejected, the state as all_invalid", st["state"] == "all_invalid" and st["invalid"] == 2 and all(k["status"] == "invalid" for k in st["keys"]), st["state"])
        me = (await req("hal", "GET", "/me")).json()
        check("... /me carries the same counts for the Home card", me["keys"]["state"] == "all_invalid" and me["keys"]["invalid"] == 2 and me["keys"]["working"] == 0, me.get("keys"))
        reset_world()
        WORLD.on("groq", h_g, err(503, {"error": {"message": "boom"}}), kind="chat")
        WORLD.on("gemini", h_m, err(503, GEMINI_503), kind="chat")
        gate.reset_all()
        r = await req("hal", "POST", "/lesson/evaluate", BODY, expect5xx=True)
        j = r.json()
        check("provider trouble: the site's OWN status and detail (502) + kp 'transient' - 'your keys are fine'", r.status_code == 502 and j["kp"]["state"] == "transient" and "kp" in j and "evaluate" in str(j["detail"]).lower(), (r.status_code, j))
        reset_world()
        WORLD.on("groq", h_g, err(429, GROQ_429_TPD), kind="chat")
        WORLD.on("gemini", h_m, ok('{"pass": true}'), kind="chat")
        gate.reset_all()
        r = await req("hal", "POST", "/lesson/evaluate", BODY)
        check("ONE key limited, the other works: the learner is served (200) - the walker fell through", r.status_code == 200, r.text)
        st = (await api("hal", "GET", "/status")).json()
        check("... and the screen shows 'degraded': one working, one limited, with the provider's reset", st["state"] == "degraded" and st["working"] == 1 and st["limited"] == 1 and st["next_reset_at"], st["state"])
        reset_world()
        k_bob_g, k_bob_m = GK("bob"), MK("bob")
        await db.save_user_keys(uid("bob"), {"groq": k_bob_g, "gemini": k_bob_m}, verified=True)
        await set_mode(key_health="off")
        WORLD.on("groq", k_bob_g, err(429, GROQ_429_TPD), kind="chat")
        WORLD.on("gemini", k_bob_m, err(429, GEMINI_429_DAY), kind="chat")
        r = await req("bob", "POST", "/lesson/evaluate", {"token": T["bob"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"}, expect5xx=True)
        check("a learner WITHOUT the switch: exactly today's answer (502, no kp)", r.status_code == 502 and "kp" not in r.json(), (r.status_code, r.text))
        r = await req("bob", "POST", "/leveltest/gen", {"token": T["bob"]})
        check("... and today's 429 quota with no kp on the site that tested for it", r.status_code == 429 and r.json() == {"detail": "quota"}, (r.status_code, r.text))
        await set_mode(key_health="on")

        # -------------------------------------------------------------- /me
        section("/me: flags, counts, strict has_keys")
        await set_mode(install_mode="on")
        me = (await req("max", "GET", "/me")).json()
        check("a learner with no stored keys: key_health on, a `keys` block with zeros and state no_keys", me["key_health"] is True and me["keys"]["state"] == "no_keys" and me["keys"]["stored"] == 0 and me["has_keys"] is False, me.get("keys"))
        await db.save_user_keys(uid("max"), {"groq": GK("max"), "github": "ghp_" + "H" * 36}, verified=True)
        me = (await req("max", "GET", "/me")).json()
        check("a legacy blob of {groq, github}: the engine counts only real providers - ONE key, so has_keys is false (a fake 'OK' GitHub token no longer counts as a second key)", me["has_keys"] is False and me["keys"]["stored"] == 1, (me["has_keys"], me.get("keys")))
        await set_mode(key_health="off")
        me = (await req("max", "GET", "/me")).json()
        check("... with the engine OFF the old rule applies unchanged (two entries = set up)", me["has_keys"] is True and "keys" not in me, (me["has_keys"], me.get("keys")))
        await set_mode(key_health="on")
        check("owner on the server's own keys: no `keys` block (nothing of theirs to show)", "keys" not in (await req("owner", "GET", "/me")).json())
        check("the install flag follows its own switch", (await req("max", "GET", "/me")).json()["install_app"] is True)

        # -------------------------------------------------------------- legacy /keys/verify
        section("the older /keys/verify: replace-all without the engine, merge with it")
        reset_world()
        await set_mode(key_health="off")
        v_g, v_m = GK("ida"), MK("ida")
        r = await req("ida", "POST", "/keys/verify", {"keys": {"groq": v_g, "gemini": v_m}})
        j = r.json()
        check("engine OFF: unchanged - both pass, saved true, both stored", r.status_code == 200 and j["saved"] is True and (await stored("ida")) == {"groq": v_g, "gemini": v_m}, r.text)
        r = await req("ida", "POST", "/keys/verify", {"keys": {}})
        check("engine OFF: an empty request still replaces everything (the old behaviour is pinned)", await stored("ida") == {} and r.json()["saved"] is False)
        await set_mode(key_health="on")
        r = await req("ida", "POST", "/keys/verify", {"keys": {"groq": v_g, "gemini": v_m}})
        check("engine ON: both pass -> saved true and both stored", r.json()["saved"] is True and await stored("ida") == {"groq": v_g, "gemini": v_m})
        r = await req("ida", "POST", "/keys/verify", {"keys": {"groq": ""}})
        check("engine ON: an empty box does not wipe the set", await stored("ida") == {"groq": v_g, "gemini": v_m} and r.json()["saved"] is True)
        bad_g = GK("ida", 3)
        WORLD.on("groq", bad_g, err(401, GROQ_401), kind="chat")
        r = await req("ida", "POST", "/keys/verify", {"keys": {"groq": bad_g, "gemini": v_m}})
        j = r.json()
        check("engine ON: a key that fails is NOT stored and does not replace the good one; `saved` still reports the merged set", j["results"]["groq"]["ok"] is False and (await stored("ida"))["groq"] == v_g and j["saved"] is True, j)
        r = await req("ida", "POST", "/keys/verify", {"keys": {"groq": v_g, "github": "ghp_" + "x" * 36}})
        check("a github key in the request is ignored (not verified, not stored)", "github" not in r.json()["results"] and "github" not in await stored("ida"))

        # -------------------------------------------------------------- recheck / remove
        section("re-check and remove")
        reset_world()
        r_g, r_m = GK("jon"), MK("jon")
        await save("jon", "groq", r_g)
        await save("jon", "gemini", r_m)
        WORLD.on("groq", r_g, err(401, GROQ_401), kind="models")
        n_chat = len(WORLD.calls_for(kind="chat"))
        r = await api("jon", "POST", "/recheck", {})
        st = r.json()
        check("a shallow re-check is the zero-quota auth probe only (no chat call) and finds the rejected key", st["checked"]["groq"] == "invalid" and st["keys"][0]["status"] == "invalid" and len(WORLD.calls_for(kind="chat")) == n_chat, st.get("checked"))
        check("... and the gate now skips it (a walk would not even try)", gate.get("groq", gate.fingerprint("groq", r_g)).status == "invalid")
        WORLD.on("groq", r_g, ok("OK"), kind="models")
        r = await api("jon", "POST", "/recheck", {"provider": "groq"})
        check("a key the provider accepts again comes back to 'ok' and the gate forgets (the learner re-enabled it)", r.json()["keys"][0]["status"] == "ok" and gate.get("groq", gate.fingerprint("groq", r_g)) is None, r.json()["keys"][0])
        WORLD.on("gemini", r_m, err(429, GEMINI_429_DAY), kind="chat")
        r = await api("jon", "POST", "/recheck", {"provider": "gemini", "deep": True})
        check("'Test' (deep) makes ONE real call and finds a limit", r.json()["keys"][1]["status"] == "limited", r.json()["keys"][1])
        r = await api("jon", "POST", "/recheck", {"provider": "gemini"})
        check("a shallow check does NOT clear a limit - the key being real does not mean the limit ended", r.json()["keys"][1]["status"] == "limited")
        WORLD.on("openrouter", OK_("jon"), ok("OK"), kind="key")
        r = await api("jon", "POST", "/recheck", {"provider": "openrouter"})
        check("re-checking a provider the learner has no key for is a no-op, not an error", r.status_code == 200 and r.json()["checked"] == {})
        r = await api("jon", "POST", "/recheck", {"provider": "github"})
        check("re-check with an unknown provider is 422", r.status_code == 422)
        keys_api._hits.clear()
        codes = [(await api("jon", "POST", "/recheck", {}, keep=True)).status_code for _ in range(6)]
        check("re-check is rate limited (4 a minute) with 'slow_down'", codes[:4] == [200] * 4 and codes[4:] == [429] * 2, codes)
        r = await api("jon", "POST", "/remove", {"provider": "gemini"})
        st = r.json()
        check("remove: the key is gone from the blob, the status row is gone, and the answer lists only what is left", [k["provider"] for k in st["keys"]] == ["groq"] and "gemini" not in await stored("jon")
              and not await rows(KM.KhStatus, KM.KhStatus.user_id == uid("jon"), KM.KhStatus.provider == "gemini"), st)
        check("... removing a key leaves has_keys false (one key left), and removing a key that is not there is a no-op", not await db.has_user_keys(uid("jon")) and (await api("jon", "POST", "/remove", {"provider": "openrouter"})).status_code == 200)
        r = await api("jon", "POST", "/remove", {"provider": "bogus"})
        check("remove with an unknown provider is 422", r.status_code == 422)

        # -------------------------------------------------------------- the ledger
        section("the ledger: rows == requests, a cancelled attempt counts, a deleted learner's rows are dropped")
        reset_world()
        ledger.reset_all()
        l_g = GK("kim")
        await db.save_user_keys(uid("kim"), {"groq": l_g, "gemini": MK("kim")}, verified=True)
        WORLD.on("groq", l_g, R(200, completion('{"pass": true}'), delay=0.05), kind="chat")
        ok_n = 7
        res = await asyncio.gather(*[req("kim", "POST", "/lesson/evaluate", {"token": T["kim"], "lang": "en", "type": "speak", "prompt": "p", "target": "t", "said": "s"}) for _ in range(ok_n)])
        op.set_active_keys({"groq": l_g}, uid=uid("kim"), engine=True)
        WORLD.on("groq", l_g, R(200, completion("late"), delay=5.0), kind="chat")
        t = asyncio.ensure_future(op._complete([{"role": "user", "content": "hi"}], 20))
        await asyncio.sleep(0.2)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        await ledger.flush()
        got = await rows(KM.KhUsage, KM.KhUsage.user_id == uid("kim"), KM.KhUsage.provider == "groq")
        sent = len(WORLD.calls_for("groq", l_g, "chat"))
        check("rows == requests: every request that reached the provider is in kh_usage, the cancelled one included", sum(x.requests for x in got) == sent == ok_n + 1 and sum(x.ok for x in got) == ok_n and sum(x.other for x in got) == 1,
              ([(x.requests, x.ok, x.other) for x in got], sent))
        check("... with tokens for the answers that returned them", sum(x.tokens_in for x in got) == 5 * ok_n and sum(x.tokens_out for x in got) == 3 * ok_n, [(x.tokens_in, x.tokens_out) for x in got])
        ledger.reset_all()
        ghost = "u-ghost-never-existed"
        ledger._usage[(ghost, "2026-10-27", "groq", "ffffffffffff")] = {"requests": 3, "ok": 3, "limited": 0, "invalid": 0, "other": 0, "tokens_in": 0, "tokens_out": 0}
        ledger._usage[(uid("kim"), classify.quota_day("groq", time.time()), "groq", gate.fingerprint("groq", l_g))] = {"requests": 5, "ok": 5, "limited": 0, "invalid": 0, "other": 0, "tokens_in": 0, "tokens_out": 0}
        before = sum(x.requests for x in await rows(KM.KhUsage, KM.KhUsage.user_id == uid("kim")))
        d0 = ledger.state["dropped"]
        await ledger.flush()
        after = sum(x.requests for x in await rows(KM.KhUsage, KM.KhUsage.user_id == uid("kim")))
        check("a row for a learner who no longer exists is DROPPED (counted) and does not stop the real learner's row from being written", after == before + 5 and ledger.state["dropped"] == d0 + 1 and not ledger._usage, (before, after, ledger.state))
        ledger.reset_all()
        ledger._usage[(uid("kim"), classify.quota_day("groq", time.time()), "groq", gate.fingerprint("groq", l_g))] = {"requests": 4, "ok": 4, "limited": 0, "invalid": 0, "other": 0, "tokens_in": 0, "tokens_out": 0}
        real_session = db._Session
        state_ = {"n": 0}

        class Flaky:
            def __call__(self, *a, **k):
                state_["n"] += 1
                if state_["n"] == 1:
                    raise OperationalError("insert", {}, Exception("connection lost"))
                return real_session(*a, **k)

        db._Session = Flaky()
        await ledger.flush()
        db._Session = real_session
        check("a database hiccup puts the counts BACK (they are real), and the next flush writes them", len(ledger._usage) == 1 and ledger.state["requeued"] >= 1, (len(ledger._usage), ledger.state))
        before = sum(x.requests for x in await rows(KM.KhUsage, KM.KhUsage.user_id == uid("kim")))
        await ledger.flush()
        after = sum(x.requests for x in await rows(KM.KhUsage, KM.KhUsage.user_id == uid("kim")))
        check("... exactly once", after == before + 4 and not ledger._usage, (before, after))
        gone = await ledger.prune(time.time() + 200 * 86400)
        check("prune: usage older than 90 days goes (here: everything, 200 days on)", gone >= 1 and await count(KM.KhUsage, KM.KhUsage.user_id == uid("kim")) == 0, gone)

        # -------------------------------------------------------------- lazy background re-check
        section("a legacy key nobody has looked at: the status screen schedules a background re-check")
        reset_world()
        svc.schedule_recheck = lambda u: None
        lz_g, lz_m = GK("lee"), MK("lee")
        await db.save_user_keys(uid("lee"), {"groq": lz_g, "gemini": lz_m}, verified=True)
        called = []
        svc.schedule_recheck = lambda u: called.append(u)
        st = (await api("lee", "GET", "/status")).json()
        check("a stored key with no status row is 'unknown' (never shown as working before it was looked at) ...", st["state"] == "unknown" and all(k["status"] == "unknown" for k in st["keys"]), st["state"])
        check("... and the screen asks for a background re-check of it", called == [uid("lee")], called)
        real_uniform, svc.random.uniform = svc.random.uniform, (lambda a, b: 0.0)
        WORLD.on("groq", lz_g, err(401, GROQ_401), kind="models")
        n_chat = len(WORLD.calls_for(kind="chat"))
        await svc._bg_recheck(uid("lee"))
        svc.random.uniform = real_uniform
        st = (await api("lee", "GET", "/status")).json()
        check("the background pass looked at both with the zero-quota probe: Groq rejected, Gemini fine", st["keys"][0]["status"] == "invalid" and st["keys"][1]["status"] == "ok" and st["state"] == "degraded"
              and len(WORLD.calls_for(kind="chat")) == n_chat, st["keys"])
        called.clear()
        st = (await api("lee", "GET", "/status")).json()
        check("a key looked at a moment ago is not looked at again", called == [], called)
        svc._last_sched.clear()
        svc.schedule_recheck = lambda u: None

        # -------------------------------------------------------------- data rights
        section("data rights: export has no key text; account deletion and the owner's wipe remove every row")
        r = await api("lee", "GET", "/export")
        j = r.json()
        check("export: statuses and usage, no key text, says so", r.status_code == 200 and j["keys"] and "sealed" in j["note"] and all(s_ not in r.text for s_ in SECRET), j)
        await save("tes", "groq", GK("tes"))
        await save("tes", "gemini", MK("tes"))
        await save("uni", "groq", GK("uni"))
        await ledger.flush()
        check("the learners have key rows before deletion", await count(KM.KhStatus, KM.KhStatus.user_id == uid("tes")) == 2 and await count(KM.KhUsage, KM.KhUsage.user_id == uid("tes")) >= 1)
        ledger.note_ok(uid("tes"), "groq", "abcdef012345", time.time())
        ledger.begin(uid("tes"), "groq", "abcdef012345")
        await db.delete_user(uid("tes"))
        check("delete_user removes the learner's key-health rows, their stored keys, and anything still pending in memory", await count(KM.KhStatus, KM.KhStatus.user_id == uid("tes")) == 0
              and await count(KM.KhUsage, KM.KhUsage.user_id == uid("tes")) == 0 and not await db.get_user_keys(uid("tes")) and not [k for k in ledger._usage if k[0] == uid("tes")])
        n = await db.admin_wipe_users({"david123rana@gmail.com"})
        check("the owner's wipe removes every learner's key-health rows too (a foreign key would otherwise block it)", n >= 1 and await count(KM.KhStatus, KM.KhStatus.user_id == uid("uni")) == 0 and await count(KM.KhUsage) == 0)
        for u in users.values():
            await db.login(u)
        await db.login(owner)

        # -------------------------------------------------------------- /health and the dashboard
        section("/health and the owner dashboard")
        from app.config import settings
        reset_world()
        op._cooldown.clear()
        settings.groq_api_key, settings.gemini_api_key = "gsk_SERVER" + "q" * 30, "AIzaSERVER" + "q" * 30
        probe.reset_server_health()
        n0 = len(WORLD.calls)
        h = (await c.get("/health")).json()
        check("/health never probes on a request (constant time) and says the server keys are unknown until the first probe", h["ok"] is True and len(WORLD.calls) == n0 and h["server_keys"] == {}, h)
        WORLD.on("groq", settings.groq_api_key, err(401, GROQ_401), kind="models")
        res = await probe.refresh_server_health()
        check("the zero-quota probe of OUR keys flags the dead Groq key and keeps the working one", res["groq"]["status"] == "invalid" and res["gemini"]["status"] == "ok", res)
        h = (await c.get("/health")).json()
        check("/health reports it - ok stays true (a dead key must not take the container down) and `usable` leaves the dead provider out", h["ok"] is True and h["server_keys"]["groq"] == "invalid" and h["usable"] == ["gemini"] and "groq" in h["providers"], h)
        # ---- early warning: a model id DuSu is configured to use that the provider no longer lists (zero quota; advisory only)
        settings.openrouter_api_key = "sk-or-v1-SERVER" + "q" * 30
        reset_world()
        probe.reset_server_health()
        WORLD.on("openrouter", "", R(200, {"data": [{"id": "google/gemma-4-26b-a4b-it:free"}, {"id": "nvidia/nemotron-3-ultra-550b-a55b:free"}]}), kind="models")     # OpenRouter's list is public: asked with no key
        WORLD.on("gemini", settings.gemini_api_key, R(200, {"data": [{"id": "models/gemini-2.5-flash"}]}), kind="models")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = await probe.refresh_server_health()
            await probe.refresh_server_health()
        check("the probe notices a configured model the provider no longer lists (OpenRouter's free list lost google/gemma-4-31b-it:free)", res["openrouter"].get("models_missing") == ["google/gemma-4-31b-it:free"], res)
        check("... but never judges an alias ('gemini-flash-lite-latest' is not listed under that name and still answers)", "models_missing" not in res["gemini"], res["gemini"])
        check("... and says it ONCE in the log, by name, with no key text (a second probe the same day stays quiet)", buf.getvalue().count("openrouter/google/gemma-4-31b-it:free") == 1 and "sk-or" not in buf.getvalue(), buf.getvalue())
        h = (await c.get("/health")).json()
        check("/health shows it (advisory: ok stays true, `usable` is unchanged)", h["ok"] is True and h["models_missing"] == {"openrouter": ["google/gemma-4-31b-it:free"]} and "openrouter" in h["usable"], h)
        probe.reset_server_health()
        WORLD.on("openrouter", "", R(200, {"data": []}), kind="models")
        res = await probe.refresh_server_health()
        check("an EMPTY or unreadable list is 'don't know', never 'every model is gone'", "models_missing" not in res["openrouter"], res)
        probe.reset_server_health()
        WORLD.on("openrouter", "", R(200, {"data": [{"id": "google/gemma-4-31b-it:free"}, {"id": "google/gemma-4-26b-a4b-it:free"}]}), kind="models")
        res = await probe.refresh_server_health()
        check("both configured models are listed again: the warning is gone", "models_missing" not in res["openrouter"], res)
        gate.mark_model_gone("groq", gate.fingerprint("groq", settings.groq_api_key), "openai/gpt-oss-120b", time.time())
        h = (await c.get("/health")).json()
        check("/health names a model the walker was told does not exist (for DuSu's OWN keys only)", h["models_gone"] == ["groq/openai/gpt-oss-120b"], h.get("models_gone"))
        gate.mark_model_gone("groq", gate.fingerprint("groq", "gsk_someone_elses_own_key_000000000000"), "openai/gpt-oss-20b", time.time())
        h = (await c.get("/health")).json()
        check("... a learner's own key never shows up there", h["models_gone"] == ["groq/openai/gpt-oss-120b"], h.get("models_gone"))
        # ---- a key that LISTS models but cannot CHAT (30 Oct 2026: Google answered 403 "The Gemini API free tier is not available for this project" to every chat call while
        #      GET /models said ok, so /health said ok and every learner on DuSu's own keys was told "AI busy")
        reset_world()
        probe.reset_server_health()
        GEM403 = [{"error": {"code": 403, "message": "The Gemini API free tier is not available for this project. To use the Gemini API, please set up billing to upgrade to the paid tier.", "status": "PERMISSION_DENIED"}}]
        WORLD.on("groq", settings.groq_api_key, err(401, GROQ_401), kind="models")                   # Groq's key is dead (rejected at the zero-quota list)
        WORLD.on("gemini", settings.gemini_api_key, err(403, GEM403), kind="chat")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = await probe.refresh_server_health()
        check("a server key that LISTS models but is refused every chat call is reported as forbidden, not ok", res["gemini"]["status"] == "forbidden" and res["gemini"]["chat"] == "forbidden" and res["gemini"]["http"] == 403, res["gemini"])
        h = (await c.get("/health")).json()
        check("/health shows it, and `usable` leaves that provider out", h["server_keys"]["gemini"] == "forbidden" and "gemini" not in h["usable"] and h["ok"] is True, h)
        check("the provider's OWN sentence is kept for the owner (Groq: 'Invalid API Key'; Google: 'free tier is not available for this project')", res["groq"].get("why") == "Invalid API Key" and "free tier is not available for this project" in res["gemini"].get("why", ""), res)
        check("... /health, which anyone can read, never carries it", "free tier" not in json.dumps(h) and "Invalid API Key" not in json.dumps(h) and "why" not in json.dumps(h), h)
        ov = (await req("owner", "GET", "/admin/overview")).json()
        check("... the owner's dashboard does", "free tier is not available" in ov["server_keys"]["gemini"].get("why", "") and ov["server_keys"]["groq"].get("why") == "Invalid API Key", ov["server_keys"])
        check("the log says it ONCE, by provider, with no key and nothing the provider wrote", buf.getvalue().count("gemini key lists models but is refused every chat call") == 1 and "AIza" not in buf.getvalue() and "billing" not in buf.getvalue(), buf.getvalue())
        n_chat = len(WORLD.calls_for("gemini", kind="chat"))
        await probe.refresh_server_health()
        check("the real call is made at most once an hour per provider (a second probe right away sends nothing)", len(WORLD.calls_for("gemini", kind="chat")) == n_chat and n_chat == 1, n_chat)
        check("OpenRouter is never chat-probed (its free pool is only 50 requests a day) and a dead Groq key is not asked to chat", not WORLD.calls_for("openrouter", kind="chat") and not WORLD.calls_for("groq", kind="chat"))
        probe._server_chat["gemini"]["at"] -= 4000                                  # an hour later the key still cannot chat
        await probe.refresh_server_health()
        check("an hour later it is asked again", len(WORLD.calls_for("gemini", kind="chat")) == n_chat + 1)
        WORLD.on("gemini", settings.gemini_api_key, err(503, GEMINI_503), kind="chat")
        probe._server_chat["gemini"]["at"] -= 4000
        res = await probe.refresh_server_health()
        check("a passing failure (503) is NOT a verdict: the status goes back to ok", res["gemini"]["status"] == "ok" and "chat" not in res["gemini"], res["gemini"])
        WORLD.on("gemini", settings.gemini_api_key, err(429, GEMINI_429_DAY), kind="chat")
        probe._server_chat["gemini"]["at"] -= 4000
        res = await probe.refresh_server_health()
        check("... and neither is a limit that ends by itself", res["gemini"]["status"] == "ok", res["gemini"])
        gate.reset_all()
        settings.openrouter_api_key = ""
        reset_world()
        probe.reset_server_health()
        WORLD.on("groq", settings.groq_api_key, err(401, GROQ_401), kind="models")
        await probe.refresh_server_health()

        ov = (await req("owner", "GET", "/admin/overview")).json()
        check("the dashboard carries the three new switches, the WhatsApp link, the server-key health and the ledger's own health", ov["key_health"] == "on" and ov["keys_ui"] == "on" and ov["install_mode"] == "on"
              and ov["server_keys"]["groq"]["status"] == "invalid" and "pending_usage" in ov["keys_health"] and ov["whatsapp_group"] == "", {k: ov.get(k) for k in ("key_health", "keys_ui", "install_mode", "server_keys")})
        r = await req("owner", "POST", "/admin/settings", {"key_health": "owner", "keys_ui": "off", "install_mode": "owner"})
        check("the dashboard switches are written and read back", r.json()["key_health"] == "owner" and r.json()["keys_ui"] == "off" and r.json()["install_mode"] == "owner", r.text)
        r = await req("owner", "POST", "/admin/settings", {"key_health": "banana"})
        check("an unknown switch value falls back to 'off' (the safe side)", r.json()["key_health"] == "off")
        await set_mode(key_health="on", keys_ui="on", install_mode="on")
        r = await req("owner", "POST", "/admin/settings", {"whatsapp_group": "https://chat.whatsapp.com/TestInviteCode0123456789?s=sh&p=a&mlu=4"})
        check("the WhatsApp invite is validated and its tracking parameters stripped", r.json()["whatsapp_group"] == "https://chat.whatsapp.com/TestInviteCode0123456789", r.text)
        me = (await req("max", "GET", "/me")).json()
        check("/me serves it (as `community`) only while the install switch is on for the learner", me.get("community") == {"whatsapp": "https://chat.whatsapp.com/TestInviteCode0123456789"}, me.get("community"))
        r = await req("owner", "POST", "/admin/settings", {"whatsapp_group": "https://evil.example.com/x"})
        check("a link that is not a WhatsApp invite is refused (400) and the saved one is kept", r.status_code == 400 and await M.whatsapp_link() == "https://chat.whatsapp.com/TestInviteCode0123456789", r.text)
        await set_mode(install_mode="off")
        me = (await req("max", "GET", "/me")).json()
        check("switch OFF: no `community` in /me", "community" not in me and me["install_app"] is False)
        await set_mode(install_mode="on")
        r = await req("max", "POST", "/admin/settings", {"key_health": "on"})
        check("only the owner can flip them", r.status_code == 403, r.status_code)
        r = await req("owner", "POST", "/admin/settings", {"whatsapp_group": ""})
        check("the owner can clear the link", r.json()["whatsapp_group"] == "" and await M.whatsapp_link() == "")
        settings.groq_api_key = settings.gemini_api_key = ""

        # -------------------------------------------------------------- grammar's question
        section("Grammar Coach's 'is anything cooling?' asks about THIS learner's keys")
        from app.grammar import budget as B
        gate.reset_all()
        op._cooldown.clear()
        sk_g, sk_m = GK("sim"), MK("sim")
        op.set_active_keys({"groq": sk_g, "gemini": sk_m}, uid=uid("sim"), engine=True)
        check("nothing limited: not cooling", B.cooling() == [])
        gate.mark_limited("gemini", gate.fingerprint("gemini", sk_m), time.time(), 90)
        check("a limited key in the learner's own chain: cooling", B.cooling() == ["gemini"], B.cooling())
        gate.reset_all()
        gate.mark_invalid("groq", gate.fingerprint("groq", sk_g), time.time())
        check("a REJECTED key is not 'busy': Grammar Coach keeps working", B.cooling() == [])
        gate.reset_all()
        gate.mark_limited("groq", gate.fingerprint("groq", "someone-elses-key"), time.time(), 90)
        check("another learner's limited key is not THIS learner's problem", B.cooling() == [])
        gate.reset_all()
        op._cooldown["groq"] = time.time() + 60
        op.set_active_keys({"groq": sk_g}, uid=uid("sim"), engine=False)
        check("with the engine off it is today's process-wide map, unchanged", B.cooling() == ["groq"])
        op._cooldown.clear()


        # -------------------------------------------------------------- the two small additions to Notifications
        section("notifications: `this_device` and the journey of a test notification")
        from app.notify import models as NMo
        from app.planner import service as plsvc
        import datetime as _dt
        await set_mode(notifications="on")
        ep = "https://fcm.googleapis.com/fcm/send/ky-test-endpoint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        await plsvc.subscribe_push(uid("fay"), {"endpoint": ep, "p256dh": "p" * 87, "auth": "a" * 22}, "test")
        r = await req("fay", "GET", "/notify/prefs")
        check("/notify/prefs without an endpoint is exactly what it was (no `this_device`)", r.status_code == 200 and "this_device" not in r.json() and r.json()["devices"] == 1, r.text)
        r = await req("fay", "GET", "/notify/prefs", params={"endpoint": ep})
        check("with THIS phone's endpoint the server says it holds it", r.json().get("this_device") is True, r.text)
        r = await req("fay", "GET", "/notify/prefs", params={"endpoint": ep + "-other"})
        check("an endpoint the server does not hold: this_device is false (the phone believes it is subscribed, the server dropped it)", r.json().get("this_device") is False and r.json()["devices"] == 1, r.text)
        r = await req("gus", "GET", "/notify/prefs", params={"endpoint": ep})
        check("another learner cannot see that an endpoint is held by someone else (false for them)", r.json().get("this_device") is False, r.text)
        r = await req("fay", "POST", "/notify/test", {})
        tid = r.json().get("id")
        check("a test notification is queued and returns its id", r.status_code == 200 and isinstance(tid, int), r.text)
        r = await req("fay", "GET", f"/notify/test/{tid}")
        check("its journey starts at 'queued'", r.status_code == 200 and r.json()["state"] == "queued" and r.json()["push_state"] == "none", r.text)
        steps = [("sending", dict(status="sending"), "sending"), ("accepted", dict(status="sent", push_state="accepted", sent_at=_dt.datetime.now(_dt.timezone.utc)), "accepted"),
                 ("received", dict(received_at=_dt.datetime.now(_dt.timezone.utc)), "received"), ("opened", dict(opened_at=_dt.datetime.now(_dt.timezone.utc)), "opened")]
        for label, cols, want in steps:
            async with db._Session() as s_:
                from sqlalchemy import update as _upd
                await s_.execute(_upd(NMo.NtOutbox).where(NMo.NtOutbox.id == tid).values(**cols)); await s_.commit()
            r = await req("fay", "GET", f"/notify/test/{tid}")
            check(f"... then '{want}'", r.json()["state"] == want, r.text)
        async with db._Session() as s_:
            await s_.execute(_upd(NMo.NtOutbox).where(NMo.NtOutbox.id == tid).values(status="sent", push_state="failed", received_at=None, opened_at=None)); await s_.commit()
        check("a push service that refused it reads 'failed'", (await req("fay", "GET", f"/notify/test/{tid}")).json()["state"] == "failed")
        async with db._Session() as s_:
            await s_.execute(_upd(NMo.NtOutbox).where(NMo.NtOutbox.id == tid).values(status="cancelled", why="quiet")); await s_.commit()
        r = await req("fay", "GET", f"/notify/test/{tid}")
        check("a cancelled one says why", r.json()["state"] == "cancelled" and r.json()["why"] == "quiet", r.text)
        check("someone else's test is a 404, never a 403 or the data", (await req("gus", "GET", f"/notify/test/{tid}")).status_code == 404)
        async with db._Session() as s_:
            row = NMo.NtOutbox(user_id=uid("fay"), kind="practice", dedupe_key="day:ky", fire_at=_dt.datetime.now(_dt.timezone.utc), status="sent"); s_.add(row); await s_.commit(); rid = row.id
        check("a notification that is not a test is a 404", (await req("fay", "GET", f"/notify/test/{rid}")).status_code == 404)
        check("odd ids are 404 / 422, never a 500", (await req("fay", "GET", "/notify/test/0")).status_code == 404 and (await req("fay", "GET", "/notify/test/99999999999")).status_code == 404
              and (await req("fay", "GET", "/notify/test/abc")).status_code == 422)
        check("no login: 401", (await req(None, "GET", f"/notify/test/{tid}")).status_code == 401)
        await set_mode(notifications="off")
        check("with the Notifications switch off the journey endpoint is invisible too (404)", (await req("fay", "GET", f"/notify/test/{tid}")).status_code == 404)

    check("no 5xx anywhere in the run", not FIVE, FIVE[:5])
    check("no key text in ANY response of the run", not LEAKS, LEAKS[:5])
    logged = TEE.buf.getvalue()
    check("no key text in any log line the app printed", not any(s_ in logged for s_ in SECRET if len(s_) > 12), [s_ for s_ in SECRET if s_ in logged][:3])
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    sys.stdout = TEE.real
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
