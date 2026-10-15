from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://relay_app:relay-app-password@localhost:5433/relay"
    warehouse_url: str = "postgresql+psycopg://relay_app:relay-app-password@localhost:5433/warehouse"

    kestra_url: str = "http://localhost:8080"
    kestra_tenant: str = "main"
    kestra_user: str = "admin@relay.dev"
    kestra_password: str = "RelayAdmin2026"

    gemini_api_key: str = ""
    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_smart: str = "gemini-2.5-pro"
    gemini_embed_model: str = "gemini-embedding-001"
    google_cloud_project: str = ""
    google_cloud_location: str = "asia-south1"

    relay_secret: str = "change-me-to-a-long-random-string"
    relay_ingest_token: str = "change-me-ingest-token"

    github_token: str = ""
    github_repo: str = ""

    pipelines_dir: str = "/app/pipelines"
    kestra_flows_dir: str = "/app/kestra_flows"
    api_internal_url: str = "http://api:8000"

    embed_dim: int = 768


@lru_cache
def get_settings() -> Settings:
    return Settings()
