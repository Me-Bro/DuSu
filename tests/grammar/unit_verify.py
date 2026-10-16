"""Unit tests for grammar/verify.py (Appendix A4 steps 1-9 + marks_from_hits, build_corrected, display_case, status_of, display_cap, check_smooth).
Uses hand-built Hit / vetoes only - no dependency on detectors.py, segment.py or gating.py.
Run: cd /home/vibhanshu/Desktop/DuSu && PYTHONPATH=backend python3 tests/grammar/unit_verify.py"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _h import check, done, section  # noqa: E402

from app.grammar import catalog, verify as V  # noqa: E402
from app.grammar.text import tokenize  # noqa: E402
from app.grammar.types import Hit, Mark  # noqa: E402


def raw(r, q, f="", c="s", w=""):
    d = {"r": r, "q": q, "f": f, "c": c}
    if w is not None:
        d["w"] = w
    return d


def ver(text, raws, **kw):
    kw.setdefault("level", "B1")
    kw.setdefault("source", "whisper")
    return V.verify_marks(text, raws, **kw)


def keys_of(s):
    return [t.key for t in tokenize(s)]


# =============================================================================================== step 1: shape
section("step 1 - shape")
T = "he go to the office every day"
check("baseline: a good mark survives", len(ver(T, [raw("ag.s_missing_3p", "he go", "he goes")])) == 1)
check("q of 81 chars dropped", ver("x " + "a" * 81, [raw("other", "a" * 81, "b")]) == [])
check("q of exactly 80 chars is not dropped by shape", V.MAX_Q_CHARS == 80)
check("f over 100 chars dropped", ver(T, [raw("ag.s_missing_3p", "he go", "he goes " + "x" * 100)]) == [])
m = ver(T, [raw("ag.s_missing_3p", "he go", "he goes", w="word " * 15)])
check("w of 15 words is dropped, the mark stays", len(m) == 1 and m[0].why == "", m)
m = ver(T, [raw("ag.s_missing_3p", "he go", "he goes", w="go is a verb so it needs s")])
check("w of 8 words kept", len(m) == 1 and m[0].why == "go is a verb so it needs s")
check("w of exactly 14 words kept", ver(T, [raw("ag.s_missing_3p", "he go", "he goes", w=" ".join(["w"] * 14))])[0].why != "")
check("non-dict raw ignored", ver(T, ["x", 3, None, [], raw("ag.s_missing_3p", "he go", "he goes")]) != [])
check("raw_marks not a list", ver(T, "nope") == [] and ver(T, None) == [])
check("q missing / empty / non-str", ver(T, [{"r": "ag.s_missing_3p", "f": "x"}, raw("ag.s_missing_3p", "", "x"), raw("ag.s_missing_3p", 5, "x"), raw("ag.s_missing_3p", ["he"], "x")]) == [])
check("f None treated as empty (deletion rule)", len(ver("my brother he is a doctor", [{"r": "st.double_subject", "q": "he", "f": None, "c": "s"}])) == 1)
check("f non-str dropped", ver(T, [{"r": "ag.s_missing_3p", "q": "he go", "f": 7, "c": "s"}]) == [])
check("q only punctuation dropped", ver(T, [raw("ag.s_missing_3p", "...", "x")]) == [])
check("c other than s -> likely", ver(T, [raw("ag.s_missing_3p", "he go", "he goes", c="x")])[0].conf == "likely")
check("empty sentence / no tokens", ver("", [raw("other", "a", "b")]) == [] and ver("...", [raw("other", "a", "b")]) == [])
check("non-str sentence", ver(None, [raw("other", "a", "b")]) == [])
many = [raw("ag.s_missing_3p", "he go", "he goes")] * 50 + [raw("tn.past_marker", "office", "x")] * 3
check("raw marks are capped", len(ver(T, many)) <= V.MAX_RAW)

# =============================================================================================== step 2: locate
section("step 2 - locate")
m = ver("Yesterday, I go to market.", [raw("tn.past_marker", "I go", "I went")])
check("found; indices + char offsets", len(m) == 1 and (m[0].i, m[0].j) == (1, 3) and (m[0].start, m[0].end) == (11, 15) and m[0].quote == "I go", m)
m = ver("He Go To school every day", [raw("ag.s_missing_3p", "he go", "he goes")])
check("case-insensitive; the quote keeps the original case", len(m) == 1 and m[0].quote == "He Go", m)
check("quote not found -> dropped", ver(T, [raw("ag.s_missing_3p", "she go", "she goes")]) == [])
check("quote not contiguous -> dropped", ver(T, [raw("ag.s_missing_3p", "he office", "he goes")]) == [])
check("whole tokens: 'he go' must not match inside 'she goes'", ver("she goes to school", [raw("ag.s_missing_3p", "he go", "he goes")]) == [])
check("whole tokens: 'go' not inside 'goes'", ver("she goes to school", [raw("tn.past_marker", "go", "went")]) == [])
check("whole tokens: 'is' not inside 'this'", ver("this works", [raw("ag.aux_form", "is", "are")]) == [])
m = ver("the cat and the dog and the cat", [raw("wd.collocation", "the cat", "a cat")])
check("repeated quote -> FIRST occurrence", len(m) == 1 and (m[0].i, m[0].j) == (0, 2), m)
m = ver("he go and he go", [raw("ag.s_missing_3p", "he go", "he goes")])
check("first occurrence of a repeated quote (second ignored)", len(m) == 1 and m[0].i == 0)
m = ver("he dont like tea", [raw("ag.he_dont", "he don't", "he doesn't")])
check("apostrophe-less 'dont' located by the quote with an apostrophe", len(m) == 1 and m[0].quote == "he dont", m)
m = ver("he don't like tea", [raw("ag.he_dont", "he don't", "he doesn't")])
check("apostrophe token kept whole", len(m) == 1 and m[0].quote == "he don't" and (m[0].i, m[0].j) == (0, 2))
check("apostrophe is part of the token: 'don' is not 'don't'", ver("he don't like tea", [raw("ag.he_dont", "he don", "he does")]) == [])
check("curly apostrophe in the sentence", len(ver("he don’t like tea".replace("’", "'"), [raw("ag.he_dont", "he don't", "he doesn't")])) == 1)
m = ver("I have 2 apples and 3 pears", [raw("wd.collocation", "2 apples", "two apples")])
check("digits are tokens (artifact numeral -> dropped)", m == [])
m = ver("he go, to office.", [raw("ag.s_missing_3p", "he go,", "he goes,")])
check("quote with trailing punctuation still located (punctuation-insensitive)", len(m) == 1 and m[0].quote == "he go" and (m[0].i, m[0].j) == (0, 2), m)

# =============================================================================================== step 3: bounds
section("step 3 - bounds")
check("quote of 8 tokens ok (edit 1)", len(ver("a b c d e f g h i", [raw("wd.collocation", "a b c d e f g h", "a b c d e f g z")])) == 1)
check("quote of 9 tokens dropped", ver("a b c d e f g h i j", [raw("wd.collocation", "a b c d e f g h i", "a b c d e f g h z")]) == [])
check("fix of 11 tokens dropped", ver("go", [raw("wd.collocation", "go", "a b c d e f g h i j k")]) == [])
check("edit distance 1 for 1-token quote ok (go -> went)", len(ver("they go home", [raw("tn.past_marker", "go", "went")])) == 1)
check("edit distance 2 for a 1-token quote dropped (go -> went home)", ver("they go home", [raw("tn.past_marker", "go", "went to")]) == [])
check("2-token quote allows 2 edits", len(ver("yesterday he go home", [raw("tn.past_marker", "he go", "she went")])) == 1)
check("2-token quote with 3 edits dropped", ver("yesterday he go home", [raw("tn.past_marker", "he go", "she went there today")]) == [])
check("insertion within bounds (in morning -> in the morning)", len(ver("i wake up in morning", [raw("ar.the_missing", "in morning", "in the morning")])) == 1)
check("edit cap 4 even for long quotes", ver("a b c d e f g h", [raw("wd.collocation", "a b c d e f g h", "v w x y z f g h")]) == [])
# word-order rules
m = ver("what you want", [raw("st.question_order", "what you want", "what do you want")])
check("word order: + 'do' allowed", len(m) == 1, m)
m = ver("tell me where is the station", [raw("st.embedded_order", "where is the station", "where the station is")])
check("word order: pure reorder allowed", len(m) == 1, m)
check("word order: a new content word dropped", ver("what you want", [raw("st.question_order", "what you want", "what do you really want")]) == [])
check("word order: > 6 tokens dropped", ver("tell me where is the big old station in the city", [raw("st.embedded_order", "where is the big old station in", "where the big old station is in")]) == [])
m = ver("i yesterday went home", [raw("st.adverb_position", "i yesterday went", "yesterday i went")])
check("adverb position: reorder only", len(m) == 1, m)
m = ver("i very like it", [raw("st.adverb_position", "i very like it", "i like it very much")])
check("adverb position: 'much' allowed", len(m) == 1, m)
# empty fix
check("empty f dropped for a non-deletion rule", ver(T, [raw("ag.s_missing_3p", "he go", "")]) == [])
check("empty f allowed for pr.extra_prep", len(ver("we discuss about the plan", [raw("pr.extra_prep", "about", "")])) == 1)
m = ver("my brother he is a doctor", [raw("st.double_subject", "he", "")])
check("empty f allowed for st.double_subject", len(m) == 1 and m[0].fix == "", m)
check("empty f allowed for ar.the_overuse", len(ver("the life is beautiful", [raw("ar.the_overuse", "the", "")], level="B1")) == 1)
check("empty f allowed for md.can_able", len(ver("i can able to swim", [raw("md.can_able", "able to", "")])) == 1)
check("empty f for 'other' dropped", ver(T, [raw("other", "he", "")]) == [])

# =============================================================================================== step 4: artifacts
section("step 4 - artifact-only")
art = [
    ("their", "there", "their house is big"), ("there", "their", "there house is big"), ("they're", "their", "they're house is big"),
    ("five", "5", "i have five apples"), ("5", "five", "i have 5 apples"), ("twenty five", "25", "i am twenty five years old"),
    ("don't", "do not", "i don't know"), ("do not", "don't", "i do not know"), ("dont", "don't", "i dont know"),
    ("i", "I", "i am happy"), ("Hello", "hello", "Hello there my friend"), ("its", "it's", "its a nice day"), ("to", "too", "me to went"),
    ("first", "1st", "the first day"), ("the the", "the", "the the day is good"), ("um go", "go", "um go home now"), ("your", "you're", "your right"),
    ("then", "than", "better then me"), ("know", "no", "i know it"), ("write", "right", "write now"), ("hear", "here", "come hear now"),
    ("who's", "whose", "who's book is this"), ("I'm", "I am", "I'm happy"), ("can't", "cannot", "i can't go"), ("ten", "10", "ten people came"),
    ("third", "3rd", "the third floor"), ("first", "first,", "first thing"),
]
for qq, ff, txt in art:
    check(f"artifact dropped: {qq!r} -> {ff!r}", ver(txt, [raw("other", qq, ff)]) == [] and ver(txt, [raw("wd.collocation", qq, ff)]) == [])
check("a real fix survives (go -> went)", len(ver("yesterday i go home", [raw("tn.past_marker", "go", "went")])) == 1)
check("a real homophone ERROR is not an artifact when the words differ in more than the class (go -> goes)", not V.is_artifact_only(["go"], ["goes"]))
check("is_artifact_only identical", V.is_artifact_only(["a"], ["a"]))
check("is_artifact_only: numerals words <-> digits both ways", V.is_artifact_only(["twenty", "one"], ["21"]) and V.is_artifact_only(["21"], ["twenty", "one"]))
check("is_artifact_only: different numbers are not", not V.is_artifact_only(["five"], ["6"]))
check("is_artifact_only: 'they are' vs 'they're'", V.is_artifact_only(["they", "are"], ["they're"]))
check("is_artifact_only: empty vs fillers", V.is_artifact_only(["um"], []))
check("is_artifact_only: a different word", not V.is_artifact_only(["go"], ["went"]))

# =============================================================================================== step 5: rule id + guard
section("step 5 - rule id")
m = ver("yesterday i go home", [raw("zz.not_a_rule", "go", "went")])
check("unknown rule -> other", len(m) == 1 and m[0].rule == "other", m)
check("other: family, severity, weight defaults", m[0].family == "other" and m[0].severity == "error" and m[0].weight == 1)
check("rule id with whitespace / case normalised? unknown", ver(T, [raw("", "he go", "he goes")])[0].rule == "other")
check("non-str rule -> other", ver(T, [{"r": 7, "q": "he go", "f": "he goes", "c": "s"}])[0].rule == "other")
check("known rule kept", ver(T, [raw("ag.s_missing_3p", "he go", "he goes")])[0].rule == "ag.s_missing_3p")
# guard: articles
check("guard ar.a_an ok", ver("a apple a day", [raw("ar.a_an", "a apple", "an apple")])[0].rule == "ar.a_an")
m = ver("a apple a day", [raw("ar.the_missing", "a apple", "an apple")])
check("sibling relabel: the_missing -> a_an", len(m) == 1 and m[0].rule == "ar.a_an", m)
m = ver("i am engineer", [raw("ar.missing_a", "engineer", "an engineer")])
check("guard ar.missing_a ok (insertion of an article)", m and m[0].rule == "ar.missing_a", m)
m = ver("i am engineer", [raw("ar.missing_a", "engineer", "a doctor")])
check("guard fails on a word swap (and bounds drop it)", m == [] or m[0].rule == "other", m)
# guard: prepositions
check("guard pr.time_in_on_at ok", ver("i will come in monday", [raw("pr.time_in_on_at", "in monday", "on monday")])[0].rule == "pr.time_in_on_at")
m = ver("i will come in monday", [raw("ag.he_dont", "in monday", "on monday")])
check("guard: preposition change under an agreement rule -> other (no sibling fits)", len(m) == 1 and m[0].rule == "other", m)
h = Hit("pr.time_in_on_at", 3, 5, ("on", "monday"), det="D16", solo=True)
m = ver("i will come in monday", [raw("ag.he_dont", "in monday", "on monday")], hits=[h])
check("guard failure + a solo hit on the span names the rule", len(m) == 1 and m[0].rule == "pr.time_in_on_at", m)
check("pr.extra_prep guard", ver("we discuss about plan", [raw("pr.extra_prep", "about", "")])[0].rule == "pr.extra_prep")
m = ver("we discuss about plan", [raw("pr.extra_prep", "plan", "program")])
check("pr.extra_prep guard fails on a noun swap (-> other)", len(m) == 1 and m[0].rule == "other", m)
# guard: verbs
check("guard verb irregular (go -> went)", ver("yesterday i go", [raw("tn.past_marker", "go", "went")])[0].rule == "tn.past_marker")
check("guard have seen -> saw", ver("i have seen him yesterday", [raw("tn.pp_finished", "have seen", "saw")])[0].rule == "tn.pp_finished")
check("guard did you went -> go", ver("did you went there", [raw("tn.did_past", "did you went", "did you go")])[0].rule == "tn.did_past")
check("guard they was -> were", ver("they was late", [raw("ag.aux_form", "they was", "they were")])[0].rule == "ag.aux_form")
check("guard he don't -> doesn't", ver("he don't like tea", [raw("ag.he_dont", "he don't", "he doesn't")])[0].rule == "ag.he_dont")
check("guard am knowing -> know", ver("i am knowing him", [raw("tn.cont_misuse", "am knowing", "know")])[0].rule == "tn.cont_misuse")
check("guard since five years -> for five years", ver("i know him since five years", [raw("tn.since_for", "since five years", "for five years")])[0].rule == "tn.since_for")
check("guard if it will rain -> rains", ver("if it will rain i stay", [raw("tn.if_will", "it will rain", "it rains")])[0].rule == "tn.if_will")
check("guard can able to -> can", ver("i can able to swim", [raw("md.can_able", "can able to swim", "can swim")])[0].rule == "md.can_able")
m = ver("he go to the office", [raw("tn.did_past", "office", "bank")])
check("a noun swap under a verb rule fails the guard (-> other)", len(m) == 1 and m[0].rule == "other", m)
# guard: nouns
check("guard informations -> information", ver("i need some informations", [raw("wd.noun_number", "informations", "information")])[0].rule == "wd.noun_number")
check("guard much people -> many people", ver("much people came", [raw("wd.much_many", "much people", "many people")])[0].rule == "wd.much_many")
check("guard one of my friend -> friends", ver("one of my friend came", [raw("ag.quantifier_number", "friend", "friends")])[0].rule == "ag.quantifier_number")
m = ver("i need some informations", [raw("ag.quantifier_number", "informations", "information")])
check("the guard is class-level: a noun inflection under a noun-inflection rule of another family is accepted as asked", m[0].rule == "ag.quantifier_number", m)
# guard: reorder + aux
check("question_order guard", ver("what you want", [raw("st.question_order", "what you want", "what do you want")])[0].rule == "st.question_order")
m = ver("tell me where is the station", [raw("st.question_order", "where is the station", "where the station is")])
check("a reorder under a sibling structure rule keeps a structure rule (relabel to embedded_order)", len(m) == 1 and m[0].rule == "st.question_order", m)
# ind.lexicon
LEX = {"prepone": "move earlier", "do the needful": "please take care of it", "revert back": "reply"}
m = ver("please prepone the meeting", [raw("ind.lexicon", "prepone", "advance")], lex=LEX)
check("ind.lexicon: q in lexicon, the fix comes from the lexicon not the model", len(m) == 1 and m[0].fix == "move earlier" and m[0].rule == "ind.lexicon#prepone", m)
check("ind.lexicon: severity natural, weight 1", m[0].severity == "natural" and m[0].weight == 1)
check("ind.lexicon: q not in lexicon -> dropped", ver("please postpone the meeting", [raw("ind.lexicon", "postpone", "delay")], lex=LEX) == [])
check("ind.lexicon: empty lexicon -> dropped", ver("please prepone the meeting", [raw("ind.lexicon", "prepone", "x")], lex={}) == [])
m = ver("kindly do the needful", [raw("ind.lexicon", "do the needful", "")], lex=LEX)
check("ind.lexicon: multi-token entry, model fix empty is fine", len(m) == 1 and m[0].fix == "please take care of it" and m[0].rule == "ind.lexicon#do_the_needful", m)
m = ver("please prepone the meeting", [raw("ind.lexicon#prepone", "prepone", "x")], lex={"prepone": {"id": "prepone", "fix": "move earlier"}})
check("ind.lexicon: dict entries", m and m[0].fix == "move earlier" and m[0].rule == "ind.lexicon#prepone")
m = ver("please prepone the meeting", [raw("ind.lexicon", "prepone", "move earlier")], lex={"prepone"})
check("ind.lexicon: set lexicon (no fix) uses the model's fix", m and m[0].fix == "move earlier")
check("ind.lexicon with a lazily-missing lexicon module does not raise", isinstance(ver("please prepone the meeting", [raw("ind.lexicon", "prepone", "move earlier")]), list))

# =============================================================================================== step 6: eligibility
section("step 6 - eligibility")
pf = "i have seen him yesterday"
check("tn.pp_finished (min B1) kept at B1", len(ver(pf, [raw("tn.pp_finished", "have seen", "saw")], level="B1")) == 1)
check("tn.pp_finished dropped at A2", ver(pf, [raw("tn.pp_finished", "have seen", "saw")], level="A2") == [])
check("tn.pp_finished dropped at A1", ver(pf, [raw("tn.pp_finished", "have seen", "saw")], level="A1") == [])
check("level words normalised ('beginner' = A1)", ver(pf, [raw("tn.pp_finished", "have seen", "saw")], level="beginner") == [])
check("level words normalised ('C1' = B2)", len(ver(pf, [raw("tn.pp_finished", "have seen", "saw")], level="C1")) == 1)
check("A1: weight-1 error dropped (ar.a_an)", ver("a apple a day", [raw("ar.a_an", "a apple", "an apple")], level="A1") == [])
check("A1: weight-2 error kept (ar.missing_a)", len(ver("i am engineer", [raw("ar.missing_a", "engineer", "an engineer")], level="A1")) == 1)
check("A1: weight-3 error kept", len(ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], level="A1")) == 1)
check("A2: weight-1 error kept (ar.a_an)", len(ver("a apple a day", [raw("ar.a_an", "a apple", "an apple")], level="A2")) == 1)
check("A1: an unlabelled 'other' mark dropped", ver("yesterday i go", [raw("zz", "go", "went")], level="A1") == [])
check("A2: 'other' mark kept", len(ver("yesterday i go", [raw("zz", "go", "went")], level="A2")) == 1)
check("natural tip dropped at A2", ver("please prepone it", [raw("ind.lexicon", "prepone", "x")], level="A2", lex=LEX) == [])
check("natural tip kept at B1", len(ver("please prepone it", [raw("ind.lexicon", "prepone", "x")], level="B1", lex=LEX)) == 1)
check("polish (st.run_on_frag) dropped at B1", ver("and then i go and then i come", [raw("st.run_on_frag", "and then i go", "i go")], level="B1") == [])
check("polish kept at B2", len(ver("and then i go and then i come", [raw("st.run_on_frag", "and then i go", "i go")], level="B2")) == 1)
# vetoes
check("veto of the same family + overlapping span drops the mark", ver("let him go", [raw("ag.s_missing_3p", "him go", "him goes")], vetoes=[("ag", 1, 3)]) == [])
check("veto of another family keeps it", len(ver("let him go", [raw("ag.s_missing_3p", "him go", "him goes")], vetoes=[("tn", 1, 3)])) == 1)
check("veto of a non-overlapping span keeps it", len(ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], vetoes=[("ag", 3, 6)])) == 1)
check("veto naming the full rule id", ver("let him go", [raw("ag.s_missing_3p", "him go", "him goes")], vetoes=[("ag.s_missing_3p", 1, 3)]) == [])
check("malformed veto entries ignored", len(ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], vetoes=[None, ("ag",), 5])) == 1)
# opaque
check("opaque index in the span drops the mark", ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], opaque=frozenset({1})) == [])
check("opaque index outside the span keeps the mark", len(ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], opaque=frozenset({4}))) == 1)
check("opaque token key", ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], opaque=frozenset({"go"})) == [])
# contested
m = ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], contested=frozenset({"ag.s_missing_3p"}))
check("contested rule: conf forced likely", m[0].conf == "likely")
m = ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], contested=frozenset({"ag.s_missing_3p"}), hits=[Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True)])
check("contested rule: even a solo hit does not upgrade", m[0].conf == "likely")
check("another rule contested: no effect", ver(T, [raw("ag.s_missing_3p", "he go", "he goes")], contested=frozenset({"tn.did_past"}))[0].conf == "sure")

# =============================================================================================== step 7: confidence
section("step 7 - confidence matrix")
S3 = raw("ag.s_missing_3p", "he go", "he goes")          # stt_sensitive
S3l = raw("ag.s_missing_3p", "he go", "he goes", c="l")
HD = Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True)
check("catalogue: ag.s_missing_3p is stt_sensitive, ag.he_dont is not", catalog.get("ag.s_missing_3p").stt_sensitive and not catalog.get("ag.he_dont").stt_sensitive)
check("sensitive rule, model sure, whisper -> sure", ver(T, [S3], source="whisper")[0].conf == "sure")
check("sensitive rule, model sure, gemini -> sure", ver(T, [S3], source="gemini")[0].conf == "sure")
check("sensitive rule, model sure, chrome, no agreement -> likely", ver(T, [S3], source="chrome")[0].conf == "likely")
m = ver(T, [S3], source="chrome", hits=[HD])
check("sensitive rule, model sure, chrome + solo hit -> sure, src both, det kept", m[0].conf == "sure" and m[0].src == "both" and m[0].det == "D2", m)
check("sensitive, chrome, recogniser conf 0.85 -> sure", ver(T, [S3], source="chrome", conf=0.85)[0].conf == "sure")
check("sensitive, chrome, recogniser conf 0.80 -> sure", ver(T, [S3], source="chrome", conf=0.80)[0].conf == "sure")
check("sensitive, chrome, recogniser conf 0.79 -> likely", ver(T, [S3], source="chrome", conf=0.79)[0].conf == "likely")
check("sensitive, chrome, conf 0 (unknown) -> likely", ver(T, [S3], source="chrome", conf=0)[0].conf == "likely")
check("model likely + whisper -> likely", ver(T, [S3l], source="whisper")[0].conf == "likely")
m = ver(T, [S3l], source="chrome", hits=[HD])
check("a solo hit on the same span upgrades likely -> sure", m[0].conf == "sure" and m[0].src == "both", m)
nonsolo = Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", False)
check("a NON-solo hit does not upgrade", ver(T, [S3l], source="chrome", hits=[nonsolo])[0].conf == "likely")
check("a non-solo hit does not count as agreement either", ver(T, [S3], source="chrome", hits=[nonsolo])[0].conf == "likely")
other_span = Hit("ag.s_missing_3p", 4, 6, ("x",), "D2", True)
check("a solo hit on another span does not upgrade", ver(T, [S3l], source="chrome", hits=[other_span])[0].conf == "likely")
other_grp = Hit("pr.time_in_on_at", 0, 2, ("x",), "D16", True)
check("a solo hit of another rule group does not upgrade", ver(T, [S3l], source="chrome", hits=[other_grp])[0].conf == "likely")
same_grp = Hit("ag.aux_form", 0, 2, ("he", "has"), "D3", True)
check("a solo hit of a sibling rule in the group counts as agreement", ver(T, [S3l], source="chrome", hits=[same_grp])[0].conf == "sure")
check("non-sensitive rule, model sure, chrome -> sure", ver("he don't like tea", [raw("ag.he_dont", "he don't", "he doesn't")], source="chrome")[0].conf == "sure")
check("non-sensitive rule, model likely, chrome -> likely", ver("he don't like tea", [raw("ag.he_dont", "he don't", "he doesn't", c="l")], source="chrome")[0].conf == "likely")
OT = raw("other", "he go", "he goes")
check("'other' never sure without agreement (whisper)", ver(T, [OT], source="whisper")[0].conf == "likely")
check("'other' never sure without agreement (chrome, conf 0.99)", ver(T, [OT], source="chrome", conf=0.99)[0].conf == "likely")
m = ver(T, [OT], source="whisper", hits=[HD])
check("'other' with agreement -> sure", m[0].conf == "sure" and m[0].rule == "other", m)
check("a guard-failed relabelled-to-other mark is not sure", ver("i will come in monday", [raw("ag.he_dont", "in monday", "on monday")])[0].conf == "likely")
check("hit list with bad indices ignored", ver(T, [S3l], source="chrome", hits=[Hit("ag.s_missing_3p", 9, 40, (), "D2", True), Hit("ag.s_missing_3p", -1, 2, (), "D2", True)])[0].conf == "likely")

# =============================================================================================== step 8: dedupe / overlap
section("step 8 - dedupe and overlap")
Tt = "yesterday he go to office and she buy a apple"
m = ver(Tt, [raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "HE GO", "he goes")])
check("identical (rule, i, j) merge", len(m) == 1, m)
m = ver(Tt, [raw("ag.s_missing_3p", "he go", "he goes", c="l"), raw("ag.s_missing_3p", "he go", "he goes", c="s")])
check("identical merge keeps the higher prio (sure)", len(m) == 1 and m[0].conf == "sure", m)
m = ver("i have seen him yesterday", [raw("tn.pp_finished", "have seen", "saw"), raw("tn.past_marker", "seen him", "saw him", c="l")])
check("overlap: sure weight-3 beats likely weight-2", len(m) == 1 and m[0].rule == "tn.pp_finished", m)
m = ver("i have seen him yesterday", [raw("tn.past_marker", "seen him", "saw him", c="s"), raw("tn.pp_finished", "have seen", "saw", c="l")])
check("overlap: sure weight-2 (1.0*2=2.0) beats likely weight-3 (0.5*3=1.5)", len(m) == 1 and m[0].rule == "tn.past_marker" and m[0].conf == "sure", m)
w1s = Mark("ar.a_an", 0, 2, 0, 5, "a app", "an app", conf="sure", severity="error", weight=1)
w3l = Mark("ag.he_dont", 1, 3, 2, 8, "x y", "x z", conf="likely", severity="error", weight=3)
kept = V._dedupe_overlap([w1s, w3l])
check("overlap: likely weight-3 (1.5) beats sure weight-1 (1.0)", len(kept) == 1 and kept[0].rule == "ag.he_dont", kept)
m = ver(Tt, [raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "she buy", "she buys")])
check("non-overlapping both kept, in reading order", [x.quote for x in m] == ["he go", "she buy"], m)
m = ver(Tt, [raw("ag.s_missing_3p", "go to", "goes to"), raw("ag.s_missing_3p", "he go", "he goes")])
check("adjacent-overlap (share 'go') keeps one", len(m) == 1)
m = ver("he go home", [raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "go home", "goes home")])
check("overlap tie -> the earlier / shorter-first deterministic choice", len(m) == 1)
m = ver("yesterday i go to the market", [raw("tn.past_marker", "i go", "i went"), raw("ind.lexicon", "market", "x")], lex={"market": "shop"})
check("natural mark loses to an overlapping... no overlap here: both kept", len(m) == 2)
m = ver("please prepone it", [raw("ind.lexicon", "prepone it", "x", c="s"), raw("wd.collocation", "prepone", "move", c="s")], lex={"prepone it": "move it"})
check("error (weight 2) beats natural (weight 1 * .35) on overlap", len(m) == 1 and m[0].rule == "wd.collocation", m)
check("marks carry catalogue severity / weight / family", ver(T, [S3])[0].severity == "error" and ver(T, [S3])[0].weight == 3 and ver(T, [S3])[0].family == "ag")
check("prio factors", V.prio(Mark("ag.he_dont", 0, 1, 0, 1, "x", "y", conf="sure", severity="error", weight=3)) == 3.0 and
      abs(V.prio(Mark("x", 0, 1, 0, 1, "x", "y", conf="likely", severity="natural", weight=1)) - 0.175) < 1e-9 and
      abs(V.prio(Mark("x", 0, 1, 0, 1, "x", "y", conf="sure", severity="polish", weight=1)) - 0.15) < 1e-9)

# fix case
section("fix text case")
m = ver("yesterday i go home", [raw("tn.past_marker", "go", "Went")])
check("lowercase STT: the fix's first letter follows the quote (lowercase)", m[0].fix == "went", m)
m = ver("Yesterday I Go home", [raw("tn.past_marker", "Go", "went")])
check("capitalised quote -> capitalised fix", m[0].fix == "Went", m)
m = ver("i is a student", [raw("ag.aux_form", "i is", "I am")])
check("the pronoun I stays capital", m[0].fix == "I am", m)

# =============================================================================================== marks_from_hits
section("marks_from_hits")
hits = [Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True), Hit("ar.a_an", 8, 10, ("an", "apple"), "D9", False),
        Hit("ag.he_dont", 5, 7, ("she", "doesn't"), "D1", True)]
m = V.marks_from_hits(Tt, hits, level="B1", source="chrome")
check("only solo hits become marks", sorted(x.rule for x in m) == ["ag.he_dont", "ag.s_missing_3p"] and all(x.src == "rule" for x in m), m)
check("rule marks are sure, src=rule, det kept, fix joined", m[0].conf == "sure" and m[0].fix == "he goes" and m[0].det == "D2" and m[0].src == "rule", m)
check("char offsets / quote", m[0].quote == "yesterday he" and m[0].start == 0, m[0])
check("level filter (A1 drops weight-1)", V.marks_from_hits("a apple a day", [Hit("ar.a_an", 0, 2, ("an", "apple"), "D9", True)], level="A1") == [])
check("level filter (A2 keeps weight-1)", len(V.marks_from_hits("a apple a day", [Hit("ar.a_an", 0, 2, ("an", "apple"), "D9", True)], level="A2")) == 1)
check("min level filter", V.marks_from_hits(pf, [Hit("tn.pp_finished", 1, 3, ("saw",), "D6", True)], level="A2") == [])
check("veto drops", V.marks_from_hits(T, [Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True)], vetoes=[("ag", 0, 1)]) == [])
check("opaque drops", V.marks_from_hits(T, [Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True)], opaque=frozenset({0})) == [])
check("contested -> likely", V.marks_from_hits(T, [Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True)], contested=frozenset({"ag.s_missing_3p"}))[0].conf == "likely")
check("unknown rule / bad indices skipped", V.marks_from_hits(T, [Hit("zz.x", 0, 1, (), "", True), Hit("ag.s_missing_3p", 3, 99, (), "D2", True), Hit("ag.s_missing_3p", 2, 2, (), "D2", True)]) == [])
m = V.marks_from_hits("we discuss about plan", [Hit("pr.extra_prep", 2, 3, (), "T1", True)])
check("deletion hit -> empty fix", len(m) == 1 and m[0].fix == "")
m = V.marks_from_hits("please prepone it", [Hit("ind.lexicon#prepone", 1, 2, ("move", "earlier"), "T3", True)], level="B1")
check("natural hit -> natural mark with its entry id", m[0].severity == "natural" and m[0].rule == "ind.lexicon#prepone" and m[0].fix == "move earlier")
check("overlapping hits resolved", len(V.marks_from_hits("he go home", [Hit("ag.s_missing_3p", 0, 2, ("he", "goes"), "D2", True), Hit("ag.aux_form", 1, 3, ("x",), "D3", True)])) == 1)
check("status_of a rule-only sentence is never 'ok'", V.status_of(V.marks_from_hits(T, []), None) == "unsure")
check("empty text", V.marks_from_hits("", hits) == [])

# =============================================================================================== build_corrected
section("build_corrected (step 9)")
def build(text, raws, **kw):
    kw.setdefault("level", "B1")
    return V.build_corrected(text, ver(text, raws, **kw))


check("one sure mark", build("he go to office", [raw("ag.s_missing_3p", "he go", "he goes")]) == "he goes to office")
tt = "he go to the market and she buy bread"
out = build(tt, [raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "she buy", "she buys")])
check("two marks applied right to left (offsets stay valid)", out == "he goes to the market and she buys bread", out)
out = build("he go to the market and she buy a bread", [raw("ag.s_missing_3p", "he go", "he goes"), raw("wd.noun_number", "a bread", "bread")])
check("a shorter replacement later in the sentence does not move earlier offsets", out == "he goes to the market and she buy bread", out)
out = build("Yesterday I go to market and I buy some vegetable.", [raw("tn.past_marker", "I go", "I went"), raw("tn.past_marker", "I buy", "I bought")])
check("original capitals and punctuation preserved", out == "Yesterday I went to market and I bought some vegetable.", out)
check("lowercase STT stays lowercase", build("he go to office", [raw("ag.s_missing_3p", "he go", "He goes")]) == "he goes to office")
check("capitalised start stays capitalised", build("He go to office.", [raw("ag.s_missing_3p", "He go", "he goes")]) == "He goes to office.")
check("start-of-sentence deletion re-capitalises", build("The life is beautiful", [raw("ar.the_overuse", "the", "")]) == "Life is beautiful")
check("start-of-sentence deletion in lowercase text stays lowercase", build("the life is beautiful", [raw("ar.the_overuse", "the", "")]) == "life is beautiful")
check("mid-sentence deletion removes one space", build("my brother he is a doctor", [raw("st.double_subject", "he", "")]) == "my brother is a doctor")
check("end-of-sentence deletion", build("we discuss about", [raw("pr.extra_prep", "about", "")]) == "we discuss")
check("likely marks are never applied", build("he go to office", [raw("ag.s_missing_3p", "he go", "he goes", c="l")], source="whisper") is None)
check("natural marks are never applied", build("please prepone it", [raw("ind.lexicon", "prepone", "x")], lex=LEX) is None)
check("no marks -> None", V.build_corrected("he goes", []) is None and V.build_corrected("he goes", None) is None)
check("a sure + a likely mark: only the sure one is applied", build(tt, [raw("ag.s_missing_3p", "he go", "he goes"), raw("ag.s_missing_3p", "she buy", "she buys", c="l")]) == "he goes to the market and she buy bread")
mk = Mark("ag.s_missing_3p", 0, 2, 0, 5, "he go", "he " + "goes " * 20, conf="sure", severity="error", weight=3)
check("post-condition: token count > n+6 -> None", V.build_corrected("he go to office", [mk]) is None)
mk = Mark("ag.s_missing_3p", 0, 2, 0, 5, "he go", "he", conf="sure", severity="error", weight=3)
check("post-condition: token count within n-4 is fine", V.build_corrected("he go to office now", [mk]) == "he to office now")
mk = Mark("tn.past_marker", 0, 1, 0, 3, "one", "2020", conf="sure", severity="error", weight=2)
check("post-condition: a new digit token -> None", V.build_corrected("one day", [mk]) is None)
mk = Mark("tn.past_marker", 1, 2, 4, 5, "2", "3", conf="sure", severity="error", weight=2)
check("post-condition: a different digit that is not in the original -> None", V.build_corrected("in 2 days", [mk]) is None)
mk = Mark("wd.collocation", 2, 3, 3, 4, "2", "2", conf="sure", severity="error", weight=2)
check("a no-op replacement -> None (corrected == text)", V.build_corrected("in 2 days", [mk]) is None)
mk = Mark("ag.s_missing_3p", 0, 2, 0, 5, "he go", "he goes", conf="sure", severity="error", weight=3)
new_hit = lambda s: [Hit("ag.s_missing_3p", 0, 1, (), "D2", True)] if "goes" in s else []     # noqa: E731
check("post-condition: recheck finds a NEW solo hit -> None", V.build_corrected("he go to office", [mk], recheck=new_hit) is None)
old_hit = lambda s: [Hit("ag.s_missing_3p", 0, 1, (), "D2", True)]                          # noqa: E731
check("a hit that already existed is not 'new'", V.build_corrected("he go to office", [mk], recheck=old_hit) == "he goes to office")
check("a non-solo hit in recheck is ignored", V.build_corrected("he go to office", [mk], recheck=lambda s: [Hit("x", 0, 1, (), "", False)]) == "he goes to office")
check("recheck raising -> None (safe)", V.build_corrected("he go to office", [mk], recheck=lambda s: 1 / 0) is None)
check("recheck clean -> applied", V.build_corrected("he go to office", [mk], recheck=lambda s: []) == "he goes to office")
bad = Mark("x", 0, 1, 50, 60, "x", "y", conf="sure", severity="error", weight=2)
check("out-of-range offsets ignored", V.build_corrected("he go", [bad]) is None)
a1 = Mark("ag.s_missing_3p", 0, 2, 0, 5, "he go", "he goes", conf="sure", severity="error", weight=3)
a2 = Mark("ag.aux_form", 1, 3, 3, 8, "go to", "goes to", conf="sure", severity="error", weight=3)
res = V.build_corrected("he go to office", [a1, a2])
check("overlapping marks produce a sane sentence", res is not None and keys_of(res).count("goes") <= 1, res)

section("display_case")
check("lowercase STT sentence-cased", V.display_case("yesterday i went to the market") == "Yesterday I went to the market")
check("i'm / i've", V.display_case("i'm sure i've seen it") == "I'm sure I've seen it")
check("after full stops", V.display_case("i came. then i left") == "I came. Then I left")
check("already cased text only has its first letter raised", V.display_case("my friend Rahul came") == "My friend Rahul came")
check("empty", V.display_case("") == "")
check("display only: the case-insensitive key list is unchanged", keys_of(V.display_case("yesterday i went")) == keys_of("yesterday i went"))
check("not a string", V.display_case(None) == "")

section("status_of")
sure_err = Mark("ag.he_dont", 0, 1, 0, 1, "x", "y", conf="sure", severity="error", weight=3)
likely_err = Mark("ag.he_dont", 0, 1, 0, 1, "x", "y", conf="likely", severity="error", weight=3)
nat = Mark("ind.lexicon#a", 0, 1, 0, 1, "x", "y", conf="sure", severity="natural", weight=1)
nat_l = Mark("ind.lexicon#a", 0, 1, 0, 1, "x", "y", conf="likely", severity="natural", weight=1)
pol = Mark("st.run_on_frag", 0, 1, 0, 1, "x", "y", conf="sure", severity="polish", weight=1)
table = [
    ([sure_err], "fix", "fix"), ([sure_err], "ok", "fix"), ([sure_err], "natural", "fix"), ([sure_err, likely_err], "ok", "fix"),
    ([likely_err], "fix", "unsure"), ([likely_err], "ok", "unsure"), ([likely_err, nat], "fix", "unsure"),
    ([nat], "natural", "natural"), ([nat], "ok", "natural"), ([nat_l], "ok", "natural"), ([pol], "ok", "natural"), ([nat, pol], "natural", "natural"),
    ([], "ok", "ok"), ([], "natural", "natural"), ([], "fix", "unsure"), ([], None, "unsure"), ([], "", "unsure"), ([], "weird", "unsure"),
    ([], "skip", "skip"), ([sure_err], "skip", "skip"), ([], "SKIP", "skip"), ([], " OK ", "ok"), ([nat], None, "unsure"), ([sure_err], None, "fix"),
]
for ms, verdict, want in table:
    check(f"status_of({[(x.severity, x.conf) for x in ms]}, {verdict!r}) = {want}", V.status_of(ms, verdict) == want, V.status_of(ms, verdict))
check("'ok' only on the model's verdict", all(V.status_of(ms, v) != "ok" for ms in ([], [nat], [likely_err]) for v in (None, "fix", "skip", "natural", "")))
check("None marks", V.status_of(None, "ok") == "ok")

section("display_cap (display only)")
def E(w, conf="sure", i=0):
    return Mark(f"r{w}", i, i + 1, i * 3, i * 3 + 2, "q", "f", conf=conf, severity="error", weight=w)


def N(i=0):
    return Mark("ind.lexicon#x", i, i + 1, i * 3, i * 3 + 2, "q", "f", conf="sure", severity="natural", weight=1)


def P(i=0):
    return Mark("st.run_on_frag", i, i + 1, i * 3, i * 3 + 2, "q", "f", conf="sure", severity="polish", weight=1)


ms = [E(1, i=0), E(2, i=1), E(3, i=2), N(3), P(4)]
a1s = V.display_cap(ms, "A1", "sentence")
check("A1 sentence: 1 mark, weight >= 2 only, the strongest", len(a1s) == 1 and a1s[0].weight == 3, a1s)
check("A1 turn: 2 marks, no weight-1, no tips", [m.weight for m in V.display_cap(ms, "A1", "turn")] == [2, 3])
check("A1 never shows natural / polish", all(m.severity == "error" for m in V.display_cap([N(), P()], "A1", "turn")) and V.display_cap([N(), P()], "A1", "turn") == [])
check("A2 sentence: 2 errors", len(V.display_cap(ms, "A2", "sentence")) == 2 and all(m.severity == "error" for m in V.display_cap(ms, "A2", "sentence")))
check("A2 turn: 3 errors, weight-1 allowed", len(V.display_cap([E(1, i=k) for k in range(5)], "A2", "turn")) == 3)
b1 = V.display_cap([E(2, i=0), E(2, i=1), N(2), N(3)], "B1", "turn")
check("B1 turn: <= 4 marks, <= 1 natural", len(b1) == 3 and sum(m.severity == "natural" for m in b1) == 1, b1)
check("B1 sentence: <= 2 marks", len(V.display_cap([E(2, i=0), E(2, i=1), E(3, i=2)], "B1", "sentence")) == 2)
check("B1 never shows polish", all(m.severity != "polish" for m in V.display_cap([P(), P(1)], "B1", "turn")))
b2 = V.display_cap([E(2, i=0), E(2, i=1), N(2), N(3), N(4), P(5), P(6)], "B2", "turn")
check("B2 turn: <= 5, natural <= 2, polish <= 1", len(b2) == 5 and sum(m.severity == "natural" for m in b2) == 2 and sum(m.severity == "polish" for m in b2) == 1, b2)
check("B2 sentence: 3 marks", len(V.display_cap([E(2, i=k) for k in range(6)], "B2", "sentence")) == 3)
check("level words normalised ('C1' behaves as B2, '' as B1)", len(V.display_cap([E(2, i=k) for k in range(6)], "C1", "sentence")) == 3 and len(V.display_cap([E(2, i=k) for k in range(6)], "", "sentence")) == 2)
ordered = V.display_cap([E(1, i=5), E(3, i=2), E(2, i=0)], "B2", "turn")
check("returned in input order (chosen by prio)", [m.i for m in ordered] == [5, 2, 0])
kept = V.display_cap([E(2, "likely", 0), E(2, "sure", 1), E(2, "sure", 2)], "A2", "sentence")
check("sure beats likely when trimming", [m.conf for m in kept] == ["sure", "sure"], kept)
check("prio decides which marks survive the cap", [m.weight for m in V.display_cap([E(1, i=0), E(3, i=1), E(2, i=2)], "A2", "sentence")] == [3, 2])
check("capping never touches the input list", len(ms) == 5)
check("empty / None", V.display_cap([], "B1") == [] and V.display_cap(None, "B1") == [])

# =============================================================================================== check_smooth
section("check_smooth")
ORIG = "yesterday i go to the market and i buy some vegetable"
CORR = "yesterday i went to the market and i bought some vegetables"
SM = "Yesterday I went to the market and bought some vegetables"
clean = lambda s: []          # noqa: E731
chk = lambda smooth, orig=ORIG, **kw: V.check_smooth(orig, smooth, recheck=kw.pop("recheck", clean), **kw)   # noqa: E731
check("a good smoother version is accepted", chk(SM, corrected=CORR, level="B1", has_fix=True) is True)
check("smooth identical to corrected is rejected", chk(CORR, corrected=CORR, has_fix=True) is False)
check("identical to corrected up to case / punctuation is rejected", chk("Yesterday, I went to the market and I bought some vegetables.", corrected=CORR, has_fix=True) is False)
check("smooth identical to the original is rejected", chk(ORIG, has_fix=True) is False)
check("no fix and level B1 -> rejected", chk(SM, corrected=None, level="B1", has_fix=False) is False)
check("no fix but level B2 -> accepted", chk(SM, corrected=None, level="B2", has_fix=False) is True)
check("has fix at A1 accepted", chk(SM, corrected=CORR, level="A1", has_fix=True) is True)
check("too short (< 0.6x)", chk("I went to the market", has_fix=True) is False)
check("too long (> 1.3x)", chk("Yesterday I went to the market and then I bought some fresh vegetables for my family", has_fix=True) is False)
long_o = " ".join(["word%d" % i for i in range(50)])
long_s = " ".join(["word%d" % i for i in range(50)] + ["extra%d" % i for i in range(14)])
check("> original + 12 words rejected (even inside 1.3x)", V.check_smooth(long_o, long_s, has_fix=True, recheck=clean) is False)
check("a new digit token rejected", chk("Yesterday I went to the market 2020 and bought some vegetables", has_fix=True) is False)
check("a digit present in the original is fine", V.check_smooth("i have 5 apples and i buy some", "I have 5 apples and bought some", has_fix=True, recheck=clean) is True)
check("a new mid-sentence capitalised name rejected", chk("Yesterday I went to the market in Delhi and bought some vegetables", has_fix=True) is False)
check("a capitalised name present in the original is fine", V.check_smooth("i go to Delhi and i buy some vegetable", "I went to Delhi and bought some vegetables", has_fix=True, recheck=clean) is True)
check("sentence-initial capital is not a 'name'", chk(SM, has_fix=True) is True)
neg_o = "i do not like the market and i go there"
check("negation count must match (dropping 'not')", V.check_smooth(neg_o, "I like the market and went there", has_fix=True, recheck=clean) is False)
check("negation count must match (adding one)", V.check_smooth("i like the market and i go there", "I do not like the market and went there", has_fix=True, recheck=clean) is False)
check("negation kept", V.check_smooth(neg_o, "I do not like the market and went there", has_fix=True, recheck=clean) is True)
check("negation via n't counts", V.check_smooth("i don't like the market and i go there", "I do not like the market and went there", has_fix=True, recheck=clean) is True)
check("content recall too low rejected", chk("Yesterday something happened near a shop and people laughed loudly", has_fix=True) is False)
check("too much new content rejected", chk("Yesterday I went to the market and bought some vegetables, fruits, cheese, bread", orig=ORIG, has_fix=True) is False)
check("a solo hit in the smooth text rejects it", chk(SM, has_fix=True, recheck=lambda s: [Hit("ag.he_dont", 0, 1, (), "D1", True)]) is False)
check("a non-solo hit does not reject", chk(SM, has_fix=True, recheck=lambda s: [Hit("ag.he_dont", 0, 1, (), "D1", False)]) is True)
check("recheck raising rejects", chk(SM, has_fix=True, recheck=lambda s: 1 / 0) is False)
check("empty / non-str inputs", V.check_smooth("", SM, has_fix=True, recheck=clean) is False and V.check_smooth(ORIG, "", has_fix=True, recheck=clean) is False and
      V.check_smooth(None, SM, has_fix=True) is False and V.check_smooth(ORIG, None, has_fix=True) is False)
check("default recheck (detectors absent or present) never raises", isinstance(V.check_smooth(ORIG, SM, has_fix=True), bool))

# =============================================================================================== property test
section("property: random single-token replacements")
VOC = "i you he she it we they go goes went gone like likes liked buy bought bring brought apple apples market school office tea coffee good big small very much many".split()
rng = random.Random(20261016)
bad = 0
n_cases = 0
for case in range(600):
    n = rng.randint(3, 14)
    ws = [rng.choice(VOC) for _ in range(n)]
    text = " ".join(ws)
    if rng.random() < 0.4:
        text = text[0].upper() + text[1:] + rng.choice([".", "?", ""])
    toks = tokenize(text)
    k = rng.randint(1, min(3, max(1, n // 3)))
    pos = sorted(rng.sample(range(0, n, 2), min(k, len(range(0, n, 2)))))          # non-adjacent
    marks = []
    expect = [t.key for t in toks]
    applied_any = False
    for p in pos:
        newtok = rng.choice(VOC + [""])
        if newtok == toks[p].key:
            newtok = newtok + "s"
        sure = rng.random() < 0.6
        sev = rng.choice(["error", "error", "natural"])
        t = toks[p]
        marks.append(Mark("ag.s_missing_3p", p, p + 1, t.start, t.end, t.raw, newtok, conf="sure" if sure else "likely", severity=sev, weight=2))
        if sure and sev == "error":
            applied_any = True
    out = V.build_corrected(text, marks)
    n_cases += 1
    exp = [t.key for t in toks]
    for mk_ in sorted(marks, key=lambda m: m.i, reverse=True):
        if mk_.conf == "sure" and mk_.severity == "error":
            exp[mk_.i:mk_.j] = keys_of(mk_.fix)
    differs = out is not None and out != text
    ok = (differs == applied_any) and (out is None or keys_of(out) == exp)
    if not ok:
        bad += 1
        if bad < 4:
            print("   case", repr(text), [(m.i, m.fix, m.conf, m.severity) for m in marks], "->", repr(out), exp)
check(f"build_corrected: differs iff a sure error applied, re-tokenises to the expected keys ({n_cases} cases)", bad == 0, f"{bad} bad")

# through verify_marks (whole pipeline) with a catalogue pair table
PAIRS = [("go", "went", "tn.past_marker"), ("buy", "bought", "tn.past_marker"), ("goes", "go", "ag.base_after_aux"), ("have", "has", "ag.aux_form"),
         ("they", "he", "pn.pronoun_misuse")]
bad = 0
cases = 0
FILL = "the market home school tea very good office and then".split()
for case in range(500):
    n = rng.randint(4, 12)
    ws = [rng.choice(FILL) for _ in range(n)]
    pair = rng.choice(PAIRS)
    p = rng.randrange(n)
    ws[p] = pair[0]
    text = " ".join(ws)
    conf = rng.choice("sl")
    ms_ = ver(text, [raw(pair[2], pair[0], pair[1], c=conf)], level="B2", source="whisper")
    out = V.build_corrected(text, ms_)
    cases += 1
    sure_applies = bool(ms_) and ms_[0].conf == "sure" and ms_[0].severity == "error"
    exp = list(keys_of(text))
    exp[p] = pair[1]
    ok = ((out is not None and out != text) == sure_applies) and (out is None or keys_of(out) == exp)
    if not ok:
        bad += 1
        if bad < 4:
            print("   case", repr(text), pair, conf, ms_, "->", repr(out))
check(f"verify_marks + build_corrected end to end ({cases} cases)", bad == 0, f"{bad} bad")

# =============================================================================================== adversarial timing
section("adversarial timing (each < 100 ms)")
hostile = []
hostile.append(("huge quote 10k chars", "a b c", [raw("other", "a " * 5000, "b")]))
hostile.append(("5000-token sentence, absent quote", "a " * 5000, [raw("other", "a a a a a a a b", "x")]))
hostile.append(("5000-token repeated, quote found at the end", "a " * 5000 + "b", [raw("tn.past_marker", "a b", "go")]))
hostile.append(("8 identical tokens in 5000", "a " * 5000, [raw("wd.collocation", "a a a a a a a a", "a a a a a a a b")]))
hostile.append(("50 raw marks", T, [raw("ag.s_missing_3p", "he go", "he goes")] * 50))
hostile.append(("50 distinct raw marks over a long sentence", " ".join(f"w{i}" for i in range(3000)), [raw("wd.collocation", f"w{i} w{i+1}", f"w{i} x{i}") for i in range(50)]))
hostile.append(("huge fix", T, [raw("other", "he", "x" * 100000)]))
hostile.append(("30000 chars without spaces", "x" * 30000, [raw("other", "x" * 70, "y")]))
hostile.append(("10000 apostrophes", "'" * 10000, [raw("other", "'", "a")]))
hostile.append(("apostrophe chains", "a'b " * 3000, [raw("other", "a'b a'b", "c")]))
hostile.append(("digit run", "1" * 30000, [raw("other", "1" * 40, "2")]))
hostile.append(("unicode soup", "नमस्ते " * 3000 + "hello \U0001F600" * 100, [raw("other", "नमस्ते नमस्ते", "x")]))
hostile.append(("non-dict raws x 5000", T, [None, 1, "x", [], {}] * 1000))
hostile.append(("weird value types", T, [{"r": [1], "q": {"a": 1}, "f": 1.5, "c": None, "w": []}] * 30))
hostile.append(("w huge", T, [raw("ag.s_missing_3p", "he go", "he goes", w="w " * 100000)]))
hostile.append(("rule id huge", T, [raw("r" * 100000, "he go", "he goes")]))
hostile.append(("5000 sorted-tokens sentence, 20 marks at the end", " ".join(f"t{i}" for i in range(5000)), [raw("wd.collocation", f"t{4980+i} t{4981+i}", f"t{4980+i} z") for i in range(20)]))
hostile.append(("all-punctuation sentence", "!!! ??? ... ,,,; " * 3000, [raw("other", "a", "b")]))
hostile.append(("repeated tokens with edit-bound edge", "go " * 5000, [raw("tn.past_marker", "go", "went")] * 20))
hostile.append(("whitespace flood", " " * 30000 + "he go", [raw("ag.s_missing_3p", "he go", "he goes")]))
hostile.append(("newline / control chars", ("he go\n\t\x00\x01 " * 2000), [raw("ag.s_missing_3p", "he go", "he goes")]))
big_hits = [Hit("ag.s_missing_3p", i, i + 1, ("x",), "D2", i % 2 == 0) for i in range(5000)]
big_vet = [("ag", i, i + 1) for i in range(5000)]
tt5000 = " ".join(f"t{i}" for i in range(5000))
hostile.append(("5000 hits + 5000 vetoes + huge opaque set", tt5000, [raw("wd.collocation", "t4990 t4991", "t4990 z")]))
hostile.append(("sibling-relabel storm", " ".join(["in", "monday"] * 2000), [raw("ag.he_dont", "in monday", "on monday")] * 20))
hostile.append(("ind.lexicon flood", "prepone " * 5000, [raw("ind.lexicon", "prepone", "x")] * 20))
slow = []
for name, text, raws in hostile:
    kw = {}
    if name.startswith("5000 hits"):
        kw = dict(hits=big_hits, vetoes=big_vet, opaque=frozenset(range(0, 5000, 2)))
    if name.startswith("ind.lexicon"):
        kw = dict(lex=LEX)
    t0 = time.perf_counter()
    r = ver(text, raws, **kw)
    dt = (time.perf_counter() - t0) * 1000
    if dt >= 100:
        slow.append((name, round(dt, 1)))
    check(f"verify_marks: {name} ({dt:.1f} ms) -> {len(r)} marks", dt < 100 and isinstance(r, list), dt)
for name, fn in [
    ("marks_from_hits 5000 hits", lambda: V.marks_from_hits(tt5000, big_hits)),
    ("build_corrected 5000 tokens, 20 marks", lambda: V.build_corrected(tt5000, [Mark("wd.collocation", i, i + 1, 0, 1, "t", "z", conf="sure", severity="error", weight=2) for i in range(0, 40, 2)])),
    ("display_case 30000 chars", lambda: V.display_case("a i " * 7500)),
    ("check_smooth 5000 tokens", lambda: V.check_smooth(tt5000, tt5000 + " x", has_fix=True, recheck=clean)),
    ("display_cap 5000 marks", lambda: V.display_cap([E(2, i=i) for i in range(5000)], "B2", "turn")),
    ("is_artifact_only long", lambda: V.is_artifact_only(["a"] * 5000, ["b"] * 5000)),
]:
    t0 = time.perf_counter()
    fn()
    dt = (time.perf_counter() - t0) * 1000
    check(f"{name} ({dt:.1f} ms)", dt < 100, dt)

raise SystemExit(done("unit_verify"))
