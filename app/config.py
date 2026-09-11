from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_DIR = DATA_DIR / "secrets"
DB_PATH = DATA_DIR / "postmaster.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dashboard_password: str = "change-me"
    secret_key: str = "dev-secret-change-me"
    host: str = "0.0.0.0"
    port: int = 8080
    cloudflare_api_token: str = ""
    google_credentials_file: str = str(SECRETS_DIR / "credentials.json")
    google_token_file: str = str(SECRETS_DIR / "token.json")
    google_postmaster_token_file: str = str(SECRETS_DIR / "token_postmaster.json")
    public_base_url: str = "http://localhost:8080"
    admin_name: str = "Admin"


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
