"""Grammar Lab - the twelve units and four levels: names, formulas, what the Hindi ending signals, the traps Hindi speakers fall into (pure data).

Writing rules for every Hindi string here (the same rules as the rest of the new features, CLAUDE.md section 23): Devanagari for the Hindi words and Latin for the grammar terms and
example words; "tum" (तुम), never "aap" (आप), never "tu"; no second-person verb ending that guesses the learner's gender (no "रहे हो", "सकते हो"); imperatives and ergative forms
("तुमने लिखा है") are fine.  Nothing here has been read by a native speaker yet - `REVIEWED` says so and the owner's 100-item sample read is the gate before "Everyone".
"""

from __future__ import annotations

REVIEWED = False                      # set to True only after a native Hindi reader has signed off the strings below and the bank's samples
VERSION = 1

LEVELS = ("easy", "medium", "hard", "extra")
LEVEL_CODE = {"easy": "e", "medium": "m", "hard": "h", "extra": "x"}
LEVEL_NAME = {
    "easy":   {"en": "Easy", "hi": "आसान"},
    "medium": {"en": "Medium", "hi": "मध्यम"},
    "hard":   {"en": "Hard", "hi": "कठिन"},
    "extra":  {"en": "Extra-hard", "hi": "बहुत कठिन"},
}
LEVEL_GIST = {
    "easy":   {"en": "Short sentences, one clear time word.", "hi": "छोटे वाक्य, समय का एक साफ़ शब्द।"},
    "medium": {"en": "Negatives, questions and irregular verbs.", "hi": "negative, questions और irregular verbs।"},
    "hard":   {"en": "Two ideas in one sentence, since / for, longer sentences.", "hi": "एक वाक्य में दो बातें, since / for, लंबे वाक्य।"},
    "extra":  {"en": "The tricky ones: tenses that look alike.", "hi": "मुश्किल वाले: जो tenses एक जैसे दिखते हैं।"},
}

FAMILY_NAME = {
    "present": {"en": "Present", "hi": "Present (अभी का)"},
    "past":    {"en": "Past", "hi": "Past (बीता समय)"},
    "future":  {"en": "Future", "hi": "Future (आने वाला समय)"},
}
TYPE_NAME = {
    "simple": "Simple", "continuous": "Continuous", "perfect": "Perfect", "perfect_continuous": "Perfect Continuous",
}

# id -> (family, type, code)  - the code is the prefix of every item id in the bank
_ORDER = (
    ("present_simple", "present", "simple", "prs"), ("present_continuous", "present", "continuous", "prc"),
    ("present_perfect", "present", "perfect", "prp"), ("present_perfect_continuous", "present", "perfect_continuous", "prpc"),
    ("past_simple", "past", "simple", "pas"), ("past_continuous", "past", "continuous", "pac"),
    ("past_perfect", "past", "perfect", "pap"), ("past_perfect_continuous", "past", "perfect_continuous", "papc"),
    ("future_simple", "future", "simple", "fus"), ("future_continuous", "future", "continuous", "fuc"),
    ("future_perfect", "future", "perfect", "fup"), ("future_perfect_continuous", "future", "perfect_continuous", "fupc"),
)
UNITS = tuple(u[0] for u in _ORDER)
UNIT_CODE = {u[0]: u[3] for u in _ORDER}
CODE_UNIT = {u[3]: u[0] for u in _ORDER}

_NAMES = {u[0]: " ".join(w.capitalize() for w in u[0].split("_")) for u in _ORDER}

UNIT_META: dict = {
    "present_simple": {
        "gist": {"hi": "रोज़ की आदत, routine, या हमेशा सच रहने वाली बात।", "en": "Habits, routines and facts that are always true."},
        "formula": {"aff": "Subject + V1  (he / she / it → V1 + s/es)", "neg": "Subject + do/does + not + V1", "q": "Do/Does + subject + V1 ?"},
        "marker": {"hi": "Hindi verb के अंत में ता है / ती है / ते हैं / ता हूँ।", "en": "The Hindi verb ends in ता है / ती है / ते हैं / ता हूँ."},
        "example": {"hi": "वह रोज़ स्कूल जाता है।", "en": "He goes to school every day."},
    },
    "present_continuous": {
        "gist": {"hi": "जो काम अभी हो रहा है, या इन दिनों चल रहा है।", "en": "Something happening right now, or around these days."},
        "formula": {"aff": "Subject + am/is/are + V1 + ing", "neg": "Subject + am/is/are + not + V1 + ing", "q": "Am/Is/Are + subject + V1 + ing ?"},
        "marker": {"hi": "Hindi में रहा है / रही है / रहे हैं / रहा हूँ।", "en": "The Hindi verb has रहा है / रही है / रहे हैं / रहा हूँ."},
        "example": {"hi": "वह अभी खाना खा रहा है।", "en": "He is eating now."},
    },
    "present_perfect": {
        "gist": {"hi": "काम हो चुका है और उसका असर अभी भी है। बीते हुए तय समय (कल, पिछले साल) का ज़िक्र नहीं आता।", "en": "Something done, with a result that still matters now. No finished time (yesterday, last year)."},
        "formula": {"aff": "Subject + has/have + V3", "neg": "Subject + has/have + not + V3", "q": "Has/Have + subject + V3 ?"},
        "marker": {"hi": "Hindi में चुका है / चुकी है / चुके हैं, या लिया है / गया है / किया है (अभी का असर)।", "en": "The Hindi verb has चुका है / चुकी है / चुके हैं, or लिया है / गया है / किया है with a result now."},
        "example": {"hi": "उसने अपना काम ख़त्म कर लिया है।", "en": "He has finished his work."},
    },
    "present_perfect_continuous": {
        "gist": {"hi": "जो काम कुछ समय पहले शुरू हुआ और अब भी चल रहा है: कब से, कितनी देर से।", "en": "Something that began earlier and is still going on: since when, for how long."},
        "formula": {"aff": "Subject + has/have + been + V1 + ing", "neg": "Subject + has/have + not + been + V1 + ing", "q": "Has/Have + subject + been + V1 + ing ?"},
        "marker": {"hi": "Hindi में 'से ... रहा है / रही है' (दो घंटे से पढ़ रहा है)।", "en": "The Hindi has 'से ... रहा है / रही है' (दो घंटे से पढ़ रहा है)."},
        "example": {"hi": "वह सुबह से पढ़ रहा है।", "en": "He has been studying since morning."},
    },
    "past_simple": {
        "gist": {"hi": "बीते समय में ख़त्म हो चुका काम: कल, पिछले हफ़्ते, दो दिन पहले।", "en": "A finished action at a finished time: yesterday, last week, two days ago."},
        "formula": {"aff": "Subject + V2", "neg": "Subject + did + not + V1", "q": "Did + subject + V1 ?"},
        "marker": {"hi": "Hindi में आया / गई / खाया / देखा, या ... था / थी।", "en": "The Hindi verb is a plain past form: आया / गई / खाया / देखा, or ... था / थी."},
        "example": {"hi": "वह कल आया।", "en": "He came yesterday."},
    },
    "past_continuous": {
        "gist": {"hi": "बीते समय में किसी पल पर जो काम चल रहा था।", "en": "Something that was in progress at a moment in the past."},
        "formula": {"aff": "Subject + was/were + V1 + ing", "neg": "Subject + was/were + not + V1 + ing", "q": "Was/Were + subject + V1 + ing ?"},
        "marker": {"hi": "Hindi में रहा था / रही थी / रहे थे।", "en": "The Hindi verb has रहा था / रही थी / रहे थे."},
        "example": {"hi": "वह उस समय पढ़ रहा था।", "en": "He was studying at that time."},
    },
    "past_perfect": {
        "gist": {"hi": "बीते समय की दो घटनाओं में से जो पहले हो चुकी थी।", "en": "Of two past events, the one that had already happened."},
        "formula": {"aff": "Subject + had + V3", "neg": "Subject + had + not + V3", "q": "Had + subject + V3 ?"},
        "marker": {"hi": "Hindi में चुका था / चुकी थी / चुके थे।", "en": "The Hindi verb has चुका था / चुकी थी / चुके थे."},
        "example": {"hi": "मेरे पहुँचने से पहले ट्रेन जा चुकी थी।", "en": "The train had left before I reached."},
    },
    "past_perfect_continuous": {
        "gist": {"hi": "बीते समय के किसी पल तक जो काम कुछ समय से चल रहा था।", "en": "Something that had been going on for some time up to a past moment."},
        "formula": {"aff": "Subject + had + been + V1 + ing", "neg": "Subject + had + not + been + V1 + ing", "q": "Had + subject + been + V1 + ing ?"},
        "marker": {"hi": "Hindi में 'से ... रहा था / रही थी'।", "en": "The Hindi has 'से ... रहा था / रही थी'."},
        "example": {"hi": "वह दो घंटे से इंतज़ार कर रहा था।", "en": "He had been waiting for two hours."},
    },
    "future_simple": {
        "gist": {"hi": "आगे होने वाला काम, वादा, अभी लिया गया फ़ैसला या अनुमान।", "en": "Something that will happen, a promise, a decision made now, or a guess."},
        "formula": {"aff": "Subject + will + V1", "neg": "Subject + will + not + V1", "q": "Will + subject + V1 ?"},
        "marker": {"hi": "Hindi verb के अंत में ेगा / ेगी / ेंगे / ूँगा।", "en": "The Hindi verb ends in ेगा / ेगी / ेंगे / ूँगा."},
        "example": {"hi": "वह कल आएगा।", "en": "He will come tomorrow."},
    },
    "future_continuous": {
        "gist": {"hi": "भविष्य के किसी समय पर जो काम चल रहा होगा।", "en": "Something that will be in progress at a time in the future."},
        "formula": {"aff": "Subject + will + be + V1 + ing", "neg": "Subject + will + not + be + V1 + ing", "q": "Will + subject + be + V1 + ing ?"},
        "marker": {"hi": "Hindi में रहा होगा / रही होगी / रहे होंगे।", "en": "The Hindi verb has रहा होगा / रही होगी / रहे होंगे."},
        "example": {"hi": "वह कल पाँच बजे पढ़ रहा होगा।", "en": "He will be studying at five tomorrow."},
    },
    "future_perfect": {
        "gist": {"hi": "भविष्य के किसी समय तक जो काम पूरा हो चुका होगा।", "en": "Something that will already be finished by a time in the future."},
        "formula": {"aff": "Subject + will + have + V3", "neg": "Subject + will + not + have + V3", "q": "Will + subject + have + V3 ?"},
        "marker": {"hi": "Hindi में चुका होगा / चुकी होगी / चुके होंगे।", "en": "The Hindi verb has चुका होगा / चुकी होगी / चुके होंगे."},
        "example": {"hi": "शाम तक वह काम ख़त्म कर चुका होगा।", "en": "He will have finished the work by evening."},
    },
    "future_perfect_continuous": {
        "gist": {"hi": "भविष्य के किसी समय तक जो काम इतने समय से चलता आ रहा होगा।", "en": "How long something will have been going on by a time in the future."},
        "formula": {"aff": "Subject + will + have + been + V1 + ing", "neg": "Subject + will + not + have + been + V1 + ing", "q": "Will + subject + have + been + V1 + ing ?"},
        "marker": {"hi": "Hindi में 'तक ... से ... रहा होगा'।", "en": "The Hindi has 'तक ... से ... रहा होगा'."},
        "example": {"hi": "अगले महीने तक वह यहाँ दो साल से काम कर रहा होगा।", "en": "By next month he will have been working here for two years."},
    },
}
for _u in UNITS:
    UNIT_META[_u]["name"] = {"en": _NAMES[_u], "hi": _NAMES[_u]}          # the grammar term stays Latin in both languages
    UNIT_META[_u]["family"] = next(o[1] for o in _ORDER if o[0] == _u)
    UNIT_META[_u]["type"] = next(o[2] for o in _ORDER if o[0] == _u)
    UNIT_META[_u]["code"] = UNIT_CODE[_u]

# the traps an item can carry (item["trap"]) - shown after a wrong answer on that item
TRAPS: dict = {
    "since_for": {"hi": "'से' का मतलब since या for है, और 'से ... रहा है' आम तौर पर Perfect Continuous होता है, Present Continuous नहीं: 'I have been living here since 2015' (I am living नहीं)।",
                  "en": "Hindi 'से' is since or for, and 'से ... रहा है' is normally a Perfect Continuous, not a Present Continuous: 'I have been living here since 2015' (not 'I am living')."},
    "pp_vs_ps": {"hi": "बीते हुए तय समय (yesterday, last year, in 2010, ago) के साथ Present Perfect नहीं आता, वहाँ Past Simple आता है: 'I saw him yesterday'।",
                 "en": "With a finished time (yesterday, last year, in 2010, ago) use the Past Simple, not the Present Perfect: 'I saw him yesterday'."},
    "stative": {"hi": "know, like, love, want, need, believe जैसे verbs आम तौर पर -ing में नहीं आते: 'I know him' (I am knowing नहीं)।",
                "en": "Verbs like know, like, love, want, need, believe are normally not used with -ing: 'I know him' (not 'I am knowing')."},
    "time_clause": {"hi": "when / before / after / if / until के बाद वाले हिस्से में भविष्य के लिए will नहीं लगता: 'when he comes' ('when he will come' नहीं)।",
                    "en": "After when / before / after / if / until, do not use will for the future: 'when he comes' (not 'when he will come')."},
    "ps_pc": {"hi": "आदत या routine = Simple, किसी पल पर चल रहा काम = Continuous। Present: 'He plays every day' / 'He is playing now'। Past: 'He played every day' / 'He was playing at five'।",
              "en": "A habit or routine = Simple, something in progress at a moment = Continuous. Present: 'He plays every day' / 'He is playing now'. Past: 'He played every day' / 'He was playing at five'."},
    "ps_vs_pp_past": {"hi": "दो बीती घटनाओं में जो पहले हो चुकी थी उसके लिए had + V3, बाद वाली के लिए Past Simple: 'When I reached, the train had left'।",
                      "en": "Of two past events, use had + V3 for the earlier one and the Past Simple for the later one: 'When I reached, the train had left'."},
    "irregular": {"hi": "यह irregular verb है: उसके V2 और V3 रटने पड़ते हैं (go – went – gone)।", "en": "This is an irregular verb: learn its V2 and V3 (go – went – gone)."},
    "question_order": {"hi": "Question में helping verb (do / does / did / is / are / have / will ...) subject से पहले आता है।", "en": "In a question the helping verb (do / does / did / is / are / have / will ...) comes before the subject."},
    "negative": {"hi": "Negative में not helping verb के बाद आता है, और do / does / did के बाद verb की 1st form (V1) आती है।", "en": "In a negative, not comes after the helping verb, and after do / does / did the verb stays in V1."},
    "third_person": {"hi": "he / she / it (एकवचन) के साथ Present Simple में verb में -s / -es लगता है।", "en": "With he / she / it, the Present Simple verb takes -s / -es."},
}
TRAP_IDS = frozenset(TRAPS)


def unit_name(unit: str) -> str:
    return UNIT_META[unit]["name"]["en"]


def level_index(level: str) -> int:
    return LEVELS.index(level)
