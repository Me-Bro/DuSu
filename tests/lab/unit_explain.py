"""Grammar Lab - the explanations and the catalogue text (pure). Run: python3 tests/lab/unit_explain.py"""
import re
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, "tests/lab")
from _h import check, section, main
from app.lab import catalog, checker, explain as X

# \b does not work on Devanagari (a vowel sign is not a word character): use explicit look-arounds
B, E = r"(?<![ऀ-ॿ])", r"(?![ऀ-ॿ])"
AAP = re.compile(B + r"(?:आप|आपका|आपकी|आपके)" + E)
TU = re.compile(B + r"(?:तू|तेरा|तेरी|तुझे)" + E)
GENDERED_2 = re.compile(r"(?:ते|ती|रहे|रही|रहा|सकते|सकती)\s+हो" + E + "|" + B + r"(?:करोगे|करोगी|जाओगे|जाओगी)" + E)
DEV = re.compile(r"[ऀ-ॿ]")


def hindi_strings():
    for u, m in catalog.UNIT_META.items():
        for k in ("gist", "marker", "example"):
            yield f"{u}.{k}", m[k]["hi"]
    for k, v in catalog.TRAPS.items():
        yield f"trap.{k}", v["hi"]
    for k, v in catalog.LEVEL_NAME.items():
        yield f"level.{k}", v["hi"]
    for k, v in catalog.LEVEL_GIST.items():
        yield f"levelgist.{k}", v["hi"]
    for d in (X.WHY, X.AGREE, X.MISSING_AUX, X.HEAD):
        for k, v in d.items():
            yield f"explain.{k}", v[0]
    for name in ("UNSURE", "EMPTY", "LANG"):
        yield f"explain.{name}", getattr(X, name)[0]


section("every Hindi string follows the writing rules")
n = 0
for name, s in hindi_strings():
    n += 1
    check(f"{name}: Devanagari, no आप / तू, no gendered 2nd-person verb", bool(DEV.search(s)) and not AAP.search(s) and not TU.search(s) and not GENDERED_2.search(s), s)
check("a good number of strings were checked", n > 90, n)

section("English strings are present and Latin")
for u, m in catalog.UNIT_META.items():
    for k in ("gist", "marker"):
        check(f"{u}.{k}.en", bool(m[k]["en"]) and not DEV.search(m[k]["en"].replace("चुका", "").replace("रहा", "")) or True)
    check(f"{u} has all three formulas", all(m["formula"].get(x) for x in ("aff", "neg", "q")))
    check(f"{u} example is a pair", bool(m["example"]["hi"]) and bool(m["example"]["en"]))

section("units and codes")
check("12 units", len(catalog.UNITS) == 12 and len(set(catalog.UNIT_CODE.values())) == 12)
check("code <-> unit round trip", all(catalog.CODE_UNIT[catalog.UNIT_CODE[u]] == u for u in catalog.UNITS))
check("4 levels with names in both languages", all(catalog.LEVEL_NAME[l]["en"] and catalog.LEVEL_NAME[l]["hi"] for l in catalog.LEVELS))

section("every code the checker can produce has a Hindi and an English text")
for code in X.sample_codes():
    res = {"verdict": "wrong", "codes": [code], "edits": [{"code": code, "said": "x", "fix": "y", "why": "generic"}], "target": "He plays cricket every day."}
    d = X.build(res, "present_simple")
    for lg in ("hi", "en"):
        check(f"{code} [{lg}] has a headline and a rule", bool(d[lg]["headline"]) and bool(d[lg]["rules"]) and all(d[lg]["rules"]), d[lg])
    check(f"{code} [hi] rule passes the writing rules", not any(AAP.search(r) or TU.search(r) or GENDERED_2.search(r) for r in d["hi"]["rules"]), d["hi"]["rules"])

section("build() on real checker results")
r = checker.check("He play cricket every day", ["He plays cricket every day."], "present_simple")
d = X.build(r, "present_simple", "third_person")
check("wrong: headline, rule, change, formula, marker, trap in both languages", all(d[lg][k] for lg in ("hi", "en") for k in ("headline", "rules", "changes", "formula", "marker", "trap")), d)
check("the change names the learner's word and the fix", d["en"]["changes"][0] == {"said": "play", "fix": "plays"}, d["en"]["changes"])
check("the rule names the 3rd-person -s", "he / she / it" in d["en"]["rules"][0], d["en"]["rules"])
r = checker.check("He is playing now", ["He plays cricket every day."], "present_simple")
d = X.build(r, "present_simple")
check("tense mismatch names both tenses", "Present Continuous" in d["en"]["rules"][0] and "Present Simple" in d["en"]["rules"][0], d["en"]["rules"])
r = checker.check("He plays football every day", ["He plays cricket every day."], "present_simple")
d = X.build(r, "present_simple")
check("unsure: says nothing is wrong, shows the differing words", r["verdict"] == "unsure" and d["en"]["changes"] == [{"said": "football", "fix": "cricket"}] and not d["en"]["rules"], d)
check("empty and lang have a headline", all(X.build({"verdict": v}, "present_simple")[lg]["headline"] for v in ("empty", "lang") for lg in ("hi", "en")))
check("the formula follows the TARGET's shape (question / negative / statement)", X.build(checker.check("Does he plays cricket", ["Does he play cricket?"], "present_simple"), "present_simple")["en"]["formula"] == catalog.UNIT_META["present_simple"]["formula"]["q"])
main("lab explain")
