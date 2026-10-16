"""Tokenizer and cleaning for learner speech (pure).

`practice.norm` turns apostrophes into spaces ("don't" -> "don t"): fine for comparisons and hashes, wrong for tokenising. This tokenizer keeps an
apostrophe INSIDE a word ("don't", "i'm", "o'clock") and lowercases a token's `key`. Every regex is linear and anchored on a character class
(no nested quantifiers), and callers slice their input to a bound BEFORE tokenising (see MAX_CHARS).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_CHARS = 30000                      # = practice.MAX_CHARS: never tokenise more than this

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BRACKET = re.compile(r"\[[^\[\]]{0,40}\]|\((?:laughs|laughter|music|applause|coughs|sighs)[^()]{0,20}\)", re.I)
_WS = re.compile(r"\s+")
# number (1,000 / 3.5 / 6.30) | word with optional apostrophe suffix (don't, o'clock, rahul's) | devanagari run
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_QUOTES = {"‘": "'", "’": "'", "‛": "'", "ʼ": "'", "“": '"', "”": '"', "…": "..."}

# the apostrophe-less spellings a recogniser sometimes writes -> the apostrophe form the rule checks match
_CONTRACT = {"dont": "don't", "doesnt": "doesn't", "didnt": "didn't", "cant": "can't", "wont": "won't", "isnt": "isn't", "arent": "aren't",
             "wasnt": "wasn't", "werent": "weren't", "havent": "haven't", "hasnt": "hasn't", "hadnt": "hadn't", "shouldnt": "shouldn't",
             "couldnt": "couldn't", "wouldnt": "wouldn't", "im": "i'm", "ive": "i've", "youre": "you're", "theyre": "they're", "thats": "that's"}


@dataclass(frozen=True)
class Tok:
    raw: str          # the characters as written
    key: str          # casefolded, NFC, apostrophe kept ("don't")
    start: int        # char offsets in the cleaned text
    end: int


def clean_input(s, limit: int = MAX_CHARS) -> str:
    """Untrusted speech text -> one bounded, control-free, single-spaced string. Slices FIRST so every later pass is bounded."""
    s = str(s or "")[:limit]
    s = unicodedata.normalize("NFC", s)
    s = "".join(_QUOTES.get(c, c) for c in s) if any(c in _QUOTES for c in s) else s
    s = _CTRL.sub(" ", s)
    s = _BRACKET.sub(" ", s)
    return _WS.sub(" ", s).strip()


def tokenize(s: str) -> list[Tok]:
    out: list[Tok] = []
    for m in _TOKEN.finditer(s or ""):
        raw = m.group(0)
        out.append(Tok(raw, raw.casefold(), m.start(), m.end()))
    return out


def keys(s: str) -> list[str]:
    return [t.key for t in tokenize(s)]


def canon_contractions(ks: list[str]) -> list[str]:
    """`dont` -> `don't`, `im` -> `i'm` ... Applied to token keys before the rule checks match."""
    return [_CONTRACT.get(k, k) for k in ks]
