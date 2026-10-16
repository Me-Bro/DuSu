"""Shared plain data types for the pure Grammar Coach modules (no behaviour here)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sent:
    """One sentence cut out of a learner turn. `text` is a slice of the cleaned turn (never rewritten)."""
    sid: str                    # "<turn>:<k>"
    turn: int
    text: str
    start: int                  # char offsets in the cleaned turn
    end: int
    n_words: int                # CORE words (leading / trailing discourse tokens not counted)
    punct: bool                 # the source had terminal punctuation here (a boundary we can trust)
    src: str = "terminal"       # terminal | whole | pause | connector | forced | model
    forced: bool = False
    conf: float | None = None   # recogniser confidence of the turn (None / 0 = unknown)
    source: str = "chrome"      # chrome | whisper | gemini


@dataclass(frozen=True)
class Gate:
    ok: bool
    reason: str = ""            # too_short | not_a_sentence | unintelligible | not_english | session reasons


@dataclass(frozen=True)
class Hints:
    pause_after: dict = field(default_factory=dict)     # token index -> seconds of silence after it
    seg_end: frozenset = frozenset()                    # token indexes that end a Whisper segment


@dataclass(frozen=True)
class Hit:
    """A rule check fired on a sentence's token keys: tokens [i, j) should become `fix` (an empty tuple = delete them)."""
    rule: str                   # catalogue id (T3: "ind.lexicon#prepone")
    i: int
    j: int
    fix: tuple = ()
    det: str = ""               # D1..D16 | T1..T3
    solo: bool = False          # may create a mark without the model


@dataclass
class Mark:
    """A verified finding on one sentence (verify.py builds these; the corrected sentence is built from them by code)."""
    rule: str
    i: int                      # token range [i, j) in the sentence's tokens
    j: int
    start: int                  # char range in the sentence text
    end: int
    quote: str
    fix: str
    conf: str = "likely"        # sure | likely
    severity: str = "error"     # error | natural | polish (from the catalogue)
    weight: int = 2
    family: str = ""
    why: str = ""               # the model's optional note, <= 14 words, only if it passed the checks
    src: str = "model"          # model | rule | both
    det: str = ""
