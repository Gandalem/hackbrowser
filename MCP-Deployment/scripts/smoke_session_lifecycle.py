#!/usr/bin/env python3
"""OCI real isolated-browser idle/reconnect lifecycle smoke (no Keycloak edits).

Runs a single temporary Chromium + MCP bridge, tests active leases, idle reap,
persistent cookies after browser restart and clean shutdown. Does not modify
the live OAuth gateway or browser profile. This is NOT a long-lived SSE test.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "scripts"))
from smoke_isolated_browser import cookie_value, ensure_tab, require_ok, wait_for_text
from isolated_backends import IsolatedBackends


class CookieSite(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/set", "/read"}:
            self.send_error(404)
            return
        value = "cookie-present" if "lifecycle=retained" in self.headers.get("Cookie", "") else "cookie-missing"
        body = ("<!doctype html><html><body>" + value + "</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if self.path == "/set":
            self.send_header("Set-Cookie", "lifecycle=retained; Path=/; SameSite=Lax")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    chromium = os.environ.get("CHROMIUM_BIN") or next(
        (exe for name in ("chromium", "google-chrome-stable", "google-chrome")
         if (exe := shutil.which(name))), None)
    if not chromium or not shutil.which("xvfb-run"):
        raise SystemExit("Requires Chromium and xvfb-run")
    site = ThreadingHTTPServer(("127.0.0.1", 0), CookieSite)
    thread = threading.Thread(target=site.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="hackbrowser-lifecycle-") as root:
            manager = IsolatedBackends(Path(root), max_sessions=1, idle_seconds=2,
                                       chromium=chromium)
            manager.bridge_python = Path(sys.executable)
            manager.server = SOURCE / "services/hackbrowser/server.py"
            owner = "lifecycle:synthetic-user"
            url = key = None
            try:
                url, key = manager.acquire(owner)
                first_session = manager.pool._sessions[key]
                first_port = first_session.port
                first_browser_pid = first_session.process.pid
                first_profile = first_session.profile_dir
                first_bridge_pid = manager.bridges[key].pid
                tab = ensure_tab(url, first_port)
                origin = f"http://127.0.0.1:{site.server_address[1]}"
                require_ok(url, "browser_navigate", {
                    "url": origin + "/set", "target_id": tab,
                })
                wait_for_text(url, tab, "cookie-")
                if "lifecycle=retained" not in cookie_value(first_port, tab):
                    raise AssertionError("Initial test cookie was not stored")
                print("[PASS] Cookie persisted in isolated Chromium profile", flush=True)

                # The active gateway request/stream lease protects an idle browser.
                first_session.last_used = time.monotonic() - 30
                manager.reap()
                if key not in manager.pool._sessions or manager.bridges[key].poll() is not None:
                    raise AssertionError("Active stream lease was incorrectly reaped")
                print("[PASS] Active request/stream lease prevents idle eviction", flush=True)

                manager.release(key)
                manager.pool._sessions[key].last_used = time.monotonic() - 30
                manager.reap()
                if key in manager.pool._sessions or key in manager.bridges:
                    raise AssertionError("Idle browser/bridge did not stop")
                if not first_profile.exists():
                    raise AssertionError("Idle reaping deleted persistent browser profile")
                print("[PASS] Idle browser + MCP bridge stopped; profile retained", flush=True)

                next_url, next_key = manager.acquire(owner)
                if next_key != key or next_url != url:
                    raise AssertionError("Reconnected owner got a different profile mapping")
                newer = manager.pool._sessions[key]
                if newer.profile_dir != first_profile:
                    raise AssertionError("User's persistent profile changed on reconnect")
                if newer.process.pid == first_browser_pid or manager.bridges[key].pid == first_bridge_pid:
                    raise AssertionError("Browser or MCP bridge was not freshly started")
                new_tab = ensure_tab(next_url, newer.port)
                require_ok(next_url, "browser_navigate", {
                    "url": origin + "/read", "target_id": new_tab,
                })
                wait_for_text(next_url, new_tab, "cookie-present")
                if "lifecycle=retained" not in cookie_value(newer.port, new_tab):
                    raise AssertionError("Cookie lost across browser process restart")
                print("[PASS] Same owner reconnects to new processes with stored cookies", flush=True)
                manager.release(next_key)
                print("[RESULT] OCI isolated browser idle/reconnect lifecycle smoke PASSED",
                      flush=True)
                print("[NOTE] Actual HTTP SSE continuity and OAuth/PKCE still untested",
                      flush=True)
            finally:
                if key is not None:
                    manager.release(key)
                manager.shutdown()
    finally:
        site.shutdown()
        site.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
