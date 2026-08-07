from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PersonaArena"
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/persona_arena"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    
    class Config:
        env_file = ".env"

settings = Settings()
