"""The tab cleaner closes only nominated pages and retains a blank GUI tab."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

FILE = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
spec = importlib.util.spec_from_file_location("test_tab_cleanup_server", FILE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

A = {"id": "a", "type": "page", "url": "https://example.org"}
B = {"id": "b", "type": "page", "url": "https://example.com"}
BLANK = {"id": "newblank", "type": "page", "url": "about:blank"}


class TabCleanupTests(unittest.TestCase):
    def test_last_tabs_create_blank_before_close(self):
        calls = []
        def cdp(method, params):
            calls.append((method, params))
            return {"targetId": "newblank"} if method == "Target.createTarget" else {"success": True}
        with mock.patch.object(server, "_targets", side_effect=[[A, B], [BLANK]]), \
             mock.patch.object(server, "_browser_cdp", side_effect=cdp):
            result = server.browser_close_tabs(["a", "b"])
        self.assertEqual(result["closed"], 2)
        self.assertEqual(result["remaining_target_ids"], ["newblank"])
        self.assertEqual(calls[0][0], "Target.createTarget")
        self.assertEqual([item[1]["targetId"] for item in calls[1:]], ["a", "b"])

    def test_partial_close_keeps_other_page_without_new_blank(self):
        with mock.patch.object(server, "_targets", side_effect=[[A, B], [B]]), \
             mock.patch.object(server, "_browser_cdp", return_value={"success": True}) as cdp:
            result = server.browser_close_tabs(["a"])
        self.assertEqual(result["closed"], 1)
        cdp.assert_called_once_with("Target.closeTarget", {"targetId": "a"})

    def test_unknown_or_duplicate_ids_do_not_close_anything(self):
        with mock.patch.object(server, "_targets", return_value=[A]), \
             mock.patch.object(server, "_browser_cdp") as cdp:
            with self.assertRaises(ValueError):
                server.browser_close_tabs(["missing"])
            with self.assertRaises(ValueError):
                server.browser_close_tabs(["a", "a"])
            cdp.assert_not_called()

    def test_create_blank_failure_does_not_close_existing(self):
        with mock.patch.object(server, "_targets", return_value=[A]), \
             mock.patch.object(server, "_browser_cdp", return_value={}) as cdp:
            with self.assertRaises(RuntimeError):
                server.browser_close_tabs(["a"])
            cdp.assert_called_once_with("Target.createTarget", {"url": "about:blank"})

    def test_nonpage_target_refused(self):
        ui = {"id": "ui", "type": "webview", "url": "file:///ui"}
        with mock.patch.object(server, "_targets", return_value=[ui]), \
             mock.patch.object(server, "_browser_cdp") as cdp:
            with self.assertRaises(ValueError):
                server.browser_close_tabs(["ui"])
            cdp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
