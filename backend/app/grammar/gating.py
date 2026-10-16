"""The language gates (pure; plan Appendix A1).

Grammar is judged only on English the learner actually spoke. Three things decide that, from coarse to fine:
  session_gate   which modes / languages the engine is allowed to see at all (a registry, like lang.SWITCHABLE);
  sentence_gate  one sentence at a time: too short, not a sentence, unintelligible, or not English -> skipped with a REASON (never judged,
                 never counted as "no mistake found", reported in the tally);
  opaque_indices tokens that are never flaggable inside an English sentence (Devanagari, Hinglish words, Indian loanwords and names, the
                 learner's own name, mid-sentence capitals of a cased text).

Order inside sentence_gate: too_short, not_a_sentence, the two text-only unintelligible tests that need no language knowledge (a Whisper silence
hallucination, a low recogniser confidence), then not_english (script / Roman Hinglish), then the statistical unintelligible tests (one-letter
tokens, "Hindi heard as English": long and almost free of English function words). not_english runs BEFORE the statistical tests on purpose:
Devanagari is split into one-letter tokens by the tokenizer and Roman Hinglish has few English stop words, so both would otherwise be
mislabelled "unintelligible" and the session-level `lang_mix` (>= 50% not_english) could never fire.
"""

from __future__ import annotations

from .. import practice
from .lexicon_lang import ENGLISH_STOP, HALLU_TOKENS, HINGLISH_STOP, LOANWORDS, NUMBER_WORDS
from .text import Tok, tokenize
from .types import Gate, Sent

_OK = Gate(True, "")

MIN_CONF = 0.45
DEV_SHARE = 0.30
HINGLISH_SHARE = 0.20
HINGLISH_SHARE_LOW = 0.10
HINGLISH_EN_MAX = 0.25
ONE_LETTER_SHARE = 0.40
SALAD_MIN_TOKENS = 6
SALAD_EN_MAX = 0.12
LANG_MIX_UNITS = 6
LANG_MIX_SHARE = 0.5

# ----------------------------------------------------------------------------- session gate
_ENGLISH_ALWAYS_OK = ("resume_interview", "job_interview")
_SESSION_OK_EN = ("conversation", "interview")
_SESSION_NEVER = ("daily", "learning", "home")


def _norm_lang(v) -> str:
    s = str(v or "").strip().lower()
    return "en" if s in ("en", "english", "en-us", "en-in", "en-gb") else s


def session_gate(mode, plang=None, lang="en") -> Gate:
    """May the engine see this session at all? Daily Talk (Hindi), Learn, Home and Practice in Hindi / Hinglish are never checked."""
    m = str(mode or "").strip().lower()
    if m in _ENGLISH_ALWAYS_OK:
        return _OK
    if m in _SESSION_OK_EN:
        return _OK if _norm_lang(lang) == "en" else Gate(False, "language")
    if m == "practice":
        return _OK if _norm_lang(plang) == "en" else Gate(False, "language")
    return Gate(False, "mode")


# ----------------------------------------------------------------------------- helpers
def _is_dev(c: str) -> bool:
    return "ऀ" <= c <= "ॿ"


def _letters(text: str) -> tuple[int, int]:
    """(devanagari characters, other letters). Matras and viramas are not alphabetic, so count the whole Devanagari block."""
    dev = oth = 0
    for c in text:
        if _is_dev(c):
            dev += 1
        elif c.isalpha():
            oth += 1
    return dev, oth


def _one_letter(key: str) -> bool:
    return len(key) == 1 and key.isalpha() and key.isascii() and key not in ("a", "i")


def _hallucination(text: str) -> bool:
    """Whisper invents 'Thank you.' / 'Thanks for watching' on silence. Local copy of resume_interview.rules.is_hallucination's TEXT logic
    (a few filler tokens, or one phrase repeated); its recogniser-doubt branch needs segment numbers, which a sentence does not carry."""
    toks = practice.norm(text).split()
    if not toks:
        return True
    if len(toks) <= 8 and all(t in HALLU_TOKENS for t in toks):
        return True
    if len(toks) >= 6 and len(set(toks)) / len(toks) < 0.3:
        return True
    return False


def is_cased(toks) -> bool:
    """Does capitalisation carry information? False for all-lowercase text only in the sense that nothing is capitalised mid-sentence (then
    there is nothing to protect); False too when nearly EVERY word is capitalised (Title Case / shouting), where a capital proves nothing."""
    alpha = [t for i, t in enumerate(toks) if i > 0 and _raw(t)[:1].isalpha()]
    if len(alpha) < 4:
        return True
    cap = sum(1 for t in alpha if _raw(t)[:1].isupper())
    return cap / len(alpha) < 0.5


def _raw(t) -> str:
    return t.raw if isinstance(t, Tok) else str(t)


def _key(t) -> str:
    return t.key if isinstance(t, Tok) else str(t).casefold()


# ----------------------------------------------------------------------------- sentence gate
def sentence_gate(sent: Sent, *, name: str = "") -> Gate:
    """Is this sentence English that can be judged? The first rule that fires wins."""
    text = sent.text or ""
    toks = tokenize(text)
    n = len(toks)
    keys = [t.key for t in toks]
    # 1. too_short: two core words or fewer say nothing to judge (um uh, yes sir, okay)
    if sent.n_words <= 2 or n == 0:
        return Gate(False, "too_short")
    # 2. not_a_sentence: spelled letters, only digits / number words, one repeated token
    single = sum(1 for k in keys if len(k) == 1 and k.isalpha() and k.isascii() and k not in ("a", "i"))
    if n >= 3 and single / n >= 0.6:
        return Gate(False, "not_a_sentence")
    if n >= 3 and all(k[0].isdigit() or k in NUMBER_WORDS for k in keys):
        return Gate(False, "not_a_sentence")
    if n >= 3 and len(set(keys)) == 1:
        return Gate(False, "not_a_sentence")
    # 3a. unintelligible, text-only: the recogniser's silence hallucination; a recogniser that doubts itself (0 / None = unknown)
    if _hallucination(text):
        return Gate(False, "unintelligible")
    conf = sent.conf
    if conf is not None and 0 < conf < MIN_CONF:
        return Gate(False, "unintelligible")
    # 4. not_english: script, then Roman Hinglish
    dev, oth = _letters(text)
    if dev + oth > 0 and dev / (dev + oth) >= DEV_SHARE:
        return Gate(False, "not_english")
    own = {t.key for t in tokenize(str(name or "")[:120])}          # the learner's own name is neutral (a person called Kal is not speaking Hindi)
    hing = sum(1 for k in keys if k in HINGLISH_STOP and k not in own) / n
    eng = sum(1 for k in keys if k in ENGLISH_STOP) / n
    if hing >= HINGLISH_SHARE or (hing >= HINGLISH_SHARE_LOW and eng < HINGLISH_EN_MAX):
        return Gate(False, "not_english")
    # 3b. unintelligible, statistical: many one-letter tokens; "Hindi heard as English" (long, almost no English function words)
    if sum(1 for k in keys if _one_letter(k)) / n >= ONE_LETTER_SHARE:
        return Gate(False, "unintelligible")
    if n >= SALAD_MIN_TOKENS and eng < SALAD_EN_MAX:
        return Gate(False, "unintelligible")
    return _OK


# ----------------------------------------------------------------------------- opaque tokens
def opaque_indices(toks, *, name: str = "", cased: bool = False) -> set[int]:
    """Indexes of tokens that must never be flagged (and any mark touching one is dropped): Devanagari, Hinglish-list words, loanwords / Indian
    names, a run of 3+ single letters (a spelled name), the learner's own name, and - when the text is `cased` - mid-sentence capitalised
    tokens and ALL-CAPS acronyms. `toks` = text.tokenize output (or plain strings)."""
    out: set[int] = set()
    name_keys = {t.key for t in tokenize(str(name or "")[:120])}
    n = len(toks)
    run = 0
    for i, t in enumerate(toks):
        raw, key = _raw(t), _key(t)
        if any(_is_dev(c) for c in raw) or key in HINGLISH_STOP or key in LOANWORDS or key in name_keys:
            out.add(i)
        elif cased:
            if i > 0 and raw[:1].isupper() and not (key == "i" or key.startswith("i'")):
                out.add(i)
            elif len(raw) >= 2 and raw.isupper() and raw.isalpha():
                out.add(i)
        if len(key) == 1 and key.isalpha() and key.isascii():
            run += 1
        else:
            if run >= 3:
                out.update(range(i - run, i))
            run = 0
    if run >= 3:
        out.update(range(n - run, n))
    return out


# ----------------------------------------------------------------------------- session-level language mix
def lang_mix(gates) -> bool:
    """>= 50% of the first 6 units not_english -> the learner is speaking Hindi / Hinglish: English checks are paused (counts only)."""
    first = list(gates)[:LANG_MIX_UNITS]
    if not first:
        return False
    bad = sum(1 for g in first if getattr(g, "reason", g) == "not_english")
    return bad / len(first) >= LANG_MIX_SHARE
