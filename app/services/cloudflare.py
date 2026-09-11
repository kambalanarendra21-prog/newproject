from __future__ import annotations

import httpx

from ..config import get_settings

API = "https://api.cloudflare.com/client/v4"


def _headers() -> dict[str, str]:
    token = get_settings().cloudflare_api_token
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def get_zone_id(domain: str) -> str | None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{API}/zones",
            params={"name": domain},
            headers=_headers(),
        )
        data = resp.json()
        if data.get("success") and data.get("result"):
            return data["result"][0]["id"]
    return None


async def create_txt_record(zone_id: str, txt_value: str) -> bool:
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
            headers=_headers(),
        )
        listed_data = listed.json()
        if listed_data.get("success"):
            for rec in listed_data.get("result", []):
                if rec.get("content") == txt_value:
                    return True

        resp = await client.post(
            f"{API}/zones/{zone_id}/dns_records",
            headers=_headers(),
            json=payload,
        )
        data = resp.json()
        return bool(data.get("success"))
