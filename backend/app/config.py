import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# The app's public origin. Only used for OpenRouter's attribution headers —
# the app itself is origin-agnostic (the client derives every URL, including the
# WebSocket, from location.host), which is what lets one deployment serve the new
# and legacy hostnames side by side. See DUSU_DOMAIN_CUTOVER.md.
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://dusu.ranabrothers.online")

# Groq's gpt-oss models, in the order they are tried. ONE list for DuSu's own chain and for a learner's own key (they used to be two literals that had to be kept in step).
_GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def _groq_chat_extra() -> dict:
    """Request params added ONLY to per-turn calls (the walker passes prefer_fast=True), per model - see `_v2_pass` in providers/openrouter_provider.py.

    Groq's gpt-oss models are REASONING models: with no `reasoning_effort` they think at length (Groq's default), the thinking is spent from the same `max_tokens` as the
    reply and from Groq's free 8,000 tokens-per-MINUTE cap, and a 420-900 token budget can go entirely on thinking - an EMPTY answer, which the walker then repeats on the
    sibling model (a second full prompt against the same minute). Seen in production on 7 and 9 Nov 2026 (`groq/openai/gpt-oss-120b:empty, groq/openai/gpt-oss-20b:empty`).
    "low" keeps the thinking short and `include_reasoning: false` keeps it out of the reply (both documented for gpt-oss). Only a model that takes the parameters gets them,
    and a model that answers 400 to them is remembered and sent without (gate.mark_param_unsupported) - so a wrong guess here costs one failed attempt, once. Scoring /
    extraction calls (not prefer_fast) are left exactly as they were."""
    return {m: {"reasoning_effort": "low", "include_reasoning": False} for m in _GROQ_MODELS if m.startswith("openai/gpt-oss")}


class Settings(BaseSettings):
    """Loaded once from .env.

    Multiple free LLM providers can be configured. They're tried in order (the
    chain): when one runs out of free quota (429/402/etc.), the next takes over.
    To add a provider: add its `*_api_key` field here, put the key in .env, and
    add an entry to `providers()`.
    """

    # --- LLM provider keys (any/all; empty ones are skipped) ---
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    github_token: str = ""

    # --- Google Sign-In ---
    google_client_id: str = ""
    session_secret: str = "dev-change-me"

    # --- Database (MongoDB). Empty = no DB (app runs stateless as before). ---
    # The shared `rooted-mongo` (replica set rs0, reached over the external docker network `rooted-shared-net`), database `dusu`, a user scoped to it:
    #   mongodb://dusu_prod_app:<password>@rooted-mongo:27017/dusu?replicaSet=rs0&authSource=dusu
    # Under docker compose it is built in docker-compose.yml from DUSU_MONGO_PASSWORD in the root .env. A `postgres://` value is refused (store.configure).
    mongodb_uri: str = ""

    # --- Usage limits (protect the shared free quota) ---
    max_sessions_per_day: int = 20      # per user; resets daily
    conversation_max_turns: int = 40    # free chat gently wraps up
    interview_max_turns: int = 15       # hard cap (interview self-ends ~8)

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def providers(self) -> list[dict]:
        """Active providers in fallback order. Each: name, base_url, key,
        models (tried in order), headers, extra (per-provider request body),
        and optionally chat_extra ({model: params}, added only to per-turn calls)."""
        # ORDER MATTERS: measured latency, fastest-healthy first. Every model listed
        # here was benchmarked live — a dead/404 model isn't just useless, it costs a
        # full round-trip (and, on retryable statuses like 503, several) on EVERY turn
        # before the chain reaches something that answers. Re-verify with a real call
        # before adding one; provider model names get retired without notice.
        chain: list[dict] = []
        if self.groq_api_key:
            chain.append({
                "name": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "key": self.groq_api_key,
                # ~0.7s measured, clean English, no reasoning leakage. (The old
                # llama-3.3-70b-versatile / llama-3.1-8b-instant were RETIRED by Groq
                # and returned 404 on every call. Do NOT use qwen3.6-27b here: it
                # emits raw <think> blocks into the reply and truncates.)
                "models": list(_GROQ_MODELS),
                "headers": {},
                "extra": {},
                "chat_extra": _groq_chat_extra(),     # per-turn calls only (see _groq_chat_extra)
            })
        if self.gemini_api_key:
            chain.append({
                "name": "gemini",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "key": self.gemini_api_key,
                # flash-lite only: plain "gemini-flash-latest" is chronically 503
                # ("model is overloaded") and, being a retryable status, burned ~25s
                # of client retries per turn before falling through.
                "models": ["gemini-flash-lite-latest"],
                "headers": {},
                "extra": {},  # NOTE: Gemini's OpenAI-compat rejects reasoning_effort (400) — leave empty
            })
        if self.openrouter_api_key:
            chain.append({
                "name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "key": self.openrouter_api_key,
                # Free tier is heavily rate-limited (429s) — kept as a late fallback
                # only. gpt-oss-*:free and z-ai/glm-5.2:free were dropped from the
                # free tier (404, "paid version available now") — probed 2026-10-20,
                # OpenRouter's free catalog is actively collapsing, not just these two.
                # The free pool of ONE model is often "busy upstream" (429) while another model's is not - measured 30 Oct 2026 with tests/keys/probe_models.py: gemma-4-31b
                # answered 429 twice in a row, gemma-4-26b answered valid Hindi JSON in 2 s. nemotron-3-ultra (slow, broke the JSON) and nemotron-3.5-lightning (empty
                # answers) were tried and left out. Re-run the probe before changing this list.
                "models": ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"],
                "headers": {"HTTP-Referer": PUBLIC_ORIGIN, "X-Title": "DuSu"},
                "extra": {"reasoning": {"exclude": True, "effort": "low"}},
            })
        # GitHub Models is gone from the chain (2026-10-27): it was in a retirement brownout (410 on every call), and it answers 200 "OK" to ANY token, so it
        # could neither validate a key nor serve a reply - it only cost a wasted round-trip. `github_token` stays a settings field so an old .env still loads.
        return chain

    def providers_from(self, keys: dict) -> list[dict]:
        """BYOK / Office mode: build a chain from caller-supplied keys.
        Same base_urls / models / headers / order as providers(); only the key
        differs. Missing keys are skipped. keys = {gemini, groq, openrouter}."""
        # Must mirror providers() exactly (same order + same live model names) —
        # a BYOK user should get identical behaviour/latency, just on their own key.
        k = {kk: (str(vv or "")).strip() for kk, vv in (keys or {}).items()}
        chain: list[dict] = []
        if k.get("groq"):
            chain.append({"name": "groq", "base_url": "https://api.groq.com/openai/v1",
                "key": k["groq"], "models": list(_GROQ_MODELS),
                "headers": {}, "extra": {}, "chat_extra": _groq_chat_extra()})
        if k.get("gemini"):
            chain.append({"name": "gemini",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "key": k["gemini"], "models": ["gemini-flash-lite-latest"],
                "headers": {}, "extra": {}})
        if k.get("openrouter"):
            chain.append({"name": "openrouter", "base_url": "https://openrouter.ai/api/v1",
                "key": k["openrouter"],
                "models": ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"],
                "headers": {"HTTP-Referer": PUBLIC_ORIGIN, "X-Title": "DuSu"},
                "extra": {"reasoning": {"exclude": True, "effort": "low"}}})
        return chain                       # (a stored / sent "github" key is ignored: see providers())


settings = Settings()
