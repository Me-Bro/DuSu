"""The Grammar Coach engine: ONE async AI stage around pure modules (plan section 7 and Appendix A).

    turns -> segment -> sentence gate -> rule checks -> [AI call per <= 12 sentences, ladder full -> compact -> rule checks]
          -> verify (the corrected sentence is BUILT BY CODE) -> status -> fold (counts, per-100, rule counts) -> flow

`llm` is injected (as practice.analyze does) so every test passes a stub. Nothing here touches the database, logs learner text, or raises into
the caller for a model problem: a failing model only lowers coverage ("checked 12 of 30"), never produces a wrong mark.
"""

from __future__ import annotations

import asyncio

from . import RULES_VERSION, budget as B, catalog, detectors, flow as flowmod, gating, prompts, scoring, segment, verify
from .text import canon_contractions, keys as tkeys, tokenize


class QuotaStop(Exception):
    """The caller's quota hook refused: the AI part stops, the rule-check floor still runs."""


def _norm_verdict(v) -> str:
    v = str(v or "").strip().lower()
    return v if v in ("ok", "fix", "natural", "skip") else ""


def _parse(res, n: int):
    """-> {index: (verdict, kind, [raw marks])} or None when the reply is not usable at all."""
    if not isinstance(res, dict) or res.get("error"):
        return None
    s = res.get("s")
    if not isinstance(s, list):
        return None
    out: dict = {}
    for it in s[: n + 5]:
        if not isinstance(it, dict):
            continue
        i = it.get("i")
        if not isinstance(i, int) or isinstance(i, bool) or not (0 <= i < n):
            continue
        m = it.get("m")
        out[i] = (_norm_verdict(it.get("v")), str(it.get("k") or "")[:20], [x for x in (m if isinstance(m, list) else []) if isinstance(x, dict)][:8])
    return out


async def _ask(llm, system: str, user: str, bud: B.Budget, first: str | None, charge):
    """One model call under the process-wide guard. Returns the parsed dict or None; a RAISE opens the breaker and is never retried."""
    if not bud.can_call():
        return None
    if charge is not None and not bud.charged:
        try:
            await charge()
        except Exception:
            bud.trip("quota")
            return None
        bud.charged = True
    bud.calls += 1
    try:
        async with B.semaphore():
            return await asyncio.wait_for(llm.assess(system, user, max_tokens=B.MAX_TOKENS, temperature=0.1, prefer_fast=False, first=first, cool=False),
                                          B.CALL_TIMEOUT_S)
    except Exception as e:                               # class name only: provider errors can echo the request body (a learner's words)
        bud.trip("quota" if _quotaish(e) else "error")
        bud.log.append(type(e).__name__)
        return None


def _quotaish(e) -> bool:
    s = str(e).lower()
    return any(k in s for k in ("429", "quota", "rate", "exhaust", "unavailable", "402"))


def _mark_dict(m, shown: bool = True) -> dict:
    return {"rule": m.rule, "title": catalog.title_of(m.rule, "en"), "i": m.i, "j": m.j, "start": m.start, "end": m.end, "quote": m.quote,
            "fix": m.fix, "conf": m.conf, "severity": m.severity, "weight": m.weight, "family": m.family, "why": m.why, "src": m.src,
            "det": m.det, "shown": shown}


def _rule_inputs(text: str, source: str):
    """(token keys after contraction canonicalisation, opaque indexes, hits, vetoes) for one sentence."""
    toks = tokenize(text)
    ks = canon_contractions([t.key for t in toks])
    opaque = gating.opaque_indices(toks, cased=(source != "chrome"))
    hits = detectors.run_all(ks, source=source, has_q=("?" in text), opaque=opaque)
    return ks, opaque, hits, detectors.vetoes(ks)


def _recheck(source: str):
    def f(t):
        return detectors.solo_hits(canon_contractions(tkeys(t)), source=source, has_q=("?" in t))
    return f


async def analyze(llm, turns: list[dict], *, level="B1", feedback_lang="hinglish", source="chrome", name="", bud: B.Budget | None = None, charge=None,
                  prev_lines: dict | None = None, contested=frozenset(), duration_sec=None, first: str | None = None) -> dict:
    """`turns`: [{"turn": int, "text": str, "conf": float | None, "hints": Hints | None}] in order. `prev_lines`: {turn: DuSu's previous line}."""
    bud = bud or B.Budget()
    prev_lines = prev_lines or {}
    level = str(level or "B1")
    sents: list = []
    for t in turns:
        sents.extend(segment.segment(t.get("text", ""), turn=int(t.get("turn", 0)), source=source, conf=t.get("conf"), hints=t.get("hints")))
    rows = [{"s": s, "status": "", "marks": [], "fixed": "", "opp": {}} for s in sents]

    # --- sentence gate, then the session cap
    cand: list = []
    for r in rows:
        g = gating.sentence_gate(r["s"], name=name)
        if not g.ok:
            r["status"] = "skip:" + g.reason
        elif len(cand) >= bud.session_sents:
            r["status"] = "unchecked:cap"
        else:
            cand.append(r)
    mix = gating.lang_mix([gating.sentence_gate(r["s"], name=name) for r in rows[:6]]) if rows else False
    if mix:
        for r in cand:
            r["status"] = "unchecked:lang_mix"
        cand = []

    # --- rule checks (always run: the offline floor and the agreement signal)
    for r in cand:
        r["ks"], r["opaque"], r["hits"], r["vet"] = _rule_inputs(r["s"].text, source)

    # --- the AI stage, batch by batch
    verdicts: dict = {}                                    # id(row) -> (verdict, kind, raw marks)
    for b0 in range(0, len(cand), B.BATCH_SENTS):
        batch = cand[b0:b0 + B.BATCH_SENTS]
        if not bud.can_call():
            break
        texts = [r["s"].text for r in batch]
        prev = prev_lines.get(batch[0]["s"].turn, "")
        got = _parse(await _ask(llm, prompts.system(level, feedback_lang), prompts.user(texts, prev), bud, first, charge), len(batch))
        if got is not None and len(got) < 0.8 * len(batch):        # rung 2: re-ask ONLY the missing items, compact
            miss = [i for i in range(len(batch)) if i not in got]
            got2 = _parse(await _ask(llm, prompts.system(level, feedback_lang, compact=True), prompts.user([texts[i] for i in miss], prev), bud, first, charge), len(miss))
            for k, i in enumerate(miss):
                if got2 and k in got2:
                    got[i] = got2[k]
        elif got is None and not bud.breaker:                      # unusable reply but the chain is alive: one compact try for the whole batch
            got = _parse(await _ask(llm, prompts.system(level, feedback_lang, compact=True), prompts.user(texts, prev), bud, first, charge), len(batch))
        for i, r in enumerate(batch):
            if got and i in got and got[i][0]:
                verdicts[id(r)] = got[i]

    # --- verify, build the corrected sentence, decide the status
    quick = dropped = 0
    for r in cand:
        s, text = r["s"], r["s"].text
        v = verdicts.get(id(r))
        if v is None:                                                   # rung 3: rule checks only
            marks = verify.marks_from_hits(text, [h for h in r["hits"] if h.solo], level=level, source=source, opaque=r["opaque"], vetoes=r["vet"])
            quick += 1 if marks else 0
            r["status"] = "fix" if any(m.conf == "sure" and m.severity == "error" for m in marks) else "unchecked:ai_down"
            r["marks"] = marks
        else:
            verdict, kind, raw = v
            if verdict == "skip":
                r["status"] = "skip:" + ("not_english" if kind == "not_english" else "unintelligible")
                continue
            marks = verify.verify_marks(text, raw, level=level, source=source, conf=s.conf, hits=r["hits"], vetoes=r["vet"], opaque=r["opaque"], contested=contested)
            dropped += max(0, len(raw) - len(marks))
            covered = [(m.i, m.j) for m in marks]
            extra = [m for m in verify.marks_from_hits(text, [h for h in r["hits"] if h.solo], level=level, source=source, opaque=r["opaque"], vetoes=r["vet"])
                     if not any(not (m.j <= a or m.i >= b) for a, b in covered)]
            marks = list(marks) + extra
            r["marks"] = marks
            r["status"] = verify.status_of(marks, verdict)
        r["fixed"] = verify.build_corrected(text, r["marks"], recheck=_recheck(source)) or ""
        r["opp"] = {rid: n for rid in _OPP_RULES if (n := detectors.opportunities(rid, r["ks"]))}

    # --- display caps (display ONLY: counting uses every verified mark)
    by_turn: dict = {}
    for r in cand:
        by_turn.setdefault(r["s"].turn, []).append(r)
    for rs in by_turn.values():
        for r in rs:
            for m in r["marks"]:
                m._shown = True                                       # type: ignore[attr-defined]
        shown = verify.display_cap([m for r in rs for m in r["marks"]], level, per="turn")
        ids = {id(m) for m in shown}
        for r in rs:
            capped = {id(m) for m in verify.display_cap(r["marks"], level, per="sentence")}
            for m in r["marks"]:
                m._shown = id(m) in ids and id(m) in capped            # type: ignore[attr-defined]

    # --- fold + flow
    units = [{"turn": r["s"].turn, "status": r["status"], "words": r["s"].n_words,
              "marks": [{"rule": m.rule, "severity": m.severity, "weight": m.weight, "conf": m.conf} for m in r["marks"]], "opp": r["opp"]} for r in rows]
    counts = scoring.fold_units(units)
    checked_sents = [r["s"] for r in rows if r["status"] in ("ok", "natural", "fix", "unsure")]
    fl = flowmod.flow_metrics(checked_sents, source=source, text=" ".join(t.get("text", "") for t in turns), duration_sec=duration_sec)
    out_rows = []
    for pos, r in enumerate(rows):
        out_rows.append({"pos": pos, "turn": r["s"].turn, "text": r["s"].text, "status": r["status"], "words": r["s"].n_words, "fixed": r["fixed"],
                         "marks": [_mark_dict(m, getattr(m, "_shown", True)) for m in r["marks"]]})
    return {"rules_version": RULES_VERSION, "level": level, "source": source, "sentences": out_rows, "counts": counts, "flow": fl, "units": units,
            "engine": {"source": source, "calls": bud.calls, "dropped": dropped, "quick": quick, "degraded": bool(bud.breaker and bud.reason != "cap" or quick and not verdicts),
                       "breaker": bud.reason, "tally": scoring.tally_text(counts), "lang_mix": mix}}


_OPP_RULES = tuple(r.id for r in catalog.RULES.values() if any(d.startswith("D") for d in r.dets))
