import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# The app's public origin. Only used for OpenRouter's attribution headers —
# the app itself is origin-agnostic (the client derives every URL, including the
# WebSocket, from location.host), which is what lets one deployment serve the new
# and legacy hostnames side by side. See DUSU_DOMAIN_CUTOVER.md.
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://dusu.ranabrothers.online")


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

    # --- Database (Postgres). Empty = no DB (app runs stateless as before). ---
    # Under docker compose this is injected from the stack's own `db` service and
    # is never an external host — see docker-compose.yml.
    database_url: str = ""
    # This stack's Postgres serves no TLS cert, so compose sets DATABASE_SSL=false.
    # The default stays True for any host that does demand TLS.
    database_ssl: bool = True

    # --- Usage limits (protect the shared free quota) ---
    max_sessions_per_day: int = 20      # per user; resets daily
    conversation_max_turns: int = 40    # free chat gently wraps up
    interview_max_turns: int = 15       # hard cap (interview self-ends ~8)

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def providers(self) -> list[dict]:
        """Active providers in fallback order. Each: name, base_url, key,
        models (tried in order), headers, extra (per-provider request body)."""
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
                "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
                "headers": {},
                "extra": {},
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
                "key": k["groq"], "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
                "headers": {}, "extra": {}})
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
