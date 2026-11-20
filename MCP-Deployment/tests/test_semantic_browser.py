"""AI-friendly observe/act regression tests: exact refs, safe actions, no secrets."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser"
sys.path.insert(0, str(SOURCE))
from semantic import allow_action, clean_public_details  # noqa: E402
from semantic_browser import SemanticBrowser  # noqa: E402

SERVER = SOURCE / "server.py"
spec = importlib.util.spec_from_file_location("tested_semantic_server", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def element(**kwargs):
    result = {
        "tag": "a", "type": "", "role": "link", "label": "Read article",
        "name": "", "href": "https://example.org/article", "download": False,
        "disabled": False, "form_exists": False, "form_method": "",
        "form_action": "", "form_has_password": False,
    }
    result.update(kwargs)
    return result


class Handle:
    def __init__(self, details):
        self.details = details
        self.disposed = False
        self.clicks = 0
        self.fills = []
        self.presses = []

    def evaluate(self, script):
        return dict(self.details)

    def dispose(self):
        self.disposed = True

    def click(self, timeout):
        self.clicks += 1

    def fill(self, value, timeout):
        self.fills.append(value)

    def input_value(self):
        return self.fills[-1] if self.fills else ""

    def press(self, key, timeout):
        self.presses.append(key)


class Page:
    def __init__(self, handles):
        self.url = "https://example.org/"
        self.handles = handles

    def query_selector_all(self, selector):
        return self.handles

    def title(self):
        return "Example Home"

    def evaluate(self, code):
        return "Visible text"


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.clock = [10.0]
        self.engine = SemanticBrowser(now=lambda: self.clock[0])
        self.link = Handle(element())
        self.page = Page([self.link])

    def test_observe_returns_short_lived_refs_without_css_or_values(self):
        o = self.engine.observe(self.page, "tab1")
        self.assertEqual(o["elements"][0]["ref"], "e1")
        self.assertEqual(o["elements"][0]["name"], "Read article")
        self.assertNotIn("selector", str(o))
        self.assertEqual(o["target_id"], "tab1")
        self.assertNotIn("value", str(o))

    def test_link_click_once_and_snapshot_invalidated(self):
        o = self.engine.observe(self.page, "tab1")
        first = self.engine.act(self.page, "tab1", o["snapshot_id"], "e1", "click")
        self.assertTrue(first["ok"])
        self.assertEqual(self.link.clicks, 1)
        again = self.engine.act(self.page, "tab1", o["snapshot_id"], "e1", "click")
        self.assertFalse(again["ok"])
        self.assertEqual(self.link.clicks, 1)
        self.assertTrue(self.link.disposed)

    def test_refused_unsafe_link_does_not_click(self):
        self.link.details["href"] = "https://example.org/delete/account"
        o = self.engine.observe(self.page, "tab1")
        result = self.engine.act(self.page, "tab1", o["snapshot_id"], "e1", "click")
        self.assertFalse(result["ok"])
        self.assertEqual(self.link.clicks, 0)

    def test_refused_sensitive_form(self):
        self.link.details = element(
            tag="input", type="password", role="textbox", label="Password",
            href="", form_exists=True, form_method="post",
            form_action="https://example.org/login",
        )
        o = self.engine.observe(self.page, "tab1")
        self.assertEqual(o["elements"], [])
        self.assertFalse(self.engine.act(self.page, "tab1", o["snapshot_id"],
                                         "e1", "fill", "secret")["ok"])

    def test_search_get_form_only_and_no_echo(self):
        self.link.details = element(
            tag="input", type="search", role="searchbox", label="Search",
            name="q", href="", form_exists=True, form_method="get",
            form_action="https://example.org/search",
        )
        o = self.engine.observe(self.page, "tab1")
        r = self.engine.act(self.page, "tab1", o["snapshot_id"],
                            "e1", "search", "gundam")
        self.assertTrue(r["ok"])
        self.assertEqual(self.link.fills, ["gundam"])
        self.assertEqual(self.link.presses, ["Enter"])
        self.assertNotIn("gundam", str(r))

    def test_search_post_form_refused(self):
        self.link.details = element(
            tag="input", type="search", role="searchbox", label="Search",
            name="q", href="", form_exists=True, form_method="post",
            form_action="https://example.org/search",
        )
        o = self.engine.observe(self.page, "tab1")
        r = self.engine.act(self.page, "tab1", o["snapshot_id"],
                            "e1", "search", "gundam")
        self.assertFalse(r["ok"])
        self.assertEqual(self.link.presses, [])

    def test_stale_url_and_expiration_refused(self):
        o = self.engine.observe(self.page, "tab1")
        self.page.url = "https://example.org/other"
        self.assertFalse(self.engine.act(
            self.page, "tab1", o["snapshot_id"], "e1", "click"
        )["ok"])
        self.page.url = "https://example.org/"
        o = self.engine.observe(self.page, "tab1")
        self.clock[0] += 91
        self.assertFalse(self.engine.act(
            self.page, "tab1", o["snapshot_id"], "e1", "click"
        )["ok"])
        self.assertEqual(self.link.clicks, 0)

    def test_repurposed_element_refused(self):
        o = self.engine.observe(self.page, "tab1")
        self.link.details["href"] = "https://example.org/somewhere-else"
        r = self.engine.act(self.page, "tab1", o["snapshot_id"], "e1", "click")
        self.assertFalse(r["ok"])
        self.assertEqual(self.link.clicks, 0)

    def test_sensitive_button_and_field_refused(self):
        self.assertFalse(allow_action("click", element(
            tag="button", role="button", label="Buy now", href=""
        ))[0])
        self.assertFalse(allow_action("fill", element(
            tag="input", type="text", role="textbox", label="email", name="email",
            href=""
        ))[0])

    def test_public_details_strip_query_tokens(self):
        d = clean_public_details(
            element(href="https://example.org/article?token=private"), "e1"
        )
        self.assertNotIn("private", str(d))

    def test_server_routes_to_shared_worker(self):
        with mock.patch.object(server, "_target", return_value={
            "id": "tab1", "url": "https://example.org/",
        }), mock.patch.object(server, "browser_page_text", return_value={
            "access_status": "ok",
        }), mock.patch.object(server, "_gui_action", return_value={
            "snapshot_id": "s", "elements": [],
        }) as action:
            result = server.browser_observe("tab1", max_elements=10)
            self.assertIn("snapshot_id", result)
            action.assert_called_once_with(
                {"id": "tab1", "url": "https://example.org/"},
                "observe", {"max_elements": 10},
            )

    def test_invalid_input_never_dispatches_action(self):
        with self.assertRaises(ValueError):
            server.browser_act("short", "e1", "delete", target_id="tab1")
        with self.assertRaises(ValueError):
            server.browser_act("snapshot-12345", "e1", "click", text="x" * 161)


class StandalonePackagingTests(unittest.TestCase):
    def test_compose_publishes_only_loopback_mcp(self):
        import yaml
        root = SOURCE.parent.parent.parent
        manifest = yaml.safe_load((root / "standalone/compose.yml").read_text())
        svc = manifest["services"]["hackbrowser"]
        self.assertEqual(svc["ports"], ["127.0.0.1:8765:8765"])
        self.assertEqual(svc["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", svc["security_opt"])
        self.assertNotIn("privileged", svc)
        self.assertNotIn("9223:9223", str(svc))

    def test_standalone_image_is_non_root_and_has_no_security_suite(self):
        root = SOURCE.parent.parent.parent
        docker = (root / "standalone/Dockerfile").read_text()
        self.assertIn("USER mcp", docker)
        self.assertIn("xvfb", docker)
        self.assertNotIn("zap", docker.lower())
        self.assertNotIn("keycloak", docker.lower())
        self.assertIn("HACKBROWSER_MCP_HOST=0.0.0.0", docker)


if __name__ == "__main__":
    unittest.main()
