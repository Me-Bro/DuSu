"""LLM provider chain (all OpenAI-compatible: Gemini, OpenRouter, Groq, …).

Every provider exposes the OpenAI Chat Completions shape, so one OpenAI client
per provider (different base_url + key) drives them all. On any failure — quota
(429/402), model gone (404), bad request — we fall through to the next model,
then the next provider. Configure the chain in config.Settings.providers().

Speech is browser-side; the model only ever sees and emits text.
"""

import asyncio
import json
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass

from openai import AsyncOpenAI

from ..config import settings
from ..keys import classify, gate, ledger
from ..keys.errors import ProviderChainError, chain_state

_clients: dict[tuple, AsyncOpenAI] = {}   # keyed (provider_name, api_key), not name alone

# Tests only: a callable returning an httpx.AsyncClient (e.g. one with a MockTransport). When set, every SDK client and every probe talks through it, so a test
# can script a provider's answers per host + bearer token without any network. Production leaves it None.
_http_client_factory = None

# Fail fast: a healthy provider answers a chat turn in well under a second (measured:
# groq ~0.7s, gemini-flash-lite ~1.0s). Anything still silent at 20s is not going to
# save the turn — the chain's next provider will answer sooner than it will.
_REQUEST_TIMEOUT_S = 20.0
# Ceiling for one whole chain walk (all providers × models, both passes). Without it a
# total outage costs the caller the sum of every attempt's timeout.
_CHAIN_DEADLINE_S = 30.0
_cooldown: dict[str, float] = {}   # provider name -> skip-until timestamp

# BYOK / Office mode: a per-request provider chain. When set (via set_active_keys),
# _complete uses these keys instead of the global default (env) chain. contextvars
# are per-task, so each WS connection / HTTP request is isolated.
_active_chain: ContextVar[list | None] = ContextVar("_active_chain", default=None)


@dataclass(frozen=True)
class KeyCtx:
    """Whose keys this request / connection is using. `engine` = the per-key walker (settings.key_health) is on for this learner; `uid` = who to count for."""
    uid: str | None = None
    engine: bool = False


_active_ctx: ContextVar[KeyCtx | None] = ContextVar("_active_ctx", default=None)
_unset = {"calls": 0}                    # LLM calls that arrived with no key context at all (a call path that forgot set_active_keys)


def set_active_keys(keys: dict | None, uid: str | None = None, engine: bool = False) -> None:
    """Office mode: route this request/connection's LLM calls through the user's keys.
    Pass a falsy value / empty dict to use the default (Personal) chain.
    `uid` / `engine` (settings.key_health): who the calls are counted for, and whether the per-key walker runs - every call site passes them (an AST test
    in tests/keys/unit.py fails the build if one forgets `uid=`), because a forgotten site would silently skip the accounting."""
    chain = settings.providers_from(keys) if keys else None
    _active_chain.set(chain or None)
    _active_ctx.set(KeyCtx(uid=uid, engine=bool(engine)))


def http_client():
    """A fresh httpx.AsyncClient for the probes (10 s, no retries). Tests inject a MockTransport through `_http_client_factory`."""
    if _http_client_factory is not None:
        return _http_client_factory()
    import httpx
    return httpx.AsyncClient(timeout=httpx.Timeout(10.0))


def new_sdk_client(p: dict, timeout: float = _REQUEST_TIMEOUT_S) -> AsyncOpenAI:
    """An OpenAI-SDK client for one provider entry, NOT cached (the probes use it for a key that is not stored yet)."""
    kw = {"http_client": _http_client_factory()} if _http_client_factory is not None else {}
    return AsyncOpenAI(api_key=p["key"], base_url=p["base_url"], default_headers=p.get("headers") or {}, timeout=timeout, max_retries=0, **kw)


def evict_client(provider: str, key: str) -> None:
    """A key was removed or replaced: forget its cached client."""
    _clients.pop((provider, key), None)


def _client(p: dict) -> AsyncOpenAI:
    # Cache key MUST include the actual key, not just the provider name — BYOK
    # (Office mode) builds a chain with the same names ("gemini"/"groq"/...) as the
    # default env chain but a different key per user. Caching by name alone means
    # whichever key hits this provider first in the process's lifetime "wins" the
    # cached client, and every later caller — including other users' BYOK requests
    # and the owner's own Personal-mode calls — silently reuses that first key.
    ck = (p["name"], p["key"])
    if ck not in _clients:
        # CRITICAL for perceived latency. The library defaults are read=600s and
        # max_retries=2 — so ONE unhealthy provider returning a retryable status
        # (e.g. Gemini's chronic 503 "model overloaded") was retried 3x with
        # backoff, burning ~25s on a dead endpoint before the chain even moved
        # on. We already HAVE a fallback chain; retrying inside a single provider
        # is strictly worse than failing fast and trying the next one.
        _clients[ck] = new_sdk_client(p, _REQUEST_TIMEOUT_S)
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
_DEAD_CODES = re.compile(r"(?<![\w.])(?:401|403|404|410)(?!\w|\.\d)")      # an HTTP status as its own token ...
_DEAD_WORDS = ("invalid authentication", "invalid api key", "unauthorized", "retirement", "brownout")
_RATE_WORDS = ("rate limit", "rate_limit", "tokens per minute", "too many requests")
_RATE_CODE = re.compile(r"(?<![\w.])429(?!\w|\.\d)")                  # 429 as its own token - like the dead codes above, not a digit run inside an id
# ... NOT a digit run inside a number: a Groq rate-limit message such as "Limit 8000, Used 4041, Requested 4500" contains "404" as a SUBSTRING, which
# used to put the whole provider on a 6-hour cooldown for every user (the cooldown map is keyed by provider name only). A message that reads as a
# rate limit is always the short, rate-limit kind of cooldown.


def cooling_down() -> list[str]:
    """Providers the chain is currently skipping (expired entries ignored)."""
    now = time.time()
    return sorted(n for n, until in _cooldown.items() if until > now)


def _cooldown_seconds(err: str) -> int:
    """How long the legacy rules skip a provider after this error text: 6 h (misconfigured / retired), 30 min (a daily limit), else 90 s."""
    low = err.lower()
    rate_limited = any(k in low for k in _RATE_WORDS) or _RATE_CODE.search(low) is not None
    if not rate_limited and (_DEAD_CODES.search(low) or any(k in low for k in _DEAD_WORDS)):
        return 21600                                 # 6h — misconfigured/retired, not busy
    daily = any(k in low for k in ("day", "quota", "free_tier", "free-models"))
    return 1800 if daily else 90


def _mark_cooldown(name: str, err: str) -> None:
    """A rate-limited/exhausted provider is skipped for a while so we don't
    waste a failing round-trip on it every single turn."""
    _cooldown[name] = time.time() + _cooldown_seconds(err)


def cooling_now() -> list[str]:
    """Providers whose key in THIS request's chain is limited right now - Grammar Coach skips its optional AI calls while it is non-empty. With the per-key
    engine on it asks the per-key gate about the learner's own keys (an invalid key is not 'busy'); otherwise it is today's process-wide cooldown map."""
    ctx = _active_ctx.get()
    if ctx is not None and ctx.engine:
        chain = _active_chain.get() or settings.providers()
        now = time.time()
        out = set()
        for p in chain:
            st = gate.blocked(p["name"], gate.fingerprint(p["name"], p["key"]), now)
            if st is not None and st.status == "limited":
                out.add(p["name"])
        return sorted(out)
    return cooling_down()


async def _complete(messages: list[dict], max_tokens: int, prefer_fast: bool = False,
                    temperature: float = 0.7, first: str | None = None, cool: bool = True) -> str:
    """Every LLM call comes through here. With the per-key engine on for this learner (settings.key_health -> set_active_keys(engine=True)) the per-key walker
    answers; otherwise it is today's walker, untouched."""
    ctx = _active_ctx.get()
    if ctx is None:
        if not _unset["calls"]:
            print("[keys] an LLM call arrived with no key context (a call path that never called set_active_keys) - counted, served the legacy way")
        _unset["calls"] += 1
    elif ctx.engine:
        return await _complete_v2(messages, max_tokens, prefer_fast, temperature, first, cool)
    return await _complete_legacy(messages, max_tokens, prefer_fast, temperature, first, cool)


async def _complete_legacy(messages: list[dict], max_tokens: int, prefer_fast: bool = False,
                           temperature: float = 0.7, first: str | None = None, cool: bool = True) -> str:
    """Walk the provider chain → each provider's models → until one answers.
    Skips providers on cooldown; if every provider is cooling down, tries them
    anyway rather than failing.

    `prefer_fast=True` moves Groq (fastest inference in this stack) to the front
    of the chain — for latency-sensitive per-turn chat calls (conversation/
    interview/daily turns). One-shot heavy generations (career roadmap, full
    assessments) keep the default gemini-first order, where quality-per-call
    matters more than shaving latency (DUSU_SPEAKER_PROGRESSION_PLAN.md §9/§18).

    `first` (Grammar Coach): move that provider to the front of the chain when it is in it (ignored otherwise); default None = unchanged.
    `cool=False` (Grammar Coach): a rate-limit on THIS call does not mark the process-global provider cooldown - the cooldown map is keyed by
    provider name only, so a background grammar call must never cool Groq for everyone's chat. Default True = unchanged.

    `temperature` defaults to the conversational 0.7 every existing caller relies on.
    SCORING callers (Practice Room) pass a low value: measured on the same speech,
    0.7 moved a weak talk's overall score by up to 15 points between runs, 0.2 by
    up to 12 — so a re-score at 0.7 is mostly noise (DUSU_PRACTICE_ROOM_PLAN.md §4.3)."""
    last_err = None
    chain = _active_chain.get() or settings.providers()   # Office keys if set, else default
    if prefer_fast:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == "groq" else 1)
    if first:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == first else 1)          # stable: the rest keep their order
    # Hard ceiling on the WHOLE walk. Each attempt is capped at _REQUEST_TIMEOUT_S, but
    # the chain can hold 6+ model attempts across two passes — when everything is down
    # that stacked up to ~2 minutes of the user staring at "DuSu is getting ready".
    # Failing at 30s lets the client show a real error while the user still cares.
    deadline = time.time() + _CHAIN_DEADLINE_S
    for ignore_cd in (False, True):
        now = time.time()
        attempted = False
        for p in chain:
            if time.time() > deadline:
                break
            if not ignore_cd and _cooldown.get(p["name"], 0) > now:
                continue
            attempted = True
            client = _client(p)
            for model in p["models"]:
                if time.time() > deadline:
                    break
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
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
                        if cool:
                            _mark_cooldown(p["name"], s)  # whole provider limited
                        break                          # skip its other models
                    continue                           # other error → next model
        if attempted:
            break   # we tried the available providers; don't loop into ignore-pass
    raise RuntimeError(f"all providers/models unavailable: {last_err}")


# ------------------------------------------------------------------------------------------------------------------------------------------------
# The per-key walker (settings.key_health). Same shape as the legacy walker - chain order, models in order, the same deadline, the same text cleaning - but:
#   * the gate is keyed (provider, key fingerprint): one learner's limit never makes another learner's key look limited;
#   * every failure is classified ONCE (keys/classify.py) from the SDK's typed error: a rejected key (401, a Gemini 400 "API key not valid") is remembered
#     and skipped instead of being retried on every call; a limit is skipped for as long as the provider said (retry-after), else the legacy 90 s / 30 min;
#   * a timeout / connection error leaves the provider (the next model of the same provider will not do better in time); 5xx / retired model / bad
#     request still try the next model, exactly like before;
#   * every attempt is counted (keys/ledger.py) when it is dispatched and settled however it ends - including a cancellation;
#   * when EVERY key is gated it fails at once (no network) with a ProviderChainError that says which key failed how; one early probe a minute may let a
#     limit that ended early be noticed; a half-open probe is single-flight so concurrent callers cannot hammer a limited key.
# ------------------------------------------------------------------------------------------------------------------------------------------------
def _limit_seconds(out, err_text: str) -> float:
    """How long to skip a limited key: the provider's own retry-after (+1 s), else a daily limit 30 min / a per-minute one 90 s, else the legacy text classes."""
    return classify.limit_seconds(out, _cooldown_seconds(err_text))


def _gated_record(name: str, st) -> dict:
    kind = st.status
    if kind == "limited" and st.scope == "credit":
        kind = "needs_credit"
    return {"provider": name, "kind": kind, "scope": "" if st.scope == "credit" else st.scope, "reset_at": st.reset_at, "approx": st.approx, "expired": st.expired}


def _apply_failure(uid, name: str, fp: str, out, err: Exception, cool: bool, byok: bool, records: dict) -> str:
    """Record what a failed attempt taught us. Returns 'leave' (skip this provider's other models) or 'next' (try the next model)."""
    now = time.time()
    kind = out.kind
    sid = uid if byok else None                      # a status row is the learner's view of THEIR OWN keys; the server chain's keys have none
    if kind == "limited":
        secs = _limit_seconds(out, str(err))
        if byok or cool:                              # cool=False (Grammar Coach) on the server chain must not gate a key everyone's chat needs
            gate.mark_limited(name, fp, now, secs, scope=out.scope, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx, http=out.http)
        if cool and not byok:
            _cooldown[name] = now + secs              # the legacy display map (/health.cooling, the non-engine callers) says the same as the gate
        ledger.note_bad(sid, name, fp, "limited", "limited", now, scope=out.scope, http=out.http, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx)
        records[(name, fp)] = {"provider": name, "kind": "limited", "scope": out.scope, "reset_at": out.reset_at, "approx": out.approx}
        return "leave"
    if kind == "invalid":
        gate.mark_invalid(name, fp, now, http=out.http, expired=out.expired)
        ledger.note_bad(sid, name, fp, "invalid", "invalid", now, http=out.http, expired=out.expired)
        records[(name, fp)] = {"provider": name, "kind": "invalid", "expired": out.expired}
        return "leave"
    if kind == "forbidden":
        gate.mark_forbidden(name, fp, now, http=out.http)
        ledger.note_bad(sid, name, fp, "forbidden", "forbidden", now, http=out.http)
        records[(name, fp)] = {"provider": name, "kind": "forbidden"}
        return "leave"
    if kind == "needs_credit":
        gate.mark_limited(name, fp, now, 1800.0, scope="credit", http=out.http)
        ledger.note_bad(sid, name, fp, "limited", "needs_credit", now, http=out.http)
        records[(name, fp)] = {"provider": name, "kind": "needs_credit"}
        return "leave"
    # Not evidence about the key (a timeout, 5xx, a retired model, a bad request, text we cannot read): nothing is gated.
    records.setdefault((name, fp), {"provider": name, "kind": "transient"})
    if kind == "transient" and not out.http:
        return "leave"                                # a timeout / connection error: do not spend another 20 s on the same provider's next model
    return "next"


async def _complete_v2(messages: list[dict], max_tokens: int, prefer_fast: bool = False,
                       temperature: float = 0.7, first: str | None = None, cool: bool = True) -> str:
    ctx = _active_ctx.get()
    uid = ctx.uid if ctx else None
    own = _active_chain.get()                        # the learner's own keys, or None = the server's chain
    byok = own is not None
    chain = own or settings.providers()
    if prefer_fast:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == "groq" else 1)
    if first:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == first else 1)
    entries = [(p, gate.fingerprint(p["name"], p["key"])) for p in chain]
    if not entries:
        raise ProviderChainError("no keys configured", "no_keys", [])
    deadline = time.time() + _CHAIN_DEADLINE_S
    records: dict[tuple, dict] = {}
    last_err = None
    now = time.time()
    early = None
    if all(gate.peek(p["name"], fp, now) == "skip" for p, fp in entries):
        early = gate.soonest_probe([(p["name"], fp) for p, fp in entries], now)       # every key is gated: one early probe a minute at most
    for p, fp in entries:
        name = p["name"]
        if time.time() > deadline:
            break
        v = "probe" if (name, fp) == early else gate.verdict(name, fp, time.time())
        if v == "skip":
            st = gate.get(name, fp)
            if st is not None:
                records[(name, fp)] = _gated_record(name, st)
            continue
        try:
            client = _client(p)
            for model in p["models"]:
                if time.time() > deadline:
                    break
                tok = ledger.begin(uid, name, fp)
                done = False
                try:
                    raw = await client.chat.completions.with_raw_response.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        extra_body=p.get("extra") or {},
                    )
                    resp = raw.parse()
                    choice = resp.choices[0]
                    text = strip_reasoning(choice.message.content or "").strip()
                    usage = getattr(resp, "usage", None)
                    t_in, t_out = getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
                    if text:
                        ledger.settle(tok, "ok", t_in, t_out)
                        done = True
                        t_now = time.time()
                        changed = gate.mark_ok(name, fp, t_now)
                        ledger.note_ok(uid if byok else None, name, fp, t_now, classify.parse_ratelimit(name, getattr(raw, "headers", None), t_now), changed)
                        # A "length" finish means the model was CUT OFF mid-thought: trim back to the last complete sentence (same as the legacy walker).
                        if getattr(choice, "finish_reason", None) == "length":
                            trimmed = _trim_to_last_sentence(text)
                            if trimmed:
                                text = trimmed
                        return sanitize_hindi_respect(text)
                    ledger.settle(tok, "other", t_in, t_out)         # an empty answer: it cost a request and told us nothing about the key
                    done = True
                    records.setdefault((name, fp), {"provider": name, "kind": "transient"})
                except asyncio.CancelledError:
                    raise                                             # the `finally` below settles it as 'other'
                except Exception as e:
                    last_err = e
                    out = classify.classify(name, e)
                    ledger.settle(tok, out.kind if out.kind in ("limited", "invalid") else "other")
                    done = True
                    if _apply_failure(uid, name, fp, out, e, cool, byok, records) == "leave":
                        break
                finally:
                    if not done:
                        ledger.settle(tok, "other")
        finally:
            gate.release(name, fp)                                    # a half-open probe that ended without a verdict frees its slot
    keys = [records.get((p["name"], fp)) or {"provider": p["name"], "kind": "transient"} for p, fp in entries]
    state = chain_state(keys)
    if last_err is None:                                              # failed at once with nothing tried: say why in words the old string checks understand
        last_err = ("429 rate limit - the keys are skipped until they reset" if state == "all_limited" else
                    "401 the keys were rejected" if state == "all_invalid" else "no provider answered")
    raise ProviderChainError(last_err, state, keys)


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
    """Models don't always return clean JSON — strip code fences, pull the {...} block.

    Measured 2026-10-06 on Gemini flash-lite: ~1 reply in 9 was syntactically broken at
    the very end although the model had finished normally (finish_reason=stop, ~190
    tokens — NOT truncation). Two shapes were captured:
      * the root object closed early, then more keys followed:  …]}\n "genuine_effort":true}
      * a stray extra closing brace after the root object.
    json.loads and the greedy {...} regex both fail on either, so a perfectly good
    scorecard was thrown away. The first COMPLETE object is parsed with raw_decode and
    any trailing "key": value pairs are merged back in. Genuine truncation (no closing
    brace at all) still fails, as it should."""
    t = (text or "").strip()
    if t.startswith("```"):                       # ```json ... ``` fences
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    i = t.find("{")
    if i >= 0:
        try:
            obj, end = json.JSONDecoder().raw_decode(t[i:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            rest = t[i + end:].strip()
            if re.match(r'^"[^"]+"\s*:', rest):       # root closed early, more pairs follow
                try:
                    obj.update(json.loads("{" + rest))
                except json.JSONDecodeError:
                    pass
            return obj
    m = re.search(r"\{.*\}", t, re.DOTALL)         # greedy → to the last closing brace
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"error": "scoring_parse_failed", "raw": text[:500]}


class OpenRouterLLM:
    async def next_question(self, system: str, transcript: list[dict], seed: str | None = None) -> str:
        messages = [{"role": "system", "content": system}, *_recent(transcript)]
        # Some providers (Gemini) reject a system-only request — DuSu speaks first
        # with an empty transcript, so seed a user turn to kick it off. `seed` lets a
        # non-English session open in its own language (default = the original English line).
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user",
                             "content": seed or "Let's begin. Greet me and ask your first question."})
        # 420 (was 320): the persona asks for 2-4 spoken sentences and a follow-up
        # question; 320 clipped the longer, more interesting turns mid-word.
        return await _complete(messages, max_tokens=420, prefer_fast=True)   # per-turn chat (§9)

    async def next_question_stream(self, system: str, transcript: list[dict], seed: str | None = None):
        """Same as next_question, but yields whole sentences as they're written."""
        messages = [{"role": "system", "content": system}, *_recent(transcript)]
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user",
                             "content": seed or "Let's begin. Greet me and ask your first question."})
        async for s in stream_sentences(messages, max_tokens=420, prefer_fast=True):
            yield s

    async def translate(self, system: str, text: str, max_tokens: int = 120) -> str:
        # Devanagari costs several times the tokens of the same sentence in English, so the
        # English->Hindi direction asks for a bigger budget (the default is unchanged).
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": text}]
        return await _complete(messages, max_tokens=max_tokens)

    async def generate(self, system: str, prompt: str, max_tokens: int = 500) -> str:
        """Free-form prose (weekly letters, session summaries). Returns raw text."""
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        return await _complete(messages, max_tokens=max_tokens)

    async def assess(self, system: str, payload: str, max_tokens: int = 700, prefer_fast: bool = False,
                     temperature: float = 0.7, first: str | None = None, cool: bool = True) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": payload + "\n\nReturn ONLY the JSON object."},
        ]
        return _extract_json(await _complete(messages, max_tokens=max_tokens, prefer_fast=prefer_fast,
                                             temperature=temperature, first=first, cool=cool))

    async def score(self, system: str, transcript: list[dict], max_tokens: int = 1200) -> dict:
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": convo + "\n\nReturn ONLY the JSON object."},
        ]
        return _extract_json(await _complete(messages, max_tokens=max_tokens))
