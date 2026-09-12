from __future__ import annotations

import httpx

from . import user_secrets

API = "https://api.cloudflare.com/client/v4"


def _headers(user_id: int) -> dict[str, str]:
    token = user_secrets.read_cloudflare_token(user_id)
    if not token:
        raise RuntimeError("Cloudflare API token is not configured in your Settings")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def get_zone_id(user_id: int, domain: str) -> str | None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{API}/zones",
            params={"name": domain},
            headers=_headers(user_id),
        )
        data = resp.json()
        if data.get("success") and data.get("result"):
            return data["result"][0]["id"]
    return None


async def create_txt_record(user_id: int, zone_id: str, txt_value: str) -> bool:
    payload = {
        "type": "TXT",
        "name": "@",
        "content": txt_value,
        "ttl": 120,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        listed = await client.get(
            f"{API}/zones/{zone_id}/dns_records",
            params={"type": "TXT", "per_page": 100},
            headers=_headers(user_id),
        )
        listed_data = listed.json()
        if listed_data.get("success"):
            for rec in listed_data.get("result", []):
                if rec.get("content") == txt_value:
                    return True

        resp = await client.post(
            f"{API}/zones/{zone_id}/dns_records",
            headers=_headers(user_id),
            json=payload,
        )
        data = resp.json()
        return bool(data.get("success"))
