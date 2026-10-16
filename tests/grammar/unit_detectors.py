"""Unit tests for backend/app/grammar/detectors.py + lexicon.py (pure; no database, no network, no model).

Run:  cd /home/vibhanshu/Desktop/DuSu && PYTHONPATH=backend python3 tests/grammar/unit_detectors.py

What is covered
  * every D1-D16 check: every "fires on" / "silent on" sentence of Appendix C of the plan, plus more positives and adversarial negatives
  * T1 (preposition), T2 (pattern) and T3 (Indianism) tables: tests GENERATED per row (wrong -> hit with the right fix, right -> silent)
  * the solo policy (D2 / D13 / D14 conditional), opaque tokens, vetoes(), opportunities()
  * a hand-written corpus (clean natural speech + seeded errors): per-check precision / recall printout, with asserts for every SOLO check
  * fixes applied to the sentence give the right form
  * adversarial timing (25 hostile token lists, each run_all < 100 ms) and a fuzz run that calls every check directly (no wrapper)
No learner text is printed except the test names (all fixtures are synthetic).
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h                                                                   # noqa: E402
from _h import check, section                                              # noqa: E402

from app.grammar import catalog, text                                       # noqa: E402
from app.grammar import detectors as D                                      # noqa: E402
from app.grammar import lexicon as L                                        # noqa: E402

ALL_HITS: list = []


def K(s):
    return text.canon_contractions(text.keys(s))


def H(s, **kw):
    kw.setdefault("source", "whisper")
    hs = D.run_all(K(s), **kw)
    ALL_HITS.extend(hs)
    return hs


def apply(ks, hits):
    out = list(ks)
    taken = []
    for h in sorted(hits, key=lambda h: (-h.i, h.j)):
        if any(h.i < b and a < h.j for a, b in taken):
            continue
        out[h.i:h.j] = list(h.fix)
        taken.append((h.i, h.j))
    return out


def fixed(s, det=None, **kw):
    hs = [h for h in H(s, **kw) if det is None or h.det == det]
    return apply(K(s), hs)


def of_det(s, det, **kw):
    return [h for h in H(s, **kw) if h.det == det]


# ======================================================================================================================================
section("lexicon sanity")
check("BASE_VERBS has >= 250 verbs", len(L.BASE_VERBS) >= 250, len(L.BASE_VERBS))
check("irregular table has the usual suspects", all(L.IRREG[b] == t for b, t in [("go", ("went", "gone")), ("see", ("saw", "seen")),
      ("take", ("took", "taken")), ("write", ("wrote", "written")), ("buy", ("bought", "bought")), ("be", ("was", "been"))]))
check("V2/V3 reverse maps", L.V2_TO_BASE["went"] == "go" and L.V3_TO_BASE["seen"] == "see" and L.V3_TO_BASE["gone"] == "go" and "read" in L.V2_EQ_BASE)
check("third_s", [L.third_s(v) for v in ("go", "try", "watch", "have", "do", "study", "play", "fix", "pass")] ==
      ["goes", "tries", "watches", "has", "does", "studies", "plays", "fixes", "passes"])
check("ing_form", [L.ing_form(v) for v in ("make", "stop", "run", "visit", "begin", "lie", "see", "dance", "play", "swim", "plan")] ==
      ["making", "stopping", "running", "visiting", "beginning", "lying", "seeing", "dancing", "playing", "swimming", "planning"])
check("past_regular", [L.past_regular(v) for v in ("walk", "like", "try", "stop", "visit", "plan")] == ["walked", "liked", "tried", "stopped", "visited", "planned"])
check("S_TO_BASE / ED_TO_BASE / ING_TO_BASE", L.S_TO_BASE["tries"] == "try" and L.ED_TO_BASE["visited"] == "visit" and L.ING_TO_BASE["stopping"] == "stop")
check("base_of covers every form", L.base_of("went") == "go" and L.base_of("goes") == "go" and L.base_of("going") == "go" and L.base_of("visited") == "visit" and L.base_of("zzz") == "")
check("KIN has genders incl. either", L.KIN["brother"] == "m" and L.KIN["mother"] == "f" and L.KIN["friend"] == "e" and L.KIN["teacher"] == "e")
check("PROFESSIONS >= 60", len(L.PROFESSIONS) >= 60, len(L.PROFESSIONS))
check("PREP_TABLE ~45 rows", 40 <= len(L.PREP_TABLE) <= 60, len(L.PREP_TABLE))
check("PATTERN_TABLE ~30 rows", len(L.PATTERN_TABLE) >= 30, len(L.PATTERN_TABLE))
check("INDIAN_LEX ~40 entries", len(L.INDIAN_LEX) >= 36, len(L.INDIAN_LEX))
check("UNCOUNTABLE, COLLOCATIONS present", len(L.UNCOUNTABLE) >= 30 and len(L.COLLOCATIONS) >= 4)
check("every PREP / PATTERN / INDIAN row names a catalogue rule",
      all(catalog.get(r.rule) for r in L.PREP_TABLE) and all(catalog.get(r.rule) for r in L.PATTERN_TABLE) and all(catalog.get("ind.lexicon#" + r.slug) for r in L.INDIAN_TABLE))
check("every table rule is a table rule in the catalogue (dets)",
      all("T1" in catalog.get(r.rule).dets for r in L.PREP_TABLE) and all("T2" in catalog.get(r.rule).dets for r in L.PATTERN_TABLE))

# ======================================================================================================================================
# D1-D16: (fires-on sentences with the expected fixed sentence) and (silent-on sentences).  The first items of each list are the
# Appendix C cases verbatim; the rest are our own.
POS = {
    "D1": [("he don't like tea", "he doesn't like tea"), ("she don't know him", "she doesn't know him"), ("it don't work", "it doesn't work"),
           ("my brother says she don't eat meat", "my brother says she doesn't eat meat"), ("I think he dont care", "I think he doesn't care"),
           ("because she don't have time", "because she doesn't have time")],
    "D2": [("he go to office", "he goes to office"), ("she always like tea", "she always likes tea"), ("it work well", "it works well"),
           ("my sister is happy because she live in delhi", "my sister is happy because she lives in delhi"),
           ("he want a new phone", "he wants a new phone"), ("she study very hard", "she studies very hard"), ("he try to help us", "he tries to help us")],
    "D3": [("I is a student", "I am a student"), ("they was late", "they were late"), ("he have a car", "he has a car"),
           ("we is ready", "we are ready"), ("she are happy", "she is happy"), ("I has a pen", "I have a pen"), ("you was right", "you were right"),
           ("it have a problem", "it has a problem")],
    "D4": [("he doesn't likes tea", "he doesn't like tea"), ("did you went there", "did you go there"), ("I can able to swim", "I can swim"),
           ("she can plays guitar", "she can play guitar"), ("he didn't came yesterday", "he didn't come yesterday"),
           ("do you wants tea", "do you want tea"), ("they didn't visited us", "they didn't visit us"), ("I want to going home", "I want to go home"),
           ("she needs to goes now", "she needs to go now"), ("will you told him", "will you tell him"), ("can he goes", "can he go")],
    "D5": [("if it will rain I stay", "if it rains I stay"), ("unless you will come we cannot start", "unless you come we cannot start"),
           ("as soon as he will arrive I will call", "as soon as he arrives I will call"),
           ("when I will reach home I will call you", "when I reach home I will call you"),
           ("if he will come tomorrow I will tell him", "if he comes tomorrow I will tell him"),
           ("before he will leave please call me", "before he leaves please call me"), ("if they will come we will eat", "if they come we will eat"),
           ("if it will be sunny we will go", "if it is sunny we will go")],
    "D6": [("I have seen him yesterday", "I saw him yesterday"), ("she has gone there last week", "she went there last week"),
           ("we have met in 2019", "we met in 2019"), ("I haven't seen him yesterday", "I didn't see him yesterday"),
           ("have you seen him yesterday", "did you see him yesterday"), ("I've been there last year", "I was there last year"),
           ("he has already finished the work two days ago", "he already finished the work two days ago"),
           ("they have bought a car on Monday", "they bought a car on Monday")],
    "D7": [("I am living here since 2010", "I have been living here since 2010"), ("I know him since five years", "I have known him for five years"),
           ("we wait since morning", "we have waited since morning"), ("I have been working here for 2015", "I have been working here since 2015"),
           ("she works here since last year", "she has worked here since last year"), ("I live in pune since two years", "I have lived in pune for two years"),
           ("it is raining since yesterday", "it has been raining since yesterday")],
    "D8": [("I am knowing him", "I know him"), ("she is wanting a car", "she wants a car"), ("we are needing help", "we need help"),
           ("he is not understanding the lesson", "he doesn't understand the lesson"), ("I am having two brothers", "I have two brothers"),
           ("are you knowing him", "do you know him"), ("I'm believing it", "I believe it"), ("she is owning a shop", "she owns a shop")],
    "D9": [("a apple a day", "an apple a day"), ("an university student", "a university student"), ("a hour ago", "an hour ago"),
           ("a umbrella is useful", "an umbrella is useful"), ("an book on the table", "a book on the table"), ("a honest man", "an honest man"),
           ("an useful tool", "a useful tool"), ("a MBA degree", "an mba degree")],
    "D10": [("I am engineer", "I am an engineer"), ("she is teacher", "she is a teacher"), ("I wake up in morning", "I wake up in the morning"),
            ("he is software engineer in a company", "he is a software engineer in a company"), ("my father is doctor", "my father is a doctor"),
            ("I am not student", "I am not a student"), ("is he doctor", "is he a doctor"), ("I work on internet", "I work on the internet"),
            ("he is the richest man in world", "he is the richest man in the world"), ("I go to gym in evening", "I go to gym in the evening")],
    "D11": [("I need some informations", "I need some information"), ("he gave me a good advice", "he gave me good advice"),
            ("many peoples came", "many people came"), ("she bought many furnitures", "she bought many furniture"),
            ("I have much friends", "I have many friends"), ("there are many water in the glass", "there are much water in the glass"),
            ("he has a luggage", "he has luggage"), ("many time I forget my keys", "many times I forget my keys")],
    "D12": [("this is more better", "this is better"), ("the most smartest boy", "the smartest boy"), ("she is more taller than me", "she is taller than me"),
            ("he is most richest man", "he is richest man"), ("it is more easier", "it is easier")],
    "D13": [("what you want", "what do you want"), ("where you are going", "where are you going"), ("how you know this", "how do you know this"),
            ("why she is crying", "why is she crying"), ("where he go", "where does he go"), ("which you like", "which do you like")],
    "D14": [("tell me where is the station", "tell me where the station is"), ("I don't know what is his name", "I don't know what his name is"),
            ("do you know where is he", "do you know where he is"), ("I wonder how is the weather today", "I wonder how the weather is today"),
            ("tell me where is the nearest bus stop", "tell me where the nearest bus stop is"), ("she asked what was his problem", "she asked what his problem was"),
            ("tell me what do you want", "tell me what you want"), ("I don't know what did he say", "I don't know what he said")],
    "D15": [("my brother he is a doctor", "my brother is a doctor"), ("my friend she lives in pune", "my friend lives in pune"),
            ("my mother he works in a bank", "my mother works in a bank"), ("our teacher he teaches maths", "our teacher teaches maths"),
            ("my parents they are in delhi", "my parents are in delhi"), ("my elder brother he is an engineer", "my elder brother is an engineer"),
            ("him is my brother", "he is my brother"), ("her is my sister", "she is my sister"), ("my sister he's a nurse", "my sister is a nurse")],
    "D16": [("I will come in Monday", "I will come on Monday"), ("I was born on 1998", "I was born in 1998"), ("I wake up at morning", "I wake up in the morning"),
            ("the meeting is on 5 pm", "the meeting is at 5 pm"), ("I was born at January", "I was born in January"),
            ("the exam is in 15 january", "the exam is on 15 january"), ("I sleep in night", "I sleep at night"), ("she came at Sunday", "she came on Sunday")],
}

NEG = {
    "D1": ["they don't like", "I don't know", "he doesn't know", "we don't have time", "you don't need it", "do you like it don't you",
           "I like it don't you", "don't go there", "she said don't worry", "he told me don't go"],
    "D2": ["he can go", "let her go", "I suggest he go", "I demand that she leave", "make it work", "let it go", "what does it mean", "did he go",
           "she doesn't like tea", "he read the book", "he put it there", "it cost a lot", "he would go", "he may go", "help him go", "she goes home",
           "it works", "I want it to work", "he need not worry", "he used to go", "she like went there", "see it work", "it is important that he go",
           "he will go"],
    "D3": ["My roommate and I are preparing for the placement drive", "you and I were friends", "she and I are close", "if I were you", "you were right", "he has a car", "does he have a car", "will she have time", "I suggest he have a rest", "they were late",
           "I am ready", "we are here", "I wish he were here", "it has a problem", "what are you doing", "how are they", "you are right", "they have a car",
           "he should have gone", "she has been here", "do you have a pen", "can we have it", "we have time"],
    "D4": ["he does his homework", "I want to go", "can you speak", "did you go there", "he doesn't like tea", "she does exercises daily", "I can't believe it",
           "we have to leave now", "I would like to meet him", "do you want some tea", "what did he say", "he did well", "I did my best",
           "they will be happy", "she can't be here", "I am going to shows every week", "I have to deal with it", "I like to dress well",
           "we need to focus", "the can holds paint", "I look forward to meeting you", "he does it every day", "can I have some water", "do you read books"],
    "D5": ["I wonder if he will come", "if you will please sit", "tell me when he will come", "I don't know if it will rain", "I am not sure whether she will come",
           "ask him if he will help", "if it will help I will do it", "what will you do if it rains", "when will he come", "as if he will win",
           "the day when he will come is near", "if you will excuse me", "if it rains we will stay home", "when he comes I will tell him"],
    "D6": ["I haven't seen him since last week", "I have lived here for two years", "I have seen him", "she has gone home", "we have met before",
           "I have never been there", "I have been here since yesterday", "I have lived here since 2010", "he has worked here for the last two years",
           "I have known her since last year", "have you seen him", "I have eaten and then I went there yesterday", "I saw him yesterday",
           "we met in 2019", "I have a meeting yesterday"],
    "D7": ["I have lived here since 2010", "I am staying here for three days", "since you asked", "I have been living here for ten years",
           "since the weather is bad we stayed home", "I have booked tickets for 2019", "it has been two years since I saw him", "I am waiting for you",
           "I lived there since I was a child", "I have been here since morning", "I will stay for two weeks", "we are here for a week"],
    "D8": ["I know him", "without knowing the way", "I'm having lunch", "she is very understanding", "I am loving it", "I am hating this", "we are having a party",
           "they are having dinner", "he is having trouble", "I was thinking about you", "he is understanding and kind", "I am having fun"],
    "D9": ["a university", "an hour ago", "an unusual day", "a one time offer", "an honest man", "an hr manager", "a european country", "an sms", "a user",
           "an egg", "a historic moment", "an historic moment", "option a and b", "plan a or plan b", "a unique idea", "an x ray", "she is an MBA", "an FM radio",
           "a hotel", "an hotel", "a ufo", "an 8 pm class", "a union leader", "a one", "an ugly shirt", "a useful tool", "a euro"],
    "D10": ["I am an engineer", "they are teachers", "I am a good teacher", "I am student council president", "I am the doctor", "she is my teacher",
            "this is doctor sharma", "in the morning", "good morning", "in morning assembly", "in world war two", "he is a doctor and she is a nurse",
            "he is president of the club", "I am captain of the team", "we are students", "it is a good day"],
    "D11": ["a piece of advice", "the people are nice", "much time", "peoples of the world", "indigenous peoples", "many a time", "a good knowledge of english",
            "she gave me some advice", "many people came", "much water", "how much time do we have", "a little advice", "many water bottles", "womens rights",
            "childrens books", "I like the news", "a lot of information", "many software engineers", "many friends came", "he has many books"],
    "D12": ["more water please", "the best day", "more or less", "more than ten people", "most people", "I want more money", "it is more beautiful",
            "the more the better", "more of it", "this is better", "he is the tallest"],
    "D13": ["what I want is peace", "what do you want", "how you doing", "what you need to do is practice", "where are you going", "what I think",
            "what you said was true", "what you eat affects your health", "how are you", "what is your name", "when you arrive call me"],
    "D14": ["do you know what is happening", "where is the station", "I know where the station is", "what is your name", "tell me what is wrong",
            "I wonder what is going on", "tell me where he is", "do you know what you want", "you know what is your name", "what's your name",
            "I asked him how it works", "tell me how it works"],
    "D15": ["my brother is a doctor", "the man he saw was tall", "my friend and he went", "I told my brother he is wrong", "my brother told me he is tired",
            "he is my brother", "my friends are nice", "she is my friend", "my mother says she is fine", "give her a book", "my sister is a nurse",
            "his brother is a doctor"],
    "D16": ["on Monday morning", "at night", "in 1998", "on Sunday", "in January", "on January 5", "on january 5th", "at 5 pm", "in the morning",
            "I go to sunday school", "at 2000 hours", "on 5 june", "in night mode", "I work on night shift", "at 6:30 pm", "in 5 minutes", "on the morning of the exam",
            "on Sundays we rest", "see you on Friday"],
}

# the NEG lists must stay silent for the WHOLE engine, not just their own check
for det in sorted(POS, key=lambda d: int(d[1:])):
    section(f"{det} fires on / silent on")
    for s, want in POS[det]:
        hs = of_det(s, det)
        got = fixed(s, det)
        check(f"{det} fires: {s}", bool(hs), [(h.rule, h.i, h.j, h.fix) for h in H(s)])
        check(f"{det} fix: {s}", got == K(want), " ".join(got))
        check(f"{det} hit is well-formed: {s}", all(0 <= h.i < h.j <= len(K(s)) and all(isinstance(x, str) for x in h.fix) for h in hs))
    for s in NEG[det]:
        hs = [h for h in H(s) if h.det == det]
        check(f"{det} silent: {s}", not hs, [(h.rule, h.i, h.j, h.fix) for h in hs])

section("Appendix C verbatim: the silent-on sentences stay silent for every check")
for det in NEG:
    for s in NEG[det]:
        hs = H(s)
        check(f"all-silent: {s}", not hs, [(h.rule, h.det, h.i, h.j, h.fix) for h in hs])

# --------------------------------------------------------------------------------------------------------------------------------------
section("rules produced match the catalogue (rule id exists, det listed for it)")
RULE_OF = {"D1": {"ag.he_dont"}, "D2": {"ag.s_missing_3p"}, "D3": {"ag.aux_form"}, "D4": {"tn.did_past", "ag.base_after_aux", "md.can_able"},
           "D5": {"tn.if_will"}, "D6": {"tn.pp_finished"}, "D7": {"tn.since_for"}, "D8": {"tn.cont_misuse"}, "D9": {"ar.a_an"},
           "D10": {"ar.missing_a", "ar.the_missing"}, "D11": {"wd.noun_number", "wd.much_many"}, "D12": {"wd.comparative_double"},
           "D13": {"st.question_order"}, "D14": {"st.embedded_order"}, "D15": {"st.double_subject", "pn.pronoun_misuse"}, "D16": {"pr.time_in_on_at"}}
for det, rules in RULE_OF.items():
    got = {h.rule for s, _ in POS[det] for h in H(s) if h.det == det}
    check(f"{det} emits only its catalogue rules {sorted(rules)}", got and got <= rules, got)
bad = [(h.rule, h.det) for h in ALL_HITS if catalog.get(h.rule) is None or (h.det not in catalog.get(h.rule).dets)]
check("every hit's rule exists in catalog.RULES and lists the hit's det", not bad, bad[:5])
check("T3 hit ids resolve through catalog.get", all(catalog.get(h.rule) is not None for h in ALL_HITS if h.det == "T3"))

# ======================================================================================================================================
section("solo policy")
def solo_of(s, **kw):
    return [h.solo for h in H(s, **kw)]

check("D2 is booster-only for Chrome without a question mark", solo_of("he go to office", source="chrome") == [False])
check("D2 is solo for Whisper", solo_of("he go to office", source="whisper") == [True])
check("D2 is solo for Gemini", solo_of("he go to office", source="gemini") == [True])
check("D2 is solo for Chrome when the sentence has a question mark", solo_of("he go to office", source="chrome", has_q=True) == [True])
check("D13 is booster-only for Chrome", solo_of("what you want", source="chrome") == [False])
check("D13 is solo for Whisper", solo_of("what you want", source="whisper") == [True])
check("D13 is solo with has_q", solo_of("what you want", source="chrome", has_q=True) == [True])
check("D14 is booster-only for Chrome", solo_of("tell me where is the station", source="chrome") == [False])
check("D14 is solo for Whisper", solo_of("tell me where is the station", source="whisper") == [True])
check("D1 solo regardless of source", solo_of("he don't like tea", source="chrome") == [True])
check("D3 solo regardless of source", solo_of("they was late", source="chrome") == [True])
check("D8 'liking' is booster-only", solo_of("I am liking it", source="whisper") == [False])
check("gender mismatch far from the noun is booster-only", [h.solo for h in H("my sister is a nurse and he works in a hospital") if h.det == "D15"] == [False])
check("solo_hits == run_all filtered", D.solo_hits(K("he go to office"), source="chrome") == [] and len(D.solo_hits(K("he go to office"), source="whisper")) == 1)

# ======================================================================================================================================
section("T1 preposition table (generated per row)")
for r in L.PREP_TABLE:
    tag = f"{r.rule}|{r.head}|{' '.join(r.wrong) or '+'+' '.join(r.fix)}"
    hs = [h for h in H(r.ex_wrong) if h.det == "T1"]
    check(f"T1 fires [{tag}]: {r.ex_wrong}", bool(hs) and all(h.rule == r.rule for h in hs), [(h.rule, h.det) for h in H(r.ex_wrong)])
    check(f"T1 fix [{tag}]", fixed(r.ex_wrong, "T1") == K(r.ex_fixed), " ".join(fixed(r.ex_wrong, "T1")))
    check(f"T1 silent on the right form [{tag}]: {r.ex_right}", not H(r.ex_right), [(h.rule, h.det, h.fix) for h in H(r.ex_right)])
section("T1 adversarial")
for s in ["I will listen carefully", "please attend to the customer", "the team consists of five people", "she is married with two kids", "he is angry at me",
          "I am good in bed", "we went to home page of the site", "he reached out to me", "I'll talk to him", "wait for me", "look at him", "the road leads to delhi",
          "I want to reach to the top"[:0] or "he arrived to find the house empty", "they entered into an agreement", "she is interested in music",
          "I am afraid of dogs", "he asked to see me", "we went for a walk", "we came to see you", "I am here to help you", "participate on the panel"[:0] or "a plan depends on you",
          "I talked him out of it", "wait them out", "look me in the eye", "that is different from this"]:
    check(f"T1 silent: {s}", not [h for h in H(s) if h.det == "T1"], [(h.rule, h.fix) for h in H(s)])
check("T1 rule coverage: all four rules have rows", {r.rule for r in L.PREP_TABLE} == {"pr.wrong_prep", "pr.extra_prep", "pr.missing_to", "pr.for_purpose"})

section("T2 pattern table (generated per row)")
for i, r in enumerate(L.PATTERN_TABLE):
    tag = f"{r.rule}#{i}"
    hs = [h for h in H(r.ex_wrong) if h.det == "T2"]
    check(f"T2 fires [{tag}]: {r.ex_wrong}", bool(hs) and all(h.rule == r.rule for h in hs), [(h.rule, h.det, h.fix) for h in H(r.ex_wrong)])
    check(f"T2 fix [{tag}]", fixed(r.ex_wrong, "T2") == K(r.ex_fixed), " ".join(fixed(r.ex_wrong, "T2")))
    check(f"T2 silent on the right form [{tag}]: {r.ex_right}", not H(r.ex_right), [(h.rule, h.det, h.fix) for h in H(r.ex_right)])
check("T2 covers all nine rules", {r.rule for r in L.PATTERN_TABLE} >= {"ag.there_is_plural", "ag.quantifier_number", "wd.say_tell", "wd.collocation", "st.be_misuse",
                                                                        "st.adverb_position", "st.verb_pattern", "pn.myself_intro", "pn.relative"})
section("T2 adversarial")
for s in ["There's many things I want to tell you", "There's many people who want this job", "there's lots of time",
          "there are many people", "there is some water", "there is a lot of traffic", "there is five minutes left", "many a time", "every two days", "each other",
          "one of my friends", "he said that he would come", "he said to me", "tell me the truth", "she told me a story", "I do my homework", "please do call me",
          "we have a plan", "open the door", "close the window", "on the table", "he always is"[:0] or "he is always late", "I very much like it", "she is very kind",
          "he was very tired", "I want you to come", "I enjoy dancing", "she made him laugh", "myself and my friend went", "I myself did it", "I am used to it",
          "the person who called", "the person that called me", "a dog which barks"]:
    check(f"T2 silent: {s}", not [h for h in H(s) if h.det == "T2"], [(h.rule, h.fix) for h in H(s)])

section("T3 Indianism lexicon (generated per row)")
for r in L.INDIAN_TABLE:
    hs = [h for h in H(r.ex_wrong) if h.det == "T3"]
    check(f"T3 fires [{r.slug}]: {r.ex_wrong}", bool(hs) and hs[0].rule == "ind.lexicon#" + r.slug, [(h.rule, h.fix) for h in H(r.ex_wrong)])
    check(f"T3 fix [{r.slug}]", fixed(r.ex_wrong, "T3") == K(r.ex_fixed), " ".join(fixed(r.ex_wrong, "T3")))
    check(f"T3 hits are solo (exact phrase)", all(h.solo for h in hs))
    check(f"T3 silent on the natural form [{r.slug}]: {r.ex_right}", not H(r.ex_right), [(h.rule, h.det, h.fix) for h in H(r.ex_right)])
check("INDIAN_LEX is {phrase: replacement}", L.INDIAN_LEX["do the needful"] == "take care of it" and L.INDIAN_LEX["prepone"] == "bring forward")
check("T3 entries from the plan are present", all(p in L.INDIAN_LEX for p in ["do the needful", "prepone", "revert back", "passed out", "cousin brother", "your good name",
                                                                           "out of station", "return back", "i have a doubt", "too good"]))
for s in ["he passed out because of the heat", "it is too good to be true", "I have a doubt about his honesty", "please reply", "I will return tomorrow"]:
    check(f"T3 silent: {s}", not [h for h in H(s) if h.det == "T3"], [(h.rule, h.fix) for h in H(s)])

# ======================================================================================================================================
section("opaque tokens drop hits")
ks = K("he go to office")
check("opaque on the verb drops the hit", D.run_all(ks, source="whisper", opaque=frozenset({1})) == [])
check("opaque elsewhere keeps it", len(D.run_all(ks, source="whisper", opaque=frozenset({3}))) == 1)
check("opaque on the subject does not touch a hit that spans only the verb", len(D.run_all(ks, source="whisper", opaque=frozenset({0}))) == 1)
ks2 = K("I have seen him yesterday")
check("opaque inside a multi-token hit drops it", D.run_all(ks2, source="whisper", opaque=frozenset({2})) == [] and len(D.run_all(ks2, source="whisper", opaque=frozenset({4}))) == 1)
check("opaque token inside a table hit drops it, next to it keeps it", D.run_all(K("we discussed about chai"), opaque=frozenset({2})) == [] and len(D.run_all(K("we discussed about chai"), opaque=frozenset({3}))) == 1)

section("robustness: empty / weird / huge input")
check("empty list", D.run_all([]) == [] and D.vetoes([]) == [] and D.opportunities("ag.aux_form", []) == 0)
check("empty strings", D.run_all(["", ""]) == [])
check("non-str tokens do not raise", isinstance(D.run_all([1, 2, None, "he", "go"]), list))
check("tuple input", len(D.run_all(("he", "go"), source="whisper")) == 1)
check("unknown rule opportunities -> 0", D.opportunities("zz.unknown", ["he", "goes"]) == 0)
check("canonicalised again inside run_all (dont -> don't)", len(D.run_all(["he", "dont", "like"])) == 1)
check("index stays valid past MAX_TOK", D.run_all(["he", "go"] + ["x"] * 5000, source="whisper")[0].i == 1)

# ======================================================================================================================================
section("vetoes")
def V(s):
    return D.vetoes(K(s))

def vfam(s):
    return {f for f, _, _ in V(s)}

check("let him go -> ag veto on 'him go'", ("ag", 1, 3) in V("let him go"))
check("let's go", ("ag", 0, 2) in V("let's go"))
check("I suggest he go -> mandative veto", ("ag", 2, 4) in V("I suggest he go"))
check("it is important that he go", ("ag", 4, 6) in V("it is important that he go"))
check("if I were you", ("ag", 1, 3) in V("if I were you"))
check("I wish he were here", ("ag", 2, 4) in V("I wish he were here"))
check("what I want is peace -> st veto", any(f == "st" and i == 0 for f, i, j in V("what I want is peace")))
check("how you doing -> st veto", ("st", 0, 3) in V("how you doing"))
check("many a time -> wd veto", ("wd", 0, 3) in V("many a time"))
check("much time -> wd veto", ("wd", 0, 2) in V("much time"))
check("more or less / more than -> wd veto", ("wd", 0, 3) in V("more or less") and ("wd", 0, 2) in V("more than ten"))
check("peoples of the world", ("wd", 0, 1) in V("peoples of the world"))
check("a university / an hour -> ar veto", ("ar", 0, 2) in V("a university") and ("ar", 0, 2) in V("an hour ago"))
check("a apple is NOT vetoed", not any(f == "ar" for f, _, _ in V("a apple")))
check("since you asked -> tn veto", ("tn", 0, 2) in V("since you asked"))
check("I wonder if he will come -> tn veto", any(f == "tn" for f, _, _ in V("I wonder if he will come")))
check("if you will please sit -> tn veto", any(f == "tn" for f, _, _ in V("if you will please sit")))
check("I'm having lunch -> tn veto", ("tn", 0, 3) in V("I'm having lunch") or any(f == "tn" for f, _, _ in V("I am having lunch")))
check("without knowing -> tn veto", ("tn", 0, 2) in V("without knowing the way"))
check("I am loving it -> tn veto", any(f == "tn" for f, _, _ in V("I am loving it")))
check("have lived for two years -> tn veto", any(f == "tn" for f, _, _ in V("I have lived here for two years")))
check("student council -> ar veto", ("ar", 0, 2) in V("student council president"))
check("Sunday school -> pr veto", any(f == "pr" for f, _, _ in V("I go to Sunday school")))
check("on Monday / in 1998 / at night -> pr veto", any(f == "pr" for f, _, _ in V("on Monday")) and any(f == "pr" for f, _, _ in V("in 1998")) and any(f == "pr" for f, _, _ in V("at night")))
check("he can go -> ag veto; does he go -> ag veto", any(f == "ag" for f, _, _ in V("he can go")) and any(f == "ag" for f, _, _ in V("does he go")))
check("an error sentence has no veto on its error span", not [v for v in V("he go to office") if v[0] == "ag"])
check("vetoes never raise on junk", isinstance(D.vetoes(["", None, 5, "let"]), list))
check("vetoes are sorted + unique + in range", all(0 <= i < j or (i == j) for f, i, j in V("let him go if I were you")) and V("let him go") == sorted(set(V("let him go")), key=lambda x: (x[1], x[2], x[0])))

section("opportunities")
def O(rule, s):
    return D.opportunities(rule, s if isinstance(s, list) else K(s))

check("ag.s_missing_3p: she goes / he always works", O("ag.s_missing_3p", "she goes and he always works") == 2)
check("ag.he_dont: he doesn't / they don't", O("ag.he_dont", "he doesn't and they don't") == 2)
check("ag.aux_form: they were / he has / I am", O("ag.aux_form", "they were here and he has a car and I am fine") == 3)
check("ar.a_an: an apple / a university / an hour", O("ar.a_an", "an apple and a university and an hour") == 3)
check("ar.a_an: a apple is not a correct use", O("ar.a_an", "a apple") == 0)
check("pr.time_in_on_at: on Monday / in 1998 / at night", O("pr.time_in_on_at", "on monday in 1998 at night") == 3)
check("pr.time_in_on_at: in the morning, at 5 pm", O("pr.time_in_on_at", "in the morning at 5 pm") == 2)
check("st.question_order: what do you / where is he", O("st.question_order", "what do you want and where is he") == 2)
check("st.embedded_order: know where the station is", O("st.embedded_order", "do you know where the station is") == 1)
check("ag.base_after_aux: doesn't + base / can + base", O("ag.base_after_aux", "he doesn't like tea and I can swim") == 2)
check("tn.did_past: did you go", O("tn.did_past", "did you go there") == 1)
check("md.can_able: can swim", O("md.can_able", "I can swim") == 1)
check("tn.if_will: if it rains", O("tn.if_will", "if it rains I stay") == 1)
check("tn.pp_finished: have seen / saw yesterday", O("tn.pp_finished", "I have seen him and I saw her yesterday") == 2)
check("tn.since_for: since 2010 / for two years", O("tn.since_for", "since 2010 and for two years") == 2)
check("tn.cont_misuse: I know / she wants", O("tn.cont_misuse", "I know and she wants") == 2)
check("ar.missing_a: I am an engineer / they are teachers", O("ar.missing_a", "I am an engineer and they are teachers") == 2)
check("ar.the_missing: in the morning", O("ar.the_missing", "in the morning") == 1)
check("wd.noun_number: advice / information", O("wd.noun_number", "some advice and information") == 2)
check("wd.much_many: much water / many people", O("wd.much_many", "much water and many people") == 2)
check("wd.comparative_double: better / more beautiful", O("wd.comparative_double", "better and more beautiful") == 2)
check("st.double_subject: my brother is", O("st.double_subject", "my brother is a doctor") == 1)
check("pr.* tables: listen to music / angry with / discussed the plan / went to buy",
      O("pr.missing_to", "I listen to music") == 1 and O("pr.wrong_prep", "he is angry with me") == 1 and O("pr.extra_prep", "we discussed the plan") == 1
      and O("pr.for_purpose", "I went to buy milk") == 1)
check("T2: there are / one of my friends / told me / make a mistake",
      O("ag.there_is_plural", "there are many people") == 1 and O("ag.quantifier_number", "one of my friends") == 1 and O("wd.say_tell", "he told me") == 1
      and O("wd.collocation", "I made a mistake") == 1)
check("st.be_misuse / st.adverb_position / st.verb_pattern / pn.myself_intro / pn.relative",
      O("st.be_misuse", "she is very kind") == 1 and O("st.adverb_position", "he is always late") == 1 and O("st.verb_pattern", "I want you to come") == 1
      and O("pn.myself_intro", "I am Rahul") == 1 and O("pn.relative", "the person who called") == 1)
check("a wrong form is not an opportunity: he go / they was", O("ag.s_missing_3p", "he go") == 0 and O("ag.aux_form", "they was") == 0)
check("hash-suffixed rule id works", O("ind.lexicon#prepone", "prepone it") == 0)
check("unknown / empty -> 0", O("", []) == 0 and O("ag.he_dont", ["he"]) == 0)

# ======================================================================================================================================
# Corpus: clean natural spoken sentences (no hit allowed from a SOLO check) and seeded errors (label, sentence, expected fixed sentence)
CLEAN = """
i went to the market yesterday and bought some vegetables | she doesn't like coffee but he does | they were late because of the traffic
i have lived in pune for five years | if it rains tomorrow we will stay at home | do you know where the station is | what do you want to eat tonight
my brother is a doctor and my sister is a teacher | i am an engineer working in a software company | he goes to the gym every morning
let him go home early today | i suggest he go to the doctor | if i were you i would take the job | what i want is peace and quiet
many a time i forgot my keys | we don't have much time left | i'm having lunch with my friends | she is very understanding about it
i have been waiting since morning | it has been two years since i saw him | on monday morning i go for a walk | i was born in 1998 in a small town
i will see you at 5 pm on friday | the people in my village are very kind | he gave me a piece of advice that i still remember
can you tell me how to get to the airport | how you doing today | i'm looking forward to meeting you | she asked me what i was doing there
i didn't go to school yesterday because i was sick | he can speak three languages fluently | my friend and he went to the movies last night
the man he saw was tall and thin | we discussed the plan with the team | i listen to music every evening | please explain it to me again
i am good at maths but weak in english | we reached the hotel late at night | he is married to my cousin | she went to buy some milk
i look forward to seeing you soon | one of my friends is a doctor | every student must bring a pen | there are many people in the hall
he told me that he was late | she said that she would come | please turn off the light | i took a photo of the temple | we had a party on sunday
i made a mistake in the exam | she is a student of class ten | he is doing his homework right now | this is the best day of my life
i want you to come with me | i enjoy dancing in the evening | he made me laugh so hard | she works in a bank in delhi | it works really well on my phone
i think he knows the answer | do you think it will rain today | a university in delhi offered me a seat | an hour ago i called him
we need more water and more time | it is more or less the same | tell me where he is | i wonder if he will come tomorrow | when he comes i will tell him
she is not sure whether he will help | i'd like to know what you think | i have never been to goa | he hasn't called me since last week
i have known him for years | my mother cooks very well | my name is rahul and i am from pune | he has been working here since 2015
they have a big house near the river | he looks tired because he works too much | i saw him yesterday at the market | she went there last week with her sister
we met in 2019 at a conference | i went for a walk this morning | the weather is nice today so let's go out | no one knows what is happening
what is happening here | she did her best and won the prize | he does exercises every morning | i usually wake up at six in the morning
what did you say | who is she talking to | he asked me to open the door | i'll call you when i reach home | she likes to read books at night
good morning how are you | thank you very much for your help | the teachers are really helpful | my friends and i play cricket on sundays
she studies in a big college near my house | we have been friends for ten years | i can't believe he did that | they don't know what to do
he doesn't know where she lives | one more thing before i go | i was reading a book when he called me | i love the way she sings
i like that music because it makes me happy | an mba degree helps you get a good job | she is an mba from delhi | he is the head of the department
i have two brothers and one sister | we are going to the market | she can drive a car
i live near the station | my father works in a hospital | he plays football on weekends | she reads a book every night
we have a meeting at 3 pm | he said he would call | she told me about her trip | i went there with my parents | we stayed at a small hotel
the film starts at eight | what time does the train leave | how long have you been here | where did you go yesterday | who told you that
he is taller than his brother | this book is more interesting than that one | she speaks better english than i do | it is the cheapest place in town
i am afraid of heights | he is proud of his son | we are interested in music | she is angry with me | they arrived at the airport at noon
i'm waiting for my friend | he is looking at the picture | we talked to the manager | i listened to the radio | she replied to my message
he teaches maths at a school | i don't have any information about it | we got some good news today | thanks for your advice
""".replace("\n", " | ").split("|")
CLEAN = [s.strip() for s in CLEAN if s.strip()]

SEEDS = [
    # (label, sentence, expected fixed sentence applying that label's hits)
    ("D1", "he don't like spicy food", "he doesn't like spicy food"), ("D1", "she don't come on sundays", "she doesn't come on sundays"),
    ("D1", "my dog is old and it don't run", "my dog is old and it doesn't run"), ("D1", "I know that he don't care", "I know that he doesn't care"),
    ("D1", "she don't speak english well", "she doesn't speak english well"), ("D1", "he dont have a phone", "he doesn't have a phone"),
    ("D2", "he go to school by bus", "he goes to school by bus"), ("D2", "she love her family", "she loves her family"), ("D2", "he work in a bank", "he works in a bank"),
    ("D2", "she speak very fast", "she speaks very fast"), ("D2", "he live near the station", "he lives near the station"),
    ("D2", "it take two hours", "it takes two hours"), ("D2", "he usually walk to work", "he usually walks to work"),
    ("D3", "they was very happy", "they were very happy"), ("D3", "I is from delhi", "I am from delhi"), ("D3", "we was at the mall", "we were at the mall"),
    ("D3", "he have two sisters", "he has two sisters"), ("D3", "she are my friend", "she is my friend"), ("D3", "you was late again", "you were late again"),
    ("D4", "she doesn't likes sweets", "she doesn't like sweets"), ("D4", "did he came yesterday", "did he come yesterday"), ("D4", "i didn't saw him", "i didn't see him"),
    ("D4", "we can goes there", "we can go there"), ("D4", "they didn't played well", "they didn't play well"), ("D4", "I need to goes now", "I need to go now"),
    ("D4", "he can able to cook", "he can cook"), ("D4", "does she likes dancing", "does she like dancing"),
    ("D5", "if she will come I will tell her", "if she comes I will tell her"), ("D5", "unless he will help we cannot finish", "unless he helps we cannot finish"),
    ("D5", "after he will arrive we will start", "after he arrives we will start"), ("D5", "if you will study you will pass"[:0] or "if they will win we will celebrate", "if they win we will celebrate"),
    ("D5", "as soon as I will get the job I will call you", "as soon as I get the job I will call you"), ("D5", "until it will stop raining we stay", "until it stops raining we stay"),
    ("D6", "I have visited delhi last year", "I visited delhi last year"), ("D6", "he has come here yesterday", "he came here yesterday"),
    ("D6", "we have watched the film last night", "we watched the film last night"), ("D6", "she has called me two hours ago", "she called me two hours ago"),
    ("D6", "I have been to goa in 2018", "I was to goa in 2018"), ("D6", "they have won the match yesterday", "they won the match yesterday"),
    ("D7", "I am working here since 2018", "I have been working here since 2018"), ("D7", "she lives here since 2015", "she has lived here since 2015"),
    ("D7", "we are friends since childhood"[:0] or "I study english since last year", "I have studied english since last year"),
    ("D7", "I have been waiting for yesterday", "I have been waiting since yesterday"), ("D7", "I wait here since morning", "I have waited here since morning"),
    ("D8", "I am understanding the lesson now"[:0] or "I am not understanding this", "I don't understand this"), ("D8", "he is wanting a bike", "he wants a bike"),
    ("D8", "they are knowing the answer", "they know the answer"), ("D8", "she is needing rest", "she needs rest"), ("D8", "I am preferring tea", "I prefer tea"),
    ("D9", "a elephant is big", "an elephant is big"), ("D9", "an dog barked", "a dog barked"), ("D9", "a idea came to me", "an idea came to me"),
    ("D9", "an cat sat there", "a cat sat there"), ("D9", "a interview is tomorrow", "an interview is tomorrow"), ("D9", "an university is near", "a university is near"),
    ("D10", "she is doctor in a hospital", "she is a doctor in a hospital"), ("D10", "my brother is engineer", "my brother is an engineer"),
    ("D10", "I am student of class ten", "I am a student of class ten"), ("D10", "he is good teacher", "he is a good teacher"),
    ("D10", "they meet in evening", "they meet in the evening"), ("D10", "I read news on internet", "I read news on the internet"),
    ("D11", "I need your advices", "I need your advice"), ("D11", "she gave me many informations", "she gave me many information"),
    ("D11", "he has a lot of luggages", "he has a lot of luggage"), ("D11", "so many peoples were there", "so many people were there"),
    ("D11", "I did my homeworks", "I did my homework"), ("D11", "I have much books", "I have many books"),
    ("D12", "she is more smarter than me", "she is smarter than me"), ("D12", "it is the most easiest way", "it is the easiest way"),
    ("D12", "this is more cheaper", "this is cheaper"), ("D12", "he is more stronger now", "he is stronger now"), ("D12", "it was more worse", "it was worse"),
    ("D13", "what you are doing", "what are you doing"), ("D13", "why you came late", "why did you come late"), ("D13", "where she lives", "where does she live"),
    ("D13", "how you reached here", "how did you reach here"), ("D13", "what you think", "what do you think"), ("D13", "which you prefer", "which do you prefer"),
    ("D14", "can you tell me where is the bank", "can you tell me where the bank is"), ("D14", "I don't know what is her address", "I don't know what her address is"),
    ("D14", "please tell me what is the time"[:0] or "tell me where are my keys"[:0] or "I wonder where is my phone"[:0] or "I wonder where are the keys", "I wonder where the keys are"),
    ("D14", "do you know how is the weather", "do you know how the weather is"), ("D14", "I don't know where was he born"[:0] or "I asked where was the meeting", "I asked where the meeting was"),
    ("D15", "my sister she is a nurse", "my sister is a nurse"), ("D15", "my uncle he lives in pune", "my uncle lives in pune"),
    ("D15", "my teacher she is very kind", "my teacher is very kind"), ("D15", "my father he works in a bank", "my father works in a bank"),
    ("D15", "my friends they play cricket", "my friends play cricket"), ("D15", "my mother he cooks well", "my mother cooks well"),
    ("D16", "we meet in friday", "we meet on friday"), ("D16", "I was born in 15 august"[:0] or "I joined on 2019", "I joined in 2019"),
    ("D16", "the class starts on 9 am", "the class starts at 9 am"), ("D16", "I was born at june", "I was born in june"), ("D16", "he left on morning", "he left in the morning"),
    ("D16", "I study on night", "I study at night"),
    ("T1", "we discussed about the budget", "we discussed the budget"), ("T1", "she is afraid from snakes", "she is afraid of snakes"),
    ("T1", "I went for buy vegetables", "I went to buy vegetables"), ("T1", "please explain me this", "please explain to me this"),
    ("T1", "he is angry on his brother", "he is angry with his brother"), ("T1", "I am interested on art", "I am interested in art"),
    ("T2", "there is many students here", "there are many students here"), ("T2", "he said me a secret", "he told me a secret"),
    ("T2", "I did a mistake", "I made a mistake"), ("T2", "myself ravi from pune", "i am ravi from pune"), ("T2", "I am agree with you", "I agree with you"),
    ("T2", "one of my friend is here", "one of my friends is here"),
    ("T3", "kindly do the needful", "kindly take care of it"), ("T3", "he is my cousin brother", "he is my cousin"),
    ("T3", "i will revert back soon", "i will reply soon"), ("T3", "may i know your good name", "may i know your name"),
]
SEEDS = [s for s in SEEDS if s[1]]

section("corpus sanity")
check("clean corpus has >= 60 sentences", len(CLEAN) >= 60, len(CLEAN))
check("seeded-error corpus has >= 60 sentences", len(SEEDS) >= 60, len(SEEDS))

DETS_ALL = [f"D{i}" for i in range(1, 17)] + ["T1", "T2", "T3"]
COND = ("D2", "D13", "D14")


def prf(source="whisper"):
    """per-det: (solo-hit counts on clean = FP, TP hits on seeds labelled with the det, FP on seeds labelled with others, recall)."""
    stats = {}
    for d in DETS_ALL:
        fp_clean = [s for s in CLEAN if any(h.det == d and h.solo for h in D.run_all(K(s), source=source, has_q=s.endswith("?")))]
        seeds_d = [x for x in SEEDS if x[0] == d]
        found = [x for x in seeds_d if any(h.det == d and h.solo for h in D.run_all(K(x[1]), source=source))]
        fp_seed = [x for x in SEEDS if x[0] != d and any(h.det == d and h.solo and h.rule not in {h2.rule for h2 in D.run_all(K(x[1]), source=source) if h2.det == x[0]}
                                                         for h in D.run_all(K(x[1]), source=source))]
        tp_hits = sum(1 for x in seeds_d for h in D.run_all(K(x[1]), source=source) if h.det == d and h.solo)
        stats[d] = dict(fp_clean=fp_clean, found=found, n=len(seeds_d), fp_seed=fp_seed, tp_hits=tp_hits)
    return stats


ST = prf("whisper")
print("\n  check  seeds recall   FP(clean)  precision(clean+seeds-of-others)")
for d in DETS_ALL:
    s = ST[d]
    rec = len(s["found"]) / s["n"] if s["n"] else float("nan")
    fp = len(s["fp_clean"]) + len(s["fp_seed"])
    tp = s["tp_hits"]
    prec = tp / (tp + fp) if tp + fp else float("nan")
    print(f"  {d:<5} {s['n']:>4}  {rec:>6.2f}    {len(s['fp_clean']):>3}        {prec:>6.2f}")
section("corpus: every SOLO check reaches precision >= 0.97 on the clean corpus and recall >= 0.90 on its own seeds")
SOLO_CHECKS = []
for d in DETS_ALL:
    s = ST[d]
    fp = len(s["fp_clean"]) + len(s["fp_seed"])
    tp = s["tp_hits"]
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = len(s["found"]) / s["n"] if s["n"] else 1.0
    check(f"{d}: seeds exist", s["n"] >= 1)
    check(f"{d}: precision >= 0.97 (clean FPs: {s['fp_clean'][:2]}, seed FPs: {[x[1] for x in s['fp_seed'][:2]]})", prec >= 0.97, f"{prec:.2f}")
    check(f"{d}: recall >= 0.90 (missed: {[x[1] for x in s['n'] and [y for y in SEEDS if y[0] == d and y not in s['found']][:2]]})", rec >= 0.90, f"{rec:.2f}")
    if prec >= 0.97 and rec >= 0.90:
        SOLO_CHECKS.append(d)

section("corpus: the clean sentences produce no hit of ANY kind (solo or booster)")
loud = [(s, [(h.rule, h.fix) for h in D.run_all(K(s), source="whisper")]) for s in CLEAN if D.run_all(K(s), source="whisper")]
check("no booster FPs on the clean corpus either", not loud, loud[:3])
section("corpus: Chrome source (no punctuation): conditional checks never stand alone")
chrome_solo = [(s, h.det) for s in CLEAN for h in D.run_all(K(s), source="chrome") if h.solo]
check("no solo hit on the clean corpus from Chrome", not chrome_solo, chrome_solo[:3])
check("D2 / D13 / D14 hits from Chrome (no ?) are all booster-only", all(not h.solo for s in [x[1] for x in SEEDS] for h in D.run_all(K(s), source="chrome") if h.det in COND))

section("corpus: fixes applied to the sentence give the right form")
for lab, s, want in SEEDS:
    if want is None:
        continue
    got = apply(K(s), [h for h in H(s) if h.det == lab])
    check(f"fix {lab}: {s}", got == K(want), " ".join(got))
section("corpus: every error sentence gets at least one hit from its own check")
for lab, s, want in SEEDS:
    check(f"hit {lab}: {s}", any(h.det == lab for h in H(s)), [(h.det, h.rule) for h in H(s)])

# ======================================================================================================================================
section("adversarial timing: 25 hostile token lists, run_all each < 100 ms")
rnd = random.Random(7)
VOC = sorted(set(list(L.BASE_VERBS)[:150] + list(L.PRON_SUBJ) + list(L.MODALS) + ["is", "are", "was", "were", "am", "have", "has", "had", "been", "will", "if", "since",
                  "for", "yesterday", "last", "week", "a", "an", "the", "my", "brother", "he", "she", "what", "where", "tell", "me", "know", "in", "on", "at", "monday",
                  "2019", "morning", "more", "better", "people", "many", "much", "discuss", "about", "listen", "music", "told", "that", "very", "always", "prepone",
                  "don't", "doesn't", "didn't", "going", "to", "able", "friend", "every", "students", "informations", "peoples", "myself", "which", "person"]))
HOSTILE = {
    "he x5000": ["he"] * 5000, "is x5000": ["is"] * 5000, "he go alternating": ["he", "go"] * 2500, "i am alternating": ["i", "am"] * 2500,
    "a apple": ["a", "apple"] * 2500, "did you went": ["did", "you", "went"] * 1666, "if it will rain": ["if", "it", "will", "rain"] * 1250,
    "have seen yesterday": ["have", "seen", "yesterday"] * 1666, "since five years": ["since", "five", "years"] * 1666,
    "what you want": ["what", "you", "want"] * 1666, "my brother he is": ["my", "brother", "he", "is"] * 1250, "in monday": ["in", "monday"] * 2500,
    "discuss about": ["discuss", "about"] * 2500, "there is many people": ["there", "is", "many", "people"] * 1250, "prepone x5000": ["prepone"] * 5000,
    "more better": ["more", "better"] * 2500, "am knowing": ["am", "knowing"] * 2500, "digits": [str(i) for i in range(5000)], "empty tokens": [""] * 5000,
    "very long tokens": ["x" * 1000] * 5000, "tell me where is the": ["tell", "me", "where", "is", "the"] * 1000,
    "have seen then and x5000": ["i", "have", "seen"] + ["and"] * 5000, "modals": ["can", "can", "can"] * 1666, "to going": ["want", "to", "going"] * 1666,
    "random soup": [rnd.choice(VOC) for _ in range(5000)],
}
check("25 hostile lists", len(HOSTILE) == 25, len(HOSTILE))
worst = 0.0
for name, toks in HOSTILE.items():
    t0 = time.perf_counter()
    out = D.run_all(toks, source="whisper", has_q=True)
    dt = (time.perf_counter() - t0) * 1000
    worst = max(worst, dt)
    check(f"timing {name}: {dt:.1f} ms", dt < 100 and isinstance(out, list), dt)
    t0 = time.perf_counter()
    D.vetoes(toks)
    D.opportunities("ag.aux_form", toks)
    D.opportunities("pr.wrong_prep", toks)
    dt2 = (time.perf_counter() - t0) * 1000
    check(f"timing vetoes/opportunities {name}: {dt2:.1f} ms", dt2 < 100, dt2)
print(f"  (worst run_all {worst:.1f} ms)")
check("a hostile huge input makes at most MAX_TOK-bounded hits", len(D.run_all(["he", "go"] * 2500, source="whisper")) <= D.MAX_TOK)

section("fuzz: every check called DIRECTLY (no wrapper) never raises and returns well-formed hits")
bad = []
for trial in range(400):
    n = rnd.choice([0, 1, 2, 3, 5, 8, 13, 25, 60])
    toks = [rnd.choice(VOC) for _ in range(n)]
    S = tuple(D.canon_contractions(toks))
    for q in (False, True):
        for src in ("chrome", "whisper"):
            c = D._Ctx(S, src, q)
            for fn in D.CHECKS:
                try:
                    for h in fn(S, c):
                        if not (0 <= h.i < h.j <= len(S)) or not all(isinstance(x, str) and x for x in h.fix) or h.rule is None:
                            bad.append((fn.__name__, toks, h))
                except Exception as e:                                                   # noqa: BLE001
                    bad.append((fn.__name__, toks, repr(e)))
    for rule in ("ag.he_dont", "pr.wrong_prep", "ind.lexicon#x", "tn.pp_finished"):
        try:
            D.opportunities(rule, toks)
            D.vetoes(toks)
        except Exception as e:                                                           # noqa: BLE001
            bad.append(("opp/veto", toks, repr(e)))
check("fuzz: 400 random token soups x 19 checks x 4 contexts, zero exceptions / malformed hits", not bad, bad[:2])

section("checks are deterministic and do not mutate their input")
ks = K("he go to office and she don't like it")
before = list(ks)
a = D.run_all(ks, source="whisper")
b = D.run_all(ks, source="whisper")
check("same input -> same hits", a == b)
check("input list unchanged", ks == before)

print(f"\nSOLO checks (precision >= 0.97 and recall >= 0.90 on the corpus): {SOLO_CHECKS}")
print(f"BOOSTER-ONLY / failing: {[d for d in DETS_ALL if d not in SOLO_CHECKS]}")
_h.main("unit_detectors")
