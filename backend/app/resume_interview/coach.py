"""Job Interview Practice - the COACHING layer of the report: what the learner should work on, why, how - and, next time, whether it worked.

Pure functions (no database, no network, no model): everything here is computed from the answers that were already scored, so a report can always be
(re)built, costs nothing and cannot fail on quota. Every sentence is either a fixed text from the catalogue below or a counted fact from the learner's own
answers - nothing is invented.

* HABITS - the style weaknesses that do not depend on WHICH questions were asked (no number in the answer, no result, too short, no tool named, filler words,
  pace, long pauses, a repeating grammar slip). They are counted per interview, so two interviews for two different jobs can be compared.
* build_weaknesses - up to 5 ranked weakness cards: what was seen, why it matters, how to fix it, a short drill, the answers it happened in, examples.
* pick_focus - the (up to) 3 improvement points saved with the interview, habits first (they can be checked next time).
* compare_progress - the NEXT interview's report: for each saved focus point, better / the same / worse, with the real numbers.

The catalogue is written in English and in Hinglish (Roman letters; tum / aap register, never the rude 'tu').
"""

from __future__ import annotations

from . import rules

REPORT_VERSION = 2                                   # reports below this have no coaching fields; they are upgraded (computed, no model) the first time they are read
HABITS = ("no_number", "no_result", "short", "named_item", "fillers", "pace", "pauses", "grammar")
_GRAMMAR_TYPES = ("grammar", "tense", "article", "word_choice")
_ORDER = ("grammar", "no_number", "no_result", "named_item", "short", "relevance", "structure", "fillers", "pace", "pauses", "language", "delivery", "coverage")

# --------------------------------------------------------------------------------------------- the catalogue: title, why it matters, how to fix it, a drill, the goal
WEAK: dict[str, dict[str, dict]] = {
    "no_number": {
        "en": {"title": "Add numbers to your stories",
               "why": "Interviewers believe and remember results they can picture. “I improved reporting” is forgettable; “I cut reporting from 2 days to 3 hours” is not.",
               "how": ["For every project, choose one number: how many, how much, how fast or how often.",
                       "Use this pattern: I did [what], which moved [measure] from [before] to [after].",
                       "If you do not know the exact figure, give an honest estimate and say that it is an estimate."],
               "drill": "Pick your three main projects. Write one sentence for each that contains a number, then say each sentence aloud twice.",
               "goal": "A number or measurable result in every project answer"},
        "hinglish": {"title": "Apni stories mein number add karo",
                     "why": "Interviewer ko wahi result yaad rehta hai jo woh imagine kar sake. “Maine reporting improve ki” yaad nahi rehta; “Maine reporting 2 din se 3 ghante kar di” yaad rehta hai.",
                     "how": ["Har project ke liye ek number chuno: kitna, kitni tezi se, kitni baar.",
                             "Is pattern ka use karo: Maine [kya kiya], jisse [measure] [pehle] se [baad mein] ho gaya.",
                             "Exact figure yaad nahi? Honest estimate do aur bolo ki yeh estimate hai."],
                     "drill": "Apne teen main projects lo. Har ek ke liye ek sentence likho jisme number ho, phir har sentence ko do baar zor se bolo.",
                     "goal": "Har project answer mein ek number ya measurable result"}},
    "no_result": {
        "en": {"title": "End every story with the result",
               "why": "A story without a result leaves the interviewer asking “so what?”. The result is the part they write down.",
               "how": ["Finish with “As a result, …” or “This led to …”.",
                       "Say what changed for the team, the customer or the business, not only what you did.",
                       "If it did not work out, say what you learned and what you would change."],
               "drill": "Take two answers you gave today and add one closing sentence that starts with “As a result”. Say them again.",
               "goal": "A clear result at the end of every story"},
        "hinglish": {"title": "Har story result par khatam karo",
                     "why": "Result ke bina story adhuri lagti hai: interviewer sochta hai “toh phir?”. Result hi woh hissa hai jo woh note karte hain.",
                     "how": ["End mein bolo “As a result, …” ya “Isse …”.",
                             "Sirf yeh mat batao ki aapne kya kiya, yeh bhi batao ki team, customer ya business mein kya badla.",
                             "Agar kaam nahi bana, toh batao ki aapne kya seekha aur ab kya alag karoge."],
                     "drill": "Aaj ke do answers lo aur ek closing sentence add karo jo “As a result” se shuru ho. Phir dobara bolo.",
                     "goal": "Har story ke end mein clear result"}},
    "short": {
        "en": {"title": "Give fuller answers",
               "why": "Very short answers sound unprepared and give the interviewer nothing to ask about; rambling ones lose them. The sweet spot is 45 to 90 seconds.",
               "how": ["Use three beats: the situation, what you did, the result.",
                       "Add one concrete example or detail to each answer.",
                       "Stop right after the result."],
               "drill": "Answer “Tell me about a project you are proud of” in three sentences (situation, action, result). Time yourself: aim for about a minute.",
               "goal": "45 to 90 seconds on every project answer"},
        "hinglish": {"title": "Poore answers do",
                     "why": "Bahut chhote answers se lagta hai ki taiyaari nahi hai, aur interviewer ke paas puchne ko kuch nahi bachta; bahut lambe answers mein woh kho jaate hain. Sahi range 45 se 90 second hai.",
                     "how": ["Teen hisse rakho: situation, aapne kya kiya, result.",
                             "Har answer mein ek concrete example ya detail jodo.",
                             "Result bolkar ruk jao."],
                     "drill": "“Tell me about a project you are proud of” ka answer sirf teen sentences mein do: situation, action, result. Timer lagao: lagbhag ek minute.",
                     "goal": "Har project answer 45 se 90 second ka"}},
    "named_item": {
        "en": {"title": "Name your tools and skills",
               "why": "Saying the tool or method by name proves you really used it, and it lets the interviewer match you to the job's requirements.",
               "how": ["Name the tool, language or method in the first sentence about a project (for example SQL, Power BI, Python).",
                       "Say in a few words what you used it for.",
                       "Use the same words as the job description when they are true for you."],
               "drill": "Write down five tools or skills the job asks for. For each one, say one sentence about where you used it.",
               "goal": "Name the tool or skill you used in every project answer"},
        "hinglish": {"title": "Tools aur skills ka naam lo",
                     "why": "Tool ya method ka naam lene se saabit hota hai ki aapne sach mein use kiya, aur interviewer aapko job ki requirements se match kar paata hai.",
                     "how": ["Project ke pehle sentence mein hi tool ya language ka naam lo (jaise SQL, Power BI, Python).",
                             "Kuch shabdon mein batao ki use kis kaam ke liye kiya.",
                             "Job description ke wahi shabd use karo, jab woh aapke liye sach ho."],
                     "drill": "Job jo paanch tools ya skills maangti hai unhe likho. Har ek ke liye ek sentence bolo ki kahan use kiya.",
                     "goal": "Har project answer mein use kiye gaye tool ya skill ka naam"}},
    "fillers": {
        "en": {"title": "Cut the filler words",
               "why": "Words like “basically” and “you know” are normal, but too many make you sound unsure. A short silence sounds more confident.",
               "how": ["When you feel a filler coming, pause quietly for one second instead.",
                       "Slow down slightly at the start of each sentence so you have time to plan the next words.",
                       "Pick your most common filler: notice it, then replace it with a pause."],
               "drill": "Talk for one minute about your day without saying “um”, “basically” or “you know”. Record it and listen back.",
               "goal": "Fewer than 2 filler words per 100 words"},
        "hinglish": {"title": "Filler words kam karo",
                     "why": "“Basically” aur “you know” jaise words normal hain, par zyada ho jaayein toh aap unsure lagte ho. Ek chhota pause zyada confident lagta hai.",
                     "how": ["Filler aate hi ek second chup raho.",
                             "Har sentence ki shuruaat thodi dheere karo, taaki agle words soch sako.",
                             "Apna sabse common filler pehchano: use notice karo, phir pause se badal do."],
                     "drill": "Ek minute apne din ke baare mein bolo, bina “um”, “basically” ya “you know” bole. Record karke suno.",
                     "goal": "100 words mein 2 se kam filler words"}},
    "pace": {
        "en": {"title": "Steady your pace",
               "why": "Speaking too fast makes you hard to follow; too slowly loses energy. About 110 to 150 words a minute is easy to listen to.",
               "how": ["If you rush: breathe at the end of each sentence and slow down on numbers and names.",
                       "If you drag: practise with a timer and finish a one-minute answer in one minute.",
                       "Listen to one recording at normal speed and mark where your speed changes."],
               "drill": "Read one paragraph of your own resume aloud with a timer: aim for about 130 words a minute.",
               "goal": "A steady pace of about 110 to 150 words a minute"},
        "hinglish": {"title": "Speed steady rakho",
                     "why": "Bahut tez bologe toh samajhna mushkil; bahut dheere bologe toh energy girti hai. Lagbhag 110 se 150 words per minute sunne mein aaram dayak hai.",
                     "how": ["Agar jaldi bolte ho: har sentence ke end mein saans lo aur numbers aur names par dheere bolo.",
                             "Agar dheere bolte ho: timer ke saath practise karo aur ek minute ka answer ek minute mein poora karo.",
                             "Apni recording ek baar normal speed par suno aur note karo kahan speed badli."],
                     "drill": "Apne resume ka ek paragraph timer ke saath zor se padho: lagbhag 130 words per minute ka target.",
                     "goal": "Steady speed: lagbhag 110 se 150 words per minute"}},
    "pauses": {
        "en": {"title": "Fewer long pauses",
               "why": "Long gaps break the story and make the interviewer wonder whether you lost your thread.",
               "how": ["Take a breath, then use a bridge phrase such as “Let me think for a second”.",
                       "Plan the first sentence before you start and the result before you finish.",
                       "Keep three keywords in mind for each story: situation, action, result."],
               "drill": "Answer three questions in a row and never stop for more than two seconds. A bridge phrase is fine.",
               "goal": "No long pause inside an answer"},
        "hinglish": {"title": "Lambe pauses kam karo",
                     "why": "Lambe gap se story toot jaati hai aur interviewer ko lagta hai ki aap dhaaga kho baithe.",
                     "how": ["Saans lo aur ek bridge phrase bolo, jaise “Let me think for a second”.",
                             "Shuru karne se pehle pehla sentence aur khatam karne se pehle result soch lo.",
                             "Har story ke teen keywords yaad rakho: situation, action, result."],
                     "drill": "Lagaataar teen questions ka answer do, kisi bhi gap ko do second se zyada mat khinchne do. Bridge phrase chalega.",
                     "goal": "Answer ke beech mein koi lamba pause nahi"}},
    "grammar": {
        "en": {"title": "Fix the grammar slip that keeps coming back",
               "why": "The same mistake in several answers is a habit, and a habit is easy to fix once you can see it.",
               "how": ["Say each corrected sentence below aloud three times.",
                       "Make up two new sentences of your own with the same pattern.",
                       "In your next interview, slow down just a little on those words."],
               "drill": "Say each corrected sentence below three times, then make up two new sentences with the same pattern.",
               "goal": "No repeated grammar slip of the same kind"},
        "hinglish": {"title": "Baar-baar aane wali grammar galti sudharo",
                     "why": "Ek hi galti kai answers mein aaye toh woh aadat hai, aur aadat ko pehchaan lo toh sudharna aasaan hota hai.",
                     "how": ["Neeche diye gaye sahi sentences ko teen-teen baar zor se bolo.",
                             "Usi pattern ke do naye sentences khud banao.",
                             "Agle interview mein un words par thoda dheere bolo."],
                     "drill": "Neeche ke har sahi sentence ko teen baar bolo, phir usi pattern ke do naye sentences banao.",
                     "goal": "Ek hi type ki grammar galti repeat nahi hogi"}},
    "relevance": {
        "en": {"title": "Answer the question that was asked",
               "why": "Interviewers notice when an answer drifts away from their question, even when the story itself is good.",
               "how": ["Start with a direct answer in one sentence that uses a key word from the question.",
                       "Then give the example that proves it.",
                       "Before you finish, check: did I answer exactly what was asked?"],
               "drill": "For each of today's questions, write the one-sentence direct answer you could have started with.",
               "goal": "A direct answer in the first sentence"},
        "hinglish": {"title": "Jo sawal pucha gaya uska jawab do",
                     "why": "Interviewer turant notice karte hain jab answer sawal se hat jaata hai, chahe story achhi ho.",
                     "how": ["Pehle sentence mein seedha jawab do, sawal ka ek key word use karke.",
                             "Phir woh example do jo use saabit kare.",
                             "Khatam karne se pehle check karo: kya maine exactly wahi bataya jo pucha tha?"],
                     "drill": "Aaj ke har sawal ke liye woh ek sentence likho jisse aap seedha jawab shuru kar sakte the.",
                     "goal": "Pehle sentence mein seedha jawab"}},
    "structure": {
        "en": {"title": "Give each answer a clear order",
               "why": "An answer with a clear order is easy to follow and easy to remember. The simplest order is Situation, Action, Result.",
               "how": ["Say one sentence about the situation.",
                       "Say what YOU did (use “I”, not only “we”).",
                       "End with the result and, if you can, what you learned."],
               "drill": "Take one project and tell it in exactly three sentences: situation, action, result.",
               "goal": "Situation, action, result in every answer"},
        "hinglish": {"title": "Har answer ko ek clear order do",
                     "why": "Clear order wala answer samajhna aur yaad rakhna aasaan hota hai. Sabse simple order: Situation, Action, Result.",
                     "how": ["Situation ke baare mein ek sentence bolo.",
                             "Batao ki AAPNE kya kiya (“I” bolo, sirf “we” nahi).",
                             "Result par khatam karo aur ho sake toh bolo ki kya seekha."],
                     "drill": "Ek project lo aur use bilkul teen sentences mein batao: situation, action, result.",
                     "goal": "Har answer mein situation, action, result"}},
    "language": {
        "en": {"title": "Make your English clearer",
               "why": "Clear, simple sentences matter more than big words. Basic grammar slips distract from your good ideas.",
               "how": ["Prefer short sentences with one idea each.",
                       "Use the corrections shown with your answers: repeat them aloud.",
                       "Listen to one answer again and write down any sentence you stumbled on."],
               "drill": "Listen to one answer again, write down two sentences you stumbled on, and say them again clearly.",
               "goal": "Short, clear sentences"},
        "hinglish": {"title": "Apni English aur saaf banao",
                     "why": "Saaf, simple sentences bade words se zyada kaam aate hain. Basic grammar ki galtiyan achhe ideas se dhyaan hata deti hain.",
                     "how": ["Chhote sentences use karo, har sentence mein ek idea.",
                             "Answers ke saath dikhaye gaye corrections ko zor se dohrao.",
                             "Ek answer dobara suno aur woh sentences likho jahan aap atke."],
                     "drill": "Ek answer dobara suno, woh do sentences likho jahan aap atke, aur unhe saaf tareeke se dobara bolo.",
                     "goal": "Chhote, saaf sentences"}},
    "delivery": {
        "en": {"title": "Speak with a steadier delivery",
               "why": "A steady delivery makes you sound confident and makes your points easy to follow.",
               "how": ["Think the whole sentence before you start it, instead of stopping in the middle.",
                       "Speak slightly slower and more clearly than feels natural.",
                       "Listen to your recording and pick one thing to fix in the next one."],
               "drill": "Record one answer, listen to it, and choose one thing to fix in your next recording.",
               "goal": "A steady, clear delivery"},
        "hinglish": {"title": "Delivery ko aur steady banao",
                     "why": "Steady delivery se aap confident lagte ho, aur aapki baat samajhna aasaan hota hai.",
                     "how": ["Sentence ke beech mein ruko nahi: pehle poora sentence soch lo.",
                             "Apni natural speed se thoda dheere aur clear bolo.",
                             "Apni recording suno aur ek cheez chuno jise agli baar theek karna hai."],
                     "drill": "Ek answer record karo, suno, aur ek cheez chuno jise agli recording mein theek karna hai.",
                     "goal": "Steady, clear delivery"}},
    "coverage": {
        "en": {"title": "Show the skills the job asks for",
               "why": "The interviewer checks your answers against the job's requirements. If none of your answers touches a requirement, they cannot tick it.",
               "how": ["For each missing requirement below, prepare one short example from a project, a course or practice.",
                       "With no experience yet, say what you have learned or built that is close, and how you would get up to speed.",
                       "Use the requirement's own words so the match is obvious."],
               "drill": "Pick the first requirement below and give a 45-second answer about it.",
               "goal": "At least one example for every key requirement"},
        "hinglish": {"title": "Job ki maangi hui skills dikhao",
                     "why": "Interviewer aapke answers ko job ki requirements se milata hai. Agar koi answer kisi requirement ko chhua hi nahi, toh woh tick nahi kar sakte.",
                     "how": ["Neeche di gayi har missing requirement ke liye ek chhota example taiyaar karo: project, course ya practice se.",
                             "Agar experience nahi hai, toh batao ki kya seekha ya banaya jo uske kareeb hai, aur kaise jaldi seekhoge.",
                             "Requirement ke apne shabd use karo, taaki match saaf dikhe."],
                     "drill": "Neeche ki pehli requirement lo aur uspar 45 second ka answer bolo.",
                     "goal": "Har key requirement ke liye kam se kam ek example"}},
}

# "what we saw" - one fixed sentence per weakness, filled with the counted facts
SEEN = {
    "en": {"no_number": "{c} of {n} answers had no number or measurable result.", "no_result": "{c} of {n} answers had no clear result.",
           "short": "{c} of {n} answers were under 40 words.", "named_item": "{c} of {n} answers did not name a tool or skill.",
           "fillers": "{t} filler words in {w} words ({p} per 100){top}.", "pace": "The pace was outside 95 to 165 words a minute in {c} of {n} answers{dir}.",
           "pauses": "Long pauses (four or more) in {c} of {n} answers.", "grammar": "The same kind of slip (“{type}”) came back {c} times.",
           "relevance": "Relevance (does the answer address the question?) scored {s} out of 100.", "structure": "Structure (a clear order) scored {s} out of 100.",
           "language": "Language (grammar and word choice) scored {s} out of 100.", "delivery": "Delivery scored {s} out of 100.",
           "coverage": "{k} of the job's requirements were not touched by any of your answers."},
    "hinglish": {"no_number": "{n} mein se {c} answers mein koi number ya measurable result nahi tha.", "no_result": "{n} mein se {c} answers mein clear result nahi tha.",
                 "short": "{n} mein se {c} answers 40 words se chhote the.", "named_item": "{n} mein se {c} answers mein kisi tool ya skill ka naam nahi tha.",
                 "fillers": "{w} words mein {t} filler words ({p} per 100){top}.", "pace": "{n} mein se {c} answers mein speed 95 se 165 words per minute ke bahar thi{dir}.",
                 "pauses": "{n} mein se {c} answers mein lambe pauses the (chaar ya zyada).", "grammar": "Ek hi type ki galti (“{type}”) {c} baar aayi.",
                 "relevance": "Relevance (answer sawal ka jawab deta hai?) ka score {s} out of 100 raha.", "structure": "Structure (clear order) ka score {s} out of 100 raha.",
                 "language": "Language (grammar aur word choice) ka score {s} out of 100 raha.", "delivery": "Delivery ka score {s} out of 100 raha.",
                 "coverage": "Job ki {k} requirements ko aapke kisi bhi answer ne chhua nahi."},
}
STATUS_NOTE = {
    "en": {"improved": "Better than last time.", "same": "About the same: keep working on it.", "worse": "Slipped back: make this the first thing you practise."},
    "hinglish": {"improved": "Pichhli baar se behtar.", "same": "Lagbhag waisa hi: ispar kaam karte raho.", "worse": "Peeche chala gaya: ise sabse pehle practise karo."},
}
PROGRESS_SUMMARY = {
    "en": {"all": "All {t} focus points improved. Well done.", "some": "{i} of {t} focus points improved.", "none": "No focus point has improved yet: keep practising the same ones."},
    "hinglish": {"all": "Saare {t} focus points behtar hue. Shabaash.", "some": "{t} mein se {i} focus points behtar hue.", "none": "Abhi tak koi focus point behtar nahi hua: unhi par practise karte raho."},
}


def _lang(lang: str) -> str:
    return lang if lang in ("en", "hinglish") else "en"


# --------------------------------------------------------------------------------------------- habits: counted per interview, comparable across interviews
def _fb(t: dict) -> dict:
    return t.get("feedback") or {}


def _real(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("status") == "answered" and t.get("real")]


def habit_metrics(turns: list[dict]) -> dict:
    """Counts of the style habits over the REAL answers: {"n": answers, "no_number": {"c": count, "of": answers it could be judged on}, ... , "fillers_per100": x, "mistakes_per100": y}."""
    real = _real(turns)
    ev = lambda t: _fb(t).get("evidence") or {}                      # noqa: E731
    dl = lambda t: _fb(t).get("delivery") or {}                      # noqa: E731
    with_ev = [t for t in real if ev(t)]

    def cnt(pred, pool):
        return {"c": sum(1 for t in pool if pred(t)), "of": len(pool)}
    words = sum(int(t.get("answer_words") or 0) for t in real)
    fill_total = sum(int(f.get("n") or 0) for t in real for f in (dl(t).get("fillers") or []))
    judged = [t for t in real if isinstance(t.get("scores"), dict) and t["scores"].get("relevance") is not None]
    j_words = sum(int(t.get("answer_words") or 0) for t in judged)
    mist = [m for t in judged for m in (_fb(t).get("mistakes") or []) if m.get("type") in _GRAMMAR_TYPES]
    with_wpm = [t for t in real if dl(t).get("wpm")]
    measured = [t for t in real if dl(t).get("measured")]
    return {
        "n": len(real), "words": words,
        "no_number": cnt(lambda t: not ev(t).get("has_number"), with_ev), "no_result": cnt(lambda t: not ev(t).get("has_result"), with_ev),
        "named_item": cnt(lambda t: not ev(t).get("named_item"), with_ev), "short": cnt(lambda t: 0 < int(t.get("answer_words") or 0) < 40, real),
        "pace": cnt(lambda t: not 95 <= dl(t)["wpm"] <= 165, with_wpm), "pauses": cnt(lambda t: (dl(t).get("pauses") or 0) >= 4, measured),
        "fillers": fill_total, "fillers_per100": round(100.0 * fill_total / max(1, words), 1),
        "mistakes": len(mist), "mistakes_per100": round(100.0 * len(mist) / max(1, j_words), 1), "judged": len(judged),
    }


def _significant(c: int, n: int) -> bool:
    return c >= 2 and n > 0 and c / n >= 0.34


def _affected(real: list[dict], pred) -> list[int]:
    return [t["idx"] for t in real if t.get("idx") is not None and pred(t)]


def _example_answer(real: list[dict], affected: list[int]) -> dict | None:
    """The learner's OWN stronger answer (written for them in this interview) to the first affected question: a model for the fix, in their words and facts."""
    for t in real:
        if t.get("idx") in affected and _fb(t).get("better_answer"):
            return {"q": t["idx"], "question": t.get("question") or "", "text": str(_fb(t)["better_answer"])[:320]}
    return None


def build_weaknesses(turns: list[dict], report: dict, habits: dict, lang: str) -> list[dict]:
    """Up to 5 ranked weakness cards. A card: key, title, severity (high / medium / low), seen (counted facts), why, how[], drill, goal, tracked (can the next report check it?),
    answers[] (the questions it happened in), examples[] (the learner's own slips with the fix), model (the learner's own stronger answer to one of them), items[] (job requirements)."""
    lg = _lang(lang)
    real = _real(turns)
    n = habits["n"]
    if not n:
        return []
    ev = lambda t: _fb(t).get("evidence") or {}                      # noqa: E731
    dl = lambda t: _fb(t).get("delivery") or {}                      # noqa: E731
    cands: list[dict] = []

    def add(key, severity, seen_vars, answers=None, examples=None, items=None):
        w = WEAK[key][lg]
        cands.append({"key": key, "title": w["title"], "severity_n": severity, "seen": SEEN[lg][key].format(**seen_vars), "why": w["why"], "how": list(w["how"]),
                      "drill": w["drill"], "goal": w["goal"], "tracked": key in HABITS, "answers": answers or [], "examples": examples or [], "items": items or []})

    for key, pred in (("no_number", lambda t: ev(t) and not ev(t).get("has_number")), ("no_result", lambda t: ev(t) and not ev(t).get("has_result")),
                      ("named_item", lambda t: ev(t) and not ev(t).get("named_item")), ("short", lambda t: 0 < int(t.get("answer_words") or 0) < 40)):
        h = habits[key]
        if _significant(h["c"], h["of"]):
            add(key, h["c"] / h["of"], {"c": h["c"], "n": h["of"]}, answers=_affected(real, pred))
    if habits["fillers"] >= 3 and habits["fillers_per100"] >= 1.5:
        tot: dict[str, int] = {}
        for t in real:
            for f in dl(t).get("fillers") or []:
                tot[f["word"]] = tot.get(f["word"], 0) + int(f.get("n") or 0)
        top = max(tot.items(), key=lambda kv: kv[1])[0] if tot else ""
        topt = (f"; most often “{top}”" if lg == "en" else f"; sabse zyada “{top}”") if top else ""
        add("fillers", min(1.0, habits["fillers_per100"] / 6.0), {"t": habits["fillers"], "w": habits["words"], "p": habits["fillers_per100"], "top": topt},
            answers=_affected(real, lambda t: any(f.get("n") for f in dl(t).get("fillers") or [])))
    h = habits["pace"]
    if _significant(h["c"], h["of"]):
        fast = sum(1 for t in real if dl(t).get("wpm") and dl(t)["wpm"] > 165)
        slow = sum(1 for t in real if dl(t).get("wpm") and dl(t)["wpm"] < 95)
        if fast and slow:
            d = f" ({fast} too fast, {slow} too slow)" if lg == "en" else f" ({fast} bahut tez, {slow} bahut dheere)"
        elif fast:
            d = " (too fast)" if lg == "en" else " (bahut tez)"
        elif slow:
            d = " (too slow)" if lg == "en" else " (bahut dheere)"
        else:
            d = ""
        add("pace", h["c"] / h["of"], {"c": h["c"], "n": h["of"], "dir": d}, answers=_affected(real, lambda t: dl(t).get("wpm") and not 95 <= dl(t)["wpm"] <= 165))
    h = habits["pauses"]
    if _significant(h["c"], h["of"]):
        add("pauses", h["c"] / h["of"], {"c": h["c"], "n": h["of"]}, answers=_affected(real, lambda t: (dl(t).get("pauses") or 0) >= 4))
    # the same kind of grammar slip repeated
    types: dict[str, int] = {}
    ex_all: list[dict] = []
    for t in real:
        for m in _fb(t).get("mistakes") or []:
            if m.get("type") in _GRAMMAR_TYPES:
                types[m["type"]] = types.get(m["type"], 0) + 1
                ex_all.append({"said": m.get("said", ""), "better": m.get("better", ""), "q": t.get("idx")})
    if types:
        ty, c = max(types.items(), key=lambda kv: kv[1])
        if c >= 2:
            add("grammar", min(1.0, c / n), {"type": ty.replace("_", " "), "c": c}, answers=sorted({e["q"] for e in ex_all if e["q"] is not None}), examples=ex_all[:3])
    # category-level weaknesses (what the habits above do not already say)
    cats = {c["key"]: c["score"] for c in (report.get("categories") or []) if c.get("score") is not None}
    have = {c["key"] for c in cands}
    for key in ("relevance", "structure"):
        s = cats.get(key)
        if s is not None and s < 60:
            add(key, min(1.0, (60 - s) / 40.0 + 0.2), {"s": s}, answers=_affected(real, lambda t, k=key: isinstance(t.get("scores"), dict) and (t["scores"].get(k) or 100) < 60))
    s = cats.get("language")
    if s is not None and s < 60 and "grammar" not in have:
        add("language", min(1.0, (60 - s) / 40.0 + 0.1), {"s": s})
    s = cats.get("delivery")
    if s is not None and s < 60 and not ({"fillers", "pace", "pauses"} & have):
        add("delivery", min(1.0, (60 - s) / 40.0 + 0.1), {"s": s})
    cov = report.get("coverage") or {}
    if (cov.get("not_yet") or []) and (cov.get("pct") if cov.get("pct") is not None else 100) < 60:
        add("coverage", min(0.55, (100 - cov["pct"]) / 180.0), {"k": len(cov["not_yet"])}, items=[str(x.get("text") or "") for x in cov["not_yet"]][:6])
    cands.sort(key=lambda w: (-w["severity_n"], _ORDER.index(w["key"]) if w["key"] in _ORDER else 99))
    out = []
    for w in cands[:5]:
        sev = w.pop("severity_n")
        w["severity"] = "high" if sev >= 0.6 else "medium" if sev >= 0.4 else "low"
        if w["key"] in ("no_number", "no_result", "short", "named_item", "relevance", "structure") and w["answers"]:
            w["model"] = _example_answer(real, w["answers"])
        out.append(w)
    return out


def _baseline(key: str, habits: dict) -> dict:
    if key in ("fillers",):
        return {"per100": habits["fillers_per100"]}
    if key == "grammar":
        return {"per100": habits["mistakes_per100"]}
    h = habits.get(key)
    return {"count": h["c"], "of": h["of"]} if isinstance(h, dict) else {}


def pick_focus(weaknesses: list[dict], habits: dict) -> list[dict]:
    """The (up to) 3 improvement points saved with the interview. Habits first: they can be checked in the next report."""
    ordered = [w for w in weaknesses if w["tracked"]] + [w for w in weaknesses if not w["tracked"]]
    return [{"key": w["key"], "title": w["title"], "goal": w["goal"], "tracked": w["tracked"], "baseline": _baseline(w["key"], habits)} for w in ordered[:3]]


# --------------------------------------------------------------------------------------------- the next interview: did it work?
def _fmt_baseline(key: str, b: dict, lang: str) -> str:
    if "per100" in b:
        return f"{b['per100']} per 100 words" if _lang(lang) == "en" else f"{b['per100']} per 100 words"
    return f"{b.get('count', 0)} of {b.get('of', 0)} answers" if _lang(lang) == "en" else f"{b.get('of', 0)} mein se {b.get('count', 0)} answers"


def _status(key: str, was: dict, now: dict) -> str | None:
    """improved / same / worse / None (not comparable). Count habits compare RATES (the two interviews have different numbers of answers) with a 25-point noise band;
    per-100-words habits compare relative change with an absolute floor."""
    if "per100" in was:
        a, b = float(was["per100"]), float(now.get("per100", 0.0))
        if b <= a * 0.75 and a - b >= 0.5:
            return "improved"
        if b >= a * 1.25 and b - a >= 0.5:
            return "worse"
        return "same"
    if not was.get("of") or not now.get("of") or was["of"] < 2 or now["of"] < 2:
        return None
    ra, rb = was["count"] / was["of"], now["count"] / now["of"]
    if rb <= ra - 0.25:
        return "improved"
    if rb >= ra + 0.25:
        return "worse"
    return "same"


def compare_progress(prev: dict | None, habits: dict, lang: str) -> dict | None:
    """prev: {session_id, title, finished_at, overall, real, habits, focus} of the previous finished interview. None when it saved no focus points to check."""
    if not prev or not prev.get("focus"):
        return None
    lg = _lang(lang)
    items = []
    for f in prev["focus"]:
        if not f.get("tracked") or f["key"] not in HABITS:
            continue
        now = _baseline(f["key"], habits)
        st = _status(f["key"], f.get("baseline") or {}, now)
        if st is None:
            continue
        items.append({"key": f["key"], "title": f["title"], "goal": f.get("goal", ""), "was": _fmt_baseline(f["key"], f.get("baseline") or {}, lg), "now": _fmt_baseline(f["key"], now, lg),
                      "status": st, "note": STATUS_NOTE[lg][st]})
    if not items:
        return None
    imp = sum(1 for i in items if i["status"] == "improved")
    summary = PROGRESS_SUMMARY[lg]["all" if imp == len(items) else "some" if imp else "none"].format(i=imp, t=len(items))
    return {"vs": {"session_id": prev.get("session_id"), "title": prev.get("title") or "", "finished_at": prev.get("finished_at"), "overall": prev.get("overall"), "answers": prev.get("real", 0)},
            "items": items, "improved": imp, "summary": summary}


# --------------------------------------------------------------------------------------------- the whole layer
def enrich_report(report: dict, turns: list[dict], *, prev_any: dict | None = None) -> dict:
    """The report + the coaching fields (v2). `report` is the v1 report (categories, coverage, feedback_lang ...); `turns` the stored turns as dicts."""
    lang = report.get("feedback_lang") or "hinglish"
    habits = habit_metrics(turns)
    weaknesses = build_weaknesses(turns, report, habits, lang)
    out = dict(report)
    out.update({"v": REPORT_VERSION, "habits": habits, "weaknesses": weaknesses, "focus": pick_focus(weaknesses, habits), "progress": compare_progress(prev_any, habits, lang)})
    return out
