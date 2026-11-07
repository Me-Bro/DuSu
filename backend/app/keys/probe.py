"""Keys - looking at a key from outside: the zero-quota auth probe, the one-call chat check, and the SERVER chain's own health.

auth_probe   GET {base}/models (Groq, Gemini) or GET {base}/key (OpenRouter) with the key in the Authorization header ONLY - never in a URL (a URL ends up in
             logs and in httpx's own error text). Costs no model quota. Tells a rejected key from a working one; a 429 means "the key is real, it is limited".
chat_probe   ONE real chat call (max_tokens 8) on the provider's first model that exists - a retired first model must not make a good key look bad. Counted in the
             ledger like any other attempt. Used when a learner saves a key or taps "Test".
server_health  the same auth probe over DuSu's OWN keys, cached 10 minutes: the owner's dashboard and /health read the cache, nothing probes on a request path. It also asks each
             provider for the list of models it has (zero quota; OpenRouter's list is public) and notes any model id DuSu is configured to use that is no longer in it
             (`models_missing`, shown by /health and logged once): provider model ids rot without notice (Groq's Llama, GitHub Models, OpenRouter's gpt-oss and glm each died
             one by one) and until now nobody noticed before learners did. Advisory only - it never switches a model off.

Both probes go through providers.openrouter_provider (`http_client`, `new_sdk_client`) so a test can script every answer with an httpx MockTransport.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..config import settings
from . import classify, gate, ledger

SERVER_HEALTH_TTL_S = 600


@dataclass
class Probe:
    kind: str                                  # ok | invalid | limited | forbidden | model_gone | transient | unknown
    http: int = 0
    expired: bool = False
    out: classify.Outcome | None = None        # the classifier's full answer for a failure
    meta: dict = field(default_factory=dict)   # provider specifics: {"is_free_tier": bool}
    rl: dict | None = None                     # the provider's own allowance numbers, when the response carried them
    ms: int = 0
    why: str = ""                              # the provider's own one-line reason for a refusal (bounded, anything key-shaped removed) - only DuSu's OWN keys ever show it, and only to the owner


class _Failure(Exception):
    """A non-2xx probe answer shaped like the SDK's typed errors, so `classify` reads it the same way."""

    def __init__(self, status: int, body, headers):
        super().__init__(f"Error code: {status} - {str(body)[:300]}")
        self.status_code = status
        self.body = body

        class _R:
            pass
        self.response = _R()
        self.response.headers = headers


_KEYISH = re.compile(r"(AIza|gsk_|sk-or-v1-|sk-or-|AQ\.)[A-Za-z0-9_\-.]+")


WHY_MAX = 240


def _why_from_body(body) -> str:
    """The first message in an error body (Groq sends a dict, Gemini a LIST of dicts, OpenRouter nests it), one line, <= 240 characters (cut at a word, never in the middle of a link),
    with anything key-shaped removed."""
    cur = body[0] if isinstance(body, list) and body else body
    msg = ""
    if isinstance(cur, dict):
        err = cur.get("error", cur)
        msg = str(err.get("message", "") if isinstance(err, dict) else err)
    elif isinstance(cur, str):
        msg = cur
    msg = _KEYISH.sub("<key>", " ".join(msg.split()))
    if len(msg) > WHY_MAX:
        msg = msg[:WHY_MAX].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return msg


def _entry(provider: str, key: str) -> dict | None:
    chain = settings.providers_from({provider: key})
    return chain[0] if chain else None


def _url(p: dict) -> str:
    base = p["base_url"].rstrip("/")
    return base + ("/key" if p["name"] == "openrouter" else "/models")


async def auth_probe(provider: str, key: str, now: float | None = None) -> Probe:
    """Does this provider accept this key? Never raises."""
    from ..providers import openrouter_provider as op
    p = _entry(provider, key)
    if p is None:
        return Probe("unknown")
    t0 = time.time()
    try:
        async with op.http_client() as c:
            r = await c.get(_url(p), headers={"Authorization": f"Bearer {key}", **(p.get("headers") or {})})
    except Exception:
        return Probe("unknown", ms=int((time.time() - t0) * 1000))
    ms = int((time.time() - t0) * 1000)
    if r.status_code == 200:
        meta = {}
        if provider == "openrouter":
            try:
                d = (r.json() or {}).get("data") or {}
                if isinstance(d.get("is_free_tier"), bool):
                    meta["is_free_tier"] = d["is_free_tier"]
            except Exception:
                pass
        return Probe("ok", http=200, meta=meta, ms=ms)
    try:
        body = r.json()
    except Exception:
        body = (r.text or "")[:300]
    out = classify.classify(provider, _Failure(r.status_code, body, r.headers), now)
    kind = out.kind if out.kind in ("invalid", "limited", "forbidden") else ("transient" if out.kind in ("transient", "model_gone") else "unknown")
    return Probe(kind, http=r.status_code, expired=out.expired, out=out, ms=ms, why=_why_from_body(body))


async def list_models(provider: str, key: str) -> set | None:
    """The model ids this provider says exist, or None when that could not be read (an empty or unreadable answer is "don't know", never "none exist"). Zero quota: the key
    goes in the Authorization header only (OpenRouter's catalogue is public and is asked without it). Gemini names its models 'models/<id>' - the prefix is dropped."""
    from ..providers import openrouter_provider as op
    p = _entry(provider, key)
    if p is None:
        return None
    headers = {} if provider == "openrouter" else {"Authorization": f"Bearer {key}"}
    headers.update(p.get("headers") or {})
    try:
        async with op.http_client() as c:
            r = await c.get(p["base_url"].rstrip("/") + "/models", headers=headers)
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data")
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    ids = {str(x.get("id", "")).split("models/", 1)[-1] for x in data if isinstance(x, dict) and x.get("id")}
    return ids or None


async def chat_probe(provider: str, key: str, uid: str | None = None, now: float | None = None) -> Probe:
    """ONE real call to the provider with this key. `ok` also carries the provider's allowance headers when it sends them. Never raises."""
    from ..providers import openrouter_provider as op
    p = _entry(provider, key)
    if p is None:
        return Probe("unknown")
    fp = gate.fingerprint(provider, key)
    client = op.new_sdk_client(p, timeout=15.0)
    last: Probe = Probe("unknown")
    try:
        for model in p["models"]:
            tok = ledger.begin(uid, provider, fp, now)
            done = False
            t0 = time.time()
            try:
                raw = await client.chat.completions.with_raw_response.create(
                    model=model, messages=[{"role": "user", "content": "Reply OK"}], max_tokens=8, temperature=0, extra_body=p.get("extra") or {})
                resp = raw.parse()
                usage = getattr(resp, "usage", None)
                ledger.settle(tok, "ok", getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)
                done = True
                return Probe("ok", http=200, rl=classify.parse_ratelimit(provider, getattr(raw, "headers", None), time.time()), ms=int((time.time() - t0) * 1000))
            except Exception as e:
                out = classify.classify(provider, e, now)
                ledger.settle(tok, out.kind if out.kind in ("limited", "invalid") else "other")
                done = True
                kind = out.kind if out.kind in ("invalid", "limited", "forbidden", "model_gone") else ("transient" if out.kind == "transient" else "unknown")
                last = Probe(kind, http=out.http, expired=out.expired, out=out, ms=int((time.time() - t0) * 1000), why=_why_from_body(getattr(e, "body", None)))
                if kind != "model_gone":          # a retired model is the platform's problem - try the provider's next model; anything else is the answer
                    return last
            finally:
                if not done:
                    ledger.settle(tok, "other")
    finally:
        try:
            await client.close()
        except Exception:
            pass
    return last


# --------------------------------------------------------------------------------------------- DuSu's own keys
_server: dict = {"at": 0.0, "keys": {}}
_missing_logged: dict = {}
_server_chat: dict = {}                       # provider -> {at, kind, http}: the last tiny REAL chat call to DuSu's own key
CHAT_PROBE_EVERY_S = 3600


async def refresh_server_health() -> dict:
    """Probe each of the SERVER chain's keys (zero quota) and cache the verdicts - and, for a key the provider accepts, whether every model DuSu is configured to use is
    still in the provider's own list. Called by the keys loop every 10 minutes and by the owner's dashboard."""
    out = {}
    for p in settings.providers():
        pr = await auth_probe(p["name"], p["key"])
        st = pr.kind if pr.kind in ("ok", "invalid", "limited", "forbidden") else "unknown"
        out[p["name"]] = {"status": st, "http": pr.http, "checked_at": int(time.time()), "expired": pr.expired}
        if st in ("invalid", "forbidden") and pr.why:
            out[p["name"]]["why"] = pr.why                        # the provider's own words for the owner's dashboard / alert ("Invalid API Key"); /health never carries them
        if st == "ok" and p["name"] != "openrouter":
            # The zero-quota list answered "ok" - but a key can list models and still be refused every chat call (28-30 Oct 2026: Google answered 403 "The Gemini API free tier is not
            # available for this project", /health said "ok", and every learner on DuSu's own keys was told "AI busy"). So once an hour ONE tiny real call is made (OpenRouter is left out:
            # its free pool is 50 requests a day). Only a refusal that no waiting fixes (rejected / blocked) changes the status; a limit or a hiccup does not.
            c = _server_chat.get(p["name"])
            if c is None or time.time() - c["at"] >= CHAT_PROBE_EVERY_S:
                cp = await chat_probe(p["name"], p["key"])
                prev = c["kind"] if c else "ok"
                c = _server_chat[p["name"]] = {"at": time.time(), "kind": cp.kind, "http": cp.http, "why": cp.why}
                if cp.kind in ("forbidden", "invalid") and prev not in ("forbidden", "invalid"):
                    print(f"[keys] DuSu's own {p['name']} key lists models but is refused every chat call (HTTP {cp.http}) - learners on DuSu's keys are told the AI is busy until it is replaced in backend/.env")
            if c["kind"] in ("forbidden", "invalid"):
                st = c["kind"]
                out[p["name"]].update(status=st, http=c["http"], chat=c["kind"], why=c.get("why", ""))
        if st in ("ok", "limited"):
            have = await list_models(p["name"], p["key"])
            if have:
                # an alias ("gemini-flash-lite-latest") may not be listed under its own name even though it answers: only names the list could contain are judged
                miss = [m for m in p["models"] if m not in have and not m.endswith("-latest")]
                if miss:
                    out[p["name"]]["models_missing"] = miss
                    now = time.time()
                    for m in miss:
                        if now - _missing_logged.get((p["name"], m), 0.0) > 86400:
                            _missing_logged[(p["name"], m)] = now
                            print(f"[keys] DuSu's own chain is configured to use {p['name']}/{m}, but {p['name']} no longer lists it - update config.py")
    _server["at"], _server["keys"] = time.time(), out
    return out


def cached_server_health() -> dict:
    """What the last probe found, never blocking and never probing: {provider: {status, http, checked_at}} ({} until the first probe has run)."""
    return dict(_server["keys"])


def reset_server_health() -> None:
    """Tests only."""
    _server["at"], _server["keys"] = 0.0, {}
    _missing_logged.clear()
    _server_chat.clear()
