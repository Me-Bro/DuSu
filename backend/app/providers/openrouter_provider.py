"""LLM provider chain (all OpenAI-compatible: Gemini, OpenRouter, Groq, …).

Every provider exposes the OpenAI Chat Completions shape, so one OpenAI client
per provider (different base_url + key) drives them all. On any failure — quota
(429/402), model gone (404), bad request — we fall through to the next model,
then the next provider. Configure the chain in config.Settings.providers().

Speech is browser-side; the model only ever sees and emits text.
"""

import json
import re
import time
from contextvars import ContextVar

from openai import AsyncOpenAI

from ..config import settings

_clients: dict[tuple, AsyncOpenAI] = {}   # keyed (provider_name, api_key), not name alone

# Fail fast: a healthy provider answers a chat turn in well under a second (measured:
# groq ~0.7s, gemini-flash-lite ~1.0s). Anything still silent at 20s is not going to
# save the turn — the chain's next provider will answer sooner than it will.
_REQUEST_TIMEOUT_S = 20.0
_cooldown: dict[str, float] = {}   # provider name -> skip-until timestamp

# BYOK / Office mode: a per-request provider chain. When set (via set_active_keys),
# _complete uses these keys instead of the global default (env) chain. contextvars
# are per-task, so each WS connection / HTTP request is isolated.
_active_chain: ContextVar[list | None] = ContextVar("_active_chain", default=None)

def set_active_keys(keys: dict | None) -> None:
    """Office mode: route this request/connection's LLM calls through the user's keys.
    Pass a falsy value / empty dict to use the default (Personal) chain."""
    chain = settings.providers_from(keys) if keys else None
    _active_chain.set(chain or None)


def _client(p: dict) -> AsyncOpenAI:
    # Cache key MUST include the actual key, not just the provider name — BYOK
    # (Office mode) builds a chain with the same names ("gemini"/"groq"/...) as the
    # default env chain but a different key per user. Caching by name alone means
    # whichever key hits this provider first in the process's lifetime "wins" the
    # cached client, and every later caller — including other users' BYOK requests
    # and the owner's own Personal-mode calls — silently reuses that first key.
    ck = (p["name"], p["key"])
    if ck not in _clients:
        _clients[ck] = AsyncOpenAI(
            api_key=p["key"],
            base_url=p["base_url"],
            default_headers=p.get("headers") or {},
            # CRITICAL for perceived latency. The library defaults are read=600s and
            # max_retries=2 — so ONE unhealthy provider returning a retryable status
            # (e.g. Gemini's chronic 503 "model overloaded") was retried 3x with
            # backoff, burning ~25s on a dead endpoint before the chain even moved
            # on. We already HAVE a fallback chain; retrying inside a single provider
            # is strictly worse than failing fast and trying the next one.
            timeout=_REQUEST_TIMEOUT_S,
            max_retries=0,
        )
    return _clients[ck]


# Deterministic safety net for prompts.HINDI_RESPECT_RULE. A prompt instruction is
# probabilistic — live-tested, ~1 in 4 real generations still slipped in "tu" even
# with the rule spelled out (weaker fallback-chain models comply less reliably).
# This guarantees तू/तेरा/तुझे (or their Latin spellings) never reach the user
# regardless of which model/provider produced the text, and it lives inside
# _complete() itself so EVERY prompt inherits it automatically — a future prompt
# that generates Hindi can't forget to sanitize because there's nothing to remember.
_HINDI_DEVANAGARI_MAP = {
    "तू": "तुम", "तेरा": "तुम्हारा", "तेरी": "तुम्हारी", "तेरे": "तुम्हारे",
    "तुझे": "तुम्हें", "तुझको": "तुमको", "तुझसे": "तुमसे",
    "तुझमें": "तुममें", "तुझपर": "तुमपर",
}
_HINDI_LATIN_MAP = {
    "tu": "tum", "tera": "tumhara", "teri": "tumhari", "tere": "tumhare",
    "tujhe": "tumhe", "tujhko": "tumko", "tujhse": "tumse",
}
# Explicit punctuation/whitespace boundaries rather than regex \b — \b's Unicode
# "word character" test can land mid-syllable on Devanagari combining vowel signs,
# and a plain unbounded substring match would corrupt words like "तूफान" (storm),
# which starts with तू but isn't the pronoun. Devanagari/Hindi is written with
# spaces between words, so a space/punctuation boundary is both safe and correct.
_BOUND_BEFORE = r'(?:(?<=^)|(?<=[\s.,!?।;:"\'()\[\]—–-]))'
_BOUND_AFTER = r'(?:(?=$)|(?=[\s.,!?।;:"\'()\[\]—–-]))'


def _match_case(sample: str, replacement: str) -> str:
    if sample.isupper():
        return replacement.upper()
    if sample[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def sanitize_hindi_respect(text: str) -> str:
    """Rewrite तू/तेरा/तुझे (and tu/tera/tujhe) to तुम/तुम्हारा/तुम्हें (tum/tumhara/
    tumhe) wherever they appear as whole words. No-op on pure-English text."""
    if not text:
        return text
    out = text
    for bad, good in _HINDI_DEVANAGARI_MAP.items():
        out = re.sub(_BOUND_BEFORE + re.escape(bad) + _BOUND_AFTER, good, out)
    for bad, good in _HINDI_LATIN_MAP.items():
        pattern = _BOUND_BEFORE + re.escape(bad) + _BOUND_AFTER
        out = re.sub(pattern, lambda m: _match_case(m.group(0), good), out, flags=re.IGNORECASE)
    return out


# Some models (e.g. Groq's qwen3.6-27b) emit their chain-of-thought in a <think>
# block before the real answer. Spoken aloud that is gibberish to the learner, so
# it's stripped centrally rather than trusting every model to behave.
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"^\s*<think>.*$", re.DOTALL | re.IGNORECASE)
# Sentence end = . ! ? or the Devanagari danda, optionally followed by a closing
# quote/bracket. Used both to repair truncated replies and to chunk streaming
# output into whole sentences.
_SENTENCE_END_RE = re.compile(r'[.!?।]["\')\]]?(?=\s|$)')


def strip_reasoning(text: str) -> str:
    if not text:
        return text
    out = _THINK_RE.sub("", text)
    if "<think>" in out.lower():        # opened but never closed → truncated mid-reasoning
        out = _UNCLOSED_THINK_RE.sub("", out)
    return out.strip()


def _trim_to_last_sentence(text: str) -> str:
    """Cut a truncated reply back to its last COMPLETE sentence. Returns '' if there
    isn't one (caller then keeps the original rather than emitting nothing)."""
    matches = list(_SENTENCE_END_RE.finditer(text))
    if not matches:
        return ""
    return text[: matches[-1].end()].strip()


# A provider failing on credentials or retirement will NOT recover on its own — no
# amount of waiting fixes a bad key or a shut-down endpoint. Retrying these on the
# 90s rate-limit schedule burns a real round-trip on every fallback (measured: dead
# Gemini 0.69s, retired GitHub Models 1.30s) against a sub-second turn-latency goal.
_DEAD_MARKERS = ("401", "403", "404", "410", "invalid authentication",
                 "invalid api key", "unauthorized", "retirement", "brownout")


def cooling_down() -> list[str]:
    """Providers the chain is currently skipping (expired entries ignored)."""
    now = time.time()
    return sorted(n for n, until in _cooldown.items() if until > now)


def _mark_cooldown(name: str, err: str) -> None:
    """A rate-limited/exhausted provider is skipped for a while so we don't
    waste a failing round-trip on it every single turn."""
    low = err.lower()
    if any(k in low for k in _DEAD_MARKERS):
        _cooldown[name] = time.time() + 21600        # 6h — misconfigured/retired, not busy
        return
    daily = any(k in low for k in ("day", "quota", "free_tier", "free-models"))
    _cooldown[name] = time.time() + (1800 if daily else 90)


async def _complete(messages: list[dict], max_tokens: int, prefer_fast: bool = False) -> str:
    """Walk the provider chain → each provider's models → until one answers.
    Skips providers on cooldown; if every provider is cooling down, tries them
    anyway rather than failing.

    `prefer_fast=True` moves Groq (fastest inference in this stack) to the front
    of the chain — for latency-sensitive per-turn chat calls (conversation/
    interview/daily turns). One-shot heavy generations (career roadmap, full
    assessments) keep the default gemini-first order, where quality-per-call
    matters more than shaving latency (DUSU_SPEAKER_PROGRESSION_PLAN.md §9/§18)."""
    last_err = None
    chain = _active_chain.get() or settings.providers()   # Office keys if set, else default
    if prefer_fast:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == "groq" else 1)
    for ignore_cd in (False, True):
        now = time.time()
        attempted = False
        for p in chain:
            if not ignore_cd and _cooldown.get(p["name"], 0) > now:
                continue
            attempted = True
            client = _client(p)
            for model in p["models"]:
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.7,
                        extra_body=p.get("extra") or {},
                    )
                    choice = resp.choices[0]
                    text = strip_reasoning(choice.message.content or "").strip()
                    if text:
                        # A "length" finish means the model was CUT OFF mid-thought.
                        # Returning it verbatim is what made replies trail off in the
                        # middle of a sentence. Trim back to the last complete
                        # sentence so the user always hears a finished thought.
                        if getattr(choice, "finish_reason", None) == "length":
                            trimmed = _trim_to_last_sentence(text)
                            if trimmed:
                                text = trimmed
                        return sanitize_hindi_respect(text)
                except Exception as e:
                    last_err = e
                    s = str(e)
                    if any(k in s.lower() for k in ("429", "rate", "quota", "exceed", "exhaust")):
                        _mark_cooldown(p["name"], s)  # whole provider limited
                        break                          # skip its other models
                    continue                           # other error → next model
        if attempted:
            break   # we tried the available providers; don't loop into ignore-pass
    raise RuntimeError(f"all providers/models unavailable: {last_err}")


# Speak-as-it-generates, but in WHOLE SENTENCES — never raw tokens. Browser
# speechSynthesis renders each utterance with its own prosody, so feeding it token
# fragments produces exactly the clipped, stuttering delivery we want to avoid.
# Buffering to a sentence boundary means every utterance is a complete thought:
# playback starts at the first sentence (~0.4s) while the rest is still generating,
# and generation always outruns speech, so the audio never starves mid-reply.
_MIN_CHUNK_CHARS = 18   # don't emit "Hi." alone as its own utterance — let it ride with the next sentence


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """Pull every COMPLETE sentence out of buf. Returns (sentences, remainder)."""
    out, start = [], 0
    for m in _SENTENCE_END_RE.finditer(buf):
        end = m.end()
        piece = buf[start:end].strip()
        if len(piece) >= _MIN_CHUNK_CHARS:
            out.append(piece)
            start = end
    return out, buf[start:]


async def stream_sentences(messages: list[dict], max_tokens: int, prefer_fast: bool = False):
    """Yield DuSu's reply sentence by sentence as the model writes it.

    Falls back to a normal blocking call if the provider can't stream, so a
    provider without streaming support degrades to "slightly later, still correct"
    rather than failing the turn."""
    chain = _active_chain.get() or settings.providers()
    if prefer_fast:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == "groq" else 1)
    now = time.time()
    last_err = None
    for p in chain:
        if _cooldown.get(p["name"], 0) > now:
            continue
        client = _client(p)
        for model in p["models"]:
            try:
                stream = await client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens,
                    temperature=0.7, extra_body=p.get("extra") or {}, stream=True,
                )
                buf, emitted_any, saw_think = "", False, False
                async for event in stream:
                    if not event.choices:
                        continue
                    piece = event.choices[0].delta.content or ""
                    if not piece:
                        continue
                    buf += piece
                    # A reasoning model started thinking out loud — stop chunking and
                    # let the whole thing be cleaned up at the end instead.
                    if not saw_think and "<think>" in buf.lower():
                        saw_think = True
                    if saw_think:
                        continue
                    sentences, buf = _split_sentences(buf)
                    for s in sentences:
                        emitted_any = True
                        yield sanitize_hindi_respect(s)
                tail = strip_reasoning(buf).strip()
                if saw_think:
                    # everything was buffered; emit the cleaned result now
                    for s in ([tail] if tail else []):
                        emitted_any = True
                        yield sanitize_hindi_respect(s)
                elif tail:
                    # trailing text with no sentence-ending punctuation
                    emitted_any = True
                    yield sanitize_hindi_respect(tail)
                if emitted_any:
                    return
                last_err = RuntimeError("empty stream")
            except Exception as e:
                last_err = e
                s_err = str(e).lower()
                if any(k in s_err for k in ("429", "rate", "quota", "exceed", "exhaust")):
                    _mark_cooldown(p["name"], str(e))
                    break
                continue
    # Nothing streamed — fall back to the normal path so the turn still happens.
    text = await _complete(messages, max_tokens=max_tokens, prefer_fast=prefer_fast)
    if text:
        yield text


# The whole transcript used to be resent on every turn. Past ~15 turns that both
# slows the call down and actively HURTS quality on small free-tier models: the
# early turns crowd out the recent ones, so DuSu starts losing the current thread
# and repeating itself. The durable stuff (facts, where-we-left-off) is already
# injected into the system prompt by _facts_summary(), so a rolling window of the
# live exchange is all the model actually needs here.
_MAX_CONTEXT_TURNS = 16


def _recent(transcript: list[dict]) -> list[dict]:
    if len(transcript) <= _MAX_CONTEXT_TURNS:
        return transcript
    return transcript[-_MAX_CONTEXT_TURNS:]


def _extract_json(text: str) -> dict:
    """Models don't always return clean JSON — strip code fences, pull the {...} block."""
    t = (text or "").strip()
    if t.startswith("```"):                       # ```json ... ``` fences
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.DOTALL)     # greedy → to the last closing brace
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"error": "scoring_parse_failed", "raw": text[:500]}


class OpenRouterLLM:
    async def next_question(self, system: str, transcript: list[dict]) -> str:
        messages = [{"role": "system", "content": system}, *_recent(transcript)]
        # Some providers (Gemini) reject a system-only request — DuSu speaks first
        # with an empty transcript, so seed a user turn to kick it off.
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user",
                             "content": "Let's begin. Greet me and ask your first question."})
        # 420 (was 320): the persona asks for 2-4 spoken sentences and a follow-up
        # question; 320 clipped the longer, more interesting turns mid-word.
        return await _complete(messages, max_tokens=420, prefer_fast=True)   # per-turn chat (§9)

    async def next_question_stream(self, system: str, transcript: list[dict]):
        """Same as next_question, but yields whole sentences as they're written."""
        messages = [{"role": "system", "content": system}, *_recent(transcript)]
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user",
                             "content": "Let's begin. Greet me and ask your first question."})
        async for s in stream_sentences(messages, max_tokens=420, prefer_fast=True):
            yield s

    async def translate(self, system: str, text: str) -> str:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": text}]
        return await _complete(messages, max_tokens=120)

    async def generate(self, system: str, prompt: str, max_tokens: int = 500) -> str:
        """Free-form prose (weekly letters, session summaries). Returns raw text."""
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        return await _complete(messages, max_tokens=max_tokens)

    async def assess(self, system: str, payload: str, max_tokens: int = 700, prefer_fast: bool = False) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": payload + "\n\nReturn ONLY the JSON object."},
        ]
        return _extract_json(await _complete(messages, max_tokens=max_tokens, prefer_fast=prefer_fast))

    async def score(self, system: str, transcript: list[dict]) -> dict:
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": convo + "\n\nReturn ONLY the JSON object."},
        ]
        return _extract_json(await _complete(messages, max_tokens=1200))
