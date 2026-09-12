from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import jobs


def _domain(name: str, **fields) -> dict:
    row = {
        "domain": name,
        "txt_record": None,
        "cloudflare_txt_added": 0,
        "site_verified": 0,
        "postmaster_registered": 0,
    }
    row.update(fields)
    return row


class PendingDomainTests(unittest.TestCase):
    def test_fetch_tokens_skips_domains_that_already_have_txt(self) -> None:
        rows = [
            _domain("old.com", txt_record="google-site-verification=abc"),
            _domain("failed.com", txt_record="ERROR: timeout"),
            _domain("new.com"),
        ]
        pending = jobs.pending_domains("fetch_tokens", rows)
        self.assertEqual([row["domain"] for row in pending], ["failed.com", "new.com"])

    def test_cloudflare_skips_already_added(self) -> None:
        rows = [
            _domain("done.com", txt_record="tok", cloudflare_txt_added=1),
            _domain("ready.com", txt_record="tok", cloudflare_txt_added=0),
            _domain("notoken.com"),
        ]
        pending = jobs.pending_domains("cloudflare_txt", rows)
        self.assertEqual([row["domain"] for row in pending], ["ready.com"])

    def test_verify_and_register_skip_completed(self) -> None:
        rows = [
            _domain("verified.com", site_verified=1, postmaster_registered=1),
            _domain("new.com"),
        ]
        self.assertEqual(
            [row["domain"] for row in jobs.pending_domains("verify_sites", rows)],
            ["new.com"],
        )
        self.assertEqual(
            [row["domain"] for row in jobs.pending_domains("register_postmaster", rows)],
            ["new.com"],
        )


class StopJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        jobs._cancel_ids.clear()

    async def asyncTearDown(self) -> None:
        jobs._cancel_ids.clear()

    async def test_request_stop_marks_running_job(self) -> None:
        job = {"id": 9, "status": "running", "user_id": 3, "job_type": "fetch_tokens"}
        with (
            patch.object(jobs.db, "get_job", AsyncMock(return_value=job)),
            patch.object(jobs.db, "mark_job_cancelling", AsyncMock(return_value=True)) as mark,
            patch.object(jobs.db, "append_job_log", AsyncMock()) as log,
        ):
            await jobs.request_stop(9, 3, is_super_user=False)
        mark.assert_awaited_once_with(9)
        log.assert_awaited()
        self.assertIn(9, jobs._cancel_ids)

    async def test_sub_user_cannot_stop_someone_elses_job(self) -> None:
        job = {"id": 9, "status": "running", "user_id": 1}
        with patch.object(jobs.db, "get_job", AsyncMock(return_value=job)):
            with self.assertRaises(RuntimeError):
                await jobs.request_stop(9, 99, is_super_user=False)

    async def test_fetch_tokens_only_calls_google_for_pending(self) -> None:
        rows = [
            _domain("old.com", txt_record="already-there"),
            _domain("new.com"),
        ]
        get_token = MagicMock(return_value="new-token")
        with (
            patch.object(jobs, "_user_id_for_job", AsyncMock(return_value=1)),
            patch.object(jobs, "_scope_for_job", AsyncMock(return_value=1)),
            patch.object(jobs.db, "list_domains", AsyncMock(return_value=rows)),
            patch.object(jobs.db, "append_job_log", AsyncMock()),
            patch.object(jobs.db, "update_domain", AsyncMock()),
            patch.object(jobs.db, "finish_job", AsyncMock()) as finish,
            patch.object(jobs.db, "get_job", AsyncMock(return_value={"status": "running"})),
            patch.object(jobs.site_verification, "build_service", return_value=object()),
            patch.object(jobs.site_verification, "get_txt_token", get_token),
            patch.object(jobs.asyncio, "sleep", AsyncMock()),
        ):
            await jobs.run_fetch_tokens(4)
        get_token.assert_called_once()
        self.assertEqual(get_token.call_args.args[1], "new.com")
        finish.assert_awaited()
        self.assertEqual(finish.call_args.args[1], "completed")

    async def test_fetch_tokens_stops_before_next_domain(self) -> None:
        rows = [_domain("one.com"), _domain("two.com")]

        def get_token(_service, domain):
            jobs._cancel_ids.add(5)
            return f"tok-{domain}"

        finish = AsyncMock()
        with (
            patch.object(jobs, "_user_id_for_job", AsyncMock(return_value=1)),
            patch.object(jobs, "_scope_for_job", AsyncMock(return_value=1)),
            patch.object(jobs.db, "list_domains", AsyncMock(return_value=rows)),
            patch.object(jobs.db, "append_job_log", AsyncMock()),
            patch.object(jobs.db, "update_domain", AsyncMock()),
            patch.object(jobs.db, "finish_job", finish),
            patch.object(jobs.db, "get_job", AsyncMock(return_value={"status": "running"})),
            patch.object(jobs.site_verification, "build_service", return_value=object()),
            patch.object(jobs.site_verification, "get_txt_token", get_token),
            patch.object(jobs.asyncio, "sleep", AsyncMock()),
        ):
            await jobs.run_fetch_tokens(5)
        self.assertEqual(finish.call_args.args[1], "cancelled")
        self.assertEqual(finish.call_args.args[2], 1)


if __name__ == "__main__":
    unittest.main()
