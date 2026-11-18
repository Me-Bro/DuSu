"""Grammar Lab - the item bank: Hindi sentences to put into English, with the English answers that are accepted (data, authored once).

One module per unit (`present_simple.py` ... `future_perfect_continuous.py`), each with

    UNIT = "present_simple"
    ITEMS = [
        # (id, level, hindi, [accepted english ...], trap)        <- `trap` is optional: one of catalog.TRAP_IDS
        ("prs-e-01", "easy", "राम रोज़ सुबह चाय पीता है।", ["Ram drinks tea every morning."], ""),
    ]

The id is `<unit code>-<level letter>-<nn>` (catalog.UNIT_CODE / LEVEL_CODE) and is STABLE: a learner's history and the Path's tests refer to it, so an item is never renumbered - a bad
one is edited in place or replaced by a NEW id.  `tests/lab/lint_bank.py` checks every rule below; nothing in this module is trusted at run time beyond `load()`'s structure check.

The English list holds only genuinely different phrasings.  What is accepted for free (so authors do not list it): case and punctuation, contractions (doesn't = does not), numerals,
`am/is/are going to <verb>` = `will <verb>`, and a time phrase moved to the other end of the sentence (`variants`).
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass

from .. import catalog

_MODULES: dict | None = None
_MOVABLE = ("every day", "every morning", "every evening", "every night", "every afternoon", "every week", "every month", "every year", "every sunday", "every monday", "every saturday",
            "daily", "yesterday", "today", "tomorrow", "last night", "last week", "last month", "last year", "last sunday", "next week", "next month", "next year", "next sunday",
            "now", "right now", "at the moment", "these days", "at present", "at that time", "at that moment", "tonight", "this morning", "this evening", "this week", "this year",
            "tomorrow morning", "tomorrow evening", "tomorrow night", "yesterday morning", "yesterday evening", "all day", "all night", "all morning", "since morning", "for two hours",
            "on sundays", "on mondays", "on saturdays", "in the morning", "in the evening", "at night", "every day of the week")


_GOVERNS = frozenset("since until till from by before after for of than between and or to on in at during within".split())


@dataclass(frozen=True)
class Item:
    id: str
    unit: str
    level: str
    hi: str
    en: tuple
    trap: str = ""


def _load_modules() -> dict:
    global _MODULES
    if _MODULES is None:
        out: dict = {}
        for unit in catalog.UNITS:
            try:
                out[unit] = importlib.import_module(f"{__name__}.{unit}")
            except ModuleNotFoundError as e:
                if e.name != f"{__name__}.{unit}":
                    raise                                    # a real import error inside a bank module must not be hidden
        _MODULES = out
    return _MODULES


def load() -> dict:
    """{id: Item} for every authored item; raises ValueError on a malformed row or a duplicate id (the lint reports these nicely, this keeps production honest)."""
    items: dict = {}
    for unit, mod in _load_modules().items():
        if getattr(mod, "UNIT", None) != unit:
            raise ValueError(f"{unit}: UNIT must be {unit!r}")
        for row in mod.ITEMS:
            if len(row) not in (4, 5):
                raise ValueError(f"{unit}: a row must be (id, level, hindi, [english], [trap]): {str(row)[:60]}")
            iid, level, hi, en = row[0], row[1], row[2], row[3]
            trap = row[4] if len(row) == 5 else ""
            if level not in catalog.LEVELS or not isinstance(en, (list, tuple)) or not en or not hi or iid in items:
                raise ValueError(f"{unit}: bad or duplicate item {iid!r}")
            items[iid] = Item(iid, unit, level, hi, tuple(en), trap or "")
    return items


def reset() -> None:
    global _MODULES
    _MODULES = None


def variants(en) -> list:
    """The accepted answers plus the harmless re-orderings: a movable time phrase at the end of a sentence is also accepted at its start, and the other way round."""
    out: list = []
    seen: set = set()

    def add(x: str) -> None:
        k = re.sub(r"[^a-z0-9' ]+", " ", x.lower()).split()
        key = " ".join(k)
        if key and key not in seen:
            seen.add(key)
            out.append(x)

    for sentence in en:
        add(sentence)
        m = re.match(r"^(.*?)([.?!]*)$", sentence.strip(), re.S)
        body, end = (m.group(1), m.group(2)) if m else (sentence, "")
        low = body.lower()
        for ph in sorted(_MOVABLE, key=len, reverse=True):
            if low.endswith(" " + ph) and len(body) > len(ph) + 2:
                head = body[:-(len(ph) + 1)].rstrip(" ,")
                if head.split()[-1].lower() in _GOVERNS:                  # `since yesterday`, `by tomorrow`, `until next week`: the phrase belongs to the word in front, it cannot move alone
                    break
                add(f"{ph[0].upper()}{ph[1:]} {head}{end}")                  # case never matters: the checker compares lower-case tokens
                break
        for ph in sorted(_MOVABLE, key=len, reverse=True):
            if low.startswith(ph + " ") and len(body) > len(ph) + 2:
                rest = body[len(ph) + 1:].lstrip(" ,")
                add(f"{rest[0].upper()}{rest[1:]} {ph}{end}")
                break
    return out



def by_unit_level(items: dict, unit: str, level: str) -> list:
    return sorted((i for i in items.values() if i.unit == unit and i.level == level), key=lambda i: i.id)
