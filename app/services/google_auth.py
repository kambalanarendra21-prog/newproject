from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from ..config import get_settings

SITE_SCOPES = ["https://www.googleapis.com/auth/siteverification"]
POSTMASTER_SCOPES = [
    "https://www.googleapis.com/auth/postmaster",
    "https://www.googleapis.com/auth/postmaster.readonly",
    "https://www.googleapis.com/auth/siteverification",
]


def credentials_file_exists() -> bool:
    return Path(get_settings().google_credentials_file).exists()


def token_path(kind: str) -> Path:
    settings = get_settings()
    if kind == "postmaster":
        return Path(settings.google_postmaster_token_file)
    return Path(settings.google_token_file)


def token_exists(kind: str) -> bool:
    return token_path(kind).exists()


def _scopes(kind: str) -> list[str]:
    return POSTMASTER_SCOPES if kind == "postmaster" else SITE_SCOPES


def load_credentials(kind: str = "site") -> Credentials:
    path = token_path(kind)
    if not path.exists():
        raise RuntimeError(
            f"Google {kind} token missing. Complete OAuth from Settings first."
        )
    creds = Credentials.from_authorized_user_file(str(path), _scopes(kind))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError(f"Google {kind} credentials are invalid. Re-authorize.")
    return creds


def build_flow(kind: str) -> Flow:
    settings = get_settings()
    creds_path = Path(settings.google_credentials_file)
    if not creds_path.exists():
        raise RuntimeError("Upload Google OAuth credentials.json in Settings first.")

    # Support both "installed" and "web" client types by normalizing to web flow.
    raw = json.loads(creds_path.read_text(encoding="utf-8"))
    if "installed" in raw and "web" not in raw:
        data = {"web": raw["installed"]}
        # Temporary normalized file for Flow
        normalized = creds_path.parent / f"credentials_{kind}_web.json"
        # Ensure redirect URIs include our callback
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
    flow = Flow.from_client_secrets_file(
        client_config_path,
        scopes=_scopes(kind),
        redirect_uri=redirect_uri,
    )
    return flow


def authorization_url(kind: str, state: str) -> str:
    flow = build_flow(kind)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(kind: str, code: str) -> None:
    flow = build_flow(kind)
    flow.fetch_token(code=code)
    creds = flow.credentials
    path = token_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")


def save_uploaded_credentials(content: bytes) -> None:
    settings = get_settings()
    path = Path(settings.google_credentials_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Validate JSON shape
    data = json.loads(content.decode("utf-8"))
    if "installed" not in data and "web" not in data:
        raise ValueError("Invalid credentials.json: expected 'installed' or 'web' key")
    path.write_bytes(content)
