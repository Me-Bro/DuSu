"""Counts, mistakes per 100 words, the honest tally, noise bands, deltas and the rule status machine (pure; plan Appendix A6, D16, D17).

A *unit* is one sentence: {"turn": int, "status": ..., "words": core words, "marks": [mark-like dicts or Marks with rule / severity / weight / conf],
"opp": {rule: correct uses}}. Statuses: ok | natural | fix | unsure | skip[:reason] | unchecked[:reason] (a separate "reason" key also works).

  checked        ok + natural + fix        (a model verdict that passed the gates)
  clean          ok + natural              ("no mistake found" - never "correct")
  errors         every verified SURE error mark in checked units, whatever the display caps say
  per100         100 * errors / words_checked   - the headline; there is no composite score (D16)
  unsure         only-likely sentences: shown softly, in no count
"""

from __future__ import annotations

import math

from . import catalog, norm_level

MIN_CHECKED = 6
MIN_WORDS = 40
DELTA_MIN_CHECKED = 40
DELTA_REL = 0.30

_CHECKED = ("ok", "natural", "fix")
_SKIP_LABEL = {"not_english": "Hindi", "too_short": "too short", "unintelligible": "unclear", "not_a_sentence": "not a sentence"}
_SKIP_ORDER = ("not_english", "too_short", "unintelligible", "not_a_sentence")
_UNCHECKED_LABEL = {"cap": "over the limit", "ai_down": "AI was busy", "budget": "AI keys were busy"}
_UNCHECKED_ORDER = ("cap", "ai_down", "budget")


def _g(m, k, d=None):
    if isinstance(m, dict):
        return m.get(k, d)
    return getattr(m, k, d)


def _status(u) -> tuple[str, str]:
    st = str(_g(u, "status", "") or "").strip().lower()
    base, _, reason = st.partition(":")
    if not reason:
        reason = str(_g(u, "reason", "") or "").strip().lower()
    return base, reason


def _family_of(rule_id: str, given=None) -> str:
    if given:
        return str(given)
    r = catalog.get(rule_id)
    return r.family if r else "other"


def fold_units(units) -> dict:
    """The pure fold of per-sentence units into every number the report shows."""
    checked = clean = fixn = unsure = 0
    skipped: dict[str, int] = {}
    unchecked: dict[str, int] = {}
    words_checked = words_total = errors = tips = 0
    rule_counts: dict[str, dict] = {}
    family_counts: dict[str, int] = {}
    timeline: list[str] = []
    best = cur = 0
    total = 0
    for u in units or ():
        total += 1
        b, reason = _status(u)
        w = max(0, int(_g(u, "words", 0) or 0))
        words_total += w
        if b in _CHECKED:
            checked += 1
            words_checked += w
            if b == "fix":
                fixn += 1
                cur = 0
                timeline.append("x")
            else:
                clean += 1
                cur += 1
                best = max(best, cur)
                timeline.append("o" if b == "ok" else "n")
            for m in _g(u, "marks", ()) or ():
                if _g(m, "conf") != "sure":
                    continue
                rid = str(_g(m, "rule", "") or "")
                if not rid:
                    continue
                rc = rule_counts.setdefault(rid, {"hits": 0, "opp": 0})
                rc["hits"] += 1
                fam = _family_of(rid, _g(m, "family"))
                family_counts[fam] = family_counts.get(fam, 0) + 1
                if _g(m, "severity", "error") == "error":
                    errors += 1
                else:
                    tips += 1
            for r, n in (_g(u, "opp", {}) or {}).items():
                try:
                    rule_counts.setdefault(str(r), {"hits": 0, "opp": 0})["opp"] += max(0, int(n))
                except (TypeError, ValueError):
                    continue
        elif b == "unsure":
            unsure += 1
            cur = 0
            timeline.append("~")
        elif b == "skip":
            reason = reason or "other"
            skipped[reason] = skipped.get(reason, 0) + 1
            timeline.append("-")                                  # a skipped sentence is not judged: it does not break a clean run
        else:
            reason = reason or "other"
            unchecked[reason] = unchecked.get(reason, 0) + 1
            cur = 0
            timeline.append("?")
    per100 = round(100.0 * errors / words_checked, 1) if words_checked > 0 else None
    out = {
        "total": total, "checked": checked, "clean": clean, "fix": fixn, "unsure": unsure,
        "skipped": skipped, "skipped_total": sum(skipped.values()), "unchecked": unchecked, "unchecked_total": sum(unchecked.values()),
        "words_checked": words_checked, "words_total": words_total, "errors": errors, "tips": tips, "per100": per100,
        "rule_counts": rule_counts, "family_counts": family_counts, "best_run": best, "timeline": "".join(timeline),
    }
    out["enough"] = enough(out)
    return out


unit_counts = fold_units


def enough(counts) -> bool:
    """Minimum evidence: >= 6 checked sentences AND >= 40 checked words; otherwise the numbers are withheld (marks are still shown)."""
    return int(_g(counts, "checked", 0) or 0) >= MIN_CHECKED and int(_g(counts, "words_checked", 0) or 0) >= MIN_WORDS


def tally_text(counts) -> str:
    """The honest tally: 'Checked 28 of 34 sentences; 3 Hindi, 2 too short, 1 unclear' (+ 'N not sure', 'N not checked (...)')."""
    total = int(_g(counts, "total", 0) or 0)
    checked = int(_g(counts, "checked", 0) or 0)
    if total <= 0:
        return "No sentences yet"
    parts: list[str] = []
    sk = dict(_g(counts, "skipped", {}) or {})
    for r in _SKIP_ORDER + tuple(sorted(k for k in sk if k not in _SKIP_ORDER)):
        if sk.get(r):
            parts.append(f"{sk[r]} {_SKIP_LABEL.get(r, r.replace('_', ' '))}")
    un = int(_g(counts, "unsure", 0) or 0)
    if un:
        parts.append(f"{un} not sure")
    uc = dict(_g(counts, "unchecked", {}) or {})
    for r in _UNCHECKED_ORDER + tuple(sorted(k for k in uc if k not in _UNCHECKED_ORDER)):
        if uc.get(r):
            parts.append(f"{uc[r]} not checked ({_UNCHECKED_LABEL.get(r, r.replace('_', ' '))})")
    s = f"Checked {checked} of {total} sentences"
    return s + ("; " + ", ".join(parts) if parts else "")


def noise_clean_share(n_a: int, n_b: int) -> int:
    """The sampling noise, in points of clean share, for two windows of n_a and n_b checked sentences (D17)."""
    if n_a <= 0 or n_b <= 0:
        return 100
    return max(5, round(100 * math.sqrt(0.2 * (1.0 / n_a + 1.0 / n_b))))


def _share(w) -> float | None:
    c = int(_g(w, "checked", 0) or 0)
    return 100.0 * int(_g(w, "clean", 0) or 0) / c if c > 0 else None


def _per100(w) -> float | None:
    p = _g(w, "per100")
    if p is not None:
        return float(p)
    wc = int(_g(w, "words_checked", 0) or 0)
    return 100.0 * int(_g(w, "errors", 0) or 0) / wc if wc > 0 else None


def delta(a, b):
    """'Better than last time' between an earlier window `a` and a later window `b` (fold dicts + {source, rules_version, level}).
    None unless each window has >= 40 checked sentences, the source / rules_version / level band match, and the change is beyond the noise
    band (clean share) or >= 30 % relative on per100. Otherwise the trend is shown as plain numbers."""
    if not a or not b:
        return None
    ca, cb = int(_g(a, "checked", 0) or 0), int(_g(b, "checked", 0) or 0)
    if ca < DELTA_MIN_CHECKED or cb < DELTA_MIN_CHECKED:
        return None
    for k in ("source", "rules_version"):
        va, vb = _g(a, k), _g(b, k)
        if va is None or vb is None or va != vb:
            return None
    if norm_level(_g(a, "level")) != norm_level(_g(b, "level")):
        return None
    sa, sb, pa, pb = _share(a), _share(b), _per100(a), _per100(b)
    if sa is None or sb is None or pa is None or pb is None:
        return None
    noise = noise_clean_share(ca, cb)
    fires: list[int] = []                                         # +1 = better, -1 = worse
    basis: list[str] = []
    if abs(sb - sa) > noise:
        fires.append(1 if sb > sa else -1)
        basis.append("share")
    rel = None
    if pa > 0:
        rel = (pb - pa) / pa
        if abs(rel) >= DELTA_REL:
            fires.append(1 if pb < pa else -1)
            basis.append("per100")
    if not fires or len(set(fires)) > 1:
        return None                                               # nothing beyond noise, or the two measures disagree
    return {"direction": "better" if fires[0] > 0 else "worse", "basis": basis, "noise": noise,
            "share_a": round(sa, 1), "share_b": round(sb, 1), "per100_a": round(pa, 1), "per100_b": round(pb, 1),
            "per100_rel": None if rel is None else round(rel, 3)}


# --------------------------------------------------------------------------------------------- the rule status machine
def _rows(history, key):
    out = []
    for s in history:
        r = ((_g(s, "rules", {}) or {}).get(key)) or {}
        out.append((int(_g(r, "hits", 0) or 0), int(_g(r, "opp", 0) or 0), max(0, int(_g(s, "words_checked", 0) or 0))))
    return out


def _nw_window(rows) -> bool:
    return sum(1 for h, _, _ in rows[-5:] if h > 0) >= 2 or sum(h for h, _, _ in rows[-3:]) >= 3


def _is_fixed(rows) -> bool:
    total = sum(h for h, _, _ in rows)
    if total < 3:
        return False
    last = max((i for i, r in enumerate(rows) if r[0] > 0), default=-1)
    if last < 0:
        return False
    after = rows[last + 1:]
    if len(after) < 2:
        return False
    has_opp = any(o > 0 for _, o, _ in rows)
    words_after = sum(w for _, _, w in after)
    if words_after < (300 if has_opp else 500):
        return False
    if has_opp and sum(o for _, o, _ in after) < 5:
        return False
    return any(_nw_window(rows[:k + 1]) for k in range(last + 1))   # it was a real pattern once


def _is_improving(rows) -> bool:
    if len(rows) < 6:
        return False
    cur, prev = rows[-3:], rows[-6:-3]
    wc, wp = sum(w for _, _, w in cur), sum(w for _, _, w in prev)
    hc, hp = sum(h for h, _, _ in cur), sum(h for h, _, _ in prev)
    if wc < 150 or wp < 150 or hp < 3 or hc < 1:
        return False
    rc, rp = 100.0 * hc / wc, 100.0 * hp / wp
    return rc <= 0.5 * rp and (rp - rc) >= 0.5


def _core_state(rows) -> str:
    total = sum(h for h, _, _ in rows)
    if total == 0:
        return "unknown"
    if _is_fixed(rows):
        return "fixed"
    if _is_improving(rows):
        return "improving"
    if _nw_window(rows):
        return "needs_work"
    if total <= 2 and sum(1 for h, _, _ in rows if h > 0) <= 1:
        return "new"
    return "unknown"                                              # hits long ago and not enough speaking since to tell


def rule_states(history, now=None) -> dict:
    """{rule or rule#entry: {state, hits, regressed}} from per-session {ts, words_checked, rules:{key:{hits, opp}}} (oldest -> newest).
    States: new | needs_work | improving | fixed | unknown. SILENCE ALONE NEVER PRODUCES 'fixed' (it needs sessions, words and, where the
    rule has opportunities, correct uses). A hit after a 'fixed' state returns needs_work with regressed=True."""
    hist = list(history or ())[-60:]
    if now is not None:
        keep = []
        for s in hist:
            try:
                if _g(s, "ts") is not None and _g(s, "ts") > now:
                    continue
            except TypeError:
                pass
            keep.append(s)
        hist = keep
    keys: list[str] = []
    seen = set()
    for s in hist:
        for k in (_g(s, "rules", {}) or {}):
            if k not in seen:
                seen.add(k)
                keys.append(k)
    out: dict[str, dict] = {}
    for key in keys:
        rows = _rows(hist, key)
        total = sum(h for h, _, _ in rows)
        state = _core_state(rows)
        regressed = False
        first_fixed = next((k for k in range(1, len(rows) + 1) if _core_state(rows[:k]) == "fixed"), None)
        if first_fixed is not None and state != "fixed" and any(h > 0 for h, _, _ in rows[first_fixed:]):
            state, regressed = "needs_work", True
        out[key] = {"state": state, "hits": total, "regressed": regressed}
    return out


def focus_limit(level) -> int:
    """What to fix first: 3 for beginners (A1 / A2), else 5."""
    return 3 if norm_level(level) in ("A1", "A2") else 5


def top_focus(rule_counts_or_states, limit=None, *, level=None) -> list[dict]:
    """Rank rules by hits x weight x 1.2 (when needs_work). A rule is a pattern only from 2 hits; tips (natural / polish) and rules already
    'fixed' are not focus items. `limit` defaults to focus_limit(level)."""
    if limit is None:
        limit = focus_limit(level)
    ranked = []
    for key, v in (rule_counts_or_states or {}).items():
        hits = int(_g(v, "hits", 0) or 0)
        if hits < 2:
            continue
        r = catalog.get(key)
        if r is not None and r.severity != "error":
            continue
        state = _g(v, "state")
        if state == "fixed":
            continue
        weight = r.weight if r else 1
        score = hits * weight * (1.2 if state == "needs_work" else 1.0)
        ranked.append({"rule": key, "hits": hits, "weight": weight, "score": round(score, 3), "state": state})
    ranked.sort(key=lambda d: (-d["score"], -d["hits"], d["rule"]))
    return ranked[:max(0, int(limit))]


__all__ = ["fold_units", "unit_counts", "enough", "tally_text", "noise_clean_share", "delta", "rule_states", "top_focus", "focus_limit"]
