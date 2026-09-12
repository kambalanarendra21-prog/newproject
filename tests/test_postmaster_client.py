from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import UnknownApiNameOrVersion

from app.services import postmaster


class PostmasterClientTests(unittest.TestCase):
    def test_default_discovery_catalog_does_not_list_v2(self) -> None:
        with self.assertRaises(UnknownApiNameOrVersion) as ctx:
            build("gmailpostmastertools", "v2", cache_discovery=False)
        self.assertIn("gmailpostmastertools", str(ctx.exception))
        self.assertIn("v2", str(ctx.exception))

    def test_service_discovery_url_loads_v2(self) -> None:
        http = httplib2.Http()
        try:
            service = build(
                postmaster.POSTMASTER_API_NAME,
                postmaster.POSTMASTER_API_VERSION,
                http=http,
                cache_discovery=False,
                discoveryServiceUrl=postmaster.POSTMASTER_DISCOVERY_URL,
            )
            self.assertTrue(hasattr(service, "domains"))
            self.assertTrue(callable(service.domains().list))
            self.assertTrue(callable(service.domains().create))
            self.assertTrue(callable(service.domains().verify))
        finally:
            http.close()

    def test_resource_name_parsing(self) -> None:
        self.assertEqual(postmaster._domain_from_resource("domains/lavenderlend.com"), "lavenderlend.com")

    def test_register_sends_v2_domain_id(self) -> None:
        service = MagicMock()
        with (
            patch.object(postmaster, "build_service", return_value=service),
        ):
            result = postmaster.register_domain(1, "lavenderlend.com")
        service.domains.return_value.create.assert_called_once_with(body={"domainId": "lavenderlend.com"})
        self.assertEqual(result, "created")

    def test_verify_sends_txt_method(self) -> None:
        service = MagicMock()
        with patch.object(postmaster, "build_service", return_value=service):
            postmaster.verify_domain(1, "lavenderlend.com")
        service.domains.return_value.verify.assert_called_once_with(
            name="domains/lavenderlend.com",
            body={"verificationMethod": "TXT"},
        )


if __name__ == "__main__":
    unittest.main()
