from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "PersonaArena"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/persona_arena"

    # LLM provider configuration
    LLM_PROVIDER: str = "gemini"  # Changeable: openai, gemini, etc.
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gemini-1.5-pro"
    LLM_BASE_URL: str = ""

    # Debate generation settings.
    # Every participant in a debate uses these identical values — the only
    # difference between two agents is persona + position + context.
    DEBATE_TEMPERATURE: float = 0.8
    DEBATE_TOP_P: float = 1.0
    DEBATE_MAX_TOKENS: int = 500

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
    LLM_MAX_RETRIES: int = 4
    LLM_BACKOFF_BASE: float = 2.0
    LLM_MAX_BACKOFF: float = 60.0

    # CORS — comma-separated list of allowed frontend origins.
    CORS_ORIGINS: str = "http://localhost:5173"

    SQL_ECHO: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

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
        env_file = "../.env"
        extra = "ignore"


settings = Settings()
