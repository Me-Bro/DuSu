from pydantic_settings import BaseSettings, SettingsConfigDict


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
                # only. gpt-oss-*:free were dropped from the free tier (404).
                "models": ["z-ai/glm-5.2:free", "google/gemma-4-31b-it:free"],
                "headers": {"HTTP-Referer": "https://dusu-app-1.onrender.com", "X-Title": "DuSu"},
                "extra": {"reasoning": {"exclude": True, "effort": "low"}},
            })
        if self.github_token:
            chain.append({
                "name": "github",
                # LAST: GitHub Models is in a retirement brownout (410 on every call).
                # Kept only so the chain still has a tail if it comes back.
                "base_url": "https://models.github.ai/inference",
                "key": self.github_token,
                "models": ["openai/gpt-4o-mini"],
                "headers": {},
                "extra": {},
            })
        return chain

    def providers_from(self, keys: dict) -> list[dict]:
        """BYOK / Office mode: build a chain from caller-supplied keys.
        Same base_urls / models / headers / order as providers(); only the key
        differs. Missing keys are skipped. keys = {gemini, groq, openrouter, github}."""
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
                "models": ["z-ai/glm-5.2:free", "google/gemma-4-31b-it:free"],
                "headers": {"HTTP-Referer": "https://dusu-app-1.onrender.com", "X-Title": "DuSu"},
                "extra": {"reasoning": {"exclude": True, "effort": "low"}}})
        if k.get("github"):
            chain.append({"name": "github", "base_url": "https://models.github.ai/inference",
                "key": k["github"], "models": ["openai/gpt-4o-mini"],
                "headers": {}, "extra": {}})
        return chain


settings = Settings()
