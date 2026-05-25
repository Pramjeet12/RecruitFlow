from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env going up from this file: backend/config/ → backend/ → recruitflow/
_HERE = Path(__file__).resolve().parent
_ENV_CANDIDATES = [
    _HERE.parent / ".env",          # backend/.env  (local dev)
    _HERE.parent.parent / ".env",   # recruitflow/.env  (docker / root)
]
_ENV_FILE = next((str(p) for p in _ENV_CANDIDATES if p.exists()), ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Database
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USERNAME: str = "root"
    POSTGRES_PASSWORD: str = "root"
    POSTGRES_DATABASE: str = "recruitflow"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # Worker
    WORKER_BATCH_SIZE: int = 2
    LINK_FETCH_MAX_CHARS: int = 1000
    LINK_FETCH_TIMEOUT_SECS: int = 10

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Gmail
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # Assessment / Realtime
    BASE_URL: str = "http://localhost:8000"
    OPENAI_REALTIME_MODEL: str = "gpt-realtime-1.5"

    # App
    ENV: str = "dev"
    LOG_LEVEL: str = "INFO"
    TOP_K_OPTIONS: list[int] = [5, 10, 15, 20, 25, 30]

    @property
    def database_url(self) -> str:
        import urllib.parse
        pw = urllib.parse.quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql://{self.POSTGRES_USERNAME}:{pw}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"
        )

    @property
    def database_migration_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
