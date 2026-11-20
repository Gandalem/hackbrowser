"""Read-only discovery and explicit browser actions over a local Electron CDP endpoint.

This is a sidecar for hackbrowser/hackbrowser, not a modification of its old code.
Never expose CDP or the unauthenticated MCP endpoint to the public Internet.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import websocket
from mcp.server import MCPServer
from mcp.server.apps import Apps
from mcp.types import ImageContent, TextContent

CDP_PORT = int(os.environ.get("HACKBROWSER_CDP_PORT", "9222"))
MCP_PORT = int(os.environ.get("HACKBROWSER_MCP_PORT", "8765"))
CDP_HOST = "127.0.0.1"
CDP_ROOT = f"http://{CDP_HOST}:{CDP_PORT}"
SCREENSHOT_DIR = Path(os.environ.get("HACKBROWSER_SCREENSHOT_DIR", str(Path.home() / "hackbrowser-mcp-screenshots")))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SCREENSHOT_UI_URI = "ui://hackbrowser/screenshot.html"
SCREENSHOT_UI_MIME = "text/html;profile=mcp-app"

apps = Apps()
apps.add_html_resource(
    SCREENSHOT_UI_URI,
    Path(__file__).with_name("screenshot_widget.html").read_text(encoding="utf-8"),
    title="HackBrowser screenshot preview",
)
mcp = MCPServer("HackBrowser Local CDP Bridge", extensions=[apps])
_opener = build_opener(ProxyHandler({}))


def _targets() -> list[dict]:
    """Get only locally exposed DevTools targets; never accept arbitrary CDP URLs."""
    req = Request(CDP_ROOT + "/json/list", headers={"Accept": "application/json"})
    try:
        with _opener.open(req, timeout=3) as response:
            raw = response.read(2_000_000)
    except OSError as exc:
        raise RuntimeError(
            f"HackBrowser CDP unavailable on {CDP_ROOT}. "
            "Start HackBrowser with --remote-debugging-port=9222. "
            f"Details: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Unexpected CDP /json/list response") from exc
    if not isinstance(data, list):
        raise RuntimeError("CDP /json/list must return a JSON array")
    return [
        t for t in data
        if isinstance(t, dict)
        and t.get("type") in {"page", "webview"}
        and isinstance(t.get("id"), str)
        and isinstance(t.get("webSocketDebuggerUrl"), str)
    ]


def _target(target_id: str | None) -> dict:
    targets = _targets()
    if target_id:
        selected = next((t for t in targets if t["id"] == target_id), None)
        if selected is None:
            raise ValueError(f"Unknown target_id: {target_id}. First call browser_tabs().")
        return selected
    # Avoid accidentally replacing the app's internal file:// browser UI.
    visible = [
        t for t in targets
        if str(t.get("url", "")).startswith(("http://", "https://", "about:blank"))
    ]
    if not visible:
        raise RuntimeError("No external web page target. Open a page in HackBrowser and call browser_tabs().")
    return visible[0]


def _cdp(method: str, params: dict | None = None, target_id: str | None = None) -> dict:
    target = _target(target_id)
    ws_url = target["webSocketDebuggerUrl"]
    parsed = urlsplit(ws_url)
    if parsed.scheme != "ws" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != CDP_PORT:
        raise RuntimeError("CDP returned a non-local WebSocket URL; refusing connection")

    conn = None
    try:
        conn = websocket.create_connection(ws_url, timeout=8, enable_multithread=True, suppress_origin=True)
        conn.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                response = json.loads(conn.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if response.get("id") != 1:
                continue
            if "error" in response:
                raise RuntimeError(f"CDP {method}: {response['error']}")
            return response.get("result", {})
        raise TimeoutError(f"CDP {method} did not respond in time")
    except (OSError, websocket.WebSocketException) as exc:
        raise RuntimeError(f"CDP transport error: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _evaluate(expression: str, target_id: str | None = None):
    response = _cdp(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
        target_id,
    )
    if response.get("exceptionDetails"):
        details = response["exceptionDetails"]
        raise RuntimeError(f"Browser JavaScript error: {details.get('text', 'unknown')}")
    remote = response.get("result", {})
    if "value" in remote:
        return remote["value"]
    if remote.get("type") == "undefined":
        return None
    return remote.get("description", "")


@mcp.tool()
def browser_status() -> dict:
    """Check whether HackBrowser exposes a local Chrome DevTools Protocol endpoint."""
    try:
        tabs = _targets()
        return {"connected": True, "cdp": CDP_ROOT, "target_count": len(tabs)}
    except Exception as exc:
        return {"connected": False, "cdp": CDP_ROOT, "error": str(exc)}


@mcp.tool()
def browser_tabs() -> list[dict]:
    """List tabs/webviews with their target_id, title, and URL."""
    return [
        {"target_id": t["id"], "type": t.get("type"), "title": t.get("title", ""), "url": t.get("url", "")}
        for t in _targets()
    ]


@mcp.tool()
def browser_navigate(url: str, target_id: str | None = None) -> dict:
    """Navigate a tab to an explicitly supplied HTTP(S) URL. Does not bypass security controls."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are allowed")
    selected = _target(target_id)
    result = _cdp("Page.navigate", {"url": url}, selected["id"])
    if result.get("errorText"):
        raise RuntimeError(result["errorText"])
    return {"target_id": selected["id"], "requested_url": url, "navigation_started": True}


@mcp.tool()
def browser_page_text(target_id: str | None = None, max_chars: int = 12000) -> dict:
    """Read visible page text and title (up to 30,000 characters) from an open tab."""
    max_chars = max(1, min(max_chars, 30_000))
    expression = """(function () { return {
      url: location.href,
      title: document.title,
      text: (document.body ? document.body.innerText : '').slice(0, %d)
    }; })()""" % max_chars
    value = _evaluate(expression, target_id)
    return value if isinstance(value, dict) else {"result": value}


@mcp.tool()
def browser_elements(target_id: str | None = None, max_items: int = 30) -> dict:
    """List links and input selectors for the currently open page."""
    max_items = max(1, min(max_items, 100))
    expression = """(function(){
      var links = Array.prototype.slice.call(document.querySelectorAll('a[href]'),0,%d)
        .map(function(el){return {text:(el.innerText||'').slice(0,90),href:el.href};});
      var inputs = Array.prototype.slice.call(document.querySelectorAll('input,textarea,button'),0,%d)
        .map(function(el){return {tag:el.tagName.toLowerCase(),id:el.id||'',name:el.name||'',type:el.type||'',placeholder:el.placeholder||''};});
      return {links:links,inputs:inputs};
    })()""" % (max_items, max_items)
    value = _evaluate(expression, target_id)
    return value if isinstance(value, dict) else {"result": value}


@mcp.tool()
def browser_click(selector: str, target_id: str | None = None) -> dict:
    """Click one CSS-selector-matched element in the current page."""
    if not selector or len(selector) > 512:
        raise ValueError("selector must contain 1-512 characters")
    expression = """(function(){
      var el=document.querySelector(%s);
      if(!el)return {ok:false,error:'No element matches selector'};
      el.click(); return {ok:true};
    })()""" % json.dumps(selector)
    value = _evaluate(expression, target_id)
    return value if isinstance(value, dict) else {"result": value}


@mcp.tool()
def browser_fill(selector: str, value: str, target_id: str | None = None) -> dict:
    """Set a text input by CSS selector and dispatch input/change events. Does not log value."""
    if not selector or len(selector) > 512 or len(value) > 10_000:
        raise ValueError("Invalid selector or value too long")
    expression = """(function(){
      var el=document.querySelector(%s);
      if(!el)return {ok:false,error:'No element matches selector'};
      if(!('value' in el))return {ok:false,error:'Not an input element'};
      el.focus();
      var proto=Object.getPrototypeOf(el);
      var descriptor=Object.getOwnPropertyDescriptor(proto,'value');
      if(descriptor&&descriptor.set)descriptor.set.call(el,%s);
      else el.value=%s;
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return {ok:true};
    })()""" % (json.dumps(selector), json.dumps(value), json.dumps(value))
    result = _evaluate(expression, target_id)
    return result if isinstance(result, dict) else {"result": result}


@apps.tool(resource_uri=SCREENSHOT_UI_URI, meta={"openai/outputTemplate": SCREENSHOT_UI_URI})
def browser_screenshot(target_id: str | None = None) -> list[TextContent | ImageContent]:
    """Capture a PNG, save a private local copy and return the image inline to the MCP client."""
    result = _cdp("Page.captureScreenshot", {"format": "png"}, target_id)
    encoded = result.get("data")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("CDP screenshot returned no image data")
    # Avoid decoding unexpectedly huge server responses. Base64 is roughly 4/3 the binary size.
    if len(encoded) > ((MAX_SCREENSHOT_BYTES + 2) // 3) * 4 + 4:
        raise RuntimeError("Screenshot exceeds the 8 MiB limit")
    try:
        png = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("CDP screenshot returned invalid base64") from exc
    if not png.startswith(PNG_SIGNATURE):
        raise RuntimeError("CDP screenshot is not a PNG")
    if len(png) > MAX_SCREENSHOT_BYTES:
        raise RuntimeError("Screenshot exceeds the 8 MiB limit")

    SCREENSHOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # 192 bits of entropy make the short-lived download URL unguessable.
    filename = f"hb-{secrets.token_hex(24)}.png"
    output = SCREENSHOT_DIR / filename
    # Create a private file and never overwrite an earlier capture.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as capture:
        capture.write(png)

    metadata = {"saved_path": str(output), "bytes": len(png), "mime_type": "image/png"}
    if PUBLIC_BASE_URL:
        metadata["download_url"] = f"{PUBLIC_BASE_URL}/captures/{filename}"
        metadata["expires_in_seconds"] = 600
    return [
        TextContent(type="text", text=json.dumps(metadata)),
        ImageContent(type="image", data=encoded, mime_type="image/png"),
    ]


if __name__ == "__main__":
    # Bind localhost only. For remote access use SSH forwarding or an authenticated HTTPS reverse proxy.
    mcp.run(transport="streamable-http", host="127.0.0.1", port=MCP_PORT, json_response=True)
