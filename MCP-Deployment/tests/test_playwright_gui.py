"""Isolated regressions for Playwright attached to an existing GUI Chromium."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser"
spec = importlib.util.spec_from_file_location("tested_gui_playwright", SOURCE / "playwright_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

SERVER = SOURCE / "server.py"
server_spec = importlib.util.spec_from_file_location("tested_gui_tools", SERVER)
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)

TARGET = {"id": "gui-tab", "url": "https://example.org/"}


class FakeSession:
    def send(self, command):
        assert command == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": "gui-tab"}}

    def detach(self):
        pass


class FakeLocator:
    def __init__(self):
        self.clicks = 0
        self.fills = []
        self.presses = []

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self, timeout):
        self.clicks += 1

    def fill(self, value, timeout):
        self.fills.append(value)

    def input_value(self):
        return self.fills[-1]

    def press(self, key, timeout):
        self.presses.append(key)


class FakePage:
    url = "https://example.org/"

    def __init__(self):
        self.element = FakeLocator()
        self.mouse = types.SimpleNamespace(click=lambda x, y: None)

    def is_closed(self):
        return False

    def locator(self, selector):
        return self.element

    def get_by_role(self, role, name, exact):
        return self.element

    def get_by_text(self, text, exact):
        return self.element

    def evaluate(self, expr):
        if "innerWidth" in expr:
            return {"width": 1366, "height": 900}
        return "Before"

    def wait_for_timeout(self, ms):
        pass


class FakeContext:
    def __init__(self, page):
        self.pages = [page]

    def new_cdp_session(self, page):
        return FakeSession()


class FakeBrowser:
    def __init__(self, page):
        self.contexts = [FakeContext(page)]


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = types.SimpleNamespace(
            connect_over_cdp=lambda url, timeout: browser,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class GuiActionTests(unittest.TestCase):
    def setUp(self):
        server._next_navigation_at.clear()
        server._restricted_until.clear()

    def _run(self, action, args, tabs=None, page=None):
        page = page or FakePage()
        browser = FakeBrowser(page)
        list_targets = mock.Mock(side_effect=[
            [{"id": "gui-tab", "url": TARGET["url"]}],
            [{"id": "gui-tab", "url": TARGET["url"]}] + (tabs or []),
        ])
        with mock.patch.object(control.time, "monotonic",
                               side_effect=[0.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0]):
            output = control._run_connected(
                browser, TARGET, action, args, list_targets,
            )
        return output, page, list_targets

    def test_existing_gui_tab_is_selected_and_clicks_once(self):
        result, page, _ = self._run("click", {"selector": "a.product"})
        self.assertTrue(result["ok"])
        self.assertEqual(page.element.clicks, 1)
        self.assertFalse(result["effect_observed"])

    def test_new_tab_is_tracked_after_click(self):
        new_tab = {"id": "new-product-tab", "url": "https://shop.example/item", "title": "Item"}
        result, _, _ = self._run("click", {"selector": "a"}, tabs=[new_tab])
        self.assertEqual(result["next_target_id"], "new-product-tab")
        self.assertEqual(result["new_tabs"][0]["url"], new_tab["url"])
        self.assertTrue(result["effect_observed"])

    def test_field_content_is_not_returned(self):
        result, _, _ = self._run("fill", {"selector": "#password", "value": "private-secret"})
        self.assertTrue(result["value_confirmed"])
        self.assertNotIn("private-secret", str(result))

    def test_accessible_click_and_press(self):
        click, page, _ = self._run("click_text", {
            "text": "판매 많은순", "role": "button", "exact": True,
        })
        self.assertTrue(click["ok"])
        self.assertEqual(page.element.clicks, 1)
        press, page, _ = self._run("press", {"selector": "#q", "key": "Enter"})
        self.assertTrue(press["ok"])
        self.assertEqual(page.element.presses, ["Enter"])

    def test_gui_coordinate_click_uses_supported_mouse_api(self):
        page = FakePage()
        clicks = []
        page.mouse = types.SimpleNamespace(click=lambda x, y: clicks.append((x, y)))
        result, _, _ = self._run("click_at", {"x": 600, "y": 350}, page=page)
        self.assertTrue(result["ok"])
        self.assertEqual(clicks, [(600, 350)])

    def test_semantic_click_reports_ambiguous_matches_without_mcp_exception(self):
        page = FakePage()
        duplicate = FakeLocator()
        duplicate.count = lambda: 3
        page.get_by_role = lambda role, name, exact: duplicate
        result, _, _ = self._run("click_text", {
            "text": "건프라", "role": "link", "exact": True,
        }, page=page)
        self.assertFalse(result["ok"])
        self.assertIn("Multiple elements match (3)", result["error"])
        self.assertEqual(duplicate.clicks, 0)

    def test_rejects_nonlocal_cdp_or_ambiguous_page(self):
        with self.assertRaisesRegex(RuntimeError, "local GUI"):
            control.run_action("http://example.org:9223", TARGET, "click", {}, lambda: [])
        page = FakePage()
        context = FakeContext(page)
        context.new_cdp_session = mock.Mock(return_value=types.SimpleNamespace(
            send=lambda *_: {"targetInfo": {"targetId": "different"}}, detach=lambda: None,
        ))
        page.url = "https://another.example.org"
        with self.assertRaisesRegex(RuntimeError, "Cannot uniquely"):
            control._find_page(context, TARGET)

    def test_worker_reuses_existing_cdp_across_two_actions(self):
        page = FakePage()
        browser = FakeBrowser(page)
        browser.is_connected = lambda: True
        connects = []
        class FakeDriver:
            chromium = types.SimpleNamespace(connect_over_cdp=lambda *a, **k: (
                connects.append(1) or browser
            ))
        driver = FakeDriver()
        class DriverContext:
            def __enter__(self):
                return driver
            def __exit__(self, *args):
                pass
        fake_module = types.ModuleType("playwright.sync_api")
        fake_module.sync_playwright = lambda: DriverContext()
        fake_module.Error = RuntimeError
        fake_module.TimeoutError = TimeoutError
        worker = control._GuiWorker()
        with mock.patch.dict(sys.modules, {"playwright.sync_api": fake_module}), \
             mock.patch.object(control, "_run_connected", return_value={"ok": True}):
            one = worker.submit("http://127.0.0.1:9223", TARGET, "click",
                                {"selector": "#first"}, lambda: [])
            two = worker.submit("http://127.0.0.1:9223", TARGET, "click",
                                {"selector": "#second"}, lambda: [])
        self.assertTrue(one["ok"])
        self.assertTrue(two["ok"])
        self.assertEqual(len(connects), 1)

    def test_server_routes_click_without_javascript_click(self):
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_pace_navigation"), \
             mock.patch.object(server, "_gui_action", return_value={"ok": True}) as gui:
            self.assertTrue(server.browser_click("a.product")["ok"])
        gui.assert_called_once_with(TARGET, "click", {"selector": "a.product"})

    def test_text_click_and_search_api_validation(self):
        with self.assertRaises(ValueError):
            server.browser_click_text("test", role="invalid")
        with self.assertRaises(ValueError):
            server.browser_fill_and_submit("#search", "query", key="Escape")
        with self.assertRaises(ValueError):
            server.browser_click_at(-1.0, 10)


if __name__ == "__main__":
    unittest.main()
