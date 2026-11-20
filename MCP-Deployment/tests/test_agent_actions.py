"""Regressions for CDP-backed agent keyboard, scroll, selectors, and page waits."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
spec = importlib.util.spec_from_file_location("tested_hackbrowser_agent", SOURCE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

TARGET = {"id": "tab-test", "url": "https://example.org/"}


class AgentActionsTests(unittest.TestCase):
    def setUp(self):
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def tearDown(self):
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def test_enter_uses_bounded_cdp_key_events(self):
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_pace_navigation"), \
             mock.patch.object(server, "_cdp", return_value={}) as cdp:
            response = server.browser_keypress("Enter")
        self.assertTrue(response["ok"])
        self.assertEqual(cdp.call_count, 2)
        self.assertEqual(cdp.call_args_list[0].args[0], "Input.dispatchKeyEvent")
        self.assertEqual(cdp.call_args_list[0].args[1]["key"], "Enter")
        self.assertEqual(cdp.call_args_list[0].args[1]["text"], "\r")
        self.assertEqual(cdp.call_args_list[1].args[1]["type"], "keyUp")
        with self.assertRaises(ValueError):
            server.browser_keypress("Control+L")

    def test_scroll_restricts_direction_and_bounds(self):
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_pace_navigation"), \
             mock.patch.object(server, "_evaluate", return_value={"ok": True}) as evaluate:
            output = server.browser_scroll("up", 120, selector="#results")
        self.assertTrue(output["ok"])
        expression = evaluate.call_args.args[0]
        self.assertIn('document.querySelector("#results")', expression)
        self.assertIn("top:-120", expression)
        for options in ({"direction": "diagonal"}, {"pixels": 0}, {"pixels": 9000},
                        {"selector": ""}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                server.browser_scroll(**options)

    def test_wait_for_selector_and_dynamic_page(self):
        calls = [
            {"url": TARGET["url"], "title": "Loading", "ready_state": "loading",
             "matched": False, "access_text": ""},
            {"url": TARGET["url"], "title": "Ready", "ready_state": "complete",
             "matched": True, "access_text": "Search results"},
        ]
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", side_effect=calls) as evaluate, \
             mock.patch.object(server.time, "sleep") as sleeper:
            response = server.browser_wait_for(selector=".results", timeout_seconds=2)
        self.assertTrue(response["ok"])
        self.assertEqual(evaluate.call_count, 2)
        sleeper.assert_called_once()
        self.assertIn('document.querySelector(".results")', evaluate.call_args.args[0])

    def test_wait_stops_immediately_on_access_restriction(self):
        blocked = {
            "url": "https://search.shopping.naver.com/ns/search?query=test",
            "title": "NAVER", "ready_state": "complete", "matched": False,
            "access_text": "쇼핑 서비스 접속이 일시적으로 제한되었습니다.",
        }
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value=blocked) as evaluate, \
             mock.patch.object(server.time, "sleep") as sleeper:
            response = server.browser_wait_for(text="건담", timeout_seconds=5)
        self.assertEqual(response["access_status"], "restricted")
        self.assertFalse(response["ok"])
        evaluate.assert_called_once()
        sleeper.assert_not_called()

    def test_wait_rejects_bad_parameters(self):
        for options in ({"selector": "#x", "text": "hi"}, {"timeout_seconds": 0},
                        {"timeout_seconds": 100}, {"selector": ""}, {"text": ""}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                server.browser_wait_for(**options)

    def test_element_discovery_uses_visible_actionable_selectors(self):
        with mock.patch.object(server, "_evaluate", return_value={
            "links": [{"text": "Products", "selector": "#products", "href": TARGET["url"]}],
            "inputs": [{"tag": "input", "selector": "#query", "disabled": False}],
        }) as evaluate:
            output = server.browser_elements()
        self.assertEqual(output["links"][0]["selector"], "#products")
        self.assertEqual(output["inputs"][0]["selector"], "#query")
        self.assertIn("getComputedStyle", evaluate.call_args.args[0])
        self.assertIn("CSS.escape", evaluate.call_args.args[0])
        self.assertNotIn("el.value", evaluate.call_args.args[0])

    def test_click_refuses_hidden_and_disabled_elements(self):
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_pace_navigation"), \
             mock.patch.object(server, "_evaluate", return_value={"ok": False, "error": "Element is disabled"}) as evaluate:
            result = server.browser_click("button:disabled")
        self.assertFalse(result["ok"])
        expression = evaluate.call_args.args[0]
        self.assertIn("if(el.disabled)", expression)
        self.assertIn("Element is not visible", expression)


if __name__ == "__main__":
    unittest.main()
