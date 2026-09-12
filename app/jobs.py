from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from . import db
from .config import get_settings
from .services import cloudflare, google_auth, postmaster, site_verification, user_secrets

JobRunner = Callable[[int], Awaitable[None]]
_lock = asyncio.Lock()


async def _ensure_idle() -> None:
    running = await db.get_running_job()
    if running:
        raise RuntimeError(f"Job #{running['id']} ({running['job_type']}) is already running")


async def start_job(
    job_type: str,
    runner: JobRunner,
    total: int = 0,
    user_id: int | None = None,
) -> int:
    async with _lock:
        await _ensure_idle()
        job_id = await db.create_job(job_type, total=total, user_id=user_id)

    async def _wrap():
        try:
            await runner(job_id)
        except Exception as exc:  # noqa: BLE001
            await db.append_job_log(job_id, f"Fatal: {exc}", level="error")
            await db.finish_job(job_id, "failed", 0, 1, str(exc))

    asyncio.create_task(_wrap())
    return job_id


async def _user_id_for_job(job_id: int) -> int:
    job = await db.get_job(job_id)
    if not job or not job.get("user_id"):
        raise RuntimeError("Job has no owning user for credentials")
    return int(job["user_id"])


async def _scope_for_job(job_id: int) -> int | None:
    job = await db.get_job(job_id)
    if not job or not job.get("user_id"):
        return None
    user = await db.get_user(int(job["user_id"]))
    if not user or user.get("role") == "super":
        return None
    return int(user["id"])


async def run_fetch_tokens(job_id: int) -> None:
    user_id = await _user_id_for_job(job_id)
    scope = await _scope_for_job(job_id)
    domains = await db.list_domains(owner_id=scope)
    await db.append_job_log(job_id, f"Fetching TXT tokens for {len(domains)} domains")
    success = fail = 0
    service = site_verification.build_service(user_id)
    for i, row in enumerate(domains, 1):
        domain = row["domain"]
        try:
            token = await asyncio.to_thread(site_verification.get_txt_token, service, domain)
            await db.update_domain(domain, txt_record=token, last_error=None)
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] OK {domain}")
            success += 1
        except Exception as exc:  # noqa: BLE001
            await db.update_domain(domain, txt_record=f"ERROR: {exc}", last_error=str(exc))
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] FAIL {domain}: {exc}", "error")
            fail += 1
        await asyncio.sleep(1)
    await db.finish_job(job_id, "completed", success, fail, f"{success} tokens fetched")


async def run_cloudflare_txt(job_id: int) -> None:
    user_id = await _user_id_for_job(job_id)
    if not user_secrets.read_cloudflare_token(user_id):
        raise RuntimeError("Cloudflare API token is not configured in your Settings")
    scope = await _scope_for_job(job_id)
    domains = [
        d
        for d in await db.list_domains(owner_id=scope)
        if d.get("txt_record") and not str(d["txt_record"]).startswith("ERROR")
    ]
    await db.append_job_log(job_id, f"Adding Cloudflare TXT for {len(domains)} domains")
    success = fail = 0
    for i, row in enumerate(domains, 1):
        domain = row["domain"]
        try:
            zone_id = await cloudflare.get_zone_id(user_id, domain)
            if not zone_id:
                raise RuntimeError("Domain not found in this Cloudflare account")
            ok = await cloudflare.create_txt_record(user_id, zone_id, row["txt_record"])
            if not ok:
                raise RuntimeError("Cloudflare API rejected TXT create")
            await db.update_domain(domain, cloudflare_txt_added=1, last_error=None)
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] OK {domain}")
            success += 1
        except Exception as exc:  # noqa: BLE001
            await db.update_domain(domain, last_error=str(exc))
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] FAIL {domain}: {exc}", "error")
            fail += 1
        await asyncio.sleep(0.25)
    await db.finish_job(job_id, "completed", success, fail, f"{success} TXT records added")


async def run_verify_sites(job_id: int) -> None:
    user_id = await _user_id_for_job(job_id)
    scope = await _scope_for_job(job_id)
    domains = await db.list_domains(owner_id=scope)
    await db.append_job_log(job_id, f"Verifying {len(domains)} domains with Google Site Verification")
    success = fail = 0
    service = site_verification.build_service(user_id)
    for i, row in enumerate(domains, 1):
        domain = row["domain"]
        try:
            await asyncio.to_thread(site_verification.verify_domain, service, domain)
            await db.update_domain(domain, site_verified=1, last_error=None)
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] VERIFIED {domain}")
            success += 1
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "already verified" in msg.lower():
                await db.update_domain(domain, site_verified=1, last_error=None)
                await db.append_job_log(job_id, f"[{i}/{len(domains)}] ALREADY VERIFIED {domain}")
                success += 1
            else:
                await db.update_domain(domain, last_error=msg)
                await db.append_job_log(job_id, f"[{i}/{len(domains)}] PENDING {domain}: {msg}", "error")
                fail += 1
        await asyncio.sleep(1)
    await db.finish_job(job_id, "completed", success, fail, f"{success} verified")


async def run_sync_postmaster(job_id: int) -> None:
    user_id = await _user_id_for_job(job_id)
    await db.append_job_log(job_id, "Fetching domains from Google Postmaster Tools")
    registered = await asyncio.to_thread(postmaster.list_domains, user_id)
    registered_set = {d.lower() for d in registered}
    scope = await _scope_for_job(job_id)
    domains = await db.list_domains(owner_id=scope)
    success = 0
    for row in domains:
        in_pm = 1 if row["domain"] in registered_set else 0
        await db.update_domain(row["domain"], postmaster_registered=in_pm)
        success += 1
    missing = sum(1 for d in domains if d["domain"] not in registered_set)
    await db.append_job_log(
        job_id,
        f"Postmaster has {len(registered_set)} domains; {missing} local domains missing",
    )
    await db.finish_job(job_id, "completed", success, missing, f"{missing} missing from Postmaster")


async def run_register_postmaster(job_id: int) -> None:
    user_id = await _user_id_for_job(job_id)
    scope = await _scope_for_job(job_id)
    domains = [d for d in await db.list_domains(owner_id=scope) if not d["postmaster_registered"]]
    await db.append_job_log(job_id, f"Registering {len(domains)} missing domains in Postmaster")
    success = fail = skipped = 0
    for i, row in enumerate(domains, 1):
        domain = row["domain"]
        try:
            result = await asyncio.to_thread(postmaster.register_domain, user_id, domain)
            if result == "exists":
                skipped += 1
                await db.update_domain(domain, postmaster_registered=1, last_error=None)
                await db.append_job_log(job_id, f"[{i}/{len(domains)}] EXISTS {domain}")
            else:
                success += 1
                await db.update_domain(domain, postmaster_registered=1, last_error=None)
                await db.append_job_log(job_id, f"[{i}/{len(domains)}] REGISTERED {domain}")
                try:
                    await asyncio.to_thread(postmaster.verify_domain, user_id, domain)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            fail += 1
            await db.update_domain(domain, last_error=str(exc))
            await db.append_job_log(job_id, f"[{i}/{len(domains)}] FAIL {domain}: {exc}", "error")
        await asyncio.sleep(0.4)
    await db.finish_job(
        job_id,
        "completed",
        success + skipped,
        fail,
        f"{success} added, {skipped} existed, {fail} failed",
    )


async def credential_status(user_id: int, public_base_url: str | None = None) -> dict:
    settings = get_settings()
    user_secrets.migrate_legacy_secrets_for_user(user_id)
    return {
        "cloudflare": bool(user_secrets.read_cloudflare_token(user_id)),
        "google_credentials": google_auth.credentials_file_exists(user_id),
        "google_site_token": google_auth.token_exists(user_id, "site"),
        "google_postmaster_token": google_auth.token_exists(user_id, "postmaster"),
        "public_base_url": (public_base_url or settings.public_base_url).rstrip("/"),
    }
