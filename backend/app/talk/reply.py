"""Talk - what one model reply becomes before a learner sees it (pure: no database, no network, no clock).

The model returns ONE JSON object per learner turn:

    {"reply": "<English, 1-2 short sentences, a question back>",
     "hi":    "<Hindi translation of reply>",                     # only asked for at support level `en_sub`
     "fix":   null | {"q": "<exact words from the learner's last message>", "f": "<the fix>", "r": "<reason, English>", "w": "<reason, Hindi>"}}

Nothing in it is trusted:
  * `reply` must be English (a Devanagari sentence is stripped; a reply with no English left is unusable) and is cleaned of markup and control characters;
  * `hi` is shown only if it is Hindi in Devanagari (with Latin everyday words) and follows the writing rules (तुम, never आप / तू; no verb that guesses the learner's gender) - otherwise it is
    dropped and the learner simply reads English (a missing subtitle is never worse than a wrong one);
  * `fix` is verified BY CODE with Grammar Coach's own machinery (`grammar/verify.py`): the quoted words must be found, whole, in the learner's message; the change must be a real, bounded
    edit (token edit distance, at most 8 words) and not just something a speech recogniser may have chosen differently (case, punctuation, numerals, contractions, repeats, fillers,
    homophones); a rule check that knows better (a veto) wins.  Whatever cannot be verified is DROPPED - never shown, never half-shown.  At most one fix per turn.
Only the verified English `reply` ever goes into the session transcript (memory, reconnect replay and summaries never see Hindi or JSON).
"""

from __future__ import annotations

import dataclasses
import re

from ..grammar import detectors, gating, verify
from ..grammar.text import canon_contractions, clean_input, tokenize
from . import topics as T

SCHEMA = {"reply": "str+"}               # what the validated walk enforces INSIDE the call (a reply without it is a failed attempt, the next model answers)
MAX_TOKENS = {"en_sub": 480, "en": 320}  # output budget per turn; Devanagari is token-heavy, so the subtitle level gets the bigger one (<= 500)
REPLY_MAX = 420
LEARNER_MAX = 500                        # the learner's own message, as the model sees it
HISTORY_LINES, HISTORY_CHARS = 8, 200    # the chat window in the prompt (with the system prompt this keeps a call under ~1.5K tokens)
HI_MAX = 700
REASON_MAX = 160
REASON_HI_MAX = 240
Q_MAX_CHARS = verify.MAX_Q_CHARS
VERIFY_LEVEL_FLOOR = "A2"                # see verify_fix: Talk's fix always carries its own reason, which is what Grammar Coach's "no unlabelled mark for a beginner" rule is for

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MARKUP = re.compile(r"[<>{}\[\]`*_#|\\]")
_WS = re.compile(r"\s+")
_DEV = re.compile(r"[ऀ-ॿ]")
_SENT = re.compile(r"(?<=[.?!।])\s+")


# ----------------------------------------------------------------------------------------------------------------- the walk's own rule for a usable reply
def check(d) -> str | None:
    """`check=` for llm.assess: a reason (<= 40 chars) when the reply field is not usable English.  The walk then asks the next model instead of showing the learner a Hindi line."""
    r = d.get("reply") if isinstance(d, dict) else None
    if not isinstance(r, str) or not r.strip():
        return "missing:reply"
    letters = len(re.findall(r"[A-Za-z]", r))
    if letters < 2 or T.dev_share(r) >= 0.5:
        return "not_english"
    return None


# ----------------------------------------------------------------------------------------------------------------- cleaning
def _flat(s) -> str:
    s = _CTRL.sub(" ", str(s or ""))
    s = _MARKUP.sub(" ", s)
    return _WS.sub(" ", s).strip().strip('"“”').strip()


def clean_reply(s) -> str:
    """The English line DuSu says: no markup, no control characters, no Devanagari sentence, at most REPLY_MAX characters (cut at a sentence end when there is one).  '' when nothing usable is left."""
    t = _flat(s)
    if not t:
        return ""
    if _DEV.search(t):
        t = " ".join(x for x in _SENT.split(t) if not _DEV.search(x)).strip()
    if len(re.findall(r"[A-Za-z]", t)) < 2:
        return ""
    if len(t) > REPLY_MAX:
        cut = t[:REPLY_MAX]
        k = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = cut[:k + 1] if k >= 40 else cut.rsplit(" ", 1)[0]
    return t.strip()


def clean_hi(s) -> str | None:
    """The Hindi subtitle, or None when it must not be shown: not Devanagari-led, too long, or it breaks a writing rule (आप / तू, a verb that guesses the learner's gender)."""
    t = _flat(s)
    if not t or len(t) > HI_MAX or not _DEV.search(t):
        return None
    if T.dev_share(t) < T.MIN_DEV_SHARE:
        return None
    if T.hindi_problems(t):
        return None
    return t


def _reason_en(s) -> str:
    t = _flat(s)
    if not t or _DEV.search(t) or len(t) > REASON_MAX:
        return ""
    return t


def _reason_hi(s) -> str:
    t = _flat(s)
    if not t or len(t) > REASON_HI_MAX or not _DEV.search(t) or T.dev_share(t) < T.MIN_DEV_SHARE or T.hindi_problems(t):
        return ""
    return t


def clean_name(s) -> str:
    """The learner's name as it goes into the prompt: no markup, no control characters, at most 40 characters."""
    return _flat(s)[:40]


def clean_note(s) -> str:
    return _flat(s)[:240]


def clean_learner(s) -> str:
    """The learner's words as the model sees them and as the transcript keeps them: control characters and bracketed recogniser annotations out, whitespace collapsed, at most 600
    characters (the same cleaning `verify_fix` applies, so a quote that matches one matches the other)."""
    return clean_input(s, LEARNER_MAX)


def learner_note(facts) -> str:
    """One short line about the learner from what DuSu remembers (profession, dream, interests) - at most 240 characters, never a name, never a number."""
    f = facts if isinstance(facts, dict) else {}
    bits = []
    for k, label in (("profession", "works as"), ("dream", "dream")):
        v = _flat(f.get(k))[:60]
        if v:
            bits.append(f"{label}: {v}")
    it = f.get("interests")
    vals = [str(k) for k in it.keys()] if isinstance(it, dict) else [str(x) for x in it] if isinstance(it, (list, tuple)) else []
    vals = [_flat(v)[:30] for v in vals[:5] if _flat(v)]
    if vals:
        bits.append("likes " + ", ".join(vals))
    return clean_note("; ".join(bits))


# ----------------------------------------------------------------------------------------------------------------- the fix, verified by code
# The words a GRAMMAR edit may change freely (helping verbs, articles, prepositions, pronouns, quantifiers); every other changed word must have a partner on the other side that is a
# form of the same word (an inflection - go / goes / going - or a known irregular pair - go / went / gone, a / an).  A swap of one content word for another (market -> bazaar) is a
# word-choice opinion, not a mistake, and is shown only when a rule check on the same words agrees.
_FREE = frozenset(verify.AUX | verify.ART | verify.PREP | verify.PRON | verify.QUANT)


def grammar_edit(q: str, f: str) -> bool:
    qk = canon_contractions([t.key for t in tokenize(q)])
    fk = canon_contractions([t.key for t in tokenize(f)])
    left, right = verify._changed(qk, fk)
    return bool(left or right) and verify._all_resolved(left, right, _FREE)


def _recheck(source: str):
    def f(t):
        return detectors.solo_hits(canon_contractions([k.key for k in tokenize(t)]), source=source, has_q=("?" in t))
    return f


def verify_fix(message: str, raw, *, level="", support: str = "en_sub", source: str = "chrome") -> dict | None:
    """The learner-facing fix, or None.  `raw` is what the model proposed (one dict, or a list of them - the first that verifies wins, so two fixes become one).

    The change is verified exactly as Grammar Coach verifies a mark (grammar/verify.verify_marks: locate whole tokens, bounds, not artifact-only, no rule-check veto, no opaque token
    touched).  The level floor is A2 because the `other` (unlabelled) mark that the model's free-form fix becomes is never shown to an A1 learner by Grammar Coach - there it has no
    explanation; here every fix carries its own reason, which is what that rule exists for.  The result is {"q","f","r","w"?,"c","full"?}: `q` is the learner's own words exactly as
    they wrote them, `f` the replacement (first-letter case follows the quote), `r` the English reason, `w` the Hindi reason (only at `en_sub`, only if it passed the writing rules), `c` is
    "sure" (a rule check on the same words agrees) or "likely", `full` the whole message with the fix applied, built by code - a fix whose corrected message fails the post-conditions
    (it would introduce a mistake the rule checks can see, grow the sentence too much, or invent a digit) is dropped, so `full` is always present."""
    msg = clean_input(message, LEARNER_MAX)
    if not msg or raw is None:
        return None
    cands = raw if isinstance(raw, (list, tuple)) else [raw]
    toks = tokenize(msg)
    if len(toks) < 2 or not any(t.key.isascii() and t.key[:1].isalpha() for t in toks):
        return None
    ks = canon_contractions([t.key for t in toks])
    opaque = gating.opaque_indices(toks, cased=(source != "chrome"))
    hits = detectors.run_all(ks, source=source, has_q=("?" in msg), opaque=opaque)
    vet = detectors.vetoes(ks)
    lvl = VERIFY_LEVEL_FLOOR if not level or verify.level_rank(level) < verify.level_rank(VERIFY_LEVEL_FLOOR) else str(level)
    for c in cands[:3]:
        if not isinstance(c, dict):
            continue
        q, f = c.get("q"), c.get("f")
        if not isinstance(q, str) or not isinstance(f, str) or not q.strip() or not f.strip() or len(q.strip()) > Q_MAX_CHARS:
            continue
        marks = verify.verify_marks(msg, [{"q": q, "f": f, "r": "", "c": "s", "w": ""}], level=lvl, source=source, hits=hits, vetoes=vet, opaque=opaque)
        m = next((x for x in marks if x.severity == "error"), None)
        if m is None:
            continue
        if m.conf != "sure" and not grammar_edit(m.quote, m.fix):
            continue                                   # a free word swap that no rule check backs: a style opinion, not a mistake - dropped
        # The corrected message is BUILT BY CODE from the verified edit, and its post-conditions are the last gate: the token count stays within [n-4, n+6], no digit is invented and - the
        # important one - the rule checks must not find a NEW mistake in it.  A model "fix" that would introduce an error ("made him to cry") fails here and is dropped.
        full = verify.build_corrected(msg, [dataclasses.replace(m, conf="sure")], recheck=_recheck(source))
        if not full:
            continue
        out = {"q": m.quote, "f": m.fix, "r": _reason_en(c.get("r")) or "A small grammar fix.", "c": m.conf, "full": full}
        if support == "en_sub":
            w = _reason_hi(c.get("w"))
            if w:
                out["w"] = w
        return out
    return None


# ----------------------------------------------------------------------------------------------------------------- the whole reply
def shape(data, message: str, *, support: str, level="", source: str = "chrome") -> dict | None:
    """One model object -> {"text", "hi"?, "fix"?} for the learner, or None when there is no usable English reply.  `message` is the learner's words this reply answers."""
    if not isinstance(data, dict) or data.get("error"):
        return None
    text = clean_reply(data.get("reply"))
    if not text:
        return None
    out: dict = {"text": text}
    if support == "en_sub":
        hi = clean_hi(data.get("hi"))
        if hi:
            out["hi"] = hi
    fix = verify_fix(message, data.get("fix"), level=level, support=support, source=source)
    if fix:
        out["fix"] = fix
    return out
