"""Security regression tests for expiring screenshot capability URLs."""
import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from aiohttp import web

MODULE = Path(__file__).resolve().parent.parent / "services/gateway/screenshot_download.py"
spec = importlib.util.spec_from_file_location("tested_screenshot_download", MODULE)
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)

PNG = b"\x89PNG\r\n\x1a\n" + b"valid-test-payload"
CAPTURE_ID = "hb-" + "a" * 48 + ".png"


class DummyRequest:
    def __init__(self, name):
        self.match_info = {"capture_id": name}


class ScreenshotDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_capture_is_downloadable(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(download, "SCREENSHOT_DIR", Path(root)):
            path = Path(root, CAPTURE_ID)
            path.write_bytes(PNG)
            os.chmod(path, 0o600)
            result = await download.download_screenshot(DummyRequest(CAPTURE_ID))
            self.assertIsInstance(result, web.Response)
            self.assertEqual(result.body, PNG)
            self.assertEqual(result.content_type, "image/png")
            self.assertIn("no-store", result.headers["Cache-Control"])
            self.assertIn("attachment", result.headers["Content-Disposition"])

    async def test_guessable_or_path_traversal_capture_rejected(self):
        for filename in ("../private.env", "hackbrowser-123.png", "hb-" + "A" * 48 + ".png"):
            with self.assertRaises(web.HTTPNotFound):
                await download.download_screenshot(DummyRequest(filename))

    async def test_expired_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(download, "SCREENSHOT_DIR", Path(root)):
            path = Path(root, CAPTURE_ID)
            path.write_bytes(PNG)
            old = time.time() - 601
            os.utime(path, (old, old))
            with self.assertRaises(web.HTTPNotFound):
                await download.download_screenshot(DummyRequest(CAPTURE_ID))

    async def test_symlink_rejected(self):
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("O_NOFOLLOW unavailable")
        with tempfile.TemporaryDirectory() as root, mock.patch.object(download, "SCREENSHOT_DIR", Path(root)):
            secret = Path(root, "secret")
            secret.write_bytes(PNG)
            Path(root, CAPTURE_ID).symlink_to(secret)
            with self.assertRaises(web.HTTPNotFound):
                await download.download_screenshot(DummyRequest(CAPTURE_ID))

    async def test_corrupt_png_rejected(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(download, "SCREENSHOT_DIR", Path(root)):
            Path(root, CAPTURE_ID).write_bytes(b"not a png")
            with self.assertRaises(web.HTTPNotFound):
                await download.download_screenshot(DummyRequest(CAPTURE_ID))


if __name__ == "__main__":
    unittest.main()
