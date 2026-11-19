"""Short-lived, unguessable screenshot downloads for MCP clients.

The PNG filename is a 192-bit capability token. Possessing its URL grants
temporary read access; never log it or include it in publicly shared records.
No screenshot directory listing or arbitrary filesystem paths are accepted.
"""
from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path

from aiohttp import web

SCREENSHOT_DIR = Path(
    os.environ.get(
        "HACKBROWSER_SCREENSHOT_DIR",
        str(Path.home() / "hackbrowser-mcp-screenshots"),
    )
)
CAPTURE_FILENAME = re.compile(r"hb-[0-9a-f]{48}\.png\Z")
DOWNLOAD_TTL_SECONDS = 600
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024


async def download_screenshot(request: web.Request) -> web.Response:
    """Return one private PNG through a 10-minute bearer URL."""
    filename = request.match_info.get("capture_id", "")
    if not CAPTURE_FILENAME.fullmatch(filename):
        raise web.HTTPNotFound()

    # The directory is mode 0700 and the file is mode 0600. The gateway
    # and browser MCP must run under the same unprivileged account.
    path = SCREENSHOT_DIR / filename
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise web.HTTPNotFound() from exc

    try:
        with os.fdopen(fd, "rb") as capture:
            info = os.fstat(capture.fileno())
            age = time.time() - info.st_mtime
            if (
                not stat.S_ISREG(info.st_mode)
                or not 0 < info.st_size <= MAX_SCREENSHOT_BYTES
                or age < -30
                or age >= DOWNLOAD_TTL_SECONDS
            ):
                raise web.HTTPNotFound()
            data = capture.read(MAX_SCREENSHOT_BYTES + 1)
            if len(data) != info.st_size or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise web.HTTPNotFound()
    except OSError as exc:
        raise web.HTTPNotFound() from exc

    return web.Response(
        body=data,
        content_type="image/png",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": 'attachment; filename="hackbrowser-screenshot.png"',
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "sandbox",
        },
    )
