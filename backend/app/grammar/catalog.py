"""The rule catalogue: metadata here, bilingual lesson content in catalog_data.CONTENT (Appendix B of the plan).

Severity and weight come from HERE, never from the model. `dets` names the rule checks (detectors.py) that cover the rule; a rule with no
detector is judged by the AI alone ("AI only") or is a "booster" the model may report but no solo check can create.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import level_rank, norm_level

GROUPS = {"tn": "Tense", "ag": "Agreement", "ar": "Articles", "pr": "Prepositions", "wd": "Word choice", "st": "Sentence structure",
          "pn": "Modals & pronouns", "md": "Modals & pronouns", "ind": "Natural English"}
GROUP_ORDER = ("Tense", "Agreement", "Articles", "Prepositions", "Word choice", "Sentence structure", "Modals & pronouns", "Natural English")
SEVERITIES = ("error", "natural", "polish")


@dataclass(frozen=True)
class Rule:
    id: str                     # family.slug, <= 18 chars (the model returns it)
    family: str                 # tn | ag | ar | pr | wd | st | pn | md | ind
    severity: str               # error | natural | polish
    weight: int                 # 1..3
    cefr_min: str               # A1 | A2 | B1 | B2
    stt_sensitive: bool         # the recogniser may have dropped / added the word
    dets: tuple[str, ...] = ()  # D1..D16 / T1..T3, empty = AI only
    starred: bool = False       # has a rule check -> fully authored for the owner stage

    @property
    def group(self) -> str:
        return GROUPS[self.family]


def _r(id_, sev, w, lvl, stt, dets=()):
    return Rule(id_, id_.split(".")[0], sev, w, lvl, stt, tuple(dets), starred=any(d.startswith("D") for d in dets))


_LIST = [
    # Tense
    _r("tn.pp_finished", "error", 3, "B1", True, ("D6",)), _r("tn.since_for", "error", 3, "A2", False, ("D7",)),
    _r("tn.cont_misuse", "error", 2, "A2", False, ("D8",)), _r("tn.did_past", "error", 3, "A1", True, ("D4",)),
    _r("tn.if_will", "error", 2, "A2", False, ("D5",)), _r("tn.cond_would", "error", 2, "B1", False),
    _r("tn.past_marker", "error", 2, "A2", True),
    # Agreement
    _r("ag.he_dont", "error", 3, "A1", False, ("D1",)), _r("ag.s_missing_3p", "error", 3, "A1", True, ("D2",)),
    _r("ag.aux_form", "error", 3, "A1", False, ("D3",)), _r("ag.there_is_plural", "error", 2, "A2", False, ("T2",)),
    _r("ag.quantifier_number", "error", 2, "A2", True, ("T2",)), _r("ag.base_after_aux", "error", 3, "A1", True, ("D4",)),
    # Articles
    _r("ar.a_an", "error", 1, "A1", True, ("D9",)), _r("ar.missing_a", "error", 2, "A1", True, ("D10",)),
    _r("ar.the_missing", "error", 2, "A2", True, ("D10",)), _r("ar.the_overuse", "error", 1, "B1", True),
    # Prepositions
    _r("pr.extra_prep", "error", 2, "A2", True, ("T1",)), _r("pr.wrong_prep", "error", 2, "A2", True, ("T1",)),
    _r("pr.time_in_on_at", "error", 2, "A1", True, ("D16",)), _r("pr.missing_to", "error", 2, "A2", True, ("T1",)),
    _r("pr.for_purpose", "error", 2, "A2", True, ("T1",)),
    # Word form & choice
    _r("wd.comparative_double", "error", 2, "A2", False, ("D12",)), _r("wd.noun_number", "error", 2, "A2", True, ("D11",)),
    _r("wd.adj_adv", "error", 2, "A2", True), _r("wd.say_tell", "error", 2, "A2", False, ("T2",)),
    _r("wd.collocation", "error", 2, "A2", False, ("T2",)), _r("wd.much_many", "error", 2, "A2", False, ("D11",)),
    # Structure
    _r("st.question_order", "error", 3, "A1", False, ("D13",)), _r("st.embedded_order", "error", 2, "B1", False, ("D14",)),
    _r("st.be_misuse", "error", 2, "A1", True, ("T2",)), _r("st.double_subject", "error", 2, "A2", False, ("D15",)),
    _r("st.missing_subject", "error", 1, "B1", True), _r("st.adverb_position", "error", 1, "A2", False, ("T2",)),
    _r("st.verb_pattern", "error", 2, "A2", False, ("T2",)), _r("st.run_on_frag", "polish", 1, "B2", False),
    # Pronoun & modal
    _r("pn.myself_intro", "error", 2, "A1", False, ("T2",)), _r("md.can_able", "error", 2, "A2", False, ("D4",)),
    _r("pn.relative", "error", 2, "B1", False, ("T2",)), _r("pn.pronoun_misuse", "error", 2, "A2", False, ("D15", "T2")),
    # Natural English
    _r("ind.lexicon", "natural", 1, "B1", False, ("T3",)),
]
RULES: dict[str, Rule] = {r.id: r for r in _LIST}
OTHER = "other"
FLOW_IDS = ("f.run_on", "f.choppy", "f.starters", "f.connectors", "f.fillers", "f.restarts")


def get(rule_id: str) -> Rule | None:
    """The rule for an id; `ind.lexicon#prepone` resolves to `ind.lexicon`. Unknown -> None (callers map it to `other`)."""
    return RULES.get(str(rule_id or "").split("#")[0])


def base_id(rule_id: str) -> str:
    return str(rule_id or "").split("#")[0]


def eligible(rule: Rule, level) -> bool:
    """May a miss of this rule be flagged for a learner at `level`?"""
    return level_rank(level) >= level_rank(rule.cefr_min)


def compact_listing(level="B1", compact=False) -> str:
    """The id list that goes into the AI prompt, generated from the catalogue so prompt and catalogue cannot drift."""
    lines = []
    for r in RULES.values():
        if not eligible(r, level) or r.severity == "polish" and level_rank(level) < level_rank("B2"):
            continue
        if r.severity == "natural" and level_rank(level) < level_rank("B1"):
            continue
        title = title_of(r.id, "en")
        lines.append(f"{r.id}: {title}" if compact else f"{r.id} [{r.severity}{r.weight}]: {title}")
    return "\n".join(lines)


def _content():
    try:
        from . import catalog_data
        return catalog_data.CONTENT
    except Exception:
        return {}


def content(rule_id: str) -> dict:
    """The bilingual lesson content for a rule ({} until authored): {"en": {...}, "hi": {...}} (see catalog_data)."""
    return _content().get(base_id(rule_id), {})


def title_of(rule_id: str, lang="en") -> str:
    c = content(rule_id).get(lang) or content(rule_id).get("en") or {}
    return c.get("title") or base_id(rule_id)


__all__ = ["Rule", "RULES", "get", "base_id", "eligible", "compact_listing", "content", "title_of", "GROUPS", "GROUP_ORDER", "norm_level", "OTHER", "FLOW_IDS"]
