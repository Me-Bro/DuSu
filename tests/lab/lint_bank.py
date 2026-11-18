"""Grammar Lab - lint the item bank. Run from the repo root:  python3 tests/lab/lint_bank.py [unit ...]   (no unit = every authored unit)

Exit 1 on any ERROR.  Authors run it on their own units until it is clean.  Pure: no database, no network.
"""
import re
import sys

sys.path.insert(0, "backend")
from app.lab import bank, catalog, checker, forms as F       # noqa: E402

DEV = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
GENDERED_1SG = re.compile(r"(?:ता|ती|रहा|रही|चुका|चुकी)\s+(?:हूँ|हूं|था|थी|होऊँगा|होऊँगी)|ूँगा|ूँगी|ूंगा|ूंगी|ऊँगा|ऊँगी")
MAX_WORDS = {"easy": 9, "medium": 12, "hard": 17, "extra": 19}
ERR: list = []
WARN: list = []


def err(i, msg):
    ERR.append(f"{i}: {msg}")


def warn(i, msg):
    WARN.append(f"{i}: {msg}")


def lint(only: list) -> dict:
    items = {}
    try:
        items = bank.load()
    except ValueError as e:
        err("bank", str(e))
        return {}
    units = [u for u in catalog.UNITS if (not only or u in only) and any(i.unit == u for i in items.values())]
    for u in only:
        if u not in catalog.UNITS:
            err(u, "not a unit")
        elif u not in units:
            err(u, f"no bank module (backend/app/lab/bank/{u}.py)")
    hi_seen, en_seen = {}, {}
    stats = {}
    for it in sorted(items.values(), key=lambda x: x.id):
        if it.unit not in units:
            continue
        i = it.id
        want_prefix = f"{catalog.UNIT_CODE[it.unit]}-{catalog.LEVEL_CODE[it.level]}-"
        if not re.fullmatch(re.escape(want_prefix) + r"\d{2}", i):
            err(i, f"id must be {want_prefix}NN")
        if it.trap and it.trap not in catalog.TRAP_IDS:
            err(i, f"unknown trap {it.trap!r} (one of {sorted(catalog.TRAP_IDS)})")
        # ---- Hindi
        hi = it.hi.strip()
        if not DEV.search(hi):
            err(i, "the Hindi sentence has no Devanagari")
        if LATIN.search(hi):
            err(i, f"Latin letters in the Hindi sentence: {hi}")
        if not hi.endswith(("।", "?", "!")):
            err(i, "the Hindi sentence must end with । or ?")
        n_hi = len(hi.split())
        if not 3 <= n_hi <= 18:
            err(i, f"Hindi length {n_hi} words (3-18)")
        if re.search(r"\bतू\b|\bतेरा\b|\bतेरी\b|\bतुझे\b|\bतुझ\b", hi):
            err(i, "use तुम / आप as a subject, never तू")
        toks = hi.replace("।", " ").replace("?", " ").split()
        if "मैं" in toks and GENDERED_1SG.search(hi):
            err(i, f"'मैं' with a gendered verb ending (learners are every gender; use a name, हम, वह ... ): {hi}")
        if hi in hi_seen:
            err(i, f"the same Hindi sentence as {hi_seen[hi]}")
        hi_seen[hi] = i
        # ---- English
        if not 1 <= len(it.en) <= 4:
            err(i, "1-4 accepted English answers")
        form_sets = []
        for k, s in enumerate(it.en):
            s2 = s.strip()
            if not s2 or not s2[0].isupper() or s2[-1] not in ".?!":
                err(i, f"English must start with a capital and end with . ? or ! : {s!r}")
            if DEV.search(s2):
                err(i, f"Devanagari in English: {s!r}")
            n_en = len(s2.split())
            if n_en > MAX_WORDS[it.level] and k == 0:
                err(i, f"{it.level}: {n_en} words is too long (max {MAX_WORDS[it.level]}): {s!r}")
            if n_en < 2:
                err(i, f"too short: {s!r}")
            fs = F.forms_of(s2)
            form_sets.append(fs)
            if it.unit not in fs:
                err(i, f"{s!r} reads as {sorted(fs) or 'no tense'}, not {it.unit}")
            elif fs == {"present_simple", "past_simple"}:
                warn(i, f"ambiguous verb (put / cut / read ...): {s!r} - add a time word")
            r = checker.check(s2, bank.variants(it.en), it.unit)
            if r["verdict"] != "ok":
                err(i, f"its own answer is not accepted: {s!r} -> {r['verdict']}")
        if len(set(map(frozenset, form_sets))) > 1:
            warn(i, f"the accepted answers read as different clause tenses (fine for a time clause, check it is intended): {[sorted(f) for f in form_sets]}")
        low = [re.sub(r"[^a-z0-9' ]+", " ", s.lower()).split().__repr__() for s in it.en]
        if len(set(low)) != len(low):
            err(i, "two accepted answers are the same")
        first = " ".join(re.sub(r"[^a-z0-9' ]+", " ", it.en[0].lower()).split())
        if first in en_seen:
            err(i, f"the same English answer as {en_seen[first]}")
        en_seen[first] = i
        # ---- stats for the distribution rules
        ts = F.norm_tokens(it.en[0])
        st = stats.setdefault((it.unit, it.level), {"n": 0, "neg": 0, "q": 0, "aff": 0, "trap": 0, "irr": 0, "multi": 0})
        st["n"] += 1
        neg, q = F.has_negation(ts), F.question_in(it.en[0]) or it.en[0].strip().endswith("?")
        st["neg"] += int(neg and not q)
        st["q"] += int(q)
        st["aff"] += int(not neg and not q)
        st["trap"] += int(bool(it.trap))
        st["irr"] += int(any(tok in __import__("app.grammar.lexicon", fromlist=["IRREG"]).IRREG or tok in ("went", "gone", "ate", "eaten", "saw", "seen", "bought", "wrote", "written") for tok in ts))
        st["multi"] += int(len(F.clauses(it.en[0])) > 1)
    for u in units:
        for lv in catalog.LEVELS:
            st = stats.get((u, lv))
            if not st:
                err(f"{u}/{lv}", "no items")
                continue
            if not 12 <= st["n"] <= 14:
                err(f"{u}/{lv}", f"{st['n']} items (12-14)")
            if lv == "easy" and st["aff"] < 10:
                err(f"{u}/{lv}", f"only {st['aff']} affirmative statements (>= 10: easy is short plain sentences)")
            if lv == "medium" and (st["neg"] < 3 or st["q"] < 3):
                err(f"{u}/{lv}", f"medium needs >= 3 negatives and >= 3 questions (has {st['neg']} / {st['q']})")
            if lv in ("hard", "extra") and (st["neg"] < 2 or st["q"] < 2):
                err(f"{u}/{lv}", f"{lv} needs >= 2 negatives and >= 2 questions (has {st['neg']} / {st['q']})")
            if lv == "hard" and st["multi"] < 4:
                err(f"{u}/{lv}", f"hard needs >= 4 sentences with two clauses (has {st['multi']})")
            if lv == "extra" and st["trap"] < 6:
                err(f"{u}/{lv}", f"extra needs >= 6 items with a trap tag (has {st['trap']})")
    return stats


if __name__ == "__main__":
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    stats = lint(only)
    if "-q" not in sys.argv:
        print(f"{'unit':28} " + " ".join(f"{lv:>16}" for lv in catalog.LEVELS) + "     (n/aff/neg/q)")
        for u in catalog.UNITS:
            if any(k[0] == u for k in stats):
                print(f"{u:28} " + " ".join(f"{(str(stats[(u, lv)]['n']) + '/' + str(stats[(u, lv)]['aff']) + '/' + str(stats[(u, lv)]['neg']) + '/' + str(stats[(u, lv)]['q'])) if (u, lv) in stats else '-':>16}" for lv in catalog.LEVELS))
    for w in WARN[:40]:
        print("  warn ", w)
    for e in ERR:
        print("  ERROR", e)
    print(f"\n{len(stats)} unit-levels, {sum(s['n'] for s in stats.values())} items, {len(ERR)} errors, {len(WARN)} warnings")
    sys.exit(1 if ERR else 0)
