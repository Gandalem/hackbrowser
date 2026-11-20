#!/usr/bin/env python3
"""OCI live Chromium/MCP isolation smoke test (synthetic users, no Keycloak).

Runs two real GUI Chromium + MCP bridge processes via the PR's
IsolatedBackends manager. Uses temporary profiles and a loopback test site.
Never modifies the installed gateway, its ports, users or profiles.

This verifies browser/process isolation; a separate two-account JWT test is
still required before declaring end-to-end OAuth tenant isolation.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "services" / "gateway"))
from isolated_backends import IsolatedBackends  # noqa: E402

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {
        "name": "oci-isolation-smoke", "version": "1.0",
    },
}
OPENER = build_opener(ProxyHandler({}))
PNG = b"\x89PNG\r\n\x1a\n"


class TestSite(BaseHTTPRequestHandler):
    def do_GET(self):
        marker = {
            "/alice": "SYNTHETIC-ALICE",
            "/bob": "SYNTHETIC-BOB",
        }.get(self.path)
        if marker is None:
            self.send_error(404)
            return
        body = (
            "<!doctype html><html><head><title>" + marker +
            "</title></head><body><h1>" + marker + "</h1></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", f"tenant={marker}; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def rpc(url: str, method: str, params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if method == "tools/call":
        headers["Mcp-Name"] = params["name"]
    request = Request(url, json.dumps(payload).encode(), headers, method="POST")
    try:
        with OPENER.open(request, timeout=25) as response:
            raw = response.read(16_000_000).decode()
    except HTTPError as exc:
        raise RuntimeError(f"MCP returned HTTP {exc.code}") from exc
    if raw.lstrip().startswith(("data:", "event:")):
        raw = next(line[5:].strip() for line in raw.splitlines()
                   if line.startswith("data:"))
    result = json.loads(raw)
    if "error" in result:
        raise RuntimeError(str(result["error"])[:240])
    return result.get("result", {})


def tool(url: str, name: str, args: dict | None = None) -> tuple[dict, dict]:
    response = rpc(url, "tools/call", {
        "name": name, "arguments": args or {}, "_meta": META,
    })
    text = next((part.get("text") for part in response.get("content", [])
                 if part.get("type") == "text"), None)
    try:
        value = json.loads(text) if text else {}
    except (TypeError, ValueError):
        value = {"text": text}
    return response, value


def require_ok(url: str, name: str, args: dict | None = None) -> tuple[dict, dict]:
    response, value = tool(url, name, args)
    if response.get("isError"):
        raise RuntimeError(f"{name}: {str(value)[:200]}")
    return response, value


def wait_for_text(url: str, target_id: str, text: str) -> None:
    until = time.monotonic() + 14
    while time.monotonic() < until:
        try:
            _response, value = require_ok(
                url, "browser_page_text", {"target_id": target_id},
            )
            if text in value.get("text", ""):
                return
        except (RuntimeError, OSError):
            pass
        time.sleep(0.25)
    raise AssertionError("Browser page did not show the expected synthetic marker")


def cookie_value(cdp_port: int, target_id: str) -> str:
    import websocket
    with OPENER.open(f"http://127.0.0.1:{cdp_port}/json/list", timeout=3) as response:
        targets = json.load(response)
    selected = next(item for item in targets if item.get("id") == target_id)
    ws = selected["webSocketDebuggerUrl"]
    if not ws.startswith(f"ws://127.0.0.1:{cdp_port}/"):
        raise AssertionError("Unexpected browser WebSocket address")
    connection = websocket.create_connection(
        ws, timeout=8, enable_multithread=True, suppress_origin=True,
    )
    try:
        connection.send(json.dumps({
            "id": 7,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.cookie", "returnByValue": True},
        }))
        for _ in range(50):
            result = json.loads(connection.recv())
            if result.get("id") == 7:
                return result["result"]["result"].get("value", "")
        raise RuntimeError("CDP cookie read timed out")
    finally:
        connection.close()


def memory_available_mib() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return -1


def main() -> None:
    chrome = os.environ.get("CHROMIUM_BIN") or next(
        (exe for name in ("chromium", "google-chrome-stable",
                         "google-chrome", "chromium-browser")
         if (exe := shutil.which(name))), None,
    )
    if not chrome:
        raise SystemExit("Chrome/Chromium not found: set CHROMIUM_BIN to an executable path")
    if shutil.which("xvfb-run") is None:
        raise SystemExit("xvfb-run not found; the GUI test cannot run")

    print("[INFO] No production gateway or CDP port is modified", flush=True)
    baseline = memory_available_mib()
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="hackbrowser-oci-isolation-") as temp:
            manager = IsolatedBackends(Path(temp), max_sessions=2, chromium=chrome)
            manager.bridge_python = Path(sys.executable)
            manager.server = SOURCE_ROOT / "services/hackbrowser/server.py"
            a_key = b_key = None
            try:
                a_url, a_key = manager.acquire("smoke-issuer:synthetic-alice")
                b_url, b_key = manager.acquire("smoke-issuer:synthetic-bob")
                a_port = manager.pool._sessions[a_key].port
                b_port = manager.pool._sessions[b_key].port
                assert a_url != b_url and a_port != b_port
                assert a_port != 9223 and b_port != 9223
                print("[PASS] Independent browser and MCP ports", flush=True)

                for url, port in ((a_url, a_port), (b_url, b_port)):
                    _resp, status = require_ok(url, "browser_status")
                    assert status["connected"] is True
                    assert status["cdp"] == f"http://127.0.0.1:{port}"
                print("[PASS] Both real MCP bridges connect to their own Chromium", flush=True)

                _resp, a_tabs = require_ok(a_url, "browser_tabs")
                _resp, b_tabs = require_ok(b_url, "browser_tabs")
                a_target = a_tabs[0]["target_id"]
                b_target = b_tabs[0]["target_id"]
                assert a_target != b_target
                base = f"http://127.0.0.1:{server.server_address[1]}"
                require_ok(a_url, "browser_navigate", {
                    "url": base + "/alice", "target_id": a_target,
                })
                require_ok(b_url, "browser_navigate", {
                    "url": base + "/bob", "target_id": b_target,
                })
                wait_for_text(a_url, a_target, "SYNTHETIC-ALICE")
                wait_for_text(b_url, b_target, "SYNTHETIC-BOB")
                assert "tenant=SYNTHETIC-ALICE" in cookie_value(a_port, a_target)
                assert "tenant=SYNTHETIC-BOB" in cookie_value(b_port, b_target)
                assert "ALICE" not in cookie_value(b_port, b_target)
                print("[PASS] Independent page content and browser cookies", flush=True)

                cross, _ = tool(b_url, "browser_page_text", {"target_id": a_target})
                assert cross.get("isError") is True
                print("[PASS] Cross-user target ID refused", flush=True)

                _resp, handoff = require_ok(a_url, "browser_handoff_begin", {
                    "target_id": a_target,
                })
                token = handoff["control_token"]
                try:
                    cross, _ = tool(b_url, "browser_handoff_end", {
                        "control_token": token,
                    })
                    assert cross.get("isError") is True
                finally:
                    require_ok(a_url, "browser_handoff_end", {
                        "control_token": token,
                    })
                print("[PASS] Cross-user handoff token refused", flush=True)

                images = []
                for url, target in ((a_url, a_target), (b_url, b_target)):
                    response, _ = require_ok(
                        url, "browser_screenshot", {"target_id": target},
                    )
                    img = next(x for x in response["content"]
                               if x.get("type") == "image")
                    data = base64.b64decode(img["data"], validate=True)
                    assert data.startswith(PNG)
                    images.append(data)
                assert images[0] != images[1]
                print("[PASS] Distinct real screenshots returned", flush=True)

                try:
                    manager.acquire("smoke-issuer:synthetic-charlie")
                except RuntimeError as exc:
                    assert "limit" in str(exc).lower()
                else:
                    raise AssertionError("Third user unexpectedly acquired a browser")
                print("[PASS] Third-user capacity limit fails closed", flush=True)

                now = memory_available_mib()
                if baseline >= 0 and now >= 0:
                    print(f"[INFO] Approximate MemAvailable delta: {baseline - now} MiB", flush=True)
                print("[RESULT] Browser/MCP process isolation smoke PASSED", flush=True)
                print("[NOTE] Keycloak JWT end-to-end isolation NOT tested", flush=True)
            finally:
                if a_key:
                    manager.release(a_key)
                if b_key:
                    manager.release(b_key)
                manager.shutdown()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
