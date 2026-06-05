from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENTSEE_", extra="ignore")

    environment: str = "dev"
    redis_url: str = "redis://localhost:6379/0"
    redis_required: bool = False

    audit_stream: str = "agentsee:audit:requests"
    report_stream: str = "agentsee:report:requests"

    service_name: str = "agentsee-api"
    component_version: str = "v1"


settings = Settings()
