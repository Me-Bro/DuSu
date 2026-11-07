"""Keys - ONE classifier: what did this provider just tell us about THIS key?

Before this module six places each decided with their own substring tests ("rate" matches "generate", "quota" is both a minute limit and a day limit,
only the LAST error was read, a Gemini 400 "API key not valid" never matched anything so a dead key was retried on every call). Everything now asks `classify`.

Pure: no I/O, no clock except an argument, never raises. Input is the exception the OpenAI SDK raised (typed: `.status_code`, `.body`, `.response.headers`) -
duck-typed so a test can hand it a stand-in. Output is an `Outcome`.

The one rule that matters: **only positive evidence marks a key invalid.** A 401 is evidence on every provider, a Gemini 400 that says the key is not valid is
evidence; a timeout, a 5xx, a 404 (the platform retired a model), an unknown 4xx or text we cannot read is NEVER evidence about the key.
"""

from __future__ import annotations

import datetime as dt
import re
import time as _time
from dataclasses import dataclass

# The three keys a learner can bring. (GitHub Models is gone from this list on purpose: it answers 200 "OK" to ANY token, so it can neither validate nor serve.)
PROVIDERS = ("groq", "gemini", "openrouter")

KINDS = ("invalid", "limited", "forbidden", "needs_credit", "model_gone", "bad_request", "transient", "unknown")


@dataclass(frozen=True)
class Outcome:
    kind: str                          # one of KINDS
    http: int = 0                      # the HTTP status when there was one
    scope: str = ""                    # for `limited`: "minute" | "day" | "upstream" (the provider's shared pool is busy, not this key) | "" (the text did not say)
    retry_after: float | None = None   # seconds - what the provider itself reported (header or text)
    reset_at: float | None = None      # epoch seconds the limit should end
    evidence: bool = False             # reset_at / retry_after come from the provider's own words
    approx: bool = False               # reset_at comes from the provider's PUBLISHED daily rule (midnight UTC / Pacific), not from this response
    expired: bool = False              # kind == invalid and the provider said the key EXPIRED


# --------------------------------------------------------------------------------------------- reading what the provider said
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)(?![a-z])", re.I)
_TRY_AGAIN = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?\s*(?:ms|h|m|s)\s*)+)", re.I)
_RETRY_DELAY = re.compile(r"""retry_?delay['"]?[\s:=]+['"]?([0-9.]+s)""", re.I)


def parse_duration(text) -> float | None:
    """'2m59.56s' -> 179.56, '7.66s' -> 7.66, '1h2m3s' -> 3723, '35ms' -> 0.035, '23s' -> 23. None when there is no duration in it."""
    total, found = 0.0, False
    for num, unit in _DUR.findall(str(text or "")):
        u = unit.lower()
        v = float(num)
        total += v * {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}[u]
        found = True
    return total if found else None


def _flatten(obj, out: list, depth: int = 0) -> None:
    """Every string in a (possibly nested) body, bounded: Groq sends a dict, Gemini sends a LIST of dicts, OpenRouter nests `metadata.raw` as text or JSON."""
    if depth > 6 or len(out) > 80:
        return
    if isinstance(obj, str):
        out.append(obj[:800])
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and len(out) < 80:
                out.append(k[:80])
            _flatten(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj[:12]:
            _flatten(v, out, depth + 1)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(str(obj))


def _text(exc) -> str:
    parts: list = []
    try:
        _flatten(getattr(exc, "body", None), parts)
    except Exception:
        pass
    try:
        parts.append(str(exc)[:1200])
    except Exception:
        pass
    return " ".join(parts).lower()


def _header(headers, name: str):
    if not headers:
        return None
    try:
        v = headers.get(name)
        if v is not None:
            return v
        low = name.lower()
        for k in headers:
            if str(k).lower() == low:
                return headers[k]
    except Exception:
        return None
    return None


def _num(v):
    try:
        f = float(str(v).strip())
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------------- the provider's published daily reset
def _utc_midnight_after(now: float) -> float:
    d = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    return (d.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)).timestamp()


def _pacific_midnight_after(now: float) -> float:
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo("America/Los_Angeles")
        d = dt.datetime.fromtimestamp(now, z)
        nxt = (d.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1))
        return dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=z).timestamp()
    except Exception:
        return _utc_midnight_after(now) + 8 * 3600          # no tz database: a reasonable stand-in, only ever shown as "about"


def quota_day_end(provider: str, now: float) -> float:
    """When the provider's daily bucket starts again: Gemini = midnight Pacific; Groq and OpenRouter = midnight UTC (their published rules)."""
    return _pacific_midnight_after(now) if provider == "gemini" else _utc_midnight_after(now)


def quota_day(provider: str, now: float) -> str:
    """The provider's own quota day ('YYYY-MM-DD') - the ledger buckets by it so 'used today' lines up with 'left today'."""
    if provider == "gemini":
        try:
            from zoneinfo import ZoneInfo
            return dt.datetime.fromtimestamp(now, ZoneInfo("America/Los_Angeles")).date().isoformat()
        except Exception:
            pass
    return dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()


# --------------------------------------------------------------------------------------------- the classifier
_DAY_WORDS = ("per day", "perday", "per-day", "per_day", "daily", "(tpd)", "(rpd)", " tpd", " rpd", "free-models-per-day", "free_tier_requests_per_day")
_MIN_WORDS = ("per minute", "perminute", "per-minute", "per_minute", "(tpm)", "(rpm)", " tpm", " rpm", "per second", "per-second", "persecond")
_INVALID_WORDS = ("api key not valid", "pass a valid api key", "api_key_invalid", "api key expired", "invalid api key", "api key is invalid",
                  "invalid_api_key", "incorrect api key", "no auth credentials", "invalid authentication", "api key was reported as leaked",
                  "invalid auth key")       # Google's 400 for a wrong / cut / mistyped "AQ." key (measured 2026-11-07); an AIza key gets "API key not valid"
_RATE_TEXT = re.compile(r"(?<![\w.])429(?!\w|\.\d)|rate limit|rate_limit|resource_exhausted|too many requests|exceeded your current quota")
_KEY_DEAD_403 = ("leaked", "revoked", "disabled", "suspended", "invalid api key", "api key not valid", "api key expired")


def _scope(text: str) -> str:
    if "rate-limited upstream" in text or "temporarily rate-limited" in text:
        return "upstream"                                     # OpenRouter: the shared FREE model's pool is busy - not this key's own limit
    if any(w in text for w in _DAY_WORDS):
        return "day"                                          # the stricter one wins when a body lists both
    if any(w in text for w in _MIN_WORDS):
        return "minute"
    return ""


def _retry_after(headers, text: str, now: float):
    """(seconds, reset_at, evidence) from the provider's own words: the retry-after header, OpenRouter's X-RateLimit-Reset (ms epoch), Groq's
    'try again in 6m45.6s', Gemini's RetryInfo.retryDelay."""
    ra = _num(_header(headers, "retry-after"))
    if ra is not None and 0 <= ra < 7 * 86400:
        return ra, now + ra, True
    xr = _num(_header(headers, "x-ratelimit-reset"))
    if xr is not None:
        sec = xr / 1000.0 if xr > 1e12 else xr if xr > 1e9 else None
        if sec is not None and now < sec < now + 7 * 86400:
            return sec - now, sec, True
    m = _TRY_AGAIN.search(text) or _RETRY_DELAY.search(text)
    if m:
        d = parse_duration(m.group(1))
        if d is not None and 0 <= d < 7 * 86400:
            return d, now + d, True
    return None, None, False


def classify(provider: str, exc, now: float | None = None) -> Outcome:
    now = _time.time() if now is None else now
    try:
        return _classify(provider, exc, now)
    except Exception:                                         # a classifier must never be the thing that fails a request
        return Outcome("unknown")


def _names(exc) -> set:
    return {c.__name__ for c in type(exc).__mro__}


def _classify(provider: str, exc, now: float) -> Outcome:
    names = _names(exc)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = 0
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    text = _text(exc)

    if not status:
        if names & {"APITimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout", "TimeoutError", "CancelledError"} or "timed out" in text or "timeout" in text:
            return Outcome("transient")
        if names & {"APIConnectionError", "ConnectError", "ConnectionError", "TransportError", "NetworkError", "RemoteProtocolError", "OSError"}:
            return Outcome("transient")
        # No HTTP status at all (an error that was re-raised as text): the only thing the old walker acted on was a rate limit, and so do we.
        if _RATE_TEXT.search(text):
            sec, reset_at, evidence = _retry_after(None, text, now)
            return Outcome("limited", http=429, scope=_scope(text), retry_after=sec, reset_at=reset_at, evidence=evidence)
        return Outcome("unknown")

    if status == 401:
        return Outcome("invalid", http=401, expired="expired" in text)
    if status == 429:
        sec, reset_at, evidence = _retry_after(headers, text, now)
        scope = _scope(text)
        approx = False
        if reset_at is None and scope == "day":
            reset_at, approx = quota_day_end(provider, now), True
        return Outcome("limited", http=429, scope=scope, retry_after=sec, reset_at=reset_at, evidence=evidence, approx=approx)
    if status == 400:
        if any(w in text for w in _INVALID_WORDS):
            return Outcome("invalid", http=400, expired="expired" in text)
        return Outcome("bad_request", http=400)
    if status == 403:
        if any(w in text for w in _KEY_DEAD_403):
            return Outcome("invalid", http=403, expired="expired" in text)
        return Outcome("forbidden", http=403)
    if status == 402:
        return Outcome("needs_credit", http=402)
    if status in (404, 410):
        return Outcome("model_gone", http=status)
    if status == 408 or status >= 500:
        return Outcome("transient", http=status)
    if 400 <= status < 500:
        return Outcome("bad_request", http=status)
    return Outcome("unknown", http=status)


UPSTREAM_BUSY_S = 20.0      # OpenRouter's shared FREE pool says "busy, retry shortly": that passes in seconds, so it is skipped for seconds - not the 90 s of a per-minute limit


def limit_seconds(out: Outcome, fallback: float = 90.0) -> float:
    """How long to skip a limited key: the provider's own retry-after (+1 s, clamped), else 30 min for a daily limit, 90 s for a per-minute limit, 20 s for a busy
    shared pool, else `fallback` (the walker passes the legacy text-based class)."""
    if out.evidence and out.retry_after is not None:
        return min(21600.0, max(5.0, out.retry_after + 1.0))
    if out.scope == "day":
        return 1800.0
    if out.scope == "upstream":
        return UPSTREAM_BUSY_S
    if out.scope == "minute":
        return 90.0
    return float(fallback)


# --------------------------------------------------------------------------------------------- what a SUCCESSFUL call tells us (Groq reports its daily request allowance)
def parse_ratelimit(provider: str, headers, now: float) -> dict | None:
    """{limit, remaining, reset_at} from the response headers, or None. Only Groq documents these as the DAILY request allowance; for anyone else the
    headers (if any) are not trusted."""
    if provider != "groq":
        return None
    lim = _num(_header(headers, "x-ratelimit-limit-requests"))
    rem = _num(_header(headers, "x-ratelimit-remaining-requests"))
    if lim is None or rem is None or lim <= 0 or rem < 0 or rem > lim:
        return None
    reset = parse_duration(_header(headers, "x-ratelimit-reset-requests"))
    return {"limit": int(lim), "remaining": int(rem), "reset_at": (now + reset) if reset is not None else None}
