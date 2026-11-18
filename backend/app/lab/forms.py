"""Grammar Lab - the twelve tense forms and the token helpers around them (pure: no database, no network, no clock).

Present / Past / Future x Simple / Continuous / Perfect / Perfect Continuous.  `forms_of(text)` answers "which of the twelve forms does this English sentence use?" by reading the
auxiliary chain of each clause.  It is used in three places: the bank lint (every accepted answer must belong to its unit), the checker (the learner's form against the target's) and
the explanations.  It is deliberately a *rule* reader, not a model: it says what the words ARE, and returns an EMPTY set when it cannot tell - the checker never marks an answer wrong on
the strength of an empty set.

Everything is bounded: callers slice their input first (`text.clean_input`) and every loop here is over a token list of at most MAX_TOKENS.
"""

from __future__ import annotations

import re

from ..grammar import lexicon as L
from ..grammar.text import canon_contractions, clean_input, tokenize

MAX_TOKENS = 60

FAMILIES = ("present", "past", "future")
TYPES = ("simple", "continuous", "perfect", "perfect_continuous")
UNITS = tuple(f"{f}_{t}" for f in FAMILIES for t in TYPES)

BE = frozenset("am is are was were be been being".split())
BE_PRES = frozenset(("am", "is", "are"))
BE_PAST = frozenset(("was", "were"))
HAVE = frozenset(("have", "has", "had"))
DO = frozenset(("do", "does", "did"))
FUT = frozenset(("will", "shall"))
MODALS = frozenset("can could would should may might must".split())
AUX = BE | HAVE | DO | FUT | MODALS
SUBORD = frozenset("when while before after because if that which who whom whose where until unless although though since as and but so then whenever once".split())
ADV = frozenset("""not never always already just still also often usually ever soon probably definitely really only even yet now then sometimes rarely seldom hardly almost surely
certainly finally recently currently quickly slowly again too nearly maybe perhaps""".split())
DETS = frozenset("a an the my your his her its our their this that these those some any no another every each".split())
SUBJ_PRON = frozenset("i you he she it we they".split())
FILLERS = frozenset("um umm uh uhh er erm err hmm hm ah mm mhm".split())
# words ending in -ed / -ing that are not verb forms (the suffix fallback must not read them as participles)
_ED_BLOCK = frozenset("need feed speed breed proceed succeed exceed bleed indeed hundred sacred naked wicked kindred seed weed bed red shed sled led wed fled".split())
_ING_BLOCK = frozenset("morning evening king thing something anything everything nothing spring ring string wing sing bring swing sting cling fling wedding ceiling building".split())
# a few -ing words that really are used as verbs here although the verb list has them only as bases
_NEG = {"don't": "do", "doesn't": "does", "didn't": "did", "isn't": "is", "aren't": "are", "wasn't": "was", "weren't": "were", "haven't": "have", "hasn't": "has", "hadn't": "had",
        "shouldn't": "should", "couldn't": "could", "wouldn't": "would", "mustn't": "must", "needn't": "need", "mightn't": "might"}
_PRON_S = frozenset("he she it that there here what who where how when why".split())
_V3_ONLY_HINT = frozenset(("been", "gone", "done", "seen", "taken", "given", "made", "got", "gotten", "eaten", "written", "known", "come", "become", "begun", "broken", "chosen", "driven"))
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_SPLIT = re.compile(r"[,;:.!?()\"]+")


# --------------------------------------------------------------------------------------------- verb-form kinds
def kinds(tok: str) -> frozenset:
    """Which verb forms a token can be: a subset of {"base", "s", "ing", "v2", "v3"}.  Empty = not recognised as a verb form."""
    if not tok or tok in AUX:
        return frozenset()
    b = L.base_of(tok)
    out = set()
    if b:
        if tok == b:
            out.add("base")
        if tok == L.third_s(b):
            out.add("s")
        if tok in L.ing_forms(b):
            out.add("ing")
        if b in L.IRREG:
            if tok == L.IRREG[b][0]:
                out.add("v2")
            if tok == L.IRREG[b][1] or tok == L.EXTRA_V3.get(b):
                out.add("v3")
        elif tok in L.past_forms(b):
            out.update(("v2", "v3"))
        if not out and tok in (L.v3_of(b), L.v2_of(b)):
            out.update(("v2", "v3"))
        return frozenset(out)
    if tok.endswith("ing") and len(tok) > 4 and tok not in _ING_BLOCK:
        return frozenset({"ing"})
    if tok.endswith("ed") and len(tok) > 4 and tok not in _ED_BLOCK:
        return frozenset({"v2", "v3"})
    return frozenset()


def lemma(tok: str) -> str:
    """The base verb of a verb form, or the token itself (a crude plural strip is NOT done: a content word is compared as written)."""
    if tok in AUX:
        return tok
    return L.base_of(tok) or tok


def is_devanagari(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if _DEVANAGARI.match(c)) * 2 > len(letters)


# --------------------------------------------------------------------------------------------- normalising a sentence into comparable tokens
def expand(ks: list[str]) -> list[str]:
    """`doesn't` -> does not, `I'm` -> i am, `he's gone` -> he has gone, `he's playing` -> he is playing, `we'll` -> we will ... (keys are already lower-case)."""
    out: list[str] = []
    for i, k in enumerate(ks):
        if k in _NEG:
            out += [_NEG[k], "not"]
        elif k == "can't" or k == "cannot":
            out += ["can", "not"]
        elif k == "won't":
            out += ["will", "not"]
        elif k == "shan't":
            out += ["shall", "not"]
        elif k.endswith("'ll") and len(k) > 3:
            out += [k[:-3], "will"]
        elif k.endswith("'ve") and len(k) > 3:
            out += [k[:-3], "have"]
        elif k.endswith("'re") and len(k) > 3:
            out += [k[:-3], "are"]
        elif k.endswith("'m") and len(k) > 2:
            out += [k[:-2], "am"]
        elif k.endswith("'d") and len(k) > 2:
            nxt = ks[i + 1] if i + 1 < len(ks) else ""
            out += [k[:-2], "had" if ("v3" in kinds(nxt) and "base" not in kinds(nxt)) or nxt == "been" else "would"]
        elif k.endswith("'s") and len(k) > 2 and k[:-2] in _PRON_S:
            nxt = next((x for x in ks[i + 1:i + 3] if x not in ADV), "")
            hk = kinds(nxt)
            out += [k[:-2], "has" if (nxt in _V3_ONLY_HINT or ("v3" in hk and "ing" not in hk and "base" not in hk)) else "is"]
        else:
            out.append(k)
    return out


def _going_to(ts: list[str]) -> list[str]:
    """`am/is/are going to <verb>` -> `will <verb>` (a valid way to say the future; a motion `going to the market` is left alone)."""
    out: list[str] = []
    i = 0
    n = len(ts)
    while i < n:
        if ts[i] in BE_PRES and i + 3 < n + 0 and ts[i + 1] == "going" and ts[i + 2] == "to" and i + 3 < n and "base" in kinds(ts[i + 3]) and ts[i + 3] not in DETS and ts[i + 3] not in SUBJ_PRON:
            out.append("will")
            i += 3
            continue
        if ts[i] in BE_PRES and i + 4 < n and ts[i + 1] == "not" and ts[i + 2] == "going" and ts[i + 3] == "to" and "base" in kinds(ts[i + 4]) and ts[i + 4] not in DETS:
            out += ["will", "not"]
            i += 4
            continue
        out.append(ts[i])
        i += 1
    return out


def norm_tokens(text: str) -> list[str]:
    """One sentence of learner or target text -> lower-case tokens: contractions expanded, `going to` read as `will`, fillers gone.  Bounded."""
    ks = [t.key for t in tokenize(clean_input(text))][:MAX_TOKENS]
    ks = [k for k in canon_contractions(ks) if k not in FILLERS]
    return _going_to(expand(ks))


_MULTI = (("by", "the", "time", "that"), ("by", "the", "time"), ("as", "soon", "as"), ("as", "long", "as"), ("the", "moment"), ("every", "time"), ("each", "time"), ("even", "if"), ("in", "case"), ("so", "that"))


def _sub_len(ts: list[str], j: int) -> int:
    """How many tokens at position j open a subordinate clause: a multi-word one (`by the time`, `as soon as`) or a single word from SUBORD; 0 = none."""
    for m in _MULTI:
        if tuple(ts[j:j + len(m)]) == m:
            return len(m)
    return 1 if ts[j] in SUBORD else 0


def split_clauses(ts: list[str]) -> list[list[str]]:
    """Cut a token list in front of every subordinator that opens a new FINITE clause (the subordinator itself is dropped)."""
    out: list[list[str]] = []
    cur: list[str] = []
    j, n = 0, len(ts)
    while j < n:
        k = _sub_len(ts, j)
        if k and cur and _has_finite(ts[j + k:]) and _has_finite(cur):
            out.append(cur)
            cur = []
            j += k
            continue
        cur.append(ts[j])
        j += 1
    if cur:
        out.append(cur)
    return out


def clauses(text: str) -> list[list[str]]:
    """The clauses of a sentence as normalised token lists: split at punctuation, then in front of a subordinator that opens a new finite clause."""
    out: list[list[str]] = []
    for p in (p for p in _SPLIT.split(clean_input(text)) if p.strip()):
        out.extend(split_clauses(norm_tokens(p)))
    return out


def _has_finite(ts: list[str]) -> bool:
    return any(t in AUX or kinds(t) for t in ts)


# --------------------------------------------------------------------------------------------- the classifier
def _after(ts: list[str], i: int, window: int = 5) -> list[tuple[int, str]]:
    """The tokens after position i (up to `window`), adverbs skipped - where a participle may stand (a question puts a subject in between)."""
    out = []
    for j in range(i + 1, min(len(ts), i + 1 + window + 3)):
        if ts[j] in ADV:
            continue
        out.append((j, ts[j]))
        if len(out) >= window:
            break
    return out


def _v3_at(ts: list[str], j: int) -> bool:
    k = kinds(ts[j])
    return "v3" in k and "ing" not in k and (j == 0 or ts[j - 1] not in DETS)


def _perf_at(ts: list[str], j: int) -> bool:
    """A participle after have/has/had.  The correct V3 - or, for a learner's slip (`has went`), an irregular V2 that is never a noun (not `saw`, `left`, `rose`...)."""
    if ts[j] == "had" and j > 0:                                       # have / had + had: the participle of `have` (have you had lunch; she had had enough)
        return True
    if _v3_at(ts, j):
        return True
    k = kinds(ts[j])
    return "v2" in k and "base" not in k and "s" not in k and ts[j] not in L.AMBIG_PAST and (j == 0 or ts[j - 1] not in DETS)


def _ing_at(ts: list[str], j: int) -> bool:
    return "ing" in kinds(ts[j]) and (j == 0 or ts[j - 1] not in DETS)


def clause_forms(ts: list[str]) -> set:
    """The tense form(s) of ONE clause.  A set, because an irregular verb that is spelled the same in V1 / V2 (put, cut, read) can be two forms; empty = cannot tell."""
    n = len(ts)
    if n == 0:
        return set()
    # ---- future: will / shall
    for i, t in enumerate(ts):
        if t in FUT:
            w = _after(ts, i)
            for k, (j, x) in enumerate(w):
                if x == "have":
                    nxt = w[k + 1] if k + 1 < len(w) else None
                    if nxt and nxt[1] == "been":
                        nn = w[k + 2] if k + 2 < len(w) else None
                        return {"future_perfect_continuous"} if nn and _ing_at(ts, nn[0]) else {"future_perfect"}
                    if nxt and _v3_at(ts, nxt[0]):
                        return {"future_perfect"}
                if x == "be":
                    nxt = w[k + 1] if k + 1 < len(w) else None
                    if nxt and _ing_at(ts, nxt[0]):
                        return {"future_continuous"}
            return {"future_simple"}
    # ---- past perfect (continuous): had
    for i, t in enumerate(ts):
        if t == "had" and not any(x in DO or x in ("have", "has") for x in ts[:i]):
            w = _after(ts, i)
            for k, (j, x) in enumerate(w):
                if x == "been":
                    nxt = w[k + 1] if k + 1 < len(w) else None
                    return {"past_perfect_continuous"} if nxt and _ing_at(ts, nxt[0]) else {"past_perfect"}
                if _perf_at(ts, j):
                    return {"past_perfect"}
            return {"past_simple"}                                       # had as a main verb (I had a car)
    # ---- present perfect (continuous): have / has
    for i, t in enumerate(ts):
        if t in ("have", "has") and not (i > 0 and ts[i - 1] == "to") and not any(x in DO for x in ts[:i]):       # `did / does / do ... have` = have is the main verb
            w = _after(ts, i)
            for k, (j, x) in enumerate(w):
                if x == "been":
                    nxt = w[k + 1] if k + 1 < len(w) else None
                    return {"present_perfect_continuous"} if nxt and _ing_at(ts, nxt[0]) else {"present_perfect"}
                if _perf_at(ts, j):
                    return {"present_perfect"}
            return {"present_simple"}                                    # have as a main verb (I have a pen)
    # ---- continuous: be + -ing
    for i, t in enumerate(ts):
        if t in BE_PAST or t in BE_PRES:
            for j, x in _after(ts, i):
                if _ing_at(ts, j):
                    return {"past_continuous"} if t in BE_PAST else {"present_continuous"}
                if x in AUX:
                    break
    # ---- simple: did / do(es) / be as the main verb / a bare verb
    for t in ts:
        if t == "did":
            return {"past_simple"}
    for t in ts:
        if t in ("do", "does"):
            return {"present_simple"}
    for t in ts:
        if t in BE_PAST:
            return {"past_simple"}
    for t in ts:
        if t in BE_PRES:
            return {"present_simple"}
    found: set = set()
    for j, t in enumerate(ts):
        k = kinds(t)
        if not k or (j > 0 and ts[j - 1] in DETS):
            continue
        if "v2" in k and "base" not in k and "s" not in k:
            found.add("past_simple")
        elif "v2" in k and ("base" in k or "s" in k):
            found.update(("present_simple", "past_simple"))
        elif "base" in k or "s" in k:
            found.add("present_simple")
    if len(found) > 1 and "past_simple" in found and "present_simple" in found and any(kinds(t) and "v2" in kinds(t) and "base" not in kinds(t) for t in ts):
        return {"past_simple"}                                           # one unambiguous past verb decides it
    return found


def forms_of(text: str) -> frozenset:
    """Every tense form used by the clauses of this sentence (empty when none can be read)."""
    out: set = set()
    for c in clauses(text):
        out |= clause_forms(c)
    return frozenset(out)


def forms_of_tokens(ts: list[str]) -> frozenset:
    out: set = set()
    for c in split_clauses(ts):
        out |= clause_forms(c)
    return frozenset(out)


_WH = frozenset(("what", "where", "when", "why", "how", "who", "which", "whose", "whom"))
_WH_NOUN = frozenset(("what", "which", "whose", "how"))
_WH_PREP = frozenset("at in on for from by to with about since until of".split())
_HOW_WORD = frozenset(("many", "much", "long", "often", "far", "old", "big", "tall", "fast", "soon", "late", "early"))


def is_question(ts: list[str]) -> bool:
    """A question starts with a helping verb, or with a wh-phrase (`what`, `what time`, `how many books`) followed by one (`does he play`, `where is she`, `what time did the train arrive`).
    `when he was young ...` is NOT one: there the subject comes first."""
    if not ts:
        return False
    if ts[0] in AUX:
        return True
    if len(ts) > 2 and ts[0] in _WH_PREP and ts[1] in _WH:                 # at what time / in which room / for how long
        ts = ts[1:]
    if ts[0] not in _WH:
        return False
    i = 1
    if ts[0] == "how" and i < len(ts) and ts[1] in _HOW_WORD:
        i += 1
    for _ in range(2 if ts[0] in _WH_NOUN else 0):                      # what time / which book / whose bag / how many books: a noun may sit between the wh-word and the helping verb
        if i < len(ts) and ts[i] in AUX:
            return True
        if i < len(ts) and ts[i] not in SUBJ_PRON and ts[i] not in DETS:
            i += 1
        else:
            break
    return i < len(ts) and ts[i] in AUX


def question_in(text: str) -> bool:
    """Is any CLAUSE of this text a question?  (`By the time we get there, will Amit have finished?` starts with a subordinate clause but is a question.)"""
    return any(is_question(c) for c in clauses(text))


def has_negation(ts: list[str]) -> bool:
    return any(t in ("not", "never", "no", "nobody", "nothing", "nowhere", "neither", "nor") for t in ts)
