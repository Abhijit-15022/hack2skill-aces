from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://relay_app:relay-app-password@localhost:5433/relay"
    warehouse_url: str = "postgresql+psycopg://relay_app:relay-app-password@localhost:5433/warehouse"

    gemini_api_key: str = ""
    gemini_model_smart: str = "gemini-3.8-flash"
    gemini_thinking_smart: str = "high"
    gemini_thinking_meeting: str = "medium"
    gemini_model_fast: str = "gemini-3.8-flash"
    gemini_thinking_fast: str = "low"
    gemini_model_lite: str = "gemini-3.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"
    google_cloud_project: str = ""
    google_cloud_location: str = "asia-south1"

    relay_secret: str = "change-me-to-a-long-random-string"
    relay_ingest_token: str = "change-me-ingest-token"

    github_token: str = ""
    github_repo: str = ""

    pipelines_dir: str = "/app/pipelines"

    embed_dim: int = 768
    timezone: str = "Asia/Kolkata"
    data_dir: str = "/app/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
