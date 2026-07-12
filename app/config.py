from functools import lru_cache
from typing import Annotated
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str
    database_ssl: bool = False
    public_base_url: str | None = None

    telegram_bot_token: SecretStr | None = None
    allowed_telegram_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    openai_api_key: SecretStr | None = None
    openai_model: str = ""

    api_secret_key: SecretStr | None = None
    default_currency: str = "EUR"
    default_timezone: str = "Europe/Madrid"
    max_receipt_size_mb: int = 10
    log_level: str = "INFO"

    purchase_min_daily_limit: float = 5.0
    purchase_low_available_threshold: float = 100.0
    purchase_caution_daily_drop_ratio: float = 0.5

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_allowed_ids(cls, value: str | list[int] | None) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        return [int(part.strip()) for part in value.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


AppEnv = Literal["development", "test", "production"]
