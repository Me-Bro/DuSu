"""Grammar Lab - the checker (pure). Run: python tests/lab/unit_checker.py (from the repo root)."""
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, "tests/lab")
from _h import check, section, main
from app.lab import checker as C

# (accepted answers, said, verdict, primary code prefix or "")
CASES = [
    # ---- correct (and what a speech recogniser writes differently)
    (["He plays cricket every day."], "he plays cricket every day", "ok", ""),
    (["He plays cricket every day."], "He plays cricket every day.", "ok", ""),
    (["He does not play cricket."], "he doesn't play cricket", "ok", ""),
    (["He doesn't play cricket."], "He does not play cricket.", "ok", ""),
    (["I am going to the market."], "i'm going to the market", "ok", ""),
    (["I am going to the market."], "I am going to the market", "ok", ""),
    (["She will buy a car."], "she is going to buy a car", "ok", ""),
    (["She is going to buy a car."], "She will buy a car", "ok", ""),
    (["He has gone out."], "He's gone out", "ok", ""),
    (["They have 5 books."], "they have five books", "ok", ""),
    (["He plays cricket."], "um he plays uh cricket", "ok", ""),
    # ---- present simple slips
    (["He plays cricket."], "He play cricket", "wrong", "vf:base>s"),
    (["They play cricket."], "They plays cricket", "wrong", "vf:s>base"),
    (["She does not like tea."], "She does not likes tea", "wrong", "vf:s>base"),
    (["Does he play cricket?"], "Does he plays cricket", "wrong", "vf:s>base"),
    (["He does not play cricket."], "He not play cricket", "wrong", "missing_aux:does"),
    (["Do you like tea?"], "You like tea", "wrong", "missing_aux:do"),
    (["Does she live in Delhi?"], "She lives in Delhi", "wrong", ""),
    (["I am a teacher."], "I is a teacher", "wrong", "be:is>am"),
    (["They are students."], "They is students", "wrong", "be:is>are"),
    (["He is a doctor."], "He are a doctor", "wrong", "be:are>is"),
    # ---- present continuous slips
    (["He is playing football now."], "He is play football now", "wrong", "vf:base>ing"),
    (["He is playing football now."], "He playing football now", "wrong", "missing_aux:is"),
    (["He is playing football now."], "He plays football now", "wrong", "tense:present_simple>present_continuous"),
    (["They are eating."], "They is eating", "wrong", "be:is>are"),
    (["I am reading a book."], "I am reads a book", "wrong", "vf:s>ing"),
    # ---- present perfect slips
    (["I have seen him."], "I have saw him", "wrong", "vf:v2>v3"),
    (["She has gone home."], "She has went home", "wrong", "vf:v2>v3"),
    (["She has gone home."], "She have gone home", "wrong", "have:have>has"),
    (["They have finished."], "They has finished", "wrong", "have:has>have"),
    (["I have finished my work."], "I finished my work", "wrong", "tense:past_simple>present_perfect"),
    (["I have finished my work."], "I have finish my work", "wrong", "vf:base>v3"),
    (["Has he arrived?"], "He has arrived", "wrong", "qform:q"),
    # ---- present perfect continuous
    (["I have been waiting for two hours."], "I am waiting for two hours", "wrong", "tense:present_continuous>present_perfect_continuous"),
    (["I have been waiting for two hours."], "I have waiting for two hours", "wrong", "missing_aux:been"),
    (["I have been waiting for two hours."], "I have been wait for two hours", "wrong", "vf:base>ing"),
    (["She has been studying since morning."], "She have been studying since morning", "wrong", "have:have>has"),
    # ---- past simple
    (["He came yesterday."], "He comes yesterday", "wrong", ""),
    (["He came yesterday."], "He come yesterday", "wrong", ""),
    (["I went to the market."], "I goed to the market", "wrong", "overreg:goed>went"),
    (["She did not come."], "She did not came", "wrong", "vf:v2>base"),
    (["Did you see the film?"], "Did you saw the film", "wrong", "vf:v2>base"),
    (["I bought a bike."], "I buyed a bike", "wrong", "overreg:buyed>bought"),
    (["I saw him yesterday."], "I have seen him yesterday", "wrong", "tense:present_perfect>past_simple"),
    # ---- past continuous
    (["He was playing football."], "He is playing football", "wrong", ""),
    (["They were sleeping."], "They was sleeping", "wrong", "be:was>were"),
    (["I was reading."], "I were reading", "wrong", "be:were>was"),
    # ---- past perfect
    (["She had left before I came."], "She has left before I came", "wrong", "have:has>had"),
    (["She had left before I came."], "She left before I came", "wrong", ""),
    (["He had gone."], "He had went", "wrong", "vf:v2>v3"),
    # ---- future
    (["She will come tomorrow."], "She comes tomorrow", "wrong", "tense:present_simple>future_simple"),
    (["She will not come."], "She will not comes", "wrong", "vf:s>base"),
    (["I will go there."], "I will going there", "wrong", "vf:ing>base"),
    (["I will be waiting."], "I will waiting", "wrong", "missing_aux:be"),
    (["I will have finished by five."], "I will finished by five", "wrong", ""),
    (["I will have finished by five."], "I have finished by five", "wrong", ""),
    (["By June he will have been teaching for ten years."], "By June he will teach for ten years", "wrong", ""),
    # ---- grammar looks right but the words differ: NEVER wrong
    (["I go to school every day."], "I go to the school every day", "unsure", ""),
    (["He plays cricket every day."], "He plays football every day", "unsure", ""),
    (["He plays cricket every day."], "He plays cricket daily", "unsure", ""),
    (["He eats an apple."], "He eats one apple", "unsure", ""),
    # ---- empty / Hindi
    (["He plays cricket."], "", "empty", ""),
    (["He plays cricket."], "   ", "empty", ""),
    (["He plays cricket."], "वह क्रिकेट खेलता है", "lang", ""),
]

section("verdicts and the primary reason")
for acc, said, want, code in CASES:
    r = C.check(said, acc)
    ok = r["verdict"] == want and (not code or (r["codes"] and r["codes"][0].startswith(code) or code in r["codes"]))
    check(f"{said!r} vs {acc[0]!r} -> {want} {code}".strip(), ok, f"got {r['verdict']} {r.get('codes')}")

section("found by the authors' real sentences")
r = C.check("Priya had never gone to Delhi before.", ["Priya had never been to Delhi before."])
check("had never GONE vs BEEN is a different word, not a missing helping verb", r["verdict"] == "unsure" and not any(c.startswith("missing_aux") for c in r["codes"]), r)
r = C.check("He has waited for two hours.", ["He has been waiting for two hours."])
check("...but has WAITED vs has BEEN WAITING is still the wrong tense", r["verdict"] == "wrong" and any("been" in c or c.startswith("tense") for c in r["codes"]), r)
check("a leading preposition before the wh-phrase is still a question", C.check("At what time will the guests reach our house on Saturday?", ["What time will the guests reach our house on Saturday?"])["verdict"] != "wrong")
r = C.check("We will not be stay in Pune next week.", ["We will not be living in Pune next week.", "We will not be staying in Pune next week."])
check("the answer with the learner's own verb is the one compared (stay -> staying, not stay -> living)", r["verdict"] == "wrong" and r["codes"][0] == "vf:base>ing", r)
r = C.check("When we reaches home what will the children be doing", ["What will the children be doing when we get home?", "What will the children be doing when we reach home?"])
check("a wrong -es on the verb the learner chose is called wrong", r["verdict"] == "wrong", r)

section("a helping verb in the wrong place is ONE mistake, said once")
r = C.check("When Rohan's train will reach Delhi", ["When will Rohan's train reach Delhi?"])
check("a question written as a statement: 'this is a question', not 'will is missing' AND 'will is extra'", r["verdict"] == "wrong" and r["codes"][0] == "qform:q" and not any(c.startswith(("missing_aux", "extra_aux")) for c in r["codes"]), r["codes"])
r = C.check("He always is late", ["He is always late."])
check("a misplaced helping verb in a statement is ONE edit: aux_place", r["verdict"] == "wrong" and r["codes"][0] == "aux_place:is" and not any(c.startswith(("missing_aux", "extra_aux")) for c in r["codes"]), r["codes"])
r = C.check("Where he is going", ["Where is he going?"])
check("'where he is going' is also 'this is a question'", r["verdict"] == "wrong" and r["codes"][0] == "qform:q", r["codes"])

section("variants(): harmless re-orderings only")
from app.lab import bank
low = lambda vs: [v.lower() for v in vs]                                          # noqa: E731 - the checker compares lower-case tokens, so the case of a moved word is cosmetic
check("a trailing time phrase is also accepted first", "every day he plays cricket." in low(bank.variants(["He plays cricket every day."])), bank.variants(["He plays cricket every day."]))
check("a leading time phrase is also accepted last", "she went home yesterday." in low(bank.variants(["Yesterday she went home."])), bank.variants(["Yesterday she went home."]))
check("'since yesterday' is NOT split from its 'since' (no junk answer)", bank.variants(["Rohan has not been going to college since yesterday."]) == ["Rohan has not been going to college since yesterday."], bank.variants(["Rohan has not been going to college since yesterday."]))
check("'by tomorrow' / 'until next week' are not split either", len(bank.variants(["He will finish by tomorrow."])) == 1 and len(bank.variants(["She stayed until next week."])) == 1)
check("variants never contain a duplicate", all(len(v) == len({x.lower() for x in v}) for v in (bank.variants(["He plays cricket every day.", "Every day he plays cricket."]),)))
check("variants of a sentence with no time phrase = itself", bank.variants(["He plays cricket."]) == ["He plays cricket."])

section("the nearest of several accepted answers is the one diffed")
r = C.check("Every morning Ram drink tea", ["Ram drinks tea every morning.", "Every morning Ram drinks tea."])
check("nearest variant", r["verdict"] == "wrong" and r["target"] == "Every morning Ram drinks tea." and r["codes"][0] == "vf:base>s", r)

section("a wrong answer is never 'ok' and an unknown answer is never 'wrong'")
for said in ("he plays cricket", "He PLAYS CRICKET!!", "he, plays cricket."):
    check(f"{said!r} is ok", C.check(said, ["He plays cricket."])["verdict"] == "ok")
for said in ("cricket plays he", "play he cricket"):
    v = C.check(said, ["He plays cricket."])["verdict"]
    check(f"{said!r} is not ok", v != "ok", v)

section("bounded")
r = C.check("word " * 5000, ["He plays cricket."])
check("a huge answer is handled", r["verdict"] in ("wrong", "unsure"), r["verdict"])

main("lab checker")
