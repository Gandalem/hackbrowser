"""Read-only discovery and explicit browser actions over a local Electron CDP endpoint.

This is a sidecar for hackbrowser/hackbrowser, not a modification of its old code.
Never expose CDP or the unauthenticated MCP endpoint to the public Internet.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import threading
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
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SCREENSHOT_UI_URI = "ui://hackbrowser/screenshot.html"
# A modest per-site navigation gap prevents accidental bursts. It does not
# spoof browser identity or circumvent a site's access control.
MIN_NAVIGATION_INTERVAL_SECONDS = 4.0
# If a site explicitly denies automated access, do not repeatedly hammer it.
ACCESS_COOLDOWN_SECONDS = 30 * 60
_access_lock = threading.Lock()
_next_navigation_at: dict[str, float] = {}
_restricted_until: dict[str, float] = {}

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


def _restriction_reason(url: str, text: str) -> str | None:
    """Classify explicit access-denial pages, not ordinary empty or slow pages."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host.endswith(".naver.com") and (
        "쇼핑 서비스 접속이 일시적으로 제한되었습니다." in text
        or "검색 서비스 이용이 제한되었습니다." in text
    ):
        return "네이버의 접속 제한 안내가 표시됨"
    if (host == "google.com" or host.endswith(".google.com")) and (
        parsed.path.startswith("/sorry/")
        or "Our systems have detected unusual traffic from your computer network" in text
    ):
        return "Google에서 비정상 트래픽 확인을 요구함"
    if (host == "gmarket.co.kr" or host.endswith(".gmarket.co.kr")) and (
        "봇 확인 절차가 진행되고 있습니다" in text
    ):
        return "G마켓에서 방문자 확인을 요구함"
    return None


def _site_key(host: str) -> str:
    """Treat Naver Shopping's home and search subdomains as one rate-limit scope."""
    if host == "shopping.naver.com" or host.endswith(".shopping.naver.com"):
        return "shopping.naver.com"
    return host


def _record_restriction(url: str) -> int:
    host = urlsplit(url).hostname
    if not host:
        return 0
    key = _site_key(host)
    with _access_lock:
        now = time.monotonic()
        previous = _restricted_until.get(key, 0.0)
        if previous > now:
            # Reading the same blocked page should not reset the cooldown.
            return int(previous - now) + 1
        _restricted_until[key] = now + ACCESS_COOLDOWN_SECONDS
    return ACCESS_COOLDOWN_SECONDS


def _pace_navigation(host: str) -> None:
    """Reserve a non-burst navigation slot; never retry a denied origin."""
    key = _site_key(host)
    with _access_lock:
        now = time.monotonic()
        remaining = _restricted_until.get(key, 0.0) - now
        if remaining > 0:
            raise RuntimeError(
                f"{host}: 접속 제한이 확인되어 재요청을 중단했습니다 "
                f"(남은 대기 {int(remaining) + 1}초). 차단 우회 대신 사이트의 "
                "공식 확인·고객센터 절차를 이용하세요."
            )
        delay = max(0.0, _next_navigation_at.get(key, now) - now)
        _next_navigation_at[key] = now + delay + MIN_NAVIGATION_INTERVAL_SECONDS
    if delay:
        time.sleep(delay)
    # A concurrent tool call may have detected a restriction while we waited.
    with _access_lock:
        remaining = _restricted_until.get(key, 0.0) - time.monotonic()
        if remaining > 0:
            raise RuntimeError(
                f"{host}: 접속 제한을 확인해 페이지 이동을 중단했습니다 "
                f"(남은 대기 {int(remaining) + 1}초)."
            )



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
    _pace_navigation(parsed.hostname.lower())
    result = _cdp("Page.navigate", {"url": url}, selected["id"])
    if result.get("errorText"):
        raise RuntimeError(result["errorText"])
    return {"target_id": selected["id"], "requested_url": url, "navigation_started": True}


@mcp.tool()
def browser_page_text(target_id: str | None = None, max_chars: int = 12000) -> dict:
    """Read visible page text and title (up to 30,000 characters) from an open tab."""
    max_chars = max(1, min(max_chars, 30_000))
    # Inspect enough text to recognize a site restriction, even if the
    # caller requested only a very short visible-text preview.
    probe_chars = max(max_chars, 2000)
    expression = """(function () { return {
      url: location.href,
      title: document.title,
      text: (document.body ? document.body.innerText : '').slice(0, %d)
    }; })()""" % probe_chars
    value = _evaluate(expression, target_id)
    if not isinstance(value, dict):
        return {"result": value}
    text = value.get("text", "")
    url = value.get("url", "")
    reason = _restriction_reason(url, text) if isinstance(url, str) and isinstance(text, str) else None
    if isinstance(text, str):
        value["text"] = text[:max_chars]
    if reason:
        value["access_status"] = "restricted"
        value["restriction_reason"] = reason
        value["retry_after_seconds"] = _record_restriction(url)
    else:
        value["access_status"] = "ok"
    return value


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
    selected = _target(target_id)
    current_host = urlsplit(selected.get("url", "")).hostname
    if current_host:
        _pace_navigation(current_host.lower())
    expression = """(function(){
      var el=document.querySelector(%s);
      if(!el)return {ok:false,error:'No element matches selector'};
      el.click(); return {ok:true};
    })()""" % json.dumps(selector)
    value = _evaluate(expression, selected["id"])
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


@mcp.tool(meta={"ui": {"resourceUri": SCREENSHOT_UI_URI}, "openai/outputTemplate": SCREENSHOT_UI_URI})
def browser_screenshot(target_id: str | None = None) -> list[TextContent | ImageContent]:
    """Capture a PNG and return it directly to the MCP Apps inline viewer."""
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

    metadata = {"bytes": len(png), "mime_type": "image/png"}
    return [
        TextContent(type="text", text=json.dumps(metadata)),
        ImageContent(type="image", data=encoded, mime_type="image/png"),
    ]


if __name__ == "__main__":
    # Bind localhost only. For remote access use SSH forwarding or an authenticated HTTPS reverse proxy.
    mcp.run(transport="streamable-http", host="127.0.0.1", port=MCP_PORT, json_response=True)
