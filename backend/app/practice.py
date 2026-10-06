"""Practice Room — scoring, metrics and the analysis orchestrator.

DUSU_PRACTICE_ROOM_PLAN.md is the design. The two ideas that shape this file:

1. HYBRID SCORING. An LLM ranks a strong talk far above a weak one but re-scoring the
   same speech wobbles by up to 12-15 points (measured). So whatever can be MEASURED
   (pace, pauses, restarts, time, recogniser confidence) is measured from the word
   timestamps, and the model is only asked for judgements it can ground in quotes
   (content, structure, grammar, vocabulary, a flow/steadiness read). Low temperature,
   median of RUNS runs.
2. LANGUAGE-AWARE RUBRIC (plan §13.6). A Hindi/Hinglish talk is scored on five
   language-neutral categories; Grammar, Vocabulary and Clarity exist for English only —
   Hindi transcripts are machine-normalised and DuSu is not a Hindi coach, so a Hindi
   "grammar score" would be invented. The same strong talk scored 91.5 in Hindi and 91.8
   in English on the shared skills, so the language choice does not move the score.

Pure functions plus two async orchestrators (analyze, build_bridge). No database access
here — main.py persists. The transcript is never logged and never stored server-side.
"""

from __future__ import annotations

import asyncio
import re
import statistics
import unicodedata

from .interview.prompts import practice_analysis_system, practice_bridge_system

KINDS = ("presentation", "viva", "speech", "seminar", "discussion", "custom")
ENABLED_KINDS = ("presentation",)             # Phase 1 — the rest are accepted by the schema/XP table only
LANGS = ("en", "hi", "hinglish")
FEEDBACK_LANGS = ("en", "hinglish")
LEVELS = ("beginner", "intermediate", "advanced")

MIN_WORDS = 40                                # below this (or MIN_SECONDS) → "too short to score", no XP
MIN_SECONDS = 45
MAX_RECORD_SECONDS = 15 * 60
MAX_WORDS = 6000
MAX_CHARS = 30000
RUNS = 2                                      # LLM runs per attempt (median); 3 if quota allows
PAUSE_MIN = 0.7                               # a gap this long between words counts as a pause
LONG_PAUSE = 2.5
SIGNIFICANT_DELTA = 5                         # smaller changes are "about the same" (noise floor, plan §4.3)
DAILY_ATTEMPT_CAP = 30

WEIGHTS_EN = {"fluency": 20, "grammar": 15, "vocabulary": 5, "clarity": 10,
              "content": 20, "structure": 10, "steadiness": 10, "time": 10}
WEIGHTS_HI = {"fluency": 25, "content": 30, "structure": 15, "steadiness": 15, "time": 15}
ORDER_EN = ("fluency", "grammar", "vocabulary", "clarity", "content", "structure", "steadiness", "time")
ORDER_HI = ("fluency", "content", "structure", "steadiness", "time")
JUDGED_EN = ("fluency", "content", "structure", "steadiness", "vocabulary", "grammar")
JUDGED_HI = ("fluency", "content", "structure", "steadiness")
# Categories that mean the same thing in any language — the only ones compared when a
# Hindi attempt is followed by an English attempt of the same talk (the "bridge").
LANGUAGE_NEUTRAL = ("content", "structure", "steadiness", "time")


class AnalysisUnavailable(RuntimeError):
    """Every analysis run failed (provider chain down, or no parseable reply)."""


# ----------------------------------------------------------------------------- text helpers
_PUNCT_RE = re.compile(r"[।॥.,;:!?\"'()\[\]{}\-–—‘’“”]")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def norm(s: str) -> str:
    """Script- and punctuation-insensitive form used for quote checks and counting.
    NFC makes the two Devanagari spellings of nukta letters agree; measured on quoted
    grammar fixes: 6 of 6 matched after this vs 5 of 6 exactly."""
    s = unicodedata.normalize("NFC", str(s or ""))
    s = s.replace("‌", "").replace("‍", "")
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip().casefold()


def clean_text(s, limit: int) -> str:
    """Untrusted text (topic, model output) → single-line-ish, bounded, no control chars."""
    s = _CTRL_RE.sub("", str(s or ""))
    s = _WS_RE.sub(" ", s).strip()
    return s[:limit]


def _num(x, default=None):
    try:
        return max(0, min(100, int(round(float(x)))))
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ----------------------------------------------------------------------------- input cleaning
def clean_words(raw) -> list[tuple[str, float, float]]:
    """[[word, start, end], …] (or {"w","s","e"}) → validated tuples. Bad rows are dropped,
    never trusted: the client is the only source of these numbers (audio never reaches us)."""
    out: list[tuple[str, float, float]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_WORDS]:
        try:
            if isinstance(item, dict):
                w, s, e = item.get("w"), item.get("s"), item.get("e")
            else:
                w, s, e = item[0], item[1], item[2]
            s, e = float(s), float(e)
            w = clean_text(w, 40)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not w or not (0 <= s <= MAX_RECORD_SECONDS + 60) or not (s <= e <= s + 30):
            continue
        out.append((w, s, e))
    return out


def clean_segments(raw) -> list[tuple[float, float, float, float]]:
    """[[start, end, avg_logprob, no_speech_prob], …]"""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:2000]:
        try:
            s, e, lp, ns = float(item[0]), float(item[1]), float(item[2]), float(item[3] if len(item) > 3 else 0.0)
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= s <= e <= MAX_RECORD_SECONDS + 60 and -10 <= lp <= 1:
            out.append((s, e, lp, ns))
    return out


# ----------------------------------------------------------------------------- measured metrics
def count_restarts(toks: list[str]) -> int:
    """Immediate repetitions of a 1-3 word sequence ("we are we are", "I I think")."""
    n, i, c = len(toks), 0, 0
    while i < n:
        hit = False
        for k in (3, 2, 1):
            if i + 2 * k <= n and toks[i:i + k] == toks[i + k:i + 2 * k]:
                if k == 1 and len(toks[i]) > 3:     # "very very" is emphasis; "the the" / "I I" is a restart
                    continue
                c += 1
                i += k
                hit = True
                break
        if not hit:
            i += 1
    return c


def compute_metrics(words: list[tuple[str, float, float]]) -> dict | None:
    n = len(words)
    if n < 8:
        return None
    t0 = words[0][1]
    t1 = max(w[2] for w in words)
    span = max(0.5, t1 - t0)
    gaps = [max(0.0, words[i + 1][1] - words[i][2]) for i in range(n - 1)]
    pauses = [g for g in gaps if g >= PAUSE_MIN]
    long_p = [g for g in gaps if g >= LONG_PAUSE]
    # pace per complete 30 s window → how steady the speaker's speed is
    buckets: dict[int, int] = {}
    for _w, s, _e in words:
        buckets[int((s - t0) // 30)] = buckets.get(int((s - t0) // 30), 0) + 1
    full = [c for idx, c in buckets.items() if idx < int(span // 30)]
    cv = None
    if len(full) >= 3:
        m = statistics.mean(full)
        cv = (statistics.pstdev(full) / m) if m else None
    toks = [norm(w) for w, _s, _e in words]
    toks = [t for t in toks if t]
    restarts = count_restarts(toks)
    return {
        "words": n, "span": round(span, 1), "wpm": round(n / (span / 60.0)),
        "pauses": len(pauses), "long_pauses": len(long_p),
        "longest_pause": round(max(gaps), 1) if gaps else 0.0,
        "pause_ratio": round(sum(pauses) / span, 3),
        "pace_cv": round(cv, 3) if cv is not None else None,
        "restarts": restarts, "restart_rate": round(restarts / (n / 100.0), 2),
    }


def score_pace(wpm: float) -> float:            # English only until Hindi bands are calibrated (plan §13.6)
    if 110 <= wpm <= 150:
        return 100
    if 95 <= wpm < 110 or 150 < wpm <= 165:
        return 85
    if 80 <= wpm < 95 or 165 < wpm <= 185:
        return 65
    return 45


def score_pauses(ratio: float, long_n: int) -> float:
    return _clamp(100 - max(0.0, ratio - 0.10) * 250 - min(25, 5 * long_n))


def score_restarts(rate_per_100: float) -> float:
    return _clamp(100 - 12 * rate_per_100)


def score_cv(cv: float) -> float:
    return _clamp(100 - (cv - 0.15) * (60 / 0.35), 30, 100)


def score_time(actual: float, target: float) -> int | None:
    if not target or target <= 0:
        return None
    d = abs(actual - target) / target
    return 100 if d <= 0.10 else 75 if d <= 0.25 else 45 if d <= 0.50 else 20


def score_clarity(segs: list[tuple[float, float, float, float]]) -> int | None:
    """Recogniser confidence, NOT a pronunciation test (we have no phoneme model)."""
    if not segs:
        return None
    tot = sum(max(0.01, e - s) for s, e, _lp, _ns in segs)
    lp = sum(l * max(0.01, e - s) for s, e, l, _ns in segs) / tot
    if lp >= -0.20:
        return 100
    return round(_clamp(100 - (-0.20 - lp) * (55 / 0.60), 40, 100))


_HEDGES = tuple(norm(p) for p in ("maybe", "probably", "perhaps", "i think", "i guess", "sort of", "kind of",
                                  "i don't know", "not sure", "something like"))
_FILLERS = ("you know", "basically", "actually", "literally", "i mean", "kind of", "sort of",
            "um", "umm", "uh", "uhh", "er", "ah")


def _count_phrase(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<!\w)" + re.escape(norm(phrase)) + r"(?!\w)", text))


def score_hedges(text: str, n_words: int) -> float:
    c = sum(_count_phrase(text, p) for p in _HEDGES)
    return _clamp(100 - min(40, 8 * (c / max(1.0, n_words / 100.0))))


def count_fillers(text: str) -> list[dict]:
    """English only, real words only — Whisper tends to drop um/uh, so those show only if
    the transcript actually contains them; a fake 0 is never displayed."""
    out = []
    for p in _FILLERS:
        c = _count_phrase(text, p)
        if c >= 1:
            out.append({"word": p, "n": c})
    out.sort(key=lambda d: -d["n"])
    return out[:6]


# ----------------------------------------------------------------------------- LLM output handling
def _valid_run(d, english: bool) -> bool:
    if not isinstance(d, dict) or d.get("error"):
        return False
    sc = d.get("scores")
    if not isinstance(sc, dict):
        return False
    need = JUDGED_EN if english else JUDGED_HI
    return all(_num(sc.get(k)) is not None for k in need)


def _small_int(x, hi: int = 20) -> int:
    try:
        return max(0, min(hi, int(x)))
    except (TypeError, ValueError):
        return 0


def _clean_structure(sc) -> dict:
    sc = sc if isinstance(sc, dict) else {}
    return {"introduction": sc.get("introduction") is True, "conclusion": sc.get("conclusion") is True,
            "main_points": _small_int(sc.get("main_points")), "examples": _small_int(sc.get("examples"))}


def _structure_points(sc: dict) -> int:
    """0-100 from the checklist: intro 25 · a REAL conclusion 25 · main points (2+ → 30, 1 → 15) · an example 20."""
    mp, ex = sc["main_points"], sc["examples"]
    return (25 if sc["introduction"] else 0) + (25 if sc["conclusion"] else 0) \
        + (30 if mp >= 2 else 15 if mp == 1 else 0) + (20 if ex >= 1 else 0)


def _clean_list(items, n: int, limit: int) -> list[str]:
    out = []
    for it in items if isinstance(items, list) else []:
        t = clean_text(it if isinstance(it, str) else "", limit)
        if t and t not in out:
            out.append(t)
    return out[:n]


def verified_fixes(runs: list[dict], text_norm: str) -> list[dict]:
    """Grammar fixes whose 'said' is really in the transcript (script/punctuation-insensitive).
    A quote that can't be found is dropped, never shown — a made-up error is worse than none."""
    seen, out = set(), []
    padded = " " + text_norm + " "                       # whole-word match: "he go" must not hit inside "she goes"
    for r in runs:
        for fx in r.get("grammar_fixes") or []:
            if not isinstance(fx, dict):
                continue
            said, better = clean_text(fx.get("said"), 160), clean_text(fx.get("better"), 200)
            ns = norm(said)
            if not said or not better or not ns or ns == norm(better) or ns in seen:
                continue
            if (" " + ns + " ") in padded:
                seen.add(ns)
                out.append({"said": said, "better": better})
    return out[:3]


def verified_words(runs: list[dict], text_norm: str) -> list[str]:
    toks = set(text_norm.split())
    out: list[str] = []
    for r in runs:
        for w in r.get("hard_words") or []:
            w = clean_text(w if isinstance(w, str) else "", 24)
            nw = norm(w)
            if nw and " " not in nw and len(nw) >= 4 and nw in toks and w.lower() not in [x.lower() for x in out]:
                out.append(w)
    return out[:5]


# ----------------------------------------------------------------------------- explanations (one line per bar)
_T = {
    "en": {
        "fluency_pace": "{wpm} words/min · {pauses} pauses · longest {longest}s",
        "fluency_flat": "{pauses} pauses · longest {longest}s · {restarts} restarts",
        "time": "Target {tgt} · you spoke {act}",
        "clarity": "How clearly the recogniser could hear you — not a pronunciation test",
        "steady": "Pace held steady" , "uneven": "Your speed changed a lot between minutes",
        "structure": "intro {i} · {mp} main points · {ex} example(s) · conclusion {c}",
    },
    "hinglish": {
        "fluency_pace": "{wpm} words/min · {pauses} pauses · sabse lamba {longest}s",
        "fluency_flat": "{pauses} pauses · sabse lamba {longest}s · {restarts} restarts",
        "time": "Target {tgt} · aapne {act} bola",
        "clarity": "Recogniser ne aapko kitna saaf suna — pronunciation test nahi hai",
        "steady": "Speed ek jaisi rahi", "uneven": "Minutes ke beech speed kaafi badli",
        "structure": "intro {i} · {mp} main points · {ex} example · conclusion {c}",
    },
}


def _mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def band(overall: int) -> str:
    return "excellent" if overall >= 90 else "good" if overall >= 75 else "developing" if overall >= 60 else "needs_practice"


# ----------------------------------------------------------------------------- the analysis
def _payload(kind, topic, lang, level, target_sec, actual_sec, goal, transcript) -> str:
    topic_line = "<topic>" + (topic or "(not given)") + "</topic>"
    parts = [f"kind: {kind}", f"topic: {topic_line}", f"level setting: {level}",
             f"target length: {_mmss(target_sec) if target_sec else 'not set'}; actual speaking time: {_mmss(actual_sec)}"]
    if goal:
        parts.append(f"student's goal: <topic>{goal}</topic>")
    parts.append("\nTRANSCRIPT:\n" + transcript)
    return "\n".join(parts)


async def analyze(llm, *, kind: str, topic: str, lang: str, feedback_lang: str, level: str,
                  target_sec: int, actual_sec: float, transcript: str, words, segments, goal: str = "") -> dict:
    """Score one rehearsal. Returns {"too_short": True, …} or the full report dict.
    Raises AnalysisUnavailable when no run produced usable JSON."""
    english = lang == "en"
    kind = kind if kind in KINDS else "presentation"
    lang = lang if lang in LANGS else "en"
    feedback_lang = feedback_lang if feedback_lang in FEEDBACK_LANGS else ("en" if english else "hinglish")
    level = level if level in LEVELS else "intermediate"
    topic = clean_text(topic, 200).replace("<", "").replace(">", "")
    goal = clean_text(goal, 120).replace("<", "").replace(">", "")
    transcript = str(transcript or "").strip()[:MAX_CHARS]
    wl = clean_words(words)
    sl = clean_segments(segments)
    n_words = len(wl) if len(wl) >= 8 else len(transcript.split())
    metrics = compute_metrics(wl)
    actual = max(0.0, min(float(actual_sec or 0), MAX_RECORD_SECONDS + 30))
    if metrics:
        actual = max(actual, metrics["span"])        # can't have spoken for longer than you were recording
    if n_words < MIN_WORDS or actual < MIN_SECONDS:
        return {"too_short": True, "words": n_words, "seconds": int(actual)}

    system = practice_analysis_system(kind, lang, feedback_lang, level)
    user = _payload(kind, topic, lang, level, int(target_sec or 0), actual, goal, transcript)
    results = await asyncio.gather(
        *[llm.assess(system, user, max_tokens=1500, temperature=0.2) for _ in range(RUNS)],
        return_exceptions=True)
    runs = [r for r in results if _valid_run(r, english)]
    if not runs:
        first_exc = next((r for r in results if isinstance(r, Exception)), None)
        raise AnalysisUnavailable(str(first_exc) if first_exc else "no parseable analysis reply")

    judged = JUDGED_EN if english else JUDGED_HI
    med = {k: _median([_num(r["scores"].get(k)) for r in runs]) for k in judged}
    rep = min(runs, key=lambda r: sum(abs(_num(r["scores"].get(k)) - med[k]) for k in judged))   # most typical run
    text_norm = norm(transcript)
    T = _T[feedback_lang]

    # ---- plausibility (server-side; the model's genuine_effort flag can only LOWER trust)
    wpm_cap = 230 if english else 280
    genuine = True
    if metrics:
        genuine = metrics["wpm"] <= wpm_cap and metrics["span"] >= 0.35 * actual
    false_votes = sum(1 for r in runs if r.get("genuine_effort") is False)
    if false_votes * 2 >= len(runs):
        genuine = False

    # ---- structure
    sc_checks = [r.get("structure_check") for r in runs if isinstance(r.get("structure_check"), dict)]
    struct_clean = _clean_structure(rep.get("structure_check") if isinstance(rep.get("structure_check"), dict)
                                    else (sc_checks[0] if sc_checks else {}))
    structure_score = round(0.7 * _structure_points(struct_clean) + 0.3 * med["structure"])

    # ---- fluency / steadiness / time / clarity from measurements (+ the model's read)
    cats: dict[str, int | None] = {}
    why: dict[str, str] = {}
    measured: dict[str, bool] = {}
    notes = rep.get("notes") if isinstance(rep.get("notes"), dict) else {}

    def note(k: str) -> str:
        return clean_text(notes.get(k) if isinstance(notes.get(k), str) else "", 110)

    if metrics:
        p_score = score_pauses(metrics["pause_ratio"], metrics["long_pauses"])
        r_score = score_restarts(metrics["restart_rate"])
        flow = (statistics.mean([score_pace(metrics["wpm"]), p_score]) if english else p_score)
        cats["fluency"] = round(0.5 * flow + 0.3 * r_score + 0.2 * med["fluency"])
        why["fluency"] = (T["fluency_pace" if english else "fluency_flat"]).format(
            wpm=metrics["wpm"], pauses=metrics["pauses"], longest=metrics["longest_pause"], restarts=metrics["restarts"])
        measured["fluency"] = True
        parts, weights = [], []
        if metrics["pace_cv"] is not None:
            parts.append(score_cv(metrics["pace_cv"])); weights.append(0.35)
        parts.append(r_score); weights.append(0.15)
        if english:
            parts.append(score_hedges(text_norm, n_words)); weights.append(0.10)
        parts.append(med["steadiness"]); weights.append(0.40)
        cats["steadiness"] = round(sum(p * w for p, w in zip(parts, weights)) / sum(weights))
        why["steadiness"] = note("steadiness") or (T["uneven"] if (metrics["pace_cv"] or 0) > 0.35 else T["steady"])
        measured["steadiness"] = metrics["pace_cv"] is not None
    else:                                          # no word timestamps (rare fallback) → model's read only
        cats["fluency"], cats["steadiness"] = round(med["fluency"]), round(med["steadiness"])
        why["fluency"], why["steadiness"] = note("fluency"), note("steadiness")
        measured["fluency"] = measured["steadiness"] = False

    cats["content"] = round(med["content"])
    why["content"] = note("content")
    cats["structure"] = structure_score
    why["structure"] = T["structure"].format(
        i="✓" if struct_clean["introduction"] else "✗", mp=struct_clean["main_points"],
        ex=struct_clean["examples"], c="✓" if struct_clean["conclusion"] else "✗")
    tscore = score_time(actual, int(target_sec or 0))
    cats["time"] = tscore
    if tscore is not None:
        why["time"] = T["time"].format(tgt=_mmss(target_sec), act=_mmss(actual))
    measured["time"] = True

    fixes: list[dict] = []
    hard: list[str] = []
    fillers: list[dict] = []
    if english:
        fixes = verified_fixes(runs, text_norm)
        err_rate = len(fixes) / max(1.0, n_words / 100.0)
        cats["grammar"] = round(0.5 * med["grammar"] + 0.5 * _clamp(100 - min(40, 10 * err_rate)))
        why["grammar"] = note("grammar")
        cats["vocabulary"] = round(med["vocabulary"])
        why["vocabulary"] = note("vocabulary")
        cats["clarity"] = score_clarity(sl)
        if cats["clarity"] is not None:
            why["clarity"] = T["clarity"]
        measured["clarity"] = True
        hard = verified_words(runs, text_norm)
        fillers = count_fillers(text_norm)

    order = ORDER_EN if english else ORDER_HI
    weights = WEIGHTS_EN if english else WEIGHTS_HI
    avail = [k for k in order if cats.get(k) is not None]
    overall = round(sum(weights[k] * cats[k] for k in avail) / sum(weights[k] for k in avail))
    categories = [{"key": k, "score": int(cats[k]), "weight": weights[k], "why": why.get(k, ""),
                   "measured": bool(measured.get(k))} for k in avail]

    improvements = []
    for it in rep.get("improvements") if isinstance(rep.get("improvements"), list) else []:
        if isinstance(it, dict):
            iss, how = clean_text(it.get("issue"), 150), clean_text(it.get("how"), 230)
            if iss:
                improvements.append({"issue": iss, "how": how})
    return {
        "too_short": False, "kind": kind, "lang": lang, "feedback_lang": feedback_lang, "level": level,
        "overall": overall, "band": band(overall), "categories": categories,
        "strengths": _clean_list(rep.get("strengths"), 3, 170),
        "improvements": improvements[:3],
        "content_gaps": _clean_list(rep.get("content_gaps"), 3, 140),
        "grammar_fixes": fixes, "hard_words": hard, "fillers": fillers,
        "structure": struct_clean,
        "metrics": ({k: metrics[k] for k in ("words", "wpm", "pauses", "long_pauses", "longest_pause", "restarts")}
                    if metrics else {"words": n_words}),
        "genuine_effort": bool(genuine), "words": n_words, "seconds": int(round(actual)),
        "runs_used": len(runs),
    }


# ----------------------------------------------------------------------------- comparison with an earlier attempt
def compute_delta(prev: dict, overall: int, cats: dict, lang: str) -> dict:
    """prev = {attempt_no, lang, overall, scores}. A change smaller than SIGNIFICANT_DELTA is
    reported as noise ('about the same'), never as improvement. When the language changed
    (Hindi → English bridge) only language-neutral categories are compared — the English-only
    ones are a new baseline, never a drop."""
    same_lang = prev.get("lang") == lang
    pscores = prev.get("scores") if isinstance(prev.get("scores"), dict) else {}
    keys = [k for k in cats if k in pscores and (same_lang or k in LANGUAGE_NEUTRAL)]
    per = {}
    for k in keys:
        d = int(cats[k]) - int(pscores[k])
        per[k] = {"delta": d, "significant": abs(d) >= SIGNIFICANT_DELTA}
    out = {"vs_attempt_no": prev.get("attempt_no"), "language_changed": not same_lang, "categories": per}
    if same_lang and prev.get("overall") is not None:
        d = int(overall) - int(prev["overall"])
        out["overall"] = d
        out["significant"] = abs(d) >= SIGNIFICANT_DELTA
    return out


# ----------------------------------------------------------------------------- progression hand-off
def progress_scores(cats: dict, english: bool) -> tuple[dict, set]:
    """Map the Practice categories onto the five Speaker-Progression components. A Hindi
    attempt has no vocabulary / grammar, so those are reported as 'unscored' — NOT as 0,
    which would silently cut 35% of the Performance score (plan §13.7)."""
    scores = {"confidence": cats.get("steadiness") or 0, "continuity": cats.get("fluency") or 0,
              "depth": cats.get("content") or 0}
    unscored: set[str] = set()
    if english:
        scores["vocabulary"] = cats.get("vocabulary") or 0
        scores["grammar_trend"] = cats.get("grammar") or 0
    else:
        unscored = {"vocabulary", "grammar_trend"}
    return scores, unscored


# ----------------------------------------------------------------------------- the English invitation (nag guard, plan §13.4)
def invite_decision(prefs: dict, *, lang: str, genuine: bool, strengths: list[str], seen_today: bool, today: str) -> dict:
    """ONE dismissible card per Hindi/Hinglish attempt, never spoken, never repeated for the
    same topic on the same day, snoozed for 14 days after two 'Not now', and switchable off
    for good. The card is built from a scored strength — no extra model-written praise."""
    off = {"show": False}
    if lang == "en" or not genuine or not strengths:
        return off
    if (prefs or {}).get("english_invite", "on") != "on":
        return off
    if (prefs or {}).get("invite_snooze_until", "") and str(prefs["invite_snooze_until"]) >= today:
        return off
    if seen_today:
        return off
    return {"show": True, "strength": strengths[0]}


# ----------------------------------------------------------------------------- the on-demand bridge
async def build_bridge(llm, *, lang: str, topic: str, transcript: str) -> dict:
    """Hindi/Hinglish talk → an English outline, key phrases, opening and closing line, built
    only from what the student said. Called only when they tap 'Try in English'."""
    transcript = str(transcript or "").strip()[:MAX_CHARS]
    if len(transcript.split()) < 15:
        raise ValueError("too_short")
    topic = clean_text(topic, 200).replace("<", "").replace(">", "")
    user = f"<topic>{topic or '(not given)'}</topic>\n\nTRANSCRIPT:\n{transcript}"
    d = await llm.assess(practice_bridge_system(lang if lang in LANGS else "hi"), user, max_tokens=900, temperature=0.3)
    if not isinstance(d, dict) or d.get("error"):
        raise AnalysisUnavailable("no parseable bridge reply")
    outline = []
    for it in d.get("outline") if isinstance(d.get("outline"), list) else []:
        if isinstance(it, dict):
            p, s = clean_text(it.get("point"), 60), clean_text(it.get("say"), 220)
            if s:
                outline.append({"point": p, "say": s})
    phrases = []
    for it in d.get("key_phrases") if isinstance(d.get("key_phrases"), list) else []:
        if isinstance(it, dict):
            en, hi = clean_text(it.get("en"), 60), clean_text(it.get("hi"), 80)
            if en:
                phrases.append({"en": en, "hi": hi})
    if not outline:
        raise AnalysisUnavailable("empty bridge")
    return {"outline": outline[:6], "key_phrases": phrases[:6],
            "opening": clean_text(d.get("opening"), 220), "closing": clean_text(d.get("closing"), 220)}
