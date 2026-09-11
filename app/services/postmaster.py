from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import google_auth


def build_service(user_id: int):
    creds = google_auth.load_credentials(user_id, "postmaster")
    return build("gmailpostmastertools", "v2", credentials=creds, cache_discovery=False)


def list_domains(user_id: int) -> list[str]:
    service = build_service(user_id)
    domains: list[str] = []
    page_token = None
    while True:
        request = service.domains().list(pageSize=100, pageToken=page_token)
        response = request.execute()
        for item in response.get("domains", []):
            name = item.get("name", "").replace("domains/", "").strip().lower()
            if name:
                domains.append(name)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return domains


def register_domain(user_id: int, domain: str) -> str:
    service = build_service(user_id)
    try:
        service.domains().create(body={"name": f"domains/{domain}"}).execute()
        return "created"
    except HttpError as exc:
        if exc.resp.status == 409 or "already exists" in str(exc).lower():
            return "exists"
        raise


def verify_domain(user_id: int, domain: str) -> None:
    service = build_service(user_id)
    service.domains().verify(name=f"domains/{domain}").execute()
