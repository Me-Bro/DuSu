"""Grammar Coach - every English sentence checked, corrected and explained (DUSU_GRAMMAR_COACH_PLAN.md; the approved plan lives in the session plan file).

Pure modules (no database, no network, no clock except an argument):
  text        apostrophe-keeping tokenizer, input cleaning, contraction canonicalisation
  segment     sentence segmentation of punctuated and unpunctuated speech-to-text
  gating      the language gate (session + sentence) and the opaque tokens
  lexicon     word lists and tables the gates and rule checks read
  catalog     the 41 rules: metadata (here) + bilingual lesson content (catalog_data)
  detectors   16 token-pattern rule checks + 3 table-driven ones (offline floor, never certify "clean")
  verify      quote location, edit bounds, artifact filter, rule-id guard, confidence, corrected sentence BUILT BY CODE
  scoring     counts, mistakes per 100 words, noise band, rule status machine
  flow        computed flow metrics
  drills      deterministic drill items
Async / DB: prompts, engine (the ONE AI stage), budget, tracker (the detached after-session task), models, service, api.

Switch: settings.grammar_coach = off (default) / owner / on. While it is off the endpoints answer 404 (export / delete excepted).
"""

RULES_VERSION = 1

_LEVELS = ("A1", "A2", "B1", "B2")


def norm_level(v) -> str:
    """A0 / A1 / beginner -> A1; A2 -> A2; B1 / intermediate / unknown -> B1; B2 / C* / advanced -> B2."""
    s = str(v or "").strip().upper()
    if s in ("A0", "A1", "BEGINNER"):
        return "A1"
    if s == "A2":
        return "A2"
    if s in ("B2", "ADVANCED") or s.startswith("C"):
        return "B2"
    return "B1"


def level_rank(v) -> int:
    return _LEVELS.index(norm_level(v))
