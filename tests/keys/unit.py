"""Keys - tier 1: the pure logic and the walker, with NO database and NO network.

  A  the classifier        real openai-SDK error objects built from synthetic provider bodies (Groq dict, Gemini LIST, OpenRouter nested): only positive evidence marks a key invalid
  B  fingerprints, masks   stable, not reversible, never more than the provider's prefix + the last four characters
  C  the gate              per key (never per provider name), ONE half-open probe among many concurrent callers, one early probe a minute, invalid for 6 h
  D  the per-key walker    attempt order, what is skipped, what is remembered, timeouts leave a provider, a dead key is not retried, the ledger counts every attempt
                           (including a cancelled one), fail-fast with nothing sent, the structured error
  E  main.py helpers       kp from a wrapped error, quota_msg, key_error, the WhatsApp link validator
  F  hygiene               every set_active_keys call passes uid= and engine= (AST), column widths, no key text anywhere in what a learner can see

Run:  tests/keys/run.sh unit.py
"""

import ast
import asyncio
import os
import re
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import httpx                                              # noqa: E402
import openai                                             # noqa: E402

from world import (World, install, ok, err, timeout, conn, completion, R,                      # noqa: E402
                   GROQ_401, GROQ_429_TPD, GROQ_429_TPM, GROQ_429_PLAIN, GEMINI_400_KEY, GEMINI_400_AUTH_KEY, GEMINI_400_EXPIRED, GEMINI_400_OTHER,
                   GEMINI_403_LEAKED, GEMINI_429_DAY, GEMINI_429_MIN, GEMINI_429_BARE, GEMINI_503, OPENROUTER_401, OPENROUTER_402,
                   OPENROUTER_404, OPENROUTER_429_DAY, OPENROUTER_429_UPSTREAM)

FAILS, N = [], 0


def check(name, cond, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {'' if cond else str(detail)[:300]}")
    if not cond:
        FAILS.append(name)


def section(t):
    print(f"\n== {t}")


from app.keys import classify, gate, ledger                # noqa: E402
from app.keys.errors import ProviderChainError, chain_state  # noqa: E402
from app.providers import openrouter_provider as op        # noqa: E402


def sdk_err(status, body, headers=None):
    req = httpx.Request("POST", "https://x.test/v1/chat/completions")
    resp = httpx.Response(status, json=body, headers=headers or {}, request=req)
    msg = f"Error code: {status} - {body}"
    cls = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError, 404: openai.NotFoundError,
           422: openai.UnprocessableEntityError, 429: openai.RateLimitError}.get(status)
    if cls is None:
        cls = openai.InternalServerError if status >= 500 else openai.APIStatusError
    return cls(msg, response=resp, body=body)


NOW = 1_800_000_000.0                      # a fixed instant for the pure tests

# ============================================================================================ A. the classifier
section("A. classifier - what each provider said")
o = classify.classify("groq", sdk_err(429, GROQ_429_TPD), NOW)
check("Groq 429 on tokens PER DAY: limited, day scope, the provider's own 'try again in 6m45.6s' = 405.6 s, evidence", o.kind == "limited" and o.scope == "day" and abs(o.retry_after - 405.6) < 0.01 and o.evidence and abs(o.reset_at - (NOW + 405.6)) < 0.01, o)
o = classify.classify("groq", sdk_err(429, GROQ_429_TPM), NOW)
check("Groq 429 on tokens PER MINUTE: minute scope, 3.2 s", o.kind == "limited" and o.scope == "minute" and abs(o.retry_after - 3.2) < 0.01, o)
o = classify.classify("groq", sdk_err(429, GROQ_429_PLAIN), NOW)
check("Groq 429 with no scope and no wait: limited, nothing invented (no scope, no reset)", o.kind == "limited" and o.scope == "" and o.retry_after is None and o.reset_at is None and not o.evidence, o)
o = classify.classify("groq", sdk_err(429, GROQ_429_PLAIN, {"retry-after": "12"}), NOW)
check("retry-after header: 12 s with evidence", o.retry_after == 12 and o.evidence and o.reset_at == NOW + 12, o)
o = classify.classify("groq", sdk_err(401, GROQ_401), NOW)
check("Groq 401: invalid", o.kind == "invalid" and o.http == 401 and not o.expired, o)
o = classify.classify("gemini", sdk_err(400, GEMINI_400_KEY), NOW)
check("Gemini 400 'API key not valid' (a LIST body): invalid - the case that used to match nothing", o.kind == "invalid" and o.http == 400, o)
o = classify.classify("gemini", sdk_err(400, GEMINI_400_AUTH_KEY), NOW)
check("Gemini 400 'Invalid Auth key.' (Google's answer to a wrong AQ. key, measured 2026-11-07): invalid, not expired - it used to read as bad_request -> 'couldn't reach'", o.kind == "invalid" and o.http == 400 and not o.expired, o)
o = classify.classify("gemini", sdk_err(400, GEMINI_400_EXPIRED), NOW)
check("Gemini 400 'API key expired': invalid AND expired", o.kind == "invalid" and o.expired, o)
o = classify.classify("gemini", sdk_err(400, GEMINI_400_OTHER), NOW)
check("Gemini 400 about something else: bad_request - NEVER evidence about the key", o.kind == "bad_request", o)
o = classify.classify("gemini", sdk_err(403, GEMINI_403_LEAKED), NOW)
check("Gemini 403 'reported as leaked': invalid", o.kind == "invalid", o)
o = classify.classify("gemini", sdk_err(403, {"error": {"message": "Access denied. Please check your network settings."}}), NOW)
check("a 403 that says nothing about the key is only 'forbidden' (not invalid)", o.kind == "forbidden", o)
o = classify.classify("gemini", sdk_err(429, GEMINI_429_DAY), NOW)
check("Gemini 429 PerDay quotaId (LIST body): limited, day scope; the reset is the PUBLISHED daily rule (approx, no evidence)", o.kind == "limited" and o.scope == "day" and o.approx and not o.evidence and o.reset_at > NOW, o)
o = classify.classify("gemini", sdk_err(429, GEMINI_429_MIN), NOW)
check("Gemini 429 PerMinute + RetryInfo 23s: minute scope, 23 s, evidence", o.kind == "limited" and o.scope == "minute" and abs(o.retry_after - 23) < 0.01 and o.evidence, o)
o = classify.classify("gemini", sdk_err(429, GEMINI_429_BARE), NOW)
check("Gemini 429 with no details: limited, no scope, no reset", o.kind == "limited" and o.scope == "" and o.reset_at is None, o)
o = classify.classify("gemini", sdk_err(503, GEMINI_503), NOW)
check("Gemini 503 overloaded: transient (never the key's fault)", o.kind == "transient" and o.http == 503, o)
o = classify.classify("openrouter", sdk_err(401, OPENROUTER_401), NOW)
check("OpenRouter 401: invalid", o.kind == "invalid", o)
o = classify.classify("openrouter", sdk_err(429, OPENROUTER_429_DAY), NOW)
check("OpenRouter 429 free-models-per-day: limited, day scope", o.kind == "limited" and o.scope == "day", o)
reset_ms = int((NOW + 5000) * 1000)
o = classify.classify("openrouter", sdk_err(429, OPENROUTER_429_DAY, {"x-ratelimit-reset": str(reset_ms)}), NOW)
check("OpenRouter X-RateLimit-Reset (ms epoch) becomes a 5000 s wait with evidence", abs(o.retry_after - 5000) < 1 and o.evidence, o)
o = classify.classify("openrouter", sdk_err(429, OPENROUTER_429_UPSTREAM), NOW)
check("OpenRouter 'temporarily rate-limited upstream': scope 'upstream' (the shared free pool, not this key's limit)", o.kind == "limited" and o.scope == "upstream", o)
check("402 -> needs_credit", classify.classify("openrouter", sdk_err(402, OPENROUTER_402), NOW).kind == "needs_credit")
check("404 (a retired model) -> model_gone, not invalid", classify.classify("openrouter", sdk_err(404, OPENROUTER_404), NOW).kind == "model_gone")
check("413 / 422 -> bad_request", classify.classify("groq", sdk_err(413, {"error": {"message": "Request too large"}}), NOW).kind == "bad_request"
      and classify.classify("groq", sdk_err(422, {"error": {"message": "bad"}}), NOW).kind == "bad_request")
check("500 / 502 / 504 -> transient", all(classify.classify("groq", sdk_err(c, {"error": {"message": "x"}}), NOW).kind == "transient" for c in (500, 502, 504)))
req = httpx.Request("POST", "https://x.test")
check("an SDK timeout -> transient with no HTTP status", classify.classify("groq", openai.APITimeoutError(request=req), NOW) == classify.Outcome("transient"))
check("an SDK connection error -> transient", classify.classify("groq", openai.APIConnectionError(request=req), NOW).kind == "transient")
check("httpx.ReadTimeout -> transient", classify.classify("groq", httpx.ReadTimeout("timed out"), NOW).kind == "transient")
check("a status-less error whose TEXT is a rate limit (the old walker acted on it) -> limited", classify.classify("groq", RuntimeError("429 rate limit hit"), NOW).kind == "limited")
check("... but 'generate' is not a rate limit (the old substring test said it was)", classify.classify("groq", RuntimeError("could not generate a reply"), NOW).kind == "unknown")
check("a digit run inside a number is not 429 ('Used 14290')", classify.classify("groq", RuntimeError("Used 14290 tokens"), NOW).kind == "unknown")
check("text we cannot read is 'unknown', never invalid", classify.classify("groq", RuntimeError("something odd 401-ish"), NOW).kind == "unknown")
check("the classifier never raises (None, an object, a bad body)", all(classify.classify("groq", x, NOW).kind == "unknown" for x in (None, object(), 12)))
bad = sdk_err(429, GROQ_429_PLAIN)
bad.body = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "x" * 5000}}}}}}}
check("a deeply nested / huge body does not break it", classify.classify("groq", bad, NOW).kind == "limited")
check("limit_seconds: provider evidence wins (+1 s), day = 30 min, minute = 90 s, a busy shared pool (upstream) = 20 s, unknown = the fallback",
      classify.limit_seconds(classify.Outcome("limited", retry_after=10, evidence=True)) == 11 and classify.limit_seconds(classify.Outcome("limited", scope="day")) == 1800
      and classify.limit_seconds(classify.Outcome("limited", scope="minute")) == 90 and classify.limit_seconds(classify.Outcome("limited", scope="upstream")) == 20
      and classify.limit_seconds(classify.Outcome("limited"), 77) == 77 and classify.limit_seconds(classify.Outcome("limited", retry_after=99999999, evidence=True)) == 21600
      and classify.limit_seconds(classify.Outcome("limited", retry_after=0, evidence=True)) == 5)
check("parse_duration", classify.parse_duration("2m59.56s") == 179.56 and abs(classify.parse_duration("1h2m3s") - 3723) < 1e-9 and classify.parse_duration("35ms") == 0.035
      and classify.parse_duration("23s") == 23 and classify.parse_duration("nothing") is None and classify.parse_duration(None) is None)
hdr = {"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14380", "x-ratelimit-reset-requests": "2m59.56s"}
rl = classify.parse_ratelimit("groq", hdr, NOW)
check("Groq allowance headers -> {limit, remaining, reset_at}", rl == {"limit": 14400, "remaining": 14380, "reset_at": NOW + 179.56}, rl)
check("allowance headers are trusted for Groq only", classify.parse_ratelimit("openrouter", hdr, NOW) is None and classify.parse_ratelimit("gemini", hdr, NOW) is None)
check("nonsense allowance headers are ignored", classify.parse_ratelimit("groq", {"x-ratelimit-limit-requests": "10", "x-ratelimit-remaining-requests": "99"}, NOW) is None
      and classify.parse_ratelimit("groq", {}, NOW) is None and classify.parse_ratelimit("groq", None, NOW) is None)

import datetime as dt                                      # noqa: E402
jul = dt.datetime(2026, 7, 15, 5, 0, tzinfo=dt.timezone.utc).timestamp()          # 22:00 on 14 July in Pacific (PDT, UTC-7)
jan = dt.datetime(2026, 1, 15, 5, 0, tzinfo=dt.timezone.utc).timestamp()          # 21:00 on 14 January in Pacific (PST, UTC-8)
check("the Gemini quota day is the PACIFIC day (summer and winter)", classify.quota_day("gemini", jul) == "2026-07-14" and classify.quota_day("gemini", jan) == "2026-01-14"
      and classify.quota_day("groq", jul) == "2026-07-15" and classify.quota_day("openrouter", jan) == "2026-01-15")
check("Gemini's daily reset is the next Pacific midnight: 07:00 UTC in summer, 08:00 UTC in winter",
      classify.quota_day_end("gemini", jul) == dt.datetime(2026, 7, 15, 7, 0, tzinfo=dt.timezone.utc).timestamp()
      and classify.quota_day_end("gemini", jan) == dt.datetime(2026, 1, 15, 8, 0, tzinfo=dt.timezone.utc).timestamp())
check("Groq / OpenRouter reset at the next UTC midnight", classify.quota_day_end("groq", jul) == dt.datetime(2026, 7, 16, 0, 0, tzinfo=dt.timezone.utc).timestamp())

# ============================================================================================ B. fingerprints, masks, shapes
section("B. fingerprint, mask, key shape")
K1, K2, K3 = "gsk_" + "a" * 40 + "9fA2", "AIza" + "b" * 35 + "zZ91", "sk-or-v1-" + "c" * 50 + "Q7xP"
f1 = gate.fingerprint("groq", K1)
check("fingerprint: 12 hex, stable, differs by key AND by provider, and does not contain the key", len(f1) == 12 and re.fullmatch(r"[0-9a-f]{12}", f1) and f1 == gate.fingerprint("groq", K1)
      and f1 != gate.fingerprint("groq", K1 + "x") and f1 != gate.fingerprint("gemini", K1) and K1[4:12] not in f1)
check("mask: provider prefix + dots + last four, nothing else", gate.mask(K1) == "gsk_••••9fA2" and gate.mask(K2) == "AIza••••zZ91" and gate.mask(K3) == "sk-or-v1-••••Q7xP", [gate.mask(K1), gate.mask(K2), gate.mask(K3)])
check("mask never leaks the middle of a key", all(k[8:-6] not in gate.mask(k) for k in (K1, K2, K3)))
check("mask of a short / empty value", gate.mask("") == "••••" and gate.mask("abc") == "••••" and "abcdefg" not in gate.mask("abcdefg"))
check("clean_key accepts a normal key and strips the ends", gate.clean_key("groq", "  " + K1 + "\n") == K1)
check("clean_key refuses: empty, too short, spaces inside, control characters, absurd length, not a string",
      all(gate.clean_key("groq", v) is None for v in ("", "short", "gsk_ has space inside_xx", "gsk_abcdefgh\x00ij", "k" * 401, None, 12, ["x"])))

# ============================================================================================ C. the gate
section("C. the per-key gate")
gate.reset_all()
P, F = "groq", "fp-aaaaaaaa"
check("a key nobody has seen is 'go'", gate.verdict(P, F, NOW) == "go" and gate.peek(P, F, NOW) == "go")
gate.mark_limited(P, F, NOW, 90, scope="minute", http=429)
check("limited: skipped until it ends", gate.verdict(P, F, NOW + 10) == "skip" and gate.peek(P, F, NOW + 89) == "skip")
check("... and keyed by the KEY: another key, and the same key on another provider, are untouched", gate.verdict(P, "fp-bbbbbbbb", NOW + 10) == "go" and gate.verdict("gemini", F, NOW + 10) == "go")
check("peek changes nothing (no probe slot is taken)", gate.peek(P, F, NOW + 91) == "probe" and gate.peek(P, F, NOW + 91) == "probe" and not gate.get(P, F).inflight)
got = [gate.verdict(P, F, NOW + 91) for _ in range(20)]
check("the gate expired: among 20 concurrent callers EXACTLY ONE gets the half-open probe", got.count("probe") == 1 and got.count("skip") == 19, got)
gate.release(P, F)
check("release() gives the slot back (the probe ended without a verdict)", gate.verdict(P, F, NOW + 92) == "probe")
check("a probe that never reported back goes stale after 90 s - the key is never gated forever", gate.verdict(P, F, NOW + 92 + 100) == "probe")
gate.mark_ok(P, F, NOW + 200)
check("a success clears the gate", gate.get(P, F) is None and gate.verdict(P, F, NOW + 201) == "go")
check("mark_ok on a key that was fine changes nothing and says so", gate.mark_ok(P, F, NOW) is False)
gate.mark_limited(P, F, NOW, 90, http=429)
check("mark_ok after a limit reports that it CHANGED something", gate.mark_ok(P, F, NOW) is True)
gate.mark_invalid(P, F, NOW, http=401)
check("invalid: skipped for 6 hours (it cannot recover on its own), then ONE probe", gate.verdict(P, F, NOW + 21599) == "skip" and gate.verdict(P, F, NOW + 21601) == "probe")
gate.clear(P, F)
check("clear() forgets it (the learner just re-added the key)", gate.get(P, F) is None)
gate.mark_forbidden(P, F, NOW)
check("forbidden: a short skip (5 min)", gate.verdict(P, F, NOW + 299) == "skip" and gate.verdict(P, F, NOW + 301) == "probe")
gate.reset_all()
gate.mark_limited("groq", "g1", NOW, 1800, http=429)
gate.mark_limited("gemini", "m1", NOW, 90, http=429)
gate.mark_invalid("openrouter", "o1", NOW)
cands = [("groq", "g1"), ("gemini", "m1"), ("openrouter", "o1")]
check("early probe: nothing before the probe gap", gate.soonest_probe(cands, NOW + 10) is None)
sp = gate.soonest_probe(cands, NOW + 61)
check("early probe: the LIMITED key that ends soonest (never the invalid one)", sp == ("gemini", "m1"), sp)
check("... and only ONE probe in flight per chain: while it runs nobody starts another", gate.soonest_probe(cands, NOW + 62) is None)
gate.release("gemini", "m1")
check("... when it ends, the next eligible key (its own minute is up) may take one - and again only one at a time",
      gate.soonest_probe(cands, NOW + 63) == ("groq", "g1") and gate.soonest_probe(cands, NOW + 64) is None)
gate.reset_all()
chain = [{"name": "groq", "key": K1}, {"name": "gemini", "key": K2}]
gate.mark_limited("gemini", gate.fingerprint("gemini", K2), time.time(), 90)
check("chain_limited: true when one of THIS chain's keys is limited", gate.chain_limited(chain, time.time()))
gate.reset_all()
gate.mark_invalid("gemini", gate.fingerprint("gemini", K2), time.time())
check("... an invalid key is not 'busy'", not gate.chain_limited(chain, time.time()))
gate.reset_all()
for i in range(gate.MAX_ENTRIES + 50):
    gate.mark_limited("groq", f"x{i}", NOW, 1)
check("the gate map is bounded", len(gate._state) <= gate.MAX_ENTRIES + 1, len(gate._state))
gate.reset_all()

# ============================================================================================ chain_state / ProviderChainError
section("C2. the headline state and the structured error")
check("chain_state: empty -> no_keys", chain_state([]) == "no_keys")
check("... all rejected -> all_invalid", chain_state([{"kind": "invalid"}, {"kind": "invalid"}]) == "all_invalid")
check("... limited / blocked / out of credit / rejected mix -> all_limited", chain_state([{"kind": "limited"}, {"kind": "invalid"}]) == "all_limited"
      and chain_state([{"kind": "forbidden"}]) == "all_limited" and chain_state([{"kind": "needs_credit"}, {"kind": "limited"}]) == "all_limited")
check("... any non-key failure -> transient (provider trouble, not the keys)", chain_state([{"kind": "limited"}, {"kind": "transient"}]) == "transient"
      and chain_state([{"kind": "invalid"}, {"kind": "transient"}]) == "transient")
check("... a limit on the shared free pool is transient, not 'your keys'", chain_state([{"kind": "limited", "scope": "upstream"}]) == "transient")
e = ProviderChainError("Error code: 429 - rate limit", "all_limited", [{"provider": "groq", "kind": "limited", "scope": "day", "reset_at": NOW + 5, "approx": True}, {"provider": "gemini", "kind": "invalid", "expired": True}])
check("ProviderChainError IS a RuntimeError with the legacy message text (every old string check keeps working)", isinstance(e, RuntimeError) and str(e) == "all providers/models unavailable: Error code: 429 - rate limit")
kp = e.kp(NOW)
check("kp: state + own + per-key {provider, kind, scope, reset_at, approx, expired} + now, nothing else (no retry_in for a state the learner must act on)", kp == {"state": "all_limited", "own": True, "now": int(NOW), "keys": [
    {"provider": "groq", "kind": "limited", "scope": "day", "reset_at": int(NOW + 5), "approx": True}, {"provider": "gemini", "kind": "invalid", "expired": True}]}, kp)
check("kp carries no provider error text and no key", "rate limit" not in str(kp) and "gsk_" not in str(kp))

# ============================================================================================ D. the walker
section("D. the per-key walker, against a scripted provider world")
world = World()
install(world)
LA = {"groq": K1, "gemini": K2, "openrouter": K3}                     # learner A's keys
LB = {"groq": "gsk_" + "z" * 40 + "BBBB", "gemini": "AIza" + "y" * 35 + "BBBB"}      # learner B's keys (different keys, same providers)
MSG = [{"role": "user", "content": "hi"}]


def fresh(keys, uid="uA", engine=True, w=None):
    gate.reset_all(); ledger.reset_all(); op._cooldown.clear(); op._clients.clear()
    global world
    world = w or World()
    install(world)
    op.set_active_keys(keys, uid=uid, engine=engine)


def age_limit(provider, key):
    """Pretend a limit has run its course: the key's gate and every model remembered for that key expire together (as they do in production)."""
    fp = gate.fingerprint(provider, key)
    st = gate.get(provider, fp)
    if st is not None:
        st.until = time.time() - 1
    for (p, f, _m), ms in list(gate._models.items()):
        if p == provider and f == fp:
            ms.until = time.time() - 1


def usage_of(uid, provider=None):
    out = {"requests": 0, "ok": 0, "limited": 0, "invalid": 0, "other": 0, "tokens_in": 0, "tokens_out": 0}
    for (u, _day, p, _fp), d in ledger._usage.items():
        if u == uid and (provider is None or p == provider):
            for k in out:
                out[k] += d[k]
    return out


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def t_success():
    fresh(LA)
    text = await op._complete(MSG, 50)
    check("a plain success returns the model's text through the per-key walker", text == "OK")
    check("the chain order is groq -> gemini -> openrouter and only the first was asked", [c[0] for c in world.calls_for()] == ["groq"], world.calls)
    u = usage_of("uA")
    check("the ledger counted exactly one request, ok, with tokens", u["requests"] == 1 and u["ok"] == 1 and u["tokens_in"] == 5 and u["tokens_out"] == 3, u)
    check("a success on a fine key leaves no gate entry", gate.get("groq", gate.fingerprint("groq", K1)) is None)


async def t_limit_falls_through():
    w = World().on("groq", K1, err(429, GROQ_429_TPD))
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    g = gate.get("groq", gate.fingerprint("groq", K1))
    check("Groq limited on BOTH its models (Groq limits per model: the second one is asked too) -> Gemini answered", text == "OK" and [c[0] for c in world.calls_for()] == ["groq", "groq", "gemini"], world.calls)
    check("the limited key is gated for the PROVIDER'S OWN wait (405.6 s + 1), not a guess", g is not None and g.status == "limited" and abs((g.until - time.time()) - 406.6) < 3, g)
    n = len(world.calls_for())
    await op._complete(MSG, 50)
    check("the NEXT call does not touch the limited key at all", [c[0] for c in world.calls_for()][n:] == ["gemini"], world.calls)
    check("a provider whose every model is limited is skipped whole afterwards (two requests in total, one per model - never again)", len([c for c in world.calls_for("groq")]) == 2)
    u = usage_of("uA", "groq")
    check("the ledger saw both limited attempts", u["requests"] == 2 and u["limited"] == 2, u)


async def t_dead_keys():
    w = World().on("groq", K1, err(401, GROQ_401))
    fresh(LA, w=w)
    await op._complete(MSG, 50)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    await op._complete(MSG, 50)
    check("a REJECTED key (Groq 401) is asked once, then never again - it used to be retried on every call", n == 1 and len(world.calls_for("groq")) == 1, world.calls)
    check("the status row will say invalid", ledger._status[("uA", "groq", gate.fingerprint("groq", K1))]["status"] == "invalid")
    w = World().on("gemini", K2, err(400, GEMINI_400_KEY)).on("groq", K1, err(429, GROQ_429_PLAIN))
    fresh(LA, w=w)
    await op._complete(MSG, 50)
    await op._complete(MSG, 50)
    check("a Gemini 400 'API key not valid' is remembered too (the old walker never matched it)", len(world.calls_for("gemini")) == 1, world.calls)


async def t_all_down():
    w = World().on("groq", K1, err(429, GROQ_429_TPD)).on("gemini", K2, err(429, GEMINI_429_DAY)).on("openrouter", K3, err(429, OPENROUTER_429_DAY))
    fresh(LA, w=w)
    try:
        await op._complete(MSG, 50)
        check("every key limited raises", False)
    except ProviderChainError as e:
        check("every key limited: ProviderChainError, state all_limited, one record per key with the exact kind", e.state == "all_limited" and [k["provider"] for k in e.keys] == ["groq", "gemini", "openrouter"]
              and all(k["kind"] == "limited" for k in e.keys), (e.state, e.keys))
        check("... the message still reads like a quota error to every old string check", "429" in str(e) and str(e).startswith("all providers/models unavailable:"))
        kp = e.kp()
        check("... kp carries a reset time for the keys whose provider said one (Groq's own wait; Gemini's / OpenRouter's published daily rule marked approx)",
              kp["keys"][0].get("reset_at") and not kp["keys"][0].get("approx") and kp["keys"][1].get("approx") and kp["keys"][2].get("approx"), kp)
    n = len(world.calls)
    t0 = time.time()
    try:
        await op._complete(MSG, 50)
    except ProviderChainError as e:
        check("the NEXT call fails AT ONCE: nothing was sent, same structured error", len(world.calls) == n and e.state == "all_limited" and time.time() - t0 < 0.5, (len(world.calls) - n, e.state))
        check("... and its message is still a quota message for the old checks", "429" in str(e))
    w = World().on("groq", K1, err(401, GROQ_401)).on("gemini", K2, err(400, GEMINI_400_KEY)).on("openrouter", K3, err(401, OPENROUTER_401))
    fresh(LA, w=w)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError as e:
        check("every key rejected: all_invalid, and the message is NOT a quota message", e.state == "all_invalid" and "429" not in str(e), (e.state, str(e)[:80]))
    n = len(world.calls)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError as e:
        check("... fails at once the second time too, with nothing sent", len(world.calls) == n and e.state == "all_invalid" and "429" not in str(e) and "quota" not in str(e).lower())
    w = World().on("groq", K1, err(401, GROQ_401)).on("gemini", K2, err(503, GEMINI_503)).on("openrouter", K3, err(401, OPENROUTER_401))
    fresh(LA, w=w)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError as e:
        check("two rejected + one provider outage: transient (it is NOT all the keys' fault)", e.state == "transient", e.state)
    fresh({})
    try:
        await op._complete(MSG, 50)
        check("an empty chain raises", False)
    except ProviderChainError as e:
        check("an empty chain (no keys at all): state no_keys, no records, nothing sent", e.state == "no_keys" and e.keys == [] and not world.calls, (e.state, e.keys))


async def t_leave_and_next():
    w = World().on("groq", K1, timeout())
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    check("a TIMEOUT leaves the provider: its second model is not tried (another 20 s)", text == "OK" and [c[3] for c in world.calls_for("groq")] == ["openai/gpt-oss-120b"], world.calls)
    check("... a timeout gates nothing (it says nothing about the key)", gate.get("groq", gate.fingerprint("groq", K1)) is None)
    w = World().on("groq", K1, conn())
    fresh(LA, w=w)
    await op._complete(MSG, 50)
    check("a connection error leaves the provider too", len(world.calls_for("groq")) == 1)
    w = World().on("groq", K1, err(500, {"error": {"message": "boom"}}), ok())
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    check("a 5xx tries the provider's NEXT MODEL (as before)", text == "OK" and [c[3] for c in world.calls_for("groq")] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], world.calls)
    w = World().on("groq", K1, err(404, OPENROUTER_404), ok())
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    check("a retired model (404) tries the next model and does NOT gate the key", text == "OK" and gate.get("groq", gate.fingerprint("groq", K1)) is None and len(world.calls_for("groq")) == 2)
    w = World().on("groq", K1, err(400, GEMINI_400_OTHER), ok())
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    check("a bad request (400, not about the key) tries the next model and gates nothing", text == "OK" and gate.get("groq", gate.fingerprint("groq", K1)) is None)
    w = World().on("groq", K1, R(200, completion("")), ok())
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    u = usage_of("uA", "groq")
    check("an EMPTY answer costs a request, is counted as 'other', and the next model is tried", text == "OK" and u["requests"] == 2 and u["other"] == 1 and u["ok"] == 1, u)
    w = World().on("groq", K1, ok("A long reply that was cut off mid-sent", finish="length"))
    fresh(LA, w=w)
    text = await op._complete(MSG, 50)
    check("a 'length' finish is trimmed back to the last whole sentence (same as before)", text == "A long reply that was cut off mid-sent" or text.endswith("."), text)
    w = World().on("groq", K1, ok("First sentence. Second one is cut off mid", finish="length"))
    fresh(LA, w=w)
    check("... trimmed", await op._complete(MSG, 50) == "First sentence.")
    w = World().on("groq", K1, ok("<think>hidden</think>Hello tu"))
    fresh(LA, w=w)
    check("reasoning is stripped and the respectful-Hindi guard still runs ('tu' -> 'tum')", await op._complete(MSG, 50) == "Hello tum")


async def t_isolation():
    w = World().on("groq", K1, err(429, GROQ_429_TPD))
    fresh(LA, uid="uA", w=w)
    await op._complete(MSG, 50)
    op.set_active_keys(LB, uid="uB", engine=True)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    check("learner A's limited Groq key does NOT make learner B's Groq key look limited (the old cooldown was per provider NAME)", len(world.calls_for("groq")) == n + 1 and world.calls_for("groq")[-1][1] == LB["groq"], world.calls)
    check("... and the ledger kept the two learners apart", usage_of("uA", "groq")["limited"] == 2 and usage_of("uB", "groq")["ok"] == 1 and usage_of("uB", "groq")["limited"] == 0)
    op.set_active_keys({"groq": K1}, uid="uC", engine=True)
    n = len(world.calls_for("groq"))
    try:
        await op._complete(MSG, 50)
    except ProviderChainError:
        pass
    check("two learners who pasted the SAME key share its gate (it is one key, one limit)", len(world.calls_for("groq")) == n)


async def t_server_chain():
    from app.config import settings
    settings.groq_api_key, settings.gemini_api_key = "gsk_SERVER" + "q" * 30, "AIzaSERVER" + "q" * 30
    w = World().on("groq", settings.groq_api_key, err(429, GROQ_429_PLAIN))
    fresh(None, uid="owner", w=w)
    text = await op._complete(MSG, 50)
    check("the server chain works through the same walker (Groq's two models, then Gemini)", text == "OK" and [c[0] for c in world.calls_for()] == ["groq", "groq", "gemini"], world.calls)
    check("a limit on a SERVER key keeps today's process-wide cooldown map up to date (/health.cooling)", "groq" in op.cooling_down())
    check("... and the cooldown length is the legacy class for that text (90 s)", abs(op._cooldown["groq"] - time.time() - 90) < 3)
    fresh(None, uid="owner", w=World().on("groq", settings.groq_api_key, err(429, GROQ_429_PLAIN)))
    await op._complete(MSG, 50, cool=False)
    check("cool=False (Grammar Coach) on the server chain neither gates the key nor cools the provider - it must never cost everyone's chat",
          gate.get("groq", gate.fingerprint("groq", settings.groq_api_key)) is None and "groq" not in op.cooling_down())
    fresh(LA, uid="uA", w=World().on("groq", K1, err(429, GROQ_429_PLAIN)))
    await op._complete(MSG, 50, cool=False)
    check("cool=False on a LEARNER'S OWN key still records the limit (a limited key is limited whoever hit it)", gate.get("groq", gate.fingerprint("groq", K1)) is not None)
    check("... but never touches the process-wide cooldown map", "groq" not in op.cooling_down())
    fresh(None, uid="owner", w=World().on("groq", settings.groq_api_key, err(401, GROQ_401)))
    await op._complete(MSG, 50)
    await op._complete(MSG, 50)
    check("a REJECTED server key is asked once and skipped (the dead Groq key cost two requests on every call)", len(world.calls_for("groq")) == 1, world.calls)
    settings.groq_api_key = settings.gemini_api_key = ""


async def t_single_flight():
    w = World().on("groq", K1, err(429, GROQ_429_PLAIN))
    fresh(LA, w=w)
    await op._complete(MSG, 50)
    age_limit("groq", K1)                                             # the limit has run its course (for the key AND for each of its models: they expire together)
    w.on("groq", K1, R(200, completion("OK"), delay=0.15))              # a real answer takes time: the callers interleave exactly as they do in production
    n = len(world.calls_for("groq"))
    res = await asyncio.gather(*[op._complete(MSG, 50) for _ in range(12)])
    check("12 concurrent callers after a limit ended: EXACTLY ONE request goes to the limited key", len(world.calls_for("groq")) == n + 1, len(world.calls_for("groq")) - n)
    check("... the other 11 were served by the next provider, and the key is healthy again", len(res) == 12 and all(r == "OK" for r in res) and gate.get("groq", gate.fingerprint("groq", K1)) is None)


async def t_early_probe():
    w = World().on("groq", K1, err(429, GROQ_429_PLAIN)).on("gemini", K2, err(429, GEMINI_429_BARE))
    fresh({"groq": K1, "gemini": K2}, w=w)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError:
        pass
    n = len(world.calls_for())
    try:
        await op._complete(MSG, 50)
    except ProviderChainError:
        pass
    check("both limited: the second call sends nothing (no early probe inside the first minute)", len(world.calls_for()) == n)
    for k in ("groq", "gemini"):
        st = gate.get(k, gate.fingerprint(k, {"groq": K1, "gemini": K2}[k]))
        st.probe_at = time.time() - 1
    w.on("groq", K1, R(200, completion("OK"), delay=0.15))
    res = await asyncio.gather(*[op._complete(MSG, 50) for _ in range(5)], return_exceptions=True)
    sent = len(world.calls_for()) - n
    check("after a minute ONE early probe goes out (a limit that ended early is noticed)", sent == 1, sent)
    check("... it succeeded, the key is healthy, and at most that one caller was served by it", sum(1 for r in res if r == "OK") >= 1 and gate.get("groq", gate.fingerprint("groq", K1)) is None, res)


async def t_cancel():
    w = World().on("groq", K1, R(200, completion("late"), delay=5.0))
    fresh(LA, w=w)
    task = asyncio.ensure_future(op._complete(MSG, 50))
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    u = usage_of("uA", "groq")
    check("a CANCELLED attempt is still counted (the provider received it): 1 request, settled as 'other'", u["requests"] == 1 and u["other"] == 1, u)
    gate.mark_limited("groq", gate.fingerprint("groq", K1), time.time() - 200, 90)
    st = gate.get("groq", gate.fingerprint("groq", K1))
    task = asyncio.ensure_future(op._complete(MSG, 50))
    await asyncio.sleep(0.15)
    check("a half-open probe holds the slot while it is in flight", st.inflight)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    check("... and a cancelled probe gives the slot back", not gate.get("groq", gate.fingerprint("groq", K1)).inflight)


async def t_dispatch():
    w = World()
    fresh(LA, engine=False, w=w)
    n_before = ledger.snapshot()["pending_usage"]
    await op._complete(MSG, 50)
    check("engine OFF: today's walker answers - no ledger rows, no gate entries", ledger.snapshot()["pending_usage"] == n_before and not gate._state)
    gate.reset_all(); ledger.reset_all(); op._clients.clear()
    op._active_ctx.set(None)
    op._active_chain.set(None)
    from app.config import settings
    settings.groq_api_key = "gsk_SERVER" + "q" * 30
    before = op._unset["calls"]
    install(w)
    await op._complete(MSG, 50)
    check("no key context at all: counted (a call path forgot set_active_keys), served the legacy way", op._unset["calls"] == before + 1)
    settings.groq_api_key = ""


async def t_status_notes():
    w = World().on("groq", K1, ok("fine", headers={"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14000", "x-ratelimit-reset-requests": "2m0s"}))
    fresh(LA, w=w)
    await op._complete(MSG, 50)
    row = ledger._status.get(("uA", "groq", gate.fingerprint("groq", K1)))
    check("a success on a fresh key writes a status row (ok) with the provider's allowance numbers", row and row["status"] == "ok" and row["rl_limit"] == 14400 and row["rl_remaining"] == 14000, row)
    ledger._status.clear()
    await op._complete(MSG, 50)
    check("a second success a moment later is NOT rewritten (no write per chat turn)", not ledger._status)
    fresh(None, uid="owner")
    from app.config import settings
    settings.groq_api_key = "gsk_SERVER" + "q" * 30
    await op._complete(MSG, 50)
    check("the server chain's keys get no per-learner status row, but the attempt is counted for the learner", not ledger._status and usage_of("owner")["requests"] == 1)
    settings.groq_api_key = ""


for t in (t_success, t_limit_falls_through, t_dead_keys, t_all_down, t_leave_and_next, t_isolation, t_server_chain, t_single_flight, t_early_probe, t_cancel, t_dispatch, t_status_notes):
    print(f"\n-- {t.__name__}")
    run(t())

# ============================================================================================ D3. the "AI busy" work
section("D3. 'AI busy': one more pass for a passing failure, limits per model, the model memory, one safe log line")
import contextlib                                          # noqa: E402
import io                                                  # noqa: E402

BOOM = {"error": {"message": "boom"}}


class Pauses:
    """Stands in for op._pause: records how long the walk wanted to wait; `age` lets the test move time forward (a limit runs its course)."""

    def __init__(self, age=None):
        self.log, self.age = [], age

    async def __call__(self, secs):
        self.log.append(round(secs, 2))
        if self.age:
            self.age()


async def walk(keys=None, w=None, uid="uA", pz=None, **kw):
    """One walk with a fake pause. -> (text or the ProviderChainError, the pauses it asked for)."""
    fresh(keys, uid=uid, w=w)
    pz = pz or Pauses()
    saved, op._pause = op._pause, pz
    try:
        try:
            return await op._complete(MSG, 50, **kw), pz.log
        except ProviderChainError as e:
            return e, pz.log
    finally:
        op._pause = saved


async def t_repass():
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(503, BOOM), err(503, BOOM), ok()))
    check("a passing failure (503 on every model): the walk pauses ~1.2-1.8 s and goes round ONCE more - the learner never sees it",
          r == "OK" and len(pz) == 1 and 1.2 <= pz[0] <= 1.8 and len(world.calls_for("groq")) == 3, (r, pz, world.calls))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(503, BOOM)))
    check("... and when the second pass fails too: a ProviderChainError 'transient' after exactly two passes (2 models x 2) and one pause", isinstance(r, ProviderChainError) and r.state == "transient"
          and len(pz) == 1 and len(world.calls_for("groq")) == 4, (r, pz, len(world.calls)))
    kp = r.kp()
    check("... whose kp carries the short default countdown (nothing the provider said) and says these are the learner's OWN keys", kp["retry_in"] == 6 and kp["own"] is True and kp["state"] == "transient", kp)
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(401, GROQ_401)))
    check("a REJECTED key never earns a second pass", isinstance(r, ProviderChainError) and r.state == "all_invalid" and pz == [] and len(world.calls_for("groq")) == 1, (r, pz))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_PLAIN)))
    check("a limit with a long wait (90 s) never earns one either", isinstance(r, ProviderChainError) and r.state == "all_limited" and pz == [], (r, pz))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_TPM), err(429, GROQ_429_TPM), ok()), pz=Pauses(age=lambda: age_limit("groq", K1)))
    check("a limit that ends in seconds ('try again in 3.2s' -> held 5 s, the classifier's floor) is WAITED OUT: one pause of ~5.25 s, then the answer", r == "OK" and len(pz) == 1 and 5.0 <= pz[0] <= 5.5, (r, pz, world.calls))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(400, {"error": {"message": "Unsupported value"}})))
    check("a bad request (every model refuses it) is deterministic: no second pass", isinstance(r, ProviderChainError) and pz == [], (r, pz))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(404, OPENROUTER_404)))
    check("every model 'not found': no second pass either", isinstance(r, ProviderChainError) and pz == [] and len(world.calls_for("groq")) == 2, (r, pz, world.calls))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(503, BOOM), err(503, BOOM), ok()), cool=False)
    check("a BACKGROUND caller (cool=False: Grammar Coach) never waits", isinstance(r, ProviderChainError) and pz == [], (r, pz))
    saved_dl = op._CHAIN_DEADLINE_S
    op._CHAIN_DEADLINE_S = 5.0
    try:
        r, pz = await walk({"groq": K1}, World().on("groq", K1, err(503, BOOM), err(503, BOOM), ok()))
    finally:
        op._CHAIN_DEADLINE_S = saved_dl
    check("the 30 s ceiling still rules: not enough of it left -> no second pass", isinstance(r, ProviderChainError) and pz == [], (r, pz))
    r, pz = await walk({"groq": K1, "gemini": K2}, World().on("groq", K1, err(503, BOOM)).on("gemini", K2, ok()))
    check("an answer from the NEXT provider needs no pause at all", r == "OK" and pz == [], (r, pz))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, R(200, completion("")), R(200, completion("")), ok()))
    check("an EMPTY answer on every model is a passing failure too: one pause, then the answer", r == "OK" and len(pz) == 1, (r, pz))
    r, pz = await walk({"groq": K1}, World().on("groq", K1, timeout(), ok()))
    check("a timeout leaves the provider (as before) - and the second pass asks it again after the pause", r == "OK" and len(pz) == 1 and len(world.calls_for("groq")) == 2, (r, pz, world.calls))


async def t_per_model():
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_PLAIN), ok()))
    fp = gate.fingerprint("groq", K1)
    check("Groq limits PER MODEL: the first model limited, the second answers - the learner got an answer and the KEY is not gated",
          r == "OK" and [c[3] for c in world.calls_for("groq")] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"] and gate.get("groq", fp) is None, (r, world.calls))
    check("... only the limited MODEL is remembered", gate.model_blocked("groq", fp, "openai/gpt-oss-120b", time.time()) is not None and gate.model_blocked("groq", fp, "openai/gpt-oss-20b", time.time()) is None)
    n = len(world.calls_for("groq"))
    text = await op._complete(MSG, 50)
    check("the NEXT call goes straight to the model that works (no wasted round trip on the limited one)", text == "OK" and [c[3] for c in world.calls_for("groq")][n:] == ["openai/gpt-oss-20b"], world.calls)
    u = usage_of("uA", "groq")
    check("the ledger saw all three requests (1 limited, 2 ok)", u["requests"] == 3 and u["limited"] == 1 and u["ok"] == 2, u)
    age_limit("groq", K1)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    check("when the model's time is up it is asked again (ONE half-open probe), and its memory is cleared by the answer",
          [c[3] for c in world.calls_for("groq")][n:] == ["openai/gpt-oss-120b"] and gate.model_get("groq", fp, "openai/gpt-oss-120b") is None, (world.calls, gate._models))
    r, _ = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_PLAIN)))
    check("EVERY model limited -> now the key is gated, shown as limited, and a call after that sends nothing", isinstance(r, ProviderChainError) and r.state == "all_limited"
          and gate.get("groq", fp) is not None and gate.get("groq", fp).status == "limited", r)
    n = len(world.calls)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError:
        pass
    check("... fail-fast: nothing was sent", len(world.calls) == n)
    r, _ = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_PLAIN), err(503, BOOM)))
    check("one model limited and the other 503: NOT 'all limited' - the failure is mixed, so the state is transient and the key is not gated", isinstance(r, ProviderChainError)
          and r.state == "transient" and gate.get("groq", fp) is None, r)
    r, _ = await walk({"groq": K1}, World().on("groq", K1, err(429, GROQ_429_PLAIN)), uid="uA", cool=False)
    check("cool=False on a LEARNER'S OWN key still records the limit", gate.get("groq", fp) is not None)
    from app.config import settings
    settings.groq_api_key = "gsk_SERVER" + "q" * 30
    r, _ = await walk(None, World().on("groq", settings.groq_api_key, err(429, GROQ_429_PLAIN)), uid="owner", cool=False)
    sfp = gate.fingerprint("groq", settings.groq_api_key)
    check("cool=False on the SERVER chain neither gates the key nor remembers a limited model (a background call must never cost everyone's chat)",
          gate.get("groq", sfp) is None and not gate._models, (gate.get("groq", sfp), gate._models))
    settings.groq_api_key = ""
    r, _ = await walk({"openrouter": K3}, World().on("openrouter", K3, err(429, OPENROUTER_429_DAY)))
    fp3 = gate.fingerprint("openrouter", K3)
    check("OpenRouter's DAY limit is the whole account's: the key is gated at once and the second model is not even asked", gate.get("openrouter", fp3) is not None and len(world.calls_for("openrouter")) == 1, world.calls)
    r, _ = await walk({"openrouter": K3}, World().on("openrouter", K3, err(429, OPENROUTER_429_UPSTREAM), ok()))
    check("OpenRouter's 'busy upstream' 429 is per MODEL (each free model has its own pool): the first is busy, the second answers - and the key is not gated",
          r == "OK" and [c[3] for c in world.calls_for("openrouter")] == ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"] and gate.get("openrouter", fp3) is None, (r, world.calls))
    r, pz = await walk({"openrouter": K3}, World().on("openrouter", K3, err(429, OPENROUTER_429_UPSTREAM)))
    g3 = gate.get("openrouter", fp3)
    check("both pools busy: the key is held for ~20 s (a busy pool passes in seconds, not the 90 s of a per-minute limit) and the state is 'transient', never 'your keys'",
          isinstance(r, ProviderChainError) and r.state == "transient" and g3 is not None and abs(g3.until - time.time() - 20) < 3 and r.kp()["retry_in"] == 20, (r, g3))


async def t_gone_models():
    fp = gate.fingerprint("groq", K1)
    r, _ = await walk({"groq": K1}, World().on("groq", K1, err(404, OPENROUTER_404), ok()))
    check("a model that answers 404 is skipped (the next model answered) and remembered as GONE for 30 minutes",
          r == "OK" and gate.model_get("groq", fp, "openai/gpt-oss-120b").status == "gone" and abs(gate.model_get("groq", fp, "openai/gpt-oss-120b").until - time.time() - 1800) < 5, (r, gate._models))
    check("... the key itself is untouched (a missing model says nothing about the key)", gate.get("groq", fp) is None)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    check("the NEXT call never asks the gone model", [c[3] for c in world.calls_for("groq")][n:] == ["openai/gpt-oss-20b"], world.calls)
    check("/health's list names it (for DuSu's own key fingerprints only)", gate.gone_models({fp}, time.time()) == [("groq", "openai/gpt-oss-120b")] and gate.gone_models({"someone-else"}, time.time()) == [])
    op.set_active_keys(LB, uid="uB", engine=True)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    check("it is remembered per KEY: another learner's key asks the model again", [c[3] for c in world.calls_for("groq")][n:][:1] == ["openai/gpt-oss-120b"], world.calls)
    age_limit("groq", K1)
    for k, ms in gate._models.items():
        ms.until = time.time() - 1
    op.set_active_keys({"groq": K1}, uid="uA", engine=True)
    n = len(world.calls_for("groq"))
    await op._complete(MSG, 50)
    check("after 30 minutes it is asked again (once)", [c[3] for c in world.calls_for("groq")][n:][:1] == ["openai/gpt-oss-120b"], world.calls)
    gate.mark_model_gone("groq", fp, "openai/gpt-oss-120b", time.time())
    gate.mark_model_limited("groq", fp, "openai/gpt-oss-20b", time.time(), 60)
    other_key = gate.fingerprint("groq", "gsk_someone_else_000000000000000000")
    gate.mark_model_gone("groq", other_key, "openai/gpt-oss-120b", time.time())
    check("(two models of this key are remembered, and one of another learner's)", len([k for k in gate._models if k[1] == fp]) == 2 and len([k for k in gate._models if k[1] == other_key]) == 1)
    gate.clear("groq", fp)
    check("a learner re-adding / re-verifying the key wipes what was believed about ITS models - and only its own", not [k for k in gate._models if k[1] == fp] and len([k for k in gate._models if k[1] == other_key]) == 1, gate._models)
    r, pz = await walk({"groq": K1}, World().on("groq", K1, err(404, OPENROUTER_404)))
    check("EVERY model gone: 'transient' with kind 'unavailable' and NO countdown (waiting will not bring a model back)", isinstance(r, ProviderChainError) and r.state == "transient"
          and r.keys[0]["kind"] == "unavailable" and r.kp().get("retry_in") is None and pz == [], (r.keys if isinstance(r, ProviderChainError) else r, pz))
    n = len(world.calls)
    try:
        await op._complete(MSG, 50)
    except ProviderChainError as e2:
        again = e2
    check("... and the next call sends nothing at all (both models are remembered as gone) yet still answers the same way", len(world.calls) == n and again.state == "transient")
    r, _ = await walk({"groq": K1}, World().on("groq", K1, err(404, OPENROUTER_404), err(429, GROQ_429_PLAIN)))
    check("a gone model never counts against the key: 120b gone + 20b limited = the key IS limited", isinstance(r, ProviderChainError) and r.state == "all_limited", r)


async def t_failure_log():
    op._fail_logged.clear(); op._gone_logged.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r, _ = await walk({"groq": K1}, World().on("groq", K1, err(503, {"error": {"message": "secret learner words: my salary is 90000"}})), uid="uA-secret-id")
        first = buf.getvalue()
        r, _ = await walk({"groq": K1}, World().on("groq", K1, err(503, {"error": {"message": "secret learner words: my salary is 90000"}})), uid="uA-secret-id")
    out = buf.getvalue()
    lines = [l for l in out.splitlines() if l.startswith("[keys] chain failed")]
    check("a failed walk leaves ONE line: state, whose keys, what each attempt was (provider / model / kind / status), and the pause", len(lines) == 1 and "state=transient" in lines[0] and "own=yes" in lines[0]
          and "groq/openai/gpt-oss-120b:transient-503" in lines[0] and "pause" in lines[0], out)
    check("... the same line is not repeated inside 30 s", len([l for l in out.splitlines() if l.startswith("[keys] chain failed")]) == 1)
    check("... and it carries NO key, NO learner id and NOTHING the provider wrote (it can echo the learner's words)", K1 not in out and "gsk_" not in out and "uA-secret-id" not in out and "salary" not in out and "boom" not in out, out)
    op._fail_logged.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        await walk({"groq": K1}, World().on("groq", K1, err(404, OPENROUTER_404)))
    check("a model the provider says does not exist is logged ONCE by name (an owner can fix config.py before anyone asks)", buf.getvalue().count("[keys] model not found: groq/openai/gpt-oss-120b") == 1, buf.getvalue())


for t in (t_repass, t_per_model, t_gone_models, t_failure_log):
    print(f"\n-- {t.__name__}")
    run(t())

# ============================================================================================ legacy cooldown classes (pinned)
section("D2. the legacy cooldown classes are unchanged")
cases = {"Error code: 401 - invalid authentication": 21600, "Error code: 403 - forbidden": 21600, "Error code: 404 - not found": 21600, "Error code: 410 - gone": 21600,
         "github_models_retirement_brownout": 21600, "Unauthorized": 21600, "invalid api key provided": 21600,
         "Error code: 429 - daily quota exhausted for the day": 1800, "429 rate limit": 90, "rate limited, try again": 90,
         "Limit 8000, Used 4041, Requested 4500 rate limit": 90}
for msg, want in cases.items():
    op._cooldown.clear()
    op._mark_cooldown("p", msg)
    check(f"_mark_cooldown({msg[:40]!r}) = {want} s", abs(op._cooldown["p"] - time.time() - want) < 5 and op._cooldown_seconds(msg) == want)

# ============================================================================================ E. main.py helpers
section("E. main.py helpers")
os.environ.setdefault("GOOGLE_CLIENT_ID", "")
import app.main as M                                      # noqa: E402

pe = ProviderChainError("429 x", "all_limited", [{"provider": "groq", "kind": "limited"}])
try:
    try:
        raise pe
    except Exception as inner:
        raise RuntimeError("wrapped once") from inner
except Exception as outer:
    wrapped = outer
check("key_failure finds the ProviderChainError behind a wrapper (practice.AnalysisUnavailable ... from first_exc)", M.key_failure(wrapped)["state"] == "all_limited")
check("... None for an ordinary error, None for None", M.key_failure(RuntimeError("boom")) is None and M.key_failure(None) is None)
cyc = RuntimeError("a"); cyc.__cause__ = cyc
check("... a cause cycle cannot loop forever", M.key_failure(cyc) is None)
kw = M.kp_kw(pe)
check("kp_kw adds the field only when there is one", set(kw) == {"kp"} and kw["kp"]["state"] == "all_limited" and M.kp_kw(RuntimeError("x")) == {})

# the "AI busy" work: what is quota, what the learner is told, when it is worth asking again
TR = lambda kind, **k: {"provider": "groq", "kind": kind, **k}
check("kp.retry_in: a passing failure with no wait from the provider -> the short default (6 s)", ProviderChainError("x", "transient", [TR("transient")]).kp()["retry_in"] == 6)
check("... a busy shared pool (20 s) and a minute limit use the wait the walker recorded", ProviderChainError("x", "transient", [TR("limited", scope="upstream", retry_s=20.0)]).kp()["retry_in"] == 20
      and ProviderChainError("x", "transient", [TR("limited", scope="minute", retry_s=42.4)]).kp()["retry_in"] == 42)
check("... the SOONEST key that can recover wins", ProviderChainError("x", "transient", [TR("limited", scope="minute", retry_s=40), TR("transient"), TR("invalid")]).kp()["retry_in"] == 6)
check("... never below 3 s, never above 10 minutes", ProviderChainError("x", "transient", [TR("limited", scope="minute", retry_s=1)]).kp()["retry_in"] == 3
      and ProviderChainError("x", "transient", [TR("limited", scope="minute", retry_s=99999)]).kp()["retry_in"] == 600)
check("... nothing that cannot recover by itself (rejected, blocked, out of credit, a day limit, a gone model) has one",
      all("retry_in" not in ProviderChainError("x", "transient", [TR(k, **extra)]).kp() for k, extra in (("invalid", {}), ("forbidden", {}), ("needs_credit", {}), ("limited", {"scope": "day", "retry_s": 1800.0}), ("unavailable", {}))))
check("... and a state the learner must ACT on (all rejected / limited) carries none", "retry_in" not in ProviderChainError("x", "all_limited", [TR("limited", scope="minute", retry_s=10)]).kp())
own_false = ProviderChainError("Error code: 429 - secret", "all_invalid", [TR("invalid"), {"provider": "gemini", "kind": "limited", "scope": "day", "reset_at": NOW + 99, "retry_s": 99.0}], own=False).kp(NOW)
check("DuSu's OWN keys: whatever the real reason, the learner is told 'transient', own false, and given NO key rows (they cannot fix a key they never added)",
      own_false["state"] == "transient" and own_false["own"] is False and own_false["keys"] == [] and "groq" not in str(own_false) and "secret" not in str(own_false), own_false)
check("... the learner's own keys keep their rows and say own true", ProviderChainError("x", "all_limited", [TR("limited", scope="day")]).kp()["own"] is True
      and ProviderChainError("x", "all_limited", [TR("limited", scope="day")]).kp()["keys"][0]["provider"] == "groq")
def pce(state, own=True, msg="Error code: 429 - rate limit"):
    return ProviderChainError(msg, state, [TR("limited")], own=own)
check("_is_quota: 'the AI service did not answer' is NEVER quota - even when its text says 429", M._is_quota(pce("transient")) is False and M._is_quota(pce("transient", own=False)) is False)
check("_is_quota: the learner's OWN keys rejected / limited / absent IS quota", M._is_quota(pce("all_invalid")) and M._is_quota(pce("all_limited")) and M._is_quota(pce("no_keys")))
check("_is_quota: ... but never on DuSu's own keys (the learner cannot fix those)", not any(M._is_quota(pce(st, own=False)) for st in ("all_invalid", "all_limited", "no_keys")))
check("_is_quota: an error the engine never classified keeps the old text guess (429 / quota -> yes, a timeout -> no)", M._is_quota(RuntimeError("Error code: 429 - x")) and M._is_quota(RuntimeError("quota exceeded"))
      and not M._is_quota(RuntimeError("all providers/models unavailable: timed out")))
try:
    try:
        raise pce("transient")
    except Exception as inner:
        raise RuntimeError("wrapped, and its text says 429") from inner
except Exception as outer:
    check("_is_quota: sees through a wrapper to the engine's classification (transient stays not-quota)", M._is_quota(outer) is False)
ke = M.key_error(pce("all_limited", own=False), 502, "gen_failed")
check("key_error on DuSu's own keys: the site's own status (502), never a 429 'quota'; kp attached and transient", ke.status_code == 502 and ke.detail == "gen_failed" and ke.kp["state"] == "transient" and ke.kp["own"] is False, (ke.status_code, ke.detail))
ke = M.key_error(pce("transient"), 502, "gen_failed")
check("key_error: a busy provider whose text says 429 is no longer a 429 'quota' either", ke.status_code == 502 and ke.detail == "gen_failed", (ke.status_code, ke.detail))
ke = M.key_error(pce("all_limited"), 502, "gen_failed")
check("key_error: the learner's own keys all limited is still 429 'quota' (unchanged)", ke.status_code == 429 and ke.detail == "quota")

# the provider's own sentence for a refusal (what the OWNER's alert and dashboard show for DuSu's own keys)
from app.keys import probe as KP                          # noqa: E402
from world import GEMINI_403_FREE_TIER                    # noqa: E402
check("probe._why_from_body: Groq's dict, Gemini's LIST and OpenRouter's nested body each give the provider's own sentence",
      KP._why_from_body(GROQ_401) == "Invalid API Key" and KP._why_from_body(GEMINI_403_FREE_TIER).startswith("The Gemini API free tier is not available for this project.")
      and KP._why_from_body(OPENROUTER_429_UPSTREAM) == "Provider returned error", (KP._why_from_body(GROQ_401), KP._why_from_body(GEMINI_403_FREE_TIER)[:60]))
check("... Google's whole sentence fits (it ends in the billing link, which must not be cut in the middle)", KP._why_from_body(GEMINI_403_FREE_TIER).endswith("https://aistudio.google.com/billing"), KP._why_from_body(GEMINI_403_FREE_TIER))
leaky = {"error": {"message": "Bad keys AIzaSyA1234567890abcdefghijkLMN and gsk_abcdef1234567890 and sk-or-v1-0123456789abcdef and AQ.Ab8RN6IxYz"}}
why = KP._why_from_body(leaky)
check("... anything key-shaped is removed", "AIza" not in why and "gsk_" not in why and "sk-or" not in why and "AQ." not in why and why.count("<key>") == 4, why)
long_body = {"error": {"message": ("word " * 120).strip()}}
why = KP._why_from_body(long_body)
check("... bounded to 240 characters and cut at a word, with an ellipsis", len(why) <= KP.WHY_MAX + 1 and why.endswith("…") and "wor…" not in why and why[:-1].endswith("word"), (len(why), why[-20:]))
check("... a body that is not shaped like an error gives nothing (never raises)", KP._why_from_body(None) == "" and KP._why_from_body([]) == "" and KP._why_from_body("plain text") == "plain text" and KP._why_from_body(12) == "")
check("quota_msg: the old text without kp, a new one that names the real path (More -> My AI keys) with kp - never 'Settings'",
      M.quota_msg(RuntimeError("429")) == M._OLD_QUOTA_MSG and "Settings" not in M.quota_msg(pe) and "My AI keys" in M.quota_msg(pe))
ke = M.key_error(pe, 502, "x")
check("key_error: a key problem is 429 'quota' with kp", ke.status_code == 429 and ke.detail == "quota" and ke.kp["state"] == "all_limited")
ke = M.key_error(ProviderChainError("t", "transient", []), 502, "gen_failed")
check("key_error: provider trouble keeps the site's own status and detail, kp attached", ke.status_code == 502 and ke.detail == "gen_failed" and ke.kp["state"] == "transient")
ke = M.key_error(RuntimeError("Error code: 429 limit"), 502, "gen_failed")
check("key_error: an old-style quota string is still 429 'quota' (no kp)", ke.status_code == 429 and ke.detail == "quota" and ke.kp is None)
ke = M.key_error(RuntimeError("Error code: 429 limit"), 502, "gen_failed", check_quota=False)
check("key_error(check_quota=False): sites that never tested for quota keep answering their own error", ke.status_code == 502 and ke.detail == "gen_failed")
check("clean_whatsapp accepts a group invite and strips tracking parameters", M.clean_whatsapp("https://chat.whatsapp.com/TestInviteCode0123456789?s=sh&p=a&mlu=4#x") == "https://chat.whatsapp.com/TestInviteCode0123456789")
check("... and a Channel", M.clean_whatsapp("https://whatsapp.com/channel/0029VaAbCdEfGh12/") == "https://whatsapp.com/channel/0029VaAbCdEfGh12")
check("... and nothing else (other hosts, http, lookalikes, junk, empty)", all(M.clean_whatsapp(u) == "" for u in (
    "http://chat.whatsapp.com/TestInviteCode0123456789", "https://chat.whatsapp.com.evil.com/TestInviteCode0123456789", "https://evil.com/chat.whatsapp.com/TestInviteCode0123456789",
    "https://chat.whatsapp.com/short", "javascript:alert(1)", "", None, "https://wa.me/919999999999")))

# ============================================================================================ F. hygiene
section("F. hygiene")
root = "/app/app"
bad_sites, sites = [], 0
for dirpath, _d, files in os.walk(root):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(dirpath, fn)
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name == "set_active_keys":
                    sites += 1
                    kws = {k.arg for k in node.keywords}
                    if not {"uid", "engine"} <= kws:
                        bad_sites.append(f"{os.path.relpath(path, root)}:{node.lineno}")
check(f"every set_active_keys call site ({sites}) passes uid= and engine= (a forgotten site would silently skip the accounting)", sites >= 12 and not bad_sites, bad_sites)
check("there are exactly the 12 known call sites (10 in main.py, grammar/api.py, resume_interview/api.py)", sites == 12, sites)

from app.keys import models as km                         # noqa: E402
widths = {}
for M_ in km.KY_TABLES:
    for col in M_.__table__.columns:
        ln = getattr(col.type, "length", None)
        if ln:
            widths[(M_.__tablename__, col.name)] = ln
statuses = ["ok", "limited", "invalid", "forbidden", "unknown"]
kinds = ["", "limited", "invalid", "forbidden", "needs_credit", "model_gone", "bad_request", "transient", "unknown"]
scopes = ["", "minute", "day", "upstream"]
check("kh_status column widths fit every value the code writes", all(len(v) <= widths[("kh_status", "status")] for v in statuses) and all(len(v) <= widths[("kh_status", "kind")] for v in kinds)
      and all(len(v) <= widths[("kh_status", "scope")] for v in scopes) and all(len(p) <= widths[("kh_status", "provider")] for p in classify.PROVIDERS)
      and len(f1) <= widths[("kh_status", "fp")] and len(f1) <= widths[("kh_usage", "fp")], widths)
check("kh_usage: the day column fits an ISO date, the provider column fits every provider", len("2026-10-27") <= widths[("kh_usage", "day")] and all(len(p) <= widths[("kh_usage", "provider")] for p in classify.PROVIDERS))
check("every kind the gate / walker can write is in the classifier's vocabulary", all(k in classify.KINDS or k in ("", "limited") for k in kinds))

import app.keys.service as ksvc                           # noqa: E402


class Row:
    def __init__(self, **kw):
        self.status = kw.get("status", "ok"); self.kind = kw.get("kind", ""); self.scope = kw.get("scope", ""); self.evidence = kw.get("evidence", False)
        self.approx = kw.get("approx", False); self.expired = kw.get("expired", False); self.since = kw.get("since"); self.reset_at = kw.get("reset_at")
        self.rl_limit = kw.get("rl_limit"); self.rl_remaining = kw.get("rl_remaining"); self.rl_reset_at = kw.get("rl_reset_at"); self.rl_at = kw.get("rl_at")
        self.meta = kw.get("meta") or {}


section("F2. what the Keys screen derives (pure)")
T = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc)      # noqa: E731
gate.reset_all()
check("a key with no row and no gate entry is 'unknown' (never shown as working before it was looked at)", ksvc.effective("groq", "f", None, NOW)["status"] == "unknown")
check("a saved ok row reads ok", ksvc.effective("groq", "f", Row(status="ok", since=T(NOW - 10)), NOW)["status"] == "ok")
r = Row(status="limited", scope="day", evidence=True, since=T(NOW - 10), reset_at=T(NOW + 500))
e = ksvc.effective("groq", "f", r, NOW)
check("a saved limit with provider evidence reads limited and shows its reset", e["status"] == "limited" and e["reset_at"] == int(NOW + 500), e)
e = ksvc.effective("groq", "f", r, NOW + 501)
check("... and reads ok once its time is up (stale, so a re-check is scheduled)", e["status"] == "ok" and e["stale"] and e["reset_at"] is None, e)
r = Row(status="limited", scope="minute", since=T(NOW - 10))
check("a minute limit with no evidence lasts 90 s", ksvc.effective("groq", "f", r, NOW + 70)["status"] == "limited" and ksvc.effective("groq", "f", r, NOW + 91)["status"] == "ok")
r = Row(status="limited", scope="day", since=T(NOW - 10))
check("a day limit with no evidence is held for 30 min then re-tested", ksvc.effective("groq", "f", r, NOW + 1700)["status"] == "limited" and ksvc.effective("groq", "f", r, NOW + 1900)["status"] == "ok")
check("an invalid key stays invalid (it does not run out)", ksvc.effective("groq", "f", Row(status="invalid", since=T(NOW - 99999)), NOW)["status"] == "invalid")
gate.mark_limited("groq", "f", NOW - 5, 600, scope="day", reset_at=NOW + 600, evidence=True)
e = ksvc.effective("groq", "f", Row(status="ok", since=T(NOW - 1000)), NOW)
check("a NEWER gate entry beats an older saved row (two learners can share a key)", e["status"] == "limited" and e["reset_at"] == int(NOW + 600), e)
e = ksvc.effective("groq", "f", Row(status="invalid", since=T(NOW + 100)), NOW)
check("... a newer saved row beats an older gate entry", e["status"] == "invalid")
gate.reset_all()
check("allowance: Groq reports -> exact, with its own reset", ksvc._allowance("groq", Row(rl_limit=14400, rl_remaining=14000, rl_reset_at=T(NOW + 100), rl_at=T(NOW - 5)), 7, NOW)
      == {"kind": "exact", "limit": 14400, "left": 14000, "reset_at": int(NOW + 100), "as_of": int(NOW - 5)})
check("allowance: a Groq reading older than its own reset is 'unknown' - no number beats a wrong one", ksvc._allowance("groq", Row(rl_limit=14400, rl_remaining=14000, rl_reset_at=T(NOW - 1), rl_at=T(NOW - 99)), 7, NOW) == {"kind": "unknown"})
check("allowance: Groq with no reading yet -> unknown", ksvc._allowance("groq", None, 3, NOW) == {"kind": "unknown"})
a = ksvc._allowance("openrouter", Row(meta={"is_free_tier": True}), 38, NOW)
check("allowance: OpenRouter free account = the documented 50/day minus what DuSu counted, marked computed", a["kind"] == "computed" and a["limit"] == 50 and a["left"] == 12, a)
a = ksvc._allowance("openrouter", Row(meta={"is_free_tier": False}), 38, NOW)
check("... an account with credits = 1000/day", a["limit"] == 1000 and a["left"] == 962, a)
check("... never below zero", ksvc._allowance("openrouter", None, 500, NOW)["left"] == 0)
check("allowance: Gemini has no quota API -> unknown (DuSu says so instead of guessing)", ksvc._allowance("gemini", Row(), 99, NOW) == {"kind": "unknown"})
check("state: no keys / all ok / some bad / one ok / unknown / all rejected / all limited", [ksvc._state_of(*a) for a in
      ((0, 0, 0, 0, 0), (2, 2, 0, 0, 0), (3, 2, 1, 0, 0), (2, 1, 0, 1, 0), (2, 0, 0, 0, 2), (2, 0, 0, 2, 0), (2, 0, 1, 1, 0))]
      == ["no_keys", "ok", "degraded", "degraded", "unknown", "all_invalid", "all_limited"])

print(f"\n{N - len(FAILS)} / {N} checks passed")
sys.exit(1 if FAILS else 0)
