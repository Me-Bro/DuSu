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

HOSTS = {"groq": "api.groq.com", "gemini": "generativelanguage.googleapis.com", "openrouter": "openrouter.ai",
         "cloudflare": "api.cloudflare.com", "zai": "api.z.ai", "sarvam": "api.sarvam.ai"}
PROVIDER_OF = {v: k for k, v in HOSTS.items()}


def completion(text="OK", usage=(5, 3), finish="stop"):
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": usage[0] + usage[1]}}


class R:
    """One scripted answer."""

    def __init__(self, status=200, body=None, headers=None, exc=None, delay=0.0, text=None, ctype="text/html"):
        self.status, self.body, self.headers, self.exc, self.delay = status, body, headers or {}, exc, delay
        self.text, self.ctype = text, ctype             # a body that is NOT json (an HTML 502 from a CDN, a JSON reply cut off mid-way)


def ok(text="OK", headers=None, usage=(5, 3), finish="stop"):
    return R(200, completion(text, usage, finish), headers)


def err(status, body, headers=None):
    return R(status, body, headers)


def raw(status, text, ctype="text/html", headers=None):
    """An answer whose body is not JSON the SDK can read: a CDN's HTML error page (status 502), or a 200 whose JSON was cut off."""
    return R(status, None, headers, text=text, ctype=ctype)


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
GEMINI_400_AUTH_KEY = [{"error": {"code": 400, "message": "Invalid Auth key.", "status": "INVALID_ARGUMENT"}}]     # measured 2026-11-07: Google's answer to a wrong / cut / mistyped AQ. key
GEMINI_400_OTHER =[{"error": {"code": 400, "message": "Unsupported value for max_tokens.", "status": "INVALID_ARGUMENT"}}]
GEMINI_403_LEAKED = [{"error": {"code": 403, "message": "Your API key was reported as leaked. Please use another API key.", "status": "PERMISSION_DENIED"}}]
GEMINI_403_FREE_TIER = [{"error": {"code": 403, "message": "The Gemini API free tier is not available for this project. To use the Gemini API, please set up billing to upgrade to the paid tier at https://aistudio.google.com/billing", "status": "PERMISSION_DENIED"}}]
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


# --- Cloudflare Workers AI / Z.ai / Sarvam (added 2026-11-17). SYNTHETIC like the rest: the shapes follow each provider's OWN docs (Cloudflare: developers.cloudflare.com/workers-ai/platform/errors/, Z.ai: docs.z.ai/api-reference/api-code,
# Sarvam: docs.sarvam.ai chat-completions reference + pricing page); NONE was seen from a real key - tests/keys/capture_real_errors.py records the real ones. Marked per body where the docs gave
# the code but not the exact text, or where the code is from the tester's memory of Cloudflare's API (10000 / 6003 / 6111 / 7003).
def _cf(code, msg, **extra):
    return {"result": None, "success": False, "errors": [{"code": code, "message": msg, **extra}], "messages": []}


CF_429_DAY = _cf(3036, "AiError: You have used up your daily free allocation of 10,000 neurons. Please upgrade to Cloudflare's Workers Paid plan if you would like to continue usage.")      # docs: code + start of the text
CF_429_CAPACITY = _cf(3040, "AiError: Capacity temporarily exceeded, please try again.")                                                                                                 # docs: code; text paraphrased
CF_403_AUTH = _cf(10000, "Authentication error")                                                                                                                                         # NOT in the fetched docs: from memory of Cloudflare's API
CF_400_AUTH_HDR = {"result": None, "success": False, "errors": [{"code": 6003, "message": "Invalid request headers", "error_chain": [{"code": 6111, "message": "Invalid format for Authorization header"}]}], "messages": []}   # from memory
CF_404_ROUTE = _cf(7003, "Could not route to /client/v4/accounts/00000000000000000000000000000000/ai/v1/chat/completions, perhaps your object identifier is invalid?")                  # from memory: a wrong account id
CF_400_NO_MODEL = _cf(5007, "AiError: No such model @cf/nope/nope or task")                                                                                                              # docs: code + status 400
CF_404_MODEL = _cf(3042, "AiError: Invalid model name")                                                                                                                                  # docs: code + status 404
CF_410_MODEL = _cf(5028, "AiError: Model has been deprecated")                                                                                                                           # docs: code + status 410
CF_403_PAID = _cf(5035, "AiError: Model requires a Workers Paid plan")                                                                                                                   # docs: code + status 403
CF_403_PLAIN = {"result": None, "success": False, "errors": [{"code": 3023, "message": "AiError: Service unavailable for account"}], "messages": []}                                       # docs: code 3023, status 403
CF_413 = _cf(3006, "AiError: Request is too large")
CF_API_429 = {"result": None, "success": False, "errors": [{"code": 971, "message": "Too many requests"}], "messages": []}                                                               # the global API rate limit: HTTP 429 + a retry-after header (code from memory)
ZAI_401_AUTH = {"error": {"code": "1000", "message": "Authentication Failed"}}                                                                                                           # docs
ZAI_401_NOHDR = {"error": {"code": "1001", "message": "Authentication parameter not received in Header, unable to authenticate"}}                                                        # docs
ZAI_401_EXPIRED = {"error": {"code": "1003", "message": "Authentication Token expired, please regenerate/obtain"}}                                                                       # docs
ZAI_429_RATE = {"error": {"code": "1302", "message": "Rate limit reached for requests"}}                                                                                                 # docs
ZAI_429_BUSY = {"error": {"code": "1305", "message": "The service may be temporarily overloaded, please try again later"}}                                                               # docs
ZAI_429_BALANCE = {"error": {"code": "1113", "message": "Insufficient balance or no resource package. Please recharge."}}                                                                # docs (HTTP 429!)
ZAI_429_CAP = {"error": {"code": "1308", "message": "Usage limit reached for this period; it resets at a set time."}}                                                                    # docs: code; text paraphrased
ZAI_400_MODEL = {"error": {"code": "1211", "message": "Unknown Model, please check the model code."}}                                                                                    # docs
ZAI_400_PARAM = {"error": {"code": "1210", "message": "Invalid API parameter"}}                                                                                                          # docs
ZAI_400_UNSAFE = {"error": {"code": "1301", "message": "The input or output was flagged as unsafe or sensitive."}}                                                                       # docs: code; text paraphrased
ZAI_403_PERM = {"error": {"code": "1220", "message": "You do not have permission to access the requested API"}}                                                                          # docs: code; text paraphrased
ZAI_500 = {"error": {"code": "1234", "message": "Network error, please retry later"}}                                                                                                    # docs: code
SARVAM_403_KEY = {"error": {"message": "Invalid API key", "code": "invalid_api_key_error", "request_id": "r-1"}}                                                                          # docs: code names; text invented
SARVAM_403_AUTH = {"error": {"message": "Authentication failed", "code": "authentication_error", "request_id": "r-2"}}                                                                    # docs: code name
SARVAM_403_PLAIN = {"error": {"message": "Forbidden", "code": "forbidden_error", "request_id": "r-3"}}                                                                                    # docs: message "Forbidden"
SARVAM_402 = {"error": {"message": "Insufficient credits", "code": "insufficient_quota_error", "request_id": "r-4"}}                                                                      # docs: 402 + code (pricing page)
SARVAM_429_QUOTA = {"error": {"message": "Quota Exceeded", "code": "insufficient_quota_error", "request_id": "r-5"}}                                                                      # docs: the chat reference lists 429 "Quota Exceeded" with this code
SARVAM_429_RATE = {"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded_error"}}                                                                                     # docs (rate-limits page)
SARVAM_422 = {"error": {"message": "Unprocessable Entity", "code": "unprocessable_entity_error", "request_id": "r-6"}}                                                                    # docs


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
        self.bodies: list = []        # the JSON body of every chat request, in order (what was really SENT: max_tokens, reasoning_effort ...)
        self.paths: list = []         # (provider, url path, full url) of every request (Cloudflare puts the account id in the path)
        self.auth: list = []          # (provider, the raw Authorization header) of every request - what really went on the wire
        self.subkey: list = []        # (provider, the raw api-subscription-key header or None) of every request - Sarvam is sent its own header as well as Bearer

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
            body = {}
            try:
                body = json.loads(req.content or b"{}")
                model, messages = body.get("model", ""), body.get("messages")
            except Exception:
                model = ""
            self.last_messages = messages
            self.bodies.append(body)
        self.calls.append((provider, key, kind, model))
        self.paths.append((provider, req.url.path, str(req.url)))
        self.auth.append((provider, auth))
        self.subkey.append((provider, req.headers.get("api-subscription-key")))
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
            limit = (req.extensions.get("timeout") or {}).get("read")          # a real transport enforces the request's timeout; MockTransport does not, so do it here
            if limit is not None and r.delay > limit:
                await asyncio.sleep(limit)
                raise httpx.ReadTimeout("timed out", request=req)
            await asyncio.sleep(r.delay)
        if r.exc is not None:
            raise r.exc
        if r.text is not None:
            return httpx.Response(r.status, content=r.text.encode("utf-8"), headers={"content-type": r.ctype, **r.headers}, request=req)
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
