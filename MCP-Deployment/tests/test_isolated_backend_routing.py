"""Regression tests for isolated bridge routing without launching Chromium."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SERVICES = Path(__file__).resolve().parents[1] / "services"
sys.path.insert(0, str(SERVICES / "hackbrowser"))
sys.path.insert(0, str(SERVICES / "gateway"))

from isolated_backends import IsolatedBackends  # noqa: E402
from session_pool import SessionPool  # noqa: E402


class FakeProcess:
    counter = 300000

    def __init__(self, *args, **kwargs):
        FakeProcess.counter += 1
        self.pid = FakeProcess.counter
        self.exited = False

    def poll(self):
        return 0 if self.exited else None

    def terminate(self):
        self.exited = True

    def wait(self, timeout=None):
        self.exited = True
        return 0

    def kill(self):
        self.exited = True


class IsolatedRoutingTests(unittest.TestCase):
    def test_distinct_users_get_distinct_browser_and_mcp_ports(self):
        with tempfile.TemporaryDirectory() as root:
            manager = IsolatedBackends(Path(root), max_sessions=2)
            with patch("subprocess.Popen", side_effect=FakeProcess), \
                 patch("session_pool.os.killpg"), \
                 patch.object(SessionPool, "_ready", return_value=True), \
                 patch.object(SessionPool, "_port_available", return_value=True), \
                 patch.object(manager, "_reachable", side_effect=[False, True, False, True]):
                url_a, key_a = manager.acquire("issuer:alice")
                url_b, key_b = manager.acquire("issuer:bob")
                self.assertNotEqual(url_a, url_b)
                self.assertNotEqual(key_a, key_b)
                self.assertNotEqual(manager.pool._sessions[key_a].profile_dir,
                                    manager.pool._sessions[key_b].profile_dir)
                self.assertEqual(len(manager.bridges), 2)
                with self.assertRaisesRegex(RuntimeError, "limit"):
                    manager.acquire("issuer:charlie")
                manager.release(key_a)
                manager.release(key_b)
                manager.shutdown()
                self.assertFalse(manager.bridges)

    def test_invalid_user_identity_is_rejected(self):
        for identity in (None, "", " "):
            with self.assertRaises(ValueError):
                SessionPool._key(identity)


if __name__ == "__main__":
    unittest.main()
