from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./chapashop.db"
    secret_key: str = "dev-insecure-key"
    bot_token: str = ""
    webhook_secret: str = ""
    public_url: str = "http://localhost:8000"
    admin_username: str = "owner"
    admin_password: str = ""

    @property
    def db_url(self) -> str:
        # Render выдаёт postgres://, SQLAlchemy ждёт postgresql://
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url

    def secrets_status(self) -> dict:
        """Только факт настройки секрета, без значений."""
        return {
            "BOT_TOKEN": bool(self.bot_token),
            "WEBHOOK_SECRET": bool(self.webhook_secret),
            "SECRET_KEY": self.secret_key not in ("", "dev-insecure-key"),
            "ADMIN_PASSWORD": bool(self.admin_password),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
