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

