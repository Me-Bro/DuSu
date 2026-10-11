"""Home 2.0 - "AI companion first" (CLAUDE.md §12, DUSU_HOME_AI_PLAN.md).

ONE registry of what DuSu actually has. It feeds three things, so they cannot disagree:
  - the "Know About DuSu" page (GET /home/features),
  - the list of features the Home AI is allowed to mention (the prompt's catalogue),
  - the validation of the ids the model suggests (an id that is not here - or not switched on for this learner - is dropped).

The Home AI never navigates and never changes anything: it names a feature id, the server checks it, and the app draws a
button the learner may tap. Nothing here talks to the model or the database; it is pure data and small pure functions, so
the whole module can be checked without either.

Honesty rule: a feature that is not built yet carries status "soon" - it is shown as "coming soon" and the model is told
it does not exist. When the Goals planner ships (DUSU_GOALS_PLAN.md), flip its status to "live" and give it a route.
"""

from __future__ import annotations

import re

INTENTS = ("daily_plan", "goal_progress", "english_practice", "confidence_practice", "interview_prep",
           "translate_help", "presentation_prep", "feature_discovery", "general_conversation")

# status: "live" = built and reachable; "soon" = not built (never linked, never promised).
# needs: a switch the learner must have for the feature to exist for them ("practice_room").
# route: where the app goes when the learner taps it (a key of the client's ROUTES table).
FEATURES: list[dict] = [
    {"id": "daily_talk", "icon": "☀️", "route": "/daily-talk", "status": "live", "needs": None, "group": "main",
     "en": {"title": "Daily Talk",
            "desc": "Tell DuSu about your day like you would tell a friend. She answers warmly and shows you how to say it in natural English.",
            "best": "Best for: an easy daily habit, even on a low-energy day.",
            "say": "talk through your day like with a friend; DuSu shows how to say it in natural English"},
     "hi": {"title": "Daily Talk",
            "desc": "अपने दिन की बात DuSu को बताओ, बिल्कुल एक क़रीबी दोस्त की तरह। वो दोस्त की तरह जवाब देती है और वही बात natural English में बोलना सिखाती है।",
            "best": "किसके लिए: रोज़ की एक आसान आदत, थके हुए दिन में भी।"}},
    {"id": "face_to_face", "icon": "💬", "route": "/face-to-face", "status": "live", "needs": None, "group": "main",
     "en": {"title": "Face to Face Talk",
            "desc": "A relaxed, non-stop chat with DuSu. No judging, no lectures - she keeps the conversation going so you just speak.",
            "best": "Best for: building confidence and fluency by simply talking.",
            "say": "a relaxed free conversation with DuSu to build speaking confidence"},
     "hi": {"title": "Face to Face Talk",
            "desc": "DuSu के साथ आराम से, बिना रुके बातचीत। न कोई judge करता है, न lecture - वो बात चलाती रहती है और तुम बस बोलते जाओ।",
            "best": "किसके लिए: बोलने का confidence और flow बनाना।"}},
    {"id": "interview", "icon": "🎯", "route": "/interview", "status": "live", "needs": None, "group": "main",
     "en": {"title": "Interview Prep",
            "desc": "A mock HR interview for the role you pick. DuSu asks, you answer out loud, then you get a score and a stronger version of your answer.",
            "best": "Best for: job interviews and campus placements.",
            "say": "a mock HR interview for a role, then a scored report with a better version of an answer"},
     "hi": {"title": "Interview Prep",
            "desc": "तुम जो role चुनो, उसके लिए mock HR interview। DuSu सवाल पूछती है, तुम बोलकर जवाब दो, और आख़िर में score और जवाब का बेहतर version मिलता है।",
            "best": "किसके लिए: job interview और campus placement।"}},
    {"id": "learn", "icon": "🎓", "route": "/learn", "status": "live", "needs": None, "group": "main",
     "en": {"title": "Learn",
            "desc": "Say a sentence in Hindi and DuSu says it back in natural spoken English - slowly, as many times as you want - so you can repeat it.",
            "best": "Best for: when you know what you want to say but not how to say it in English.",
            "say": "say a sentence in Hindi and hear it in natural spoken English, slowly, to repeat"},
     "hi": {"title": "Learn",
            "desc": "कोई भी वाक्य हिंदी में बोलो, DuSu उसे natural spoken English में बोलकर सुनाती है - धीरे-धीरे, जितनी बार चाहो - ताकि तुम दोहरा सको।",
            "best": "किसके लिए: जब बात पता हो पर English में कैसे कहें, ये न पता हो।"}},
    {"id": "journey", "icon": "🗺️", "route": "/learning-journey", "status": "live", "needs": None, "group": "main",
     "en": {"title": "Your English Journey",
            "desc": "A 7-level roadmap with short lessons and a test at the end of each level, so you can always see how far you have come and what is next.",
            "best": "Best for: seeing your progress and having a clear next step.",
            "say": "the 7-level learning roadmap with short lessons and a level test"},
     "hi": {"title": "Your English Journey",
            "desc": "7 levels का roadmap - हर level में छोटे lessons और आख़िर में एक test, ताकि हमेशा दिखे कि अब तक कितना सफ़र तय हुआ और अगला step क्या है।",
            "best": "किसके लिए: अपनी progress देखना और अगला step साफ़ रखना।"}},
    {"id": "practice_room", "icon": "🎤", "route": "/practice-room", "status": "live", "needs": "practice_room", "group": "main",
     "en": {"title": "Practice Room",
            "desc": "Rehearse a presentation: record it, get a scored report with specific feedback, listen back and try again.",
            "best": "Best for: a presentation or talk coming up.",
            "say": "rehearse a presentation: record it, get a scored report, listen back and retry"},
     "hi": {"title": "Practice Room",
            "desc": "Presentation की rehearsal करो - record करो, score और specific feedback पाओ, खुद को सुनो और फिर से try करो।",
            "best": "किसके लिए: जब कोई presentation या talk आने वाला हो।"}},
    {"id": "career_path", "icon": "🧭", "route": "/career-path", "status": "live", "needs": None, "group": "more",
     "en": {"title": "Career Path",
            "desc": "Tell DuSu what you want to become and she builds a step-by-step roadmap of stages and skills.",
            "best": "Best for: turning a big career dream into small steps.",
            "say": "a step-by-step career roadmap for what they want to become"},
     "hi": {"title": "Career Path",
            "desc": "DuSu को बताओ कि तुम्हें क्या बनना है, वो stages और skills का step-by-step roadmap बना देती है।",
            "best": "किसके लिए: बड़े career dream को छोटे steps में बाँटना।"}},
    {"id": "league", "icon": "🏆", "route": "/league", "status": "live", "needs": None, "group": "more",
     "en": {"title": "Weekly League",
            "desc": "Earn XP when you speak and see where you stand against other learners this week. It resets every Monday.",
            "best": "Best for: a little friendly competition.",
            "say": "a weekly XP league against other learners that resets every Monday"},
     "hi": {"title": "Weekly League",
            "desc": "बोलने पर XP कमाओ और देखो कि इस हफ़्ते दूसरे learners के बीच तुम कहाँ हो। हर Monday को reset होती है।",
            "best": "किसके लिए: थोड़ी friendly competition।"}},
    {"id": "achievements", "icon": "🏅", "route": "/achievements", "status": "live", "needs": None, "group": "more",
     "en": {"title": "Achievements",
            "desc": "Badges for the real milestones you reach - first talk, streaks, brave moments.",
            "best": "Best for: celebrating how far you have come.",
            "say": "badges for real milestones like streaks and brave moments"},
     "hi": {"title": "Achievements",
            "desc": "तुम्हारे असली milestones के badges - पहली बातचीत, streaks, हिम्मत वाले पल।",
            "best": "किसके लिए: अपनी जीत को celebrate करना।"}},
    # Not built (DUSU_GOALS_PLAN.md is a plan). Shown as "coming soon", never linked, and the model is told it does not exist.
    {"id": "goals_planning", "icon": "✅", "route": None, "status": "soon", "needs": None, "group": "soon",
     "en": {"title": "Goals & Daily Planning",
            "desc": "Daily tasks, habits and reminders that keep you on track.",
            "best": "Coming soon.",
            "say": "saved daily tasks, goals with tasks, habits and reminders"},
     "hi": {"title": "Goals & Daily Planning",
            "desc": "रोज़ के tasks, habits और reminders, जो तुम्हें track पर रखें।",
            "best": "जल्दी आ रहा है।"}},
]

# Shown on the page too (never offered as a chip): the Know About page itself.
ABOUT = {"id": "about", "route": "/about",
         "en": {"title": "Know About DuSu"}, "hi": {"title": "Know About DuSu"}}

HOW_IT_WORKS = {
    "en": [("Speak", "Tap Start Speaking and talk. DuSu listens - no typing needed."),
           ("DuSu answers", "She replies out loud, like a friend, and suggests what to try next."),
           ("You choose", "Nothing starts or changes unless you tap it. You are always in control.")],
    "hi": [("बोलो", "Start Speaking दबाओ और बात करो। DuSu सुनती है - type करने की ज़रूरत नहीं।"),
           ("DuSu जवाब देती है", "वो दोस्त की तरह बोलकर जवाब देती है और बताती है कि आगे क्या try करें।"),
           ("फ़ैसला तुम्हारा", "तुम tap करो, तभी कुछ शुरू होता है। हर चीज़ तुम्हारे control में है।")],
}


def _flags(flags: dict | None) -> dict:
    return flags if isinstance(flags, dict) else {}


def available(flags: dict | None = None) -> list[dict]:
    """The features that exist for THIS learner: built (status live) and, where a switch is needed, switched on."""
    f = _flags(flags)
    return [x for x in FEATURES if x["status"] == "live" and (not x["needs"] or f.get(x["needs"]))]


def upcoming() -> list[dict]:
    return [x for x in FEATURES if x["status"] == "soon"]


def tiles(flags: dict | None = None) -> list[dict]:
    """The icon tiles on the Home page: one per feature that really exists for THIS learner (built, switched on, and with a
    route to open), in registry order. Both languages' titles ride along so the Hindi/English switch re-labels them without a
    fetch. "Coming soon" features and the Know About page are never tiles - there is nothing to open. Same registry as the
    Know About page and the model's catalogue, so the three cannot disagree."""
    return [{"id": x["id"], "icon": x["icon"], "route": x["route"], "t": {"hi": x["hi"]["title"], "en": x["en"]["title"]}}
            for x in available(flags) if x["route"]]


def valid_ids(flags: dict | None = None) -> set[str]:
    """Ids a chip may carry for this learner. 'about' is always valid; a 'soon' feature never is."""
    return {x["id"] for x in available(flags)} | {ABOUT["id"]}


def route_of(fid: str) -> str | None:
    if fid == ABOUT["id"]:
        return ABOUT["route"]
    for x in FEATURES:
        if x["id"] == fid and x["status"] == "live":
            return x["route"]
    return None


def label_of(fid: str, lang: str) -> str:
    lg = "en" if lang == "en" else "hi"
    if fid == ABOUT["id"]:
        return ABOUT[lg]["title"]
    for x in FEATURES:
        if x["id"] == fid:
            return x[lg]["title"]
    return fid


def page(flags: dict | None, lang: str) -> dict:
    """GET /home/features: everything the Know About page draws, for this learner, in their language."""
    lg = "en" if lang == "en" else "hi"

    def card(x: dict) -> dict:
        c = x[lg]
        return {"id": x["id"], "icon": x["icon"], "title": c["title"], "desc": c["desc"], "best": c["best"],
                "status": x["status"], "route": x["route"] if x["status"] == "live" else None, "group": x["group"]}
    return {"lang": lg,
            "features": [card(x) for x in available(flags)] + [card(x) for x in upcoming()],
            "how": [{"title": t, "text": d} for t, d in HOW_IT_WORKS[lg]]}


def actions(ids, flags: dict | None, lang: str) -> list[dict]:
    """[{id, label, route}] for the ids that are valid for this learner, in order, no repeats, at most 3."""
    ok = valid_ids(flags)
    out, seen = [], set()
    for i in ids if isinstance(ids, (list, tuple)) else []:
        if isinstance(i, str) and i in ok and i not in seen:
            seen.add(i)
            out.append({"id": i, "label": label_of(i, lang), "route": route_of(i)})
        if len(out) >= 3:
            break
    return out


def catalog(flags: dict | None) -> str:
    """The prompt's list of what exists, and what does not - the only features the Home AI may mention."""
    lines = ["FEATURE IDS you may suggest (these exist; each is one tap away):"]
    for x in available(flags):
        lines.append(f"- {x['id']}: {x['en']['title']} - {x['en']['say']}")
    lines.append(f"- {ABOUT['id']}: Know About DuSu - a page that explains everything DuSu can do")
    soon = upcoming()
    if soon:
        lines.append("NOT AVAILABLE YET (no id; if asked, say honestly that it is coming and does not exist today; "
                     "never pretend, never promise a date): "
                     + "; ".join(f"{x['en']['title']} ({x['en']['say']})" for x in soon))
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------------------------
# Deterministic fallback: if the model's JSON is unusable, the learner still gets a sensible intent and buttons.
# Keywords are matched on a lowercased message, in BOTH scripts (speech recognition returns Devanagari for hi-IN).
# Order matters: the first group that matches wins, so the narrow ones come first.
_KW: list[tuple[str, tuple[str, ...]]] = [
    ("presentation_prep", ("presentation", "viva", "seminar", "speech", "प्रेजेंटेशन", "प्रेज़ेंटेशन", "प्रस्तुति", "भाषण", "वाइवा")),
    ("interview_prep", ("interview", "इंटरव्यू", "इंटरव्यु", "hr round", "placement", "प्लेसमेंट")),
    ("translate_help", ("translate", "translation", "meaning", "अनुवाद", "ट्रांसलेट", "मतलब", "कैसे बोलते", "कैसे कहते",
                        "कैसे बोलें", "कैसे कहें", "english में क्या", "इंग्लिश में क्या", "इंग्लिश में कैसे")),
    ("feature_discovery", ("what can you do", "what do you do", "features", "how does", "how do you work", "about dusu", "know about",
                           "क्या कर सकती", "क्या करती हो", "क्या कर सकते", "कैसे काम", "फीचर", "dusu क्या", "दुसु क्या",
                           "तुम क्या", "आप क्या कर", "डूसू क्या")),
    ("goal_progress", ("goal", "progress", "streak", "how far", "how much", "level", "rank", "score", "xp",
                       "गोल", "प्रगति", "कितना", "स्ट्रीक", "लेवल", "रैंक", "स्कोर", "तरक्की", "कहाँ तक")),
    ("daily_plan", ("plan", "today", "tasks", "to-do", "todo", "to do", "schedule", "routine", "agenda", "what should i do",
                    "प्लान", "आज", "टास्क", "काम", "क्या करना", "क्या करूँ", "क्या करूं", "शेड्यूल", "रूटीन")),
    ("confidence_practice", ("confidence", "nervous", "scared", "afraid", "shy", "hesitat", "stage fear", "anxious", "anxiety",
                             "कॉन्फिडेंस", "आत्मविश्वास", "डर", "घबरा", "झिझक", "शर्म", "नर्वस", "हिचक")),
    ("english_practice", ("english", "practice", "practise", "speak", "speaking", "fluency", "fluent", "grammar", "vocabulary",
                          "इंग्लिश", "अंग्रेज़ी", "अंग्रेजी", "प्रैक्टिस", "बोलना", "बोलने", "फ्लुएंसी", "ग्रामर")),
]

_DEFAULT_SUGGEST = {
    "daily_plan": ["daily_talk"],
    "goal_progress": ["journey"],
    "english_practice": ["face_to_face", "daily_talk"],
    "confidence_practice": ["face_to_face"],
    "interview_prep": ["interview"],
    "translate_help": ["learn"],
    "presentation_prep": ["practice_room", "face_to_face"],
    "feature_discovery": ["about"],
    "general_conversation": [],
}


def detect_intent(text: str) -> str:
    t = (text or "").lower()
    for intent, words in _KW:
        if any(w in t for w in words):
            return intent
    return "general_conversation"


def default_suggest(intent: str) -> list[str]:
    return list(_DEFAULT_SUGGEST.get(intent, []))


def fallback_reply(intent: str, lang: str) -> str:
    """What DuSu says when the model could not be used for a turn: short, true, and it keeps the learner moving."""
    if lang == "en":
        return {"daily_plan": "I don't have any saved tasks for you yet - planning isn't in DuSu yet. But tell me what is on your mind for today, and we can sort your priorities out loud.",
                "goal_progress": "Your Journey page shows exactly how far you have come - take a look. Want to tell me what you are working towards?",
                "feature_discovery": "I can talk with you, practise interviews, help you say things in English and track your journey. Tap Know About DuSu to see everything.",
                }.get(intent, "Sorry, I lost my words for a second. Could you say that once more?")
    return {"daily_plan": "अभी तुम्हारे कोई saved tasks मेरे पास नहीं हैं - planning अभी DuSu में नहीं आई है। पर बताओ आज दिमाग़ में क्या चल रहा है - चलो साथ में बोलकर priorities तय करें।",
            "goal_progress": "तुम्हारा Journey page साफ़ दिखाता है कि अब तक कितना सफ़र तय हुआ - एक बार देख लो। और बताओ, तुम्हारा अगला goal क्या है?",
            "feature_discovery": "मैं तुमसे बात कर सकती हूँ, interview की practice करा सकती हूँ, English में बोलना सिखा सकती हूँ और तुम्हारी journey track कर सकती हूँ। पूरी list के लिए Know About DuSu दबाओ।",
            }.get(intent, "सॉरी, एक सेकंड के लिए मैं शब्द भूल गई। एक बार फिर से बोल दो?")


# --------------------------------------------------------------------------------------------------------------------
# The user asked for natural, modern Hinglish - not the stiff textbook words. The prompt forbids these; this is the
# belt-and-braces pass for the one time in a while a model slips. Whole words only (Devanagari has no \b, so the
# boundaries are "not a Devanagari letter").
# Devanagari letters, vowel signs and digits - but NOT the danda / double danda (U+0964, U+0965): they end a sentence and must
# not count as part of the word in front of them.
_DEV = chr(0x900) + "-" + chr(0x963) + chr(0x966) + "-" + chr(0x97F)   # U+0900-0963 and U+0966-097F
_STIFF = [
    (r"सुप्रभात", "Good morning"),
    (r"शुभ\s*संध्या", "Good evening"),
    (r"शुभ\s*रात्रि", "Good night"),
    (r"शुभ\s*अपराह्न", "Good afternoon"),
    (r"नमस्कार", "Hi"),
    (r"अभिवादन", "Hello"),
    (r"प्राथमिकताएँ|प्राथमिकताएं|प्राथमिकताओं", "priorities"),
    (r"प्राथमिकता", "priority"),
    (r"कृपया", "please"),
    (r"धन्यवाद", "thanks"),
]
_STIFF_RE = [(re.compile(rf"(?<![{_DEV}]){p}(?![{_DEV}])"), r) for p, r in _STIFF]
# The intimate (तू) imperative used as an interjection - "देख, ..." / "चल, ..." / "सुन, ..." - becomes the friendly तुम form. Only when a comma
# follows, so a real verb stem ("देख लो", "सुन सकते") is never touched.
_TU_RE = re.compile(rf"(?<![{_DEV}])(देख|सुन|चल)(?=\s*,)")
_TU_FIX = {"देख": "देखो", "सुन": "सुनो", "चल": "चलो"}


def soften(text: str) -> str:
    out = text or ""
    for rx, rep in _STIFF_RE:
        out = rx.sub(rep, out)
    return _TU_RE.sub(lambda m: _TU_FIX[m.group(1)], out)
