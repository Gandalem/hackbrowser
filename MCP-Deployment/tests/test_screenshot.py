"""Unit tests for HackBrowser screenshot transport and private file storage."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
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
    def test_returns_text_and_inline_image_and_writes_private_png(self):
        encoded = base64.b64encode(PNG).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(browser, "SCREENSHOT_DIR", Path(directory)), \
                 mock.patch.object(browser, "_cdp", return_value={"data": encoded}) as cdp:
                result1 = browser.browser_screenshot()
                result2 = browser.browser_screenshot()
                cdp.assert_called_with("Page.captureScreenshot", {"format": "png"}, None)

            self.assertEqual(len(result1), 2)
            self.assertIsInstance(result1[0], TextContent)
            self.assertIsInstance(result1[1], ImageContent)
            self.assertEqual(result1[1].mime_type, "image/png")
            self.assertEqual(base64.b64decode(result1[1].data, validate=True), PNG)
            meta1 = json.loads(result1[0].text)
            meta2 = json.loads(result2[0].text)
            self.assertEqual(meta1["bytes"], len(PNG))
            self.assertEqual(meta1["mime_type"], "image/png")
            self.assertNotEqual(meta1["saved_path"], meta2["saved_path"])
            self.assertEqual(Path(meta1["saved_path"]).read_bytes(), PNG)
            self.assertEqual(Path(meta2["saved_path"]).read_bytes(), PNG)
            self.assertEqual(Path(meta1["saved_path"]).stat().st_mode & 0o777, 0o600)

            # ImageContent is preserved; a short-lived file link is additive.
            self.assertNotIn("download_url", meta1)
            with mock.patch.object(browser, "PUBLIC_BASE_URL", "https://mcp.example.test"), \
                 mock.patch.object(browser, "_cdp", return_value={"data": encoded}):
                result3 = browser.browser_screenshot()
            meta3 = json.loads(result3[0].text)
            self.assertRegex(meta3["download_url"], r"^https://mcp\.example\.test/captures/hb-[0-9a-f]{48}\.png$")
            self.assertEqual(meta3["expires_in_seconds"], 600)
            self.assertIsInstance(result3[1], ImageContent)


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
        self.assertEqual(browser.SCREENSHOT_UI_MIME, "text/html;profile=mcp-app")
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
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<img src=", html)

    def test_invalid_base64_does_not_create_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(browser, "SCREENSHOT_DIR", Path(directory)), \
                 mock.patch.object(browser, "_cdp", return_value={"data": "not-base64!"}):
                with self.assertRaisesRegex(RuntimeError, "invalid base64"):
                    browser.browser_screenshot()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_non_png_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(browser, "SCREENSHOT_DIR", Path(directory)), \
                 mock.patch.object(browser, "_cdp", return_value={
                     "data": base64.b64encode(b"not a png").decode("ascii")
                 }):
                with self.assertRaisesRegex(RuntimeError, "not a PNG"):
                    browser.browser_screenshot()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_screenshot_size_limit(self):
        # A very large string must be rejected before decoding or writing.
        huge = "A" * (browser.MAX_SCREENSHOT_BYTES * 2)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(browser, "SCREENSHOT_DIR", Path(directory)), \
                 mock.patch.object(browser, "_cdp", return_value={"data": huge}):
                with self.assertRaisesRegex(RuntimeError, "8 MiB limit"):
                    browser.browser_screenshot()
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
