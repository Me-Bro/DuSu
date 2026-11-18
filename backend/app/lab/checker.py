"""Grammar Lab - the checker (pure: no database, no network, no model).

`check(said, accepted)` compares what the learner wrote or said with the accepted English answers of an item and returns a verdict:

  ok      the answer is one of the accepted ones (up to what a speech recogniser may write differently: case, punctuation, contractions, numerals, fillers)
  wrong   there is POSITIVE evidence of a grammar error: a different tense form, a wrong helping verb (is/are, has/have ...), a wrong verb form (play / plays / playing / played),
          a missing or extra helping verb, a missing `not`, a question turned into a statement.  `codes` and `edits` say exactly which.
  unsure  the tense and the verb forms look right but the words differ from every accepted answer (a different noun, an extra article ...).  NEVER counted as a mistake: the
          learner is shown our answer and nothing is held against them (the precision-over-recall rule of Grammar Coach).
  empty   nothing was written.
  lang    the answer is in Devanagari (a Hindi answer to an English task).

The learner's sentence is diffed against the NEAREST accepted answer, token by token; each difference is classified (`_edit`).  The classification is rule-based and deterministic, so the
same answer always gets the same verdict, and it costs no AI call.
"""

from __future__ import annotations

import difflib

from ..grammar import lexicon as L
from ..grammar.text import clean_input
from ..grammar.verify import _charedit, _tokedit, is_artifact_only
from . import forms as F

MAX_SAID = 400
PREP = frozenset("in on at to for of with from by about into onto over under after before during since until till between among through".split())
KIND_ORDER = ("ing", "v3", "v2", "s", "base")

LEXICAL = frozenset({"word", "near", "missing_word", "extra_word", "missing_det", "extra_det", "missing_prep", "extra_prep"})
WRONG_PREFIX = ("aux_place:", "tense:", "be:", "have:", "do:", "will:", "aux:", "extra_aux:", "missing_aux:", "overreg:", "vf:")
WRONG_EXACT = frozenset({"missing_not", "extra_not", "polarity", "qform:q", "qform:s", "order_q"})
_RANK = {"tense": 0, "aux_place": 1, "be": 1, "have": 1, "do": 1, "will": 1, "aux": 1, "extra_aux": 2, "missing_aux": 2, "overreg": 3, "vf": 3, "qform": 4, "polarity": 4, "missing_not": 4, "extra_not": 4, "order_q": 5}


def _fam(x: str) -> str:
    if x in F.BE:
        return "be"
    if x in F.HAVE:
        return "have"
    if x in F.DO:
        return "do"
    if x in F.FUT:
        return "will"
    return ""


def _kind_of(tok: str, other: frozenset, prefer_other: bool) -> str:
    ks = F.kinds(tok)
    pool = (ks - other) if prefer_other and (ks - other) else ks
    for k in KIND_ORDER:
        if k in pool:
            return k
    return ""


def _prev(A: list[str], j: int) -> str:
    for x in reversed(A[:j]):
        if x in F.ADV:
            continue
        return x
    return ""


def _expected_kind(A: list[str], j: int, kt: frozenset) -> str:
    """The verb form the WORD IN FRONT asks for at target position j (am/is/are/was/were/been -> -ing, has/have/had -> V3, do/does/did/will/to -> V1), if the token can be it."""
    prev = _prev(A, j)
    want = ("ing" if (prev in F.BE) else "v3" if prev in F.HAVE else "base" if (prev in F.DO or prev in F.FUT or prev in F.MODALS or prev == "to") else "")
    return want if want and want in kt else ""


def _why_vf(A: list[str], j: int, tk: str, uk: str) -> str:
    """Which rule decided the verb form at target position j - read off the word in front of it."""
    prev = _prev(A, j)
    if tk == "ing":
        return "ing_after_been" if prev == "been" else ("ing_after_be" if prev in F.BE else "generic")
    if tk == "v3":
        return "v3_after_have" if prev in F.HAVE else "generic"
    if tk == "base":
        if prev in F.DO or prev in F.FUT or prev in F.MODALS or prev == "to":
            return "v1_after_aux"
        return "no_s_plural" if uk == "s" else "generic"
    if tk == "s":
        return "s_third"
    if tk == "v2":
        return "v2_past"
    return "generic"


def _edit(u: str | None, t: str | None, A: list[str], j: int) -> dict:
    """Classify ONE difference.  u = the learner's token (None: they left it out), t = the target's token (None: they added it)."""
    if u is not None and t is not None:
        fu, ft = _fam(u), _fam(t)
        if fu and ft:
            return {"code": f"{fu}:{u}>{t}" if fu == ft else f"aux:{u}>{t}", "said": u, "fix": t}
        if u in F.MODALS or t in F.MODALS:
            return {"code": f"aux:{u}>{t}", "said": u, "fix": t}
        lu, lt = F.lemma(u), F.lemma(t)
        ku, kt = F.kinds(u), F.kinds(t)
        if lt in L.IRREG and u in {L.past_regular(lt), lt + "ed", lt + "d"} and u != t:
            return {"code": f"overreg:{u}>{t}", "said": u, "fix": t}
        if lu == lt and (ku or kt) and ku != kt:
            uk, tk = _kind_of(u, kt, True), (_expected_kind(A, j, kt) or _kind_of(t, ku, True))
            if uk and tk and uk != tk:
                return {"code": f"vf:{uk}>{tk}", "said": u, "fix": t, "why": _why_vf(A, j, tk, uk)}
        if u != t and _charedit(u, t) <= 2 and len(t) >= 4:
            return {"code": "near", "said": u, "fix": t}
        return {"code": "word", "said": u, "fix": t}
    if u is not None:                                     # the learner added a word
        if u == "not":
            return {"code": "extra_not", "said": u, "fix": ""}
        if u in F.AUX:
            return {"code": f"extra_aux:{u}", "said": u, "fix": ""}
        if u in F.DETS:
            return {"code": "extra_det", "said": u, "fix": ""}
        if u in PREP:
            return {"code": "extra_prep", "said": u, "fix": ""}
        return {"code": "extra_word", "said": u, "fix": ""}
    t = t or ""
    if t == "not":
        return {"code": "missing_not", "said": "", "fix": t}
    if t in F.AUX:
        return {"code": f"missing_aux:{t}", "said": "", "fix": t}
    if t in F.DETS:
        return {"code": "missing_det", "said": "", "fix": t}
    if t in PREP:
        return {"code": "missing_prep", "said": "", "fix": t}
    return {"code": "missing_word", "said": "", "fix": t}


def _is_wrong(code: str) -> bool:
    return code in WRONG_EXACT or code.startswith(WRONG_PREFIX)


def _rank(code: str) -> int:
    return _RANK.get(code.split(":", 1)[0], 9)


def _compat(u: str, t: str) -> bool:
    """Two tokens that may be the same slot: equal, the same kind of helping verb, or two forms of the same verb."""
    if u == t:
        return True
    if _fam(u) and _fam(u) == _fam(t):
        return True
    return bool(F.kinds(u) and F.kinds(t) and F.lemma(u) == F.lemma(t))


def diff(S: list[str], A: list[str]) -> list[dict]:
    """The classified differences between the learner's tokens S and one accepted answer A (empty = the same words)."""
    sm = difflib.SequenceMatcher(None, S, A, autojunk=False)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace":
            i, j = i1, j1
            while i < i2 and j < j2:
                if _compat(S[i], A[j]):
                    e = _edit(S[i], A[j], A, j)
                    e["i"], e["j"] = i, j
                    i += 1
                    j += 1
                elif A[j] == "been" and "v3" in F.kinds(S[i]) and not (j + 1 < len(A) and "ing" in F.kinds(A[j + 1]) and F.lemma(A[j + 1]) == F.lemma(S[i])):
                    e = _edit(S[i], A[j], A, j)                           # `had never gone to Delhi` for `had never been to Delhi`: a different participle, not a missing `been`
                    e["code"], e["fix"] = "word", A[j]
                    e["i"], e["j"] = i, j
                    i += 1
                    j += 1
                elif A[j] in F.AUX or A[j] == "not":                  # the target has a helping verb / not the learner skipped
                    e = _edit(None, A[j], A, j)
                    e["i"], e["j"] = -1, j
                    j += 1
                elif S[i] in F.AUX or S[i] == "not":                  # the learner added one
                    e = _edit(S[i], None, A, j)
                    e["i"], e["j"] = i, -1
                    i += 1
                else:
                    e = _edit(S[i], A[j], A, j)
                    e["i"], e["j"] = i, j
                    i += 1
                    j += 1
                out.append(e)
            while i < i2:
                e = _edit(S[i], None, A, j)
                e["i"], e["j"] = i, -1
                out.append(e)
                i += 1
            while j < j2:
                e = _edit(None, A[j], A, j)
                e["i"], e["j"] = -1, j
                out.append(e)
                j += 1
        elif op == "delete":
            for k in range(i1, i2):
                e = _edit(S[k], None, A, j1)
                e["i"], e["j"] = k, -1
                out.append(e)
        else:
            for k in range(j1, j2):
                e = _edit(None, A[k], A, k)
                e["i"], e["j"] = -1, k
                out.append(e)
    return out


def _merge_misplaced(edits: list[dict]) -> list[dict]:
    """`will` missing in one place and extra in another is not two mistakes: the helping verb is THERE, in the wrong place (When Rohan's train will reach / When will Rohan's train reach)."""
    out = list(edits)
    for e in list(out):
        if e["code"].startswith("extra_aux:"):
            x = e["code"].split(":", 1)[1]
            mate = next((m for m in out if m["code"] == f"missing_aux:{x}"), None)
            if mate is not None:
                first = min(out.index(e), out.index(mate))
                out = [m for m in out if m is not e and m is not mate]
                out.insert(first, {"code": f"aux_place:{x}", "said": x, "fix": x, "i": e.get("i", -1), "j": mate.get("j", -1)})
    return out


def _family_of(form: str) -> str:
    return form.split("_", 1)[0]


def check(said, accepted: list[str], unit: str = "") -> dict:
    """The verdict for one answer.  `accepted` = the accepted English answers (already expanded with their harmless variants)."""
    t = clean_input(said, MAX_SAID)
    if not t:
        return {"verdict": "empty", "codes": [], "edits": []}
    if F.is_devanagari(t):
        return {"verdict": "lang", "codes": [], "edits": []}
    S = F.norm_tokens(t)
    if not S:
        return {"verdict": "empty", "codes": [], "edits": []}
    cand = [(a, F.norm_tokens(a)) for a in accepted]
    cand = [(a, A) for a, A in cand if A]
    if not cand:
        return {"verdict": "unsure", "codes": [], "edits": []}
    for a, A in cand:
        if S == A or is_artifact_only(S, A):
            return {"verdict": "ok", "target": a, "codes": [], "edits": []}
    # the accepted answer to compare with: the one whose WORDS the learner used (fewest different words), then the fewest edits - so a wrong verb form is read against the answer with
    # the same verb, not against a synonym answer that happens to be a token nearer
    scored = []
    for a, A in cand:
        e = diff(S, A)
        scored.append((sum(1 for x in e if x["code"] in LEXICAL), len(e), _tokedit(S, A), a, A, e))
    _, _, _, best_a, best, edits = min(scored, key=lambda c: c[:3])
    edits = _merge_misplaced(edits)
    codes = [e["code"] for e in edits]
    # ---- sentence-level evidence on top of the token edits
    q_t, q_s = F.question_in(best_a), F.question_in(t)
    if sorted(S) == sorted(best) and q_t and q_s:
        edits.insert(0, {"code": "order_q", "said": "", "fix": "", "i": -1, "j": -1})
        codes.insert(0, "order_q")
    elif q_t != q_s and not any(c in ("missing_aux:do", "missing_aux:does", "missing_aux:did") for c in codes):
        edits = [e for e in edits if not e["code"].startswith("aux_place:")]            # "this is a question" already says where the helping verb goes
        codes = [e["code"] for e in edits]
        edits.insert(0, {"code": "qform:q" if q_t else "qform:s", "said": "", "fix": "", "i": -1, "j": -1})
        codes.insert(0, "qform:q" if q_t else "qform:s")
    fs, ft = F.forms_of_tokens(S), F.forms_of_tokens(best)
    tense_code = ""
    if fs and ft and not (fs & ft):
        lf = sorted(fs - ft)[0] if (fs - ft) else sorted(fs)[0]
        tf = unit if unit in ft else sorted(ft)[0]
        structural = [c for c in codes if c.split(":", 1)[0] in ("be", "have", "do", "will", "aux", "extra_aux", "missing_aux")]
        if structural or _family_of(lf) != _family_of(tf):
            tense_code = f"tense:{lf}>{tf}"
            codes.insert(0, tense_code)
            edits.insert(0, {"code": tense_code, "said": "", "fix": "", "i": -1, "j": -1})
    verdict = "wrong" if any(_is_wrong(c) for c in codes) else "unsure"
    order = sorted(range(len(codes)), key=lambda k: (_rank(codes[k]) if _is_wrong(codes[k]) else 9, k))
    edits = [edits[k] for k in order]
    codes = [codes[k] for k in order]
    return {"verdict": verdict, "target": best_a, "codes": codes, "edits": edits,
            "forms": {"said": sorted(fs), "target": sorted(ft)}, "tense": tense_code}
