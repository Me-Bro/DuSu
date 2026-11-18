"""Keys - tier 1b: the VALIDATED WALK (settings.chain_v3) - the pure logic and the walker, with NO database and NO network.

  A  validators          json_accept / chat_accept: valid object, wrong type, missing field, not JSON, a list, cut off (finish 'length'), numbers as strings, code fences
  B  the gate            a model held back for ONE kind of call: 20 s doubling to 10 min, one good reply clears it, per key, per kind, bounded
  C  the walker          an unusable reply is a failure like any other: the NEXT PROVIDER answers in the same call, siblings follow in a second pass, a held-back model is
                         not asked again, every model held back is still asked (never zero attempts), nothing usable -> BadReplyError (never "your keys")
  D  the engine levels   engine 0 / 1 / 2: the validated walk exists only at 2, and at 1 the walker is exactly what it was
  E  request parameters  Groq's reasoning settings go to per-turn calls only; a model that answers 400 to them is remembered and sent without
  F  the llm helpers     assess / score return the failure shape callers already handle, never a half-parsed object; the save-time probe wants a real answer
  G  input bounds        /level/test/submit's body

Run:  tests/keys/run.sh chain_unit.py
"""

import asyncio
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

from world import World, install, ok, err, timeout, completion, R, GROQ_429_PLAIN, GROQ_401       # noqa: E402

FAILS, N = [], 0


def check(name, cond, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {'' if cond else str(detail)[:400]}")
    if not cond:
        FAILS.append(name)


def section(t):
    print(f"\n== {t}")


from app.keys import classify, gate, ledger, probe          # noqa: E402
from app.keys.errors import BadReplyError, ProviderChainError, engine_kp, is_keys_problem   # noqa: E402
from app.providers import llm                               # noqa: E402
from app.providers import openrouter_provider as op         # noqa: E402

K1, K2, K3 = "gsk_" + "a" * 40 + "9fA2", "AIza" + "b" * 35 + "zZ91", "sk-or-v1-" + "c" * 50 + "Q7xP"
LA = {"groq": K1, "gemini": K2, "openrouter": K3}
LB = {"groq": "gsk_" + "z" * 40 + "BBBB", "gemini": "AIza" + "y" * 35 + "BBBB"}
MSG = [{"role": "user", "content": "hi"}]
G120, G20 = "openai/gpt-oss-120b", "openai/gpt-oss-20b"

GOOD = ok(json.dumps({"reply": "Haan bilkul, chalo shuru karte hain.", "intent": "general_conversation"}))
NOTJSON = ok("Sure! I would love to help you with that, here you go.")
ACCEPT = op.json_accept({"reply": "str+"})


def fresh(keys, uid="uA", engine=2, w=None):
    gate.reset_all(); ledger.reset_all(); op._cooldown.clear(); op._clients.clear(); op._ring.clear(); op._fail_logged.clear()
    world = w or World()
    install(world)
    op.set_active_keys(keys, uid=uid, engine=engine)
    return world


class Pauses:
    def __init__(self):
        self.log = []

    async def __call__(self, secs):
        self.log.append(round(secs, 2))


async def walk(keys, w, uid="uA", engine=2, accept=ACCEPT, cls="json", **kw):
    """One walk with a fake pause -> (text or the exception, the world, the pauses)."""
    world = fresh(keys, uid=uid, engine=engine, w=w)
    pz = Pauses()
    saved, op._pause = op._pause, pz
    try:
        try:
            return await op._complete(MSG, 50, accept=accept, cls=cls, **kw), world, pz.log
        except ProviderChainError as e:
            return e, world, pz.log
    finally:
        op._pause = saved


def usage_of(uid, provider=None):
    out = {"requests": 0, "ok": 0, "limited": 0, "invalid": 0, "other": 0}
    for (u, _day, p, _fp), d in ledger._usage.items():
        if u == uid and (provider is None or p == provider):
            for k in out:
                out[k] += d[k]
    return out


def models(world, provider=None):
    return [c[3] for c in world.calls_for(provider)]


# ============================================================================================ A. validators
section("A. the validators (pure)")
check("a valid object with the field the caller needs is usable", ACCEPT('{"reply": "hello"}', "stop") is None)
check("... inside a code fence, with prose around it (what models do)", ACCEPT('```json\n{"reply": "hello"}\n```', "stop") is None
      and ACCEPT('Here you go: {"reply": "hello"} hope it helps', "stop") is None)
check("plain prose is not JSON", ACCEPT("Sure! Here is my answer.", "stop") == "not_json")
check("a missing field is named", ACCEPT('{"intent": "x"}', "stop") == "missing:reply")
check("a null / empty / wrong-typed field is refused ('str+' = a non-empty string)", ACCEPT('{"reply": null}', "stop") == "missing:reply" and ACCEPT('{"reply": "   "}', "stop") == "bad:reply"
      and ACCEPT('{"reply": 5}', "stop") == "bad:reply" and ACCEPT('{"reply": ["a"]}', "stop") == "bad:reply")
check("a list is never the object (`.get` on it crashed the turn)", ACCEPT('["a", "b"]', "stop") == "not_json" and op._extract_json("[1, 2]").get("error") == "scoring_parse_failed")
check("... a list holding one object yields that object (the repair `_extract_json` always did for text with a { in it)", op._extract_json('[{"reply": "x"}]') == {"reply": "x"})
cut = '{"reply": "Haan bilkul. Aaj ka din bahut accha hai aur main chahti hu ki tum'
check("a reply CUT OFF by the token limit is refused - never trimmed, never half-parsed", ACCEPT(cut, "length") == "truncated" and ACCEPT(cut, "stop") == "not_json")
check("... but a complete object that happened to end exactly at the limit is fine", ACCEPT('{"reply": "ok"}', "length") is None and ACCEPT('```json\n{"reply": "ok"}\n```', "length") is None)
check("json_accept with no fields wants only an object", op.json_accept()('{"a": 1}', "stop") is None and op.json_accept()("nope", "stop") == "not_json")
num = op.json_accept({"score": "num"})
check("'num' takes numbers and numeric strings ('70', '70%', 69.5) - what the scorers always accepted - and refuses words ('eighty') and booleans",
      num('{"score": 70}', "stop") is None and num('{"score": "70"}', "stop") is None and num('{"score": "70%"}', "stop") is None and num('{"score": 69.5}', "stop") is None
      and num('{"score": "eighty"}', "stop") == "bad:score" and num('{"score": true}', "stop") == "bad:score")
check("'bool', 'list' and 'dict' are exact types", op.json_accept({"pass": "bool"})('{"pass": false}', "stop") is None and op.json_accept({"pass": "bool"})('{"pass": "false"}', "stop") == "bad:pass"
      and op.json_accept({"m": "list"})('{"m": []}', "stop") is None and op.json_accept({"m": "dict"})('{"m": []}', "stop") == "bad:m")
check("a rule of the caller's own (check) can refuse a valid object, in a reason of its own", op.json_accept({}, lambda d: None if d.get("x") else "no_x")('{"y": 1}', "stop") == "no_x")
check("chat_accept: prose is usable", op.chat_accept("Hello there.", "stop") is None and op.chat_accept("cut off mid sen", "length") is None)
check("the reasons are OUR words and bounded (nothing a provider wrote can reach a log through them)", all(len(str(r)) <= 40 for r in
      (ACCEPT("x", "stop"), ACCEPT("{}", "stop"), ACCEPT(cut, "length"), op.json_accept({}, lambda d: "z" * 500)("{}", "stop"))))

# ============================================================================================ B. the gate
section("B. the gate: a model held back for one kind of call")
gate.reset_all()
fp = gate.fingerprint("groq", K1)
NOW = 1_800_000_000.0
check("nothing is held against a model nobody has complained about", gate.bad_blocked("groq", fp, G120, "json", NOW) is None)
st = gate.mark_bad("groq", fp, G120, "json", NOW, "not_json")
check("the first strike: held back 20 s", st.strikes == 1 and abs(st.until - (NOW + 20)) < 0.01 and gate.bad_blocked("groq", fp, G120, "json", NOW + 19) is st
      and gate.bad_blocked("groq", fp, G120, "json", NOW + 21) is None)
for i, want in ((2, 40), (3, 80), (4, 160), (5, 320), (6, 600), (7, 600)):
    st = gate.mark_bad("groq", fp, G120, "json", NOW + i, "not_json")
    check(f"strike {i}: held back {want} s (doubling, capped at 10 minutes)", st.strikes == i and abs((st.until - (NOW + i)) - want) < 0.01, (st.strikes, st.until - NOW - i))
check("it is held per KIND of call: the same model may still write prose", gate.bad_blocked("groq", fp, G120, "chat", NOW + 1) is None)
check("... and per model and per key", gate.bad_blocked("groq", fp, G20, "json", NOW + 1) is None and gate.bad_blocked("groq", gate.fingerprint("groq", K1 + "x"), G120, "json", NOW + 1) is None)
gate.bad_ok("groq", fp, G120, "json")
check("one usable reply clears it", gate.bad_get("groq", fp, G120, "json") is None)
gate.mark_bad("groq", fp, G120, "json", NOW, "x")
gate.mark_bad("groq", fp, G120, "json", NOW + gate.BAD_FORGET_S + 10, "x")
check("a model that goes a long time without a new strike starts again from the first", gate.bad_get("groq", fp, G120, "json").strikes == 1)
gate.clear("groq", fp)
check("a key re-added / re-verified forgets what was held against its models", gate.bad_get("groq", fp, G120, "json") is None)
for i in range(gate.MAX_BAD_ENTRIES + 30):
    gate.mark_bad("groq", f"fp{i}", G120, "json", NOW, "x")
check("the map is bounded", len(gate._bad) <= gate.MAX_BAD_ENTRIES + 1, len(gate._bad))
gate.reset_all()
gate.mark_bad("groq", "f1", G120, "json", time.time(), "not_json")
gate.mark_bad("groq", "f2", G120, "json", time.time(), "not_json")
bm = gate.bad_models(time.time())
check("the owner's view counts keys and carries no fingerprint", bm == [{"provider": "groq", "model": G120, "class": "json", "keys": 2, "strikes": 1, "reason": "not_json"}], bm)
gate.mark_param_unsupported("groq", G120, NOW)
check("a model that refused our extra parameters is sent without them for hours - then asked again", gate.param_unsupported("groq", G120, NOW + 3600)
      and not gate.param_unsupported("groq", G120, NOW + gate.PARAM_UNSUPPORTED_S + 1) and not gate.param_unsupported("groq", G20, NOW))
gate.reset_all()
check("reset_all forgets everything", not gate._bad and not gate._noparam)

# ============================================================================================ C. the walker
section("C. the validated walk, against a scripted provider world")


async def t_failover():
    r, w, pz = await walk(LA, World().on("groq", K1, NOTJSON).on("gemini", K2, GOOD))
    check("Groq answers with prose where JSON was needed: the NEXT PROVIDER answers - in the SAME call, no pause", isinstance(r, str) and json.loads(r)["reply"].startswith("Haan")
          and [c[0] for c in w.calls_for()] == ["groq", "gemini"] and pz == [], (r, w.calls, pz))
    check("... Groq's sibling model is not asked while another provider is left to try", models(w, "groq") == [G120], models(w, "groq"))
    fp_ = gate.fingerprint("groq", K1)
    check("... the model that broke the contract is held back for JSON calls (20 s)", gate.bad_blocked("groq", fp_, G120, "json", time.time()) is not None
          and gate.bad_blocked("groq", fp_, G120, "chat", time.time()) is None)
    check("... but NOT the key: it answered, so the key is fine and there is no gate entry", gate.get("groq", fp_) is None)
    u = usage_of("uA", "groq")
    check("the unusable reply still counts as a request that worked (the provider counted it)", u["requests"] == 1 and u["ok"] == 1, u)
    ch = {(r_["provider"], r_["model"], r_["class"]): r_ for r_ in op.chain_health(3600)}
    check("the model-health card sees it: Groq 1 attempt, 1 unusable; Gemini 1 attempt, 1 usable", ch[("groq", G120, "json")]["bad"] == 1 and ch[("groq", G120, "json")]["ok"] == 0
          and ch[("gemini", "gemini-flash-lite-latest", "json")]["ok"] == 1, ch)


async def t_missing_field():
    r, w, _ = await walk(LA, World().on("groq", K1, ok('{"intent": "time_date"}')).on("gemini", K2, GOOD))
    check("valid JSON without the field the caller needs is just as unusable as prose", isinstance(r, str) and [c[0] for c in w.calls_for()] == ["groq", "gemini"])
    check("... and the reason is recorded in our own words", gate.bad_get("groq", gate.fingerprint("groq", K1), G120, "json").reason == "missing:reply")


async def t_all_bad():
    r, w, pz = await walk(LA, World().on("groq", K1, NOTJSON).on("gemini", K2, NOTJSON).on("openrouter", K3, NOTJSON))
    check("nothing usable anywhere: a BadReplyError (a ProviderChainError, so every handler that knew the old one still works)", isinstance(r, BadReplyError) and isinstance(r, ProviderChainError), r)
    check("... after asking every model once: both Groq models, Gemini's, both OpenRouter models (the siblings in a second pass), with NO pause - nothing to wait for",
          sorted(models(w)) == sorted([G120, G20, "gemini-flash-lite-latest", "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"]) and pz == [], (models(w), pz))
    check("... the headline is 'transient' (the AI did not answer properly) - never 'your keys'", r.state == "transient" and not is_keys_problem(r.kp()), r.kp())
    check("... with the reasons, as 'provider/model:reason'", len(r.reasons) == 5 and all(x.endswith(":not_json") for x in r.reasons) and r.reasons[0] == f"groq/{G120}:not_json", r.reasons)
    check("... the message keeps the old wording for every old string check", str(r).startswith("all providers/models unavailable: no usable reply"))
    kp = engine_kp(r)
    check("... kp is the usual one: state transient, own, a short countdown", kp["state"] == "transient" and kp["own"] is True and kp["retry_in"] == 6, kp)
    r2, w2, _ = await walk({"groq": K1}, World().on("groq", K1, NOTJSON), engine=2)
    check("a learner with ONE key and nothing usable gets the same honest failure", isinstance(r2, BadReplyError), r2)
    # on DuSu's own chain the learner is never shown a provider
    saved = op.settings.groq_api_key
    op.settings.groq_api_key = K1
    try:
        fresh(None, uid="uS", engine=2, w=World().on("groq", K1, NOTJSON))
        op.set_active_keys(None, uid="uS", engine=2)
        try:
            await op._complete(MSG, 50, accept=ACCEPT, cls="json")
            check("DuSu's own chain, nothing usable, raises", False)
        except BadReplyError as e:
            k = e.kp()
            check("... on DuSu's own chain the learner's kp carries NO key rows (they cannot fix DuSu's keys)", k["own"] is False and k["keys"] == [] and k["state"] == "transient", k)
    finally:
        op.settings.groq_api_key = saved


async def t_sibling_second_pass():
    r, w, pz = await walk({"groq": K1}, World().on("groq", K1, NOTJSON, GOOD))
    check("one provider, two models: the first is unusable, the SIBLING answers in a second pass (no pause)", isinstance(r, str) and models(w) == [G120, G20] and pz == [], (r, models(w), pz))
    r, w, pz = await walk({"gemini": K2}, World().on("gemini", K2, NOTJSON, GOOD))
    check("a provider with ONE model has no sibling: the failure is final (nothing is asked twice in a row)", isinstance(r, BadReplyError) and len(w.calls_for()) == 1, (r, w.calls))


async def t_held_back():
    w = World().on("groq", K1, NOTJSON, GOOD)
    r, w, _ = await walk({"groq": K1}, w)
    fp_ = gate.fingerprint("groq", K1)
    check("(setup) the first model is held back after its unusable reply", gate.bad_blocked("groq", fp_, G120, "json", time.time()) is not None)
    world = World().on("groq", K1, GOOD)
    install(world)
    r = await op._complete(MSG, 50, accept=ACCEPT, cls="json")
    check("the NEXT call does not ask the held-back model at all - the sibling is asked first", models(world) == [G20], models(world))
    check("... and the held-back model is skipped in the log line's terms too", gate.bad_blocked("groq", fp_, G120, "json", time.time()) is not None)
    gate.bad_get("groq", fp_, G120, "json").until = time.time() - 1                      # its 20 s are up
    world = World().on("groq", K1, GOOD)
    install(world)
    await op._complete(MSG, 50, accept=ACCEPT, cls="json")
    check("when its time is up it is asked again, and one good reply clears it for good", models(world) == [G120] and gate.bad_get("groq", fp_, G120, "json") is None, models(world))
    # held back for JSON, still welcome for prose
    gate.mark_bad("groq", fp_, G120, "json", time.time(), "not_json")
    world = World().on("groq", K1, ok("Hello there, how are you today?"))
    install(world)
    t = await op._complete(MSG, 50, accept=op.chat_accept, cls="chat")
    check("a model held back for JSON is still asked for PROSE", models(world) == [G120] and t.startswith("Hello"), models(world))


async def t_truncation():
    cut_ = '{"reply": "Haan bilkul. Aaj ka din bahut accha hai aur main chahti hu ki tum'
    r, w, _ = await walk(LA, World().on("groq", K1, ok(cut_, finish="length")).on("gemini", K2, GOOD))
    check("a JSON reply cut off at the token limit is NOT trimmed to its last sentence and passed on - the next provider answers", isinstance(r, str) and json.loads(r)["reply"].startswith("Haan bilkul, chalo")
          and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, w.calls))
    check("... and the reason is 'truncated'", gate.bad_get("groq", gate.fingerprint("groq", K1), G120, "json").reason == "truncated")
    r, w, _ = await walk(LA, World().on("groq", K1, ok('{"reply": "ok"}', finish="length")))
    check("a complete object that ended exactly at the limit is accepted", isinstance(r, str) and json.loads(r) == {"reply": "ok"} and len(w.calls_for()) == 1, (r, w.calls))
    r, w, _ = await walk({"groq": K1}, World().on("groq", K1, ok("First sentence is here. Second one is cut of", finish="length")), accept=op.chat_accept, cls="chat")
    check("PROSE that was cut off is still trimmed to its last complete sentence (as it always was)", r == "First sentence is here.", r)
    r, w, _ = await walk({"groq": K1}, World().on("groq", K1, ok('{"reply": "cut', finish="length")), engine=1)
    check("with the validated walk OFF (engine 1) the old behaviour is exactly what it was: a cut reply with no sentence end comes back as it is", r == '{"reply": "cut', r)
    r, w, _ = await walk({"groq": K1}, World().on("groq", K1, ok("First sentence is here. Second one is cut of", finish="length")), engine=1)
    check("... and prose is trimmed to its last sentence there too", r == "First sentence is here.", r)


async def t_empty():
    r, w, pz = await walk(LA, World().on("groq", K1, R(200, completion("")), ).on("gemini", K2, GOOD))
    check("an EMPTY answer is an unusable one: held back, the next provider answers, no pause", isinstance(r, str) and [c[0] for c in w.calls_for()] == ["groq", "gemini"] and pz == []
          and gate.bad_get("groq", gate.fingerprint("groq", K1), G120, "json").reason == "empty", (r, w.calls, pz))
    u = usage_of("uA", "groq")
    check("... counted as a request that told us nothing ('other'), not as a success", u["requests"] == 1 and u["other"] == 1 and u["ok"] == 0, u)
    r, w, pz = await walk(LA, World().on("groq", K1, R(200, completion("")), ).on("gemini", K2, ok("A fine answer.")), accept=op.chat_accept, cls="chat")
    check("the same for prose", r == "A fine answer." and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, w.calls))


async def t_limits_still_work():
    from world import GROQ_429_TPD
    r, w, pz = await walk({"groq": K1, "gemini": K2}, World().on("groq", K1, err(429, GROQ_429_TPD)).on("gemini", K2, GOOD))
    check("a limit still moves on exactly as before (the validated walk changes nothing about limits)", isinstance(r, str) and [c[0] for c in w.calls_for()] == ["groq", "groq", "gemini"], (r, w.calls))
    r, w, pz = await walk({"groq": K1}, World().on("groq", K1, err(401, GROQ_401)))
    check("a rejected key is still a rejected key: all_invalid, one request, no BadReplyError", isinstance(r, ProviderChainError) and not isinstance(r, BadReplyError) and r.state == "all_invalid"
          and len(w.calls_for()) == 1, (r, w.calls))
    r, w, pz = await walk({"groq": K1, "gemini": K2}, World().on("groq", K1, err(401, GROQ_401)).on("gemini", K2, NOTJSON))
    check("a rejected key AND an unusable reply: the learner is told the AI did not answer properly (transient), with the rejected key still listed", isinstance(r, BadReplyError)
          and {(k["provider"], k["kind"]) for k in r.kp()["keys"]} == {("groq", "invalid"), ("gemini", "transient")}, (r, r.kp() if isinstance(r, ProviderChainError) else ""))


async def t_isolation():
    r, w, _ = await walk({"groq": K1}, World().on("groq", K1, NOTJSON, GOOD))
    gate_a = gate.bad_blocked("groq", gate.fingerprint("groq", K1), G120, "json", time.time())
    world = World().on("groq", LB["groq"], GOOD)
    install(world)
    op.set_active_keys({"groq": LB["groq"]}, uid="uB", engine=2)
    await op._complete(MSG, 50, accept=ACCEPT, cls="json")
    check("learner A's unusable replies never hold anything against learner B's key (the gate is per key)", gate_a is not None and models(world) == [G120], (gate_a, models(world)))


async def t_log():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        await walk(LA, World().on("groq", K1, ok("secret learner words: my salary is 90000")).on("gemini", K2, NOTJSON).on("openrouter", K3, NOTJSON), uid="uA-secret-id")
    out = buf.getvalue()
    lines = [l for l in out.splitlines() if l.startswith("[keys] chain failed")]
    check("a failed validated walk leaves ONE line that names every unusable reply (provider / model / reason) and the second pass", len(lines) == 1 and "state=transient" in lines[0]
          and f"groq/{G120}:bad_output(not_json)" in lines[0] and "again" in lines[0] and "skipped-bad" in lines[0], out)
    check("... carrying NO key, NO learner id and NOTHING a provider wrote", K1 not in out and "uA-secret-id" not in out and "salary" not in out and "secret learner" not in out, out)


async def t_background_server_chain():
    saved = (op.settings.groq_api_key, op.settings.gemini_api_key, op.settings.openrouter_api_key)
    op.settings.groq_api_key, op.settings.gemini_api_key, op.settings.openrouter_api_key = K1, K2, ""
    try:
        w = fresh(None, uid="uS", engine=2, w=World().on("groq", K1, NOTJSON).on("gemini", K2, NOTJSON))
        op.set_active_keys(None, uid="uS", engine=2)
        try:
            await op._complete(MSG, 50, accept=ACCEPT, cls="json", cool=False)
            check("a background call with nothing usable raises", False)
        except BadReplyError:
            pass
        check("a BACKGROUND call (cool=False: Grammar Coach) against DuSu's own chain holds nothing back for everyone's chat - the gate is empty afterwards", not gate._bad, gate.bad_models(time.time()))
        check("... and the walk did not ask the same model twice: Groq's first model once, Gemini once, then Groq's sibling", models(w) == [G120, "gemini-flash-lite-latest", G20], models(w))
        w = fresh(None, uid="uS", engine=2, w=World().on("groq", K1, NOTJSON).on("gemini", K2, NOTJSON))
        op.set_active_keys(None, uid="uS", engine=2)
        try:
            await op._complete(MSG, 50, accept=ACCEPT, cls="json")
        except BadReplyError:
            pass
        check("an INTERACTIVE call against the same chain does hold the models back", len(gate._bad) == 3, len(gate._bad))
    finally:
        op.settings.groq_api_key, op.settings.gemini_api_key, op.settings.openrouter_api_key = saved


async def t_engine_levels():
    r, w, _ = await walk(LA, World().on("groq", K1, NOTJSON), engine=1)
    check("engine 1 (the per-key walker alone) ignores `accept`: prose where JSON was wanted is returned as before, nothing is held against the model", r == "Sure! I would love to help you with that, here you go."
          and len(w.calls_for()) == 1 and not gate._bad, (r, w.calls))
    r, w, _ = await walk(LA, World().on("groq", K1, R(200, completion("")), ok("later")), engine=1)
    check("... and an empty answer is still the old 'passing failure': a pause, a second pass", r == "later" and len(w.calls_for("groq")) == 2, (r, w.calls))
    for given, want in ((False, 0), (0, 0), (None, 0), (True, 1), (1, 1), (2, 2), (7, 2), (-3, 0)):
        op.set_active_keys(None, uid="u", engine=given)
        check(f"set_active_keys(engine={given!r}) -> level {want}", op._active_ctx.get().engine == want)
    op.set_active_keys(None, uid="u", engine=1)
    check("chain_v3_active() is false at 1 and true at 2", not op.chain_v3_active() and (op.set_active_keys(None, uid="u", engine=2) or op.chain_v3_active()))
    op._active_ctx.set(None)
    check("... and false when no context was ever set", not op.chain_v3_active())


for t in (t_failover, t_missing_field, t_all_bad, t_sibling_second_pass, t_held_back, t_truncation, t_empty, t_limits_still_work, t_isolation, t_log, t_background_server_chain, t_engine_levels):
    print(f"\n-- {t.__name__}")
    asyncio.run(t())


async def t_every_model_held_back2():
    w = World().on("groq", K1, GOOD)
    fresh({"groq": K1}, w=w)
    fp_ = gate.fingerprint("groq", K1)
    for m in (G120, G20):
        gate.mark_bad("groq", fp_, m, "json", time.time(), "not_json")
    pz = Pauses()
    saved, op._pause = op._pause, pz
    try:
        t = await op._complete(MSG, 50, accept=ACCEPT, cls="json")
    finally:
        op._pause = saved
    check("every model of the chain is being held back and nothing else is left: they are asked ANYWAY (a hiccup that hit all of them must not lock the learner out)",
          isinstance(t, str) and models(w) == [G120] and pz.log == [], (t, models(w)))
    check("... and the one that answered is cleared", gate.bad_get("groq", fp_, G120, "json") is None and gate.bad_get("groq", fp_, G20, "json") is not None)


async def t_single_held_back():
    w = World().on("gemini", K2, GOOD)
    fresh({"gemini": K2}, w=w)
    gate.mark_bad("gemini", gate.fingerprint("gemini", K2), "gemini-flash-lite-latest", "json", time.time(), "not_json")
    t = await op._complete(MSG, 50, accept=ACCEPT, cls="json")
    check("a provider with ONE model, held back, and nothing else in the chain: it is asked anyway, and answers", isinstance(t, str) and len(w.calls_for("gemini")) == 1, (t, w.calls))


print("\n-- t_every_model_held_back2")
asyncio.run(t_every_model_held_back2())
print("\n-- t_single_held_back")
asyncio.run(t_single_held_back())

# ============================================================================================ E. request parameters
section("E. Groq's reasoning settings: per-turn calls only, and a model that refuses them is remembered")


async def t_params():
    w = World().on("groq", K1, ok("Hello there!"))
    fresh({"groq": K1}, w=w)
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    b = w.bodies[0]
    check("a per-turn call to Groq's gpt-oss gets reasoning_effort 'low' and no reasoning in the reply", b.get("reasoning_effort") == "low" and b.get("include_reasoning") is False, b)
    w = World().on("groq", K1, ok("Hello there!"))
    fresh({"groq": K1}, w=w)
    await op._complete(MSG, 50, prefer_fast=False, accept=op.chat_accept, cls="chat")
    check("a scoring / extraction call (not prefer_fast) is sent exactly as it always was - reasoning stays on", "reasoning_effort" not in w.bodies[0] and "include_reasoning" not in w.bodies[0], w.bodies[0])
    w = World().on("groq", K1, ok("Hello there!"))
    fresh({"groq": K1}, w=w, engine=1)
    await op._complete(MSG, 50, prefer_fast=True)
    check("with the validated walk OFF (engine 1) the request to Groq is exactly what it always was - no reasoning settings (they are part of chain_v3)", "reasoning_effort" not in w.bodies[0] and "include_reasoning" not in w.bodies[0], w.bodies[0])
    w = World().on("gemini", K2, ok("Hello there!"))
    fresh({"gemini": K2}, w=w)
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("Gemini (which answers 400 to reasoning_effort) is never sent it", "reasoning_effort" not in w.bodies[0] and "include_reasoning" not in w.bodies[0], w.bodies[0])
    w = World().on("groq", K1, err(400, {"error": {"message": "Unrecognized request argument supplied: reasoning_effort", "type": "invalid_request_error"}}), ok("Hello there!"))
    fresh({"groq": K1}, w=w)
    t = await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("a model that answers 400 to those settings: the walk goes on (a 400 is the next model's turn) and answers", t == "Hello there!" and models(w) == [G120, G20], (t, models(w)))
    check("... and the refusing model is REMEMBERED", gate.param_unsupported("groq", G120, time.time()))
    w2 = World().on("groq", K1, ok("Hello again!"))
    install(w2)
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("... the next call to it is sent WITHOUT them (it works plain)", w2.bodies[0]["model"] == G120 and "reasoning_effort" not in w2.bodies[0] and "include_reasoning" not in w2.bodies[0], w2.bodies[0])
    w2b = World().on("groq", K1, ok("x"))
    fresh({"groq": K1}, w=w2b)
    gate.mark_param_unsupported("groq", G120, time.time())
    gate.mark_bad("groq", gate.fingerprint("groq", K1), G120, "chat", time.time(), "empty")        # hold the first model back so the SIBLING is the one asked
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("... while a sibling that never refused still gets them", w2b.bodies[0]["model"] == G20 and w2b.bodies[0].get("reasoning_effort") == "low", w2b.bodies[0])
    w3 = World().on("groq", K1, err(400, {"error": {"message": "max_tokens is too large", "type": "invalid_request_error"}}), ok("fine"))
    fresh({"groq": K1}, w=w3)
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("a 400 about something ELSE does not make a model forget its settings", not gate.param_unsupported("groq", G120, time.time()))


asyncio.run(t_params())

# ============================================================================================ F. the llm helpers and the save-time probe
section("F. assess / score / the save-time probe")


async def t_helpers():
    fresh(LA, w=World().on("groq", K1, NOTJSON).on("gemini", K2, GOOD))
    d = await llm.assess("system", "payload", prefer_fast=True, schema={"reply": "str+"})
    check("assess with the validated walk: the failover happens inside the call and a real object comes back", d.get("reply", "").startswith("Haan") and llm.v3_active(), d)
    fresh(LA, w=World().on("groq", K1, NOTJSON).on("gemini", K2, NOTJSON).on("openrouter", K3, NOTJSON))
    d = await llm.assess("system", "payload", prefer_fast=True, schema={"reply": "str+"})
    check("... when NOTHING is usable it returns the failure shape every caller already handles - it does not raise and it is never half-parsed", d.get("error") == "scoring_parse_failed" and "reply" not in d, d)
    fresh(LA, w=World().on("groq", K1, ok('{"intent": "x"}')).on("gemini", K2, ok('{"reply": "ok"}')))
    d = await llm.assess("system", "payload", schema={"reply": "str+"})
    check("a schema is enforced by name", d == {"reply": "ok"}, d)
    fresh(LA, w=World().on("groq", K1, NOTJSON), engine=1)
    d = await llm.assess("system", "payload", schema={"reply": "str+"})
    check("engine 1: assess is what it was - the same unusable reply comes back as the parse-failure sentinel after ONE request", d.get("error") == "scoring_parse_failed" and len(world_of().calls_for()) == 1 and not llm.v3_active(), d)
    fresh(LA, w=World().on("groq", K1, ok('{"overall": "81", "scores": {}}')))
    d = await llm.score("sys", [{"role": "user", "content": "hello"}])
    check("score: a numeric string for 'overall' is accepted (the scorers always did)", d.get("overall") == "81", d)
    fresh(LA, w=World().on("groq", K1, ok('{"scores": {}}')).on("gemini", K2, ok('{"overall": 70}')))
    d = await llm.score("sys", [{"role": "user", "content": "hello"}])
    check("score: a card without 'overall' is unusable and the next provider scores it", d.get("overall") == 70, d)
    fresh(LA, w=World().on("groq", K1, ok("Sure!")).on("gemini", K2, ok("Sure!")).on("openrouter", K3, ok("Sure!")))
    d = await llm.score("sys", [{"role": "user", "content": "hello"}])
    check("score with nothing usable: the sentinel, not an exception", d.get("error") == "scoring_parse_failed", d)
    fresh(LA, w=World().on("groq", K1, R(200, completion(""))).on("gemini", K2, ok("Hello there, friend.")))
    t = await llm.next_question("sys", [{"role": "user", "content": "hi"}])
    check("next_question / translate / generate: an empty reply is unusable and the walk moves on to the next PROVIDER", t == "Hello there, friend." and [c[0] for c in world_of().calls_for()] == ["groq", "gemini"], (t, world_of().calls))


def world_of():
    return op._http_client_factory.__self__


asyncio.run(t_helpers())


async def t_probe():
    w = World().on("groq", K1, R(200, completion("")), ok("OK"))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("the save-time probe: a model that answers with NOTHING is not a working key - the provider's next model is tried, and an answer counts", p.kind == "ok" and models(w) == [G120, G20], (p, models(w)))
    check("... it asks with room to answer (160 tokens; 8 were spent entirely on a reasoning model's thinking) and with the same reasoning setting the walker sends",
          w.bodies[0].get("max_tokens") == 160 and w.bodies[0].get("reasoning_effort") == "low", w.bodies[0])
    w = World().on("groq", K1, err(400, {"error": {"message": "Unrecognized request argument supplied: reasoning_effort", "type": "invalid_request_error"}}), ok("OK"))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("a 400 that names the reasoning settings is NOT a bad key: the model is asked once more without them and the key is ok - and the model is remembered, so the walker stops sending them too",
          p.kind == "ok" and len(w.bodies) == 2 and "reasoning_effort" in w.bodies[0] and "reasoning_effort" not in w.bodies[1] and gate.param_unsupported("groq", G120, time.time()), (p, w.bodies))
    w = World().on("groq", K1, R(200, completion("", finish="length")))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("a reasoning model cut off by the token limit while still thinking proves the key runs: ok (an empty answer that ENDED normally does not)", p.kind == "ok" and len(w.calls_for()) == 1, (p, w.calls))
    w = World().on("groq", K1, err(400, {"error": {"message": "max_tokens is too large", "type": "invalid_request_error"}}))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("a 400 about something else is still 'unknown' - never evidence about the key, never retried blindly", p.kind == "unknown" and len(w.bodies) == 1 and not gate.param_unsupported("groq", G120, time.time()), (p, len(w.bodies)))
    w = World().on("groq", K1, R(200, completion("")))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("every model answering with nothing: 'transient' (not ok) - the key is not counted as working", p.kind == "transient" and p.why == "empty", p)
    w = World().on("groq", K1, ok("OK"))
    fresh({"groq": K1}, w=w)
    p = await probe.chat_probe("groq", K1, "uA")
    check("a normal answer is ok, one request", p.kind == "ok" and len(w.calls_for()) == 1, (p, w.calls))


asyncio.run(t_probe())

# ============================================================================================ G. input bounds + the hygiene of the call sites
section("G. /level/test/submit's body is bounded; every call site passes the engine level")
os.environ.setdefault("GOOGLE_CLIENT_ID", "")
from pydantic import ValidationError                      # noqa: E402
from app import main as M                                 # noqa: E402

item = {"prompt": "p", "target": "t", "said": "s"}


def bad_body(**kw):
    try:
        M.LevelTestIn(**{"token": "t", "level": 1, "items": [item], **kw})
        return False
    except ValidationError:
        return True


check("a normal level-test body is accepted", not bad_body())
check("a level outside 1..7 is refused (it used to reach the learner's progress as it was)", bad_body(level=0) and bad_body(level=8) and bad_body(level=-3) and not bad_body(level=7))
check("no items / too many items are refused", bad_body(items=[]) and bad_body(items=[item] * 21) and not bad_body(items=[item] * 20))
check("a said / prompt / target that is absurdly long is refused (it is pasted into the model's prompt)", bad_body(items=[{**item, "said": "x" * 2001}]) and bad_body(items=[{**item, "prompt": "x" * 801}])
      and not bad_body(items=[{**item, "said": "x" * 2000}]))
check("lang is bounded", bad_body(lang="x" * 9))
check("engine_level exists and is what every call site passes (main.py + the two routers)",
      all(("engine=await engine_level(" in open(f"/app/app/{p}").read() or "engine=await M.engine_level(" in open(f"/app/app/{p}").read()) and "engine=await key_health_enabled(" not in open(f"/app/app/{p}").read()
          for p in ("main.py", "grammar/api.py", "resume_interview/api.py")))

# ============================================================================================ H. time, the breaker and the order of the providers
section("H. the health of a model (pure)")
gate.reset_all()
T0 = 1_800_000_000.0
check("a model nobody measured is a prior (0.9) with a closed breaker", gate.health_verdict("groq", G120, "json", T0) == "go" and gate.provider_score("groq", T0) == gate.HEALTH_PRIOR)
for i in range(5):
    gate.health_ok("gemini", "gemini-flash-lite-latest", "json", 800 + i, T0 + i)
h = gate._health[("gemini", "gemini-flash-lite-latest", "json")]
check("usable replies raise the success rate toward 1 and the speed follows (smoothed)", 0.95 < h.ok < 0.96 and 700 < h.ms < 900 and h.n == 5 and h.consec == 0, (h.ok, h.ms, h.n))
gate.health_fail("groq", G120, "json", "bad", T0)
check("an unusable reply lowers the success rate but does NOT count toward the breaker (the model answered)", gate._health[("groq", G120, "json")].consec == 0 and gate._health[("groq", G120, "json")].ok < 0.8
      and gate.order_by_health(["groq", "gemini"], T0) == ["groq", "gemini"])
gate.health_fail("groq", G20, "json", "bad", T0)
gate.health_fail("groq", G20, "json", "bad", T0)
check("... one unusable reply does not demote a provider, two in a row do (the band changes)", gate.order_by_health(["groq", "gemini"], T0) == ["gemini", "groq"], gate.provider_score("groq", T0))
gate.reset_all()
gate.health_fail("groq", G120, "json", "bad", T0)
gate.health_fail("groq", G120, "json", "transient", T0)
gate.health_fail("groq", G120, "json", "transient", T0)
check("two failures to ANSWER in a row are not yet an open breaker", gate.health_verdict("groq", G120, "json", T0) == "go")
gate.health_fail("groq", G120, "json", "transient", T0)
check("three in a row open it for 60 s", gate.health_verdict("groq", G120, "json", T0 + 30) == "skip" and abs(gate._health[("groq", G120, "json")].until - (T0 + 60)) < 0.01)
check("... then ONE caller is the probe and everybody else keeps skipping (single flight)", gate.health_verdict("groq", G120, "json", T0 + 61) == "probe" and gate.health_verdict("groq", G120, "json", T0 + 61) == "skip")
gate.health_fail("groq", G120, "json", "transient", T0 + 62)
check("a probe that fails again opens it for twice as long (120 s)", abs(gate._health[("groq", G120, "json")].until - (T0 + 62 + 120)) < 0.01 and gate.health_verdict("groq", G120, "json", T0 + 100) == "skip")
gate.health_verdict("groq", G120, "json", T0 + 400)
gate.health_release("groq", G120, "json")
check("a probe that ended without a verdict gives its slot back", gate.health_verdict("groq", G120, "json", T0 + 401) == "probe")
gate.health_ok("groq", G120, "json", 600, T0 + 402)
check("one usable reply closes the breaker for good", gate.health_verdict("groq", G120, "json", T0 + 403) == "go" and gate._health[("groq", G120, "json")].consec == 0 and gate._health[("groq", G120, "json")].opened == 0)
for i in range(8):
    gate.health_fail("groq", G20, "json", "transient", T0 + i * 1000)       # a long time passes between failures: they are not 'in a row' for long
check("the hold is capped at 5 minutes", gate._health[("groq", G20, "json")].until - (T0 + 7000) <= gate.BREAKER_MAX_S + 0.01)
gate.reset_all()
gate.health_fail("groq", G120, "json", "bad", T0)
ok_before = gate._health[("groq", G120, "json")].ok
check("a reading older than 30 minutes drifts back toward the prior", (gate.provider_score("groq", T0 + gate.HEALTH_STALE_S + 60) > ok_before) and gate.provider_score("groq", T0 + gate.HEALTH_STALE_S + 60) < gate.HEALTH_PRIOR)
gate.reset_all()
for i in range(6):
    gate.health_fail("groq", G120, "json", "bad", T0 + i)
for i in range(5):
    gate.health_ok("gemini", "gemini-flash-lite-latest", "json", 700, T0 + i)
order = gate.order_by_health(["groq", "gemini", "openrouter"], T0 + 10)
check("providers are ordered best-first by band: a measured-bad Groq goes last, an unmeasured OpenRouter keeps its place after Gemini", order == ["gemini", "openrouter", "groq"], order)
gate.reset_all()
for i in range(5):
    gate.health_ok("gemini", "gemini-flash-lite-latest", "json", 700, T0 + i)
check("two scores inside one band keep the CONFIGURED order: a measured-good Gemini (0.96) does not leapfrog an unmeasured Groq (0.9) - no flapping", gate.order_by_health(["groq", "gemini", "openrouter"], T0 + 10) == ["groq", "gemini", "openrouter"])
gate.reset_all()
for _ in range(3):
    gate.health_fail("groq", G120, "json", "transient", T0)
    gate.health_fail("groq", G20, "json", "transient", T0)
check("a provider whose every measured model has its breaker open is worth nothing - last", gate.provider_score("groq", T0 + 1) == 0.0 and gate.order_by_health(["groq", "gemini"], T0 + 1) == ["gemini", "groq"])
v = gate.health_view(T0 + 1)
check("the dashboard's view is counts and times only: no key, no fingerprint, no learner", all(set(r) == {"provider", "model", "class", "ok", "ms", "n", "breaker", "reopen_in"} for r in v) and any(r["breaker"] for r in v), v)
for i in range(gate.MAX_HEALTH_ENTRIES + 40):
    gate.health_ok("groq", f"m{i}", "json", 1, T0 + i)
check("the map is bounded", len(gate._health) <= gate.MAX_HEALTH_ENTRIES + 1, len(gate._health))
gate.reset_all()

section("H2. time budgets, the ceiling, the breaker and the order, against the scripted world")
SLOW = 3.0
SAVED_T = (dict(op._ATTEMPT_S), op._ATTEMPT_HEAVY_S, dict(op._WALK_S), op._MIN_ATTEMPT_S, op._REPASS_MIN_LEFT_S)
op._REPASS_MIN_LEFT_S = 0.3
op._ATTEMPT_S.update(chat=0.4, json=0.5)
op._ATTEMPT_HEAVY_S = 0.9
op._WALK_S.update(chat=1.4, json=1.6)
op._MIN_ATTEMPT_S = 0.05
GOODJ = ok(json.dumps({"reply": "Haan bilkul."}))


async def timed(keys, w, engine=2, **kw):
    fresh(keys, engine=engine, w=w)
    t0 = time.time()
    try:
        r = await op._complete(MSG, 50, accept=ACCEPT, cls="json", **kw)
    except ProviderChainError as e:
        r = e
    return r, time.time() - t0, op._http_client_factory.__self__


async def t_timeouts():
    SLOWR = R(200, completion("late"), delay=SLOW)
    r, el, w = await timed(LA, World().on("groq", K1, SLOWR).on("gemini", K2, GOODJ), prefer_fast=True)
    check("an interactive JSON turn: a provider that is silent is given up on after 0.5 s (here; 11 s in production), then the NEXT provider answers - not after the old 20 s",
          isinstance(r, str) and 0.4 < el < 1.0 and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, el, w.calls))
    r, el, w = await timed({"groq": K1}, World().on("groq", K1, SLOWR), prefer_fast=True)
    check("ONE provider only: there is nowhere to switch to, so it gets what is left of the walk (the 1.6 s ceiling here), not the 0.5 s cut - one request, then the honest failure",
          isinstance(r, ProviderChainError) and r.state == "transient" and 1.4 < el < 2.0 and len(w.calls_for("groq")) == 1, (r, el, w.calls))
    r, el, w = await timed({"groq": K1}, World().on("groq", K1, R(200, completion('{"reply": "eventually"}'), delay=0.8)), prefer_fast=True)
    check("... so an answer after 0.8 s (past the 0.5 s cut) is received when it is the only one there is", isinstance(r, str) and json.loads(r)["reply"] == "eventually" and el >= 0.8 and len(w.calls_for()) == 1, (r, el, w.calls))
    r, el, w = await timed(LA, World().on("groq", K1, SLOWR).on("gemini", K2, GOODJ), prefer_fast=False)
    check("a heavy call (scoring, extraction: not prefer_fast) keeps the long limit - 0.9 s here, the old 20 s in production - and fails over the same way", isinstance(r, str) and 0.8 < el < 1.5
          and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, el, w.calls))
    slowfine = R(200, completion('{"reply": "slowbutfine"}'), delay=0.7)
    r, el, w = await timed(LA, World().on("groq", K1, slowfine).on("gemini", K2, GOODJ), prefer_fast=False)
    check("a heavy call: an answer after 0.7 s (inside its limit) is NOT cut off and the next provider is never asked", isinstance(r, str) and json.loads(r)["reply"] == "slowbutfine" and el >= 0.7
          and [c[0] for c in w.calls_for()] == ["groq"], (r, el, w.calls))
    r, el, w = await timed(LA, World().on("groq", K1, slowfine).on("gemini", K2, GOODJ), prefer_fast=True)
    check("... the SAME answer for an interactive call (cut at 0.5 s) is given up on: the next provider answers", isinstance(r, str) and json.loads(r)["reply"] == "Haan bilkul." and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, w.calls))
    r, el, w = await timed(LA, World().on("groq", K1, SLOWR).on("gemini", K2, SLOWR).on("openrouter", K3, SLOWR), prefer_fast=True)
    check("every provider silent: Groq cut at 0.5 s, Gemini at 0.5 s, the LAST provider gets the 0.6 s that are left - the walk ends at its 1.6 s ceiling, never past it",
          isinstance(r, ProviderChainError) and 1.4 < el < 1.9 and len(w.calls_for()) == 3, (r, el, w.calls))
    op._WALK_S["json"] = 0.7
    r, el, w = await timed(LA, World().on("groq", K1, SLOWR).on("gemini", K2, SLOWR).on("openrouter", K3, SLOWR), prefer_fast=True)
    op._WALK_S["json"] = 1.6
    check("a ceiling shorter than two cuts: the second attempt is cut to what is left (0.2 s), the third is never started - the walk ends at 0.7 s, not 1.0",
          isinstance(r, ProviderChainError) and 0.6 < el < 0.95 and [c[0] for c in w.calls_for()] == ["groq", "gemini"], (r, el, w.calls))
    r, el, w = await timed({"groq": K1}, World().on("groq", K1, R(200, completion("late"), delay=0.7), R(200, completion("late"), delay=0.7)), engine=1, prefer_fast=True)
    check("engine 1 (no validated walk): no per-class limit - the answer after 0.7 s is simply waited for", isinstance(r, str) and el >= 0.7, (r, el))


async def t_breaker():
    w = World().on("groq", K1, timeout())
    fresh({"groq": K1}, w=w)
    for i in range(3):
        try:
            await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True, cool=False)       # cool=False: no pause and no second pass - one request per turn, deterministic
        except ProviderChainError:
            pass
    n120 = len([c for c in w.calls_for("groq") if c[3] == G120])
    check("three turns in a row: Groq's first model fails to answer each time (a timeout LEAVES the provider, so its sibling was never asked)", n120 == 3 and len(w.calls_for("groq")) == 3, (n120, w.calls))
    w.on("groq", K1, GOODJ)
    w.n.clear()
    for _ in range(2):
        await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    n120b = len([c for c in w.calls_for("groq") if c[3] == G120])
    check("the breaker is open: the next turns do not ask that model at all (no wait on it) - its sibling answers", n120b == 3 and len([c for c in w.calls_for("groq") if c[3] == G20]) == 2, models(w, "groq"))
    h = gate._health[("groq", G120, "json")]
    check("... and the dashboard's view says so, with when it will be tried again", any(r["model"] == G120 and r["breaker"] and 0 < r["reopen_in"] <= 60 for r in op.model_health()), op.model_health())
    h.until = time.time() - 1                               # the minute is up
    w2 = World().on("groq", K1, R(200, completion('{"reply": "back"}'), delay=0.2))
    install(w2)
    await asyncio.gather(*[op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True) for _ in range(5)])
    n_probe = len([c for c in w2.calls_for("groq") if c[3] == G120])
    check("when the hold is over exactly ONE of five concurrent turns is the probe of that model (single flight)", n_probe == 1, (n_probe, models(w2, "groq")))
    check("... the probe answered: the breaker is closed and the model is welcome again", gate.health_verdict("groq", G120, "json", time.time()) == "go" and gate._health[("groq", G120, "json")].consec == 0)
    # a probe that fails opens it again for twice as long
    for _ in range(3):
        gate.health_fail("groq", G120, "json", "transient", time.time())
    h = gate._health[("groq", G120, "json")]
    h.until = time.time() - 1
    w3 = World().on("groq", K1, timeout())
    install(w3)
    try:
        await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True, cool=False)
    except ProviderChainError:
        pass
    check("a probe that fails again opens the breaker for twice as long (the model was asked once, not hammered)", len([c for c in w3.calls_for("groq") if c[3] == G120]) == 1
          and 100 < gate._health[("groq", G120, "json")].until - time.time() <= 120, (models(w3, "groq"), gate._health[("groq", G120, "json")].until - time.time()))
    # a model that ANSWERS badly is alive: through the walker, three unusable replies in a row never open its breaker (they are held back per key and per kind instead)
    wb = World().on("groq", K1, NOTJSON)
    fresh({"groq": K1}, w=wb)
    for _ in range(4):
        gate._bad.clear()                                   # the 20 s hold is over each time, so the model IS asked each time
        try:
            await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
        except ProviderChainError:
            pass
    hb = gate._health[("groq", G120, "json")]
    check("unusable replies four turns in a row: the model was asked each time, its success rate fell, and its breaker is still CLOSED (it answers, badly - that is a different failure)",
          len([c for c in wb.calls_for("groq") if c[3] == G120]) == 4 and hb.ok < 0.6 and hb.consec == 0 and gate.health_verdict("groq", G120, "json", time.time()) == "go", (hb, models(wb, "groq")))
    # legacy / engine 1 never consults any of this
    fresh(LA, w=World().on("groq", K1, timeout()).on("gemini", K2, ok("fine")), engine=1)
    for _ in range(4):
        await op._complete(MSG, 50, prefer_fast=True)
    check("engine 1: the breaker does not exist - the first model is asked every time, as before", len([c for c in op._http_client_factory.__self__.calls_for("groq") if c[3] == G120]) == 4 and not gate._health)


async def t_order():
    fresh(LA, w=World().on("groq", K1, GOODJ).on("gemini", K2, GOODJ).on("openrouter", K3, GOODJ))
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    w = op._http_client_factory.__self__
    check("no measurements: the configured order (Groq first for a per-turn call)", [c[0] for c in w.calls_for()] == ["groq"], w.calls)
    gate.reset_all()
    for i in range(6):
        gate.health_fail("groq", G120, "json", "bad", time.time())
    for i in range(5):
        gate.health_ok("gemini", "gemini-flash-lite-latest", "json", 700, time.time())
    w = World().on("groq", K1, GOODJ).on("gemini", K2, GOODJ).on("openrouter", K3, GOODJ)
    install(w)
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    check("Groq measured bad, Gemini measured good: GEMINI is asked first - the first provider is no longer fixed by the configuration", [c[0] for c in w.calls_for()] == ["gemini"], w.calls)
    w = World().on("groq", K1, GOODJ).on("gemini", K2, GOODJ).on("openrouter", K3, GOODJ)
    install(w)
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True, first="groq")
    check("a caller that names a provider (first=) still gets it first", [c[0] for c in w.calls_for()] == ["groq"], w.calls)
    gate.reset_all()
    for i in range(6):
        gate.health_fail("groq", G120, "json", "bad", time.time())
    fresh(LA, w=World().on("groq", K1, GOODJ).on("gemini", K2, GOODJ), engine=1)
    for i in range(6):
        gate.health_fail("groq", G120, "json", "bad", time.time())
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    check("engine 1: the order is not touched by any of it", [c[0] for c in op._http_client_factory.__self__.calls_for()] == ["groq"])
    fresh(LA, w=World().on("groq", K1, GOODJ).on("gemini", K2, GOODJ), engine=2)
    for _ in range(3):
        gate.health_fail("groq", G120, "json", "transient", time.time())
        gate.health_fail("groq", G20, "json", "transient", time.time())
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    check("every Groq model's breaker is open: Groq is asked last, and not at all while another provider answers", [c[0] for c in op._http_client_factory.__self__.calls_for()] == ["gemini"])
    check("the dashboard's model_health() sees it", any(r["provider"] == "groq" and r["breaker"] for r in op.model_health()), op.model_health())


async def t_all_open():
    fresh({"groq": K1}, w=World().on("groq", K1, GOODJ))
    for m in (G120, G20):
        for _ in range(3):
            gate.health_fail("groq", m, "json", "transient", time.time())
    r = await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    check("every model's breaker is open and nothing else is left: they are asked anyway (a hiccup must not lock the learner out), and an answer closes the breaker",
          isinstance(r, str) and len(op._http_client_factory.__self__.calls_for("groq")) >= 1 and gate.health_verdict("groq", G120, "json", time.time()) == "go", r)


for t in (t_timeouts, t_breaker, t_order, t_all_open):
    print(f"\n-- {t.__name__}")
    asyncio.run(t())

# ============================================================================================ I. Cloudflare / Z.ai / Sarvam under the validated walk (learner-added, 2026-11-17)
section("I. an unverified service is safe: a bad reply from it is a failure like any other, and it starts behind the established ones")
CF_ACCT = "0123456789abcdef0123456789abcdef"
CF_TOK = "cfdemo_" + "T" * 33 + "9xYz"
CF_KEY = f"{CF_ACCT}:{CF_TOK}"
ZAI_KEY = "a" * 32 + "." + "Zz" * 8 + "Q4rT"
SV_KEY = "sk_" + "s" * 30 + "Sv91"
CFM = ["@cf/google/gemma-4-26b-a4b-it", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/mistralai/mistral-small-3.1-24b-instruct"]


async def t_new_services():
    # a service that answers with prose where JSON was needed is held back for JSON calls (per key), and the next provider answers in the SAME call
    r, w, pz = await walk({"cloudflare": CF_KEY, "zai": ZAI_KEY}, World().on("cloudflare", CF_TOK, NOTJSON).on("zai", ZAI_KEY, GOOD))
    check("Cloudflare answers prose where JSON was needed: Z.ai answers in the same call, no pause - an unverified model cannot hand the learner a broken reply",
          isinstance(r, str) and json.loads(r)["reply"].startswith("Haan") and [c[0] for c in w.calls_for()] == ["cloudflare", "zai"] and pz == [], (r, w.calls, pz))
    fpc = gate.fingerprint("cloudflare", CF_KEY)
    check("... Gemma is held back for JSON calls (per KEY, per kind) - not the key, not the prose calls", gate.bad_blocked("cloudflare", fpc, CFM[0], "json", time.time()) is not None
          and gate.bad_blocked("cloudflare", fpc, CFM[0], "chat", time.time()) is None and gate.get("cloudflare", fpc) is None)
    check("... and Cloudflare's other models wait for the second pass (another provider first)", [c[3] for c in w.calls_for("cloudflare")] == [CFM[0]])
    # nothing usable anywhere on these services
    r, w, pz = await walk({"cloudflare": CF_KEY, "zai": ZAI_KEY, "sarvam": SV_KEY}, World().on("cloudflare", CF_TOK, NOTJSON).on("zai", ZAI_KEY, ok('{"intent": "x"}')).on("sarvam", SV_KEY, ok("")))
    check("nothing usable on any of the three: a BadReplyError (transient - 'the AI did not answer properly'), never 'your keys'", isinstance(r, BadReplyError) and r.state == "transient" and not is_keys_problem(r.kp()), r)
    check("... every model of every one of them was asked once (3 + 2 + 2)", sorted(models(w)) == sorted(CFM + ["glm-4.7-flash", "glm-4.5-flash", "sarvam-105b-conversations", "sarvam-105b"]), models(w))
    # Sarvam: reasoning_effort is learned like Groq's - a 400 that names it is remembered per model
    w = World().on("sarvam", SV_KEY, err(400, {"error": {"message": "Unknown parameter: reasoning_effort", "code": "unprocessable_entity_error"}}), ok("Hello there!"))
    fresh({"sarvam": SV_KEY}, w=w)
    t = await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("Sarvam: a model that answers 400 to reasoning_effort is remembered and the walk answers with the next model", t == "Hello there!" and gate.param_unsupported("sarvam", "sarvam-105b-conversations", time.time()), (t, models(w)))
    w2 = World().on("sarvam", SV_KEY, ok("again"))
    install(w2)
    await op._complete(MSG, 50, prefer_fast=True, accept=op.chat_accept, cls="chat")
    check("... and the next call to it is sent without", "reasoning_effort" not in w2.bodies[0], w2.bodies[0])
    # order: the unverified services start a band lower, so a healthy established provider answers alone
    r, w, _ = await walk({"groq": K1, "cloudflare": CF_KEY, "zai": ZAI_KEY}, World().on("groq", K1, GOOD).on("cloudflare", CF_TOK, GOOD).on("zai", ZAI_KEY, GOOD))
    check("with Groq healthy and the new services unmeasured only Groq is asked (a health-ordered chain does not put the unverified first)", [c[0] for c in w.calls_for()] == ["groq"], w.calls)
    fresh({"cloudflare": CF_KEY, "groq": K1}, w=World().on("groq", K1, GOOD).on("cloudflare", CF_TOK, GOOD))
    for _ in range(8):
        gate.health_fail("groq", G120, "json", "bad", time.time()); gate.health_fail("groq", G20, "json", "bad", time.time())
    for _ in range(8):
        gate.health_ok("cloudflare", CFM[0], "json", 600, time.time())
    await op._complete(MSG, 50, accept=ACCEPT, cls="json", prefer_fast=True)
    check("... but once Groq is doing badly and Cloudflare has proved itself, Cloudflare is asked first - the order follows real answers", [c[0] for c in op._http_client_factory.__self__.calls_for()][:1] == ["cloudflare"], op._http_client_factory.__self__.calls)


asyncio.run(t_new_services())

op._ATTEMPT_S.clear(); op._ATTEMPT_S.update(SAVED_T[0])
op._ATTEMPT_HEAVY_S, op._MIN_ATTEMPT_S, op._REPASS_MIN_LEFT_S = SAVED_T[1], SAVED_T[3], SAVED_T[4]
op._WALK_S.clear(); op._WALK_S.update(SAVED_T[2])

print(f"\n{N - len(FAILS)} / {N} checks passed")
sys.exit(1 if FAILS else 0)
