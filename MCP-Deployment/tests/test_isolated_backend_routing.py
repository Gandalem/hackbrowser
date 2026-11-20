"""Regression tests for isolated bridge routing without launching Chromium."""
import sys
import tempfile
import time
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

    def test_active_stream_lease_prevents_idle_reap_and_idle_reconnect(self):
        # acquire() owns a lease until release(); a stream keeps it open.
        with tempfile.TemporaryDirectory() as root:
            manager = IsolatedBackends(Path(root), max_sessions=1, idle_seconds=1)
            with patch("subprocess.Popen", side_effect=FakeProcess), \
                 patch("session_pool.os.killpg"), \
                 patch.object(SessionPool, "_ready", return_value=True), \
                 patch.object(SessionPool, "_port_available", return_value=True), \
                 patch.object(manager, "_reachable",
                              side_effect=[False, True, False, True]):
                url, key = manager.acquire("issuer:alice")
                first = manager.pool._sessions[key]
                first.last_used = time.monotonic() - 60
                manager.reap()
                self.assertIn(key, manager.pool._sessions)
                self.assertIs(manager.pool._sessions[key], first)
                self.assertIn(key, manager.bridges)
                manager.release(key)
                first.last_used = time.monotonic() - 60
                manager.reap()
                self.assertNotIn(key, manager.pool._sessions)
                self.assertNotIn(key, manager.bridges)
                self.assertTrue(first.profile_dir.exists())
                url2, key2 = manager.acquire("issuer:alice")
                self.assertEqual(key, key2)
                self.assertEqual(url, url2)
                self.assertEqual(manager.pool._sessions[key].profile_dir,
                                 first.profile_dir)
                self.assertIsNot(manager.pool._sessions[key].process, first.process)
                manager.release(key2)
                manager.shutdown()

    def test_smoke_browser_tabs_decoding(self):
        import importlib.util
        script = SERVICES.parent / "scripts" / "smoke_isolated_browser.py"
        spec = importlib.util.spec_from_file_location("isolated_smoke_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        item = {"target_id": "example-id", "url": "about:blank"}
        self.assertEqual(module.normalize_tabs([item]), [item])
        self.assertEqual(module.normalize_tabs(item), [item])
        self.assertEqual(module.normalize_tabs({"result": item}), [item])
        self.assertEqual(module.normalize_tabs({"result": [item]}), [item])
        second = {"target_id": "another-id", "url": "about:blank"}
        blocks = {"content": [
            {"type": "text", "text": __import__("json").dumps(item)},
            {"type": "text", "text": __import__("json").dumps(second)},
        ]}
        self.assertEqual(module.decode_tool_content(blocks), [item, second])
        self.assertEqual(module.normalize_tabs(module.decode_tool_content(blocks)),
                         [item, second])
        self.assertEqual(module.normalize_tabs({"result": {"result": [item]}}), [item])
        self.assertEqual(module.normalize_tabs({"result": []}), [])
        self.assertEqual(module.normalize_tabs([]), [])
        for invalid in ({}, {"result": {}}, {"result": [{}]}):
            with self.assertRaises(ValueError):
                module.normalize_tabs(invalid)

    def test_invalid_user_identity_is_rejected(self):
        for identity in (None, "", " "):
            with self.assertRaises(ValueError):
                SessionPool._key(identity)


if __name__ == "__main__":
    unittest.main()
