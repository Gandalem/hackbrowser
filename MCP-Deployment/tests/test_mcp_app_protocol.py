"""Integration regression: screenshot remains callable via legacy MCP discovery."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

SERVER = Path(__file__).resolve().parent.parent / "services/hackbrowser/server.py"
UI_URI = "ui://hackbrowser/screenshot.html"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {
        "name": "screenshot-ci-regression", "version": "1.0"
    },
}


def rpc(port: int, method: str, params: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Method": method,
        "MCP-Protocol-Version": "2026-07-28",
    }
    if method == "resources/read":
        headers["Mcp-Name"] = params["uri"]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=6) as response:
        raw = response.read().decode()
    if raw.lstrip().startswith(("event:", "data:")):
        raw = next(line[5:].strip() for line in raw.splitlines() if line.startswith("data:"))
    answer = json.loads(raw)
    if "error" in answer:
        raise RuntimeError(f"{method}: {str(answer['error'])[:180]}")
    return answer.get("result", {})


class ScreenshotAppProtocolTests(unittest.TestCase):
    def test_screenshot_tool_and_ui_visible_over_mcp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = dict(os.environ, HACKBROWSER_MCP_PORT=str(port))
        process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(35):
                if process.poll() is not None:
                    raise RuntimeError("MCP process exited before handshake")
                try:
                    discovery = rpc(port, "server/discover", {"_meta": META})
                    break
                except (OSError, ValueError, RuntimeError, StopIteration):
                    time.sleep(0.2)
            else:
                self.fail("MCP staging endpoint did not become ready")
            self.assertIn("io.modelcontextprotocol/ui", str(discovery))
            tools = rpc(port, "tools/list", {"_meta": META})["tools"]
            names = [tool["name"] for tool in tools]
            self.assertEqual(len(names), 22)
            for name in ("browser_screenshot", "browser_keypress", "browser_scroll", "browser_wait_for", "browser_submit_verification",
                         "browser_click_text", "browser_fill_and_submit", "browser_click_at",
                         "browser_workflow_start", "browser_workflow_resume",
                         "browser_workflow_status", "browser_close_tabs",
                         "browser_observe", "browser_act"):
                self.assertIn(name, names)
            screenshot = next(tool for tool in tools if tool["name"] == "browser_screenshot")
            self.assertEqual(screenshot["_meta"]["ui"]["resourceUri"], UI_URI)
            ui = rpc(port, "resources/read", {"uri": UI_URI, "_meta": META})
            contents = ui.get("contents", [])
            self.assertTrue(any(
                item.get("mimeType") == "text/html;profile=mcp-app"
                and "data:image/png;base64," in item.get("text", "")
                for item in contents
            ))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
