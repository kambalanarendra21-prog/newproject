from __future__ import annotations

import shutil
from pathlib import Path

from ..config import SECRETS_DIR, get_settings


def user_secrets_dir(user_id: int) -> Path:
    path = SECRETS_DIR / "users" / str(int(user_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cloudflare_token_path(user_id: int) -> Path:
    return user_secrets_dir(user_id) / "cloudflare.token"


def google_credentials_path(user_id: int) -> Path:
    return user_secrets_dir(user_id) / "credentials.json"


def google_token_path(user_id: int, kind: str) -> Path:
    if kind == "postmaster":
        return user_secrets_dir(user_id) / "token_postmaster.json"
    return user_secrets_dir(user_id) / "token_site.json"


def read_cloudflare_token(user_id: int) -> str:
    path = cloudflare_token_path(user_id)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    # Legacy fallback: shared env/runtime token (pre per-user settings)
    return (get_settings().cloudflare_api_token or "").strip()


def write_cloudflare_token(user_id: int, token: str) -> None:
    path = cloudflare_token_path(user_id)
    path.write_text(token.strip(), encoding="utf-8")


def migrate_legacy_secrets_for_user(user_id: int) -> None:
    """Copy old global secret files into this user's folder once, if empty."""
    settings = get_settings()
    dest_creds = google_credentials_path(user_id)
    if not dest_creds.exists():
        src = Path(settings.google_credentials_file)
        if src.exists():
            shutil.copy2(src, dest_creds)

    dest_site = google_token_path(user_id, "site")
    if not dest_site.exists():
        src = Path(settings.google_token_file)
        if src.exists():
            shutil.copy2(src, dest_site)

    dest_pm = google_token_path(user_id, "postmaster")
    if not dest_pm.exists():
        src = Path(settings.google_postmaster_token_file)
        if src.exists():
            shutil.copy2(src, dest_pm)

    dest_cf = cloudflare_token_path(user_id)
    if not dest_cf.exists():
        token = (settings.cloudflare_api_token or "").strip()
        if token:
            dest_cf.write_text(token, encoding="utf-8")
