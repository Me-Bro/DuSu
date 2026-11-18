"""Talk - what one model reply becomes (pure: no database, no network, no model): the prompt and its token budget, the walk's own rule for a usable reply, the cleaning of `reply` / `hi`,
and above all the verification of `fix` by Grammar Coach's own machinery.  Run from the repo root:  python3 tests/talk/unit_reply.py"""
import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "tests", "talk"))

from _h import check, section, main                      # noqa: E402
import fixtures as F                                      # noqa: E402
from app.interview import prompts as P                    # noqa: E402
from app.talk import reply as R, topics as T              # noqa: E402

DEV = lambda s: any("ऀ" <= c <= "ॿ" for c in s)   # noqa: E731

# ------------------------------------------------------------------------------------------------------------------- the prompt
section("talk_system: contents")
topic = F.row("A1", 0)
sys_sub = P.talk_system(topic, "en_sub", "Ann", "A1", "works as: a teacher", "Present Simple")
sys_en = P.talk_system(topic, "en", "Ann", "B1", "works as: a teacher", "Present Simple")
check("the topic's title, vocabulary and starters are in the prompt", topic["title"]["en"] in sys_sub and "morning" in sys_sub and topic["starters"][0]["en"] in sys_sub)
check("the grammar focus is named (not the id)", "Present Simple" in sys_sub and "present_simple" not in sys_sub)
check("the learner's name and note are in the prompt", "Ann" in sys_sub and "a teacher" in sys_sub)
check("exactly ONE JSON object is asked for", "ONLY one JSON object" in sys_sub and "ONLY one JSON object" in sys_en)
check("en_sub asks for `hi` and `w`; en does NOT (it would cost tokens for nothing)", '"hi"' in sys_sub and '"w"' in sys_sub and '"hi"' not in sys_en and '"w"' not in sys_en)
check("the English-only prompt has no Devanagari at all", not DEV(sys_en))
check("the subtitle prompt carries the Hindi rules (तुम, never आप / तू, no gendered verb, woman)", "तुम" in sys_sub and "आप" in sys_sub and "तू" in sys_sub and "woman" in sys_sub and "reveals the learner's gender" in sys_sub)
check("the prompt forbids fixing recogniser artifacts", "capital letters, punctuation" in sys_sub and "NEVER fix" in sys_sub)
check("the prompt asks for at most one fix", "Never more than one fix" in sys_sub)
check("the prompt keeps DuSu non-romantic", "never romantic" in sys_sub)
check("support level shapes the difficulty note", "beginner" in sys_sub and "comfortable" in sys_en and "beginner" not in sys_en)
check("the band note follows the topic's band", "Topic level A1" in sys_sub and "Topic level B1" in P.talk_system(F.row("B1", 0), "en", "", "", "", ""))
check("no name -> 'the learner', never the word 'there'", "the learner" in P.talk_system(topic, "en", "there", "", "", "") and "with there" not in P.talk_system(topic, "en", "there", "", "", ""))
check("an empty note adds no 'About the learner' line", "About the learner" not in P.talk_system(topic, "en", "Ann", "A1", "", ""))

section("talk_system: the token budget (<= ~1.5K tokens for the whole call)")
worst = copy.deepcopy(topic)
worst["title"]["en"] = "T" * 60
worst["starters"] = [{"en": "word " * 17, "hi": "x"} for _ in range(3)]
worst["vocab"] = [{"en": "w" * 28, "hi": "x"} for _ in range(8)]
note = R.clean_note("n" * 400)
name = R.clean_name("N" * 100)
check("clean_name caps at 40, clean_note at 240", len(name) == 40 and len(note) == 240)
for sup in ("en_sub", "en"):
    sysw = P.talk_system(worst, sup, name, "B1", note, "Present Perfect Continuous")
    # the payload at its worst: the whole chat window (8 lines of 200 characters) + a 500 character learner message
    payload = "conversation so far:\n" + "\n".join("user: " + "q" * R.HISTORY_CHARS for _ in range(R.HISTORY_LINES)) + "\n\nlearner just said: " + "z" * R.LEARNER_MAX
    n_sys, n_all = T.est_tokens(sysw), T.est_tokens(sysw) + T.est_tokens(payload)
    check(f"{sup}: the worst-case system prompt is <= 850 estimated tokens", n_sys <= 850, n_sys)
    check(f"{sup}: system + the worst-case payload is <= 1,500 estimated tokens", n_all <= 1500, n_all)
    check(f"{sup}: the output budget is <= 500 tokens", R.MAX_TOKENS[sup] <= 500, R.MAX_TOKENS)
check("a normal en_sub call (a real topic, a 6 turn chat) is well under 1,000 tokens", T.est_tokens(sys_sub) + T.est_tokens("conversation so far:\n" + "\n".join("user: I went to the market yesterday with my friend" for _ in range(6))) < 1000)

# ------------------------------------------------------------------------------------------------------------------- the walk's own rule
section("check(): the walk's rule for a usable reply")
check("an English reply is usable", R.check({"reply": "Good morning, how are you?"}) is None)
check("a Hindi-only reply is rejected (so the next model answers)", R.check({"reply": "बहुत अच्छा, आज क्या किया?"}) == "not_english")
check("a MOSTLY-Hindi reply with a few English letters is rejected too (Devanagari share >= 50%)", R.check({"reply": "OK बहुत अच्छा लगा आज तुमने क्या किया ज़रा बताओ"}) == "not_english")
check("a mostly-English reply with one Hindi word is accepted", R.check({"reply": "That is nice, I like it very much बहुत"}) is None)
check("a missing / empty / non-string reply is rejected", R.check({}) == "missing:reply" and R.check({"reply": "  "}) == "missing:reply" and R.check({"reply": 5}) == "missing:reply" and R.check(None) == "missing:reply")
check("a reply of one letter is rejected", R.check({"reply": "A"}) == "not_english")
check("English with a little Hindi passes the walk (the cleaner strips the Hindi sentence afterwards)", R.check({"reply": "Nice! What did you eat? बहुत अच्छा।"}) is None)
check("the schema the walk enforces is exactly {'reply': 'str+'}", R.SCHEMA == {"reply": "str+"})

# ------------------------------------------------------------------------------------------------------------------- cleaning
section("clean_reply()")
check("plain English passes through", R.clean_reply("Nice! What did you eat?") == "Nice! What did you eat?")
check("markup, backticks and braces are removed", "<" not in R.clean_reply("Nice <b>one</b>! `What` {did} you eat?") and "`" not in R.clean_reply("Nice `one`! What did you eat?"))
check("control characters are removed", "\x00" not in R.clean_reply("Nice\x00 one! What did you eat?") and "\x07" not in R.clean_reply("Nice\x07 one! What?"))
check("a Devanagari sentence is stripped from the reply", R.clean_reply("Nice! बहुत अच्छा लगा। What did you eat?") == "Nice! What did you eat?", R.clean_reply("Nice! बहुत अच्छा लगा। What did you eat?"))
check("a reply with no English left is unusable ('')", R.clean_reply("बहुत अच्छा लगा। आगे बताओ।") == "")
check("empty / None / whitespace -> ''", R.clean_reply("") == "" and R.clean_reply(None) == "" and R.clean_reply("   ") == "")
long_ = "This is a sentence. " * 40
c = R.clean_reply(long_)
check("a long reply is cut at a sentence end within 420 characters", 40 <= len(c) <= R.REPLY_MAX and c.endswith("."), (len(c), c[-30:]))
check("surrounding quotes are stripped", R.clean_reply('"Nice! What did you eat?"') == "Nice! What did you eat?")
check("a JSON fragment is not shown as markup (braces and brackets are gone)", not any(ch in R.clean_reply('Nice {"x": [1]} what?') for ch in "{}[]"))
check("whitespace is collapsed", R.clean_reply("Nice!   \n\n  What\tdid you eat?") == "Nice! What did you eat?")

section("clean_hi(): the Hindi subtitle is shown only if it is good Hindi")
check("good Devanagari with Latin everyday words is kept", R.clean_hi("अच्छा! तुमने क्या खाया? Lunch में क्या था?") is not None)
check("no Devanagari -> None", R.clean_hi("accha, tumne kya khaya?") is None)
check("an आप form -> None", R.clean_hi("अच्छा! आपने क्या खाया?") is None)
check("a तू form -> None", R.clean_hi("अच्छा! तूने क्या खाया?") is None)
check("a second-person verb that guesses gender -> None", R.clean_hi("अच्छा! तुम क्या खाते हो?") is None and R.clean_hi("अच्छा! तुम कहाँ जाओगे?") is None)
check("DuSu's own feminine verb is fine", R.clean_hi("मैं समझ गई! तुमने क्या खाया?") is not None)
check("a mostly romanised line (< 30% Devanagari) -> None", R.clean_hi("Hello my friend how are you doing today and what did you eat ना") is None)
check("too long -> None", R.clean_hi("अच्छा " * 200) is None)
check("empty / None -> None", R.clean_hi("") is None and R.clean_hi(None) is None)
check("markup is stripped from a kept subtitle", "<" not in (R.clean_hi("अच्छा <b>लगा</b>! तुमने क्या खाया?") or ""))

# ------------------------------------------------------------------------------------------------------------------- fix verification
section("verify_fix(): a real slip is shown")
REAL = [
    ("yesterday i go to the market and i buy some vegetable", {"q": "i go", "f": "I went", "r": "Yesterday means past: use went."}, "i go", "I went"),
    ("he go to office every day", {"q": "he go", "f": "he goes", "r": "He needs goes."}, "he go", "he goes"),
    ("she is go to school", {"q": "is go", "f": "is going", "r": "After is use going."}, "is go", "is going"),
    ("I am a engineer in a software company", {"q": "a engineer", "f": "an engineer", "r": "Use an before a vowel sound."}, "a engineer", "an engineer"),
    ("they was happy yesterday", {"q": "they was", "f": "they were", "r": "They takes were."}, "they was", "they were"),
    ("I have went to the temple", {"q": "have went", "f": "have gone", "r": "After have use gone."}, "have went", "have gone"),
]
for msg, fx, q, f in REAL:
    out = R.verify_fix(msg, fx, level="A1", support="en")
    check(f"{msg!r}: {q!r} -> {f!r}", out is not None and out["q"] == q and out["f"] == f and out["r"] == fx["r"], out)
out = R.verify_fix("yesterday i go to the market", {"q": "i go", "f": "I went", "r": "Past.", "w": "Yesterday का मतलब past है, इसलिए went।"}, level="A1", support="en_sub")
check("the result carries q, f, r, w, c and the corrected message built by code", out and set(out) == {"q", "f", "r", "w", "c", "full"} and out["full"] == "yesterday I went to the market" and out["c"] in ("sure", "likely"), out)
check("`q` is the learner's own wording, exactly as written (case kept)", R.verify_fix("Yesterday I Go to the market", {"q": "i go", "f": "I went", "r": "x"}, level="A1", support="en")["q"] == "I Go")
check("a beginner (A1) sees the fix too (the level floor is A2, see the module docstring)", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x"}, level="A1", support="en") is not None)
check("an unknown / empty level works", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x"}, level="", support="en") is not None and R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x"}, level=None, support="en") is not None)
check("a B2 learner is checked the same way", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x"}, level="B2", support="en") is not None)
check("a sure mark (a rule check on the same words agrees) says so", R.verify_fix("I am a engineer", {"q": "a engineer", "f": "an engineer", "r": "x"}, level="A2", support="en")["c"] == "sure")

section("verify_fix(): what a speech recogniser may have chosen differently is NEVER a fix")
ARTIFACTS = [
    ("capital letter only", "i am fine today", {"q": "i am fine", "f": "I am fine"}),
    ("a capital at the start of the quote", "my name is ravi", {"q": "my name", "f": "My name"}),
    ("a full stop added", "i am fine", {"q": "i am fine", "f": "i am fine."}),
    ("a comma added", "yes I like it", {"q": "yes I like it", "f": "yes, I like it"}),
    ("a homophone (there / their)", "i want to go there", {"q": "there", "f": "their"}),
    ("a homophone (to / too)", "i like it to", {"q": "to", "f": "too"}),
    ("a numeral written as a word", "i have two brothers", {"q": "two", "f": "2"}),
    ("a numeral written as digits", "i have 2 brothers", {"q": "2", "f": "two"}),
    ("a contraction", "i do not know", {"q": "do not", "f": "don't"}),
    ("a contraction the other way", "i don't know", {"q": "don't", "f": "do not"}),
    ("a repeated word", "i i like it", {"q": "i i", "f": "i"}),
    ("a filler word", "i um like it", {"q": "i um like", "f": "i like"}),
    ("an identical quote and fix", "he goes home", {"q": "he goes", "f": "he goes"}),
]
for name, msg, fx in ARTIFACTS:
    check(f"{name} is dropped", R.verify_fix(msg, dict(fx, r="x"), level="B1", support="en") is None, R.verify_fix(msg, dict(fx, r="x"), level="B1", support="en"))

section("verify_fix(): anything that cannot be located, bounded and checked is dropped")
check("a quote that is not in the message is dropped", R.verify_fix("i like mangoes", {"q": "i love", "f": "I like", "r": "x"}, level="B1", support="en") is None)
check("a quote that is only PART of a word is dropped (whole tokens only)", R.verify_fix("he goes to office", {"q": "he go", "f": "he goes", "r": "x"}, level="B1", support="en") is None)
check("a quote of more than 8 words is dropped", R.verify_fix("one two three four five six seven eight nine ten", {"q": "one two three four five six seven eight nine", "f": "x y", "r": "x"}, level="B1", support="en") is None)
check("an edit that rewrites the whole phrase is dropped (edit distance bound)", R.verify_fix("he go to the old market", {"q": "he go to the old market", "f": "she travelled yesterday evening", "r": "x"}, level="B1", support="en") is None)
check("an empty fix is dropped (a deletion is not offered)", R.verify_fix("he go to office", {"q": "he go", "f": "", "r": "x"}, level="B1", support="en") is None)
check("a missing f / q is dropped", R.verify_fix("he go to office", {"q": "he go", "r": "x"}, level="B1", support="en") is None and R.verify_fix("he go to office", {"f": "he goes", "r": "x"}, level="B1", support="en") is None)
check("non-string q / f are dropped", R.verify_fix("he go to office", {"q": 5, "f": ["x"], "r": "x"}, level="B1", support="en") is None and R.verify_fix("he go", {"q": ["he"], "f": "he", "r": "x"}, level="B1", support="en") is None)
check("an over-long quote (> 80 characters) is dropped", R.verify_fix("a " * 60, {"q": "a " * 60, "f": "b", "r": "x"}, level="B1", support="en") is None)
check("null / list of junk / a string / a number are dropped", all(R.verify_fix("he go to office", v, level="B1", support="en") is None for v in (None, "he goes", 5, [], [None, 5, "x"], {})))
check("a fix on a Hindi-only message is dropped (nothing English to fix)", R.verify_fix("मैं कल बाज़ार गया था", {"q": "मैं कल", "f": "I yesterday", "r": "x"}, level="B1", support="en") is None)
check("a Devanagari token inside the quote is never touched", R.verify_fix("i go बाज़ार daily", {"q": "go बाज़ार", "f": "went बाज़ार", "r": "x"}, level="B1", support="en") is None)
check("an empty message / a one-word message gives nothing", R.verify_fix("", {"q": "a", "f": "b"}, level="B1", support="en") is None and R.verify_fix("yes", {"q": "yes", "f": "yeah"}, level="B1", support="en") is None)
check("a swap of one content word for another is a style opinion and is dropped (market -> bazaar)", R.verify_fix("yesterday i go to the market", {"q": "market", "f": "bazaar", "r": "x"}, level="B1", support="en") is None)
check("...but the same swap IS shown when a rule check agrees (make a photo -> take a photo)", (R.verify_fix("i make a photo", {"q": "make", "f": "take", "r": "x"}, level="B1", support="en") or {}).get("c") == "sure")
for msg, q, f in [("i have two brother", "brother", "brothers"), ("she don't like it", "don't", "doesn't"), ("i am agree with you", "am agree", "agree"), ("i discuss about the plan", "discuss about", "discuss"),
                  ("he have a car", "have", "has"), ("i buy it yesterday", "buy", "bought")]:
    check(f"a grammar edit is kept: {q!r} -> {f!r}", R.verify_fix(msg, {"q": q, "f": f, "r": "x"}, level="B1", support="en") is not None)
check("grammar_edit: inflection / irregular / function word yes, a different content word no", R.grammar_edit("he go", "he goes") and R.grammar_edit("have went", "have gone") and R.grammar_edit("a engineer", "an engineer")
      and not R.grammar_edit("market", "bazaar") and not R.grammar_edit("big house", "large house") and not R.grammar_edit("same", "same"))
check("a fix that would INTRODUCE a mistake is dropped (the rule checks see it in the corrected message)", R.verify_fix("she made him cry", {"q": "made him cry", "f": "made him to cry", "r": "x"}, level="B1", support="en") is None)
check("a fix whose corrected message is too long is dropped (token bound)", R.verify_fix("he go", {"q": "he go", "f": "he goes to the big old market near the station on foot daily", "r": "x"}, level="B1", support="en") is None)

section("verify_fix(): at most one fix, and the reasons")
two = [{"q": "nothere", "f": "x", "r": "a"}, {"q": "he go", "f": "he goes", "r": "b"}, {"q": "office", "f": "the office", "r": "c"}]
out = R.verify_fix("he go to office", two, level="B1", support="en")
check("two (three) proposed fixes become ONE, the first that verifies", out is not None and out["q"] == "he go" and out["r"] == "b" and isinstance(out, dict))
check("only the first three proposals are looked at", R.verify_fix("he go to office", [{"q": "x1", "f": "y"}, {"q": "x2", "f": "y"}, {"q": "x3", "f": "y"}, {"q": "he go", "f": "he goes", "r": "late"}], level="B1", support="en") is None)
check("a reason with Devanagari is replaced by the plain fallback", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "इसलिए goes"}, level="B1", support="en")["r"] == "A small grammar fix.")
check("a missing reason gets the plain fallback", R.verify_fix("he go to office", {"q": "he go", "f": "he goes"}, level="B1", support="en")["r"] == "A small grammar fix.")
check("a reason over 160 characters is replaced", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x" * 200}, level="B1", support="en")["r"] == "A small grammar fix.")
check("support=en never carries `w`, even if the model sent one", "w" not in R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "He के साथ goes आता है।"}, level="B1", support="en"))
check("support=en_sub keeps a good `w`", R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "He के साथ goes आता है।"}, level="B1", support="en_sub").get("w", "").startswith("He के साथ"))
fx = R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "आपको goes लगाना होगा।"}, level="B1", support="en_sub")
check("an `w` with आप is dropped but the fix stays", fx is not None and "w" not in fx)
fx = R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "तुम्हें goes लगाना चाहिए, तुम कर सकते हो।"}, level="B1", support="en_sub")
check("an `w` that guesses gender (सकते हो) is dropped but the fix stays", fx is not None and "w" not in fx)
fx = R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "तुम्हें goes लगाना चाहिए, तुम कर सकते हो।"}, level="B1", support="en_sub")
check("the danda right after हो does not hide a gendered verb (the danda lies inside the Devanagari block)", fx is not None and "w" not in fx)
check("clean_hi catches 'सकते हो।' with the danda too", R.clean_hi("तुम बता सकते हो।") is None and R.clean_hi("तुम क्या करोगी।") is None and R.clean_hi("तुम कहाँ गए हो।") is None)
fx = R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "goes goes goes goes"}, level="B1", support="en_sub")
check("an `w` with no Devanagari is dropped", fx is not None and "w" not in fx)
fx = R.verify_fix("he go to office", {"q": "he go", "f": "he goes", "r": "x", "w": "<b>He</b> के साथ goes आता है।"}, level="B1", support="en_sub")
check("markup in `w` is stripped", fx is not None and "<" not in fx.get("w", ""))

section("shape(): one model object -> what the learner sees")
good_obj = {"reply": "Nice! What did you buy?", "hi": "अच्छा! तुमने क्या खरीदा?", "fix": {"q": "i go", "f": "I went", "r": "Past.", "w": "Yesterday के साथ past आता है।"}}
s_ = R.shape(good_obj, "yesterday i go to the market", support="en_sub", level="A1")
check("en_sub: text, hi and fix", s_ and s_["text"] == "Nice! What did you buy?" and s_["hi"].startswith("अच्छा") and s_["fix"]["f"] == "I went", s_)
s_ = R.shape(good_obj, "yesterday i go to the market", support="en", level="A1")
check("en: NO hi (even though the model sent one), fix without w", s_ and "hi" not in s_ and "w" not in s_["fix"], s_)
bad = dict(good_obj, hi="आपने क्या खरीदा?")
s_ = R.shape(bad, "yesterday i go to the market", support="en_sub", level="A1")
check("a bad subtitle is dropped, the English reply and the fix stay", s_ and "hi" not in s_ and s_["text"] and s_["fix"], s_)
s_ = R.shape(dict(good_obj, fix={"q": "market", "f": "bazaar", "r": "x"}), "yesterday i go to the market", support="en", level="A1")
check("an unverifiable fix is dropped, the reply stays", s_ and "fix" not in s_ and s_["text"], s_)
check("an error object / a non-dict / no reply -> None", R.shape({"error": "scoring_parse_failed"}, "x y", support="en") is None and R.shape(None, "x y", support="en") is None and R.shape([], "x y", support="en") is None and R.shape({"hi": "x"}, "x y", support="en") is None)
check("a reply that is only Hindi -> None", R.shape({"reply": "बहुत अच्छा।"}, "x y", support="en_sub") is None)
check("the shaped dict has only text / hi / fix", set(R.shape(good_obj, "yesterday i go to the market", support="en_sub", level="A1")) <= {"text", "hi", "fix"})

section("learner_note()")
n_ = R.learner_note({"profession": "teacher", "dream": "to speak well", "interests": {"cricket": 1, "music": 1}})
check("profession, dream and interests make one short line", "teacher" in n_ and "speak well" in n_ and "cricket" in n_ and len(n_) <= 300, n_)
check("nothing known -> ''", R.learner_note({}) == "" and R.learner_note(None) == "" and R.learner_note("x") == "")
check("a hostile fact is stripped of markup and capped", "<" not in R.learner_note({"profession": "<script>x</script>" * 20}) and len(R.learner_note({"profession": "x" * 500})) <= 300)
check("interests as a list works too", "chess" in R.learner_note({"interests": ["chess", "tea"]}))
check("clean_learner removes control characters and bracketed annotations, keeps the words", R.clean_learner("hello\x00 [laughs] world") == "hello world")

main("unit_reply")
