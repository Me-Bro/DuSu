"""Verification of proposed grammar marks (pure; no database, no network, no clock).

The AI proposes `{r, q, f, c, w}` per sentence; this module is the only thing between the model and the learner. A mark survives only if
CODE can locate it, bound it and check it (plan Appendix A4, steps 1-9, in this order):

  1 shape          q <= 80 chars, f <= 100, w <= 14 words (else only w is dropped)
  2 locate         the quote is a contiguous run of WHOLE tokens of the sentence (case / punctuation insensitive), first occurrence
  3 bounds         1..8 quote tokens, <= 10 fix tokens, token edit distance <= min(4, ceil(0.6*|q|)); word-order rules <= 6 tokens with the
                   same token multiset +/- an auxiliary; an empty fix only for deletion rules
  4 artifact       q and f equal after canonicalising case / punctuation / numerals / contractions / repeats / fillers / homophones -> dropped
  5 rule id        unknown -> `other`; guard(rule, q, f) checks the changed tokens belong to the rule's class; else a sibling rule; else `other`
  6 eligibility    catalogue level, severity allowed at the level, no rule-check veto, no opaque token touched, contested rule -> `likely`
  7 confidence     `sure` only if the model said so AND (the rule is not STT-sensitive OR the source is not Chrome OR a solo rule check agrees
                   OR the recogniser confidence >= 0.80); a solo hit on the same span upgrades likely -> sure; `other` needs agreement
  8 overlap        identical (rule, i, j) merge; on overlap keep the higher prio
  9 corrected      built by code from `sure` error marks only, right to left; post-conditions or None

Every loop here is bounded (raw marks, hits, vetoes, token counts) and every regex is the tokenizer's linear one.
"""

from __future__ import annotations

import importlib
import math
import re
from collections import Counter

from . import catalog, level_rank, norm_level
from .text import tokenize, canon_contractions
from .types import Hit, Mark

MAX_Q_CHARS = 80
MAX_F_CHARS = 100
MAX_W_WORDS = 14
MAX_RAW = 20            # raw marks looked at per sentence (the engine asks for <= 3)
MAX_HITS = 300
MAX_VETOES = 600
Q_MAX_TOK = 8
Q_MAX_TOK_ORDER = 6
F_MAX_TOK = 10
SURE_CONF = 0.80

SEV_FACTOR = {"error": 1.0, "natural": 0.35, "polish": 0.15}
CONF_FACTOR = {"sure": 1.0, "likely": 0.5}

WORD_ORDER = frozenset({"st.question_order", "st.embedded_order", "st.adverb_position"})
ORDER_AUX = frozenset({"do", "does", "did", "is", "are", "was", "were", "'s"})
# rules whose fix may be empty (the learner added a word that has to go)
DELETION_RULES = frozenset({"pr.extra_prep", "ar.the_overuse", "st.double_subject", "md.can_able", "pn.pronoun_misuse",
                            "wd.comparative_double", "st.be_misuse"})

# --------------------------------------------------------------------------------------------- word classes
ART = frozenset({"a", "an", "the"})
PREP = frozenset("""in on at to for of with from by about into onto over under after before during since until till between among through
towards toward across against within without up down off near beside behind like as than along around past via per""".split())
PRON = frozenset("""i me my mine myself you your yours yourself he him his himself she her hers herself it its itself we us our ours ourselves
they them their theirs themselves who whom whose which that this these those""".split())
AUX = frozenset("""be am is are was were been being 's 'm 're have has had having do does did done doing will would shall should can could may
might must to not don't doesn't didn't can't cannot won't isn't aren't wasn't weren't haven't hasn't hadn't shouldn't couldn't wouldn't
i'm i've you're they're we're he's she's it's that's""".split())
QUANT = frozenset("much many few little less fewer some any every each one all most several more lot lots a an the another other".split())
SAYTELL = frozenset("say says said saying tell tells told telling to that me him her them us you".split())
RELATIVE = frozenset("who whom whose which that what where when".split())
SUBJ = frozenset("it there i we they he she this that you".split())
MYSELF = frozenset("myself i am my name is me".split())
FILLERS = frozenset("um umm uh uhh er erm err hmm hm ah mm mhm".split())

# base, past, past participle
_IRREG = [
    ("be", "was", "been"), ("have", "had", "had"), ("do", "did", "done"), ("go", "went", "gone"), ("see", "saw", "seen"),
    ("come", "came", "come"), ("take", "took", "taken"), ("give", "gave", "given"), ("get", "got", "gotten"), ("make", "made", "made"),
    ("know", "knew", "known"), ("think", "thought", "thought"), ("buy", "bought", "bought"), ("bring", "brought", "brought"),
    ("eat", "ate", "eaten"), ("drink", "drank", "drunk"), ("write", "wrote", "written"), ("read", "read", "read"),
    ("speak", "spoke", "spoken"), ("say", "said", "said"), ("tell", "told", "told"), ("find", "found", "found"), ("leave", "left", "left"),
    ("meet", "met", "met"), ("run", "ran", "run"), ("sit", "sat", "sat"), ("stand", "stood", "stood"), ("sleep", "slept", "slept"),
    ("wake", "woke", "woken"), ("begin", "began", "begun"), ("break", "broke", "broken"), ("choose", "chose", "chosen"),
    ("drive", "drove", "driven"), ("fall", "fell", "fallen"), ("feel", "felt", "felt"), ("fly", "flew", "flown"), ("forget", "forgot", "forgotten"),
    ("grow", "grew", "grown"), ("hear", "heard", "heard"), ("hold", "held", "held"), ("keep", "kept", "kept"), ("lose", "lost", "lost"),
    ("pay", "paid", "paid"), ("put", "put", "put"), ("ride", "rode", "ridden"), ("rise", "rose", "risen"), ("sell", "sold", "sold"),
    ("send", "sent", "sent"), ("show", "showed", "shown"), ("sing", "sang", "sung"), ("spend", "spent", "spent"), ("swim", "swam", "swum"),
    ("teach", "taught", "taught"), ("throw", "threw", "thrown"), ("understand", "understood", "understood"), ("wear", "wore", "worn"),
    ("win", "won", "won"), ("build", "built", "built"), ("catch", "caught", "caught"), ("cut", "cut", "cut"), ("hit", "hit", "hit"),
    ("let", "let", "let"), ("set", "set", "set"), ("shut", "shut", "shut"), ("lead", "led", "led"), ("learn", "learnt", "learnt"),
    ("lend", "lent", "lent"), ("mean", "meant", "meant"), ("pick", "picked", "picked"), ("stay", "stayed", "stayed"),
    ("steal", "stole", "stolen"), ("sweep", "swept", "swept"), ("tear", "tore", "torn"), ("wind", "wound", "wound"),
    ("bear", "bore", "born"), ("bite", "bit", "bitten"), ("blow", "blew", "blown"), ("draw", "drew", "drawn"), ("hide", "hid", "hidden"),
    ("lie", "lay", "lain"), ("shake", "shook", "shaken"), ("shoot", "shot", "shot"), ("sink", "sank", "sunk"), ("strike", "struck", "struck"),
    ("swear", "swore", "sworn"), ("beat", "beat", "beaten"), ("become", "became", "become"), ("cost", "cost", "cost"),
]
_IRR_ID: dict[str, set] = {}
for _n, (_b, _p, _pp) in enumerate(_IRREG):
    for _f in (_b, _p, _pp):
        _IRR_ID.setdefault(_f, set()).add(_n)
_PLURALS = [("man", "men"), ("woman", "women"), ("child", "children"), ("foot", "feet"), ("person", "people"), ("tooth", "teeth"), ("mouse", "mice")]
for _n2, (_s, _pl) in enumerate(_PLURALS, start=1000):
    for _f in (_s, _pl):
        _IRR_ID.setdefault(_f, set()).add(_n2)
_ADJ_ADV = {("good", "well"), ("well", "good")}

# --------------------------------------------------------------------------------------------- canonical forms (step 4)
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "twenty": 20}
_TENS = {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
        "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
        "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50}
_ORD_SUFFIX = frozenset({"st", "nd", "rd", "th"})
_HOMO = {}
for _cls in (("their", "there", "they're"), ("your", "you're"), ("its", "it's"), ("to", "too", "two"), ("then", "than"),
             ("whose", "who's"), ("know", "no"), ("here", "hear"), ("write", "right")):
    for _w in _cls:
        _HOMO[_w] = "~" + _cls[0]
_CONTR = {"don't": ("do", "not"), "doesn't": ("does", "not"), "didn't": ("did", "not"), "can't": ("can", "not"), "cannot": ("can", "not"),
          "won't": ("will", "not"), "isn't": ("is", "not"), "aren't": ("are", "not"), "wasn't": ("was", "not"), "weren't": ("were", "not"),
          "haven't": ("have", "not"), "hasn't": ("has", "not"), "hadn't": ("had", "not"), "shouldn't": ("should", "not"),
          "couldn't": ("could", "not"), "wouldn't": ("would", "not"), "i'm": ("i", "am"), "i've": ("i", "have"), "i'll": ("i", "will"),
          "i'd": ("i", "would"), "you're": ("you", "are"), "they're": ("they", "are"), "we're": ("we", "are"), "you've": ("you", "have"),
          "we've": ("we", "have"), "they've": ("they", "have"), "he's": ("he", "is"), "she's": ("she", "is"), "it's": ("it", "is"),
          "that's": ("that", "is"), "what's": ("what", "is"), "there's": ("there", "is"), "here's": ("here", "is"), "who's": ("who", "is"),
          "let's": ("let", "us"), "you'll": ("you", "will"), "we'll": ("we", "will"), "they'll": ("they", "will"), "he'll": ("he", "will"),
          "she'll": ("she", "will"), "it'll": ("it", "will")}


def _numerals(ks: list[str]) -> list[str]:
    """Number words 0-20 / tens / ordinals -> digit strings; 'twenty five' -> '25'; '1st' (1 + st) -> '1'; '1,000' -> '1000'."""
    out: list[str] = []
    for k in ks:
        if out and k in _ORD_SUFFIX and out[-1].isdigit():
            continue
        if k in _ONES:
            v = str(_ONES[k])
        elif k in _TENS:
            v = str(_TENS[k])
        elif k in _ORD:
            v = str(_ORD[k])
        elif k[:1].isdigit():
            v = k.replace(",", "")
        else:
            out.append(k)
            continue
        # tens + unit ("twenty" "five") -> 25
        if out and v.isdigit() and 1 <= int(v) <= 9 and out[-1].isdigit() and int(out[-1]) in (20, 30, 40, 50, 60, 70, 80, 90) and k in _ONES:
            out[-1] = str(int(out[-1]) + int(v))
        else:
            out.append(v)
    return out


def _expand(ks: list[str]) -> list[str]:
    out: list[str] = []
    for k in ks:
        out.extend(_CONTR.get(k, (k,)))
    return out


def _homo(ks: list[str]) -> list[str]:
    return [_HOMO.get(k, k) for k in ks]


def _dedupe_runs(ks: list[str]) -> list[str]:
    out: list[str] = []
    for k in ks:
        if not out or out[-1] != k:
            out.append(k)
    return out


def _canon_variants(ks: list[str]) -> list[tuple]:
    """Canonical forms of a token list under the four artifact pipelines (case / punctuation are already gone: the tokenizer keys)."""
    raw = _dedupe_runs([k for k in canon_contractions(ks) if k not in FILLERS])
    base = _dedupe_runs(_numerals(raw))
    d = _dedupe_runs
    return [tuple(base), tuple(d(_expand(base))), tuple(d(_homo(base))), tuple(d(_expand(_homo(base)))),
            tuple(d(_homo(raw))), tuple(d(_expand(_homo(raw))))]


def is_artifact_only(qk: list[str], fk: list[str]) -> bool:
    """True when q and f differ only by what a speech recogniser may have chosen differently (case, punctuation, numerals, contractions,
    repeats, fillers, homophones)."""
    if qk == fk:
        return True
    a, b = _canon_variants(qk), _canon_variants(fk)
    return any(x == y for x in a for y in b)


# --------------------------------------------------------------------------------------------- small edit helpers
def _charedit(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 3 or len(a) > 40 or len(b) > 40:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _tokedit(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _changed(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    """Tokens of a and b NOT on a longest common subsequence: (left only, right only)."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    i = j = 0
    la: list[str] = []
    lb: list[str] = []
    while i < n and j < m:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            la.append(a[i])
            i += 1
        else:
            lb.append(b[j])
            j += 1
    la.extend(a[i:])
    lb.extend(b[j:])
    return la, lb


def _pair_ok(a: str, b: str) -> bool:
    """Two tokens may be forms of the same word: a known irregular pair, or the same first letter and a char edit <= 3."""
    ia, ib = _IRR_ID.get(a), _IRR_ID.get(b)
    if ia and ib and ia & ib:
        return True
    return bool(a and b and a[0] == b[0] and _charedit(a, b) <= 3)


def _all_resolved(left: list[str], right: list[str], free: frozenset | set, pair=_pair_ok) -> bool:
    """Every changed token is either in the rule's `free` class or has a partner on the other side (edit <= 3 / irregular / special)."""
    for t in left:
        if t in free:
            continue
        if not any(pair(t, u) for u in right):
            return False
    for u in right:
        if u in free:
            continue
        if not any(pair(t, u) for t in left):
            return False
    return True


# --------------------------------------------------------------------------------------------- rule guards (step 5)
def _guard(rule: str, qk: list[str], fk: list[str]) -> bool:
    """Do the tokens that differ between q and f belong to the rule's class? `other` has no class."""
    if rule == catalog.OTHER:
        return True
    left, right = _changed(qk, fk)
    ch = set(left) | set(right)
    if rule == "ar.a_an":
        return len(left) == 1 and len(right) == 1 and set(left) | set(right) <= {"a", "an"}
    if rule == "ar.missing_a":
        return not left and bool(right) and set(right) <= {"a", "an"}
    if rule == "ar.the_missing":
        return "the" in right and set(right) <= ({"the"} | PREP) and set(left) <= PREP
    if rule == "ar.the_overuse":
        return bool(left) and set(left) <= ART and not right
    if rule == "pr.time_in_on_at":
        return ch <= (PREP | ART | {"night", "morning", "evening", "afternoon"})
    if rule.startswith("pr."):
        return ch <= (PREP | ART)
    if rule in ("tn.pp_finished", "tn.cont_misuse", "tn.did_past", "tn.if_will", "tn.cond_would", "tn.past_marker", "ag.he_dont",
                "ag.s_missing_3p", "ag.aux_form"):
        return _all_resolved(left, right, AUX)
    if rule == "tn.since_for":
        return _all_resolved(left, right, AUX | {"since", "for"})
    if rule == "ag.base_after_aux":
        return _all_resolved(left, right, AUX | {"ing"})
    if rule == "md.can_able":
        return _all_resolved(left, right, AUX | {"able"})
    if rule == "ag.there_is_plural":
        return _all_resolved(left, right, AUX | {"there", "here", "there's", "here's"})
    if rule in ("wd.noun_number", "wd.much_many", "ag.quantifier_number"):
        return _all_resolved(left, right, QUANT)
    if rule == "wd.comparative_double":
        return set(left) <= {"more", "most"} or _all_resolved(left, right, {"more", "most"})
    if rule == "wd.adj_adv":
        return _all_resolved(left, right, {"very", "so", "too"}, pair=lambda a, b: (a, b) in _ADJ_ADV or _pair_ok(a, b))
    if rule == "wd.say_tell":
        return ch <= (SAYTELL | PRON)
    if rule in ("wd.collocation", "st.verb_pattern", "st.run_on_frag"):
        return len(left) <= 3 and len(right) <= 3
    if rule in WORD_ORDER:
        return True                                   # the multiset check in `_bounds` is the guard
    if rule == "st.double_subject":
        return set(left) <= PRON and not right
    if rule == "pn.pronoun_misuse":
        return _all_resolved(left, right, PRON | AUX)
    if rule == "st.be_misuse":
        return _all_resolved(left, right, AUX | PRON)
    if rule == "st.missing_subject":
        return not left and set(right) <= SUBJ
    if rule == "pn.myself_intro":
        return ch <= MYSELF
    if rule == "pn.relative":
        return ch <= RELATIVE
    return True


def _bounds(rule: str, qk: list[str], fk: list[str]) -> bool:
    """Step 3 for one candidate rule."""
    nq, nf = len(qk), len(fk)
    if not 1 <= nq <= Q_MAX_TOK or nf > F_MAX_TOK:
        return False
    base = catalog.base_id(rule)
    if base == "ind.lexicon":
        return True                                   # the fix comes from the lexicon, not from the model
    if nf == 0:
        return base in DELETION_RULES
    if base in WORD_ORDER:
        if nq > Q_MAX_TOK_ORDER:
            return False
        extra = ORDER_AUX | ({"much"} if base == "st.adverb_position" else frozenset())
        cq, cf = Counter(qk), Counter(fk)
        diff = (cq - cf) + (cf - cq)
        return all(t in extra for t in diff) and qk != fk
    return _tokedit(qk, fk) <= min(4, math.ceil(0.6 * nq))


# --------------------------------------------------------------------------------------------- the Indianism lexicon
def _load_lex():
    for mod in ("lexicon", "detectors"):
        try:
            m = importlib.import_module("." + mod, package=__package__)
        except Exception:
            continue
        v = getattr(m, "INDIAN_LEX", None)
        if v:
            return v
    return None


def _lex_lookup(lex, qk: list[str]):
    """-> (entry_id, fix_text or None) when the quote is a known Indianism, else None. The lexicon may map phrase -> fix (str),
    phrase -> {"id","fix"}, or phrase -> (fix, ...); a plain set / list of phrases means 'known, fix unspecified'."""
    if not lex:
        return None
    phrase = " ".join(qk)
    entry = "_".join(qk)[:40]
    try:
        if isinstance(lex, (set, frozenset, list, tuple)):
            return (entry, None) if phrase in lex else None
        val = lex.get(phrase)
        if val is None:
            val = lex.get(tuple(qk))
        if val is None:
            return None
    except Exception:
        return None
    if isinstance(val, str):
        return entry, val
    if isinstance(val, dict):
        fix = val.get("fix") or val.get("f") or val.get("to")
        return str(val.get("id") or entry)[:40], (fix if isinstance(fix, str) else None)
    if isinstance(val, (tuple, list)) and val and isinstance(val[0], str):
        return entry, val[0]
    return entry, None


# --------------------------------------------------------------------------------------------- shared helpers
def _allowed_at(rule: catalog.Rule, level) -> bool:
    """Catalogue level + the severity table (A1: errors of weight >= 2; A2: errors; B1: + natural; B2: + polish)."""
    if not catalog.eligible(rule, level):
        return False
    r = level_rank(level)
    if rule.severity == "error":
        return rule.weight >= 2 if r == 0 else True
    if rule.severity == "natural":
        return r >= 2
    return r >= 3


def prio(m: Mark) -> float:
    return m.weight * SEV_FACTOR.get(m.severity, 0.15) * CONF_FACTOR.get(m.conf, 0.5)


def _overlap(i1: int, j1: int, i2: int, j2: int) -> bool:
    return i1 < j2 and i2 < j1


def _fix_case(quote: str, fix: str) -> str:
    """The first letter of the fix follows the quote's (lowercase STT text stays lowercase); the pronoun "I" is always capital."""
    if not fix:
        return fix
    first = fix.split(" ", 1)[0]
    if first == "i" or re.fullmatch(r"i'(?:m|ve|ll|d)", first):
        return "I" + fix[1:]
    q0 = next((c for c in quote if c.isalpha()), "")
    f0 = fix[0]
    if q0 and f0.isalpha():
        if q0.islower() and f0.isupper() and first not in ("I",) and not re.fullmatch(r"I'(?:m|ve|ll|d)", first):
            return f0.lower() + fix[1:]
        if q0.isupper() and f0.islower():
            return f0.upper() + fix[1:]
    return fix


def _dedupe_overlap(marks: list[Mark]) -> list[Mark]:
    """Step 8: merge identical (rule, i, j), then greedily keep the highest-prio non-overlapping marks."""
    best: dict[tuple, Mark] = {}
    for m in marks:
        k = (m.rule, m.i, m.j)
        if k not in best or prio(m) > prio(best[k]):
            best[k] = m
    ordered = sorted(best.values(), key=lambda m: (-prio(m), m.i, m.j - m.i))
    kept: list[Mark] = []
    for m in ordered:
        if all(not _overlap(m.i, m.j, k.i, k.j) for k in kept):
            kept.append(m)
    kept.sort(key=lambda m: (m.i, m.j))
    return kept


def _veto_hit(rule: catalog.Rule | None, rid: str, i: int, j: int, vetoes) -> bool:
    fam = rule.family if rule else ""
    for v in list(vetoes)[:MAX_VETOES]:
        try:
            f, a, b = v
        except Exception:
            continue
        if (f == fam or f == rid or f == catalog.base_id(rid)) and _overlap(i, j, a, b):
            return True
    return False


def _touches_opaque(i: int, j: int, ks: list[str], opaque) -> bool:
    if not opaque:
        return False
    for p in range(i, j):
        if p in opaque or ks[p] in opaque:
            return True
    return False


def _agreeing_hit(mark_rule: str, i: int, j: int, solo: list[Hit]) -> Hit | None:
    grp = _group(mark_rule)
    for h in solo:
        if _overlap(i, j, h.i, h.j) and (mark_rule == catalog.OTHER or _group(h.rule) == grp):
            return h
    return None


def _group(rule_id: str) -> str:
    r = catalog.get(rule_id)
    return catalog.GROUPS.get(r.family, r.family) if r else ""


def _clean_hits(hits, n_tokens: int) -> list[Hit]:
    out = []
    for h in list(hits or ())[:MAX_HITS]:
        try:
            if 0 <= h.i < h.j <= n_tokens:
                out.append(h)
        except Exception:
            continue
    return out


def _mk(rule_id, i, j, toks, text, fix, *, conf, src, why="", det="") -> Mark | None:
    rule = catalog.get(rule_id)
    start, end = toks[i].start, toks[j - 1].end
    quote = text[start:end]
    if rule is None:
        sev, w, fam = "error", 1, catalog.OTHER
        rid = catalog.OTHER
    else:
        sev, w, fam, rid = rule.severity, rule.weight, rule.family, rule_id
    return Mark(rule=rid, i=i, j=j, start=start, end=end, quote=quote, fix=_fix_case(quote, fix), conf=conf, severity=sev, weight=w,
                family=fam, why=why, src=src, det=det)


# --------------------------------------------------------------------------------------------- the public API
def _w_ok(w) -> str:
    if not isinstance(w, str):
        return ""
    w = " ".join(w.split())
    return w if 0 < len(w.split()) <= MAX_W_WORDS else ""


def verify_marks(sent_text, raw_marks, *, level, source="chrome", conf=None, hits=(), vetoes=(), opaque=frozenset(), contested=frozenset(),
                 lex=None) -> list[Mark]:
    """Model-proposed marks -> the verified list (see the module docstring). `hits` / `vetoes` are the rule checks' output for this sentence,
    already computed by the caller; `lex` overrides the Indianism lexicon (default: lazy import of `lexicon.INDIAN_LEX`)."""
    text = sent_text if isinstance(sent_text, str) else ""
    if not text or not isinstance(raw_marks, (list, tuple)):
        return []
    toks = tokenize(text)
    if not toks:
        return []
    ks = [t.key for t in toks]
    sk = canon_contractions(ks)
    n = len(sk)
    firsts: dict[str, list[int]] = {}
    for p, k in enumerate(sk):
        firsts.setdefault(k, []).append(p)
    hl = _clean_hits(hits, n)
    solo = [h for h in hl if h.solo]
    cand: list[Mark] = []
    lex_cache = [lex]
    lex_loaded = lex is not None

    for raw in list(raw_marks)[:MAX_RAW]:
        # ---- 1 shape
        if not isinstance(raw, dict):
            continue
        q, f = raw.get("q"), raw.get("f", "")
        f = "" if f is None else f
        if not isinstance(q, str) or not isinstance(f, str):
            continue
        q, f = q.strip(), f.strip()
        if not q or len(q) > MAX_Q_CHARS or len(f) > MAX_F_CHARS:
            continue
        said = raw.get("c") == "s"
        why = _w_ok(raw.get("w"))
        rid_req = raw.get("r") if isinstance(raw.get("r"), str) else ""
        # ---- 2 locate (whole tokens, first occurrence)
        qk = canon_contractions([t.key for t in tokenize(q)])
        if not qk:
            continue
        pos = -1
        m_ = len(qk)
        for p in firsts.get(qk[0], ()):
            if p + m_ <= n and sk[p:p + m_] == qk:
                pos = p
                break
        if pos < 0:
            continue
        i, j = pos, pos + m_
        fk = canon_contractions([t.key for t in tokenize(f)])
        # the requested rule (unknown -> other)
        rid = rid_req.strip()
        rule = catalog.get(rid)
        if rule is None:
            rid, rule = catalog.OTHER, None
        elif "#" not in rid:
            rid = rule.id
        # ---- 3 bounds (for the requested rule)
        if not _bounds(rid, qk, fk):
            continue
        # ---- 4 artifact-only
        if is_artifact_only(qk, fk):
            continue
        # ---- 5 rule id
        entry_fix: str | None = None
        base = catalog.base_id(rid)
        if base == "ind.lexicon":
            if not lex_loaded:
                lex_cache[0] = _load_lex()
                lex_loaded = True
            hit_ = _lex_lookup(lex_cache[0], qk)
            if hit_ is None:
                continue
            entry, entry_fix = hit_
            rid = "ind.lexicon#" + entry
            if entry_fix is not None:
                fk = canon_contractions([t.key for t in tokenize(entry_fix)])
                if not 1 <= len(fk) <= F_MAX_TOK or is_artifact_only(qk, fk):
                    continue
        elif not _guard(base, qk, fk):
            relabel = None
            if rule is not None:
                grp = _group(base)
                for r2 in catalog.RULES.values():
                    if r2.id != base and r2.family != "ind" and catalog.GROUPS.get(r2.family) == grp and _bounds(r2.id, qk, fk) and _guard(r2.id, qk, fk):
                        relabel = r2.id
                        break
            if relabel is None:                                  # a solo rule check on the same span may name the rule
                for h in solo:
                    if _overlap(i, j, h.i, h.j) and catalog.get(h.rule) and "#" not in h.rule and _bounds(h.rule, qk, fk) and _guard(h.rule, qk, fk):
                        relabel = h.rule
                        break
            rid = relabel or catalog.OTHER
            base = rid
        rule = catalog.get(rid)
        if rule is None:
            rid = catalog.OTHER
        # ---- 6 eligibility
        if rule is not None and not _allowed_at(rule, level):
            continue
        if _veto_hit(rule, rid, i, j, vetoes) or _touches_opaque(i, j, ks, opaque):
            continue
        if rule is None and level_rank(level) == 0:
            continue                                             # beginners never see an unlabelled mark
        # ---- 7 confidence
        agree = _agreeing_hit(rid, i, j, solo)
        stt = bool(rule and rule.stt_sensitive)
        sure = said and (not stt or source != "chrome" or agree is not None or (conf is not None and conf >= SURE_CONF))
        if rid == catalog.OTHER and agree is None:
            sure = False
        if agree is not None and not sure:
            sure = True                                          # a solo hit on the same span upgrades likely -> sure
        if rule is not None and (rid in contested or catalog.base_id(rid) in contested):
            sure = False                                         # auto-demoted rule: soft only
        fix_text = entry_fix if entry_fix is not None else f
        mk = _mk(rid, i, j, toks, text, fix_text, conf="sure" if sure else "likely", src="both" if agree is not None else "model",
                 why=why, det=agree.det if agree is not None else "")
        cand.append(mk)
    return _dedupe_overlap(cand)


def marks_from_hits(sent_text, hits, *, level="B1", source="chrome", conf=None, vetoes=(), opaque=frozenset(), contested=frozenset()) -> list[Mark]:
    """Solo rule-check hits -> marks (src='rule') for the AI-down floor. A solo check is deterministic, so its marks are `sure` unless the
    rule is contested. Never certifies a sentence clean (that is `status_of`'s job and needs a model verdict)."""
    text = sent_text if isinstance(sent_text, str) else ""
    toks = tokenize(text)
    if not toks:
        return []
    ks = [t.key for t in toks]
    out: list[Mark] = []
    for h in _clean_hits(hits, len(toks)):
        if not h.solo:
            continue
        rule = catalog.get(h.rule)
        if rule is None or not _allowed_at(rule, level):
            continue
        if _veto_hit(rule, h.rule, h.i, h.j, vetoes) or _touches_opaque(h.i, h.j, ks, opaque):
            continue
        sure = not (h.rule in contested or rule.id in contested)
        fix = " ".join(h.fix) if h.fix else ""
        out.append(_mk(h.rule, h.i, h.j, toks, text, fix, conf="sure" if sure else "likely", src="rule", det=h.det))
    return _dedupe_overlap(out)


def build_corrected(sent_text, marks, *, recheck=None):
    """The corrected sentence, BUILT BY CODE from `sure` error marks only (right to left by char offset). Returns None when there is nothing
    to apply or a post-condition fails: token count within [n-4, n+6], no new digit token, and (when `recheck(text) -> [Hit]` is given) no
    new solo hit. A `likely` mark is never applied. First-letter case follows the original (lowercase STT stays lowercase)."""
    text = sent_text if isinstance(sent_text, str) else ""
    use = [m for m in marks or () if m.severity == "error" and m.conf == "sure"]
    if not text or not use:
        return None
    use.sort(key=lambda m: (m.start, m.end), reverse=True)
    out = text
    applied: list[Mark] = []
    for m in use:
        if not 0 <= m.start < m.end <= len(text) or any(m.start < a.end and a.start < m.end for a in applied):
            continue
        s, e, rep = m.start, m.end, m.fix
        if not rep:                                               # a deletion eats one neighbouring space
            if e < len(out) and out[e] == " ":
                e += 1
            elif s > 0 and out[s - 1] == " ":
                s -= 1
        out = out[:s] + rep + out[e:]
        applied.append(m)
    if not applied:
        return None
    if any(a.i == 0 for a in applied):                            # the sentence start: keep the original's first-letter case
        o0 = next((c for c in text if c.isalpha()), "")
        k = next((p for p, c in enumerate(out) if c.isalpha()), -1)
        if o0 and k >= 0:
            c = out[k]
            word = re.match(r"[^\W_]+(?:'[^\W_]+)?", out[k:])
            is_i = bool(word and re.fullmatch(r"I(?:'(?:m|ve|ll|d))?", word.group(0)))
            if o0.isupper() and c.islower():
                out = out[:k] + c.upper() + out[k + 1:]
            elif o0.islower() and c.isupper() and not is_i:
                out = out[:k] + c.lower() + out[k + 1:]
    out = out.strip()
    if out == text:
        return None
    n0 = len(tokenize(text))
    t1 = tokenize(out)
    if not n0 - 4 <= len(t1) <= n0 + 6 or not t1:
        return None
    d0 = Counter(t.key for t in tokenize(text) if t.key[:1].isdigit())
    d1 = Counter(t.key for t in t1 if t.key[:1].isdigit())
    if any(d1[k] > d0.get(k, 0) for k in d1):
        return None
    if recheck is not None:
        try:
            old = Counter((h.rule, h.det) for h in recheck(text) if h.solo)
            new = Counter((h.rule, h.det) for h in recheck(out) if h.solo)
        except Exception:
            return None
        if any(new[k] > old.get(k, 0) for k in new):
            return None
    return out


def display_case(text) -> str:
    """Sentence case for DISPLAY only. Lowercase speech-to-text gets a capital first letter, "I" forms and capitals after . ? !; text that
    already has capitals only gets its first letter raised. Never used for counting or comparison."""
    s = text if isinstance(text, str) else ""
    if not s:
        return s
    cased = any(c.isupper() for c in s)
    if not cased:
        s = re.sub(r"\bi\b", "I", s)
        s = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    k = next((p for p, c in enumerate(s) if c.isalpha()), -1)
    if k >= 0 and s[k].islower():
        s = s[:k] + s[k].upper() + s[k + 1:]
    return s


def status_of(marks, model_verdict) -> str:
    """ok | natural | fix | unsure | skip. `fix` needs >= 1 sure error mark; only-likely errors -> unsure (shown softly, not counted);
    natural / polish tips only -> natural; `ok` ONLY on the model's own verdict `ok` (a rule check never certifies clean); a model that
    said `skip` wins; no model verdict at all (AI down) -> unsure unless a sure error was found."""
    v = str(model_verdict or "").strip().lower()
    if v == "skip":
        return "skip"
    ms = list(marks or ())
    errs = [m for m in ms if m.severity == "error"]
    if any(m.conf == "sure" for m in errs):
        return "fix"
    if errs:
        return "unsure"
    if v in ("ok", "natural"):
        return "natural" if v == "natural" or any(m.severity in ("natural", "polish") for m in ms) else "ok"
    return "unsure"


_LEVEL_CAPS = {  # level -> (per sentence, per turn, natural per scope, polish per scope)
    "A1": (1, 2, 0, 0), "A2": (2, 3, 0, 0), "B1": (2, 4, 1, 0), "B2": (3, 5, 2, 1),
}


def display_cap(marks, level, per="sentence") -> list[Mark]:
    """The marks to SHOW at this level (display only; counting never uses this). A1: errors of weight >= 2, 1 per sentence / 2 per turn, no
    tips; A2: errors, 2 / 3; B1: errors + natural tips (<= 1), 2 / 4; B2+: 3 / 5 with natural <= 2 and polish <= 1. Highest prio first,
    returned in the input order."""
    lv = norm_level(level)
    cap_s, cap_t, nat_cap, pol_cap = _LEVEL_CAPS[lv]
    cap = cap_t if per == "turn" else cap_s
    ranked = sorted(enumerate(marks or ()), key=lambda p: (-prio(p[1]), p[0]))
    kept: list[tuple[int, Mark]] = []
    nat = pol = 0
    for idx, m in ranked:
        if len(kept) >= cap:
            break
        if m.severity == "error":
            if lv == "A1" and m.weight < 2:
                continue
        elif m.severity == "natural":
            if nat >= nat_cap:
                continue
            nat += 1
        else:
            if pol >= pol_cap:
                continue
            pol += 1
        kept.append((idx, m))
    kept.sort(key=lambda p: p[0])
    return [m for _, m in kept]


# --------------------------------------------------------------------------------------------- check_smooth (v1.1 helper)
_STOP = frozenset("""a an the and or but so if then than that this these those i me my mine we us our you your he him his she her it its they them their
am is are was were be been being have has had do does did will would can could shall should may might must to of in on at for from by with about as
into over after before up down out off not no yes just very really also too there here what when where who which how why all some any each every
more most much many such own same other another only even still again ever never always often um uh er like okay ok well""".split())
_NEG = frozenset({"not", "no", "never", "cannot", "nothing", "nobody", "neither", "nor", "none", "nowhere", "hardly", "without"})


def _stem(w: str) -> str:
    """A crude, consistent stemmer (vegetables / vegetable, liked / likes / liking share a stem); only used to compare two versions."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    for suf in ("ing", "ed", "ly"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


_LEMMA: dict[str, str] = {}
for _b, _p, _pp in _IRREG:
    for _f in (_p, _pp):
        if _f != _b:
            _LEMMA.setdefault(_f, _b)


def _content_stems(ks: list[str]) -> list[str]:
    ls = [_LEMMA.get(k, k) for k in _expand(ks) if k not in _STOP and not k[:1].isdigit() and k not in FILLERS]
    return [_stem(k) for k in ls if len(k) >= 3]


def _negs(ks: list[str]) -> int:
    return sum(1 for k in _expand(canon_contractions(ks)) if k in _NEG or k.endswith("n't"))


def _cased_midsentence(text: str) -> set[str]:
    out = set()
    for t in tokenize(text):
        if t.raw[:1].isupper() and t.raw not in ("I",) and not re.fullmatch(r"I'(?:m|ve|ll|d)", t.raw):
            before = text[:t.start].rstrip()
            if before and before[-1] not in ".!?":
                out.add(t.key)
    return out


def check_smooth(original_turn, smooth, *, corrected=None, level="B1", has_fix=False, recheck=None) -> bool:
    """May this 'smoother way to say it' be shown? (v1.1 helper.) 0.6-1.3x the words and <= original + 12; every digit / mid-sentence
    capitalised token of the new text occurs in the original; equal negation count; content-stem recall >= 0.70 and new-content share
    <= 0.25; no solo rule-check hit; not identical to the corrected (or the original) sentence; the turn has a fix or the level is B2+."""
    if not isinstance(original_turn, str) or not isinstance(smooth, str) or not original_turn.strip() or not smooth.strip():
        return False
    if not (has_fix or level_rank(level) >= 3):
        return False
    ok_ = [t.key for t in tokenize(original_turn)]
    sk_ = [t.key for t in tokenize(smooth)]
    if not ok_ or not sk_:
        return False
    if not 0.6 <= len(sk_) / len(ok_) <= 1.3 or len(sk_) > len(ok_) + 12:
        return False
    oset = set(ok_)
    if any(k[:1].isdigit() and k not in oset for k in sk_):
        return False
    if not _cased_midsentence(smooth) <= oset:
        return False
    if _negs(ok_) != _negs(sk_):
        return False
    a, b = _content_stems(ok_), _content_stems(sk_)
    sa, sb = set(a), set(b)
    if a and sum(1 for s in a if s in sb) / len(a) < 0.70:
        return False
    if b and sum(1 for s in b if s not in sa) / len(b) > 0.25:
        return False
    canon = lambda ks: tuple(_dedupe_runs(_numerals(canon_contractions(ks))))     # noqa: E731
    if canon(sk_) == canon(ok_):
        return False
    if corrected is not None and canon(sk_) == canon([t.key for t in tokenize(corrected)]):
        return False
    if recheck is not None:
        try:
            if any(getattr(h, "solo", True) for h in recheck(smooth)):
                return False
        except Exception:
            return False
    else:
        try:                                                      # the default floor: the rule checks, if they are importable
            det = importlib.import_module(".detectors", package=__package__)
            sks = canon_contractions(sk_)
            found = det.run_all(sks, source="chrome", has_q="?" in smooth, opaque=frozenset())
        except Exception:
            found = []
        if any(getattr(h, "solo", False) for h in found):
            return False
    return True


__all__ = ["verify_marks", "marks_from_hits", "build_corrected", "display_case", "status_of", "display_cap", "check_smooth",
           "is_artifact_only", "prio"]
