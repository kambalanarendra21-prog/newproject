from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError, UnknownApiNameOrVersion

from . import google_auth

# v2 is not published on Google's central discovery catalog
# (www.googleapis.com/discovery/v1/...), so build() 404s with
# "name: gmailpostmastertools version: v2" unless we load it here.
POSTMASTER_API_NAME = "gmailpostmastertools"
POSTMASTER_API_VERSION = "v2"
POSTMASTER_DISCOVERY_URL = (
    "https://gmailpostmastertools.googleapis.com/$discovery/rest?version=v2"
)


def build_service(user_id: int):
    creds = google_auth.load_credentials(user_id, "postmaster")
    try:
        return build(
            POSTMASTER_API_NAME,
            POSTMASTER_API_VERSION,
            credentials=creds,
            cache_discovery=False,
            discoveryServiceUrl=POSTMASTER_DISCOVERY_URL,
        )
    except UnknownApiNameOrVersion as exc:
        raise RuntimeError(
            "Could not load Gmail Postmaster Tools API v2. "
            "Enable the API in Google Cloud, wait a few minutes, then retry. "
            f"({exc})"
        ) from exc


def _domain_from_resource(name: str) -> str:
    return name.replace("domains/", "", 1).strip().lower()


def list_domains(user_id: int) -> list[str]:
    service = build_service(user_id)
    domains: list[str] = []
    page_token = None
    try:
        while True:
            request = service.domains().list(pageSize=100, pageToken=page_token)
            response = request.execute()
            for item in response.get("domains", []):
                name = _domain_from_resource(item.get("name") or "")
                if name:
                    domains.append(name)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    return domains


def register_domain(user_id: int, domain: str) -> str:
    service = build_service(user_id)
    try:
        service.domains().create(body={"domainId": domain}).execute()
        return "created"
    except HttpError as exc:
        text = str(exc).lower()
        if exc.resp.status == 409 or "already exists" in text or "already_exists" in text:
            return "exists"
        raise RuntimeError(_http_error_message(exc)) from exc


def verify_domain(user_id: int, domain: str) -> None:
    service = build_service(user_id)
    try:
        service.domains().verify(
            name=f"domains/{domain}",
            body={"verificationMethod": "TXT"},
        ).execute()
    except HttpError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc


def _http_error_message(exc: HttpError) -> str:
    raw = str(exc)
    if "accessNotConfigured" in raw or "has not been used" in raw:
        return (
            "Gmail Postmaster Tools API is disabled in this Google Cloud project. "
            "Enable it, wait a few minutes, then retry."
        )
    if "insufficientPermissions" in raw or "insufficient authentication scopes" in raw.lower():
        return "Postmaster OAuth is missing permission. Re-authorize Postmaster in Settings."
    return raw
