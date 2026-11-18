"""Talk - the topic bank: loader, validator, and "today's topic" selection (pure: no database, no network; the only clock is an argument).

The bank itself is DATA, authored once in `backend/app/talk/bank/a1.py`, `a2.py`, `b1.py`, each exposing `TOPICS: list[dict]`.  One row:

    {"id": "a1-morning-routine",             # "<band lower>-<slug>", unique, [a-z0-9-]
     "band": "A1",                           # A1 | A2 | B1
     "cat": "daily",                         # one of CATS
     "title":   {"en": "...", "hi": "..."},
     "opener":  {"en": "...", "hi": "..."},  # the first thing DuSu says: English + its Hindi subtitle (NO model call is made for it)
     "starters":[{"en": "...", "hi": "..."} x 3],      # three sentences / questions the learner can use
     "vocab":   [{"en": "...", "hi": "..."} x 6..8],
     "focus":   "present_simple"}            # a Grammar Lab unit id (lab/catalog.py UNITS)

Everything here is defensive on purpose: a missing module is that band EMPTY (never a crash), a row that fails validation is skipped and recorded in `ERRORS`
(never half-loaded), and a module that cannot even be imported is an error entry, not an exception.  `tests/talk/lint_topics.py` is the author's tool: it runs the
same `validate()` and exits 1 on any error.

Hindi writing rules (CLAUDE.md section 23, the same as the rest of the new features): Devanagari for the Hindi words + Latin for everyday English / grammar words,
तुम never आप or तू, no second-person verb that guesses the learner's gender (no "करते हो" / "रहे हो" / "जाओगे"), no first-person gendered verb in a STARTER (the learner may be any
gender).  DuSu speaks as a woman about herself.  `\\b` does not work on Devanagari: this module uses token sets, never `\\b`.  Everything authored is unreviewed until a native
reader signs the sample off (`REVIEWED`).
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import importlib
import re

REVIEWED = False                       # set True only after a native Hindi reader has signed off the bank's sample
BANDS = ("A1", "A2", "B1")
MODULES = ("a1", "a2", "b1")
CATS = ("daily", "family", "food", "shopping", "travel", "work", "health", "study", "tech", "hobby", "festival", "weather", "city", "goals", "past", "opinion", "phone", "service")
SUPPORTS = ("hi", "en_sub", "en")      # hi = Hindi -> English (Daily Talk, unchanged); en_sub = English + Hindi subtitles; en = English only
TALK_SUPPORTS = ("en_sub", "en")       # the two levels that are the `talk` WebSocket mode
DEFAULT_SUPPORT = {"A1": "hi", "A2": "en_sub", "B1": "en"}

# ----------------------------------------------------------------------------------------------------------------- limits (every one is linted)
ID_RE = re.compile(r"^(a1|a2|b1)-[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_ID = 48
TITLE_EN = (3, 60)
TITLE_HI = (2, 80)
OPENER_WORDS = (4, 40)
OPENER_HI_MAX = 300
STARTER_WORDS = (2, 18)
STARTER_HI_MAX = 180
VOCAB_COUNT = (6, 8)
VOCAB_EN_MAX = 28
VOCAB_HI_MAX = 48
MIN_DEV_SHARE = 0.30                    # of the LETTERS of a Hindi sentence, at least this share is Devanagari (romanised Hindi is mispronounced by the voice)
WARN_DEV_SHARE = 0.50

_DEV_CH = re.compile(r"[ऀ-ॿ]")
_DEV_RUN = re.compile(r"[ऀ-ॣ०-ॿ]+")      # the danda (U+0964 / U+0965) lies INSIDE the Devanagari block: a word before "।" must still be a whole token
_LATIN = re.compile(r"[A-Za-z]")
_EN_OK = re.compile(r"^[A-Za-z0-9 ,.'’?!:;()/&%+\-–\"“”$₹]+$")
_HI_OK = re.compile(r"^[A-Za-z0-9 ,.'’?!:;()/&%+\-–\"“”$₹ऀ-ॿ।॥]+$")

# आप-family and तू-family, as WHOLE Devanagari tokens (a vowel sign is not a word character, so \b is wrong here; "आपस" / "आपसी" are different words and stay legal)
_AAP = re.compile(r"^आप(?:का|की|के|को|से|ने|में|पर|कि)?$")
_TU = re.compile(r"^(?:तू|तूने|तेरा|तेरी|तेरे|तुझे|तुझको|तुझसे|तुझमें|तुझ)$")
# a second-person verb that guesses the learner's gender: "<verb>ते/ती हो", "रहे/रही हो", "सकते/सकती हो", "चुके/चुकी हो", "गए/गई/आए/आई हो", the future "-ोगे / -ोगी"
_GEND_HO_PREV = re.compile(r"^.*(?:ते|ती)$|^(?:रहे|रही|चुके|चुकी|गए|गई|आए|आई|गये|गयी|आये|आयी)$")
_GEND_FUT = re.compile(r"^.+(?:ो|ओ)(?:गे|गी)$")
_GEND_TUM_PARTICIPLE = frozenset("गया गयी गई गए गये आया आयी आई आए आये था थी थे".split())
# "मैं" + a gendered ending ("जाता हूँ", "रही हूँ", "जाऊँगा", "चुका हूँ"): the learner may be any gender
_GEND_1SG = re.compile(r"(?:ता|ती|रहा|रही|चुका|चुकी)\s+(?:हूँ|हूं|था|थी)|(?:ूँगा|ूँगी|ूंगा|ूंगी|ऊँगा|ऊँगी|ऊंगा|ऊंगी)")

ERRORS: list[str] = []                  # what the last load of the default bank rejected (the lint prints it)


# ----------------------------------------------------------------------------------------------------------------- text helpers
def est_tokens(s: str) -> int:
    """A deliberately pessimistic token estimate (no tokenizer is available): Latin text ~3.6 characters a token, Devanagari ~1.4 (its characters are single code points
    but cost several tokens each on the models DuSu uses).  Used to hold the prompt to its budget; never to bill anything."""
    s = str(s or "")
    dev = len(_DEV_CH.findall(s))
    return int((len(s) - dev) / 3.6 + 0.999) + int(dev / 1.4 + 0.999)


def dev_share(s: str) -> float:
    """Devanagari letters / all letters (Devanagari + Latin) of `s`; 0.0 when there are none."""
    d = len(_DEV_CH.findall(s or ""))
    a = len(_LATIN.findall(s or ""))
    return d / (d + a) if d + a else 0.0


def hindi_problems(text: str, *, starter: bool = False) -> list[str]:
    """Rule breaks in one Hindi string (empty list = clean): आप / तू forms, a second-person verb that guesses gender, a gendered first-person verb (starters only)."""
    out: list[str] = []
    toks = _DEV_RUN.findall(text or "")
    for t in toks:
        if _AAP.match(t):
            out.append(f"आप-form {t!r} (use तुम)")
        if _TU.match(t):
            out.append(f"तू-form {t!r} (use तुम)")
        if _GEND_FUT.match(t) and len(t) >= 5 and not t.endswith("योगी"):         # (उपयोगी, सहयोगी ... are nouns / adjectives, not a future verb)
            out.append(f"future second-person {t!r} guesses gender")
    for a, b in zip(toks, toks[1:]):
        # "<verb> हो" is second person ("क्या कर रहे हो"); "<verb> होगे / होगी" is second person only when तुम is the subject ("वह कर रही होगी" is a third person: fine)
        if _GEND_HO_PREV.match(a) and (b == "हो" or (b in ("होगे", "होगी") and "तुम" in toks)):
            out.append(f"{a} {b!r}: a second-person verb that guesses gender")
    if "तुम" in toks:
        i = toks.index("तुम")
        for t in toks[i + 1:i + 5]:
            if t in _GEND_TUM_PARTICIPLE:
                out.append(f"तुम ... {t!r}: guesses gender")
    if starter and _GEND_1SG.search(text or "") and "मैं" in toks:
        out.append("'मैं' with a gendered verb ending (the learner may be any gender: use a name, हम, मेरा ..., or a gender-neutral wording)")
    return out


# ----------------------------------------------------------------------------------------------------------------- validation
def _words(s: str) -> int:
    return len(str(s or "").split())


def _pair(v, path: str, errs: list, *, en_words=None, en_chars=None, hi_chars=None, sentence: bool = False, starter: bool = False, dev_min: float = MIN_DEV_SHARE) -> dict | None:
    if not isinstance(v, dict) or not isinstance(v.get("en"), str) or not isinstance(v.get("hi"), str):
        errs.append(f"{path}: must be {{'en': str, 'hi': str}}")
        return None
    en, hi = " ".join(v["en"].split()), " ".join(v["hi"].split())
    if not en or not hi:
        errs.append(f"{path}: empty en or hi")
        return None
    if _DEV_CH.search(en):
        errs.append(f"{path}.en: Devanagari in the English")
    if not _EN_OK.match(en):
        errs.append(f"{path}.en: characters outside letters / digits / basic punctuation (no markup, quotes of code, braces): {en!r}")
    if not _HI_OK.match(hi):
        errs.append(f"{path}.hi: characters outside Devanagari / Latin / digits / basic punctuation: {hi!r}")
    if not _DEV_CH.search(hi):
        errs.append(f"{path}.hi: no Devanagari (Hindi must be written in Devanagari)")
    elif dev_share(hi) < dev_min:
        errs.append(f"{path}.hi: only {dev_share(hi):.0%} of the letters are Devanagari - romanised Hindi is mispronounced by the voice (Devanagari for Hindi words, Latin only for everyday English words)")
    if en_words and not en_words[0] <= _words(en) <= en_words[1]:
        errs.append(f"{path}.en: {_words(en)} words (allowed {en_words[0]}-{en_words[1]})")
    if en_chars and not en_chars[0] <= len(en) <= en_chars[1]:
        errs.append(f"{path}.en: {len(en)} characters (allowed {en_chars[0]}-{en_chars[1]})")
    if hi_chars and len(hi) > hi_chars:
        errs.append(f"{path}.hi: {len(hi)} characters (max {hi_chars})")
    if sentence and en[-1:] not in ".?!":
        errs.append(f"{path}.en: must end with . ? or !")
    for p in hindi_problems(hi, starter=starter):
        errs.append(f"{path}.hi: {p}")
    return {"en": en, "hi": hi}


def validate_row(row, seen_ids: set | None = None) -> tuple[dict | None, list[str], list[str]]:
    """(clean topic or None, errors, warnings) for one row.  A topic is returned only when it has NO error."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(row, dict):
        return None, ["row is not a dict"], warns
    tid = row.get("id")
    label = tid if isinstance(tid, str) and tid else "?"
    e0 = len(errs)
    if not isinstance(tid, str) or not ID_RE.match(tid) or len(tid) > MAX_ID:
        errs.append(f"{label}: id must match <a1|a2|b1>-<slug of a-z 0-9 ->, at most {MAX_ID} characters")
    band = row.get("band")
    if band not in BANDS:
        errs.append(f"{label}: band must be one of {BANDS}")
    elif isinstance(tid, str) and ID_RE.match(tid) and tid.split("-", 1)[0] != band.lower():
        errs.append(f"{label}: id prefix must be {band.lower()}- to match the band {band}")
    if seen_ids is not None and isinstance(tid, str) and tid in seen_ids:
        errs.append(f"{label}: duplicate id")
    if row.get("cat") not in CATS:
        errs.append(f"{label}: cat must be one of {CATS}")
    # lazy import: lab.catalog is pure, but keep this module importable on its own
    try:
        from ..lab import catalog as lab_catalog
        units = lab_catalog.UNITS
    except Exception:                                     # pragma: no cover - the Lab package always ships
        units = ()
    if units and row.get("focus") not in units:
        errs.append(f"{label}: focus {row.get('focus')!r} is not a Grammar Lab unit id (one of {tuple(units)})")
    title = _pair(row.get("title"), f"{label}.title", errs, en_chars=TITLE_EN, hi_chars=TITLE_HI[1])
    if title and len(title["hi"]) < TITLE_HI[0]:
        errs.append(f"{label}.title.hi: too short")
    opener = _pair(row.get("opener"), f"{label}.opener", errs, en_words=OPENER_WORDS, hi_chars=OPENER_HI_MAX, sentence=True)
    if opener and "?" not in opener["en"]:
        errs.append(f"{label}.opener.en: DuSu's first line must ask the learner something (a question mark)")
    if opener and "?" not in opener["hi"]:
        warns.append(f"{label}.opener.hi: the Hindi subtitle has no question mark")
    sts = row.get("starters")
    starters: list = []
    if not isinstance(sts, list) or len(sts) != 3:
        errs.append(f"{label}.starters: exactly 3 starters")
    else:
        for k, s in enumerate(sts):
            p = _pair(s, f"{label}.starters[{k}]", errs, en_words=STARTER_WORDS, hi_chars=STARTER_HI_MAX, sentence=True, starter=True)
            if p:
                starters.append(p)
        if len({s["en"].lower() for s in starters}) != len(starters):
            errs.append(f"{label}.starters: two starters are the same sentence")
    vocab: list = []
    vs = row.get("vocab")
    if not isinstance(vs, list) or not VOCAB_COUNT[0] <= len(vs) <= VOCAB_COUNT[1]:
        errs.append(f"{label}.vocab: {VOCAB_COUNT[0]}-{VOCAB_COUNT[1]} words")
    else:
        for k, v in enumerate(vs):
            p = _pair(v, f"{label}.vocab[{k}]", errs, en_words=(1, 3), en_chars=(2, VOCAB_EN_MAX), hi_chars=VOCAB_HI_MAX, dev_min=0.01)
            if p:
                vocab.append(p)
        if len({v["en"].lower() for v in vocab}) != len(vocab):
            errs.append(f"{label}.vocab: the same English word twice")
    extra = sorted(set(row) - {"id", "band", "cat", "title", "opener", "starters", "vocab", "focus"})
    if extra:
        warns.append(f"{label}: unknown keys {extra} are ignored")
    if len(errs) > e0 or len(starters) != 3 or not (VOCAB_COUNT[0] <= len(vocab) <= VOCAB_COUNT[1]) or not title or not opener:
        return None, errs, warns
    if opener and dev_share(opener["hi"]) < WARN_DEV_SHARE:
        warns.append(f"{label}.opener.hi: {dev_share(opener['hi']):.0%} Devanagari (aim for about 70%)")
    return ({"id": tid, "band": band, "cat": row["cat"], "title": title, "opener": opener, "starters": starters, "vocab": vocab, "focus": row["focus"]}, errs, warns)


def validate(rows, *, expect_band: str | None = None) -> tuple[list[dict], list[str], list[str]]:
    """(valid topics, errors, warnings) for a list of rows.  Cross-row rules: unique ids, unique English titles, unique openers.  `expect_band` is the module's own band:
    a row that says another band is an error."""
    topics: list[dict] = []
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(rows, (list, tuple)):
        return [], ["TOPICS is not a list"], warns
    seen: set = set()
    titles: dict = {}
    openers: dict = {}
    for row in rows:
        t, e, w = validate_row(row, seen)
        errs.extend(e)
        warns.extend(w)
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            seen.add(row["id"])
        if t is None:
            continue
        if expect_band and t["band"] != expect_band:
            errs.append(f"{t['id']}: band {t['band']} in the {expect_band} module")
            continue
        tk, ok_ = t["title"]["en"].lower(), t["opener"]["en"].lower()
        if tk in titles:
            errs.append(f"{t['id']}: the same English title as {titles[tk]}")
            continue
        if ok_ in openers:
            errs.append(f"{t['id']}: the same opener as {openers[ok_]}")
            continue
        titles[tk], openers[ok_] = t["id"], t["id"]
        topics.append(t)
    return topics, errs, warns


# ----------------------------------------------------------------------------------------------------------------- the bank
class Bank:
    """A validated, indexed set of topics.  Build one from rows (tests) or from the three bank modules (`load_modules`)."""

    def __init__(self, topics: list[dict], errors: list[str] | None = None, warnings: list[str] | None = None, missing: list[str] | None = None):
        self.topics = list(topics)
        self.errors = list(errors or [])
        self.warnings = list(warnings or [])
        self.missing = list(missing or [])
        self.by_id = {t["id"]: t for t in self.topics}
        self.by_band = {b: [t for t in self.topics if t["band"] == b] for b in BANDS}

    @classmethod
    def from_rows(cls, rows) -> "Bank":
        t, e, w = validate(rows)
        return cls(t, e, w)


def load_modules(names=MODULES) -> Bank:
    """Import the band modules defensively.  A module that does not exist is that band empty (`missing`); a module that raises, or exposes no `TOPICS`, is an error entry."""
    topics: list[dict] = []
    errs: list[str] = []
    warns: list[str] = []
    missing: list[str] = []
    seen_titles: dict = {}
    seen_openers: dict = {}
    for name in names:
        full = f"{__package__}.bank.{name}"
        try:
            mod = importlib.import_module(full)
        except ModuleNotFoundError as e:
            if e.name == full:
                missing.append(name)
            else:
                errs.append(f"module {name}: missing dependency {e.name!r}")
            continue
        except Exception as e:                            # a syntax error in an author's file must not take the server down
            errs.append(f"module {name}: {type(e).__name__}")
            continue
        rows = getattr(mod, "TOPICS", None)
        if rows is None:
            errs.append(f"module {name}: no TOPICS list")
            continue
        t, e, w = validate(rows, expect_band=name.upper())
        errs.extend(f"[{name}] {x}" for x in e)
        warns.extend(f"[{name}] {x}" for x in w)
        for x in t:                                       # ids / titles / openers must also be unique ACROSS modules
            if x["id"] in {y["id"] for y in topics}:
                errs.append(f"[{name}] {x['id']}: duplicate id across modules")
                continue
            tk, ok_ = x["title"]["en"].lower(), x["opener"]["en"].lower()
            if tk in seen_titles or ok_ in seen_openers:
                errs.append(f"[{name}] {x['id']}: same English title / opener as {seen_titles.get(tk) or seen_openers.get(ok_)}")
                continue
            seen_titles[tk], seen_openers[ok_] = x["id"], x["id"]
            topics.append(x)
    return Bank(topics, errs, warns, missing)


_BANK: Bank | None = None


def _bank() -> Bank:
    global _BANK
    if _BANK is None:
        _BANK = load_modules()
        ERRORS[:] = _BANK.errors
        if _BANK.errors:
            print(f"[talk] {len(_BANK.errors)} topic row(s) rejected at load (see tests/talk/lint_topics.py)")
    return _BANK


def use(bank: Bank | None) -> None:
    """Replace the default bank (tests).  `use(None)` forgets it, so the next call reloads the real modules."""
    global _BANK
    _BANK = bank
    ERRORS[:] = bank.errors if bank else []


def reset() -> None:
    use(None)


# ----------------------------------------------------------------------------------------------------------------- queries
def all_topics() -> list[dict]:
    return copy.deepcopy(_bank().topics)


def count() -> dict:
    b = _bank()
    return {"total": len(b.topics), **{k: len(v) for k, v in b.by_band.items()}}


def get(tid) -> dict | None:
    t = _bank().by_id.get(tid) if isinstance(tid, str) else None
    return copy.deepcopy(t) if t else None


def for_band(band: str) -> list[dict]:
    return copy.deepcopy(_bank().by_band.get(band, []))


def band_for_level(cefr) -> str:
    """A0 / A1 -> A1, A2 -> A2, B1 / B2 (and C*) -> B1; anything unknown -> A1."""
    s = str(cefr or "").strip().upper()
    if s in ("A0", "A1", "BEGINNER"):
        return "A1"
    if s == "A2":
        return "A2"
    if s in ("B1", "B2", "INTERMEDIATE", "ADVANCED") or (s[:1] == "C" and s[1:2].isdigit()):
        return "B1"
    return "A1"


def default_support(level) -> str:
    """The support level a learner starts on: A1 -> hi (Daily Talk's engine), A2 -> en_sub, B1 -> en."""
    return DEFAULT_SUPPORT[band_for_level(level)]


def _date(d) -> _dt.date:
    if isinstance(d, _dt.datetime):
        return d.date()
    if isinstance(d, _dt.date):
        return d
    return _dt.date.fromisoformat(str(d)[:10])


def ist_today() -> _dt.date:
    """The IST day the rest of the app uses (a fixed +05:30 - no DST, no zone database)."""
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).date()


def _h(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _order(uid: str, band: str, pool: list[dict]) -> list[dict]:
    """A fixed order for one learner in one band: categories take turns (so two days in a row never share a category while two categories exist), inside a category the
    topics are in a per-learner hashed order, and the categories themselves are in a per-learner hashed order.  Stable for as long as the bank is."""
    buckets: dict = {}
    for t in sorted(pool, key=lambda t: _h(uid, band, "t", t["id"])):
        buckets.setdefault(t["cat"], []).append(t)
    cats = sorted(buckets, key=lambda c: _h(uid, band, "c", c))
    out: list[dict] = []
    i = 0
    while len(out) < len(pool):
        for c in cats:
            if i < len(buckets[c]):
                out.append(buckets[c][i])
        i += 1
    return out


def _band_pool(band: str) -> tuple[str, list[dict]]:
    """The band's topics; an empty band (a module not authored yet) falls back to the nearest band that has some, so a learner is never offered nothing."""
    b = _bank()
    if b.by_band.get(band):
        return band, b.by_band[band]
    idx = BANDS.index(band)
    for k in range(1, len(BANDS)):
        for j in (idx - k, idx + k):
            if 0 <= j < len(BANDS) and b.by_band.get(BANDS[j]):
                return BANDS[j], b.by_band[BANDS[j]]
    return band, []


def today(uid: str, level, date_ist=None) -> dict | None:
    """Today's topic for this learner: deterministic for (learner, IST day, band); consecutive days walk one fixed per-learner order of the band, so a topic does not come
    back for as many days as the band has topics (>= 7 whenever the band has 8 or more).  None only when the whole bank is empty."""
    band, pool = _band_pool(band_for_level(level))
    if not pool:
        return None
    order = _order(str(uid or ""), band, pool)
    return copy.deepcopy(order[_date(date_ist if date_ist is not None else ist_today()).toordinal() % len(order)])


def alternatives(uid: str, level, exclude=(), n: int = 3, date_ist=None) -> list[dict]:
    """Up to `n` other topics from the learner's band (topped up from a neighbouring band only if the band is too small): deterministic per learner per IST day, never an
    excluded id, different categories first (and different from the excluded topics' categories)."""
    n = max(0, int(n))
    band, pool = _band_pool(band_for_level(level))
    exc = {str(x) for x in (exclude or ())}
    day = _date(date_ist if date_ist is not None else ist_today()).toordinal()
    cand = [t for t in _order(str(uid or ""), band, pool) if t["id"] not in exc]
    seed = _h(uid, band, "alt", day)
    cand.sort(key=lambda t: _h(seed, t["id"]))
    cats_taken = {t["cat"] for t in pool if t["id"] in exc}
    picked: list[dict] = []
    for t in cand:                                         # first pass: new categories only
        if len(picked) >= n:
            break
        if t["cat"] not in cats_taken:
            picked.append(t)
            cats_taken.add(t["cat"])
    for t in cand:                                         # second pass: fill up from what is left
        if len(picked) >= n:
            break
        if t not in picked:
            picked.append(t)
    if len(picked) < n:                                    # a band too small to offer n: borrow from the others
        have = {t["id"] for t in picked} | exc
        others = [t for b in BANDS if b != band for t in _bank().by_band.get(b, []) if t["id"] not in have]
        others.sort(key=lambda t: _h(seed, "x", t["id"]))
        picked.extend(others[:n - len(picked)])
    return copy.deepcopy(picked[:n])


def brief(t: dict) -> dict:
    """The small form of a topic (the "choose another topic" list): enough to draw a card, nothing of the lesson."""
    return {"id": t["id"], "title": t["title"], "band": t["band"], "cat": t["cat"], "focus": t["focus"]}
