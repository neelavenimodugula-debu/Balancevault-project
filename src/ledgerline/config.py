from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LEDGERLINE_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://ledgerline:ledgerline_dev@localhost:5432/ledgerline"
    )
    jwt_secret: SecretStr = SecretStr("local-development-secret-change-before-deploy")
    token_expiry_minutes: int = 30
    environment: str = "development"

    @model_validator(mode="after")
    def require_production_secret(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret.get_secret_value().startswith(
            "local-development-"
        ):
            raise ValueError("Set LEDGERLINE_JWT_SECRET to a private production secret")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()