"""Per-session state + turn logic, shared by both modes.

Modes:
  - "interview"     : DuSu plays HR interviewer; self-ends and produces a report.
  - "conversation"  : DuSu is a friendly partner; never ends, no report.
  - "daily"         : Daily Talk, a close-friend chat (one JSON call per turn).
  - "learning"      : Learn, a one-sentence translator.

Every mode also has a language (`Session.lang`, DUSU_BILINGUAL_PLAN.md): "hi" or "en" - what the learner speaks and what
DuSu answers in (for Learn: the language the learner speaks, i.e. the translation direction). With the bilingual switch
OFF, main.py passes lang.LEGACY[mode] (conversation/interview "en", daily/learning "hi"), which is exactly the behaviour
before the switch existed - nothing below changes a word of those paths.

v0 keeps the full transcript in memory (one session per WebSocket). Plan
section P calls for summarizing context once conversations get long — do that
here later; the interface stays the same.
"""

from .. import lang as L
from ..providers import llm
from ..config import settings
from .prompts import (interviewer_system, conversation_system, scorer_system,
                      TRANSLATE_SYSTEM, TRANSLATE_SYSTEM_EN2HI, SESSION_MEMORY_SYSTEM,
                      DAILY_TURN_SYSTEM, DAILY_TURN_SYSTEM_EN)

END_MARKER = "INTERVIEW_COMPLETE:"
MODES = ("interview", "conversation", "learning", "daily")
# Free-tier models occasionally return a lazy dead-end line ("Hi!", "How are you?")
# instead of a real reactive follow-up. One retry with a sharper nudge, same spirit
# as the retry-on-parse-failure pattern already used for /assessment. (The per-language
# floor and the nudge text live in lang.py; the English values are the original ones.)
_MIN_DAILY_REPLY_CHARS = 25


class Session:
    def __init__(self, mode: str, name: str, role: str, facts_summary: str = "", mood: str = "",
                 profession: str = "", time_of_day: str = "", level: str = "", daily_context: str = "",
                 career_goal: str = "", past_interview_count: int = 0, past_interview_avg: float | None = None,
                 lang: str | None = None, bilingual: bool = False):
        self.mode = mode if mode in MODES else "interview"
        self.name = name or "there"
        self.role = role or "general"
        self.facts_summary = facts_summary
        self.profession = profession
        self.time_of_day = time_of_day
        self.level = level
        self.daily_context = daily_context
        self.mood = mood
        self.career_goal = career_goal
        self.past_interview_count = past_interview_count
        self.past_interview_avg = past_interview_avg
        # The session language; None = what this mode did before the switch existed.
        self.lang = L.norm(lang, L.LEGACY.get(self.mode, "en")) if lang else L.LEGACY.get(self.mode, "en")
        self.bilingual = bilingual           # the switch is on for this learner (affects scoring rules only)
        self._switch_note = False            # the next model call carries a one-off "learner switched language" note
        self.thoughts_translated = 0   # Daily Talk's unique metric (§5) — counted deterministically below, never LLM-inferred
        self._build_system()
        self.transcript: list[dict] = []  # {role: "user"|"assistant", content}
        self.done = False
        self.capped = False   # conversation hit its turn cap
        self.turns = 0        # user turns so far

    def _build_system(self) -> None:
        if self.mode == "interview":
            self.system = interviewer_system(self.name, self.role, self.facts_summary, self.mood,
                                              level=self.level, career_goal=self.career_goal,
                                              past_interview_count=self.past_interview_count,
                                              past_interview_avg=self.past_interview_avg, lang=self.lang)
        elif self.mode == "conversation":
            self.system = conversation_system(self.name, self.facts_summary, self.mood, lang=self.lang)
        else:  # learning + daily: no static chat persona (daily uses per-turn assess)
            self.system = ""

    def set_lang(self, lang: str) -> bool:
        """Switch the session language mid-conversation. The transcript stays; the prompt is rebuilt; the next model
        call carries a one-off note so a transcript written in the other language doesn't pull the reply back."""
        new = L.norm(lang, self.lang)
        if new == self.lang:
            return False
        self.lang = new
        self._build_system()
        self._switch_note = self.mode in ("conversation", "interview") and bool(self.transcript)
        return True

    def _transcript_for_call(self) -> list[dict]:
        """The stored transcript, plus - for ONE call after a language switch - a note folded into the last user turn
        (never stored, so it can't leak into memory, summaries or the saved tail)."""
        if self._switch_note and self.transcript and self.transcript[-1]["role"] == "user":
            last = dict(self.transcript[-1])
            last["content"] = last["content"] + "\n\n" + L.line(self.lang, "switch_note")
            return self.transcript[:-1] + [last]
        return self.transcript

    def add_user(self, text: str) -> None:
        self.transcript.append({"role": "user", "content": text})
        self.turns += 1

    async def next_ai_turn(self) -> str:
        """Return DuSu's next spoken line. Enforces turn caps per mode."""
        transcript = self._transcript_for_call()
        seed = L.SEED[self.lang]
        raw = await llm.next_question(self.system, transcript, seed=seed)
        self._switch_note = False
        # Retry once if the model gave a dead-end one-liner instead of a real reactive
        # turn — but not when it's legitimately wrapping up (END_MARKER present).
        floor = L.MIN_TURN_CHARS[self.lang]
        if (self.mode in ("interview", "conversation") and END_MARKER not in raw
                and len(raw.strip()) < floor):
            nudged = transcript + [{"role": "user", "content": L.line(self.lang, "short_nudge")}]
            retry = await llm.next_question(self.system, nudged, seed=seed)
            if len(retry.strip()) >= floor:
                raw = retry
        spoken = raw
        if self.mode == "interview":
            if END_MARKER in raw:
                self.done = True
                spoken = raw.split(END_MARKER, 1)[1].strip() or L.line(self.lang, "interview_end")
            elif self.turns >= settings.interview_max_turns:
                self.done = True
                spoken = L.line(self.lang, "interview_cap", name=self.name)
        elif self.mode == "conversation" and self.turns >= settings.conversation_max_turns:
            self.capped = True
            spoken = L.line(self.lang, "convo_cap")
        self.transcript.append({"role": "assistant", "content": spoken})
        return spoken

    async def next_ai_turn_stream(self):
        """Streaming twin of next_ai_turn(): yields whole sentences as they're
        generated so the browser can start speaking the first one immediately.
        Applies the SAME cap/end-marker rules, then commits the assembled reply to
        the transcript exactly once — so memory/persistence are identical to the
        non-streaming path and can't drift from it."""
        parts = []
        async for piece in llm.next_question_stream(self.system, self._transcript_for_call(), seed=L.SEED[self.lang]):
            parts.append(piece)
            # Hold back the marker line itself — it's a control token, never spoken.
            if self.mode == "interview" and END_MARKER in piece:
                continue
            yield piece
        self._switch_note = False
        raw = " ".join(parts).strip()
        spoken = raw
        if self.mode == "interview":
            if END_MARKER in raw:
                self.done = True
                spoken = raw.split(END_MARKER, 1)[1].strip() or L.line(self.lang, "interview_end")
            elif self.turns >= settings.interview_max_turns:
                self.done = True
        elif self.mode == "conversation" and self.turns >= settings.conversation_max_turns:
            self.capped = True
        if spoken:
            self.transcript.append({"role": "assistant", "content": spoken})
        self._last_spoken = spoken

    async def translate(self, text: str) -> str:
        """Learn: the language the learner SPEAKS is self.lang. Hindi/Hinglish -> natural spoken English (the original
        direction), or English -> natural spoken Hindi in Devanagari."""
        if self.lang == "en":
            return await llm.translate(TRANSLATE_SYSTEM_EN2HI, text, max_tokens=240)
        return await llm.translate(TRANSLATE_SYSTEM, text)

    async def daily_turn(self, answer: str, first: bool = False) -> dict:
        """Daily Companion: one JSON call → english + praise + next question
        + mood + context. `first=True` opens the conversation (no answer yet).
        Hindi (the original): the friend chats in Hindi and `english` is the learner's line TRANSLATED. English: the
        friend chats in English and `english` is the learner's line POLISHED. The JSON keys are the same in both."""
        hi = self.lang == "hi"
        system = DAILY_TURN_SYSTEM if hi else DAILY_TURN_SYSTEM_EN
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in self.transcript)
        payload = (
            f"LEARNER FACTS:\n{self.facts_summary or '(none yet)'}\n\n"
            # Explicit, every turn. DAILY_TURN_SYSTEM requires addressing the learner
            # by name; when the name was missing the model invented one.
            f"learner_name: {self.name or 'unknown'}\n"
            f"profession: {self.profession or 'unknown'}\n"
            f"time_of_day: {self.time_of_day or 'unknown'}\n"
            f"english_level: {self.level or 'A1'}\n"
            + ("" if hi else "language: English\n")
            + f"recent daily context:\n{self.daily_context or '(none)'}\n\n"
            f"conversation so far:\n{convo or '(just starting)'}\n\n"
            + ("This is the FIRST turn — open the conversation with a warm, context-aware "
               "question. Leave english/praise empty."
               if first else
               f"learner just said (in {'Hindi/Hinglish' if hi else 'English'}): {answer}")
        )
        # bigger budget: the friend-reply + full JSON must fit or it truncates → empty reply
        # prefer_fast=True: this is a per-turn chat call (§9), same latency class as next_question.
        data = await llm.assess(system, payload, max_tokens=1100, prefer_fast=True)
        # Retry once if the model gave a lazy dead-end reply (e.g. just "haan theek hai")
        # instead of the real 6-step friend reply the prompt asks for.
        if len((data.get("reply_hindi") or "").strip()) < _MIN_DAILY_REPLY_CHARS:
            retry_payload = payload + "\n\n" + L.DAILY_SHORT_NUDGE
            retry = await llm.assess(system, retry_payload, max_tokens=1100, prefer_fast=True)
            if len((retry.get("reply_hindi") or "").strip()) >= _MIN_DAILY_REPLY_CHARS:
                data = retry
        if not first and answer:
            self.transcript.append({"role": "user", "content": answer})
            self.turns += 1
            # deterministic count, never LLM-reported (§5). Only a real Hindi->English translation counts: in English
            # mode `english` is the learner's own line polished, not a thought they translated.
            if hi and (data.get("english") or "").strip():
                self.thoughts_translated += 1
        # keep the richer reply in memory (falls back to the bare question)
        reply = (data.get("reply_hindi") or data.get("next_question_hindi") or "").strip()
        if reply:
            self.transcript.append({"role": "assistant", "content": reply})
        return data

    async def build_report(self) -> dict:
        """Only interview mode is scored. Conversation returns nothing."""
        if self.mode != "interview":
            return {}
        if self.lang == "hi":
            # Hindi interview: a Hindi rubric without the English-only skills, a bigger token budget (Devanagari), and
            # the report is tagged so the client renders Hindi labels and skips the metrics that don't apply.
            d = await llm.score(scorer_system("hi"), self.transcript, max_tokens=2000)
            if isinstance(d, dict) and not d.get("error"):
                d["lang"] = "hi"
            return d
        return await llm.score(scorer_system("en"), self.transcript)

    async def summarize_and_extract(self) -> dict:
        """ONE LLM call at session end: summary + learned facts + events + signals +
        Speaking Score (DUSU_SPEAKER_PROGRESSION_PLAN.md §2.2/§20). Returns {} for
        empty/learning sessions (nothing worth remembering or scoring)."""
        if self.mode == "learning" or not any(m["role"] == "user" for m in self.transcript):
            return {}
        convo = f"learner's stated English level: {self.level or 'A1'}\n\n" + \
            "\n".join(f"{m['role']}: {m['content']}" for m in self.transcript)
        if self.bilingual and self.lang == "hi":
            # A Hindi session says nothing about English vocabulary/grammar: main.py stores those two as NULL (unscored)
            # whatever comes back, so just keep the model from penalising the learner for speaking Hindi.
            convo = ("NOTE: this session was held in HINDI. The vocabulary and grammar_trend rubrics don't apply - "
                     "return 0 for both. Score confidence, continuity and depth as usual. Set no_hindi and "
                     "asked_question to false.\n\n" + convo)
        try:
            return await llm.assess(SESSION_MEMORY_SYSTEM, convo, max_tokens=900)
        except Exception:
            return {}
