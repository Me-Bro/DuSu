"""OWNER-RUN gold-set evaluation of the Grammar Coach engine against the REAL model chain (plan section 15 item 4, spike S2).

*** THIS SPENDS MODEL CALLS (free-tier quota; a full 3-run pass is roughly 3 x 60 batches). ***
It refuses to run unless the environment variable GC_REAL=1 is set. The pure metric / gate functions below are importable without any
provider, network or backend import (tests/grammar/unit_gold.py exercises them); the engine is imported lazily inside main().

    cd /home/vibhanshu/Desktop/DuSu
    GC_REAL=1 GC_CHAIN=gemini GC_RUNS=3 PYTHONPATH=backend python3 tests/grammar/real_model.py

Environment
    GC_REAL=1          required (otherwise the script exits 2 without doing anything)
    GC_CHAIN           default | gemini | groq | groq+openrouter | gemini+openrouter   (the other providers' keys are blanked in
                       app.config.settings before the first call; the chain actually used is printed)
    GC_RUNS            runs over the gold set (default 3; the stability metrics need >= 2, the ship gate wants 3)
    GC_SLEEP           seconds to sleep between batches (default 2)
    GC_ONLY            comma list of groups to run (clean,error,multi,trap,twin,hindi,inject) - a SUBSET run, the gate is then INCOMPLETE
    GC_LIMIT           at most N items per group (smoke test) - the gate is then INCOMPLETE
    GC_RECALL_BASIS    any (default: a sure OR likely verified mark counts as found) | sure (only sure marks)
    GC_OUT             write a JSON dump (item ids, statuses, rule ids, confidences - never learner text) to this path

Exit code: 0 = every gate passed on a complete run; 1 = at least one gate FAILED; 2 = not run / could not run / passed but INCOMPLETE
(subset, fewer than 3 runs, or a metric with no data) - an incomplete pass is never certified.

Learner text is never printed: only item ids, rule ids and numbers.

DEFINITIONS (the single source of truth is this file; the tests pin them)
  item observation   the engine segments each gold item (ONE turn per item); the rows of that turn give the item status:
                     any row `fix` -> fix; every row skip:* -> skip; else any `unsure` -> unsure; any `unchecked:*` -> unchecked; any `natural` -> natural;
                     else ok.  status class: ok|natural -> "ok", fix -> "fix", skip -> "skip", anything else -> "other".
  gold mark found    an engine mark (hidden-by-display-cap included) whose quote OVERLAPS the gold quote span AND whose rule is the same rule id (base id,
                     `ind.lexicon#x` == `ind.lexicon`) or the same family (tn/ag/ar/pr/wd/st/pn+md/ind). Basis `any` = sure or likely; `sure` = sure only.
  rule-id accuracy   over gold marks that were OVERLAPPED by any mark: exact = an overlapping mark has the same base rule id; family = same family.
  false positive     a negative item (no expected marks, not expected-skip) with a SHOWN mark of confidence `sure` and severity error|natural
                     (`fp_sure`, the gate); `fp_any` = any shown error|natural mark incl. `likely` (reported, not gated).
  fix match          single-error items (exactly one gold mark, not ind.lexicon): among item-runs where a `sure` mark overlaps the gold span with a
                     matching family, the mark's replacement (or the sentence with it applied, or the engine's corrected sentence) equals an acceptable
                     fix_ok replacement (normalised: case, punctuation and n't/not folded). End-to-end variant (all item-runs) is also reported.
  Hindi skip         recall = observed-skip item-runs / expected-skip item-runs of group `hindi`; precision = expected-skip item-runs / observed-skip
                     item-runs over ALL items; plus the number of rows that are skipped yet carry a mark (must be 0).
  injection clean    every `inject` item-run has the expected status class (ok items: no sure mark; fix items: a found gold mark).
  stability          over run pairs: Jaccard of the sets of items whose status is `fix`, and agreement of the item status class (mean over pairs).
  cost               engine model calls per 100 sentences (all rows incl. skipped); p95 latency of single model calls (nearest rank).
  top-15 rules       the 15 highest-weight rules: weight desc, starred first, then rule id (catalog weights; computed in main()).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import time
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLD_PATH = HERE / "gold.jsonl"
BACKEND = HERE.parent.parent / "backend"

# --- the ship gate (plan section 15 item 4). Every entry: (metric key, operator, threshold, label)
GATE = {
    "fp_sure_first150": ("==", 0, "shown 'sure' false positives in the first 150 clean items (all runs)"),
    "fp_sure_neg_rate": ("<=", 0.03, "shown 'sure' false-positive rate over all negative items"),
    "recall_top15": (">=", 0.70, "recall on the 15 highest-weight rules"),
    "recall_all": (">=", 0.55, "recall on all rules"),
    "rule_exact": (">=", 0.85, "rule id exact"),
    "rule_family": (">=", 0.95, "rule family"),
    "fix_match": (">=", 0.75, "corrected-sentence match (single-error items)"),
    "hindi_recall": (">=", 0.95, "Hindi skip recall"),
    "hindi_precision": (">=", 0.95, "Hindi skip precision"),
    "marks_on_skipped": ("==", 0, "marks on skipped sentences"),
    "inject_clean": (">=", 1.0, "injection items unchanged"),
    "stab_jaccard": (">=", 0.85, "stability: Jaccard of flagged items"),
    "stab_agree": (">=", 0.90, "stability: status agreement"),
    "calls_per_100": ("<=", 9.0, "model calls per 100 sentences"),
    "p95_latency": ("<", 20.0, "p95 call latency (s)"),
}
MIN_RUNS = 3
BATCH_ITEMS = 12
EPS = 1e-9
FAMILY = {"tn": "Tense", "ag": "Agreement", "ar": "Articles", "pr": "Prepositions", "wd": "Word choice", "st": "Sentence structure",
          "pn": "Modals & pronouns", "md": "Modals & pronouns", "ind": "Natural English"}
SKIP_EQUIV = {"unintelligible": "unintelligible", "not_a_sentence": "unintelligible", "not_english": "not_english", "too_short": "too_short"}


# ============================================================================================ pure helpers (importable, no I/O except load_gold)
def load_gold(path=GOLD_PATH) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"gold.jsonl line {n}: not JSON ({e.__class__.__name__})") from None
    return items


def norm(s) -> str:
    """Comparison form: case-folded, curly quotes straightened, n't / cannot / won't expanded, punctuation and apostrophes dropped, spaces collapsed."""
    s = str(s or "").casefold().replace("’", "'").replace("‘", "'")
    s = s.replace("won't", "will not").replace("can't", "can not").replace("cannot", "can not").replace("n't", " not")
    s = re.sub(r"[^\w\s]", " ", s.replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


def base_id(rule) -> str:
    return str(rule or "").split("#")[0]


def family_of(rule) -> str:
    return FAMILY.get(base_id(rule).split(".")[0], "")


def rule_relation(gold_rule, mark_rule) -> str:
    """exact (same base id) | family | none."""
    if base_id(gold_rule) and base_id(gold_rule) == base_id(mark_rule):
        return "exact"
    f = family_of(gold_rule)
    return "family" if f and f == family_of(mark_rule) else "none"


_REL_RANK = {"exact": 2, "family": 1, "none": 0}


def find_span(text, quote):
    """(start, end) of the first whole-token, case-insensitive occurrence of `quote` in `text`, else None."""
    q = str(quote or "").strip()
    if not q:
        return None
    m = re.search(r"(?<![\w'])" + re.escape(q) + r"(?![\w'])", str(text or ""), re.I)
    return (m.start(), m.end()) if m else None


def marks_overlap(text, gold_quote, mark_quote) -> bool:
    """Do two quotes cover a common stretch of `text`? (token fallback when one of them cannot be located verbatim)."""
    a, b = find_span(text, gold_quote), find_span(text, mark_quote)
    if a and b:
        return a[0] < b[1] and b[0] < a[1]
    ta, tb = set(norm(gold_quote).split()), set(norm(mark_quote).split())
    return bool(ta & tb)


def item_status(rows) -> str:
    sts = [str(r.get("status") or "") for r in rows or ()]
    if not sts:
        return "skip"
    if any(s == "fix" for s in sts):
        return "fix"
    if all(s.startswith("skip") for s in sts):
        return "skip"
    live = [s for s in sts if not s.startswith("skip")]
    if any(s == "unsure" for s in live):
        return "unsure"
    if any(s.startswith("unchecked") for s in live):
        return "unchecked"
    if any(s == "natural" for s in live):
        return "natural"
    return "ok"


def status_class(st) -> str:
    st = str(st or "")
    if st in ("ok", "natural"):
        return "ok"
    if st in ("fix", "skip"):
        return st
    return "other"


def skip_reason(rows) -> str:
    for r in rows or ():
        s = str(r.get("status") or "")
        if s.startswith("skip:"):
            return SKIP_EQUIV.get(s[5:], s[5:])
    return ""


def observe_item(rows) -> dict:
    """The engine rows of ONE item (one turn) -> {"status", "rows", "marks"}."""
    rows = list(rows or [])
    marks = [dict(m, _row=k) for k, r in enumerate(rows) for m in (r.get("marks") or [])]
    return {"status": item_status(rows), "rows": rows, "marks": marks}


def _eligible(m, basis):
    return m.get("conf") == "sure" if basis == "sure" else True


def match_gold(item, obs, basis="any") -> list[dict]:
    """One dict per gold mark: {rule, found, overlapped, relation, exact, family, mark}."""
    out = []
    for g in item["expect"]["marks"]:
        best, best_rel = None, "none"
        overlapped = False
        for m in obs.get("marks", ()):
            if not _eligible(m, basis) or not marks_overlap(item["text"], g["quote"], m.get("quote", "")):
                continue
            overlapped = True
            rel = rule_relation(g["rule"], m.get("rule"))
            if _REL_RANK[rel] > _REL_RANK[best_rel] or best is None:
                best, best_rel = m, rel
        out.append({"rule": g["rule"], "found": best_rel in ("exact", "family"), "overlapped": overlapped, "relation": best_rel,
                    "exact": best_rel == "exact", "family": best_rel in ("exact", "family"), "mark": best if best_rel != "none" else None})
    return out


def fp_flags(obs) -> dict:
    shown = [m for m in obs.get("marks", ()) if m.get("shown", True) and m.get("severity", "error") in ("error", "natural")]
    sure = [m for m in shown if m.get("conf") == "sure"]
    return {"sure": bool(sure), "any": bool(shown), "rules": sorted({str(m.get("rule")) for m in sure})}


def _replace_quote(text, quote, repl):
    span = find_span(text, quote)
    return None if span is None else text[:span[0]] + repl + text[span[1]:]


def fix_matches(item, gold_mark, mark, row) -> bool:
    """Does the engine's replacement amount to an acceptable fix for the gold mark?"""
    ok_fixes = [norm(f) for f in gold_mark["fix_ok"]]
    if norm(mark.get("fix")) in ok_fixes:
        return True
    row_text = row.get("text", "") if row else ""
    expected = {norm(x) for f in gold_mark["fix_ok"] if (x := _replace_quote(row_text, gold_mark["quote"], f)) is not None}
    if not expected:
        return False
    applied = _replace_quote(row_text, mark.get("quote", ""), mark.get("fix", ""))
    if applied is not None and norm(applied) in expected:
        return True
    return bool(row) and norm(row.get("fixed", "")) in expected


def is_single_error(item) -> bool:
    ms = item["expect"]["marks"]
    return item["expect"]["status"] == "fix" and len(ms) == 1 and base_id(ms[0]["rule"]) != "ind.lexicon"


def is_negative(item) -> bool:
    return not item["expect"]["marks"] and item["expect"]["status"] != "skip"


def top_rules(weights: dict, n=15) -> list[str]:
    """`weights` = {rule id: (weight, starred)} -> the n highest-weight rules (weight desc, starred first, id)."""
    return [r for r, _ in sorted(weights.items(), key=lambda kv: (-kv[1][0], not kv[1][1], kv[0]))[:n]]


def percentile(values, p=95):
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    return vals[max(0, math.ceil(p / 100 * len(vals)) - 1)]


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return 1.0 if not (a | b) else len(a & b) / len(a | b)


def stability(runs) -> dict:
    """Mean (and min) over run pairs of the Jaccard of `fix` items and the status-class agreement. None with fewer than two runs."""
    if len(runs) < 2:
        return {"jaccard": None, "jaccard_min": None, "agree": None, "agree_min": None, "pairs": 0}
    js, ag = [], []
    for a, b in combinations(runs, 2):
        ids = sorted(set(a["obs"]) & set(b["obs"]))
        js.append(jaccard({i for i in ids if a["obs"][i]["status"] == "fix"}, {i for i in ids if b["obs"][i]["status"] == "fix"}))
        ag.append(sum(status_class(a["obs"][i]["status"]) == status_class(b["obs"][i]["status"]) for i in ids) / len(ids) if ids else 1.0)
    return {"jaccard": sum(js) / len(js), "jaccard_min": min(js), "agree": sum(ag) / len(ag), "agree_min": min(ag), "pairs": len(js)}


def _ratio(n, d):
    return None if not d else n / d


def compute_metrics(items, runs, top=(), basis="any") -> dict:
    """`runs`: [{"obs": {item id: observation}, "calls": int, "sentences": int, "latencies": [seconds]}]. Only items present in a run's obs count."""
    clean_ids = [it["id"] for it in items if it["group"] == "clean"]
    first150 = set(clean_ids[:150])
    top = set(top)
    c = {k: 0 for k in ("neg_n", "fp_sure", "fp_any", "clean_n", "clean_fp_sure", "first150_fp_sure", "first150_n",
                        "gold_n", "found", "found_top", "gold_top", "found_sure", "overlapped", "exact", "family",
                        "fix_attempt", "fix_ok", "fix_total", "hin_exp", "hin_tp", "skip_obs", "skip_obs_tp", "skip_reason_ok", "marks_on_skipped",
                        "inj_n", "inj_ok", "other_n", "live_n", "calls", "sentences")}
    per_rule: dict = {}
    fp_items: dict = {}
    miss_items: dict = {}
    inj_fail: dict = {}
    lat: list = []
    for ri, run in enumerate(runs):
        c["calls"] += int(run.get("calls", 0))
        c["sentences"] += int(run.get("sentences", 0))
        lat.extend(run.get("latencies") or [])
        for it in items:
            obs = run["obs"].get(it["id"])
            if obs is None:
                continue
            exp = it["expect"]
            if obs["status"] != "skip":
                c["live_n"] += 1
                if obs["status"] in ("unsure", "unchecked"):
                    c["other_n"] += 1
            for r in obs.get("rows", ()):
                if str(r.get("status", "")).startswith("skip") and r.get("marks"):
                    c["marks_on_skipped"] += 1
            if obs["status"] == "skip":
                c["skip_obs"] += 1
                if exp["status"] == "skip":
                    c["skip_obs_tp"] += 1
                    if exp.get("skip") and skip_reason(obs.get("rows")) == SKIP_EQUIV.get(exp["skip"], exp["skip"]):
                        c["skip_reason_ok"] += 1
            if it["group"] == "hindi" and exp["status"] == "skip":
                c["hin_exp"] += 1
                c["hin_tp"] += obs["status"] == "skip"
            # ---- negatives
            if is_negative(it):
                fl = fp_flags(obs)
                c["neg_n"] += 1
                c["fp_sure"] += fl["sure"]
                c["fp_any"] += fl["any"]
                if it["group"] == "clean":
                    c["clean_n"] += 1
                    c["clean_fp_sure"] += fl["sure"]
                if it["id"] in first150:
                    c["first150_n"] += 1
                    c["first150_fp_sure"] += fl["sure"]
                if fl["sure"]:
                    fp_items.setdefault(it["id"], set()).update(fl["rules"] or {"?"})
            # ---- recall / rule accuracy / fix match
            if exp["marks"]:
                got = match_gold(it, obs, basis)
                got_sure = match_gold(it, obs, "sure")
                for k, g in enumerate(got):
                    rid = base_id(g["rule"])
                    pr = per_rule.setdefault(rid, [0, 0])
                    pr[0] += 1
                    c["gold_n"] += 1
                    c["found"] += g["found"]
                    c["found_sure"] += got_sure[k]["found"]
                    pr[1] += g["found"]
                    if rid in top:
                        c["gold_top"] += 1
                        c["found_top"] += g["found"]
                    if g["overlapped"]:
                        c["overlapped"] += 1
                        c["exact"] += g["exact"]
                        c["family"] += g["family"]
                    if not g["found"]:
                        miss_items.setdefault(it["id"], set()).add(rid)
                if is_single_error(it):
                    c["fix_total"] += 1
                    gs = got_sure[0]
                    if gs["found"] and gs["mark"] is not None:
                        c["fix_attempt"] += 1
                        row = obs["rows"][gs["mark"]["_row"]] if obs.get("rows") else None
                        c["fix_ok"] += fix_matches(it, it["expect"]["marks"][0], gs["mark"], row)
            # ---- injection
            if it["group"] == "inject":
                c["inj_n"] += 1
                ok = status_class(obs["status"]) == status_class(exp["status"])
                if ok and exp["status"] == "ok":
                    ok = not fp_flags(obs)["sure"]
                if ok and exp["status"] == "fix":
                    ok = all(g["found"] for g in match_gold(it, obs, "any"))
                c["inj_ok"] += ok
                if not ok:
                    inj_fail[it["id"]] = inj_fail.get(it["id"], 0) + 1
    st = stability(runs)
    m = {
        "runs": len(runs), "counts": c,
        "fp_sure_first150": c["first150_fp_sure"] if c["first150_n"] else None, "first150_n": c["first150_n"],
        "fp_sure_neg_rate": _ratio(c["fp_sure"], c["neg_n"]), "fp_any_neg_rate": _ratio(c["fp_any"], c["neg_n"]),
        "fp_sure_clean_rate": _ratio(c["clean_fp_sure"], c["clean_n"]),
        "recall_all": _ratio(c["found"], c["gold_n"]), "recall_top15": _ratio(c["found_top"], c["gold_top"]), "recall_all_sure_only": _ratio(c["found_sure"], c["gold_n"]),
        "rule_exact": _ratio(c["exact"], c["overlapped"]), "rule_family": _ratio(c["family"], c["overlapped"]),
        "fix_match": _ratio(c["fix_ok"], c["fix_attempt"]), "fix_match_end_to_end": _ratio(c["fix_ok"], c["fix_total"]),
        "hindi_recall": _ratio(c["hin_tp"], c["hin_exp"]), "hindi_precision": _ratio(c["skip_obs_tp"], c["skip_obs"]),
        "skip_reason_acc": _ratio(c["skip_reason_ok"], c["skip_obs_tp"]), "marks_on_skipped": c["marks_on_skipped"] if c["live_n"] or c["skip_obs"] else None,
        "inject_clean": _ratio(c["inj_ok"], c["inj_n"]),
        "stab_jaccard": st["jaccard"], "stab_jaccard_min": st["jaccard_min"], "stab_agree": st["agree"], "stab_agree_min": st["agree_min"],
        "calls_per_100": None if not c["sentences"] else 100.0 * c["calls"] / c["sentences"],
        "p95_latency": percentile(lat, 95), "unsure_rate": _ratio(c["other_n"], c["live_n"]),
        "per_rule_recall": {r: (v[1], v[0]) for r, v in sorted(per_rule.items())},
        "fp_items": {k: sorted(v) for k, v in sorted(fp_items.items())}, "miss_items": {k: sorted(v) for k, v in sorted(miss_items.items())},
        "inject_fail": inj_fail,
    }
    return m


def _cmp(value, op, thr) -> bool:
    if op == "==":
        return abs(value - thr) <= EPS
    if op == "<=":
        return value <= thr + EPS
    if op == ">=":
        return value >= thr - EPS
    if op == "<":
        return value < thr - EPS
    raise ValueError(op)


def ship_gate(metrics: dict, complete: bool = True) -> dict:
    """Apply GATE. -> {"checks": [{key, label, value, op, threshold, ok (True | False | None = no data)}], "failures": [...], "incomplete": bool,
    "verdict": "PASS" | "FAIL" | "INCOMPLETE", "exit": 0 | 1 | 2}. A metric with no data is `None` (not evaluated), never a pass."""
    checks, failures, nodata = [], [], []
    for key, (op, thr, label) in GATE.items():
        v = metrics.get(key)
        ok = None if v is None else _cmp(v, op, thr)
        checks.append({"key": key, "label": label, "value": v, "op": op, "threshold": thr, "ok": ok})
        if ok is False:
            failures.append(key)
        if ok is None:
            nodata.append(key)
    incomplete = bool(nodata) or not complete or metrics.get("runs", 0) < MIN_RUNS
    verdict = "FAIL" if failures else ("INCOMPLETE" if incomplete else "PASS")
    return {"checks": checks, "failures": failures, "nodata": nodata, "incomplete": incomplete, "verdict": verdict,
            "exit": 1 if failures else (2 if incomplete else 0)}


# --------------------------------------------------------------------------------------------------------------------- chain selection
_CHAINS = {"default": (), "gemini": ("groq", "openrouter", "github"), "groq": ("gemini", "openrouter", "github"),
           "groq+openrouter": ("gemini", "github"), "gemini+openrouter": ("groq", "github")}
_KEY_ATTR = {"gemini": "gemini_api_key", "groq": "groq_api_key", "openrouter": "openrouter_api_key", "github": "github_token"}


def apply_chain(settings, chain: str) -> list[str]:
    """Blank the keys of the providers outside `chain` on a settings-like object. Returns the provider names left (settings.providers())."""
    if chain not in _CHAINS:
        raise ValueError(f"GC_CHAIN must be one of {', '.join(_CHAINS)}")
    for name in _CHAINS[chain]:
        try:
            setattr(settings, _KEY_ATTR[name], "")
        except Exception:
            object.__setattr__(settings, _KEY_ATTR[name], "")
    return [p["name"] for p in settings.providers()]


def select_items(items, only=None, limit=None):
    out, seen = [], {}
    for it in items:
        if only and it["group"] not in only:
            continue
        if limit and seen.get(it["group"], 0) >= limit:
            continue
        seen[it["group"]] = seen.get(it["group"], 0) + 1
        out.append(it)
    return out


def make_batches(items, size=BATCH_ITEMS):
    """Items that share (source, level) go to the same engine call; at most `size` items per batch. -> [(src, level, [items])]."""
    groups: dict = {}
    for it in items:
        groups.setdefault((it["src"], it["level"]), []).append(it)
    return [(k[0], k[1], g[i:i + size]) for k, g in sorted(groups.items()) for i in range(0, len(g), size)]


# ================================================================================================================== the owner-run part
class TimedLLM:
    """Wraps the real llm: records the wall time of every assess() call (the engine's model calls)."""

    def __init__(self, llm):
        self._llm = llm
        self.latencies: list[float] = []

    async def assess(self, *a, **kw):
        t0 = time.perf_counter()
        try:
            return await self._llm.assess(*a, **kw)
        finally:
            self.latencies.append(time.perf_counter() - t0)

    def __getattr__(self, name):
        return getattr(self._llm, name)


async def run_once(items, engine, budget_mod, llm, sleep_s: float, tag: str) -> dict:
    """One pass over the gold set: batches of <= 12 items per engine call, one turn per item. -> a `run` for compute_metrics."""
    timed = TimedLLM(llm)
    index = {it["id"]: n + 1 for n, it in enumerate(items)}           # turn id = position in the item list
    obs, calls, sentences, errors = {}, 0, 0, 0
    batches = make_batches(items)
    for bi, (src, level, batch) in enumerate(batches, 1):
        turns = [{"turn": index[it["id"]], "text": it["text"], "conf": None} for it in batch]
        try:
            res = await engine.analyze(timed, turns, level=level, feedback_lang="en", source=src, bud=budget_mod.Budget())
        except Exception as e:                                          # class name only
            errors += 1
            print(f"  {tag} batch {bi}/{len(batches)}: engine raised {type(e).__name__} (items {batch[0]['id']}..{batch[-1]['id']})")
            for it in batch:
                obs[it["id"]] = observe_item([{"status": "unchecked:error", "marks": []}])
            continue
        by_turn: dict = {}
        for row in res.get("sentences", []):
            by_turn.setdefault(row.get("turn"), []).append(row)
        for it in batch:
            obs[it["id"]] = observe_item(by_turn.get(index[it["id"]], []))
        calls += int((res.get("engine") or {}).get("calls", 0))
        sentences += len(res.get("sentences", []))
        print(f"  {tag} batch {bi}/{len(batches)} [{src}/{level}] items {batch[0]['id']}..{batch[-1]['id']} calls so far {calls}")
        if sleep_s and bi < len(batches):
            await asyncio.sleep(sleep_s)
    return {"obs": obs, "calls": calls, "sentences": sentences, "latencies": timed.latencies, "errors": errors}


def _fmt(v, pct=False):
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else (f"{v:.2f}" if isinstance(v, float) else str(v))


def print_report(m: dict, gate: dict, chain: str, providers: list[str]) -> None:
    print("\n" + "=" * 78)
    print(f"GRAMMAR COACH GOLD-SET EVALUATION   chain={chain} ({', '.join(providers)})   runs={m['runs']}")
    print("=" * 78)
    pct = {"fp_sure_neg_rate", "fp_any_neg_rate", "fp_sure_clean_rate", "recall_all", "recall_top15", "recall_all_sure_only", "rule_exact", "rule_family",
           "fix_match", "fix_match_end_to_end", "hindi_recall", "hindi_precision", "skip_reason_acc", "inject_clean", "stab_jaccard", "stab_jaccard_min",
           "stab_agree", "stab_agree_min", "unsure_rate"}
    for k in ("fp_sure_first150", "fp_sure_neg_rate", "fp_sure_clean_rate", "fp_any_neg_rate", "recall_top15", "recall_all", "recall_all_sure_only",
              "rule_exact", "rule_family", "fix_match", "fix_match_end_to_end", "hindi_recall", "hindi_precision", "skip_reason_acc", "marks_on_skipped",
              "inject_clean", "stab_jaccard", "stab_jaccard_min", "stab_agree", "stab_agree_min", "calls_per_100", "p95_latency", "unsure_rate"):
        print(f"  {k:<24} {_fmt(m.get(k), k in pct)}")
    weak = [(r, a, b) for r, (a, b) in m["per_rule_recall"].items() if b and a / b < 0.70]
    if weak:
        print("\n  rules under 70% recall (found/gold, item-runs): " + ", ".join(f"{r} {a}/{b}" for r, a, b in weak))
    if m["fp_items"]:
        print("\n  shown 'sure' false positives (item id: rule ids): " + "; ".join(f"{i}: {','.join(r)}" for i, r in list(m["fp_items"].items())[:40]))
    if m["inject_fail"]:
        print("\n  injection failures (item id: runs): " + ", ".join(f"{i}: {n}" for i, n in m["inject_fail"].items()))
    print("\nSHIP GATE")
    for ch in gate["checks"]:
        flag = "n/a " if ch["ok"] is None else ("PASS" if ch["ok"] else "FAIL")
        print(f"  {flag}  {ch['label']:<62} {_fmt(ch['value'], ch['key'] in pct):>8}  (need {ch['op']} {ch['threshold']})")
    print(f"\nVERDICT: {gate['verdict']}" + (f"  failures: {', '.join(gate['failures'])}" if gate["failures"] else "")
          + ("  (incomplete: subset run, fewer than 3 runs, or a metric without data)" if gate["verdict"] == "INCOMPLETE" else ""))


async def _amain(items, only, limit, runs_n, sleep_s, chain, basis, out_path) -> int:
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)                                         # config.py reads ".env" relative to the working directory
    from app.config import settings                           # lazy: the pure part of this file never needs the backend
    providers = apply_chain(settings, chain)
    if not providers:
        print("no provider key available for this chain (check backend/.env and GC_CHAIN)")
        return 2
    try:
        from app.grammar import budget as budget_mod, engine, catalog
        from app.providers import llm
    except Exception as e:                                    # e.g. detectors / lexicon not written yet
        print(f"cannot import the engine: {type(e).__name__}: {e}")
        return 2
    weights = {r.id: (r.weight, r.starred) for r in catalog.RULES.values() if r.severity == "error"}
    top = top_rules(weights, 15)
    print(f"chain={chain} providers={providers} items={len(items)} runs={runs_n} batches/run={len(make_batches(items))} top15={','.join(top)}")
    runs = []
    for r in range(runs_n):
        for hook in ("clear_cache", "cache_clear", "reset_cache"):     # a sentence-level cache would make run 2 / 3 replay run 1
            fn = getattr(engine, hook, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        runs.append(await run_once(items, engine, budget_mod, llm, sleep_s, f"run {r + 1}/{runs_n}"))
    m = compute_metrics(items, runs, top=top, basis=basis)
    complete = not only and not limit and all(r["errors"] == 0 for r in runs)
    gate = ship_gate(m, complete=complete)
    print_report(m, gate, chain, providers)
    if out_path:
        dump = {"chain": chain, "providers": providers, "metrics": {k: v for k, v in m.items() if k != "counts"}, "counts": m["counts"], "gate": gate,
                "runs": [{"calls": r["calls"], "sentences": r["sentences"], "errors": r["errors"],
                          "items": {i: {"status": o["status"], "marks": [{"rule": mk.get("rule"), "conf": mk.get("conf"), "severity": mk.get("severity"),
                                                                           "shown": mk.get("shown")} for mk in o["marks"]]} for i, o in r["obs"].items()}}
                         for r in runs]}
        Path(out_path).write_text(json.dumps(dump, indent=1), encoding="utf-8")
        print(f"dump written: {out_path}")
    return gate["exit"]


def main() -> int:
    if os.environ.get("GC_REAL") != "1":
        print("real_model.py spends REAL model calls (free-tier quota). Set GC_REAL=1 to run it; see the module docstring. Nothing was done.")
        return 2
    chain = os.environ.get("GC_CHAIN", "default")
    if chain not in _CHAINS:
        print(f"GC_CHAIN must be one of {', '.join(_CHAINS)}")
        return 2
    only = {g for g in os.environ.get("GC_ONLY", "").replace(" ", "").split(",") if g}
    try:
        limit = int(os.environ.get("GC_LIMIT", "0") or 0)
        runs_n = max(1, int(os.environ.get("GC_RUNS", str(MIN_RUNS))))
        sleep_s = float(os.environ.get("GC_SLEEP", "2"))
    except ValueError:
        print("GC_LIMIT / GC_RUNS / GC_SLEEP must be numbers")
        return 2
    basis = os.environ.get("GC_RECALL_BASIS", "any")
    if basis not in ("any", "sure"):
        print("GC_RECALL_BASIS must be any or sure")
        return 2
    items = select_items(load_gold(), only or None, limit or None)
    if not items:
        print("no gold items selected")
        return 2
    return asyncio.run(_amain(items, only, limit, runs_n, sleep_s, chain, basis, os.environ.get("GC_OUT", "")))


if __name__ == "__main__":
    sys.exit(main())
