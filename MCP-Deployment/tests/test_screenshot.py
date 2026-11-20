"""Unit tests for inline MCP screenshot transport and widget download."""
import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

from mcp.types import ImageContent, TextContent

SERVER = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
spec = importlib.util.spec_from_file_location("tested_hackbrowser_server", SERVER)
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)

# A valid 1x1 PNG; a real browser capture is additionally exercised in release CD.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/XdYAAAAASUVORK5CYII="
)


class ScreenshotTests(unittest.TestCase):
    def test_returns_inline_png_without_public_url_or_private_file(self):
        encoded = base64.b64encode(PNG).decode("ascii")
        with mock.patch.object(browser, "_cdp", return_value={"data": encoded}) as cdp:
            result = browser.browser_screenshot()
        cdp.assert_called_with("Page.captureScreenshot", {"format": "png"}, None)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], TextContent)
        self.assertIsInstance(result[1], ImageContent)
        self.assertEqual(result[1].mime_type, "image/png")
        self.assertEqual(base64.b64decode(result[1].data, validate=True), PNG)
        metadata = json.loads(result[0].text)
        self.assertEqual(metadata, {"bytes": len(PNG), "mime_type": "image/png"})

    def test_screenshot_mcp_ui_metadata_and_resource(self):
        import ast
        server = SERVER.read_text()
        tree = ast.parse(server)
        nodes = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
        screenshot = nodes["browser_screenshot"]
        ui_decorators = [d for d in screenshot.decorator_list
                         if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                         and d.func.attr == "tool"]
        self.assertEqual(len(ui_decorators), 1)
        meta = next(k.value for k in ui_decorators[0].keywords if k.arg == "meta")
        self.assertIsInstance(meta, ast.Dict)
        self.assertIn('openai/outputTemplate', ast.unparse(meta))
        self.assertIn('resourceUri', ast.unparse(meta))
        self.assertIn('SCREENSHOT_UI_URI', ast.unparse(meta))
        self.assertIn('@mcp.tool', server)
        self.assertIn('ui://hackbrowser/screenshot.html', server)
        html = SERVER.with_name("screenshot_widget.html").read_text(encoding="utf-8")
        self.assertIn("ui/initialize", html)
        # MIME is verified over the real MCP resources/read protocol in test_mcp_app_protocol.py.
        self.assertIn("ui/notifications/tool-result", html)
        self.assertIn("ui/notifications/size-changed", html)
        self.assertIn("ResizeObserver", html)
        self.assertIn("applyHostHeightLimit", html)
        self.assertIn("overflow-x: hidden", html)
        self.assertIn("max-height: var(--preview-max-height, 440px)", html)
        self.assertIn("data:image/png;base64,", html)
        # Regression: without the .preview class the source PNG renders at
        # its intrinsic pixel width, overflowing both axes of the MCP iframe.
        from html.parser import HTMLParser

        class Images(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                if tag == "img":
                    self.tags.append(dict(attrs))

        images = Images()
        images.feed(html)
        self.assertEqual(len(images.tags), 1)
        self.assertEqual(images.tags[0].get("id"), "preview")
        self.assertIn("preview", images.tags[0].get("class", "").split())
        self.assertIsNone(images.tags[0].get("src"))
        self.assertIn("PNG 다운로드", html)
        self.assertIn('"ui/download-file"', html)
        self.assertIn('"file:///hackbrowser-screenshot.png"', html)
        self.assertIn("getFileDownloadUrl", html)
        self.assertNotIn("URL.createObjectURL", html)
        self.assertNotIn("/captures/", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<img src=", html)

    def test_transient_screenshot_transport_error_retries_once(self):
        encoded = base64.b64encode(PNG).decode("ascii")
        with mock.patch.object(browser, "_cdp", side_effect=[
            RuntimeError("CDP transport error: connection closed"),
            {"data": encoded},
        ]) as cdp:
            result = browser.browser_screenshot()
        self.assertEqual(cdp.call_count, 2)
        self.assertEqual(base64.b64decode(result[1].data), PNG)

    def test_nontransport_screenshot_error_is_not_retried(self):
        with mock.patch.object(browser, "_cdp", side_effect=RuntimeError(
            "CDP Page.captureScreenshot: permission denied",
        )) as cdp:
            with self.assertRaisesRegex(RuntimeError, "permission denied"):
                browser.browser_screenshot()
        self.assertEqual(cdp.call_count, 1)

    def test_invalid_base64_rejected(self):
        with mock.patch.object(browser, "_cdp", return_value={"data": "not-base64!"}):
            with self.assertRaisesRegex(RuntimeError, "invalid base64"):
                browser.browser_screenshot()

    def test_non_png_rejected(self):
        with mock.patch.object(browser, "_cdp", return_value={
            "data": base64.b64encode(b"not a png").decode("ascii")
        }):
            with self.assertRaisesRegex(RuntimeError, "not a PNG"):
                browser.browser_screenshot()

    def test_screenshot_size_limit(self):
        huge = "A" * (browser.MAX_SCREENSHOT_BYTES * 2)
        with mock.patch.object(browser, "_cdp", return_value={"data": huge}):
            with self.assertRaisesRegex(RuntimeError, "8 MiB limit"):
                browser.browser_screenshot()


if __name__ == "__main__":
    unittest.main()
