"""Access safety regression tests: no denial evasion or unbounded retries."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
spec = importlib.util.spec_from_file_location("tested_browser_access", SOURCE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class AccessSafetyTests(unittest.TestCase):
    def setUp(self):
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def tearDown(self):
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def test_restricted_pages_are_classified(self):
        self.assertEqual(
            server._restriction_reason(
                "https://search.shopping.naver.com/ns/search?query=test",
                "쇼핑 서비스 접속이 일시적으로 제한되었습니다."),
            "네이버의 접속 제한 안내가 표시됨",
        )
        self.assertIsNotNone(server._restriction_reason(
            "https://www.google.com/sorry/index", "About this page"))
        self.assertIsNotNone(server._restriction_reason(
            "https://www.gmarket.co.kr/", "봇 확인 절차가 진행되고 있습니다"))
        self.assertIsNone(server._restriction_reason(
            "https://example.com/", "쇼핑 서비스 접속이 일시적으로 제한되었습니다."))
        self.assertIsNone(server._restriction_reason(
            "https://shopping.naver.com/ns/home", "정상 쇼핑 페이지입니다."))

    def test_naver_shopping_subdomains_share_cooldown(self):
        with mock.patch.object(server.time, "monotonic", return_value=100):
            self.assertEqual(server._record_restriction(
                "https://search.shopping.naver.com/ns/search?query=test"), 1800)
            with self.assertRaisesRegex(RuntimeError, "접속 제한"):
                server._pace_navigation("shopping.naver.com")
            with self.assertRaisesRegex(RuntimeError, "접속 제한"):
                server._pace_navigation("search.shopping.naver.com")
            # The restricted Naver Shopping origin doesn't block unrelated sites.
            server._pace_navigation("example.com")

    def test_nav_rate_limited_with_no_automatic_retries(self):
        clock = [100.0]
        def fake_sleep(seconds):
            clock[0] += seconds
        with mock.patch.object(server.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(server.time, "sleep", side_effect=fake_sleep) as sleeper:
            server._pace_navigation("example.org")
            server._pace_navigation("example.org")
            self.assertEqual(sleeper.call_count, 1)
            self.assertGreaterEqual(sleeper.call_args.args[0], 4)

    def test_page_text_detects_restriction_and_respects_length(self):
        restricted = {
            "url": "https://search.shopping.naver.com/ns/search?query=test",
            "title": "네이버쇼핑",
            "text": "쇼핑 서비스 접속이 일시적으로 제한되었습니다.",
        }
        with mock.patch.object(server, "_evaluate", return_value=restricted.copy()):
            result = server.browser_page_text(max_chars=5)
        self.assertEqual(result["access_status"], "restricted")
        self.assertEqual(result["text"], "쇼핑 서비스"[:5])
        self.assertEqual(result["retry_after_seconds"], 1800)
        self.assertIn("shopping.naver.com", server._restricted_until)

    def test_navigation_blocked_before_cdp_when_access_restricted(self):
        with mock.patch.object(server, "_target", return_value={"id": "abc"}), \
             mock.patch.object(server, "_cdp") as cdp:
            server._record_restriction(
                "https://search.shopping.naver.com/ns/search?query=test")
            with self.assertRaisesRegex(RuntimeError, "접속 제한"):
                server.browser_navigate("https://shopping.naver.com/ns/home")
            cdp.assert_not_called()

    def test_normal_navigation_still_works(self):
        with mock.patch.object(server, "_target", return_value={"id": "abc"}), \
             mock.patch.object(server, "_cdp", return_value={}) as cdp:
            out = server.browser_navigate("https://example.org/hello")
        self.assertTrue(out["navigation_started"])
        cdp.assert_called_once_with(
            "Page.navigate", {"url": "https://example.org/hello"}, "abc")


if __name__ == "__main__":
    unittest.main()
