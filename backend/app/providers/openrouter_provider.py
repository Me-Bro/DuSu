"""LLM provider chain (all OpenAI-compatible: Gemini, OpenRouter, Groq, …).

Every provider exposes the OpenAI Chat Completions shape, so one OpenAI client
per provider (different base_url + key) drives them all. On any failure — quota
(429/402), model gone (404), bad request — we fall through to the next model,
then the next provider. Configure the chain in config.Settings.providers().

Speech is browser-side; the model only ever sees and emits text.
"""

import asyncio
import json
import random
import re
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass

from openai import AsyncOpenAI

from ..config import settings
from ..keys import classify, gate, ledger
from ..keys.errors import BadReplyError, ProviderChainError, chain_state

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
    """Whose keys this request / connection is using. `uid` = who to count for. `engine` = which walker answers: 0 = today's (legacy) walker, 1 = the per-key walker
    (settings.key_health), 2 = the per-key walker PLUS the validated walk (settings.chain_v3: an unusable reply is a failure that moves on to the next model)."""
    uid: str | None = None
    engine: int = 0


_active_ctx: ContextVar[KeyCtx | None] = ContextVar("_active_ctx", default=None)
_unset = {"calls": 0}                    # LLM calls that arrived with no key context at all (a call path that forgot set_active_keys)


def set_active_keys(keys: dict | None, uid: str | None = None, engine: bool | int = 0) -> None:
    """Office mode: route this request/connection's LLM calls through the user's keys.
    Pass a falsy value / empty dict to use the default (Personal) chain.
    `uid` / `engine` (settings.key_health / settings.chain_v3): who the calls are counted for, and which walker runs (False / 0 legacy, True / 1 per-key, 2 per-key +
    validated) - every call site passes them (an AST test in tests/keys/unit.py fails the build if one forgets `uid=` or `engine=`), because a forgotten site would
    silently skip the accounting."""
    chain = settings.providers_from(keys) if keys else None
    _active_chain.set(chain or None)
    _active_ctx.set(KeyCtx(uid=uid, engine=max(0, min(2, int(engine or 0)))))


_last_bad: ContextVar[BadReplyError | None] = ContextVar("_last_bad", default=None)      # the unusable-reply failure of the most recent assess() / score() in THIS task


def last_bad() -> BadReplyError | None:
    """The BadReplyError the most recent assess() / score() call in this task turned into the parse-failure sentinel (None when it succeeded). The few callers that answer with an
    HTTP error use it to attach the learner-facing `kp` - 'the AI did not answer properly, try again' - instead of a bare 502."""
    return _last_bad.get()


def chain_v3_active() -> bool:
    """Is the validated walk on for THIS request? (Callers use it to drop their own retry loops: the walk has already tried every model.)"""
    ctx = _active_ctx.get()
    return bool(ctx is not None and ctx.engine >= 2)


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
                    temperature: float = 0.7, first: str | None = None, cool: bool = True, accept=None, cls: str = "chat") -> str:
    """Every LLM call comes through here. With the per-key engine on for this learner (settings.key_health -> set_active_keys(engine=1)) the per-key walker
    answers; with the validated walk on as well (settings.chain_v3 -> engine=2) it also judges every reply with `accept` (see `_v2_pass`); otherwise it is today's
    walker, untouched. `accept` / `cls` are ignored unless engine >= 2."""
    ctx = _active_ctx.get()
    if ctx is None:
        if not _unset["calls"]:
            print("[keys] an LLM call arrived with no key context (a call path that never called set_active_keys) - counted, served the legacy way")
        _unset["calls"] += 1
    elif ctx.engine:
        return await _complete_v2(messages, max_tokens, prefer_fast, temperature, first, cool, accept if ctx.engine >= 2 else None, cls)
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
#     and skipped instead of being retried on every call; a limit is skipped for as long as the provider said (retry-after), else the legacy 90 s / 30 min
#     (20 s for a busy shared free pool);
#   * Gemini and Groq publish their free limits PER MODEL (and OpenRouter's busy-upstream 429 is per model too): a 429 on one model tries the provider's next model, and the
#     KEY is gated only when every model is limited;
#   * a model the provider says does not exist (404) is remembered for 30 minutes, per key, instead of costing a round trip on every turn;
#   * a timeout / connection error leaves the provider (the next model of the same provider will not do better in time); 5xx / bad request still try the next model;
#   * when a failure was a passing one (a timeout, a 5xx, an empty answer, a limit that ends in a few seconds) the walk waits that long and goes round ONCE more -
#     never for a rejected key, a limit with a long wait, or a background caller (cool=False), and only while the 30 s ceiling leaves room;
#   * every attempt is counted (keys/ledger.py) when it is dispatched and settled however it ends - including a cancellation;
#   * when EVERY key is gated it fails at once (no network) with a ProviderChainError that says which key failed how; one early probe a minute may let a
#     limit that ended early be noticed; a half-open probe is single-flight so concurrent callers cannot hammer a limited key;
#   * a failed walk leaves ONE safe log line (provider / model / kind - never text, never a key) so the next "AI busy" can be explained afterwards.
# The VALIDATED walk (settings.chain_v3, engine 2) adds: a reply is judged by the caller's `accept` function (valid JSON with the fields the caller needs, not cut off,
# not empty). An unusable reply is a failure like any other: the model is held back for that kind of call (20 s, doubling to 10 min; one good reply clears it), the walk
# goes on to the NEXT PROVIDER in the same call (a different family, its own budget), its siblings follow in a second pass - and only when nothing usable came back does
# the caller get a BadReplyError. Before, `if text:` was the only test: a broken reply counted as success, the model stayed "healthy", and every caller's own retry asked
# the same model again.
# ------------------------------------------------------------------------------------------------------------------------------------------------
# The validated walk also keeps TIME (settings.chain_v3, engine 2): an interactive per-turn call gives each attempt 8 s (prose) / 11 s (a JSON turn) instead of 20, and the whole
# walk 16 s / 22 s instead of 30 - an attempt is cut to what is left of the walk, so a walk can no longer run past its ceiling, and the LAST provider (nowhere else to switch to)
# gets everything that is left instead of the short limit; a model that fails to ANSWER three times in a row
# (timeouts, 5xx, connection errors) has its breaker opened for a minute (then one probe, doubling) so the next turn does not wait on it again; and the providers are asked in
# the order of how they are doing (a measured-good provider before a measured-bad one; close scores keep the configured order). Everything else (scoring, extraction) keeps 20 / 30.
_ATTEMPT_S = {"chat": 8.0, "json": 11.0}        # per attempt, an interactive per-turn call
_ATTEMPT_HEAVY_S = 20.0                          # per attempt, everything else (scoring, extraction, background) - as before
_WALK_S = {"chat": 16.0, "json": 22.0}          # the whole walk, an interactive per-turn call
_MIN_ATTEMPT_S = 1.0                             # less than this of the walk left: not worth another request


def _attempt_timeout(cls: str, interactive: bool) -> float:
    return _ATTEMPT_S.get(cls, 11.0) if interactive else _ATTEMPT_HEAVY_S


def _walk_deadline(cls: str, interactive: bool) -> float:
    return _WALK_S.get(cls, 22.0) if interactive else _CHAIN_DEADLINE_S


PER_MODEL_LIMITS = frozenset({"gemini", "groq"})
_REPASS_PAUSE_S = 1.2          # a passing failure: wait this (+ up to 0.6 s of jitter) before the second pass
_REPASS_MAX_WAIT_S = 5.0       # a limit that ends sooner than this is waited out instead of failing the turn
_REPASS_MIN_LEFT_S = 6.0       # the second pass needs at least this much of the 30 s ceiling to be left after the wait
_pause = asyncio.sleep         # tests replace it, so a second pass does not really wait
_fail_logged: dict[str, float] = {}
_gone_logged: dict[tuple, float] = {}
_LOG_EVERY_S = 30.0

# What every attempt did, in the order it happened (bounded): the owner's "model health" card and the tests read it. Provider / model NAMES are our own configuration;
# there is no learner id, no key, no text and no fingerprint in it.
_ring: deque = deque(maxlen=600)


def _ring_add(provider: str, model: str, cls: str, kind: str, ms: float, t_in: int = 0, t_out: int = 0, finish: str | None = None, why: str = "") -> None:
    _ring.append({"t": time.time(), "p": provider, "m": model, "c": cls, "k": kind, "ms": int(ms), "in": int(t_in or 0), "out": int(t_out or 0), "fin": finish or "", "why": why[:40]})


def chain_health(window_s: float = 3600.0, now: float | None = None) -> list[dict]:
    """Per (provider, model, class) over the last `window_s`: attempts and how they ended, the mean and the slowest answer. For the owner's dashboard."""
    now = time.time() if now is None else now
    agg: dict = {}
    for r in list(_ring):
        if now - r["t"] > window_s:
            continue
        a = agg.setdefault((r["p"], r["m"], r["c"]), {"provider": r["p"], "model": r["m"], "class": r["c"], "n": 0, "ok": 0, "bad": 0, "limited": 0, "failed": 0, "ms_sum": 0, "ms_max": 0})
        a["n"] += 1
        k = r["k"]
        a["ok" if k == "ok" else "bad" if k == "bad" else "limited" if k == "limited" else "failed"] += 1
        a["ms_sum"] += r["ms"]
        a["ms_max"] = max(a["ms_max"], r["ms"])
    out = []
    for a in agg.values():
        a["ms_avg"] = int(a.pop("ms_sum") / max(1, a["n"]))
        out.append(a)
    return sorted(out, key=lambda a: (a["provider"], a["model"], a["class"]))


def model_health(now: float | None = None) -> list[dict]:
    """Every measured model: its success rate, its speed and whether its breaker is open (owner's dashboard)."""
    return gate.health_view(time.time() if now is None else now)


def _rejects_params(err: Exception, sent: dict) -> bool:
    """Did a 400 complain about the extra request parameters we added (a reasoning setting this model does not take)?"""
    text = classify._text(err)
    if any(str(k).lower() in text for k in sent):
        return True
    return any(w in text for w in ("unsupported parameter", "unrecognized request argument", "extra inputs are not permitted", "unknown parameter", "unknown field"))


def _limit_seconds(out, err_text: str) -> float:
    """How long to skip a limited key: the provider's own retry-after (+1 s), else a daily limit 30 min / a per-minute one 90 s / a busy shared pool 20 s,
    else the legacy text classes."""
    return classify.limit_seconds(out, _cooldown_seconds(err_text))


def _gated_record(name: str, st) -> dict:
    kind = st.status
    if kind == "limited" and st.scope == "credit":
        kind = "needs_credit"
    rec = {"provider": name, "kind": kind, "scope": "" if st.scope == "credit" else st.scope, "reset_at": st.reset_at, "approx": st.approx, "expired": st.expired}
    if kind == "limited":
        rec["retry_s"] = max(0.0, st.until - time.time())
    return rec


def _tag(out) -> str:
    """'limited-429-minute', 'transient-503', 'model_gone-404', 'transient-noresponse' - what a failed attempt was, for the log line. Never any provider text."""
    bits = [out.kind]
    if out.http:
        bits.append(str(out.http))
    elif out.kind == "transient":
        bits.append("noresponse")
    if out.kind == "limited" and out.scope:
        bits.append(out.scope)
    return "-".join(bits)


def _log_failure(state: str, byok: bool, attempts: list) -> None:
    """ONE line per failed walk (the same line at most every 30 s). Provider and model NAMES are our own configuration; a key, a learner's id or anything the
    provider wrote (it can echo the learner's words) never goes in."""
    line = f"[keys] chain failed: state={state} own={'yes' if byok else 'no'} tried={', '.join(attempts) or 'nothing'}"
    now = time.time()
    if now - _fail_logged.get(line, 0.0) < _LOG_EVERY_S:
        return
    if len(_fail_logged) > 200:
        _fail_logged.clear()
    _fail_logged[line] = now
    print(line)


def _log_gone(name: str, model: str, http: int) -> None:
    now = time.time()
    k = (name, model)
    if now - _gone_logged.get(k, 0.0) < 1800.0:
        return
    _gone_logged[k] = now
    print(f"[keys] model not found: {name}/{model} (HTTP {http}) - skipped for 30 min; if this is DuSu's own chain, update config.py")


class _Walk:
    """State shared by the passes of one walk."""
    __slots__ = ("last_err", "wait", "bad", "bad_models", "retry_now", "ignore_bad", "asked", "skipped_bad")

    def __init__(self):
        self.last_err = None
        self.wait = None          # seconds to wait before a second pass (None = a second pass would not help)
        self.bad: list[str] = []  # 'provider/model:reason' of every reply that came back UNUSABLE (our own words, never the provider's)
        self.bad_models: set = set()   # (provider, model) that answered unusably IN THIS WALK - not asked again by it, whether or not the gate remembers them
        self.retry_now = False    # go round once more AT ONCE: a provider was left after an unusable reply (its other models are still unasked)
        self.ignore_bad = False   # the next pass asks even a model that is being held back (every model was, and nothing was sent)
        self.asked = 0            # requests actually sent in the current pass
        self.skipped_bad = 0      # models skipped in the current pass because their last replies were unusable

    def want(self, secs: float) -> None:
        self.wait = secs if self.wait is None else min(self.wait, secs)


def _limit_key(sid, name: str, fp: str, secs: float, out, cool: bool, byok: bool, records: dict) -> None:
    """The KEY is limited (its provider limits per key, or every one of its models is): gate it, show it to the learner, remember it."""
    now = time.time()
    if byok or cool:                                  # cool=False (Grammar Coach) on the server chain must not gate a key everyone's chat needs
        gate.mark_limited(name, fp, now, secs, scope=out.scope, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx, http=out.http)
    if cool and not byok:
        _cooldown[name] = now + secs                  # the legacy display map (/health.cooling, the non-engine callers) says the same as the gate
    ledger.note_bad(sid, name, fp, "limited", "limited", now, scope=out.scope, http=out.http, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx)
    records[(name, fp)] = {"provider": name, "kind": "limited", "scope": out.scope, "reset_at": out.reset_at, "approx": out.approx, "retry_s": secs}


def _apply_failure(uid, name: str, fp: str, model: str, out, err: Exception, cool: bool, byok: bool, records: dict, lim: list, w: _Walk) -> str:
    """Record what a failed attempt taught us. Returns 'leave' (skip this provider's other models), 'next' (try the next model), 'limited_model' (this ONE model is
    limited - try the next, decide about the key after the loop) or 'gone' (the model does not exist - try the next, it never counts against the key)."""
    now = time.time()
    kind = out.kind
    sid = uid if byok else None                      # a status row is the learner's view of THEIR OWN keys; the server chain's keys have none
    if kind == "limited":
        secs = _limit_seconds(out, str(err))
        if secs <= _REPASS_MAX_WAIT_S:
            w.want(secs + 0.25)                       # a limit that ends in seconds is waited out, not shown to the learner
        if name in PER_MODEL_LIMITS or out.scope == "upstream":      # a busy UPSTREAM pool (OpenRouter's free models) is per model as well: the next model has its own pool
            if byok or cool:
                gate.mark_model_limited(name, fp, model, now, secs, scope=out.scope, reset_at=out.reset_at, evidence=out.evidence, approx=out.approx, http=out.http)
            lim.append((model, secs, out))
            return "limited_model"
        _limit_key(sid, name, fp, secs, out, cool, byok, records)
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
    if kind == "model_gone":
        gate.mark_model_gone(name, fp, model, now, http=out.http)     # the provider says this model does not exist: not asked again for 30 minutes (per key)
        _log_gone(name, model, out.http)
        records.setdefault((name, fp), {"provider": name, "kind": "unavailable"})
        return "gone"
    # Not evidence about the key (a timeout, 5xx, a bad request, text we cannot read): nothing is gated.
    records.setdefault((name, fp), {"provider": name, "kind": "transient"})
    if kind == "transient":
        w.want(_REPASS_PAUSE_S + random.random() * 0.6)                # a passing failure: worth one more pass
        if not out.http:
            return "leave"                                              # a timeout / connection error: do not spend another 20 s on the same provider's next model
    return "next"


async def _v2_pass(entries: list, messages: list, max_tokens: int, temperature: float, uid, byok: bool, cool: bool, deadline: float,
                   records: dict, attempts: list, w: _Walk, first_pass: bool, accept=None, cls: str = "chat", chat: bool = False, v3: bool = False):
    """One walk round the chain. Returns the reply text, or None when nothing answered (what was learned is in `records` / `attempts` / `w`).
    `accept` (the validated walk, engine 2) judges every reply: it returns None for a usable one, else a short reason in our own words; `cls` is the kind of call
    ('json' = a structured turn, 'chat' = prose) - what is held against a model is held per kind. `chat` = a per-turn chat call (prefer_fast): the provider entry's
    `chat_extra[model]` request params are added to that one request (config.py `_groq_chat_extra`). `v3` = the validated walk: every attempt has a time limit and a
    model whose breaker is open is not asked (gate.health_*)."""
    w.asked = 0
    w.skipped_bad = 0
    early = None
    if first_pass:
        now = time.time()
        if all(gate.peek(p["name"], fp, now) == "skip" for p, fp in entries):
            early = gate.soonest_probe([(p["name"], fp) for p, fp in entries], now)       # every key is gated: one early probe a minute at most
    for ei, (p, fp) in enumerate(entries):
        name = p["name"]
        last_provider = ei == len(entries) - 1       # nowhere else to go after this one: cutting it short would only throw an answer away
        if time.time() > deadline:
            break
        v = "probe" if (name, fp) == early else gate.verdict(name, fp, time.time())
        if v == "skip":
            st = gate.get(name, fp)
            if st is not None:
                records[(name, fp)] = _gated_record(name, st)
                attempts.append(f"{name}:skipped-{st.status}")
            continue
        if (name, fp) == early:
            gate.probe_soonest_model(name, fp, p["models"], time.time())     # the early probe must reach a model whose own memory would still skip it
        lim: list = []                                # this provider's models that are limited right now: (model, seconds, Outcome)
        n_live = 0                                    # its models that exist (a model the provider says is gone does not count)
        other = False                                 # some model failed for a reason that is not "limited"
        try:
            client = _client(p)
            for mi, model in enumerate(p["models"]):
                if time.time() > deadline:
                    break
                if accept is not None and not w.ignore_bad and ((name, model) in w.bad_models or gate.bad_blocked(name, fp, model, cls, time.time()) is not None):
                    n_live += 1                       # it exists - it is only being held back because its last replies were unusable, so the KEY is not "limited"
                    other = True
                    w.skipped_bad += 1
                    attempts.append(f"{name}/{model}:skipped-bad")
                    continue
                mv = gate.model_verdict(name, fp, model, time.time())
                if mv == "skip":                      # remembered: asked again only when its time is up (no request, no wasted second)
                    ms = gate.model_get(name, fp, model)
                    if ms is not None and ms.status == "gone":
                        attempts.append(f"{name}/{model}:skipped-gone")
                        records.setdefault((name, fp), {"provider": name, "kind": "unavailable"})
                    elif ms is not None:
                        n_live += 1
                        attempts.append(f"{name}/{model}:skipped-limited")
                        lim.append((model, max(0.0, ms.until - time.time()),
                                    classify.Outcome("limited", http=ms.http or 429, scope=ms.scope, reset_at=ms.reset_at, evidence=ms.evidence, approx=ms.approx)))
                    continue
                hprobe = False
                if v3:
                    hv = gate.health_verdict(name, model, cls, time.time())
                    if hv == "skip" and not w.ignore_bad:       # it failed to ANSWER three times in a row a moment ago: do not make this turn wait on it as well
                        gate.model_release(name, fp, model)       # (a half-open probe of the model's own limit may have been taken just above)
                        n_live += 1
                        other = True
                        w.skipped_bad += 1
                        attempts.append(f"{name}/{model}:skipped-breaker")
                        continue
                    hprobe = hv == "probe"
                    if deadline - time.time() < _MIN_ATTEMPT_S:   # the walk's own ceiling: not enough of it left for another request
                        if hprobe:
                            gate.health_release(name, model, cls)
                        gate.model_release(name, fp, model)
                        break
                n_live += 1
                extra = p.get("extra") or {}
                sent: dict = {}
                if chat and v3:                           # a per-turn CHAT call (validated walk only): params only chat wants (Groq's gpt-oss: think briefly - an empty reply costs a whole prompt of the minute)
                    ce = (p.get("chat_extra") or {}).get(model)
                    if ce and not gate.param_unsupported(name, model, time.time()):      # a model that answered 400 to them is sent without
                        sent = ce
                        extra = {**extra, **ce}
                tok = ledger.begin(uid, name, fp)
                done = False
                t0 = time.time()
                w.asked += 1
                try:
                    rem = deadline - time.time()
                    kw = {"timeout": max(_MIN_ATTEMPT_S, rem if last_provider else min(_attempt_timeout(cls, chat), rem))} if v3 else {}      # the last provider gets what is left of the walk
                    raw = await client.chat.completions.with_raw_response.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        extra_body=extra,
                        **kw,
                    )
                    resp = raw.parse()
                    choice = resp.choices[0]
                    text = strip_reasoning(choice.message.content or "").strip()
                    finish = getattr(choice, "finish_reason", None)
                    usage = getattr(resp, "usage", None)
                    t_in, t_out = getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
                    ms_taken = (time.time() - t0) * 1000
                    if accept is not None:
                        reason = "empty" if not text else accept(text, finish)
                    else:
                        reason = None if text else "empty"
                    if reason is None:
                        ledger.settle(tok, "ok", t_in, t_out)
                        done = True
                        t_now = time.time()
                        gate.model_ok(name, fp, model)
                        changed = gate.mark_ok(name, fp, t_now)
                        ledger.note_ok(uid if byok else None, name, fp, t_now, classify.parse_ratelimit(name, getattr(raw, "headers", None), t_now), changed)
                        if accept is not None:
                            gate.bad_ok(name, fp, model, cls)                     # a usable reply: whatever was held against this model for this kind of call is over
                        if v3:
                            gate.health_ok(name, model, cls, ms_taken, t_now)
                        _ring_add(name, model, cls, "ok", ms_taken, t_in, t_out, finish)
                        # A "length" finish means the model was CUT OFF mid-thought: prose is trimmed back to the last complete sentence (same as the legacy walker).
                        # JSON that was cut off never gets here with the validated walk (its accept function rejects it) and is never trimmed - a cut object is not a smaller object.
                        if finish == "length" and not (accept is not None and cls == "json"):
                            trimmed = _trim_to_last_sentence(text)
                            if trimmed:
                                text = trimmed
                        return sanitize_hindi_respect(text)
                    if text:                                              # it ANSWERED, but there is nothing to use: the request counted and the key works
                        ledger.settle(tok, "ok", t_in, t_out)
                        t_now = time.time()
                        gate.model_ok(name, fp, model)
                        changed = gate.mark_ok(name, fp, t_now)
                        ledger.note_ok(uid if byok else None, name, fp, t_now, classify.parse_ratelimit(name, getattr(raw, "headers", None), t_now), changed)
                    else:
                        ledger.settle(tok, "other", t_in, t_out)         # an empty answer: it cost a request and told us nothing about the key
                    done = True
                    other = True
                    records.setdefault((name, fp), {"provider": name, "kind": "transient"})
                    if accept is None:                                    # the per-key walker without validation: exactly as before
                        attempts.append(f"{name}/{model}:empty")
                        w.want(_REPASS_PAUSE_S + random.random() * 0.6)
                        continue
                    attempts.append(f"{name}/{model}:bad_output({reason})")
                    w.bad.append(f"{name}/{model}:{reason}")
                    w.bad_models.add((name, model))
                    if byok or cool:                                      # a background call (cool=False) on DuSu's own chain must not hold a model back for everyone's chat
                        gate.mark_bad(name, fp, model, cls, time.time(), reason)
                    if v3:
                        gate.health_fail(name, model, cls, "bad", time.time())
                    _ring_add(name, model, cls, "bad", ms_taken, t_in, t_out, finish, reason)
                    if first_pass:                                        # ANOTHER PROVIDER first (a different family, its own budget); this one's other models follow in the second pass
                        if mi + 1 < len(p["models"]):
                            w.retry_now = True
                        break
                except asyncio.CancelledError:
                    raise                                             # the `finally` below settles it as 'other'
                except Exception as e:
                    w.last_err = e
                    out = classify.classify(name, e)
                    ledger.settle(tok, out.kind if out.kind in ("limited", "invalid") else "other")
                    done = True
                    attempts.append(f"{name}/{model}:{_tag(out)}")
                    if sent and out.kind == "bad_request" and _rejects_params(e, sent):
                        gate.mark_param_unsupported(name, model, time.time())     # this model does not take our extra parameters: from now on it is sent without them
                        attempts.append(f"{name}/{model}:param-rejected")
                    _ring_add(name, model, cls, out.kind, (time.time() - t0) * 1000, why=str(out.http or ""))
                    if v3 and out.kind == "transient":
                        gate.health_fail(name, model, cls, "transient", time.time())      # it did not ANSWER (a timeout, a 5xx, a connection error): counts toward its breaker
                    act = _apply_failure(uid, name, fp, model, out, e, cool, byok, records, lim, w)
                    if act == "gone":
                        n_live -= 1
                    elif act != "limited_model":
                        other = True
                    if act == "leave":
                        break
                finally:
                    if not done:
                        ledger.settle(tok, "other")
                    gate.model_release(name, fp, model)               # a half-open probe of this model that ended without a verdict frees its slot
                    if hprobe:
                        gate.health_release(name, model, cls)
            if lim and not other and len(lim) == n_live:
                soonest = min(lim, key=lambda x: x[1])                # every model that exists is limited: now the KEY is limited, until the first of them frees up
                _limit_key(uid if byok else None, name, fp, soonest[1], soonest[2], cool, byok, records)
        finally:
            gate.release(name, fp)                                    # a half-open probe that ended without a verdict frees its slot
    return None


async def _complete_v2(messages: list[dict], max_tokens: int, prefer_fast: bool = False,
                       temperature: float = 0.7, first: str | None = None, cool: bool = True, accept=None, cls: str = "chat") -> str:
    ctx = _active_ctx.get()
    uid = ctx.uid if ctx else None
    own = _active_chain.get()                        # the learner's own keys, or None = the server's chain
    byok = own is not None
    chain = own or settings.providers()
    v3 = bool(ctx is not None and ctx.engine >= 2)
    if prefer_fast:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == "groq" else 1)
    if v3:                                           # best-first by how each provider is doing now; providers whose scores are close keep the order they were in
        rank = {n: i for i, n in enumerate(gate.order_by_health([p["name"] for p in chain], time.time()))}
        chain = sorted(chain, key=lambda p: rank[p["name"]])
    if first:
        chain = sorted(chain, key=lambda p: 0 if p["name"] == first else 1)
    entries = [(p, gate.fingerprint(p["name"], p["key"])) for p in chain]
    if not entries:
        raise ProviderChainError("no keys configured", "no_keys", [], own=byok)
    deadline = time.time() + (_walk_deadline(cls, prefer_fast) if v3 else _CHAIN_DEADLINE_S)
    records: dict[tuple, dict] = {}
    attempts: list[str] = []
    w = _Walk()
    for pass_no in (0, 1):
        text = await _v2_pass(entries, messages, max_tokens, temperature, uid, byok, cool, deadline, records, attempts, w, pass_no == 0,
                              accept=accept, cls=cls, chat=prefer_fast, v3=v3)
        if text is not None:
            return text
        if pass_no == 0:
            if (accept is not None or v3) and w.asked == 0 and w.skipped_bad:
                w.ignore_bad = True                  # every model was being held back (an unusable reply, an open breaker) and nothing was sent: ask them anyway rather than fail without a single attempt
                w.retry_now = True
            if cool and w.wait is not None and deadline - time.time() >= w.wait + _REPASS_MIN_LEFT_S:
                attempts.append("pause")
                pause, w.wait = w.wait, None
                w.retry_now = False
                await _pause(pause)                  # a passing failure (or a limit that ends in seconds): wait it out, then ONE more pass
                continue
            if w.retry_now and deadline - time.time() >= _REPASS_MIN_LEFT_S:
                attempts.append("again")
                w.retry_now = False
                continue                             # an unusable reply left a provider early: its other models (and a model held back with nothing else to ask) go now
        break
    keys = [records.get((p["name"], fp)) or {"provider": p["name"], "kind": "transient"} for p, fp in entries]
    state = chain_state(keys)
    last_err = w.last_err
    if last_err is None:                                              # failed at once with nothing tried: say why in words the old string checks understand
        last_err = ("429 rate limit - the keys are skipped until they reset" if state == "all_limited" else
                    "401 the keys were rejected" if state == "all_invalid" else "no provider answered")
    _log_failure(state, byok, attempts)
    if w.bad:                                                          # somebody answered, nobody answered USABLY: the learner is told the AI did not answer properly, never "your keys"
        raise BadReplyError("no usable reply (" + ", ".join(w.bad[:4]) + ")", keys, own=byok, reasons=w.bad)
    raise ProviderChainError(last_err, state, keys, own=byok)


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
        whole = json.loads(t)
        if isinstance(whole, dict):                   # a list / string / number is valid JSON but never the object every caller expects (`.get` on a list crashes the turn)
            return whole
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


# ---- the validators of the validated walk (settings.chain_v3). An `accept` function gets (text, finish_reason) and returns None for a usable reply, else a short reason
# in OUR words (it goes into the log line and the model's penalty - never anything the provider wrote). `cls` tells the gate which kind of call the reply was for.
_FIELD_TYPES = {
    "str": lambda v: isinstance(v, str),
    "str+": lambda v: isinstance(v, str) and v.strip() != "",          # a non-empty string
    "bool": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
    "num": lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)) or (isinstance(v, str) and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*%?\s*", v) is not None),
}


def _closed_object(t: str) -> bool:
    """Does this text END like a finished JSON object (ignoring a closing code fence)? A reply that stopped because it ran out of tokens does not."""
    return t.rstrip().rstrip("`").rstrip().endswith("}")


def json_accept(fields: dict | None = None, check=None):
    """The accept function for a call that must answer with ONE JSON object. `fields` = {name: type} with type in str / str+ / bool / list / dict / num (a missing or wrong-typed
    field is a rejection that names it); `check(d)` may add a rule of its own (return a reason or None). A reply that was CUT OFF (finish_reason 'length' without a closing
    brace) is rejected - never trimmed, never half-parsed."""
    want = dict(fields or {})

    def accept(text: str, finish) -> str | None:
        t = (text or "").strip()
        if finish == "length" and not _closed_object(t):
            return "truncated"
        d = _extract_json(t)
        if not isinstance(d, dict) or (d.get("error") == "scoring_parse_failed" and "raw" in d):
            return "not_json"
        for k, typ in want.items():
            v = d.get(k)
            if k not in d or v is None:
                return f"missing:{k}"
            if not _FIELD_TYPES[typ](v):
                return f"bad:{k}"
        if check is not None:
            r = check(d)
            if r:
                return str(r)[:40]
        return None

    return accept


def chat_accept(text: str, finish) -> str | None:
    """Prose: anything non-empty is usable (the walker already rejects an empty reply; a cut-off one is trimmed to its last sentence, as it always was)."""
    return None


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
        return await _complete(messages, max_tokens=420, prefer_fast=True, accept=chat_accept, cls="chat")   # per-turn chat (§9)

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
        return await _complete(messages, max_tokens=max_tokens, accept=chat_accept, cls="chat")

    async def generate(self, system: str, prompt: str, max_tokens: int = 500) -> str:
        """Free-form prose (weekly letters, session summaries). Returns raw text."""
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        return await _complete(messages, max_tokens=max_tokens, accept=chat_accept, cls="chat")

    def v3_active(self) -> bool:
        """Is the validated walk on for this request? (A caller then drops its own retry loop: the walk has already tried every model.)"""
        return chain_v3_active()

    def last_bad(self) -> BadReplyError | None:
        return last_bad()

    async def assess(self, system: str, payload: str, max_tokens: int = 700, prefer_fast: bool = False,
                     temperature: float = 0.7, first: str | None = None, cool: bool = True, schema: dict | None = None, check=None) -> dict:
        """One JSON object. With the validated walk on, `schema` ({field: type}, see json_accept) and `check` are enforced INSIDE the walk: a reply that is not that object
        is a failed attempt and the next model answers. If no model gave a usable one this returns the same failure shape callers already handle
        ({"error": "scoring_parse_failed"}) - never a half-parsed object. With it off, nothing changes."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": payload + "\n\nReturn ONLY the JSON object."},
        ]
        try:
            text = await _complete(messages, max_tokens=max_tokens, prefer_fast=prefer_fast, temperature=temperature, first=first, cool=cool,
                                   accept=json_accept(schema, check), cls="json")
        except BadReplyError as e:
            _last_bad.set(e)
            return {"error": "scoring_parse_failed", "raw": ""}
        _last_bad.set(None)
        return _extract_json(text)

    async def score(self, system: str, transcript: list[dict], max_tokens: int = 1200) -> dict:
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": convo + "\n\nReturn ONLY the JSON object."},
        ]
        try:
            text = await _complete(messages, max_tokens=max_tokens, accept=json_accept({"overall": "num"}), cls="json")
        except BadReplyError as e:
            _last_bad.set(e)
            return {"error": "scoring_parse_failed", "raw": ""}
        _last_bad.set(None)
        return _extract_json(text)
