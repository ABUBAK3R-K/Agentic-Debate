from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import field_validator

# The repo root, found from this file rather than from the working directory.
# `env_file` is resolved relative to the *cwd*, so a relative "../.env" only
# works when the process happens to be started from `backend/`. Started from
# the repo root instead, it silently matches nothing: no API key, and the
# field defaults (gemini-1.5-pro, max_tokens 500) stand in for the tuned
# config with no error anywhere. Anchoring it to this file makes the same
# `.env` load from any working directory.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    PROJECT_NAME: str = "PersonaArena"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/persona_arena"

    # LLM provider configuration
    LLM_PROVIDER: str = "gemini"  # Changeable: openai, gemini, etc.
    LLM_API_KEY: str = ""
    # gemini-1.5-pro is retired (404), and the 2.5 models are closed to new
    # keys. 3.5-flash-lite is current and does not think by default.
    LLM_MODEL: str = "gemini-3.5-flash-lite"
    LLM_BASE_URL: str = ""

    # How hard a reasoning model may think before it answers ("low", "medium",
    # "high"). Hidden reasoning is billed against the same tokens-per-minute
    # ceiling as the answer and is several times its size on a debate turn, so
    # this is the largest single lever on how long a debate spends waiting out
    # rate limits. Empty means the setting is not sent at all, which is what a
    # model without one requires.
    LLM_REASONING_EFFORT: str = ""

    # Gemini's equivalent, spelled as a token budget rather than a level. Only
    # sent when set, because the model generations disagree about it: 2.5
    # takes `thinkingBudget`, and 3.5-flash-lite answers `thinkingBudget: 0`
    # with a 400. Prefer GEMINI_THINKING_LEVEL on any 3.x model. When both are
    # set, the budget wins and the level is not sent.
    GEMINI_THINKING_BUDGET: int | None = None

    # The 3.x spelling: "minimal", "low", "medium" or "high". Measured,
    # 3.5-flash and 3.6-flash DO think by default, and the thinking is billed
    # against maxOutputTokens — a 500-token turn can spend its whole budget
    # thinking and come back with no text at all (finishReason MAX_TOKENS),
    # which is how a debate turn fails intermittently. "minimal" switches
    # that off and is accepted by both the flash and flash-lite 3.x models.
    # Empty means the field is not sent.
    GEMINI_THINKING_LEVEL: str = ""

    # Debate generation settings.
    # Every participant in a debate uses these identical values — the only
    # difference between two agents is persona + position + context.
    DEBATE_TEMPERATURE: float = 0.8
    DEBATE_TOP_P: float = 1.0
    DEBATE_MAX_TOKENS: int = 500

    # The model the judge runs on. Empty means the same one the debaters
    # used, which is the default and always correct.
    #
    # Setting it to a DIFFERENT model buys a second rate-limit budget, on a
    # provider that meters per model as well as per key (Gemini free:
    # GenerateRequestsPerMinutePerProjectPerModel). It moves the judge — the
    # one request in a debate most likely to be refused, because it comes
    # last, when the window is fullest — off the budget the eight turns are
    # competing for.
    #
    # It must be a genuinely different model, not an alias: measured,
    # `gemini-flash-lite-latest` resolves to `gemini-3.5-flash-lite` and
    # shares its bucket, so a split configured that way changes nothing.
    #
    # This does not touch the "identical settings for every participant"
    # rule. The judge is not a participant, and the PRD asks for the
    # opposite: never let one debater's model instance judge the debate.
    JUDGE_MODEL: str = ""

    # Evaluation settings — the judge runs cooler than the debaters so its
    # scoring stays consistent across runs.
    JUDGE_TEMPERATURE: float = 0.3
    JUDGE_MAX_TOKENS: int = 1500

    # Persona compilation runs cooler still; it is extraction, not creation.
    COMPILER_TEMPERATURE: float = 0.4
    COMPILER_MAX_TOKENS: int = 1000

    # Provider pacing. A debate is nine requests back to back, which walks
    # straight into a free tier's per-minute limit unless it is paced.
    # Free Gemini/OpenAI tiers usually want 4-6s; a paid key can use 0.
    LLM_MIN_REQUEST_INTERVAL: float = 4.0

    # Requests allowed per rolling minute, for a provider that meters
    # requests rather than tokens. Gemini's free tier is the case this
    # exists for: it answers a 429 with
    # GenerateRequestsPerMinutePerProjectPerModel-FreeTier, a flat 15 a
    # minute, and sends no rate-limit headers to pace against.
    #
    # Unlike LLM_MIN_REQUEST_INTERVAL this does not slow a burst that fits.
    # A debate is nine requests against a limit of fifteen, so it runs at
    # full speed and only a second debate started inside the same minute
    # waits. 0 disables it.
    LLM_REQUESTS_PER_MINUTE: int = 0
    LLM_MAX_RETRIES: int = 4
    LLM_BACKOFF_BASE: float = 2.0
    LLM_MAX_BACKOFF: float = 60.0

    # How long one call may spend waiting out rate limits, in seconds.
    # A 429 is not a failure the way a timeout is — it is the provider saying
    # when it will be ready — and a tokens-per-minute ceiling can hold a turn
    # back through more than one window. Counting those waits against
    # LLM_MAX_RETRIES would abandon a turn that was only ever going to need
    # another thirty seconds, so they are bounded by total time instead.
    LLM_RATE_LIMIT_BUDGET: float = 180.0

    # CORS — comma-separated list of allowed frontend origins.
    CORS_ORIGINS: str = "http://localhost:5173"

    SQL_ECHO: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @field_validator("GEMINI_THINKING_BUDGET", mode="before")
    @classmethod
    def blank_means_unset(cls, v):
        """`GEMINI_THINKING_BUDGET=` in .env means "don't send the field".

        Without this an empty value is a startup crash, which would make the
        natural way to write "leave thinking alone" the one way to break the
        app — and leaving it alone is correct on every 3.x model.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        if not v or v.startswith("http://") or v.startswith("https://"):
            return "sqlite+aiosqlite:///./persona_arena.db"
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    class Config:
        env_file = ENV_FILE
        extra = "ignore"


settings = Settings()
