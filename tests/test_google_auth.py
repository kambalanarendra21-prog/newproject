from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from app.services import google_auth


class GoogleAuthScopeTests(unittest.TestCase):
    def test_relax_token_scope_sets_and_restores_env(self) -> None:
        os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        with google_auth._relax_token_scope():
            self.assertEqual(os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"], "1")
        self.assertNotIn("OAUTHLIB_RELAX_TOKEN_SCOPE", os.environ)

    def test_exchange_code_relaxes_scope_and_saves_both_tokens(self) -> None:
        flow = MagicMock()
        flow.credentials.to_json.return_value = '{"token":"x"}'
        flow.credentials.scopes = [
            google_auth.SITE_SCOPE,
            google_auth.POSTMASTER_SCOPE,
            google_auth.POSTMASTER_READONLY_SCOPE,
        ]

        def fetch_token(**_kwargs):
            self.assertEqual(os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE"), "1")

        flow.fetch_token.side_effect = fetch_token
        with (
            patch.object(google_auth, "build_flow", return_value=flow),
            patch.object(google_auth.user_secrets, "save_google_token_text") as save,
        ):
            google_auth.exchange_code(7, "site", "auth-code")

        kinds = [call.args[1] for call in save.call_args_list]
        self.assertIn("site", kinds)
        self.assertIn("postmaster", kinds)
        flow.fetch_token.assert_called_once_with(code="auth-code")

    def test_authorization_url_does_not_include_granted_scopes(self) -> None:
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth", "state")
        with patch.object(google_auth, "build_flow", return_value=flow):
            google_auth.authorization_url(1, "postmaster", "state-1")
        kwargs = flow.authorization_url.call_args.kwargs
        self.assertNotIn("include_granted_scopes", kwargs)
        self.assertEqual(kwargs["prompt"], "consent")


if __name__ == "__main__":
    unittest.main()
