import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


def resolve_data_dir() -> Path:
    """Use DATA_DIR env when set (Render disk, Docker volume). Else ./data."""
    override = os.environ.get("DATA_DIR", "").strip()
    path = Path(override).expanduser() if override else ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    (path / "secrets").mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = resolve_data_dir()
SECRETS_DIR = DATA_DIR / "secrets"
DB_PATH = DATA_DIR / "postmaster.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dashboard_password: str = "change-me"
    super_username: str = "admin"
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


def is_placeholder_public_url(url: str) -> bool:
    text = (url or "").strip().lower()
    return (
        not text
        or "localhost" in text
        or "127.0.0.1" in text
        or "0.0.0.0" in text
        or text.rstrip("/") in ("https://temp", "http://temp")
    )


def public_base_from_request(request) -> str:
    """Prefer a real PUBLIC_BASE_URL; otherwise use the host the user opened."""
    configured = (get_settings().public_base_url or "").rstrip("/")
    if configured and not is_placeholder_public_url(configured):
        return configured
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc or "").split(",")[0].strip()
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def persist_public_base_url(url: str) -> None:
    """Remember a live public URL so later OAuth/jobs do not fall back to localhost."""
    url = (url or "").rstrip("/")
    if is_placeholder_public_url(url):
        return
    os.environ["PUBLIC_BASE_URL"] = url
    get_settings.cache_clear()
    runtime = SECRETS_DIR / "runtime.env"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if runtime.exists():
        lines = [
            ln
            for ln in runtime.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("PUBLIC_BASE_URL=")
        ]
    lines.append(f"PUBLIC_BASE_URL={url}")
    runtime.write_text("\n".join(lines) + "\n", encoding="utf-8")
