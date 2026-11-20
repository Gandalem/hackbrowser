"""Cryptographic JWT regression tests for opt-in staging OAuth isolation."""
from __future__ import annotations

import importlib.util
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

SCRIPT = Path(__file__).resolve().parent.parent / "services/gateway/oauth_gateway.py"
PUBLIC = "https://example.test"
CLIENT = "hb-smoke-0123456789ab"


def load_gateway(*, port="18887", client=CLIENT, oauth="1"):
    env = {
        "PUBLIC_BASE_URL": PUBLIC,
        "ENABLE_OAUTH": oauth,
        "BROWSER_SESSION_MODE": "isolated",
        "OAUTH_GATEWAY_PORT": port,
        "HACKBROWSER_STAGING_TEST_CLIENT": client,
    }
    with patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("oauth_staging_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class StagingOAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.gateway = load_gateway()
        self.signing_key = patch.object(
            self.gateway.KEYS, "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=self.key.public_key()),
        )
        self.signing_key.start()
        self.addCleanup(self.signing_key.stop)

    def token(self, **overrides):
        claims = {
            "iss": self.gateway.ISSUER,
            "sub": "isolated-user-a",
            "aud": self.gateway.resource_url("hackbrowser"),
            "scope": "mcp:hackbrowser",
            "azp": CLIENT,
            "exp": int(time.time()) + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256")

    def test_staging_client_requires_nonproduction_port_and_oauth(self):
        with self.assertRaises(ValueError):
            load_gateway(port="8787")
        with self.assertRaises(RuntimeError):
            load_gateway(oauth="0")
        with self.assertRaises(ValueError):
            load_gateway(client="chatgpt-hackbrowser")

    def test_verified_staging_subject_is_preserved(self):
        result = self.gateway.verify_jwt(self.token(), "hackbrowser")
        self.assertEqual(result["sub"], "isolated-user-a")
        self.assertEqual(result["azp"], CLIENT)

    def test_production_client_still_allowed_on_own_resource(self):
        self.gateway.verify_jwt(
            self.token(azp="chatgpt-hackbrowser"), "hackbrowser",
        )

    def test_wrong_client_is_denied(self):
        with self.assertRaises(ValueError):
            self.gateway.verify_jwt(self.token(azp="another-client"), "hackbrowser")

    def test_wrong_scope_is_denied(self):
        with self.assertRaises(ValueError):
            self.gateway.verify_jwt(self.token(scope="openid profile"), "hackbrowser")

    def test_other_resource_is_denied(self):
        with self.assertRaises(jwt.PyJWTError):
            self.gateway.verify_jwt(
                self.token(aud="https://example.test/pocmap/mcp"), "hackbrowser",
            )

    def test_wrong_issuer_and_expired_are_denied(self):
        for claims in ({"iss": "https://attacker.invalid"},
                       {"exp": int(time.time()) - 120}):
            with self.assertRaises(jwt.PyJWTError):
                self.gateway.verify_jwt(self.token(**claims), "hackbrowser")

    def test_altered_signature_is_denied(self):
        token = self.token()
        chunks = token.split(".")
        # Modify signed payload with no access to signing key.
        chunks[1] = ("A" if chunks[1][0] != "A" else "B") + chunks[1][1:]
        with self.assertRaises(jwt.PyJWTError):
            self.gateway.verify_jwt(".".join(chunks), "hackbrowser")

    def test_staging_client_not_accepted_for_other_service(self):
        with self.assertRaises(jwt.PyJWTError):
            self.gateway.verify_jwt(self.token(), "pocmap")


if __name__ == "__main__":
    unittest.main()
