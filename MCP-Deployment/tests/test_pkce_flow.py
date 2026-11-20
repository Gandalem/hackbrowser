"""Unit tests for loopback-only authorization-code PKCE helper."""
import hashlib
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/keycloak_pkce.py"
spec = importlib.util.spec_from_file_location("isolated_pkce_helper", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PKCEHelperTests(unittest.TestCase):
    def test_s256_verifier_matches_hash(self):
        import base64
        verifier = mod.new_verifier()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(mod.s256_challenge(verifier), expected)

    def test_keycloak_form_hidden_fields(self):
        parser = mod._LoginForm()
        parser.feed(
            '<form id="kc-form-login" action="https://site.test/auth/realms/security-mcp/'
            'login-actions/authenticate?session_code=abc">'
            '<input type="hidden" name="session_code" value="abc">'
            '<input name="username"><input type="password" name="password"></form>'
        )
        self.assertEqual(parser.hidden, {"session_code": "abc"})
        self.assertIn("login-actions", parser.action)

    def test_login_url_only_allows_expected_realm_and_origin(self):
        kwargs = {"base_url": "http://127.0.0.1:8081/auth",
                  "public_base": "https://site.test", "realm": "security-mcp"}
        value = mod._localize_login_url(
            "https://site.test/auth/realms/security-mcp/login-actions/authenticate?x=1",
            **kwargs,
        )
        self.assertEqual(
            value,
            "http://127.0.0.1:8081/auth/realms/security-mcp/login-actions/authenticate?x=1",
        )
        for url in (
            "https://evil.test/auth/realms/security-mcp/login-actions/authenticate",
            "https://site.test/other/path",
            "https://site.test@evil.test/auth/realms/security-mcp/login-actions/authenticate",
        ):
            with self.assertRaises(mod.PKCEFlowError):
                mod._localize_login_url(url, **kwargs)


if __name__ == "__main__":
    unittest.main()
