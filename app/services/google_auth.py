from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from ..config import get_settings
from . import user_secrets

SITE_SCOPES = ["https://www.googleapis.com/auth/siteverification"]
POSTMASTER_SCOPES = [
    "https://www.googleapis.com/auth/postmaster",
    "https://www.googleapis.com/auth/postmaster.readonly",
    "https://www.googleapis.com/auth/siteverification",
]


def _scopes(kind: str) -> list[str]:
    return POSTMASTER_SCOPES if kind == "postmaster" else SITE_SCOPES


def credentials_file_exists(user_id: int) -> bool:
    user_secrets.migrate_legacy_secrets_for_user(user_id)
    return user_secrets.google_credentials_path(user_id).exists()


def token_path(user_id: int, kind: str) -> Path:
    user_secrets.migrate_legacy_secrets_for_user(user_id)
    return user_secrets.google_token_path(user_id, kind)


def token_exists(user_id: int, kind: str) -> bool:
    return token_path(user_id, kind).exists()


def load_credentials(user_id: int, kind: str = "site") -> Credentials:
    path = token_path(user_id, kind)
    if not path.exists():
        raise RuntimeError(
            f"Google {kind} token missing. Complete OAuth from Settings first."
        )
    creds = Credentials.from_authorized_user_file(str(path), _scopes(kind))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        user_secrets.save_google_token_text(user_id, kind, creds.to_json())
    if not creds.valid:
        raise RuntimeError(f"Google {kind} credentials are invalid. Re-authorize.")
    return creds


def build_flow(user_id: int, kind: str) -> Flow:
    settings = get_settings()
    creds_path = user_secrets.google_credentials_path(user_id)
    user_secrets.migrate_legacy_secrets_for_user(user_id)
    if not creds_path.exists():
        raise RuntimeError("Upload Google OAuth credentials.json in Settings first.")

    # Support both "installed" and "web" client types by normalizing to web flow.
    raw = json.loads(creds_path.read_text(encoding="utf-8"))
    if "installed" in raw and "web" not in raw:
        data = {"web": raw["installed"]}
        normalized = creds_path.parent / f"credentials_{kind}_web.json"
        redirects = list(data["web"].get("redirect_uris") or [])
        callback = f"{settings.public_base_url.rstrip('/')}/oauth/callback"
        if callback not in redirects:
            redirects.append(callback)
        data["web"]["redirect_uris"] = redirects
        if not data["web"].get("auth_uri"):
            data["web"]["auth_uri"] = "https://accounts.google.com/o/oauth2/auth"
        if not data["web"].get("token_uri"):
            data["web"]["token_uri"] = "https://oauth2.googleapis.com/token"
        normalized.write_text(json.dumps(data), encoding="utf-8")
        client_config_path = str(normalized)
    else:
        client_config_path = str(creds_path)

    redirect_uri = f"{settings.public_base_url.rstrip('/')}/oauth/callback"
    return Flow.from_client_secrets_file(
        client_config_path,
        scopes=_scopes(kind),
        redirect_uri=redirect_uri,
    )


def authorization_url(user_id: int, kind: str, state: str) -> str:
    flow = build_flow(user_id, kind)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(user_id: int, kind: str, code: str) -> None:
    flow = build_flow(user_id, kind)
    flow.fetch_token(code=code)
    creds = flow.credentials
    user_secrets.save_google_token_text(user_id, kind, creds.to_json())


def save_uploaded_credentials(user_id: int, content: bytes) -> None:
    data = json.loads(content.decode("utf-8"))
    if "installed" not in data and "web" not in data:
        raise ValueError("Invalid credentials.json: expected 'installed' or 'web' key")
    user_secrets.save_google_credentials_text(user_id, content.decode("utf-8"))
