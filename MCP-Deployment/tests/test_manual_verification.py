"""Human-entered verification: one-time token, no answers logged or solved."""
import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
spec = importlib.util.spec_from_file_location("tested_manual_verification", SOURCE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/XdYAAAAASUVORK5CYII="
)
TARGET = {"id": "verified-tab", "url": "https://search.shopping.naver.com/ns/search"}
URL = TARGET["url"]
PROMPT = "NAVER Please complete the security verification."
STATE = {
    "url": URL,
    "viewport": {"width": 1366, "height": 900},
    "verification_reason": "네이버에서 사용자 확인을 요구함",
}


class ManualVerificationTests(unittest.TestCase):
    def setUp(self):
        server._verification_sessions.clear()
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def tearDown(self):
        server._verification_sessions.clear()
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def test_challenge_status_not_access_denial(self):
        self.assertIsNone(server._restriction_reason(URL, PROMPT))
        self.assertTrue(server._verification_reason(URL, PROMPT))
        with mock.patch.object(server, "_evaluate", return_value={
            "url": URL, "title": "NAVER", "text": PROMPT,
        }):
            result = server.browser_page_text()
        self.assertEqual(result["access_status"], "verification_required")
        self.assertNotIn("shopping.naver.com", server._restricted_until)

    def test_screenshot_offers_one_time_manual_form(self):
        encoded = base64.b64encode(PNG).decode("ascii")
        with mock.patch.object(server, "_cdp", return_value={"data": encoded}), \
             mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_verification_state", return_value=STATE):
            result = server.browser_screenshot()
        metadata = json.loads(result[0].text)
        entry = metadata["verification"]
        self.assertTrue(entry["required"])
        self.assertEqual(entry["viewport"], STATE["viewport"])
        self.assertEqual(len(server._verification_sessions), 1)
        self.assertEqual(base64.b64decode(result[1].data), PNG)

    def test_manual_answer_submitted_only_once_and_not_returned(self):
        server._verification_sessions["demo"] = {
            "target_id": TARGET["id"], "url": URL,
            "viewport": (1366, 900), "expires_at": server.time.monotonic() + 120,
        }
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_verification_state", return_value=STATE), \
             mock.patch.object(server, "_pace_navigation"), \
             mock.patch.object(server, "_cdp", return_value={}) as cdp:
            result = server.browser_submit_verification(
                "demo", "human typed answer", 120, 150, 400, 500)
        self.assertTrue(result["submitted"])
        self.assertNotIn("human typed answer", str(result))
        self.assertEqual(cdp.call_count, 5)
        self.assertEqual(cdp.call_args_list[2].args[0], "Input.insertText")
        self.assertEqual(cdp.call_args_list[2].args[1]["text"], "human typed answer")
        self.assertNotIn("demo", server._verification_sessions)
        with self.assertRaisesRegex(ValueError, "expired"):
            server.browser_submit_verification("demo", "again", 120, 150, 400, 500)

    def test_expired_token_and_bad_coords_block_before_cdp(self):
        server._verification_sessions["expired"] = {
            "target_id": TARGET["id"], "url": URL,
            "viewport": (1366, 900), "expires_at": server.time.monotonic() - 1,
        }
        with mock.patch.object(server, "_cdp") as cdp:
            with self.assertRaisesRegex(ValueError, "expired"):
                server.browser_submit_verification("expired", "1234", 120, 150, 400, 500)
            cdp.assert_not_called()

        server._verification_sessions["offscreen"] = {
            "target_id": TARGET["id"], "url": URL,
            "viewport": (1366, 900), "expires_at": server.time.monotonic() + 120,
        }
        with mock.patch.object(server, "_cdp") as cdp:
            with self.assertRaisesRegex(ValueError, "outside"):
                server.browser_submit_verification("offscreen", "1234", -1, 150, 400, 500)
            cdp.assert_not_called()

    def test_page_change_invalidates_pending_verification(self):
        server._verification_sessions["moved"] = {
            "target_id": TARGET["id"], "url": URL,
            "viewport": (1366, 900), "expires_at": server.time.monotonic() + 120,
        }
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_verification_state", return_value={
                 **STATE, "url": "https://example.org/"
             }), mock.patch.object(server, "_cdp") as cdp:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                server.browser_submit_verification("moved", "1234", 100, 100, 200, 200)
            cdp.assert_not_called()

    def test_answer_validation(self):
        for answer in ("", " " * 2, "x" * 65, "abc\\n123"):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                server.browser_submit_verification("any", answer, 100, 100, 200, 200)


if __name__ == "__main__":
    unittest.main()
