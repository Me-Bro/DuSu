"""Per-session state + turn logic, shared by both modes.

Modes:
  - "interview"     : DuSu plays HR interviewer; self-ends and produces a report.
  - "conversation"  : DuSu is a friendly partner; never ends, no report.

v0 keeps the full transcript in memory (one session per WebSocket). Plan
section P calls for summarizing context once conversations get long — do that
here later; the interface stays the same.
"""

from ..providers import llm
from ..config import settings
from .prompts import (interviewer_system, conversation_system, SCORER_SYSTEM,
                      TRANSLATE_SYSTEM, SESSION_MEMORY_SYSTEM, DAILY_TURN_SYSTEM)

END_MARKER = "INTERVIEW_COMPLETE:"
MODES = ("interview", "conversation", "learning", "daily")
# Free-tier models occasionally return a lazy dead-end line ("Hi!", "How are you?")
# instead of a real reactive follow-up. One retry with a sharper nudge, same spirit
# as the retry-on-parse-failure pattern already used for /assessment.
_MIN_TURN_CHARS = 40
_MIN_DAILY_REPLY_CHARS = 25
_SHORT_REPLY_NUDGE = ("(That reply was too short and generic. React specifically to what "
                      "I just said, then ask one sharper, more specific follow-up question.)")


class Session:
    def __init__(self, mode: str, name: str, role: str, facts_summary: str = "", mood: str = "",
                 profession: str = "", time_of_day: str = "", level: str = "", daily_context: str = "",
                 career_goal: str = "", past_interview_count: int = 0, past_interview_avg: float | None = None):
        self.mode = mode if mode in MODES else "interview"
        self.name = name or "there"
        self.role = role or "general"
        self.facts_summary = facts_summary
        self.profession = profession
        self.time_of_day = time_of_day
        self.level = level
        self.daily_context = daily_context
        self.thoughts_translated = 0   # Daily Talk's unique metric (§5) — counted deterministically below, never LLM-inferred
        if self.mode == "interview":
            self.system = interviewer_system(self.name, self.role, facts_summary, mood,
                                              level=level, career_goal=career_goal,
                                              past_interview_count=past_interview_count,
                                              past_interview_avg=past_interview_avg)
        elif self.mode == "conversation":
            self.system = conversation_system(self.name, facts_summary, mood)
        else:  # learning + daily: no static chat persona (daily uses per-turn assess)
            self.system = ""
        self.transcript: list[dict] = []  # {role: "user"|"assistant", content}
        self.done = False
        self.capped = False   # conversation hit its turn cap
        self.turns = 0        # user turns so far

    def add_user(self, text: str) -> None:
        self.transcript.append({"role": "user", "content": text})
        self.turns += 1

    async def next_ai_turn(self) -> str:
        """Return DuSu's next spoken line. Enforces turn caps per mode."""
        raw = await llm.next_question(self.system, self.transcript)
        # Retry once if the model gave a dead-end one-liner instead of a real reactive
        # turn — but not when it's legitimately wrapping up (END_MARKER present).
        if (self.mode in ("interview", "conversation") and END_MARKER not in raw
                and len(raw.strip()) < _MIN_TURN_CHARS):
            nudged = self.transcript + [{"role": "user", "content": _SHORT_REPLY_NUDGE}]
            retry = await llm.next_question(self.system, nudged)
            if len(retry.strip()) >= _MIN_TURN_CHARS:
                raw = retry
        spoken = raw
        if self.mode == "interview":
            if END_MARKER in raw:
                self.done = True
                spoken = raw.split(END_MARKER, 1)[1].strip() or "Thanks, that's the end of our interview."
            elif self.turns >= settings.interview_max_turns:
                self.done = True
                spoken = f"Thanks {self.name} — that's all the questions I have for now. Let me put together your report."
        elif self.mode == "conversation" and self.turns >= settings.conversation_max_turns:
            self.capped = True
            spoken = "This has been such a great long chat — let's pause here for now. Start a fresh conversation whenever you'd like!"
        self.transcript.append({"role": "assistant", "content": spoken})
        return spoken

    async def next_ai_turn_stream(self):
        """Streaming twin of next_ai_turn(): yields whole sentences as they're
        generated so the browser can start speaking the first one immediately.
        Applies the SAME cap/end-marker rules, then commits the assembled reply to
        the transcript exactly once — so memory/persistence are identical to the
        non-streaming path and can't drift from it."""
        parts = []
        async for piece in llm.next_question_stream(self.system, self.transcript):
            parts.append(piece)
            # Hold back the marker line itself — it's a control token, never spoken.
            if self.mode == "interview" and END_MARKER in piece:
                continue
            yield piece
        raw = " ".join(parts).strip()
        spoken = raw
        if self.mode == "interview":
            if END_MARKER in raw:
                self.done = True
                spoken = raw.split(END_MARKER, 1)[1].strip() or "Thanks, that's the end of our interview."
            elif self.turns >= settings.interview_max_turns:
                self.done = True
        elif self.mode == "conversation" and self.turns >= settings.conversation_max_turns:
            self.capped = True
        if spoken:
            self.transcript.append({"role": "assistant", "content": spoken})
        self._last_spoken = spoken

    async def translate(self, text: str) -> str:
        """Learning mode: Hindi/Hinglish -> natural spoken English."""
        return await llm.translate(TRANSLATE_SYSTEM, text)

    async def daily_turn(self, answer: str, first: bool = False) -> dict:
        """Daily Companion: one JSON call → english + praise + next Hindi question
        + mood + context. `first=True` opens the conversation (no answer yet)."""
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in self.transcript)
        payload = (
            f"LEARNER FACTS:\n{self.facts_summary or '(none yet)'}\n\n"
            f"profession: {self.profession or 'unknown'}\n"
            f"time_of_day: {self.time_of_day or 'unknown'}\n"
            f"english_level: {self.level or 'A1'}\n"
            f"recent daily context:\n{self.daily_context or '(none)'}\n\n"
            f"conversation so far:\n{convo or '(just starting)'}\n\n"
            + ("This is the FIRST turn — open the conversation with a warm, context-aware "
               "question. Leave english/praise empty."
               if first else f"learner just said (in Hindi/Hinglish): {answer}")
        )
        # bigger budget: the friend-reply + full JSON must fit or it truncates → empty reply
        # prefer_fast=True: this is a per-turn chat call (§9), same latency class as next_question.
        data = await llm.assess(DAILY_TURN_SYSTEM, payload, max_tokens=1100, prefer_fast=True)
        # Retry once if the model gave a lazy dead-end reply (e.g. just "haan theek hai")
        # instead of the real 6-step friend reply the prompt asks for.
        if len((data.get("reply_hindi") or "").strip()) < _MIN_DAILY_REPLY_CHARS:
            retry_payload = payload + ("\n\n(Your reply_hindi was too short/generic. Write "
                                        "the full warm reply — sense the feeling, respond to "
                                        "it, and end with one specific question.)")
            retry = await llm.assess(DAILY_TURN_SYSTEM, retry_payload, max_tokens=1100, prefer_fast=True)
            if len((retry.get("reply_hindi") or "").strip()) >= _MIN_DAILY_REPLY_CHARS:
                data = retry
        if not first and answer:
            self.transcript.append({"role": "user", "content": answer})
            self.turns += 1
            if (data.get("english") or "").strip():   # deterministic count, never LLM-reported (§5)
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
        return await llm.score(SCORER_SYSTEM, self.transcript)

    async def summarize_and_extract(self) -> dict:
        """ONE LLM call at session end: summary + learned facts + events + signals +
        Speaking Score (DUSU_SPEAKER_PROGRESSION_PLAN.md §2.2/§20). Returns {} for
        empty/learning sessions (nothing worth remembering or scoring)."""
        if self.mode == "learning" or not any(m["role"] == "user" for m in self.transcript):
            return {}
        convo = f"learner's stated English level: {self.level or 'A1'}\n\n" + \
            "\n".join(f"{m['role']}: {m['content']}" for m in self.transcript)
        try:
            return await llm.assess(SESSION_MEMORY_SYSTEM, convo, max_tokens=900)
        except Exception:
            return {}
