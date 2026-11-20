"""Unit tests for the opt-in process pool (no browser required)."""
import tempfile
import unittest
from unittest.mock import patch
from session_pool import SessionPool


class FakeProcess:
    def __init__(self):
        self.exited = False
        self.pid = 999999

    def poll(self):
        return 0 if self.exited else None

    def terminate(self):
        self.exited = True

    def wait(self, timeout=None):
        self.exited = True
        return 0

    def kill(self):
        self.exited = True


class PoolTests(unittest.TestCase):
    def test_owner_keys(self):
        self.assertEqual(SessionPool._key("alice"), SessionPool._key("alice"))
        self.assertNotEqual(SessionPool._key("alice"), SessionPool._key("bob"))
        for value in ("", " ", None):
            with self.assertRaises(ValueError):
                SessionPool._key(value)

    def test_separate_profiles_capacity_and_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            pool = SessionPool(root, max_sessions=2)
            with patch("session_pool.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()), \
                 patch.object(pool, "_ready", return_value=True), \
                 patch.object(pool, "_port_available", return_value=True), \
                 patch("session_pool.os.killpg"):
                a = pool.acquire("alice")
                b = pool.acquire("bob")
                self.assertNotEqual(a.port, b.port)
                self.assertNotEqual(a.profile_dir, b.profile_dir)
                self.assertIs(pool.acquire("alice"), a)
                with self.assertRaisesRegex(RuntimeError, "limit"):
                    pool.acquire("charlie")
                pool.release("alice")
                self.assertTrue(a.profile_dir.exists())
                c = pool.acquire("charlie")
                self.assertNotEqual(c.profile_dir, b.profile_dir)
                pool.shutdown()
                self.assertEqual(pool.stats()["active"], 0)

    def test_failed_startup_terminates_child(self):
        with tempfile.TemporaryDirectory() as root:
            pool = SessionPool(root)
            proc = FakeProcess()
            with patch("session_pool.subprocess.Popen", return_value=proc), \
                 patch.object(pool, "_ready", return_value=False), \
                 patch.object(pool, "_port_available", return_value=True), \
                 patch("session_pool.os.killpg"):
                with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                    pool.acquire("alice", startup_timeout=0)
            self.assertTrue(proc.exited)
            self.assertEqual(pool.stats()["active"], 0)


if __name__ == "__main__":
    unittest.main()
