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
