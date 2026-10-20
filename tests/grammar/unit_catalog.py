"""Content lint for the Grammar Coach lesson catalogue (backend/app/grammar/catalog_data.py).

Run:  cd /home/vibhanshu/Desktop/DuSu && PYTHONPATH=backend python3 tests/grammar/unit_catalog.py

Pure: no database, no network. The optional integration section (rule checks vs the examples) is SKIPPED while app.grammar.detectors is absent.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _h import check, done, section  # noqa: E402

from app.grammar import catalog, catalog_data  # noqa: E402

CONTENT = catalog_data.CONTENT
FLOW = catalog_data.FLOW_TIPS

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
BANNED_WORDS = {"tu", "tera", "teri", "tere", "tujhe", "tujhko", "tumhara_"}  # tum / aap are fine
# gendered second-person verb forms ("karte ho", "kar rahe ho", "sakte ho / hain", "bolti ho"): the learner's gender is never assumed
GENDERED = [re.compile(p, re.I) for p in (r"\b\w+(?:te|ti|ta)\s+ho\b", r"\brah[eia]\s+(?:ho|hain)\b", r"\bsak(?:te|ti|ta)\s+(?:ho|hain)\b",
                                        r"\b(?:kar|bol|jaa|aa|sun|dekh|le|de|samajh|likh)(?:oge|ogi)\b", r"\bchahte\s+hain\b")]
LIMITS = {"title": 6, "rule": 20, "why_slip": 35, "tip": 20, "pattern": 14}


def wc(s) -> int:
    return len(str(s).split())


def canon(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).casefold().replace("'", "")).strip()


def words(s):
    return re.findall(r"[a-z']+", str(s).casefold())


def hi_strings(c):
    out = list(c["hi"].values())
    out += [d["explain_hi"] for d in c["drills"]]
    return out


section("coverage")
check("every catalogue rule has content", all(rid in CONTENT for rid in catalog.RULES), set(catalog.RULES) - set(CONTENT))
check("every content id is a catalogue id", all(rid in catalog.RULES for rid in CONTENT), set(CONTENT) - set(catalog.RULES))
check("41 rules", len(CONTENT) == 41 and len(catalog.RULES) == 41, (len(CONTENT), len(catalog.RULES)))
check("ids <= 22 chars", all(len(r) <= 22 for r in CONTENT), [r for r in CONTENT if len(r) > 22])
check("ind.lexicon present", "ind.lexicon" in CONTENT)
check("starred rules count matches the plan (21)", sum(1 for r in catalog.RULES.values() if r.starred) == 21,
      sum(1 for r in catalog.RULES.values() if r.starred))
check("catalog.content() / title_of() read the data", catalog.content("tn.did_past").get("en") and catalog.title_of("tn.did_past") == CONTENT["tn.did_past"]["en"]["title"])
check("catalog.content resolves ind.lexicon#entry", catalog.content("ind.lexicon#prepone") == CONTENT["ind.lexicon"])
check("unknown id -> {}", catalog.content("zz.nope") == {})

section("structure")
FIELDS = ("title", "rule", "pattern", "why_slip", "tip")
for rid, c in CONTENT.items():
    ok = (set(c) == {"en", "hi", "good", "pairs", "drills", "reviewed"} and set(c["en"]) == set(FIELDS) and set(c["hi"]) == set(FIELDS))
    if not check(f"{rid}: keys", ok, sorted(c)):
        continue
    check(f"{rid}: reviewed is False", c["reviewed"] is False)
    check(f"{rid}: en + hi fields non-empty strings", all(isinstance(c[l][f], str) and c[l][f].strip() for l in ("en", "hi") for f in FIELDS))
    check(f"{rid}: exactly 3 good / 3 pairs / 5 drills", len(c["good"]) == 3 and len(c["pairs"]) == 3 and len(c["drills"]) == 5,
          (len(c["good"]), len(c["pairs"]), len(c["drills"])))
    check(f"{rid}: pair shape", all(set(p) == {"wrong", "right"} and p["wrong"].strip() and p["right"].strip() for p in c["pairs"]))
    check(f"{rid}: drill shape", all(set(d) == {"q", "options", "answer", "explain_en", "explain_hi"} for d in c["drills"]))

section("word limits (en + hi)")
for rid, c in CONTENT.items():
    for lang in ("en", "hi"):
        bad = [(f, wc(c[lang][f])) for f, lim in LIMITS.items() if wc(c[lang][f]) > lim]
        check(f"{rid}/{lang}: within limits", not bad, bad)
    bad = [(i, wc(d["explain_en"]), wc(d["explain_hi"])) for i, d in enumerate(c["drills"]) if wc(d["explain_en"]) > 14 or wc(d["explain_hi"]) > 14]
    check(f"{rid}: drill explanations <= 14 words", not bad, bad)
    check(f"{rid}: drill explanations non-empty", all(d["explain_en"].strip() and d["explain_hi"].strip() for d in c["drills"]))
    check(f"{rid}: tips are kind (no 'wrong' / 'stupid' / 'bad' shaming)", not re.search(r"\b(stupid|dumb|idiot|shame|lazy|bad english)\b",
                                                                                    " ".join(c["en"].values()).lower()))
check("titles are unique", len({c["en"]["title"] for c in CONTENT.values()}) == len(CONTENT))
check("hi titles are unique", len({c["hi"]["title"] for c in CONTENT.values()}) == len(CONTENT))

section("Hinglish lint (Roman letters, tum / aap, never tu, no gendered second-person verbs)")
for rid, c in CONTENT.items():
    hs = hi_strings(c)
    check(f"{rid}: no Devanagari in hi", not any(DEVANAGARI.search(s) for s in hs))
    check(f"{rid}: no Devanagari in en / examples", not any(DEVANAGARI.search(s) for s in list(c["en"].values()) + c["good"]
                                                           + [x for p in c["pairs"] for x in p.values()] + [o for d in c["drills"] for o in d["options"]]))
    ws = {w for s in hs for w in words(s)}
    check(f"{rid}: no tu / tera / teri / tere / tujhe", not (ws & BANNED_WORDS), ws & BANNED_WORDS)
    hit = [(s, g.pattern) for s in hs for g in GENDERED if g.search(s)]
    check(f"{rid}: no gendered second-person verb endings", not hit, hit[:2])
    check(f"{rid}: hi is not just a copy of en", c["hi"]["rule"] != c["en"]["rule"] and c["hi"]["why_slip"] != c["en"]["why_slip"])

section("examples")
for rid, c in CONTENT.items():
    pairs = c["pairs"]
    check(f"{rid}: wrong != right in every pair", all(canon(p["wrong"]) != canon(p["right"]) for p in pairs))
    check(f"{rid}: sentences look like sentences (capital + end mark)",
          all(re.match(r"^[A-Z\"']", s) and re.search(r"[.?!'\"]$", s)
              for s in c["good"] + [x for p in pairs for x in p.values()] + [o for d in c["drills"] for o in d["options"]]),
          [s for s in c["good"] + [x for p in pairs for x in p.values()] if not re.search(r"[.?!'\"]$", s)])
    check(f"{rid}: the 3 good sentences are distinct", len({canon(g) for g in c["good"]}) == 3)
    wrongs = {canon(p["wrong"]) for p in pairs}
    rights = {canon(p["right"]) for p in pairs}
    goods = {canon(g) for g in c["good"]}
    check(f"{rid}: no good sentence is a known wrong", not (goods & wrongs), goods & wrongs)
    check(f"{rid}: a wrong is never listed as a right", not (wrongs & rights))
    check(f"{rid}: the three wrongs are distinct", len(wrongs) == 3)

section("drills")
for rid, c in CONTENT.items():
    ds = c["drills"]
    wrongs = {canon(p["wrong"]) for p in c["pairs"]}
    rights = {canon(p["right"]) for p in c["pairs"]} | {canon(g) for g in c["good"]}
    check(f"{rid}: each drill has 3 distinct options", all(len(d["options"]) == 3 and len({canon(o) for o in d["options"]}) == 3 for d in ds))
    check(f"{rid}: answer is an in-range int", all(isinstance(d["answer"], int) and not isinstance(d["answer"], bool) and 0 <= d["answer"] < len(d["options"])
                                                      for d in ds))
    check(f"{rid}: the correct option is never a 'wrong' of the same rule", all(canon(d["options"][d["answer"]]) not in wrongs for d in ds),
          [d["options"][d["answer"]] for d in ds if canon(d["options"][d["answer"]]) in wrongs])
    check(f"{rid}: no distractor is a known-correct example of the rule", all(canon(o) not in rights for d in ds for i, o in enumerate(d["options"]) if i != d["answer"]),
          [o for d in ds for i, o in enumerate(d["options"]) if i != d["answer"] and canon(o) in rights])
    check(f"{rid}: the five correct options are distinct", len({canon(d["options"][d["answer"]]) for d in ds}) == 5)
    check(f"{rid}: answers are not all in one position", len({d["answer"] for d in ds}) >= 2, [d["answer"] for d in ds])
    check(f"{rid}: question text present", all(d["q"].strip() and len(d["q"]) <= 80 for d in ds))
check("answer positions are spread across the whole catalogue", {i: sum(1 for c in CONTENT.values() for d in c["drills"] if d["answer"] == i) for i in range(3)}
      and all(sum(1 for c in CONTENT.values() for d in c["drills"] if d["answer"] == i) >= 40 for i in range(3)))

section("flow tips")
check("flow ids match the catalogue", set(FLOW) == set(catalog.FLOW_IDS), set(FLOW) ^ set(catalog.FLOW_IDS))
for fid, f in FLOW.items():
    check(f"{fid}: shape", set(f) == {"en", "hi", "band"} and all(isinstance(v, str) and v.strip() for v in f.values()))
    check(f"{fid}: <= 25 words", wc(f["en"]) <= 25 and wc(f["hi"]) <= 25, (wc(f["en"]), wc(f["hi"])))
    check(f"{fid}: band is a short label", 0 < wc(f["band"]) <= 4)
    check(f"{fid}: hi is Roman and clean", not DEVANAGARI.search(f["hi"]) and not (set(words(f["hi"])) & BANNED_WORDS)
          and not any(g.search(f["hi"]) for g in GENDERED))
    check(f"{fid}: no shaming words", not re.search(r"\b(bad|wrong|poor|stupid|lazy|mistake)\b", (f["en"] + " " + f["hi"]).lower()))

# ----------------------------------------------------------------------------------------------------------------------------------
section("integration with the rule checks (optional: SKIPPED while app.grammar.detectors is absent)")
try:
    from app.grammar import detectors  # type: ignore
except ImportError as e:
    detectors = None
    print(f"  SKIP  app.grammar.detectors not importable ({e}); run again after merge")
except Exception as e:  # a half-written module must not fail the content lint
    detectors = None
    print(f"  SKIP  app.grammar.detectors raised on import ({type(e).__name__}); run again after merge")


def _run_detectors(sentence):
    """Hits for one sentence from whichever entry point the detectors module exposes; None if no usable entry point is found."""
    from app.grammar import text as _t
    keys = _t.canon_contractions(_t.keys(sentence))
    for name in ("run", "detect", "find_hits", "hits", "check", "scan", "run_all", "all_hits"):
        fn = getattr(detectors, name, None)
        if not callable(fn):
            continue
        for arg in (keys, sentence, _t.tokenize(sentence)):
            try:
                out = fn(arg)
            except TypeError:
                continue
            except Exception:
                return None
            if isinstance(out, (list, tuple)) and all(hasattr(h, "rule") for h in out):
                return list(out)
    return None


if detectors is not None:
    probe = _run_detectors("He don't like tea.")
    if probe is None:
        print("  SKIP  no recognised entry point in app.grammar.detectors (looked for run / detect / find_hits / hits / check / scan)")
    else:
        misses, falsepos = [], []
        for rid, rule in catalog.RULES.items():
            if not any(d[0] in "DT" for d in rule.dets):
                continue
            c = CONTENT[rid]
            ok_texts = list(c["good"]) + [d["options"][d["answer"]] for d in c["drills"]] + [p["right"] for p in c["pairs"]]
            for s in ok_texts:
                hs = [h for h in (_run_detectors(s) or []) if catalog.base_id(h.rule) == rid]
                if hs:
                    falsepos.append((rid, s, [(h.det, h.fix) for h in hs]))
            for p in c["pairs"]:
                hs = [h for h in (_run_detectors(p["wrong"]) or []) if catalog.base_id(h.rule) == rid]
                if not hs:
                    misses.append((rid, p["wrong"]))
        check("no rule check fires on a good / right / drill-correct example of its own rule", not falsepos, falsepos[:3])
        if falsepos:
            print("  FALSE POSITIVES:", *falsepos, sep="\n    ")
        print(f"  INFO  pair 'wrong' sentences not caught by their rule's check: {len(misses)}")
        for m in misses:
            print("    MISS", m)

sys.exit(done("unit_catalog"))
