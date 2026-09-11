from __future__ import annotations

import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import google_auth


def build_service():
    creds = google_auth.load_credentials("site")
    return build("siteVerification", "v1", credentials=creds, cache_discovery=False)


def get_txt_token(service, domain: str, max_retries: int = 5) -> str:
    body = {
        "verificationMethod": "DNS_TXT",
        "site": {"type": "INET_DOMAIN", "identifier": domain},
    }
    delay = 2
    for _ in range(max_retries):
        try:
            response = service.webResource().getToken(body=body).execute()
            token = response.get("token")
            if not token:
                raise RuntimeError("Empty token from Google")
            return token
        except HttpError as exc:
            if exc.resp.status in (429, 403) and "rateLimitExceeded" in str(exc):
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("Max retries exceeded due to rate limits")


def verify_domain(service, domain: str) -> None:
    body = {"site": {"type": "INET_DOMAIN", "identifier": domain}}
    service.webResource().insert(verificationMethod="DNS_TXT", body=body).execute()


def list_verified_domains(service) -> list[str]:
    response = service.webResource().list().execute()
    out = []
    for item in response.get("items", []):
        identifier = item.get("site", {}).get("identifier", "").strip().lower()
        if identifier:
            out.append(identifier)
    return out
