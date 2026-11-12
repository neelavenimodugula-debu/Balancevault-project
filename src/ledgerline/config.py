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
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: SecretStr = SecretStr("local-development-secret-change-before-deploy")
    token_expiry_minutes: int = 30
    environment: str = "development"
    strict_redis: bool = False
    rate_limit_per_minute: int = 60
    admin_email: str = "admin@ledgerline.local"
    admin_password: SecretStr = SecretStr("AdminInitialPass2026!")
    auditor_email: str | None = None
    auditor_password: SecretStr | None = None
    clearing_account_name: str = "SYSTEM_CLEARING"

    @model_validator(mode="after")
    def validate_and_normalize(self) -> "Settings":
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        if self.environment == "production" and self.jwt_secret.get_secret_value().startswith(
            "local-development-"
        ):
            raise ValueError("Set LEDGERLINE_JWT_SECRET to a private production secret")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
