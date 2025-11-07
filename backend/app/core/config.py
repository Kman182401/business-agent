from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    DATABASE_URL: str  # e.g. postgresql+asyncpg://app_user:***@localhost:5432/frontdesk
    REDIS_URL: str     # e.g. redis://localhost:6379/0

    # Twilio webhook / Media Streams + OpenAI Realtime bridge
    TWILIO_AUTH_TOKEN: str | None = None
    PUBLIC_BASE_URL: str | None = None  # e.g., https://<subdomain>.ngrok-free.dev
    REALTIME_MODEL: str = "gpt-4o-realtime"
    OPENAI_API_KEY: str | None = None

    API_PREFIX: str = "/api/v1"

    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
