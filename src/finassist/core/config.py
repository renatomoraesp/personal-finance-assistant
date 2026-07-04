from functools import lru_cache
from typing import Annotated, Literal

from pydantic import PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://finassist:finassist@localhost:5432/finassist"
    )
    telegram_bot_token: SecretStr
    telegram_polling_enabled: bool = True
    # NoDecode: keep pydantic-settings from JSON-decoding env values so the
    # comma-separated validators below receive the raw string.
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = []
    pluggy_client_id: str
    pluggy_client_secret: SecretStr
    pluggy_item_ids: Annotated[list[str], NoDecode] = []
    pluggy_base_url: str = "https://api.pluggy.ai"
    openrouter_api_key: SecretStr
    openrouter_model: str = "google/gemma-4-26b-a4b-it"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    sync_max_age_minutes: int = 10
    sync_initial_lookback_days: int = 90
    sync_overlap_days: int = 7
    sync_refresh_timeout_seconds: int = 90
    sync_refresh_poll_seconds: float = 2.0
    agent_max_tool_rounds: int = 6
    agent_history_limit: int = 20
    agent_temperature: float = 0.4
    timezone: str = "America/Sao_Paulo"

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_int_list(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value

    @field_validator("pluggy_item_ids", mode="before")
    @classmethod
    def parse_str_list(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                return []
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
