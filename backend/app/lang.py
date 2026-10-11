"""Hindi / English language modes (CLAUDE.md §11, DUSU_BILINGUAL_PLAN.md).

One global language - `hi` (the default) or `en` - that Daily Talk, Face-to-Face Talk and Interview obey, switchable
before and during a session. Learn is a translator, so the same two values mean its DIRECTION instead: the language
the learner SPEAKS (`hi` = speak Hindi, hear English - the original behaviour; `en` = speak English, hear Hindi).

This module holds only the small, dependency-free pieces: the allowed values, what "the switch is off" means for each
mode, and the fixed lines used when the model can't be asked. The prompts live in interview/prompts.py.
"""

from __future__ import annotations

LANGS = ("hi", "en")
DEFAULT_LANG = "hi"

# What "bilingual switch OFF" means per WS mode - exactly today's behaviour: Face-to-Face and Interview were
# English-only; Daily Talk and Learn were Hindi-in. main.py falls back to this when the switch is off for a user.
LEGACY = {"conversation": "en", "interview": "en", "daily": "hi", "learning": "hi",
          "home": "hi"}   # Home 2.0 (home_content.py): the companion is Hinglish by default, with or without the switch


# The modes that obey the learner's Hindi / English choice: ONLY the new features (the Home AI companion; Know About DuSu has no socket;
# My Day joins by adding its mode here). Every older mode - Daily Talk, Face-to-Face, Interview, Learn - is pinned to LEGACY above: it runs
# exactly as it did before a language choice existed, whatever the dashboard switch, the saved preference or the client says
# (DUSU_LANGUAGE_SCOPE_PLAN.md). The Hindi / English prompts written for those older modes (prompts.py, engine.py) are PARKED: reachable
# again only by adding the mode here and drawing its switch.
SWITCHABLE = ("home",)


def norm(v, default: str = DEFAULT_LANG) -> str:
    return v if v in LANGS else default


def session_lang(mode: str, requested, switch_on: bool) -> str:
    """The language a WebSocket session runs in: the learner's choice for a switchable (new) mode when the switch is on for them, and
    what the mode always was (LEGACY) for everything else - an old mode never sees the choice."""
    if switch_on and mode in SWITCHABLE:
        return norm(requested)
    return LEGACY.get(mode, "en")


# A reply shorter than this is a dead-end one-liner and gets one retry (see engine.next_ai_turn). Devanagari carries
# roughly twice the meaning per character, so the Hindi floor is lower.
MIN_TURN_CHARS = {"en": 40, "hi": 24}

# The opening user turn that makes the model speak first (see OpenRouterLLM.next_question). None = the English default.
SEED = {"en": None, "hi": "शुरू करते हैं। मुझे नमस्ते कहिए और अपना पहला सवाल पूछिए।"}

# Fixed lines for when the model can't be asked (turn caps, a closing line it forgot). The English strings are the
# original inline ones, character for character - flag-off must not change a word of them.
LINES = {
    "en": {
        "interview_end": "Thanks, that's the end of our interview.",
        "interview_cap": "Thanks {name} — that's all the questions I have for now. Let me put together your report.",
        "convo_cap": ("This has been such a great long chat — let's pause here for now. "
                      "Start a fresh conversation whenever you'd like!"),
        "short_nudge": ("(That reply was too short and generic. React specifically to what I just said, "
                        "then ask one sharper, more specific follow-up question.)"),
        "switch_note": "(The learner has switched to English from now on — reply in English only.)",
        "daily_fallback_q": "How was your day today?",
    },
    "hi": {
        "interview_end": "धन्यवाद, हमारा interview यहीं पूरा होता है।",
        "interview_cap": "धन्यवाद {name} — अभी के लिए मेरे इतने ही सवाल थे। मैं आपकी रिपोर्ट तैयार करती हूँ।",
        "convo_cap": ("यह कितनी अच्छी लंबी बातचीत रही — अभी यहीं रुकते हैं। "
                      "जब मन करे, नई बातचीत शुरू कीजिए!"),
        "short_nudge": ("(That reply was too short and generic. React specifically to what I just said, then ask "
                        "one sharper, more specific follow-up question — in Hindi, Devanagari script.)"),
        "switch_note": "(The learner has switched to Hindi from now on — reply in Hindi, in Devanagari script.)",
        "daily_fallback_q": "आज आपका दिन कैसा रहा?",
    },
}

# Same wording for both languages (the key keeps its old name, `reply_hindi`, even for English Daily Talk).
DAILY_SHORT_NUDGE = ("(Your reply_hindi was too short/generic. Write the full warm reply — sense the feeling, "
                     "respond to it, and end with one specific question.)")


def line(lang: str, key: str, **kw) -> str:
    s = LINES.get(norm(lang, "en"), LINES["en"])[key]
    return s.format(**kw) if kw else s
