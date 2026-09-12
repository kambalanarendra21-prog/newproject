from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from ..config import get_settings
from . import user_secrets

SITE_SCOPE = "https://www.googleapis.com/auth/siteverification"
POSTMASTER_SCOPE = "https://www.googleapis.com/auth/postmaster"
POSTMASTER_READONLY_SCOPE = "https://www.googleapis.com/auth/postmaster.readonly"

SITE_SCOPES = [SITE_SCOPE]
POSTMASTER_SCOPES = [
    POSTMASTER_SCOPE,
    POSTMASTER_READONLY_SCOPE,
    SITE_SCOPE,
]
ALL_SCOPES = POSTMASTER_SCOPES


def _scopes(kind: str) -> list[str]:
    return POSTMASTER_SCOPES if kind == "postmaster" else SITE_SCOPES


@contextmanager
def _relax_token_scope():
    """Google may return extra previously granted scopes; do not fail the login."""
    key = "OAUTHLIB_RELAX_TOKEN_SCOPE"
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


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


def _callback_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/oauth/callback"


def build_flow(user_id: int, kind: str, public_base_url: str | None = None) -> Flow:
    settings = get_settings()
    base = (public_base_url or settings.public_base_url).rstrip("/")
    creds_path = user_secrets.google_credentials_path(user_id)
    user_secrets.migrate_legacy_secrets_for_user(user_id)
    if not creds_path.exists():
        raise RuntimeError("Upload Google OAuth credentials.json in Settings first.")

    raw = json.loads(creds_path.read_text(encoding="utf-8"))
    callback = _callback_url(base)
    if "installed" in raw and "web" not in raw:
        data = {"web": raw["installed"]}
        normalized = creds_path.parent / f"credentials_{kind}_web.json"
        redirects = list(data["web"].get("redirect_uris") or [])
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

    return Flow.from_client_secrets_file(
        client_config_path,
        scopes=ALL_SCOPES,
        redirect_uri=callback,
    )


def authorization_url(user_id: int, kind: str, state: str, public_base_url: str | None = None) -> str:
    flow = build_flow(user_id, kind, public_base_url=public_base_url)
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    return url


def _granted_scopes(creds: Credentials) -> set[str]:
    return {scope for scope in (creds.scopes or []) if scope}


def _save_tokens_from_grant(user_id: int, kind: str, creds: Credentials) -> None:
    payload = creds.to_json()
    user_secrets.save_google_token_text(user_id, kind, payload)
    granted = _granted_scopes(creds)
    if SITE_SCOPE in granted:
        user_secrets.save_google_token_text(user_id, "site", payload)
    if POSTMASTER_SCOPE in granted or POSTMASTER_READONLY_SCOPE in granted:
        user_secrets.save_google_token_text(user_id, "postmaster", payload)


def exchange_code(user_id: int, kind: str, code: str, public_base_url: str | None = None) -> None:
    flow = build_flow(user_id, kind, public_base_url=public_base_url)
    with _relax_token_scope():
        flow.fetch_token(code=code)
    _save_tokens_from_grant(user_id, kind, flow.credentials)


def save_uploaded_credentials(user_id: int, content: bytes) -> None:
    data = json.loads(content.decode("utf-8"))
    if "installed" not in data and "web" not in data:
        raise ValueError("Invalid credentials.json: expected 'installed' or 'web' key")
    user_secrets.save_google_credentials_text(user_id, content.decode("utf-8"))


def credentials_info(user_id: int) -> dict:
    """Describe the uploaded OAuth client so Settings can warn about mismatches."""
    path = user_secrets.google_credentials_path(user_id)
    if not path.exists():
        return {"client_type": None, "redirect_uris": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "web" in raw:
        block = raw["web"]
        client_type = "web"
    elif "installed" in raw:
        block = raw["installed"]
        client_type = "installed"
    else:
        return {"client_type": None, "redirect_uris": []}
    return {
        "client_type": client_type,
        "redirect_uris": list(block.get("redirect_uris") or []),
    }


def require_web_client(user_id: int) -> None:
    info = credentials_info(user_id)
    if info["client_type"] == "installed":
        raise RuntimeError(
            "This credentials.json is a Desktop app. Create a Web application "
            "OAuth client in Google Cloud, add the callback URL shown in Settings, "
            "then upload that new JSON."
        )
