from __future__ import annotations

import shutil
from pathlib import Path

from .. import db
from ..config import SECRETS_DIR, get_settings

KIND_CLOUDFLARE = "cloudflare"
KIND_GOOGLE_CREDENTIALS = "google_credentials"
KIND_GOOGLE_SITE = "google_site_token"
KIND_GOOGLE_POSTMASTER = "google_postmaster_token"


def user_secrets_dir(user_id: int) -> Path:
    path = SECRETS_DIR / "users" / str(int(user_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cloudflare_token_path(user_id: int) -> Path:
    return user_secrets_dir(user_id) / "cloudflare.token"


def google_credentials_path(user_id: int) -> Path:
    path = user_secrets_dir(user_id) / "credentials.json"
    _hydrate_file(user_id, KIND_GOOGLE_CREDENTIALS, path)
    return path


def google_token_path(user_id: int, kind: str) -> Path:
    secret_kind = KIND_GOOGLE_POSTMASTER if kind == "postmaster" else KIND_GOOGLE_SITE
    path = user_secrets_dir(user_id) / (
        "token_postmaster.json" if kind == "postmaster" else "token_site.json"
    )
    _hydrate_file(user_id, secret_kind, path)
    return path


def _hydrate_file(user_id: int, kind: str, path: Path) -> None:
    """If the DB has a secret and the file is missing, restore the file."""
    if path.exists() and path.stat().st_size > 0:
        return
    payload = db.get_user_secret(user_id, kind)
    if not payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _persist(user_id: int, kind: str, path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    db.upsert_user_secret(user_id, kind, payload)


def read_cloudflare_token(user_id: int) -> str:
    stored = db.get_user_secret(user_id, KIND_CLOUDFLARE)
    if stored:
        path = cloudflare_token_path(user_id)
        if not path.exists():
            path.write_text(stored, encoding="utf-8")
        return stored.strip()
    path = cloudflare_token_path(user_id)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            db.upsert_user_secret(user_id, KIND_CLOUDFLARE, token)
            return token
    return (get_settings().cloudflare_api_token or "").strip()


def write_cloudflare_token(user_id: int, token: str) -> None:
    _persist(user_id, KIND_CLOUDFLARE, cloudflare_token_path(user_id), token.strip())


def save_google_credentials_text(user_id: int, content: str) -> None:
    _persist(user_id, KIND_GOOGLE_CREDENTIALS, user_secrets_dir(user_id) / "credentials.json", content)


def save_google_token_text(user_id: int, kind: str, content: str) -> None:
    secret_kind = KIND_GOOGLE_POSTMASTER if kind == "postmaster" else KIND_GOOGLE_SITE
    path = user_secrets_dir(user_id) / (
        "token_postmaster.json" if kind == "postmaster" else "token_site.json"
    )
    _persist(user_id, secret_kind, path, content)


def migrate_legacy_secrets_for_user(user_id: int) -> None:
    """Copy old global secret files into this user's folder/DB once, if empty."""
    settings = get_settings()
    dest_creds = user_secrets_dir(user_id) / "credentials.json"
    if not db.get_user_secret(user_id, KIND_GOOGLE_CREDENTIALS):
        src = Path(settings.google_credentials_file)
        if dest_creds.exists():
            save_google_credentials_text(user_id, dest_creds.read_text(encoding="utf-8"))
        elif src.exists():
            shutil.copy2(src, dest_creds)
            save_google_credentials_text(user_id, dest_creds.read_text(encoding="utf-8"))

    dest_site = user_secrets_dir(user_id) / "token_site.json"
    if not db.get_user_secret(user_id, KIND_GOOGLE_SITE):
        src = Path(settings.google_token_file)
        if dest_site.exists():
            save_google_token_text(user_id, "site", dest_site.read_text(encoding="utf-8"))
        elif src.exists():
            shutil.copy2(src, dest_site)
            save_google_token_text(user_id, "site", dest_site.read_text(encoding="utf-8"))

    dest_pm = user_secrets_dir(user_id) / "token_postmaster.json"
    if not db.get_user_secret(user_id, KIND_GOOGLE_POSTMASTER):
        src = Path(settings.google_postmaster_token_file)
        if dest_pm.exists():
            save_google_token_text(user_id, "postmaster", dest_pm.read_text(encoding="utf-8"))
        elif src.exists():
            shutil.copy2(src, dest_pm)
            save_google_token_text(user_id, "postmaster", dest_pm.read_text(encoding="utf-8"))

    dest_cf = cloudflare_token_path(user_id)
    if not db.get_user_secret(user_id, KIND_CLOUDFLARE):
        if dest_cf.exists():
            write_cloudflare_token(user_id, dest_cf.read_text(encoding="utf-8"))
        else:
            token = (settings.cloudflare_api_token or "").strip()
            if token:
                write_cloudflare_token(user_id, token)
