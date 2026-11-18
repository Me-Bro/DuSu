"""Grammar Lab - the bank against the checker (pure): every accepted answer is accepted; no wrong version of it ever is.  Run: python3 tests/lab/unit_bank.py"""
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, "tests/lab")
from _h import check, section, main
from _mut import wrongs
from app.lab import bank, catalog, checker, forms as F

items = bank.load()
section(f"the bank: {len(items)} items")
check("some items are authored", len(items) > 0)

bad_ok, bad_not_ok, total, n_wrong, n_unsure = [], [], 0, 0, 0
unsure_examples = []
for it in sorted(items.values(), key=lambda i: i.id):
    acc = bank.variants(it.en)
    for a in acc:                                                                    # every accepted answer (and its harmless re-orderings, and its going-to / contraction forms) is ok
        if checker.check(a, acc, it.unit)["verdict"] != "ok":
            bad_not_ok.append((it.id, a))
    for variant in (a for a in it.en):
        for kind, w in wrongs(variant):
            total += 1
            r = checker.check(w, acc, it.unit)
            if r["verdict"] == "ok":
                bad_ok.append((it.id, kind, w))
            elif r["verdict"] == "wrong":
                n_wrong += 1
            else:
                n_unsure += 1
                if len(unsure_examples) < 25:
                    unsure_examples.append((it.id, kind, w, r.get("codes")))
check("every accepted answer of every item is accepted", not bad_not_ok, bad_not_ok[:5])
check(f"NO wrong version is ever accepted ({total} wrong versions tried)", not bad_ok, bad_ok[:8])
check(f"at least 93% of the wrong versions are called wrong, not just 'unsure' ({n_wrong} wrong, {n_unsure} unsure)", total and n_wrong / total >= 0.93, f"{n_wrong}/{total}")
if unsure_examples:
    print("   unsure examples (the checker's blind spots, for the owner to read):")
    for u in unsure_examples[:12]:
        print("    ", u)

section("each item's answers read as its unit")
bad = [(i.id, a) for i in items.values() for a in i.en if i.unit not in F.forms_of(a)]
check("every accepted answer reads as the item's unit", not bad, bad[:5])
section("the Hindi sentences")
import re
DEV = re.compile(r"[ऀ-ॿ]")
check("every Hindi sentence is Devanagari with no Latin letters", all(DEV.search(i.hi) and not re.search(r"[A-Za-z]", i.hi) for i in items.values()))
check("no Hindi sentence is repeated", len({i.hi for i in items.values()}) == len(items))
check("no English first answer is repeated", len({" ".join(F.norm_tokens(i.en[0])) for i in items.values()}) == len(items))
main("lab bank")
