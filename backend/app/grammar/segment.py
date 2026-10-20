"""Sentence segmentation of learner speech (pure; plan Appendix A2).

Two kinds of input arrive: PUNCTUATED text (Whisper / Gemini transcripts) and UNPUNCTUATED text (Web Speech: one frame is one breath, often a
whole paragraph with no full stop). So:

  1. clean (text.clean_input, which slices FIRST - everything after is bounded);
  2. split at terminals  [.!?]+ closers whitespace Capital|digit|quote  unless a veto applies (abbreviations, initials, list numbers,
     '...' after fewer than 4 words; decimals, times and URLs have no whitespace inside, so they never split - a URL's LAST dot before a space does end a sentence);
  3. a chunk of <= 22 CORE words is ONE sentence (the common Chrome case, even with no punctuation at all);
  4. a longer chunk is cut at the best candidate nearest 14 words (pause / segment end / ';' / '...', then connectors), widening to 30, else a
     forced cut at 25; pieces under 5 words merge back; an "and then" chain under 22 words is never split (it is a flow signal, not a bug).

Invariant (property-tested, and re-checked on every call - a violation falls back to ONE chunk): the token keys of the pieces re-joined equal the
token keys of the cleaned input, offsets are monotonic and every piece is an exact slice of the cleaned text. A wrong boundary therefore only
changes counts; it can never rewrite what the learner said.

Every scan is linear: no regex with nested quantifiers, terminal runs are walked by hand (a regex over "....." backtracks quadratically), and
look-backs are bounded.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict

from .. import practice
from .lexicon_lang import (ABBREV_NEEDS_DIGIT, ABBREVIATIONS, CUT_CONNECTORS, CUT_CONNECTORS_PRON, DISCOURSE_LEAD, DISCOURSE_LEAD_PHRASES,
                           DISCOURSE_TRAIL, DISCOURSE_TRAIL_PHRASES, SUBJECT_PRONOUNS)
from .text import _TOKEN, MAX_CHARS, clean_input, tokenize
from .types import Hints, Sent

PAUSE_MIN = practice.PAUSE_MIN            # 0.7 s
LONG_WORDS = 22                           # a chunk up to this many core words is one sentence
IDEAL = 14
WIN_LO = 8
WIN_HI = 22
WIN_WIDE = 30
FORCE_AT = 25
MERGE_UNDER = 5
MAX_ANCHORS = 40
MIN_PAUSE_KEPT = 0.25                     # align_hints keeps gaps from here up

_TERM = re.compile(r"[.!?।॥]")
_TERMCH = frozenset(".!?।॥")
_CLOSERS = frozenset("\"')]")
_OPENERS = frozenset("\"'([")
_SOURCES = ("chrome", "whisper", "gemini")


def _scan(clean: str):
    """(starts, ends, keys) of the tokens of `clean` - the same tokens as text.tokenize, without a Tok object per token (this runs on every call)."""
    starts: list[int] = []
    ends: list[int] = []
    ks: list[str] = []
    for m in _TOKEN.finditer(clean):
        starts.append(m.start())
        ends.append(m.end())
        ks.append(m.group(0).casefold())
    return starts, ends, ks


# ----------------------------------------------------------------------------- core words
def core_range(ks: list[str], a: int, b: int) -> tuple[int, int]:
    """Token range [a, b) minus up to 3 leading discourse units (um, uh, so, okay, well, like, you know, i mean, and, but, then ...) and up to 2
    trailing ones (you know, right, okay). What is left is what the learner actually SAID; only those words are counted and judged."""
    n = 0
    while n < 3 and a < b:
        if a + 1 < b and (ks[a], ks[a + 1]) in DISCOURSE_LEAD_PHRASES:
            a += 2
        elif ks[a] in DISCOURSE_LEAD:
            a += 1
        else:
            break
        n += 1
    t = 0
    while t < 2 and b > a:
        if b - 2 >= a and (ks[b - 2], ks[b - 1]) in DISCOURSE_TRAIL_PHRASES:
            b -= 2
        elif ks[b - 1] in DISCOURSE_TRAIL:
            b -= 1
        else:
            break
        t += 1
    return a, b


def core_count(ks: list[str], a: int, b: int) -> int:
    ca, cb = core_range(ks, a, b)
    return max(0, cb - ca)


# ----------------------------------------------------------------------------- terminals
def _starter(c: str) -> bool:
    """May this character open a new sentence? Capital, digit, quote / bracket, or a caseless letter (Devanagari ...)."""
    if c.isupper() or c.isdigit() or c in _OPENERS:
        return True
    return c.isalpha() and not c.islower()


def _prev_word(clean: str, p: int) -> str:
    """The whitespace-delimited word just before position p, lowercased, leading brackets / quotes dropped. Bounded look-back (40 chars)."""
    b = p
    lim = max(0, p - 40)
    while b > lim and not clean[b - 1].isspace():
        b -= 1
    w = clean[b:p].lower()
    i = 0
    while i < len(w) and not w[i].isalnum():
        i += 1
    return w[i:]


def _is_veto(clean: str, p: int, q: int, s: int, tstarts: list[int], last: int) -> bool:
    """Is the terminal run clean[p:q] (next sentence would start at s) NOT a sentence end?"""
    run = clean[p:q]
    if len(run) >= 2 and set(run) == {"."}:                      # '..' / '...' : a hesitation unless it follows a real stretch of speech
        return bisect_left(tstarts, p) - bisect_left(tstarts, last) < 4
    if run != ".":
        return False                                             # '?' '!' '?!' danda are never abbreviations
    w = _prev_word(clean, p)
    if not w:
        return False
    if "." in w:
        parts = w.split(".")
        if all(len(x) == 1 and x.isalpha() for x in parts if x != ""):    # e.g. a.m  p.m  u.s  i.e
            return True
    if w in ABBREVIATIONS:
        if w in ABBREV_NEEDS_DIGIT:
            return s < len(clean) and clean[s].isdigit()
        return True
    if len(w) == 1 and w.isalpha() and w != "i":                # an initial: "J. K. Rowling"  (a capital "I" does end sentences)
        return True
    if w.isdigit() and len(w) <= 2:                              # a list marker: "1. First ..."
        return True
    return False


def _terminal_cuts(clean: str, tstarts: list[int]) -> list[tuple[int, int]]:
    """[(chunk_end, next_chunk_start)] for every accepted terminal boundary. One linear walk."""
    n = len(clean)
    cuts: list[tuple[int, int]] = []
    pos = 0
    last = 0
    for m in _TERM.finditer(clean):
        p = m.start()
        if p < pos:
            continue
        q = p
        while q < n and clean[q] in _TERMCH:
            q += 1
        r = q
        while r < n and clean[r] in _CLOSERS:
            r += 1
        pos = r
        if r >= n or not clean[r].isspace():
            continue
        s = r
        while s < n and clean[s].isspace():
            s += 1
        if s >= n or not _starter(clean[s]):
            continue
        if _is_veto(clean, p, q, s, tstarts, last):
            continue
        cuts.append((r, s))
        last = s
    return cuts


def _ends_with_terminal(chunk: str) -> bool:
    i = len(chunk)
    while i > 0 and chunk[i - 1] in _CLOSERS:
        i -= 1
    if i == 0 or chunk[i - 1] not in _TERMCH:
        return False
    j = i
    while j > 0 and chunk[j - 1] == ".":
        j -= 1
    return not (i - j >= 2)                                       # a trailing '...' is a cut-off, not a sentence end


# ----------------------------------------------------------------------------- long chunks
def _candidates(clean, ts, te, ks, cur, b, ca, cb, hints, model_idx):
    """Cut candidates (token index k = first token of the NEW piece) for the window after core start `ca`.
    Returns four lists of (k, left_count): p1, p2, model."""
    p1: list[tuple[int, int]] = []
    p2: list[tuple[int, int]] = []
    pm: list[tuple[int, int]] = []
    pause = hints.pause_after if hints is not None else {}
    segend = hints.seg_end if hints is not None else frozenset()
    hi = min(ca + WIN_WIDE, cb - 1)
    for k in range(max(ca + WIN_LO, cur + 1), hi + 1):
        left = k - ca
        gap = clean[te[k - 1]:ts[k]]
        if (pause.get(k - 1, 0) >= PAUSE_MIN) or ((k - 1) in segend) or (";" in gap) or ("..." in gap):
            p1.append((k, left))
        key = ks[k]
        nxt = ks[k + 1] if k + 1 < len(ks) else ""
        if key in CUT_CONNECTORS and left >= 6:
            if key == "then" and ks[k - 1] in ("and", "but", "so") and k - 1 > cur and left - 1 >= 6:
                p2.append((k - 1, left - 1))                      # keep "and then" together: cut BEFORE the "and"
            else:
                p2.append((k, left))
        elif key in CUT_CONNECTORS_PRON and nxt in SUBJECT_PRONOUNS and left >= 8:
            p2.append((k, left))
        if k in model_idx:
            pm.append((k, left))
    return p1, p2, pm


def _best(cands, lo, hi):
    c = [x for x in cands if lo <= x[1] <= hi]
    if not c:
        return None
    return min(c, key=lambda x: (abs(x[1] - IDEAL), x[1]))[0]


def _split_long(clean, ts, te, ks, a, b, hints, model_idx):
    """Token range [a, b) of one terminal chunk -> [(piece_a, piece_b, src_of_the_cut_that_ends_it | None)]."""
    pieces: list[list] = []
    cur = a
    while True:
        ca, cb = core_range(ks, cur, b)
        if cb - ca <= LONG_WORDS:
            break
        p1, p2, pm = _candidates(clean, ts, te, ks, cur, b, ca, cb, hints, model_idx)
        k = src = None
        for cands, lo, hi, name in ((p1, WIN_LO, WIN_HI, "pause"), (p2, WIN_LO, WIN_HI, "connector"), (p1, WIN_LO, WIN_WIDE, "pause"),
                                    (p2, WIN_LO, WIN_WIDE, "connector"), (pm, WIN_LO, WIN_WIDE, "model")):
            k = _best(cands, lo, hi)
            if k is not None:
                src = name
                break
        if k is None:
            k = ca + FORCE_AT
            src = "forced"
            if k >= cb:                                           # 23-25 words and nothing to cut at: leave it whole
                break
        if k <= cur or k >= b:
            break
        pieces.append([cur, k, src])
        cur = k
    pieces.append([cur, b, None])
    # tiny pieces merge back (into the previous one, the first into the next)
    i = 0
    while len(pieces) > 1 and i < len(pieces):
        pa, pb, _ = pieces[i]
        if core_count(ks, pa, pb) < MERGE_UNDER:
            if i > 0:
                pieces[i - 1][1] = pb
                pieces[i - 1][2] = pieces[i][2]
                del pieces[i]
                i = max(0, i - 1)
                continue
            pieces[1][0] = pa
            del pieces[0]
            continue
        i += 1
    return pieces


# ----------------------------------------------------------------------------- the public segmenter
def _norm_conf(conf):
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return None
    return c if math.isfinite(c) else None


def _build(clean, ts, te, ks, turn, source, conf, hints, model_idx):
    tstarts = ts
    bounds = _terminal_cuts(clean, tstarts)
    chunks: list[tuple[int, int, bool]] = []
    cs = 0
    for ce, ns in bounds:
        chunks.append((cs, ce, True))
        cs = ns
    final = clean[cs:]
    chunks.append((cs, len(clean), _ends_with_terminal(final)))
    any_term = bool(bounds) or chunks[-1][2]
    out: list[Sent] = []
    k = 0
    for cs, ce, punct in chunks:
        a, b = bisect_left(tstarts, cs), bisect_left(tstarts, ce)
        if b <= a:
            continue
        chunk_src = "terminal" if any_term else "whole"
        pieces = _split_long(clean, ts, te, ks, a, b, hints, model_idx) if core_count(ks, a, b) > LONG_WORDS else [[a, b, None]]
        cur_start = cs
        for idx, (pa, pb, src) in enumerate(pieces):
            last = idx == len(pieces) - 1
            if last:
                end = ce
            else:
                g0 = te[pb - 1]
                g1 = ts[pb]
                i = g0
                while i < g1 and clean[i] != " ":
                    i += 1
                end = i
            text = clean[cur_start:end]
            if text and text.strip():
                forced = src == "forced" or (idx > 0 and pieces[idx - 1][2] == "forced")
                out.append(Sent(sid=f"{turn}:{k}", turn=turn, text=text, start=cur_start, end=end, n_words=core_count(ks, pa, pb),
                                punct=bool(punct and last), src=(src or chunk_src), forced=forced, conf=conf, source=source))
                k += 1
            if not last:
                nxt = end + 1 if end < len(clean) and clean[end] == " " else end
                cur_start = max(nxt, end)
    return out


def segment(text, *, turn: int = 0, source: str = "chrome", conf=None, hints: Hints | None = None, limit: int = MAX_CHARS,
            cuts=None) -> list[Sent]:
    """One learner turn -> sentences (slices of the cleaned turn). Never raises. `cuts` = optional char offsets from `apply_starts` (the model's
    help for a long unpunctuated chunk with no candidate); they are only ever used as cut positions between tokens."""
    try:
        clean = clean_input(text, limit)
    except Exception:
        return []
    if not clean:
        return []
    source = source if source in _SOURCES else "chrome"
    conf = _norm_conf(conf)
    try:
        ts, te, ks = _scan(clean)
        if not ks:
            return []
        model_idx: set[int] = set()
        if cuts:
            by_start = {st: i for i, st in enumerate(ts)}
            for c in list(cuts)[:200]:
                if isinstance(c, int) and c in by_start and by_start[c] > 0:
                    model_idx.add(by_start[c])
        out = _build(clean, ts, te, ks, int(turn), source, conf, hints, model_idx)
        if out and invariant_ok(clean, out):
            return out
    except Exception:
        pass
    return _single(clean, int(turn), source, conf)


def _single(clean: str, turn: int, source: str, conf) -> list[Sent]:
    """The safe fallback: the whole cleaned turn as one sentence."""
    try:
        ks = _scan(clean)[2]
        if not ks:
            return []
        return [Sent(sid=f"{turn}:0", turn=turn, text=clean, start=0, end=len(clean), n_words=core_count(ks, 0, len(ks)), punct=False, src="whole",
                     forced=False, conf=conf, source=source)]
    except Exception:
        return []


def invariant_ok(clean: str, sents: list[Sent]) -> bool:
    """The token keys of the pieces re-joined equal the token keys of the cleaned input; offsets are monotonic; every piece is an exact slice."""
    try:
        want = [m.casefold() for m in _TOKEN.findall(clean)]          # keys only (no Tok objects): this runs on every call
        got: list[str] = []
        prev_end = 0
        for s in sents:
            if not (0 <= s.start < s.end <= len(clean)) or s.start < prev_end:
                return False
            if clean[s.start:s.end] != s.text:
                return False
            got.extend(m.casefold() for m in _TOKEN.findall(s.text))
            prev_end = s.end
        return got == want
    except Exception:
        return False


# ----------------------------------------------------------------------------- the model's help: anchors -> offsets
def apply_starts(text, starts) -> list[int]:
    """Anchors (2-4-word phrases, the first words of sentences 2..k as the model saw them) -> char offsets in the CLEANED text, located
    token-wise (case / punctuation-insensitive, first occurrence after the previous anchor). Misses are ignored; the result is strictly
    increasing and never contains 0. Cuts only ever fall between tokens, so applying them cannot change what was said."""
    clean = clean_input(text)
    toks = tokenize(clean)
    if not toks or not isinstance(starts, (list, tuple)):
        return []
    ks = [t.key for t in toks]
    pos = defaultdict(list)
    for i, k in enumerate(ks):
        pos[k].append(i)
    out: list[int] = []
    from_idx = 1
    for anchor in list(starts)[:MAX_ANCHORS]:
        ak = [t.key for t in tokenize(clean_input(str(anchor or ""), 200))]
        if not 2 <= len(ak) <= 4:
            continue
        cands = pos.get(ak[0])
        if not cands:
            continue
        j = bisect_left(cands, from_idx)
        found = None
        while j < len(cands):
            i = cands[j]
            if ks[i:i + len(ak)] == ak:
                found = i
                break
            j += 1
        if found is None:
            continue
        out.append(toks[found].start)
        from_idx = found + 1
    return out


# ----------------------------------------------------------------------------- Whisper hints
def _rows(words):
    out = []
    if not isinstance(words, (list, tuple)):
        return out
    for item in list(words)[:practice.MAX_WORDS]:
        try:
            if isinstance(item, dict):
                w, s, e = item.get("w"), item.get("s"), item.get("e")
            else:
                w, s, e = item[0], item[1], item[2]
            s, e = float(s), float(e)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not math.isfinite(s) or not math.isfinite(e) or e < s:
            continue
        out.append((str(w or ""), s, e))
    return out


def align_hints(clean: str, words, segments=None) -> Hints | None:
    """Align Whisper [word, start, end] rows to the token keys of the cleaned transcript. Greedy with a small look-ahead so one dropped or
    split word does not derail it. Below a 0.9 match rate (or no overlap at all) the timings are not trusted: None.
    Hints.pause_after: token index -> seconds of silence AFTER that token (gaps >= 0.25 s kept); Hints.seg_end: token indexes that end a
    Whisper segment (`segments` rows are [start, end, ...] seconds)."""
    toks = tokenize(clean_input(clean))
    rows = _rows(words)
    if not toks or not rows:
        return None
    ks = [t.key for t in toks]
    # flatten the words into token keys, each carrying its word's times
    wk: list[tuple[str, float, float]] = []
    for w, s, e in rows:
        for t in tokenize(clean_input(w, 80)):
            wk.append((t.key, s, e))
    if not wk:
        return None
    LOOK = 6
    ti = wi = matched = 0
    time_of: dict[int, tuple[float, float]] = {}
    while ti < len(ks) and wi < len(wk):
        if ks[ti] == wk[wi][0]:
            time_of[ti] = (wk[wi][1], wk[wi][2])
            matched += 1
            ti += 1
            wi += 1
            continue
        # resync: a dropped / extra word on either side within the look-ahead
        hit = None
        for d in range(1, LOOK + 1):
            if wi + d < len(wk) and ks[ti] == wk[wi + d][0]:
                hit = (0, d)
                break
            if ti + d < len(ks) and ks[ti + d] == wk[wi][0]:
                hit = (d, 0)
                break
        if hit is None:
            ti += 1
            wi += 1
        else:
            ti += hit[0]
            wi += hit[1]
    if matched / len(ks) < 0.9:
        return None
    pause: dict[int, float] = {}
    for i in range(len(ks) - 1):
        a, b = time_of.get(i), time_of.get(i + 1)
        if a is None or b is None:
            continue
        gap = b[0] - a[1]
        if gap >= MIN_PAUSE_KEPT:
            pause[i] = round(gap, 3)
    seg_end: set[int] = set()
    if isinstance(segments, (list, tuple)):
        ends = sorted((t[1], i) for i, t in time_of.items())
        end_times = [x[0] for x in ends]
        for row in list(segments)[:2000]:
            try:
                e = float(row.get("end") if isinstance(row, dict) else row[1])
            except (TypeError, ValueError, IndexError, KeyError, AttributeError):
                continue
            if not math.isfinite(e):
                continue
            j = bisect_right(end_times, e + 0.15) - 1            # the last token that ends at or before the segment end (+ a little slack)
            best = ends[j][1] if j >= 0 else None
            if best is not None and best < len(ks) - 1:
                seg_end.add(best)
    return Hints(pause_after=pause, seg_end=frozenset(seg_end))
