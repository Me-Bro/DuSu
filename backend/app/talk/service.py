"""Talk - the little the server stores and reads for the Talk screen (HTTP side; the chat itself is the `talk` WebSocket mode in main.py).

The only thing stored is the learner's chosen support level, in `memory.facts.talk_prefs` (a schemaless JSON document: no migration, and it is deleted with the account together with
the rest of the memory).  Which topic is "today's" is NOT stored: `topics.today()` is a pure function of (learner, IST day, band), so it needs no history and cannot drift.
Nothing here calls a model.
"""

from __future__ import annotations

from ..store import flag_modified, func, select

from .. import db
from . import topics as T

_S = lambda: db._Session()          # noqa: E731 - resolved at call time so tests can swap the engine

# The three support levels, as the Talk screen draws them. `ws_mode` is the WebSocket mode the client starts for that level: "hi" is Daily Talk's engine, UNCHANGED.
# All Hindi below is unreviewed (REVIEWED = False in topics.py): Devanagari for Hindi words, Latin for everyday English words, तुम, no gendered second person.
LEVELS = [
    {"id": "hi", "ws_mode": "daily",
     "label": {"en": "Hindi to English", "hi": "Hindi से English"},
     "hint": {"en": "You speak Hindi and DuSu tells you how to say it in English (Daily Talk).",
              "hi": "तुम Hindi में बोलो और DuSu बताती है कि इसे English में कैसे कहते हैं (Daily Talk)।"}},
    {"id": "en_sub", "ws_mode": "talk",
     "label": {"en": "English with Hindi subtitles", "hi": "English, साथ में Hindi subtitles"},
     "hint": {"en": "DuSu speaks English and every reply has a Hindi subtitle under it.",
              "hi": "DuSu English में बोलती है और हर reply के नीचे Hindi subtitle दिखता है।"}},
    {"id": "en", "ws_mode": "talk",
     "label": {"en": "English only", "hi": "सिर्फ़ English"},
     "hint": {"en": "DuSu speaks English only and fixes one mistake at a time.",
              "hi": "DuSu सिर्फ़ English में बात करती है और एक बार में एक ग़लती ठीक करती है।"}},
]


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


async def _level_and_prefs(uid: str) -> tuple[str, dict]:
    """(the learner's CEFR level as stored - '' when unknown, their saved talk prefs) in ONE session (two by-id reads)."""
    async with _S() as s:
        prof = await s.get(db.Profile, uid)
        mem = await s.get(db.Memory, uid)
        await s.commit()
    facts = (mem.facts or {}) if mem is not None else {}
    p = facts.get("talk_prefs") if isinstance(facts.get("talk_prefs"), dict) else {}
    return ((prof.level if prof is not None else "") or ""), dict(p)


def _support_of(prefs: dict, level: str) -> tuple[str, bool]:
    """(the support level to preselect, whether the learner chose it themselves)."""
    v = prefs.get("support")
    if v in T.SUPPORTS:
        return v, True
    return T.default_support(level), False


async def state(uid: str) -> dict:
    level, prefs = await _level_and_prefs(uid)
    today_ist = T.ist_today()
    top = T.today(uid, level, today_ist)
    alts = T.alternatives(uid, level, exclude=[top["id"]] if top else (), n=3, date_ist=today_ist)
    support, chosen = _support_of(prefs, level)
    return {"enabled": True, "date": today_ist.isoformat(), "level": level, "band": T.band_for_level(level), "support": support, "support_chosen": chosen,
            "support_default": T.default_support(level), "topic": top, "alternatives": [T.brief(a) for a in alts], "levels": LEVELS, "empty": top is None,
            "reviewed": T.REVIEWED}


def topic(tid: str) -> dict:
    t = T.get(tid)
    if t is None:
        raise NotFound()
    return t


async def save_support(uid: str, support) -> dict:
    if support not in T.SUPPORTS:
        raise Invalid("support")
    async with _S() as s:
        mem = await db._get_or_make_memory(s, uid)
        f = dict(mem.facts or {})
        cur = f.get("talk_prefs") if isinstance(f.get("talk_prefs"), dict) else {}
        f["talk_prefs"] = {**cur, "support": support}
        mem.facts = f
        flag_modified(mem, "facts")
        await s.commit()
    return {"support": support}


async def health() -> dict:
    """The owner dashboard line: how many topics each band has, how many rows were rejected at load, and how many Talk chats were saved today (a conversation row is written
    only when the chat had a summary)."""
    out: dict = {"topics": T.count(), "rejected": len(T.ERRORS), "missing": list(T._bank().missing)}
    try:
        day = db._ist_day_start_utc(db._ist_now().date())
        async with _S() as s:
            n = (await s.execute(select(func.count()).select_from(db.Conversation).where(db.Conversation.mode == "talk", db.Conversation.created_at >= day))).scalar() or 0
            await s.commit()
        out["sessions_today"] = int(n)
    except Exception as e:
        out["error"] = type(e).__name__
    return out
