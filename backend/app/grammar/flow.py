"""Flow metrics over a learner's English sentences (pure; plan Appendix A6).

How the sentences hang together, not whether each is correct: average length, run-ons, choppy runs, "and then" chains, repeated starters,
connector variety, fillers, restarts. Computed only with >= 8 sentences (fewer says nothing).

Boundary honesty. Web Speech text has no punctuation, so "sentence" length there is OUR guess: run-on and choppy are computed ONLY for the
punctuated sources (whisper / gemini) and are None for chrome; a sentence that was cut by us (no terminal, or forced) never counts as evidence of
either. Fillers are measured only for whisper (the others drop um / uh: a fake 0 is never shown, the value is None). Restarts are approximate
for chrome (flagged only for the other sources).
"""

from __future__ import annotations

from collections import Counter

from .. import practice
from .lexicon_lang import CONNECTORS, CONNECTORS_START_ONLY, YESNO
from .segment import core_range
from .text import tokenize
from .types import Sent

MIN_SENTENCES = 8
LONG_SENT = 25
SHORT_SENT = 5
CHOPPY_RUN = 3
THEN_CHAIN = 3

FLOW_IDS = ("f.run_on", "f.choppy", "f.starters", "f.connectors", "f.fillers", "f.restarts")

# phrase -> category, longest phrases matched first
_PHRASES: dict[tuple[str, ...], str] = {}
for _cat, _items in CONNECTORS.items():
    for _p in _items:
        _PHRASES.setdefault(tuple(_p.split()), _cat)
_MAXLEN = max(len(p) for p in _PHRASES)


def _core_keys(s: Sent) -> tuple[list[str], list[str]]:
    ks = [t.key for t in tokenize(s.text)]
    a, b = core_range(ks, 0, len(ks))
    return ks, ks[a:b]


def _connectors(core: list[str], start_only_ok: bool) -> list[tuple[str, str]]:
    """[(phrase, category)] found in one sentence's core words. Words that are connectors only at the start count only there."""
    found: list[tuple[str, str]] = []
    i, n = 0, len(core)
    while i < n:
        hit = None
        for ln in range(min(_MAXLEN, n - i), 0, -1):
            ph = tuple(core[i:i + ln])
            if ph in _PHRASES:
                hit = (ph, ln)
                break
        if hit is None:
            i += 1
            continue
        ph, ln = hit
        phrase = " ".join(ph)
        if phrase in CONNECTORS_START_ONLY and i != 0:
            i += ln
            continue
        found.append((phrase, _PHRASES[ph]))
        i += ln
    return found


def flow_metrics(sents, *, source: str, text: str | None = None, duration_sec=None) -> dict | None:
    """`sents`: the English units already judged checkable (the caller filters). None below 8 sentences."""
    sents = list(sents or [])
    if len(sents) < MIN_SENTENCES:
        return None
    source = source if source in ("chrome", "whisper", "gemini") else "chrome"
    punct_ok = source in ("whisper", "gemini")
    both = [_core_keys(s) for s in sents]
    fulls = [x[0] for x in both]
    cores = [x[1] for x in both]
    n_sent = len(sents)
    total_words = sum(len(c) for c in cores)
    avg_words = round(total_words / n_sent, 1)

    # run-on / choppy: only on punctuated sources, only on sentences whose boundaries are real
    share_long = choppy_runs = None
    if punct_ok:
        trusted = [(s.punct and not s.forced) for s in sents]
        n_tr = sum(trusted)
        share_long = round(sum(1 for s, ok in zip(sents, trusted) if ok and s.n_words >= LONG_SENT) / n_tr, 3) if n_tr else 0.0
        choppy_runs = 0
        run = 0
        for s, c, ok in zip(sents, cores, trusted):
            if c and all(k in YESNO for k in c):
                continue                                          # "yes." / "okay." neither breaks nor extends a run
            if ok and s.n_words <= SHORT_SENT:
                run += 1
                if run == CHOPPY_RUN:
                    choppy_runs += 1
            else:
                run = 0

    # "and then / then" chains: a unit with >= 3 of them
    chains = 0
    max_then = 0
    for c in fulls:
        t = sum(1 for k in c if k == "then")
        max_then = max(max_then, t)
        if t >= THEN_CHAIN:
            chains += 1

    # repeated starters
    starters = [c[0] for c in cores if c]
    top = Counter(starters).most_common(1)
    starter_top = (top[0][0], round(top[0][1] / len(starters), 3)) if starters else ("", 0.0)
    consec = best_run = 0
    prev = None
    for w in starters:
        consec = consec + 1 if w == prev else 1
        best_run = max(best_run, consec)
        prev = w
    starter_repeat = bool(starters) and (best_run >= 3 or (starter_top[1] >= 0.5 if starter_top[0] == "i" else starter_top[1] >= 0.4))

    # connector variety
    found: list[tuple[str, str]] = []
    for c in cores:
        found.extend(_connectors(c, True))
    distinct = sorted({p for p, _ in found})
    cats = sorted({cat for _, cat in found})
    per100 = round(100 * len(distinct) / total_words, 1) if total_words else 0.0

    # fillers (whisper only) and restarts (approximate)
    full = text if text is not None else " ".join(s.text for s in sents)
    norm = practice.norm(full)
    toks = norm.split()
    fillers_per100 = None
    if source == "whisper" and toks:
        fillers_per100 = round(100 * sum(d["n"] for d in practice.count_fillers(norm)) / len(toks), 1)
    restarts = practice.count_restarts(toks)
    restarts_per100 = round(100 * restarts / len(toks), 1) if toks else 0.0

    flags: list[str] = []
    if punct_ok and (avg_words > LONG_SENT or (share_long or 0) >= 0.25):
        flags.append("f.run_on")
    if punct_ok and (avg_words < 6 or (choppy_runs or 0) >= 2):
        flags.append("f.choppy")
    if starter_repeat:
        flags.append("f.starters")
    if (len(cats) < 2 and total_words >= 100) or chains >= 2:
        flags.append("f.connectors")
    if fillers_per100 is not None and fillers_per100 >= 4.0:
        flags.append("f.fillers")
    if punct_ok and restarts >= 3 and restarts_per100 >= 2.0:
        flags.append("f.restarts")

    wpm = None
    try:
        d = float(duration_sec) if duration_sec is not None else 0.0
        if d >= 5:
            wpm = round(len(toks) * 60.0 / d)
    except (TypeError, ValueError):
        wpm = None

    return {
        "source": source,
        "approx": source == "chrome",
        "punct_ok": punct_ok,
        "n_sentences": n_sent,
        "n_words": total_words,
        "avg_words": avg_words,
        "share_long": share_long,
        "run_on": (("f.run_on" in flags) if punct_ok else None),
        "choppy_runs": choppy_runs,
        "choppy": (("f.choppy" in flags) if punct_ok else None),
        "and_then_chains": chains,
        "and_then_max": max_then,
        "starter_top": starter_top,
        "starter_repeat": starter_repeat,
        "connector_variety": {"distinct": len(distinct), "per100": per100, "categories": len(cats), "cats": cats, "good": len(cats) >= 3},
        "fillers_per100": fillers_per100,
        "restarts": restarts,
        "restarts_per100": restarts_per100,
        "wpm": wpm,
        "flags": flags,
    }
