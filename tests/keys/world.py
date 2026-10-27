"""Keys - the fake provider world every test in this folder talks to. No network: the app's SDK clients and probes are pointed at an httpx MockTransport through
`openrouter_provider._http_client_factory`, and every answer is scripted PER PROVIDER HOST + BEARER KEY - so "learner A's Groq key is limited while learner B's is
fine" is one line.

The error bodies are SYNTHETIC (a day limit cannot be provoked on demand, and a test must never spend a real key); their shapes follow what each provider documents:
Groq sends a dict with "Please try again in 6m45.6s", Gemini sends a LIST with QuotaFailure / RetryInfo, OpenRouter nests the upstream text in `metadata.raw`.
tests/keys/capture_real_errors.py (owner-run, never CI) records real ones with the owner's own keys so these fixtures can be checked against reality.
"""

from __future__ import annotations

import asyncio
import json

import httpx

HOSTS = {"groq": "api.groq.com", "gemini": "generativelanguage.googleapis.com", "openrouter": "openrouter.ai"}
PROVIDER_OF = {v: k for k, v in HOSTS.items()}


def completion(text="OK", usage=(5, 3), finish="stop"):
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": usage[0] + usage[1]}}


class R:
    """One scripted answer."""

    def __init__(self, status=200, body=None, headers=None, exc=None, delay=0.0):
        self.status, self.body, self.headers, self.exc, self.delay = status, body, headers or {}, exc, delay


def ok(text="OK", headers=None, usage=(5, 3), finish="stop"):
    return R(200, completion(text, usage, finish), headers)


def err(status, body, headers=None):
    return R(status, body, headers)


def timeout():
    return R(exc=httpx.ReadTimeout("timed out"))


def conn():
    return R(exc=httpx.ConnectError("connection refused"))


# --------------------------------------------------------------------------------------------- synthetic bodies
GROQ_401 = {"error": {"message": "Invalid API Key", "type": "invalid_request_error", "code": "invalid_api_key"}}
GROQ_429_TPD = {"error": {"message": "Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01` service tier `on_demand` on tokens per day (TPD): "
                                     "Limit 200000, Used 199921, Requested 1500. Please try again in 6m45.6s. Need more tokens? Upgrade to Dev Tier today at "
                                     "https://console.groq.com/settings/billing", "type": "tokens", "code": "rate_limit_exceeded"}}
GROQ_429_TPM = {"error": {"message": "Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01` service tier `on_demand` on tokens per minute (TPM): "
                                     "Limit 8000, Used 7900, Requested 500. Please try again in 3.2s.", "type": "tokens", "code": "rate_limit_exceeded"}}
GROQ_429_PLAIN = {"error": {"message": "Rate limit reached. Slow down.", "type": "tokens", "code": "rate_limit_exceeded"}}
GEMINI_400_KEY = [{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
                             "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID", "domain": "googleapis.com"}]}}]
GEMINI_400_EXPIRED = [{"error": {"code": 400, "message": "API key expired. Please renew the API key.", "status": "INVALID_ARGUMENT",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID", "domain": "googleapis.com"}]}}]
GEMINI_400_OTHER = [{"error": {"code": 400, "message": "Unsupported value for max_tokens.", "status": "INVALID_ARGUMENT"}}]
GEMINI_403_LEAKED = [{"error": {"code": 403, "message": "Your API key was reported as leaked. Please use another API key.", "status": "PERMISSION_DENIED"}}]
GEMINI_429_DAY = [{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED",
                             "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                                 {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                  "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "1000"}]}]}}]
GEMINI_429_MIN = [{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED",
                             "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                                 {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                  "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "15"}]},
                                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}]}}]
GEMINI_429_BARE = [{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED"}}]
GEMINI_503 = [{"error": {"code": 503, "message": "The model is overloaded. Please try again later.", "status": "UNAVAILABLE"}}]
OPENROUTER_401 = {"error": {"message": "No auth credentials found", "code": 401}}
OPENROUTER_402 = {"error": {"message": "Insufficient credits. Add more using https://openrouter.ai/credits", "code": 402}}
OPENROUTER_404 = {"error": {"message": "No endpoints found for google/gemma-4-31b-it:free.", "code": 404}}
OPENROUTER_429_DAY = {"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day", "code": 429,
                                "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0"}}}}
OPENROUTER_429_UPSTREAM = {"error": {"message": "Provider returned error", "code": 429,
                                     "metadata": {"raw": "google/gemma-4-31b-it:free is temporarily rate-limited upstream. Please retry shortly, or add your own key to "
                                                         "accumulate your rate limits: https://openrouter.ai/settings/integrations", "provider_name": "Google AI Studio"}}}


class World:
    """Scripts: `world.script[(provider, key)] = [R, R, ...]` (the LAST one repeats), or `[(provider, key, 'chat'|'models'|'key')]` for one endpoint only. `world.calls` is the
    ordered log of (provider, key, kind, model). `world.default_chat` answers anything not scripted."""

    def __init__(self):
        self.script: dict = {}
        self.calls: list = []
        self.n: dict = {}
        self.default_chat = lambda: ok()
        self.chat_reply = None        # optional: callable(messages, provider, key) -> R, consulted for an UNSCRIPTED chat call (a test that needs mode-specific replies)
        self.last_messages = None

    # ----------------------------------------------------------------------- scripting
    def on(self, provider: str, key: str, *steps, kind: str | None = None):
        self.script[(provider, key, kind) if kind else (provider, key)] = list(steps)
        self.n.pop((provider, key, kind), None)
        return self

    def calls_for(self, provider: str | None = None, key: str | None = None, kind: str = "chat") -> list:
        return [c for c in self.calls if (provider is None or c[0] == provider) and (key is None or c[1] == key) and (kind is None or c[2] == kind)]

    # ----------------------------------------------------------------------- the transport
    async def handler(self, req: httpx.Request) -> httpx.Response:
        provider = PROVIDER_OF.get(req.url.host, "?")
        auth = req.headers.get("authorization", "")
        key = auth[7:] if auth.lower().startswith("bearer ") else ""
        path = req.url.path
        kind = "chat" if path.endswith("/chat/completions") else "key" if path.endswith("/key") else "models"
        model = ""
        messages = None
        if kind == "chat":
            try:
                body = json.loads(req.content or b"{}")
                model, messages = body.get("model", ""), body.get("messages")
            except Exception:
                model = ""
            self.last_messages = messages
        self.calls.append((provider, key, kind, model))
        steps = self.script.get((provider, key, kind)) or self.script.get((provider, key))
        if not steps:
            if kind == "chat":
                r = self.chat_reply(messages, provider, key) if self.chat_reply else self.default_chat()
            elif kind == "key":
                r = R(200, {"data": {"label": "k", "usage": 0, "limit": None, "is_free_tier": True}})
            else:
                r = R(200, {"data": []})
        else:
            i = self.n.get((provider, key, kind), 0)
            self.n[(provider, key, kind)] = i + 1
            r = steps[min(i, len(steps) - 1)]
            if callable(r):
                r = r()
        if r.delay:
            await asyncio.sleep(r.delay)
        if r.exc is not None:
            raise r.exc
        return httpx.Response(r.status, json=r.body, headers=r.headers, request=req)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler), timeout=httpx.Timeout(10.0))


def install(world: World):
    """Point the app at the fake world. Returns the previous factory so a test can restore it."""
    from app.providers import openrouter_provider as op
    prev = op._http_client_factory
    op._http_client_factory = world.client
    op._clients.clear()                          # a cached client may be bound to an older world's transport
    return prev
