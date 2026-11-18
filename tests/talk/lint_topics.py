"""Talk - lint the topic bank.  Run from the repo root:

    python3 tests/talk/lint_topics.py [a1|a2|b1 ...]      (no argument = every authored module)
    python3 tests/talk/lint_topics.py --file path/to/rows.py   (a module with a TOPICS list that is not in the bank yet)

Exit 1 on any ERROR.  Authors run it on their own band until it is clean.  Pure: no database, no network, no model.  It runs exactly the validation the server runs
when it loads the bank (`backend/app/talk/topics.py: validate`), plus a few bank-level reports (warnings only).

The schema (every field is checked):
  {"id": "a1-morning-routine", "band": "A1", "cat": "daily",
   "title":  {"en": "...", "hi": "..."},
   "opener": {"en": "...?", "hi": "..."},          # DuSu's first line + its Hindi subtitle - it must ask something
   "starters": [{"en", "hi"} x 3],                 # sentences / questions the learner can use
   "vocab":  [{"en", "hi"} x 6..8],
   "focus": "<a Grammar Lab unit id>"}
Hindi: Devanagari for Hindi words + Latin for everyday English words; तुम never आप or तू; no second-person verb that guesses gender (करते हो, रहे हो, जाओगे ...);
no gendered first-person verb in a STARTER (मैं ... जाता हूँ).  See backend/app/talk/topics.py (hindi_problems) for the exact patterns.
"""

import importlib.util
import os
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app.talk import topics as T          # noqa: E402

EXPECT_PER_BAND = 30


def _load_file(path: str):
    spec = importlib.util.spec_from_file_location("talk_rows", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "TOPICS", None)


def main(argv: list) -> int:
    errs: list = []
    warns: list = []
    notes: list = []
    topics: list = []
    args = [a for a in argv if not a.startswith("-")]
    if "--file" in argv:
        i = argv.index("--file")
        path = argv[i + 1]
        rows = _load_file(path)
        if rows is None:
            print(f"{path}: no TOPICS list")
            return 1
        topics, errs, warns = T.validate(rows)
    else:
        names = [a.lower() for a in args] or list(T.MODULES)
        for a in names:
            if a not in T.MODULES:
                errs.append(f"{a}: not a band module (one of {T.MODULES})")
        names = [n for n in names if n in T.MODULES]
        bank = T.load_modules(names)
        topics, errs2, warns = bank.topics, bank.errors, bank.warnings
        errs.extend(errs2)
        for m in bank.missing:
            (errs if args else notes).append(f"module {m}: backend/app/talk/bank/{m}.py does not exist" + ("" if args else " (not authored yet)"))
    # ---- bank-level reports (warnings): size and spread per band
    by_band: dict = {}
    for t in topics:
        by_band.setdefault(t["band"], []).append(t)
    for b, ts in sorted(by_band.items()):
        if len(ts) != EXPECT_PER_BAND:
            warns.append(f"{b}: {len(ts)} topics (the plan is {EXPECT_PER_BAND})")
        cats = Counter(t["cat"] for t in ts)
        if len(cats) < 8:
            warns.append(f"{b}: only {len(cats)} categories used ({sorted(cats)}) - aim for at least 8 so the days feel different")
        top, n = cats.most_common(1)[0]
        if n > 5:
            warns.append(f"{b}: category {top!r} has {n} topics (more than 5)")
        foc = Counter(t["focus"] for t in ts)
        if len(foc) < 4:
            warns.append(f"{b}: only {len(foc)} different grammar focuses {sorted(foc)} - aim for at least 4")
        v = Counter(x["en"].lower() for t in ts for x in t["vocab"])
        for w, c in v.items():
            if c > 6:
                warns.append(f"{b}: vocabulary word {w!r} is in {c} topics (a chip that shows up everywhere teaches little)")
    for e in errs:
        print("ERROR  ", e)
    for w in warns:
        print("warning", w)
    for n in notes:
        print("note   ", n)
    print(f"\n{len(topics)} valid topic(s)  {sum(1 for _ in errs)} error(s)  {len(warns)} warning(s)  " + "  ".join(f"{b}={len(ts)}" for b, ts in sorted(by_band.items())))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
