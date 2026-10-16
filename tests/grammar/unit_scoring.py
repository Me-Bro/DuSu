"""Unit tests for grammar/scoring.py: counts, evidence gate, tally, timeline, deltas, the rule status machine, top_focus.
Run: cd /home/vibhanshu/Desktop/DuSu && PYTHONPATH=backend python3 tests/grammar/unit_scoring.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _h import check, done, section  # noqa: E402

from app.grammar import scoring as S  # noqa: E402
from app.grammar.types import Mark  # noqa: E402


def mark(rule="ag.he_dont", conf="sure", sev="error", w=3, fam="ag"):
    return {"rule": rule, "severity": sev, "weight": w, "conf": conf, "family": fam}


def unit(turn, status, words=10, marks=(), opp=None):
    return {"turn": turn, "status": status, "words": words, "marks": list(marks), "opp": opp or {}}


# --------------------------------------------------------------------------------------------- the plan's worked data
section("worked data: 28 checked / 21 clean / 9 errors / 280 words")
units = []
for k in range(21):
    units.append(unit(k, "ok" if k % 3 else "natural", 10))
for k in range(7):                                   # 7 fix sentences carrying 9 sure error marks
    ms = [mark("ag.he_dont"), mark("ar.missing_a", w=2, fam="ar")] if k < 2 else [mark("ag.he_dont")]
    units.append(unit(21 + k, "fix", 10, ms))
units += [unit(30, "skip:not_english", 4)] * 3 + [unit(31, "skip:too_short", 1)] * 2 + [unit(32, "skip:unintelligible", 5)]
c = S.fold_units(units)
check("checked 28", c["checked"] == 28, c["checked"])
check("clean 21", c["clean"] == 21)
check("errors 9", c["errors"] == 9, c["errors"])
check("words_checked 280", c["words_checked"] == 280)
check("per100 3.2", c["per100"] == 3.2, c["per100"])
check("total 34", c["total"] == 34)
check("skipped by reason", c["skipped"] == {"not_english": 3, "too_short": 2, "unintelligible": 1}, c["skipped"])
check("enough", c["enough"] is True)
check("tally text exact", S.tally_text(c) == "Checked 28 of 34 sentences; 3 Hindi, 2 too short, 1 unclear", S.tally_text(c))
check("unit_counts is fold_units", S.unit_counts(units) == c)
check("rule_counts hits", c["rule_counts"]["ag.he_dont"]["hits"] == 7 and c["rule_counts"]["ar.missing_a"]["hits"] == 2, c["rule_counts"])
check("family_counts", c["family_counts"] == {"ag": 7, "ar": 2}, c["family_counts"])
check("display caps never reduce errors (all 9 counted)", c["errors"] == 9 and c["fix"] == 7)

section("what counts and what does not")
c = S.fold_units([unit(0, "fix", 10, [mark(conf="likely")]), unit(1, "ok", 10)])
check("likely mark in a fix unit is not an error", c["errors"] == 0)
c = S.fold_units([unit(0, "unsure", 10, [mark(conf="likely")]), unit(1, "ok", 10)])
check("unsure is not clean and not checked", c["checked"] == 1 and c["clean"] == 1 and c["unsure"] == 1, c)
check("unsure words are not in words_checked", c["words_checked"] == 10)
c = S.fold_units([unit(0, "unchecked:cap", 10), unit(1, "unchecked:ai_down", 10), unit(2, "unchecked:budget", 10), unit(3, "ok", 10)])
check("unchecked never counted as clean", c["clean"] == 1 and c["checked"] == 1, c)
check("unchecked by reason", c["unchecked"] == {"cap": 1, "ai_down": 1, "budget": 1} and c["unchecked_total"] == 3)
c = S.fold_units([unit(0, "natural", 10, [mark("ind.lexicon#prepone", sev="natural", w=1, fam="ind")]), unit(1, "ok", 10)])
check("natural tip is clean but not an error", c["errors"] == 0 and c["clean"] == 2 and c["tips"] == 1, c)
check("natural tip tracked per rule entry", c["rule_counts"]["ind.lexicon#prepone"]["hits"] == 1)
c = S.fold_units([{"status": "skip", "reason": "too_short", "words": 1}, {"status": "unchecked", "reason": "cap", "words": 3}])
check("separate reason key works", c["skipped"] == {"too_short": 1} and c["unchecked"] == {"cap": 1})
check("Mark objects accepted", S.fold_units([unit(0, "fix", 5, [Mark("ag.he_dont", 0, 1, 0, 2, "he", "she", conf="sure", severity="error", weight=3, family="ag")])])["errors"] == 1)
check("empty input", S.fold_units([])["per100"] is None and S.fold_units([])["timeline"] == "")
check("opportunities summed", S.fold_units([unit(0, "ok", 5, opp={"ag.s_missing_3p": 2}), unit(1, "fix", 5, [mark("ag.s_missing_3p")], opp={"ag.s_missing_3p": 1})])["rule_counts"]["ag.s_missing_3p"] == {"hits": 1, "opp": 3})
check("marks in skipped units ignored", S.fold_units([unit(0, "skip:not_english", 5, [mark()])])["errors"] == 0)

section("minimum evidence")
check("5 checked, 100 words -> withheld", not S.enough({"checked": 5, "words_checked": 100}))
check("6 checked, 39 words -> withheld", not S.enough({"checked": 6, "words_checked": 39}))
check("6 checked, 40 words -> enough", S.enough({"checked": 6, "words_checked": 40}))
check("fold marks enough False when thin", S.fold_units([unit(0, "ok", 10)])["enough"] is False)

section("tally text")
check("no extras", S.tally_text(S.fold_units([unit(0, "ok", 5)])) == "Checked 1 of 1 sentences")
t = S.tally_text(S.fold_units([unit(0, "ok", 5), unit(1, "unsure", 5), unit(2, "unchecked:cap", 5), unit(3, "skip:not_a_sentence", 2)]))
check("tally with unsure / unchecked / not a sentence", t == "Checked 1 of 4 sentences; 1 not a sentence, 1 not sure, 1 not checked (over the limit)", t)
check("empty tally", S.tally_text(S.fold_units([])) == "No sentences yet")

section("timeline and best run")
us = [unit(0, "ok"), unit(1, "natural"), unit(2, "fix", marks=[mark()]), unit(3, "unsure"), unit(4, "skip:too_short"), unit(5, "unchecked:cap"), unit(6, "ok")]
c = S.fold_units(us)
check("timeline chars", c["timeline"] == "onx~-?o", c["timeline"])
c = S.fold_units([unit(i, "ok") for i in range(4)] + [unit(4, "fix", marks=[mark()])] + [unit(i, "ok") for i in range(5, 14)])
check("best_run 9 after a fix", c["best_run"] == 9, c["best_run"])
c = S.fold_units([unit(0, "ok"), unit(1, "skip:not_english"), unit(2, "ok"), unit(3, "ok")])
check("a skipped sentence does not break a run", c["best_run"] == 3, c["best_run"])
c = S.fold_units([unit(0, "ok"), unit(1, "unchecked:cap"), unit(2, "ok")])
check("an unchecked sentence breaks a run", c["best_run"] == 1)
c = S.fold_units([unit(0, "ok"), unit(1, "unsure"), unit(2, "ok")])
check("an unsure sentence breaks a run", c["best_run"] == 1)
check("no clean -> 0", S.fold_units([unit(0, "fix", marks=[mark()])])["best_run"] == 0)

section("noise band numbers (plan: 12 / 9 / 6)")
check("28 / 28 -> 12", S.noise_clean_share(28, 28) == 12, S.noise_clean_share(28, 28))
check("50 / 50 -> 9", S.noise_clean_share(50, 50) == 9)
check("100 / 100 -> 6", S.noise_clean_share(100, 100) == 6)
check("floor 5", S.noise_clean_share(10000, 10000) == 5)
check("zero n -> 100", S.noise_clean_share(0, 50) == 100)


def win(checked, clean, errors, words, source="whisper", rv=1, level="B1"):
    c = {"checked": checked, "clean": clean, "errors": errors, "words_checked": words, "source": source, "rules_version": rv, "level": level}
    c["per100"] = round(100.0 * errors / words, 1)
    return c


section("delta gating")
a, b = win(60, 40, 40, 800), win(60, 50, 20, 800)
d = S.delta(a, b)
check("clear improvement -> better", d is not None and d["direction"] == "better", d)
check("worse direction", S.delta(b, a)["direction"] == "worse")
check("<40 checked in a window -> None", S.delta(win(39, 20, 20, 400), b) is None)
check("<40 checked in the other window -> None", S.delta(a, win(39, 30, 10, 400)) is None)
check("cross-source -> None", S.delta(a, win(60, 50, 20, 800, source="chrome")) is None)
check("different rules_version -> None", S.delta(a, win(60, 50, 20, 800, rv=2)) is None)
check("different level band -> None", S.delta(a, win(60, 50, 20, 800, level="A2")) is None)
check("same band via norm (A0 vs beginner)", S.delta(win(60, 40, 40, 800, level="A0"), win(60, 50, 20, 800, level="beginner")) is not None)
check("missing source -> None", S.delta({k: v for k, v in a.items() if k != "source"}, b) is None)
check("inside the noise band -> None", S.delta(win(50, 40, 20, 800), win(50, 42, 19, 800)) is None)
# share up 8 pts (n=50: noise 9) and per100 only 5% down -> nothing beyond noise
check("8 points at n=50 is noise", S.delta(win(50, 40, 20, 800), win(50, 44, 19, 800)) is None)
# share barely moves but per100 falls by half: relative rule
d = S.delta(win(60, 50, 20, 400), win(60, 51, 10, 400))
check("30% relative drop on per100 fires", d is not None and "per100" in d["basis"] and d["direction"] == "better", d)
check("29% relative drop and tiny share change -> None", S.delta(win(60, 50, 100, 1000), win(60, 50, 71, 1000)) is None)
d = S.delta(win(60, 50, 0, 800), win(60, 40, 10, 800))
check("zero baseline errors, share drop beyond noise -> worse", d is not None and d["direction"] == "worse", d)
check("contradicting measures -> None", S.delta(win(60, 40, 20, 400), win(60, 50, 40, 400)) is None)
check("None windows", S.delta(None, a) is None and S.delta(a, None) is None)


# --------------------------------------------------------------------------------------------- the status machine
def sess(i, words=200, **rules):
    return {"ts": i, "words_checked": words, "rules": {k: {"hits": v[0], "opp": v[1] if len(v) > 1 else 0} for k, v in rules.items()}}


R = "ag.s_missing_3p"
section("rule_states")
check("empty history", S.rule_states([]) == {})
st = S.rule_states([sess(1, **{R: (1,)})])
check("one hit -> new", st[R]["state"] == "new" and st[R]["hits"] == 1 and st[R]["regressed"] is False, st)
st = S.rule_states([sess(1, **{R: (2,)})])
check("two hits in one session -> new", st[R]["state"] == "new")
st = S.rule_states([sess(1, **{R: (1,)}), sess(2, **{R: (1,)})])
check("hits in two of last 5 sessions -> needs_work", st[R]["state"] == "needs_work", st)
st = S.rule_states([sess(1, **{R: (3,)}), sess(2), sess(3)])
check("3 hits in the last 3 sessions -> needs_work", S.rule_states([sess(1), sess(2, **{R: (1,)}), sess(3, **{R: (2,)})])[R]["state"] == "needs_work")
st = S.rule_states([sess(1, **{R: (3,)}), sess(2, 50), sess(3, 50)])
check("3 hits in one session then quiet short sessions: not fixed", st[R]["state"] != "fixed", st)
check("hits older than 5 sessions, not enough speaking since -> unknown", S.rule_states([sess(1, **{R: (2,)}), sess(2, **{R: (2,)})] + [sess(i, 20) for i in range(3, 9)])[R]["state"] in ("unknown", "fixed") and
      S.rule_states([sess(1, **{R: (2,)}), sess(2, **{R: (2,)})] + [sess(i, 20) for i in range(3, 9)])[R]["state"] == "unknown")
check("no hits at all -> unknown", S.rule_states([sess(1, **{R: (0, 4)}), sess(2, **{R: (0, 3)})])[R]["state"] == "unknown")

# silence alone never produces fixed
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)})] + [sess(i, 0) for i in range(4, 40)]
check("silence (0 checked words) never produces fixed", S.rule_states(hist)[R]["state"] != "fixed", S.rule_states(hist))
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)})] + [sess(4, 100), sess(5, 100)]
check("2 sessions but only 200 words -> not fixed", S.rule_states(hist)[R]["state"] != "fixed")
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)})] + [sess(4, 200)]
check("300+ words but one session -> not fixed", S.rule_states(hist)[R]["state"] != "fixed")

# no-opportunity rule: needs 500 words
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)}), sess(4, 150), sess(5, 150)]
check("no opportunities: 300 words is not enough", S.rule_states(hist)[R]["state"] != "fixed", S.rule_states(hist))
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)}), sess(4, 250), sess(5, 250)]
check("no opportunities: 500 words over 2 sessions -> fixed", S.rule_states(hist)[R] == {"state": "fixed", "hits": 5, "regressed": False}, S.rule_states(hist))

# rule with opportunities: 300 words AND >= 5 correct uses
base = [sess(1, **{R: (2, 1)}), sess(2, **{R: (2, 1)}), sess(3, **{R: (1, 1)})]
hist = base + [sess(4, 160, **{R: (0, 2)}), sess(5, 160, **{R: (0, 2)})]
check("opportunities: 320 words but only 4 correct uses -> not fixed", S.rule_states(hist)[R]["state"] != "fixed", S.rule_states(hist))
hist = base + [sess(4, 160, **{R: (0, 3)}), sess(5, 160, **{R: (0, 2)})]
check("opportunities: 320 words + 5 correct uses -> fixed", S.rule_states(hist)[R]["state"] == "fixed", S.rule_states(hist))
hist = base + [sess(4, 140, **{R: (0, 3)}), sess(5, 140, **{R: (0, 3)})]
check("opportunities: 5+ correct uses but 280 words -> not fixed", S.rule_states(hist)[R]["state"] != "fixed")
check("fixed needs >= 3 hits historically", S.rule_states([sess(1, **{R: (1,)}), sess(2, **{R: (1,)}), sess(3, 400), sess(4, 400)])[R]["state"] != "fixed")

# regression
hist = [sess(1, **{R: (2,)}), sess(2, **{R: (2,)}), sess(3, **{R: (1,)}), sess(4, 250), sess(5, 250), sess(6, **{R: (1,)})]
st = S.rule_states(hist)[R]
check("a new hit after fixed -> needs_work with regressed", st["state"] == "needs_work" and st["regressed"] is True, st)
hist2 = hist + [sess(7, 0), sess(8, 0)]
check("regression sticks through silence", S.rule_states(hist2)[R]["regressed"] is True and S.rule_states(hist2)[R]["state"] == "needs_work")
hist3 = hist + [sess(7, 250), sess(8, 250)]
st = S.rule_states(hist3)[R]
check("fixed again after enough new clean speech", st["state"] == "fixed" and st["regressed"] is False, st)
check("never-fixed rule is not flagged regressed", S.rule_states([sess(1, **{R: (1,)}), sess(2, **{R: (1,)}), sess(3, **{R: (1,)})])[R]["regressed"] is False)

# improving
prev = [sess(1, 200, **{R: (1,)}), sess(2, 200, **{R: (1,)}), sess(3, 200, **{R: (2,)})]
cur = [sess(4, 200), sess(5, 200, **{R: (1,)}), sess(6, 200)]
st = S.rule_states(prev + cur)[R]
check("improving: 4 -> 1 hits over 600 words each", st["state"] == "improving", st)
cur_bad = [sess(4, 200, **{R: (1,)}), sess(5, 200, **{R: (1,)}), sess(6, 200, **{R: (1,)})]
check("not improving when the rate is unchanged", S.rule_states(prev + cur_bad)[R]["state"] != "improving")
cur_short = [sess(4, 40), sess(5, 40, **{R: (1,)}), sess(6, 40)]
check("improving needs >= 150 words in each window", S.rule_states(prev + cur_short)[R]["state"] != "improving")
prev_few = [sess(1, 200, **{R: (1,)}), sess(2, 200, **{R: (1,)}), sess(3, 200)]
check("improving needs previous hits >= 3", S.rule_states(prev_few + cur)[R]["state"] != "improving")
cur_zero = [sess(4, 200), sess(5, 200), sess(6, 200)]
check("improving needs current hits >= 1 (zero is not 'improving')", S.rule_states(prev + cur_zero)[R]["state"] != "improving")
st = S.rule_states(prev + [sess(4, 200, **{R: (3,)}), sess(5, 200), sess(6, 200)])[R]
check("rate halved but not by 0.5 per 100 words is not improving: 4 hits/600 vs 3 hits/600", st["state"] != "improving")

section("rule_states misc")
st = S.rule_states([sess(1, **{"ind.lexicon#prepone": (1,)}), sess(2, **{"ind.lexicon#prepone": (1,)}), sess(3, **{"ind.lexicon#prepone": (1,)})])
check("entry keys tracked", st["ind.lexicon#prepone"]["state"] == "needs_work")
check("now filters future sessions", S.rule_states([sess(1, **{R: (1,)}), sess(99, **{R: (1,)})], now=5)[R]["state"] == "new")
check("two rules independent", set(S.rule_states([sess(1, **{R: (1,), "tn.did_past": (1,)})])) == {R, "tn.did_past"})
big = [sess(i, 100, **{R: (i % 2,)}) for i in range(500)]
import time  # noqa: E402
t0 = time.perf_counter()
S.rule_states(big)
check("history is capped (500 sessions fast)", time.perf_counter() - t0 < 1.0, time.perf_counter() - t0)

section("top_focus")
rc = {"ag.he_dont": {"hits": 4, "opp": 2}, "ar.missing_a": {"hits": 6, "opp": 1}, "ar.a_an": {"hits": 3, "opp": 0}, "tn.did_past": {"hits": 1, "opp": 0},
      "ind.lexicon#prepone": {"hits": 9, "opp": 0}}
f = S.top_focus(rc, 5)
check("a rule is a pattern only from 2 hits", "tn.did_past" not in [x["rule"] for x in f])
check("natural tips never focus items", "ind.lexicon#prepone" not in [x["rule"] for x in f])
check("ranked by hits x weight: he_dont (4x3=12) > missing_a (6x2=12, tie -> more hits first)", [x["rule"] for x in f][:3] == ["ar.missing_a", "ag.he_dont", "ar.a_an"], [x["rule"] for x in f])
many = {r: {"hits": 4, "opp": 0} for r in ("ag.he_dont", "ag.aux_form", "tn.did_past", "ag.s_missing_3p", "tn.since_for", "ar.missing_a", "pr.time_in_on_at")}
check("limit respected", len(S.top_focus(many, 3)) == 3 and len(S.top_focus(many, 5)) == 5)
check("limit defaults by level: A2 -> 3", len(S.top_focus(many, level="A2")) == 3)
check("limit defaults by level: B1 -> 5", len(S.top_focus(many, level="B1")) == 5)
check("focus_limit table", S.focus_limit("A0") == 3 and S.focus_limit("A2") == 3 and S.focus_limit("B1") == 5 and S.focus_limit("C1") == 5)
states = {"ag.he_dont": {"state": "needs_work", "hits": 3, "regressed": False}, "ar.missing_a": {"state": "improving", "hits": 3, "regressed": False}}
f = S.top_focus(states, 5)
check("needs_work gets x1.2", f[0]["rule"] == "ag.he_dont" and f[0]["score"] == round(3 * 3 * 1.2, 3), f)
check("states input: weight from the catalogue", f[1]["score"] == 6.0)
states["tn.did_past"] = {"state": "fixed", "hits": 9, "regressed": False}
check("fixed rules are not focus", "tn.did_past" not in [x["rule"] for x in S.top_focus(states, 5)])
check("unknown rule id gets weight 1", S.top_focus({"other": {"hits": 3, "opp": 0}}, 3)[0]["weight"] == 1)
check("empty / None", S.top_focus({}, 3) == [] and S.top_focus(None, 3) == [])

raise SystemExit(done("unit_scoring"))
