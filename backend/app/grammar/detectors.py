"""Rule checks for the Grammar Coach: 16 token-pattern checks (D1-D16) + three table-driven ones (T1 prepositions, T2 patterns, T3 Indianisms).

Pure: no I/O, no clock.  Every check works on TOKEN KEYS (lowercase, apostrophes kept, see text.py) of ONE sentence and is a plain
index scan with bounded look-around windows - there is no regular expression anywhere in this file, so nothing can backtrack.  Input is
cut to MAX_TOK tokens before any check runs and every check is wrapped by `run_all`, so no input list can make it raise or stall.

A check is `solo` (may create a mark without the model) only when its measured precision is high (see tests/grammar/unit_detectors.py);
D2, D13 and D14 are solo only when the transcript came from Whisper / Gemini (they punctuate, so a missing "s" / a word order is not an
artefact of the recogniser) or when the sentence has a question mark.  A hit NEVER certifies a sentence clean - the absence of hits means
nothing.

API (what verify.py and the engine call):
    run_all(keys, *, source="chrome", has_q=False, opaque=frozenset()) -> list[Hit]
    solo_hits(...)                 same arguments, only the hits that may stand alone
    vetoes(keys)                   [(family, i, j)] spans where a KNOWN-ACCEPTABLE pattern matched (a model mark there is dropped)
    opportunities(rule, keys)      how many CORRECT uses of the rule's construct the sentence has (the "fixed" gate)
"""

from __future__ import annotations

from . import lexicon as L
from .text import canon_contractions
from .types import Hit

MAX_TOK = 600                       # a sentence longer than this is analysed only up to here (indices stay valid)

# ----------------------------------------------------------------------------------------------------------------------- small helpers

_YEAR_MIN, _YEAR_MAX = 1900, 2099


class _Ctx:
    __slots__ = ("n", "source", "has_q", "whisperish", "solo_cond", "start")

    def __init__(self, S, source, has_q):
        self.n = len(S)
        self.source = source
        self.has_q = bool(has_q)
        self.whisperish = source in ("whisper", "gemini")
        self.solo_cond = self.whisperish or self.has_q
        k = 0
        while k < min(3, self.n) and S[k] in L.FILL:
            k += 1
        self.start = k


def _is_year(t: str) -> bool:
    return len(t) == 4 and t.isdigit() and _YEAR_MIN <= int(t) <= _YEAR_MAX


def _is_num(t: str) -> bool:
    return t.isdigit() or (len(t) > 1 and t.replace(",", "").replace(".", "").isdigit())


def _at(S, i):
    return S[i] if 0 <= i < len(S) else ""


def _any_in(S, lo, hi, words) -> bool:
    for k in range(max(0, lo), min(len(S), hi)):
        if S[k] in words:
            return True
    return False


_IT_PREV = L.FILL | L._set("if because when while as that what how why where which then once until before after though although whether since "
                           "think thought guess hope believe know knew say said says maybe perhaps unless suppose than")


def _it_subj(S, i) -> bool:
    """`it` is a subject (not the object of a verb like "make it work") - looser pronouns he / she need no such test."""
    return i == 0 or S[i - 1] in _IT_PREV


def _subj3(S, i) -> bool:
    t = S[i]
    return t in ("he", "she") or (t == "it" and _it_subj(S, i))


_MANDATIVE = L._set("suggest suggests suggested insist insists insisted demand demands demanded recommend recommends recommended propose "
                    "proposes proposed request requests requested require requires required ask asks asked important essential necessary "
                    "vital imperative advisable crucial desire desired order ordered")
_EXCL_D2 = L.MODALS | _MANDATIVE | L._set("do does did to let lets letting make makes made making help helps helped watch watched see saw seen "
                                          "hear heard feel felt notice noticed not rather have had cannot")


def _excl_before(S, i, w=3) -> bool:
    for k in range(max(0, i - w), i):
        x = S[k]
        if x in _EXCL_D2 or x.endswith("n't"):
            return True
    return False


def _first_sound_vowel(w: str) -> bool:
    """Does the word begin with a VOWEL SOUND (so it takes `an`)?"""
    if not w:
        return False
    if w.startswith(L.AN_SOUND_VOWEL):
        return True
    if w in _ACRONYM_AN:
        return True
    c = w[0]
    if c in "aeiou":
        if w.startswith(L.A_SOUND_CONSONANT):
            return False
        return True
    if len(w) <= 5 and c in L.SPOKEN_LETTER_AN and not any(ch in "aeiou" for ch in w):
        return True                                     # letter-by-letter acronym: "an hr", "an sms", "an fm"
    return False


_ACRONYM_AN = L._set("mba mbbs mri sms fm nri lcd hr mp mla ngo fir rto mcq html sql faq mnc nda sdm led mca sbi rbi lic fdi hsc ms x")


def _art_for(w: str) -> str:
    return "an" if _first_sound_vowel(w) else "a"


def _h(c: _Ctx, rule, i, j, fix, det, solo=None) -> Hit:
    if solo is None:
        solo = _SOLO_BASE.get(det, True)
        if solo == "cond":
            solo = c.solo_cond
    return Hit(rule, i, j, tuple(fix), det, bool(solo))


# Per-check solo policy (documented in tests/grammar/unit_detectors.py - re-measured there on the hand-written corpus).
_SOLO_BASE = {"D1": True, "D2": "cond", "D3": True, "D4": True, "D5": True, "D6": True, "D7": True, "D8": True, "D9": True, "D10": True,
              "D11": True, "D12": True, "D13": "cond", "D14": "cond", "D15": True, "D16": True, "T1": True, "T2": True, "T3": True}

# ----------------------------------------------------------------------------------------------------------------------- D1 he don't

def d1(S, c):
    out = []
    for i in range(c.n - 1):
        if S[i + 1] != "don't":
            continue
        t = S[i]
        if t == "he" or t == "she" or (t == "it" and _it_subj(S, i)):
            if _at(S, i + 2) in ("you", "we", "they", "i"):         # a tag question: "she likes it, don't you"
                continue
            out.append(_h(c, "ag.he_dont", i + 1, i + 2, ("doesn't",), "D1"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D2 third-person s

_D2_VERBS = L.BASE_VERBS - L.V2_EQ_BASE - L._set("have be")
_LIKE_ADV = L._set("really so totally just literally actually very super kind sort is was are were be been")


def d2(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        if t != "he" and t != "she" and t != "it":
            continue
        if t == "it" and not _it_subj(S, i):
            continue
        j = i + 1
        if S[j] in L.ADV_MID and j + 1 < n:
            j += 1
        v = S[j]
        if v not in _D2_VERBS:
            continue
        nx = _at(S, j + 1)
        if v in ("need", "dare") and nx == "not":
            continue
        if v == "use" and nx == "to":
            continue
        if v == "like" and (nx in L.BASE_VERBS or nx in L.V2_FORMS or nx in L.ED_TO_BASE or nx in _LIKE_ADV):
            continue                                            # filler "like" ("she like went", "he like really")
        if _excl_before(S, i):
            continue
        out.append(_h(c, "ag.s_missing_3p", j, j + 1, (L.third_s(v),), "D2"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D3 aux form

_D3 = {}
for _s, _bad, _good in (("i", "is", "am"), ("i", "are", "am"), ("i", "has", "have"),
                        ("he", "are", "is"), ("he", "am", "is"), ("he", "have", "has"),
                        ("she", "are", "is"), ("she", "am", "is"), ("she", "have", "has"),
                        ("it", "are", "is"), ("it", "am", "is"), ("it", "have", "has"),
                        ("we", "is", "are"), ("we", "am", "are"), ("we", "has", "have"), ("we", "was", "were"),
                        ("you", "is", "are"), ("you", "am", "are"), ("you", "has", "have"), ("you", "was", "were"),
                        ("they", "is", "are"), ("they", "am", "are"), ("they", "has", "have"), ("they", "was", "were")):
    _D3[(_s, _bad)] = _good


def d3(S, c):
    out = []
    for i in range(c.n - 1):
        good = _D3.get((S[i], S[i + 1]))
        if good is None:
            continue
        if S[i] == "it" and not _it_subj(S, i):
            continue
        if S[i + 1] == "have" and S[i] in ("he", "she", "it") and _excl_before(S, i):
            continue                                            # "does he have", "I suggest he have"
        if S[i] == "i" and _at(S, i - 1) in ("and", "or", "nor"):
            continue                                            # compound subject: "my roommate and I are ..."
        if S[i] == "i" and S[i + 1] == "are" and _at(S, i - 1) in ("what", "who", "how", "where"):
            continue
        out.append(_h(c, "ag.aux_form", i + 1, i + 2, (good,), "D3"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D4 base after aux

_NT_DO = L._set("don't doesn't didn't can't couldn't won't wouldn't shouldn't mustn't mightn't shan't cannot")
_MODAL_PREV = L.PRON_SUBJ | L.WH | L._set("who and but so that if because then also just really probably maybe perhaps never always still only there "
                                           "this here when while these those")
_WANT_HEADS = L._set("want wants wanted need needs needed like likes liked love loves loved hate hates hated try tries tried trying plan plans "
                     "planned planning hope hopes hoped hoping have has had")
_PRON_Q = L.PRON_SUBJ


def _non_base(x: str):
    """(base, kind) when `x` is a finite / participle form that must be a base verb after an auxiliary; kind in s | past."""
    if x in L.BASE_VERBS or x in L.V2_EQ_BASE:
        return None
    b = L.S_TO_BASE.get(x)
    if b:
        return b, "s"
    if x in L.AMBIG_PAST:
        return None
    b = L.V2_TO_BASE.get(x) or L.V3_TO_BASE.get(x)
    if b and b != "be":
        return b, "past"
    b = L.ED_TO_BASE.get(x)
    if b:
        return b, "past"
    return None


def d4(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        if t == "did" or t == "does" or t == "do":
            kind = "do"
        elif t in _NT_DO:
            kind = "nt"
        elif t in L.MODALS:
            kind = "modal"
            if i > 0 and S[i - 1] not in _MODAL_PREV:
                continue
        else:
            continue
        j = i + 1
        subj = False
        if S[j] in _PRON_Q and j + 1 < n:
            subj = True
            j += 1
        x = S[j]
        if x == "able" and kind in ("modal", "nt") and _at(S, j + 1) == "to":
            out.append(_h(c, "md.can_able", j, j + 2, (), "D4"))
            continue
        r = _non_base(x)
        if r is None:
            continue
        base, form = r
        if kind == "do" and not subj:
            if t != "did" or form != "past":                    # "does exercises", "do works": a main verb + a plural noun
                continue
        if form == "s" and not subj and kind == "do":
            continue
        rule = "tn.did_past" if (t in ("did", "didn't") and form == "past") else "ag.base_after_aux"
        out.append(_h(c, rule, j, j + 1, (base,), "D4"))
    # want to going / need to goes ...
    for i in range(n - 2):
        if S[i] in _WANT_HEADS and S[i + 1] == "to":
            x = S[i + 2]
            b = L.ING_TO_BASE.get(x) or L.S_TO_BASE.get(x)
            if b and x not in L.BASE_VERBS:
                if S[i] in ("have", "has", "had") and _at(S, i - 1) in ("not", "n't"):
                    pass
                out.append(_h(c, "ag.base_after_aux", i + 2, i + 3, (b,), "D4"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D5 if + will

_CONJ5 = L._set("if unless until when before after")
_EMBED5 = L._set("ask asks asked tell tells told know knows knew wonder wonders wondering wondered sure whether see check find understand doubt "
                 "care matter matters depends depend question idea decide decided confirm remember guess imagine curious unsure uncertain")
_NOUN_BEFORE_WHEN = L._set("time day days moment year years week month point age date times hour hours situation way reason")
_NO_FUT_V = L._set("help make please save benefit")


def d5(S, c):
    out = []
    n = c.n
    for i in range(n - 3):
        t = S[i]
        if t not in _CONJ5 and not (t == "as" and i >= 2 and S[i - 1] == "soon" and S[i - 2] == "as"):
            continue
        asoon = t == "as"
        if t == "if" and (_at(S, i - 1) in ("as", "what")):
            continue
        if t == "when" and (c.has_q or _at(S, i - 1) in _NOUN_BEFORE_WHEN or _at(S, i - 1) in ("is", "'s", "was", "that's")):
            continue
        j = i + 1
        sj = S[j]
        if sj in L.PRON_SUBJ or sj in ("this", "that", "there"):
            j += 1
        elif sj in L.DETS and j + 1 < n and S[j + 1] not in ("will",):
            j += 2
        else:
            continue
        if S[j] != "will" or j + 1 >= n:
            continue
        v = S[j + 1]
        if sj == "you" and t == "if":
            continue                                            # polite "if you will"
        if v in _NO_FUT_V and t == "if" and sj in ("it", "this", "that"):
            continue                                            # "if it will help" (a purpose clause) is fine
        w = 6 if t in ("when", "before", "after") else 4
        lo = i - w
        if _any_in(S, lo, i, _EMBED5):
            continue
        # the subject decides the verb form
        if sj in ("he", "she", "it", "this", "that", "there") or (sj in L.DETS and not S[j - 1].endswith("s")):
            third = True
        else:
            third = False
        if v == "be":
            form = "is" if third else ("am" if sj == "i" else "are")
        elif v in L.BASE_VERBS or v == "have":
            form = L.third_s(v) if third else v
        else:
            continue
        out.append(_h(c, "tn.if_will", j, j + 2, (form,), "D5"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D6 present perfect + finished time

_D6_AUX = L._set("have has haven't hasn't")
_D6_CONTR = {"i've": "i", "we've": "we", "you've": "you", "they've": "they"}
_D6_ADV = L._set("already just never not ever also really still")
_D6_EXCL_PREV = L._set("since for from until till by before after over than")
_LAST_UNITS = L._set("week month year night weekend summer winter evening semester term morning monday tuesday wednesday thursday friday saturday sunday")
_D6_BREAK = L._set("and but so because then when that which if while or")


def _v3_base(x: str) -> str:
    if x == "been":
        return "be"
    if x in L.AMBIG_PAST and x not in ("lay",):
        return ""
    return L.V3_TO_BASE.get(x) or L.ED_TO_BASE.get(x) or ""


def _finished_marker(S, k: int) -> bool:
    n = len(S)
    t = S[k]
    prev = S[k - 1] if k > 0 else ""
    if prev in _D6_EXCL_PREV:
        return False
    if t == "yesterday":
        return True
    if t == "last":
        return prev != "the" and _at(S, k + 1) in _LAST_UNITS
    if t == "ago":
        return not _any_in(S, k - 3, k, _D6_EXCL_PREV)
    if t == "in":
        nx = _at(S, k + 1)
        return _is_year(nx) or nx in L.MONTHS_SAFE
    if t == "on":
        return _at(S, k + 1) in L.WEEKDAYS
    if t == "just":
        return _at(S, k + 1) == "now"
    return False


def _marker_after(S, v: int) -> bool:
    n = len(S)
    for k in range(v + 1, min(n, v + 9)):
        if S[k] in _D6_BREAK:
            return False
        if _finished_marker(S, k):
            return True
    return False


def _v2_for(base: str, subj: str, aux: str) -> str:
    if base == "be":
        return "were" if subj in ("we", "you", "they") else ("was" if subj in ("i", "he", "she", "it") else ("was" if aux == "has" else "were"))
    return L.v2_of(base)


def d6(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        contr = _D6_CONTR.get(t)
        if t not in _D6_AUX and contr is None:
            continue
        j = i + 1
        inv = None
        if contr is None and S[j] in L.PRON_SUBJ and (i <= c.start or _at(S, i - 1) in L.WH):
            inv = S[j]                                           # "have you seen him yesterday"
            j += 1
        advs = []
        while j < n and S[j] in _D6_ADV and len(advs) < 2:
            advs.append(S[j])
            j += 1
        if j >= n:
            continue
        base = _v3_base(S[j])
        if not base:
            continue
        if not _marker_after(S, j):
            continue
        subj = contr if contr else (inv if inv else _at(S, i - 1))
        if inv is not None:
            fix = ("did", inv) + tuple(a for a in advs) + (base,)
        elif t in ("haven't", "hasn't"):
            fix = ("didn't",) + tuple(advs) + (base,)
        elif "not" in advs:
            adv2 = [a for a in advs if a != "not"]
            fix = ("did", "not") + tuple(adv2) + (base,)
        else:
            fix = ((contr,) if contr else ()) + tuple(advs) + (_v2_for(base, subj, t),)
        out.append(_h(c, "tn.pp_finished", i, j + 1, fix, "D6"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D7 since / for

_C_VERBS = {"live": "lived", "work": "worked", "study": "studied", "stay": "stayed", "know": "known", "wait": "waited"}
_C_S = {L.third_s(k): k for k in _C_VERBS}
_BE_PRES = {"am": "have", "is": "has", "are": "have"}
_BE_CONTR = {"i'm": ("i", "have"), "we're": ("we", "have"), "you're": ("you", "have"), "they're": ("they", "have"),
             "he's": ("he", "has"), "she's": ("she", "has")}
_TP_START = L._set("yesterday morning evening childhood birth then")
_PERF = L._set("have has had haven't hasn't hadn't been i've we've you've they've")
_D7_BREAK = L._set("and but because that when while if so then")
_SINCE_TP_FOR = L._set("week month year summer winter")


def _is_duration(S, k) -> bool:
    n = len(S)
    if k + 1 >= n:
        return False
    return (S[k] in L.NUM_WORDS or _is_num(S[k])) and S[k + 1] in L.UNITS_TIME and _at(S, k + 2) != "ago"


def _is_timepoint(S, k) -> bool:
    t = _at(S, k)
    if not t:
        return False
    if _is_year(t) or t in _TP_START or t in L.WEEKDAYS or t in L.MONTHS_SAFE:
        return True
    if t == "last" and _at(S, k + 1) in L._set("week month year summer winter night"):
        return True
    if t in ("my", "his", "her", "our") and _at(S, k + 1) in L._set("childhood birth school college marriage youth"):
        return True
    if t == "the" and _at(S, k + 1) in L._set("morning beginning start"):
        return True
    return False


def d7(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        if t == "since":
            dur = _is_duration(S, i + 1)
            if dur:
                out.append(_h(c, "tn.since_for", i, i + 1, ("for",), "D7"))
            if dur or _is_timepoint(S, i + 1):
                out.extend(_d7_c(S, c, i))
        elif t == "for":
            nx = _at(S, i + 1)
            tp = _is_year(nx) or nx == "yesterday" or (nx == "last" and _at(S, i + 2) in _SINCE_TP_FOR)
            pv = _at(S, i - 1)
            verbish = pv in ("here", "there", "together") or pv in L.PRON_OBJ or pv in L.ING_TO_BASE or pv in L.V3_TO_BASE or pv in L.ED_TO_BASE or pv == "been"
            if tp and verbish and _d7_ctx(S, i):
                out.append(_h(c, "tn.since_for", i, i + 1, ("since",), "D7"))
    return out


def _d7_ctx(S, i) -> bool:
    for k in range(max(0, i - 8), i):
        x = S[k]
        if x in _PERF or x in _C_VERBS or x in _C_S or x in _BE_PRES or x in _BE_CONTR:
            return True
    return False


def _d7_c(S, c, s) -> list:
    """present simple / progressive of a state or habit verb + since + time point -> present perfect."""
    out = []
    lo = max(0, s - 8)
    k = s - 1
    while k >= lo:
        x = S[k]
        if x in _D7_BREAK:
            break
        if x in _PERF:
            return out
        k -= 1
    for k in range(lo, s):
        x = S[k]
        if x in _D7_BREAK:
            continue
        pv = _at(S, k - 1)
        if (x in _BE_PRES or x in _BE_CONTR) and L.ING_TO_BASE.get(_at(S, k + 1)):
            if x in _BE_PRES:
                out.append(_h(c, "tn.since_for", k, k + 1, (_BE_PRES[x], "been"), "D7"))
            else:
                a, b = _BE_CONTR[x]
                out.append(_h(c, "tn.since_for", k, k + 1, (a, b, "been"), "D7"))
            return out
        base = x if x in _C_VERBS else _C_S.get(x)
        if base and not (pv in L.MODALS or pv in ("to", "do", "does", "did", "not", "never") or pv.endswith("n't")):
            aux = "has" if x != base else "have"
            out.append(_h(c, "tn.since_for", k, k + 1, (aux, _C_VERBS[base]), "D7"))
            return out
    return out


# ----------------------------------------------------------------------------------------------------------------------- D8 continuous misuse

_D8_ING = {"knowing": "know", "wanting": "want", "needing": "need", "preferring": "prefer", "owning": "own", "believing": "believe",
           "understanding": "understand", "liking": "like"}
_D8_NEED_OBJ = L._set("it this that them him her me us everything nothing the what how my your his their our english now")
_D8_AUX = L._set("am is are was were")
_D8_CONTR = {"i'm": ("i", "am"), "he's": ("he", "is"), "she's": ("she", "is"), "it's": ("it", "is"), "we're": ("we", "are"),
             "you're": ("you", "are"), "they're": ("they", "are"), "that's": ("that", "is")}
_HAVE_OBJ = frozenset(set(L.KIN) | set(L.pluralize(w) for w in L.KIN) | set(
    "car bike scooter house flat phone mobile laptop dog cat job shop business farm land garden pet computer cars bikes houses flats phones "
    "dogs cats jobs".split()))
_HAVE_DET = L._set("a an two three four many one no")


def _d8_verb(form: str, aux: str, base: str, neg: bool):
    if neg:
        return ("didn't" if aux in ("was", "were") else ("doesn't" if aux == "is" else "don't"), base)
    if aux in ("was", "were"):
        return (L.v2_of(base),)
    return (L.third_s(base),) if aux == "is" else (base,)


def d8(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        contr = _D8_CONTR.get(t)
        if t not in _D8_AUX and contr is None:
            continue
        aux = contr[1] if contr else t
        subj_tok = (contr[0],) if contr else ()
        j = i + 1
        neg = False
        inv = None
        if S[j] == "not":
            neg = True
            j += 1
        elif contr is None and S[j] in L.PRON_SUBJ and j + 1 < n and S[j + 1] in _D8_ING:
            inv = S[j]
            j += 1
        x = _at(S, j)
        if x in _D8_ING:
            base = _D8_ING[x]
            nx = _at(S, j + 1)
            if x in ("understanding", "believing") and nx not in _D8_NEED_OBJ:
                continue
            solo = False if x == "liking" else None
            if inv is not None:
                aux_do = "did" if aux in ("was", "were") else ("does" if inv in ("he", "she", "it") else "do")
                out.append(_h(c, "tn.cont_misuse", i, j + 1, (aux_do, inv, base), "D8", solo))
            else:
                out.append(_h(c, "tn.cont_misuse", i, j + 1, subj_tok + _d8_verb(x, aux, base, neg), "D8", solo))
        elif x == "having" and aux in ("am", "is", "are") and not neg and inv is None:
            k = j + 1
            if _at(S, k) in _HAVE_DET:
                k += 1
            if _at(S, k) in _HAVE_OBJ:
                have = "has" if aux == "is" else "have"
                out.append(_h(c, "tn.cont_misuse", i, j + 1, subj_tok + (have,), "D8"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D9 a / an

_NUM_AN = lambda w: w.isdigit() and (w[0] == "8" or w in ("11", "18"))                      # noqa: E731
_FUNC_NEXT = L.A_FUNC_NEXT | L._set("um uh umm uhh er ah hmm")
_AN_SKIP_NEXT = L.PRON_SUBJ | L.DETS | L._set("so then")


def d9(S, c):
    out = []
    for i in range(c.n - 1):
        t = S[i]
        if t != "a" and t != "an":
            continue
        w = S[i + 1]
        if len(w) == 1 or w in _FUNC_NEXT:
            continue
        if w.isdigit() or _is_num(w):
            if t == "a" and _NUM_AN(w):
                out.append(_h(c, "ar.a_an", i, i + 1, ("an",), "D9"))
            continue
        if not w.isalpha():
            continue
        if w.startswith(L.AN_EITHER):
            continue
        vs = _first_sound_vowel(w)
        if t == "a" and vs:
            out.append(_h(c, "ar.a_an", i, i + 1, ("an",), "D9"))
        elif t == "an" and not vs:
            if w in _AN_SKIP_NEXT:
                continue
            out.append(_h(c, "ar.a_an", i, i + 1, ("a",), "D9"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D10 missing article

_COP = L._set("am is was")
_COP_C = L._set("i'm he's she's")
_WORLD_NOT_NEXT = L._set("war cup bank health trade class record wide series map heritage view news famous")
_NET_NOT_NEXT = L._set("explorer banking speed connection data plan cafe")


def _role_np(S, j, n):
    """From a position after the copula: (k, m) where S[k] is the head and m modifiers precede it."""
    k, m = j, 0
    while k < n and S[k] in L.ROLE_MODS and m < 2:
        k += 1
        m += 1
    return k, m


def d10(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        t = S[i]
        j = i + 1
        if t == "in" or t == "during":
            nx = S[j]
            if nx in L.DAYPARTS:
                if _at(S, j + 1) == "of" or _at(S, j + 1) in L.DAYPART_MODS:
                    continue
                out.append(_h(c, "ar.the_missing", j, j + 1, ("the", nx), "D10"))
            elif t == "in" and nx == "world" and _at(S, j + 1) not in _WORLD_NOT_NEXT:
                out.append(_h(c, "ar.the_missing", j, j + 1, ("the", nx), "D10"))
            continue
        if t == "on":
            if S[j] == "internet" and _at(S, j + 1) not in _NET_NOT_NEXT:
                out.append(_h(c, "ar.the_missing", j, j + 1, ("the", "internet"), "D10"))
            continue
        if t not in _COP and t not in _COP_C:
            continue
        if S[j] == "not":
            j += 1
        if j >= n or S[j] in L.DETS or S[j] in L.POSS:
            continue
        k, m = _role_np(S, j, n)
        if k >= n:
            continue
        role = S[k]
        if role in L.PROFESSIONS or (role in L.GENERIC_PERSON and m >= 1):
            nx = _at(S, k + 1)
            if nx and nx not in L.ROLE_NEXT_OK:
                continue
            out.append(_h(c, "ar.missing_a", j, j + 1, (_art_for(S[j]), S[j]), "D10"))
    # inverted: "is he doctor", "are you student"
    for i in range(n - 2):
        if S[i] in ("is", "was", "am", "are") and S[i + 1] in ("he", "she", "it", "this", "that", "you") and (i <= c.start or _at(S, i - 1) in L.WH):
            if S[i] == "are" and S[i + 1] != "you":
                continue
            j = i + 2
            if j >= n or S[j] in L.DETS or S[j] in L.POSS:
                continue
            k, m = _role_np(S, j, n)
            if k < n and S[k] in L.PROFESSIONS:
                nx = _at(S, k + 1)
                if nx and nx not in L.ROLE_NEXT_OK:
                    continue
                out.append(_h(c, "ar.missing_a", j, j + 1, (_art_for(S[j]), S[j]), "D10"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D11 noun number / much-many

_NOUN_PHRASE_BREAK = L.POSS_FOLLOW_OK | L._set("for with to of on by about from into as so then also there here")
_TIME_NOT_NEXT = L._set("zone zones slot slots management consuming saving wasting limit frame table period series")


def d11(S, c):
    out = []
    n = c.n
    for i in range(n):
        t = S[i]
        nx = S[i + 1] if i + 1 < n else ""
        bad = L.PLURAL_ERRORS.get(t)
        if bad is not None:
            if t in L.PLURAL_ERR_POSSESSIVE and nx and nx not in L.POSS_FOLLOW_OK:
                continue
            if t == "peoples" and (nx == "of" or _at(S, i - 1) in ("indigenous", "native", "aboriginal", "ethnic")):
                continue
            out.append(_h(c, "wd.noun_number", i, i + 1, (bad,), "D11"))
        elif (t == "a" or t == "an") and nx:
            k = i + 1
            if S[k] in L.UNCOUNT_A_ADJ:
                k += 1
            noun = _at(S, k)
            if noun in L.UNCOUNT_A:
                if noun == "knowledge" and _at(S, k + 1) in ("of", "about", "in"):
                    continue
                out.append(_h(c, "wd.noun_number", i, i + 1, (), "D11"))
        elif t == "much" and nx in L.COUNT_PLURALS:
            out.append(_h(c, "wd.much_many", i, i + 1, ("many",), "D11"))
        elif (t == "many" or t == "few") and nx in L.UNCOUNTABLE and nx not in ("software", "staff", "food", "work"):
            after = _at(S, i + 2)
            if after and after not in _NOUN_PHRASE_BREAK:
                continue
            out.append(_h(c, "wd.much_many", i, i + 1, ("much" if t == "many" else "little",), "D11"))
        elif t == "many" and nx == "time" and _at(S, i + 2) not in _TIME_NOT_NEXT:
            out.append(_h(c, "wd.much_many", i + 1, i + 2, ("times",), "D11"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D12 double comparative

def d12(S, c):
    out = []
    for i in range(c.n - 1):
        if (S[i] == "more" or S[i] == "most") and S[i + 1] in L.COMPARATIVES:
            out.append(_h(c, "wd.comparative_double", i, i + 1, (), "D12"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D13 question order

_WH_Q = L._set("what where when why how which")
_D13_SUBJ = L._set("you he she they we")
_D13_LATER = L._set("is was are were will be been mean means am would should could can must may might")


def d13(S, c):
    out = []
    n = c.n
    i = c.start
    if n < i + 3 or S[i] not in _WH_Q or S[i + 1] not in _D13_SUBJ:
        return out
    wh, subj, third = S[i], S[i + 1], S[i + 2]
    core = n - i
    if not (c.has_q or core <= 7):
        return out
    if wh == "when" and not c.has_q:
        return out
    later = S[i + 3:]
    if not c.has_q:
        for x in later:
            if x in _D13_LATER or x in L.S_TO_BASE or x.endswith("n't") or x in L.V2_FORMS or x in L.ED_TO_BASE:
                return out
    if third in ("am", "is", "are", "was", "were"):
        if third == "am":
            return out
        out.append(_h(c, "st.question_order", i + 1, i + 3, (third, subj), "D13"))
    elif third in L.V2_TO_BASE and third not in L.AMBIG_PAST and third not in L.V2_EQ_BASE or third in L.ED_TO_BASE:
        out.append(_h(c, "st.question_order", i + 1, i + 3, ("did", subj, L.V2_TO_BASE.get(third) or L.ED_TO_BASE[third]), "D13"))
    elif third in L.BASE_VERBS and third not in ("be",) or (subj in ("he", "she") and third in L.S_TO_BASE):
        aux = "does" if subj in ("he", "she") else "do"
        if subj in ("he", "she") and third in L.S_TO_BASE:
            out.append(_h(c, "st.question_order", i + 1, i + 3, (aux, subj, L.S_TO_BASE[third]), "D13"))
        else:
            out.append(_h(c, "st.question_order", i + 1, i + 2, (aux, subj), "D13"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D14 embedded order

_D14_TRIG = L._set("know tell ask wonder sure idea remember understand explain show check guess knows told asked wondering")
_D14_NOGUESS_DO = L._set("guess")
_D14_DET = L._set("the a an my your his her their our this that these those he she they we you i it")
_D14_STOP = L._set("in at on near and but or so because from to for with if when that which who by as is are was were will can would not today tomorrow yesterday now here there tonight again")
_D14_WH = L._set("what where when why how")
_YOU_KNOW_OK = L._set("do did don't can could would will")


def _d14_trigger(S, i) -> bool:
    for k in range(max(0, i - 4), i):
        if S[k] in _D14_TRIG:
            if S[k] == "know" and _at(S, k - 1) == "you" and _at(S, k - 2) not in _YOU_KNOW_OK:
                continue
            return True
    return False


def d14(S, c):
    out = []
    n = c.n
    for i in range(1, n - 1):
        wh = S[i]
        if wh not in _D14_WH:
            continue
        aux = S[i + 1]
        s0 = _at(S, i + 2)
        if aux in ("is", "are", "was", "were"):
            if s0 not in _D14_DET or not _d14_trigger(S, i):
                continue
            e = i + 3
            if s0 not in L.PRON_SUBJ:
                while e < n and (e - (i + 2)) < 5 and S[e] not in _D14_STOP:
                    e += 1
                if e < n and S[e] not in _D14_STOP:
                    continue                                    # the subject is longer than we can bound: stay silent
            out.append(_h(c, "st.embedded_order", i + 1, e, tuple(S[i + 2:e]) + (aux,), "D14"))
        elif aux in ("do", "does", "did") and s0 in L.PRON_SUBJ and _at(S, i + 3) in L.BASE_VERBS:
            if not _d14_trigger(S, i) or _any_in(S, i - 4, i, _D14_NOGUESS_DO):
                continue
            v = S[i + 3]
            if aux == "did":
                form = L.v2_of(v)
            elif aux == "does" or s0 in ("he", "she", "it"):
                form = L.third_s(v)
            else:
                form = v
            out.append(_h(c, "st.embedded_order", i + 1, i + 4, (s0, form), "D14"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- D15 double subject / pronoun misuse

_D15_AUX = L._set("is was has had does did can will would could should may might must doesn't didn't isn't wasn't hasn't won't can't "
                  "couldn't wouldn't always never also really just")
_D15_AUX_PL = L._set("are were have had do did can will would could should may might must don't didn't aren't weren't haven't won't can't "
                     "always never also really just")
_PRON_CONTR = {"he's": "is", "she's": "is", "he'll": "will", "she'll": "will", "he'd": "would", "she'd": "would", "they're": "are",
               "they've": "have", "they'll": "will", "they'd": "would"}
_NOM = {"him": "he", "her": "she", "them": "they", "me": "i", "us": "we"}
_BE_FORMS = L._set("is are was were am")


def _verbish(x: str, plural: bool) -> bool:
    if plural:
        return x in _D15_AUX_PL or x in L.BASE_VERBS or x in L.V2_TO_BASE or x in L.ED_TO_BASE
    return x in _D15_AUX or x in L.S_TO_BASE or (x in L.V2_TO_BASE and x not in L.AMBIG_PAST) or x in L.ED_TO_BASE


def d15(S, c):
    out = []
    n = c.n
    i = c.start
    if i < n and S[i] in L.POSS:
        j = i + 1
        if S[j:j + 1] and S[j] in L.KIN_ADJ and j + 1 < n:
            j += 1
        kin = _at(S, j)
        p = _at(S, j + 1)
        v = _at(S, j + 2)
        sing = kin in L.KIN
        plur = kin in L.KIN_PLURAL
        if p and (sing or plur):
            contr = _PRON_CONTR.get(p, "")
            pron = p if p in ("he", "she", "they") else (p.split("'")[0] if contr else "")
            ok_pron = (sing and pron in ("he", "she")) or (plur and pron == "they")
            if ok_pron and (contr or _verbish(v, plur)):
                g = L.KIN.get(kin, "e")
                mism = sing and ((g == "f" and pron == "he") or (g == "m" and pron == "she"))
                rule = "pn.pronoun_misuse" if mism else "st.double_subject"
                out.append(_h(c, rule, j + 1, j + 2, (contr,) if contr else (), "D15"))
    # him is my brother
    i = c.start
    if i + 1 < n and S[i] in _NOM and S[i + 1] in _BE_FORMS:
        out.append(_h(c, "pn.pronoun_misuse", i, i + 1, (_NOM[S[i]],), "D15"))
    # a female kin noun followed (later) by "he" ...: booster only
    for k in range(n - 3):
        g = L.KIN.get(S[k])
        if g not in ("f", "m") or _at(S, k - 1) not in L.POSS:
            continue
        for p in range(k + 2, min(n, k + 7)):
            x = S[p]
            if x in L.MALE_NOUNS or x in L.FEMALE_NOUNS or x in ("he", "she", "him", "his", "her"):
                if p > 0 and _at(S, p - 1) in ("and", "but", "so", "because", "when", "while", "then"):
                    if g == "f" and x in ("he", "him", "his") and not _any_in(S, k - 6, k, L._set("he him his")):
                        out.append(_h(c, "pn.pronoun_misuse", p, p + 1, ({"he": "she", "him": "her", "his": "her"}[x],), "D15", False))
                    elif g == "m" and x == "she" and not _any_in(S, k - 6, k, L._set("she her")):
                        out.append(_h(c, "pn.pronoun_misuse", p, p + 1, ("he",), "D15", False))
                break
    return out


# ----------------------------------------------------------------------------------------------------------------------- D16 time prepositions

_SUNDAY_NEXT = L._set("school service market best clothes league paper edition mass")
_NIGHT_NOT_NEXT = L._set("mode shift school club duty flight train bus out sky market life")
_CLOCK_SUFFIX = L._set("am pm o'clock oclock")
_DAYNUM_OK = L._set("of")


def _is_clock(S, k) -> bool:
    """S[k] starts a clock time: 5 pm, 6 30 pm, five pm, 5 o'clock."""
    t = _at(S, k)
    if not (t.isdigit() or t in L._set("one two three four five six seven eight nine ten eleven twelve")):
        return False
    nx = _at(S, k + 1)
    if nx in _CLOCK_SUFFIX:
        return True
    if nx.isdigit() and len(nx) == 2 and _at(S, k + 2) in _CLOCK_SUFFIX:
        return True
    if nx in ("a", "p") and _at(S, k + 2) == "m":
        return True
    return False


def _is_daynum(t: str) -> bool:
    if t.isdigit():
        return 1 <= int(t) <= 31
    if len(t) > 2 and t[-2:] in ("st", "nd", "rd", "th") and t[:-2].isdigit():
        return 1 <= int(t[:-2]) <= 31
    return t in L.ORDINAL_WORDS


def d16(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        p = S[i]
        if p not in ("in", "at", "on"):
            continue
        w = S[i + 1]
        nx = _at(S, i + 2)
        if w in L.WEEKDAYS:
            if p != "on" and not (w == "sunday" and nx in _SUNDAY_NEXT):
                out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("on",), "D16"))
        elif _is_year(w):
            if p != "in" and nx not in L.UNITS_AFTER_NUM and _at(S, i - 1) not in ("and",):
                out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("in",), "D16"))
        elif p != "at" and _is_clock(S, i + 1):
            out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("at",), "D16"))
        elif w in L.MONTHS_SAFE:
            if p == "at" or (p == "on" and not (_is_daynum(nx) or nx in L.ORDINAL_WORDS)):
                out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("in",), "D16"))
        elif _is_daynum(w) and p in ("on", "in") and (_at(S, i + 2) in L.MONTHS or (nx == "of" and _at(S, i + 3) in L.MONTHS)):
            if p == "in":
                out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("on",), "D16"))
        elif w in L.DAYPARTS and p in ("on", "at"):
            if nx != "of":
                out.append(_h(c, "pr.time_in_on_at", i, i + 2, ("in", "the", w), "D16"))
        elif w == "night" and p in ("on", "in"):
            if nx not in _NIGHT_NOT_NEXT and nx != "of":
                out.append(_h(c, "pr.time_in_on_at", i, i + 1, ("at",), "D16"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- T1 / T2 / T3 table checks

def _build_t1():
    idx: dict = {}
    for r in L.PREP_TABLE:
        kind, _, val = r.head.partition(":")
        toks = L.verb_forms(val) if kind == "v" else {val}
        for tk in toks:
            idx.setdefault(tk, []).append(r)
    return idx


_T1_IDX = _build_t1()


def t1(S, c):
    out = []
    n = c.n
    for i in range(n - 1):
        rows = _T1_IDX.get(S[i])
        if not rows:
            continue
        seen = set()
        for r in rows:
            m = len(r.wrong)
            j = i + 1
            if m:
                if tuple(S[j:j + m]) != r.wrong:
                    continue
                k = j + m
            else:
                k = j
                if k >= n:
                    continue
            if r.wrong in seen:
                continue
            if r.need_prev and (i == 0 or S[i - 1] not in r.need_prev):
                continue
            if r.not_prev and i > 0 and S[i - 1] in r.not_prev:
                continue
            nx = k
            first = S[nx] if nx < n else ""
            if r.skipdet and first in L.DETS:
                nx += 1
                first = S[nx] if nx < n else ""
            if r.need_next and first not in r.need_next:
                continue
            if r.not_next and first in r.not_next:
                continue
            if r.not_next2 and _at(S, nx + 1) in r.not_next2:
                continue
            seen.add(r.wrong)
            if m:
                out.append(_h(c, r.rule, j, j + m, r.fix, "T1"))
            else:
                out.append(_h(c, r.rule, k, k + 1, r.fix + (S[k],), "T1"))
    return out


_ADJ_BE = L._set(L._ADJ_BE)
_PRED = {
    "pl_quant": lambda t: t in L._set("many several few two three four five six seven eight nine ten") or (t.isdigit() and int(t) > 1),
    "sing_count": lambda t: t in L.SING_COUNT,
    "plural_noun": lambda t: t in L.SING_OF,
    "adj_be": lambda t: t in _ADJ_BE,
    "v2": lambda t: (t in L.V2_FORMS and t not in L.V2_EQ_BASE and t not in L.AMBIG_PAST) or t in L.ED_TO_BASE,
    "base_or_s": lambda t: (t in L.BASE_VERBS and t not in ("be",)) or t in L.S_TO_BASE,
    "plain_verb": lambda t: t in L.BASE_VERBS and t not in L.NOUNISH_VERBS and t not in ("be", "have"),
    "not_myself_next": lambda t: t not in L._set("and or i we is am was were have had can will would should too also only included personally myself my"),
}
_OBJ_PRON = {"i": "me", "you": "you", "he": "him", "she": "her", "it": "it", "we": "us", "they": "them"}


def _elem_ok(e, t: str) -> bool:
    if isinstance(e, str):
        return t == e
    if isinstance(e, frozenset):
        return t in e
    return _PRED[e[1]](t)


def _build_t2():
    idx: dict = {}
    for r in L.PATTERN_TABLE:
        e0 = r.elems[0]
        keys = [e0] if isinstance(e0, str) else list(e0)
        for k in keys:
            idx.setdefault(k, []).append(r)
    return idx


_T2_IDX = _build_t2()


def _fix_items(r, S, i):
    out = []
    for f in r.fix:
        if isinstance(f, str):
            out.append(f)
        elif isinstance(f, int):
            out.append(S[i + f])
        else:
            op, k, arg = f
            tok = S[i + k]
            if op == "map":
                v = arg.get(tok, tok)
                out.extend(v if isinstance(v, tuple) else (v,))
            elif op == "s3":
                out.append(L.third_s(L.base_of(tok) or tok))
            elif op == "be":
                out.append("am" if tok == "i" else ("is" if tok in ("he", "she", "it") else "are"))
            elif op == "plural":
                out.append(L.PLURAL_OF.get(tok) or L.pluralize(tok))
            elif op == "singular":
                out.append(L.SING_OF.get(tok) or tok.rstrip("s"))
            elif op == "ing":
                out.append(L.ing_form(L.base_of(tok) or tok))
            elif op == "base":
                out.append(L.base_of(tok) or tok)
            elif op == "obj":
                out.append(_OBJ_PRON.get(tok, tok))
    return tuple(out)


def t2(S, c):
    out = []
    n = c.n
    for i in range(n):
        rows = _T2_IDX.get(S[i])
        if not rows:
            continue
        for r in rows:
            m = len(r.elems)
            if i + m > n:
                continue
            ok = True
            for k in range(m):
                if not _elem_ok(r.elems[k], S[i + k]):
                    ok = False
                    break
            if not ok:
                continue
            if r.unit_start and i != c.start:
                continue
            if r.need_prev and not (i == c.start or (i > 0 and S[i - 1] in r.need_prev)):
                continue
            if r.not_prev and i > 0 and S[i - 1] in r.not_prev:
                continue
            if r.not_next and _at(S, i + m) in r.not_next:
                continue
            a, b = r.rng
            out.append(_h(c, r.rule, i + a, i + b, _fix_items(r, S, i), "T2"))
    return out


def _build_t3():
    idx: dict = {}
    for r in L.INDIAN_TABLE:
        idx.setdefault(r.phrase[0], []).append(r)
    return idx


_T3_IDX = _build_t3()


def t3(S, c):
    out = []
    n = c.n
    for i in range(n):
        rows = _T3_IDX.get(S[i])
        if not rows:
            continue
        for r in rows:
            m = len(r.phrase)
            if tuple(S[i:i + m]) != r.phrase:
                continue
            nx = _at(S, i + m)
            if r.need_next and nx not in r.need_next:
                continue
            if r.not_next and nx in r.not_next:
                continue
            out.append(_h(c, "ind.lexicon#" + r.slug, i, i + m, r.fix, "T3"))
    return out


# ----------------------------------------------------------------------------------------------------------------------- entry points

CHECKS = (d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11, d12, d13, d14, d15, d16, t1, t2, t3)


def _prep(keys):
    ks = canon_contractions([str(k) for k in list(keys)[:MAX_TOK]])
    return tuple(ks)


def run_all(keys, *, source="chrome", has_q=False, opaque=frozenset()):
    """Every rule-check Hit for ONE sentence's token keys (see the module docstring)."""
    try:
        S = _prep(keys)
    except Exception:
        return []
    if not S:
        return []
    c = _Ctx(S, source, has_q)
    hits: list = []
    for fn in CHECKS:
        try:
            hits.extend(fn(S, c))
        except Exception:                                      # a check must never take the engine down
            continue
    if opaque:
        hits = [h for h in hits if not any(k in opaque for k in range(h.i, h.j))]
    seen = set()
    uniq = []
    for h in hits:
        key = (h.rule, h.i, h.j, h.fix)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    uniq.sort(key=lambda h: (h.i, h.j, h.rule))
    return uniq


def solo_hits(keys, *, source="chrome", has_q=False, opaque=frozenset()):
    return [h for h in run_all(keys, source=source, has_q=has_q, opaque=opaque) if h.solo]


# ----------------------------------------------------------------------------------------------------------------------- vetoes

_CAUS = L._set("let lets make makes made help helps helped watch watched see saw hear heard feel felt notice noticed have had")
_FOOD_ACT = L._set("lunch dinner breakfast coffee tea fun trouble problem problems party meeting shower bath break nap look talk conversation "
                   "discussion time a an")


def vetoes(keys):
    """[(family, i, j)] spans where a known-acceptable pattern matched, so a model mark on that span is dropped."""
    try:
        S = _prep(keys)
    except Exception:
        return []
    n = len(S)
    out = set()
    for i in range(n):
        t = S[i]
        nx = _at(S, i + 1)
        n2 = _at(S, i + 2)
        if t in _CAUS and nx in L.PRON_OBJ and n2 in L.BASE_VERBS:
            out.add(("ag", i + 1, i + 3))
        if t == "let's" and nx in L.BASE_VERBS:
            out.add(("ag", i, i + 2))
        if t in _MANDATIVE:
            j = i + 1
            if _at(S, j) == "that":
                j += 1
            if _at(S, j) in L.PRON_SUBJ and _at(S, j + 1) in L.BASE_VERBS | {"be"}:
                out.add(("ag", j, j + 2))
        if t in ("if", "wish", "though", "suppose") and nx in L.PRON_SUBJ | {"there", "this", "that"} and n2 == "were":
            out.add(("ag", i + 1, i + 3))
        if t in L.WH and nx in L.PRON_SUBJ and _any_in(S, i + 3, n, L._set("is was are will")):
            out.add(("st", i, min(n, i + 3)))
        if t == "how" and nx == "you" and n2 in L.ING_TO_BASE:
            out.add(("st", i, i + 3))
        if t == "many" and nx == "a":
            out.add(("wd", i, i + 3))
        if t == "much" and (nx in L.UNCOUNTABLE or nx in ("time", "money")):
            out.add(("wd", i, i + 2))
        if t in ("many", "few", "several") and nx in L.COUNT_PLURALS:
            out.add(("wd", i, i + 2))
        if t == "more" and nx == "or" and n2 == "less":
            out.add(("wd", i, i + 3))
        if t == "more" and nx == "than":
            out.add(("wd", i, i + 2))
        if t == "peoples" and (nx == "of" or _at(S, i - 1) in ("indigenous", "native", "aboriginal", "ethnic")):
            out.add(("wd", i, i + 1))
        if (t == "a" or t == "an") and nx and nx.isalpha() and len(nx) > 1 and not nx.startswith(L.AN_EITHER):
            if (t == "an") == _first_sound_vowel(nx):
                out.add(("ar", i, i + 2))
        if t == "since" and (nx in L.PRON_SUBJ or nx in ("the", "there")) and not _is_timepoint(S, i + 1):
            out.add(("tn", i, i + 2))
        if t == "for" and _is_duration(S, i + 1) and _any_in(S, i - 5, i, L._set("am is are was were have has had been i'm we're you're they're")):
            out.add(("tn", max(0, i - 3), i + 3))
        if t in ("if", "when", "before", "after", "until", "unless"):
            j = i + 1
            if _at(S, j) in L.PRON_SUBJ and _at(S, j + 1) == "will":
                if _any_in(S, i - 6, i, _EMBED5) or _at(S, j) == "you":
                    out.add(("tn", i, min(n, i + 4)))
        if t == "having" and nx in _FOOD_ACT and _at(S, i - 1) in L.BE_GET:
            out.add(("tn", i - 1, i + 2))
        if t in ("loving", "hating") and _at(S, i - 1) in L.BE_GET:
            out.add(("tn", i - 1, i + 1))
        if t in _D8_ING and _at(S, i - 1) in ("without", "by", "for", "of", "in", "about", "while", "from", "after", "before", "on"):
            out.add(("tn", i - 1, i + 1))
        if t in _D6_AUX or t in _D6_CONTR:
            if _any_in(S, i + 1, i + 7, L._set("since for")):
                out.add(("tn", i, min(n, i + 6)))
        if t in L.PROFESSIONS and nx in ("council", "union", "body"):
            out.add(("ar", i, i + 2))
        if t in L.WEEKDAYS and nx in _SUNDAY_NEXT:
            out.add(("pr", max(0, i - 1), i + 2))
        if t == "on" and nx in L.WEEKDAYS:
            out.add(("pr", i, i + 2))
        if t == "in" and (_is_year(nx) or nx in L.MONTHS_SAFE):
            out.add(("pr", i, i + 2))
        if t == "at" and nx == "night":
            out.add(("pr", i, i + 2))
        if t in L.MODALS and nx in L.BASE_VERBS:
            out.add(("ag", max(0, i - 1), i + 2))
        if t in ("do", "does", "did") and nx in L.PRON_SUBJ and n2 in L.BASE_VERBS:
            out.add(("ag", i, i + 3))
            out.add(("tn", i, i + 3))
    return sorted(out, key=lambda x: (x[1], x[2], x[0]))


# ----------------------------------------------------------------------------------------------------------------------- opportunities

def _count(pred, S, lo=0):
    return sum(1 for i in range(lo, len(S)) if pred(i))


def _opp_prep_rule(rule, S):
    pos = set()
    n = len(S)
    for i in range(n - 1):
        rows = _T1_IDX.get(S[i])
        if not rows:
            continue
        for r in rows:
            if r.rule != rule:
                continue
            if r.wrong and r.fix:
                if tuple(S[i + 1:i + 1 + len(r.fix)]) == r.fix:
                    pos.add(i)
            elif r.wrong and not r.fix:
                if S[i + 1] not in r.wrong and S[i + 1] not in ("to", "at", "on", "about", "with", "into", "up", "from", "for", "of", "in"):
                    pos.add(i)
            elif not r.wrong:
                if tuple(S[i + 1:i + 1 + len(r.fix)]) == r.fix:
                    pos.add(i)
            if rule == "pr.for_purpose" and S[i + 1] == "to" and _at(S, i + 2) in L.BASE_VERBS:
                pos.add(i)
    return len(pos)


def _opp_aux_form(S):
    ok = {("i", "am"), ("i", "was"), ("i", "have"), ("he", "is"), ("he", "was"), ("he", "has"), ("she", "is"), ("she", "was"),
          ("she", "has"), ("it", "is"), ("it", "was"), ("it", "has"), ("we", "are"), ("we", "were"), ("we", "have"), ("you", "are"),
          ("you", "were"), ("you", "have"), ("they", "are"), ("they", "were"), ("they", "have")}
    return sum(1 for i in range(len(S) - 1) if (S[i], S[i + 1]) in ok) + _count(lambda i: S[i] in ("i'm", "he's", "she's", "we're", "they're", "you're"), S)


def _opp_base_after_aux(S):
    n = len(S)
    cnt = 0
    for i in range(n - 1):
        t = S[i]
        if t in ("do", "does", "did") or t in _NT_DO or t in L.MODALS:
            j = i + 1
            if _at(S, j) in L.PRON_SUBJ:
                j += 1
            x = _at(S, j)
            if x in L.BASE_VERBS or x in ("be", "have"):
                cnt += 1
    return cnt


def _opp_if_will(S):
    cnt = 0
    for i in range(len(S) - 2):
        if S[i] in _CONJ5 and (S[i + 1] in L.PRON_SUBJ or S[i + 1] in ("this", "that", "there")):
            x = S[i + 2]
            if x in L.S_TO_BASE or x in L.BASE_VERBS or x in ("is", "are", "am", "was", "were", "has", "have", "had"):
                cnt += 1
    return cnt


def _opp_pp(S):
    cnt = 0
    for i in range(len(S) - 1):
        t = S[i]
        if t in _D6_AUX or t in _D6_CONTR:
            j = i + 1
            while j < len(S) and S[j] in _D6_ADV:
                j += 1
            if _v3_base(_at(S, j)) or _at(S, j) in L.V3_FORMS:
                cnt += 1
        elif (t in L.V2_FORMS and t not in L.V2_EQ_BASE) or t in L.ED_TO_BASE:
            if _any_in(S, i + 1, i + 6, L._set("yesterday ago")) or (_at(S, i + 1) == "last"):
                cnt += 1
    return cnt


def _opp_since_for(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] == "since" and (_is_timepoint(S, i + 1)):
            cnt += 1
        elif S[i] == "for" and (_is_duration(S, i + 1) or (_at(S, i + 1) in L.NUM_WORDS and _at(S, i + 2) in L.UNITS_TIME)):
            cnt += 1
    return cnt


_STATIVE_OK = L._set("know knows knew want wants wanted need needs needed like likes liked prefer prefers preferred own owns owned believe "
                     "believes believed understand understands understood")


def _opp_a_an(S):
    cnt = 0
    for i in range(len(S) - 1):
        t = S[i]
        if (t == "a" or t == "an") and S[i + 1].isalpha() and len(S[i + 1]) > 1 and S[i + 1] not in _FUNC_NEXT and not S[i + 1].startswith(L.AN_EITHER):
            if (t == "an") == _first_sound_vowel(S[i + 1]):
                cnt += 1
    return cnt


def _opp_missing_a(S):
    cnt = 0
    n = len(S)
    for i in range(n - 1):
        if S[i] in L._set("am is was are i'm he's she's they're we're"):
            j = i + 1
            if S[j] in ("a", "an", "the"):
                j += 1
                m = 0
                while j < n and S[j] in L.ROLE_MODS and m < 2:
                    j += 1
                    m += 1
                if _at(S, j) in L.PROFESSIONS or _at(S, j) in L.PLURAL_OF.values():
                    cnt += 1
            elif S[i] in ("are", "they're", "we're") and S[j] in {L.pluralize(p) for p in L.PROFESSIONS}:
                cnt += 1
    return cnt


def _opp_the_missing(S):
    cnt = 0
    for i in range(len(S) - 2):
        if S[i] in ("in", "during", "on") and S[i + 1] == "the" and (S[i + 2] in L.DAYPARTS or S[i + 2] in ("internet", "world")):
            cnt += 1
    return cnt


_UNCOUNT_SING = L.UNCOUNT_A | L._set("people children men women")


def _opp_noun_number(S):
    return _count(lambda i: S[i] in _UNCOUNT_SING, S)


def _opp_much_many(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] == "much" and S[i + 1] in L.UNCOUNTABLE:
            cnt += 1
        elif S[i] in ("many", "few", "several") and S[i + 1] in L.COUNT_PLURALS:
            cnt += 1
    return cnt


def _opp_comparative(S):
    cnt = 0
    for i in range(len(S)):
        if S[i] in L.COMPARATIVES and _at(S, i - 1) not in ("more", "most"):
            cnt += 1
        elif S[i] in ("more", "most") and _at(S, i + 1) in _ADJ_BE:
            cnt += 1
    return cnt


def _opp_question_order(S):
    cnt = 0
    for i in range(len(S) - 2):
        if S[i] in _WH_Q and S[i + 1] in ("do", "does", "did", "is", "are", "was", "were", "can", "will", "would", "should", "could", "have", "has"):
            if S[i + 2] in L.PRON_SUBJ or S[i + 2] in L.DETS:
                cnt += 1
    return cnt


def _opp_embedded(S):
    cnt = 0
    for i in range(1, len(S) - 2):
        if S[i] in _D14_WH and _d14_trigger(S, i):
            sub = S[i + 1]
            if sub in L.PRON_SUBJ and S[i + 2] in ("is", "are", "was", "were"):
                cnt += 1
            elif sub in L.DETS and _any_in(S, i + 3, i + 6, L._set("is are was were")):
                cnt += 1
    return cnt


def _opp_double_subject(S):
    cnt = 0
    n = len(S)
    for i in range(n - 2):
        if S[i] in L.POSS:
            j = i + 1
            if S[j] in L.KIN_ADJ and j + 1 < n:
                j += 1
            if (S[j] in L.KIN or S[j] in L.KIN_PLURAL) and j + 1 < n and S[j + 1] not in ("he", "she", "they", "and", "or"):
                if _verbish(S[j + 1], S[j] in L.KIN_PLURAL) or S[j + 1] in L._set("is are was were has have had"):
                    cnt += 1
    return cnt


def _opp_pronoun(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] in ("he", "she", "they", "we", "i") and (S[i + 1] in L._set("is are was were am has have had") or S[i + 1] in L.S_TO_BASE):
            cnt += 1
    return cnt


def _opp_time_prep(S):
    cnt = 0
    for i in range(len(S) - 1):
        p, w = S[i], S[i + 1]
        if (p == "on" and w in L.WEEKDAYS) or (p == "in" and (_is_year(w) or w in L.MONTHS_SAFE)) or (p == "at" and (_is_clock(S, i + 1) or w == "night")):
            cnt += 1
        elif p == "in" and w == "the" and _at(S, i + 2) in L.DAYPARTS:
            cnt += 1
        elif p == "on" and _is_daynum(w):
            cnt += 1
    return cnt


def _opp_there(S):
    return _count(lambda i: S[i] == "there" and _at(S, i + 1) in ("are", "were", "is", "was", "'s", "there's"), S)


def _opp_quant(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] in ("every", "each") and S[i + 1] in L.SING_COUNT:
            cnt += 1
        elif S[i] == "one" and _at(S, i + 1) == "of":
            j = i + 2
            if _at(S, j) in L.DETS or _at(S, j) in L.POSS:
                j += 1
            if _at(S, j).endswith("s") and _at(S, j) in L.SING_OF:
                cnt += 1
    return cnt


def _opp_say_tell(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] in ("tell", "told", "tells", "telling") and S[i + 1] in L.PRON_OBJ:
            cnt += 1
        elif S[i] in ("said", "say", "says", "saying") and S[i + 1] in ("that", "to"):
            cnt += 1
    return cnt


_COLLO_OK = (L._set("make made makes making"), L._set("mistake mistakes noise plan plans decision decisions promise promises call calls effort efforts excuse suggestion"))
_COLLO_OK2 = (L._set("do did does done doing"), L._set("homework exercise exercises shopping housework laundry"))
_COLLO_OK3 = (L._set("tell told tells telling"), L._set("lie lies joke jokes story stories truth secret secrets"))
_COLLO_OK4 = (L._set("take took takes taking taken"), L._set("photo photos photograph selfie selfies bath shower nap walk"))
_COLLO_OK5 = (L._set("have had has having"), L._set("party parties"))


def _opp_collocation(S):
    cnt = 0
    n = len(S)
    for i in range(n - 1):
        for verbs, nouns in (_COLLO_OK, _COLLO_OK2, _COLLO_OK3, _COLLO_OK4, _COLLO_OK5):
            if S[i] in verbs:
                j = i + 1
                if _at(S, j) in L.COLLO_DETS:
                    j += 1
                if _at(S, j) in nouns:
                    cnt += 1
                    break
        if S[i] in ("turn", "turned", "turns", "turning") and _at(S, i + 1) in ("on", "off"):
            cnt += 1
    return cnt


def _opp_be_misuse(S):
    cnt = 0
    for i in range(len(S) - 2):
        if S[i] in L.PRON_SUBJ and S[i + 1] in ("is", "am", "are", "was", "were") and (S[i + 2] in _ADJ_BE or (S[i + 2] == "very" and _at(S, i + 3) in _ADJ_BE)):
            cnt += 1
        elif S[i] in L.PRON_SUBJ and S[i + 1] in L._set("agree disagree know want need love hate think believe understand forget prefer remember"):
            cnt += 1
    return cnt


def _opp_adverb_position(S):
    cnt = 0
    for i in range(len(S) - 1):
        if S[i] in ("is", "am", "are") and S[i + 1] in L._set("always never usually often sometimes generally normally"):
            cnt += 1
        elif i == 0 and S[i] == "yesterday" and _at(S, 1) in L.PRON_SUBJ:
            cnt += 1
        elif S[i] == "very" and S[i + 1] == "much":
            cnt += 1
    return cnt


def _opp_verb_pattern(S):
    cnt = 0
    for i in range(len(S) - 2):
        if S[i] in ("want", "wants", "wanted", "need", "needs", "needed") and S[i + 1] in L.PRON_OBJ and S[i + 2] == "to":
            cnt += 1
        elif S[i] in L._set(L._ING_VERBS) and S[i + 1] in L.ING_TO_BASE:
            cnt += 1
        elif S[i] in ("make", "makes", "made", "making", "let", "lets") and S[i + 1] in L.PRON_OBJ and S[i + 2] in L.BASE_VERBS:
            cnt += 1
        elif S[i] == "forward" and S[i + 1] == "to" and S[i + 2] in L.ING_TO_BASE:
            cnt += 1
    return cnt


def _opp_myself(S):
    return 1 if len(S) >= 2 and S[0] == "i" and S[1] == "am" else 0


def _opp_relative(S):
    return _count(lambda i: S[i] in L._set(_PERSON_WHO) and _at(S, i + 1) == "who", S)


_PERSON_WHO = "person man woman people boy girl friend friends teacher teachers doctor doctors guy guys lady ladies someone anyone everyone colleague colleagues students student children men women"

_OPP = {
    "ag.he_dont": lambda S: sum(1 for i in range(len(S) - 1) if (S[i] in ("he", "she", "it") and S[i + 1] == "doesn't") or (S[i] in ("i", "you", "we", "they") and S[i + 1] == "don't")),
    "ag.s_missing_3p": lambda S: sum(1 for i in range(len(S) - 1) if S[i] in ("he", "she", "it") and (S[i + 1] in L.S_TO_BASE or (S[i + 1] in L.ADV_MID and _at(S, i + 2) in L.S_TO_BASE))),
    "ag.aux_form": _opp_aux_form,
    "ag.base_after_aux": _opp_base_after_aux,
    "tn.did_past": _opp_base_after_aux,
    "md.can_able": lambda S: sum(1 for i in range(len(S) - 1) if S[i] in L.MODALS and S[i + 1] in L.BASE_VERBS),
    "tn.if_will": _opp_if_will,
    "tn.pp_finished": _opp_pp,
    "tn.since_for": _opp_since_for,
    "tn.cont_misuse": lambda S: _count(lambda i: S[i] in _STATIVE_OK, S),
    "ar.a_an": _opp_a_an,
    "ar.missing_a": _opp_missing_a,
    "ar.the_missing": _opp_the_missing,
    "wd.noun_number": _opp_noun_number,
    "wd.much_many": _opp_much_many,
    "wd.comparative_double": _opp_comparative,
    "st.question_order": _opp_question_order,
    "st.embedded_order": _opp_embedded,
    "st.double_subject": _opp_double_subject,
    "pn.pronoun_misuse": _opp_pronoun,
    "pr.time_in_on_at": _opp_time_prep,
    "ag.there_is_plural": _opp_there,
    "ag.quantifier_number": _opp_quant,
    "wd.say_tell": _opp_say_tell,
    "wd.collocation": _opp_collocation,
    "st.be_misuse": _opp_be_misuse,
    "st.adverb_position": _opp_adverb_position,
    "st.verb_pattern": _opp_verb_pattern,
    "pn.myself_intro": _opp_myself,
    "pn.relative": _opp_relative,
}


def opportunities(rule, keys) -> int:
    """Number of CORRECT uses of the rule's construct in the sentence (she goes / they were / an apple / on Monday / what do you ...)."""
    try:
        S = _prep(keys)
        r = str(rule or "").split("#")[0]
        if r in ("pr.extra_prep", "pr.wrong_prep", "pr.missing_to", "pr.for_purpose"):
            return _opp_prep_rule(r, S)
        f = _OPP.get(r)
        return int(f(S)) if f else 0
    except Exception:
        return 0
