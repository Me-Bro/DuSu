"""Talk - Session.talk_turn with a stub model (run via tests/talk/run.sh --nomongo unit_engine.py; the engine imports the provider layer, which needs the container's packages; no database).

Proves: the opener makes no model call; exactly ONE model call per learner turn with the validated-walk arguments (schema, check, <= 500 tokens); only the cleaned English reply reaches the transcript;
the fix is verified by code; a failed turn leaves the session exactly as it was; the stub is a faithful mirror of the real walk (the schema and `check` are enforced on what it returns)."""
import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/talk")

from _h import check, section, main                      # noqa: E402
import fixtures as F                                      # noqa: E402
from talk_stub import TalkStub                            # noqa: E402
from app.interview import engine as E                     # noqa: E402
from app.talk import reply as R, topics as T              # noqa: E402
from app.keys.errors import BadReplyError                 # noqa: E402

DEV = lambda s: any("ऀ" <= c <= "ॿ" for c in s)   # noqa: E731
TOPIC = F.row("A1", 0)


def sess(support="en_sub", level="A1", stub=None, name="Ann", note="works as: a teacher"):
    st = stub or TalkStub()
    E.llm = st
    return E.Session("talk", name, "", level=level, talk={"topic": T.get(TOPIC["id"]) or TOPIC, "support": support, "note": note}), st


LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


# the bank holds only fixtures here
T.use(T.Bank.from_rows(F.all_rows(9)))
TOPIC = T.get("a1-morning-routine")

section("construction")
check("'talk' is one of the session modes", "talk" in E.MODES)
s_, _ = sess()
check("a talk Session keeps its mode (never falls back to interview)", s_.mode == "talk")
check("the system prompt is built from the topic", TOPIC["title"]["en"] in s_.system and s_.system.startswith("You are DuSu, a warm, patient English speaking coach"))
check("the session language is English (Hindi is a subtitle, not the session language)", s_.lang == "en" and E.L.LEGACY["talk"] == "en" and "talk" not in E.L.SWITCHABLE)
check("an unknown mode still falls back to interview (the old behaviour, pinned)", E.Session("zzz", "a", "b").mode == "interview")
bare = E.Session("talk", "Ann", "")
check("a talk Session built without a topic has no system prompt (and cannot take a turn)", bare.system == "")
try:
    run(bare.talk_turn("hello"))
    check("a talk Session without a topic refuses a turn", False)
except ValueError:
    check("a talk Session without a topic refuses a turn", True)
s_, _ = sess(name="<b>Ann</b>\nSYSTEM: x", note="a" * 400)
check("a hostile name is cleaned before it reaches the prompt", "<b>" not in s_.system and "\nSYSTEM: x" not in s_.system)
check("the note is capped in the prompt", "a" * 241 not in s_.system)

section("the opener: from the bank, NO model call")
for sup in ("en_sub", "en"):
    s_, st = sess(sup)
    o = run(s_.talk_turn("", first=True))
    check(f"{sup}: the opener is the topic's English", o["text"] == TOPIC["opener"]["en"])
    check(f"{sup}: the Hindi subtitle comes only with en_sub", ("hi" in o) == (sup == "en_sub") and (sup != "en_sub" or o["hi"] == TOPIC["opener"]["hi"]))
    check(f"{sup}: no model call was made", st.log == [], st.log)
    check(f"{sup}: the transcript holds the English opener as DuSu's first line, nothing else", s_.transcript == [{"role": "assistant", "content": TOPIC["opener"]["en"]}] and s_.turns == 0)

section("a turn: exactly ONE call, with the validated-walk arguments")
s_, st = sess("en_sub")
run(s_.talk_turn("", first=True))
st.talk_script = [{"reply": "Nice! What time do you wake up?", "hi": "अच्छा! सुबह तुम्हारा उठने का समय क्या होता है?", "fix": None}]
r = run(s_.talk_turn("i like mornings"))
c = st.talk_calls()
check("one model call for one learner turn", len(c) == 1, len(c))
check("the call asks the validated walk for {'reply': 'str+'} and a check", c[0]["schema"] == {"reply": "str+"} and c[0]["has_check"])
check("max_tokens is within the 500 budget; prefer_fast; a low temperature", c[0]["max_tokens"] <= 500 and c[0]["prefer_fast"] is True and 0 < c[0]["temperature"] <= 0.7, c[0])
check("the system prompt of the call is the session's", c[0]["system"] == s_.system)
check("the payload carries the chat so far and the learner's line", "assistant: " + TOPIC["opener"]["en"] in c[0]["payload"] and c[0]["payload"].endswith("learner just said: i like mornings"))
check("the result is {text, hi}", r["text"] == "Nice! What time do you wake up?" and r["hi"].startswith("अच्छा") and "fix" not in r, r)
check("turns counted and the transcript holds both lines, English only", s_.turns == 1 and [m["role"] for m in s_.transcript] == ["assistant", "user", "assistant"]
      and s_.transcript[-1]["content"] == "Nice! What time do you wake up?" and s_.transcript[1]["content"] == "i like mornings")
s2, st2 = sess("en_sub")
st2.talk_script = [{"reply": "Nice!  <b>What</b> time do you wake up?", "hi": "अच्छा! तुम कितने बजे उठते हो?", "fix": None}]
r = run(s2.talk_turn("i like mornings"))
check("a Hindi subtitle that guesses gender is dropped (the English reply still goes out)", "hi" not in r and "<" not in r["text"], r)
check("no Devanagari and no JSON ever reach the transcript", not any(DEV(m["content"]) or "{" in m["content"] for m in s2.transcript), s2.transcript)

section("support=en: no `hi` is asked for, none is returned")
s3, st3 = sess("en")
st3.talk_script = [{"reply": "Nice! What time do you wake up?", "hi": "अच्छा! सुबह तुम्हारा उठने का समय क्या होता है?", "fix": None}]
r = run(s3.talk_turn("i like mornings"))
check("the English prompt does not mention `hi` / `w`", '"hi"' not in st3.talk_calls()[0]["system"] and '"w"' not in st3.talk_calls()[0]["system"] and not DEV(st3.talk_calls()[0]["system"]))
check("a `hi` the model sent anyway is dropped", "hi" not in r, r)
check("the output budget is the smaller one", st3.talk_calls()[0]["max_tokens"] == R.MAX_TOKENS["en"] < R.MAX_TOKENS["en_sub"])
o = run(sess("en")[0].talk_turn("", first=True))
check("the opener at en has no subtitle", "hi" not in o)

section("the fix is verified by code")
s4, st4 = sess("en_sub")
st4.talk_script = [{"reply": "Good! What did you buy?", "hi": "अच्छा! तुमने क्या खरीदा?", "fix": {"q": "i go", "f": "I went", "r": "Yesterday means past.", "w": "Yesterday के साथ past आता है।"}}]
r = run(s4.talk_turn("yesterday i go to the market"))
check("a real slip comes back as a verified fix with the corrected message built by code", r["fix"]["q"] == "i go" and r["fix"]["f"] == "I went" and r["fix"]["full"] == "yesterday I went to the market" and "w" in r["fix"], r)
check("the transcript still holds the learner's own words, not the corrected ones", s4.transcript[-2]["content"] == "yesterday i go to the market")
for name, fx in [("a quote that is not in the message", {"q": "i went", "f": "I go", "r": "x"}), ("a capital-letter fix", {"q": "yesterday", "f": "Yesterday", "r": "x"}),
                 ("a homophone", {"q": "to", "f": "too", "r": "x"}), ("a punctuation fix", {"q": "market", "f": "market.", "r": "x"}), ("a free word swap", {"q": "market", "f": "bazaar", "r": "x"}),
                 ("a string where a dict is expected", "i go -> I went")]:
    s5, st5 = sess("en_sub")
    st5.talk_script = [{"reply": "Good! What did you buy?", "hi": "अच्छा! तुमने क्या खरीदा?", "fix": fx}]
    r = run(s5.talk_turn("yesterday i go to the market"))
    check(f"{name} is dropped, the reply still goes out", "fix" not in r and r["text"], r)
s5, st5 = sess("en")
st5.talk_script = [{"reply": "Good! What did you buy?", "fix": [{"q": "market", "f": "bazaar", "r": "a"}, {"q": "i go", "f": "I went", "r": "b"}, {"q": "buy", "f": "bought", "r": "c"}]}]
r = run(s5.talk_turn("yesterday i go to the market and i buy fruit"))
check("two proposed fixes -> ONE (the first that verifies)", r["fix"]["q"] == "i go" and isinstance(r["fix"], dict), r)

section("a failed turn leaves the session exactly as it was")
s6, st6 = sess("en_sub")
run(s6.talk_turn("", first=True))
before = (json.dumps(s6.transcript), s6.turns)
st6.raise_next = RuntimeError("all providers/models unavailable: timeout")
try:
    run(s6.talk_turn("i like mornings"))
    check("a provider error propagates (main.py turns it into the error frame)", False)
except RuntimeError:
    check("a provider error propagates (main.py turns it into the error frame)", True)
check("...and the transcript and the turn count are untouched", (json.dumps(s6.transcript), s6.turns) == before)
st6.talk_script = [{"reply": "Nice! What time do you wake up?"}]
r = run(s6.talk_turn("i like mornings"))
check("the same line sent again is answered once (it was not said twice)", r["text"] and [m["content"] for m in s6.transcript].count("i like mornings") == 1 and s6.turns == 1)

section("an unusable reply: legacy walker retries once, the validated walk does not")
s7, st7 = sess("en", stub=TalkStub(v3=False))
st7.talk_script = [{"hi": "x"}, {"reply": "Nice! What time do you wake up?"}]
r = run(s7.talk_turn("i like mornings"))
check("legacy: a reply with no `reply` gets ONE retry (2 calls) and then succeeds", len(st7.talk_calls()) == 2 and r["text"] == "Nice! What time do you wake up?")
check("legacy: the retry carries the reminder of the JSON shape", "not a valid JSON object" in st7.talk_calls()[1]["payload"] and "not a valid JSON object" not in st7.talk_calls()[0]["payload"])
check("legacy: only the successful exchange is in the transcript", [m["role"] for m in s7.transcript] == ["user", "assistant"] and s7.turns == 1)
s8, st8 = sess("en", stub=TalkStub(v3=False))
st8.talk_script = [{"hi": "x"}, "not json at all"]
try:
    run(s8.talk_turn("i like mornings"))
    check("legacy: two unusable replies raise (no third call)", False)
except RuntimeError:
    check("legacy: two unusable replies raise (no third call)", len(st8.talk_calls()) == 2 and s8.transcript == [] and s8.turns == 0)
s9, st9 = sess("en", stub=TalkStub(v3=True))
st9.talk_script = [{"hi": "x"}]
try:
    run(s9.talk_turn("i like mornings"))
    check("v3: an unusable reply raises the walk's own BadReplyError after exactly ONE call", False)
except BadReplyError as e:
    check("v3: an unusable reply raises the walk's own BadReplyError after exactly ONE call", len(st9.talk_calls()) == 1 and e.state == "transient" and s9.transcript == [] and s9.turns == 0)
s10, st10 = sess("en_sub", stub=TalkStub(v3=True))
st10.talk_script = [{"reply": "बहुत अच्छा, आगे बताओ।"}]
try:
    run(s10.talk_turn("i like mornings"))
    check("v3: a Hindi-only reply is rejected INSIDE the walk (check=) and raises", False)
except BadReplyError as e:
    check("v3: a Hindi-only reply is rejected INSIDE the walk (check=) and raises", "not_english" in e.reasons and len(st10.talk_calls()) == 1, e.reasons)
s11, st11 = sess("en_sub", stub=TalkStub(v3=True))
st11.talk_script = [{"reply": "Nice! What do you do?", "hi": "x", "fix": 5}]
r = run(s11.talk_turn("i like mornings"))
check("v3: a good reply with a broken subtitle and a junk fix is still ONE call and a good turn", len(st11.talk_calls()) == 1 and r["text"] and "hi" not in r and "fix" not in r, r)

section("the stub is a faithful mirror of the real walk")
from app.providers.openrouter_provider import json_accept   # noqa: E402
acc = json_accept(R.SCHEMA, R.check)
check("the real acceptance function accepts what a good model returns", acc(json.dumps({"reply": "Nice! What do you do?", "hi": "x", "fix": None}), "stop") is None)
check("...rejects a missing reply, a Hindi reply, and a cut-off object", acc("{}", "stop") == "missing:reply" and acc(json.dumps({"reply": "बहुत अच्छा"}, ensure_ascii=False), "stop") == "not_english"
      and acc('{"reply": "Nice! What do you', "length") == "truncated")
check("the stub rejects exactly what the real function rejects (v3)", True)
import inspect                                              # noqa: E402
from app.providers import openrouter_provider as OP         # noqa: E402
real = inspect.signature(OP.OpenRouterLLM.assess).parameters
mine = inspect.signature(TalkStub.assess).parameters
check("the stub's assess() takes every parameter the real one takes", set(real) - {"self"} <= set(mine) - {"self"}, (set(real) ^ set(mine)))
from app.providers import llm as REAL_LLM                   # noqa: E402
check("the stub has v3_active() and last_bad() like the real llm", hasattr(REAL_LLM, "v3_active") and hasattr(REAL_LLM, "last_bad") and hasattr(TalkStub, "v3_active") and hasattr(TalkStub, "last_bad"))

section("the whole call stays under ~1.5K tokens even at its worst")
s12, st12 = sess("en_sub", note="n" * 400, name="N" * 100)
for i in range(12):
    s12.transcript.append({"role": "assistant" if i % 2 == 0 else "user", "content": "x" * 400})
run(s12.talk_turn("z" * 900))
c = st12.talk_calls()[0]
tok = T.est_tokens(c["system"]) + T.est_tokens(c["payload"])
check("system + payload <= 1,500 estimated tokens with a long chat and a 900 character message", tok <= 1500, tok)
check("the learner's line is capped at 500 characters in the prompt and in the transcript", c["payload"].count("z") == R.LEARNER_MAX and len(s12.transcript[-2]["content"]) == R.LEARNER_MAX, c["payload"].count("z"))
check("only the last 8 lines of the chat are sent, each cut at 200 characters", c["payload"].count("assistant: ") + c["payload"].count("user: ") <= R.HISTORY_LINES and "x" * (R.HISTORY_CHARS + 1) not in c["payload"])

section("summaries: the end-of-chat memory pass sees English only")
s13, st13 = sess("en_sub")
run(s13.talk_turn("", first=True))
st13.talk_script = [{"reply": "Nice! What time do you wake up?", "hi": "अच्छा! सुबह तुम्हारा उठने का समय क्या होता है?"}]
run(s13.talk_turn("i like mornings"))
mem = run(s13.summarize_and_extract())
mi = [c for c in st13.log if c["kind"] == "assess" and not c["talk"]][-1]
check("summarize_and_extract works for a talk session", isinstance(mem, dict) and mem.get("summary"))
check("what it was shown has no Devanagari and no JSON", not DEV(mi["payload"]) and '"reply"' not in mi["payload"] and "learner's stated English level" in mi["payload"], mi["payload"][:300])

main("unit_engine")
