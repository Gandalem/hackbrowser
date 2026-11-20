"""Browser discovery and explicit actions over the local GUI Chromium CDP endpoint.

This is a sidecar for hackbrowser/hackbrowser, not a modification of its old code.
Never expose CDP or the unauthenticated MCP endpoint to the public Internet.
"""
from __future__ import annotations

import base64
import binascii
import importlib
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import websocket
from mcp.server import MCPServer
from mcp.server.apps import Apps
from mcp.types import ImageContent, TextContent

# Tests also load this module directly from a path rather than as a package.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from handoff import manual_handoff as _manual_handoff

_handoff_input_local = threading.local()

CDP_PORT = 9223
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
VERIFICATION_TTL_SECONDS = 5 * 60
MAX_VERIFICATION_ANSWER_CHARS = 64
_verification_lock = threading.Lock()
_verification_sessions: dict[str, dict] = {}
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
            "Start GUI Chromium with --remote-debugging-port=9223. "
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
        raise RuntimeError("No external web page target. Open a page in GUI Chromium and call browser_tabs().")
    return visible[0]


def _cdp(method: str, params: dict | None = None, target_id: str | None = None) -> dict:
    with _manual_handoff.lock:
        if (method not in {"Runtime.evaluate", "Page.captureScreenshot"} and
                not getattr(_handoff_input_local, "user_authorized", False)):
            _manual_handoff.assert_ai_allowed()
        return _cdp_raw(method, params, target_id)


def _cdp_raw(method: str, params: dict | None = None, target_id: str | None = None) -> dict:
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


_tab_cleanup_lock = threading.Lock()


def _browser_cdp(method: str, params: dict | None = None) -> dict:
    with _manual_handoff.lock:
        _manual_handoff.assert_ai_allowed()
        return _browser_cdp_raw(method, params)


def _browser_cdp_raw(method: str, params: dict | None = None) -> dict:
    """Send a fixed, server-owned CDP command via LOCAL browser WebSocket.

    No user-supplied CDP methods or socket URLs are accepted by MCP tools.
    Browser-level Target.closeTarget works independently of a closing page's
    WebSocket, so tab closure does not race the command response.
    """
    req = Request(CDP_ROOT + "/json/version", headers={"Accept": "application/json"})
    try:
        with _opener.open(req, timeout=3) as response:
            info = json.loads(response.read(65536))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Local GUI Chromium browser endpoint unavailable") from exc
    ws_url = info.get("webSocketDebuggerUrl") if isinstance(info, dict) else None
    if not isinstance(ws_url, str):
        raise RuntimeError("No browser-level DevTools WebSocket was returned")
    parsed = urlsplit(ws_url)
    if (parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port != CDP_PORT
            or not parsed.path.startswith("/devtools/browser/")
            or parsed.username or parsed.password):
        raise RuntimeError("Refusing non-local or non-browser DevTools endpoint")
    conn = None
    try:
        conn = websocket.create_connection(
            ws_url, timeout=8, enable_multithread=True, suppress_origin=True,
        )
        conn.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                message = json.loads(conn.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("id") != 1:
                continue
            if "error" in message:
                raise RuntimeError(f"Browser CDP {method} failed: {message['error']}")
            return message.get("result", {})
        raise TimeoutError(f"Browser CDP {method} did not respond")
    except (OSError, websocket.WebSocketException) as exc:
        raise RuntimeError(f"Browser CDP transport error: {type(exc).__name__}") from exc
    finally:
        if conn is not None:
            conn.close()


def _evaluate(expression: str, target_id: str | None = None,
              await_promise: bool = False):
    parameters = {"expression": expression, "returnByValue": True}
    if await_promise:
        parameters["awaitPromise"] = True
    response = _cdp("Runtime.evaluate", parameters, target_id)
    if response.get("exceptionDetails"):
        details = response["exceptionDetails"]
        raise RuntimeError(f"Browser JavaScript error: {details.get('text', 'unknown')}")
    remote = response.get("result", {})
    if "value" in remote:
        return remote["value"]
    if remote.get("type") == "undefined":
        return None
    return remote.get("description", "")


def _gui_action(selected: dict, action: str, args: dict) -> dict:
    """Use the existing GUI CDP session; never spawn or reset Chromium."""
    _manual_handoff.assert_ai_allowed()
    from playwright_control import run_action
    return run_action(CDP_ROOT, selected, action, args, _targets)


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


def _verification_reason(url: str, text: str) -> str | None:
    """Separate a user-solvable challenge from an explicit access denial."""
    host = (urlsplit(url).hostname or "").lower()
    if (host == "naver.com" or host.endswith(".naver.com")) and (
        "Please complete the security verification." in text
    ):
        return "네이버에서 사용자 확인을 요구함"
    return None


def _verification_state(target_id: str) -> dict:
    """Inspect challenge indicators, never attempt to solve a CAPTCHA."""
    value = _evaluate("""(function(){
      var frames=Array.from(document.querySelectorAll('iframe[src]'));
      var recaptcha=frames.some(function(f){
        try { return /(^|\\.)google\\.com$|(^|\\.)recaptcha\\.net$/.test(new URL(f.src).hostname) &&
          /\\/recaptcha\\/api2\\//.test(new URL(f.src).pathname); }
        catch (_) { return false; }
      });
      var response=document.querySelector('textarea[name="g-recaptcha-response"]');
      return {
        url:location.href,
        text:(document.body?document.body.innerText:'').slice(0,4000),
        viewport:{width:innerWidth,height:innerHeight},
        recaptcha_present:recaptcha,
        recaptcha_completed:!!(response && response.value && response.value.trim())
      };
    })()""", target_id)
    if not isinstance(value, dict):
        return {}
    reason = _verification_reason(value.get("url", ""), value.get("text", ""))
    completed = bool(value.get("recaptcha_present") and value.get("recaptcha_completed"))
    if value.get("recaptcha_present") and not completed and not reason:
        reason = "Google reCAPTCHA: 화면에서 사용자가 직접 확인해야 합니다"
    return {"url": value.get("url", ""), "viewport": value.get("viewport", {}),
            "verification_reason": None if completed else reason,
            "verification_completed": completed}



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


def _check_access_only(host: str) -> None:
    """Check a previously detected site denial without reserving a navigation slot."""
    with _access_lock:
        remaining = _restricted_until.get(_site_key(host), 0.0) - time.monotonic()
    if remaining > 0:
        raise RuntimeError(
            f"{host}: 접속 제한이 확인되어 조작을 중단했습니다 "
            f"(남은 대기 {int(remaining) + 1}초)."
        )


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




# A bounded navigation-only workflow may pause for manual user authentication.
# This manager holds no passwords, CAPTCHA answers or persistent browser profile.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
_workflow_module = importlib.import_module('workflow_engine')
WorkflowManager = _workflow_module.WorkflowManager
safe_public_url = _workflow_module.safe_public_url


def _workflow_gate(target_id: str) -> dict:
    """Verify the same GUI tab, its public URL and current access state."""
    target = _target(target_id)
    url = target.get("url", "")
    if not safe_public_url(url):
        return {"state": "unsafe_page"}
    current = browser_page_text(target_id=target_id, max_chars=2500)
    status = current.get("access_status")
    if status == "restricted":
        return {"state": "restricted"}
    if status == "verification_required":
        return {"state": "verification_required"}
    vstate = _verification_state(target_id)
    if vstate.get("verification_reason"):
        return {"state": "verification_required"}
    actual_url = current.get("url", url)
    hostname = (urlsplit(actual_url).hostname or "").lower()
    pathname = (urlsplit(actual_url).path or "").lower()
    # Login belongs to the user. Never press sign-in or fill credentials.
    if ("login" in hostname.split(".") or
            pathname.startswith(("/login", "/signin", "/auth/login", "/nidlogin"))):
        return {"state": "login_required"}
    if not safe_public_url(actual_url):
        return {"state": "unsafe_page"}
    return {"state": "ok"}


def _workflow_execute(target_id: str, step: dict) -> dict:
    """Dispatch only the explicitly whitelisted browsing operations."""
    op = step["op"]
    if op == "navigate":
        original_url = _target(target_id).get("url", "")
        result = browser_navigate(url=step["url"], target_id=target_id)
        if not result.get("navigation_started"):
            return {"ok": False}
        # Page.navigate only confirms a request was initiated. Wait until the
        # actual tab URL changes, including redirects to a login challenge.
        # Never start the next workflow operation on the previous document.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = browser_page_text(target_id=target_id, max_chars=500)
            final_url = current.get("url", "")
            if final_url == step["url"] or final_url != original_url:
                return {"ok": True, "next_target_id": target_id,
                        "observed_url": final_url}
            time.sleep(0.2)
        return {"ok": False, "error": "Navigation did not leave the previous page"}
    if op == "wait":
        result = browser_wait_for(
            selector=step.get("selector"), text=step.get("text"),
            timeout_seconds=step["timeout_seconds"], target_id=target_id,
        )
        return {"ok": bool(result.get("ok"))}
    if op == "scroll":
        result = browser_scroll(
            direction=step["direction"], pixels=step["pixels"],
            target_id=target_id,
        )
        return {"ok": bool(result.get("ok")), "moved": result.get("moved")}
    target = _target(target_id)
    host = urlsplit(target.get("url", "")).hostname
    if host:
        _pace_navigation(host.lower())
    if op == "click_link":
        arguments = {
            key: value for key, value in step.items()
            if key in {"selector", "text", "container_selector"}
        }
        return _gui_action(target, "safe_link", arguments)
    if op == "search":
        return _gui_action(
            target, "safe_search", {
                "selector": step["selector"], "text": step["text"],
            }
        )
    raise ValueError("Unsupported workflow operation")


_workflows = WorkflowManager(_workflow_gate, _workflow_execute)


@mcp.tool()
def browser_workflow_start(steps: list[dict], target_id: str) -> dict:
    """Run up to three of eight whitelisted browsing steps. Pause at challenges.

    Operations: navigate public URL, GET search, safe link click, wait, scroll.
    Payments, state-changing submissions, credential entry and CAPTCHA solving
    are never run by workflows. Next batches need an explicit resume call.
    """
    _manual_handoff.assert_ai_allowed()
    return _workflows.start(steps, target_id)


@mcp.tool()
def browser_workflow_resume(workflow_id: str) -> dict:
    """After manual verification, resume next safe steps, never replaying clicks."""
    _manual_handoff.assert_ai_allowed()
    return _workflows.resume(workflow_id)


@mcp.tool()
def browser_workflow_status(workflow_id: str) -> dict:
    """Inspect a bounded workflow and its next step without executing actions."""
    return _workflows.get(workflow_id)


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
def browser_close_tabs(target_ids: list[str], keep_one_blank: bool = True) -> dict:
    """Close ONLY explicitly identified, currently open GUI Chromium tabs.

    The caller must list exact target IDs from browser_tabs(). When all tabs
    are selected, keep a new about:blank page so Chromium/CDP remains running.
    Never clear cookies, kill Chromium or reset its GUI profile.
    """
    if (not isinstance(target_ids, list) or not 1 <= len(target_ids) <= 20
            or any(not isinstance(t, str) or not t for t in target_ids)
            or len(set(target_ids)) != len(target_ids)):
        raise ValueError("Provide 1-20 unique target IDs from browser_tabs()")
    if not isinstance(keep_one_blank, bool):
        raise ValueError("keep_one_blank must be a boolean")

    with _tab_cleanup_lock:
        before = _targets()
        current = {tab["id"]: tab for tab in before}
        unknown = [tid for tid in target_ids if tid not in current]
        if unknown:
            raise ValueError(
                "One or more target IDs are no longer open; call browser_tabs() again"
            )
        # Only close user-visible page tabs, not browser-internal webviews.
        if any(current[tid].get("type") != "page" for tid in target_ids):
            raise ValueError("Only regular page tabs may be closed")
        new_blank_id = None
        remaining_pages = [
            tab for tab in before
            if tab.get("type") == "page" and tab["id"] not in target_ids
        ]
        if keep_one_blank and not remaining_pages:
            created = _browser_cdp("Target.createTarget", {"url": "about:blank"})
            new_blank_id = created.get("targetId")
            if not isinstance(new_blank_id, str) or not new_blank_id:
                raise RuntimeError("Could not create a safe blank tab; no tabs closed")
        outcomes = []
        for tid in target_ids:
            try:
                response = _browser_cdp("Target.closeTarget", {"targetId": tid})
                outcomes.append({"target_id": tid, "closed": bool(response.get("success"))})
            except (OSError, RuntimeError, TimeoutError):
                # A failed or dropped response is ambiguous, so inspect below.
                outcomes.append({"target_id": tid, "closed": None})
        after = _targets()
        remaining = {tab["id"] for tab in after}
        for item in outcomes:
            item["closed"] = item["target_id"] not in remaining
        return {
            "requested": len(target_ids),
            "closed": sum(1 for item in outcomes if item["closed"]),
            "results": outcomes,
            "remaining_tabs": len(after),
            "remaining_target_ids": [tab["id"] for tab in after],
            "blank_tab_id": new_blank_id,
            "gui_kept_running": True,
        }


@mcp.tool()
def browser_handoff_begin(target_id: str) -> dict:
    """Explicit user takeover of one shared GUI for at most ten minutes.

    The capability token is not user authentication. Only an authenticated
    MCP Apps operator should receive it. User profiles are still shared.
    """
    selected = _target(target_id)
    if selected.get("type") != "page":
        raise ValueError("Manual control requires a regular GUI browser tab")
    with _manual_handoff.lock:
        viewport = _evaluate(
            "({width: innerWidth, height: innerHeight})", selected["id"]
        )
        return _manual_handoff.begin(selected["id"], viewport)


@mcp.tool()
def browser_handoff_status() -> dict:
    """Read-only takeover status without exposing the control token."""
    return _manual_handoff.status()


@mcp.tool()
def browser_handoff_input(control_token: str, target_id: str, action: str,
                          x: int = 0, y: int = 0, pixels: int = 400) -> dict:
    """One user-triggered click or scroll during a manual takeover.

    No text typing, keys, arbitrary scripts, or CAPTCHA automation.
    """
    if action not in {"click", "scroll_up", "scroll_down"}:
        raise ValueError("Only click and vertical scroll are supported")
    if type(x) is not int or type(y) is not int or type(pixels) is not int:
        raise ValueError("Coordinates and pixels must be integers")
    if not 1 <= pixels <= 1200:
        raise ValueError("Scroll pixels must be 1-1200")
    with _manual_handoff.lock:
        viewport = _manual_handoff.authenticate(control_token, target_id)
        state = _verification_state(target_id)
        if state.get("verification_reason"):
            raise RuntimeError(
                "Manual verification detected; use the existing CAPTCHA card"
            )
        selected = _target(target_id)
        if selected.get("type") != "page":
            raise RuntimeError("The selected GUI tab is no longer available")
        live_viewport = _evaluate(
            "({width: innerWidth, height: innerHeight})", target_id
        )
        if live_viewport != viewport:
            raise ValueError("Viewport changed; end takeover and recapture")
        _handoff_input_local.user_authorized = True
        try:
            if action == "click":
                if not (0 <= x < viewport["width"] and 0 <= y < viewport["height"]):
                    raise ValueError("Click must be within the GUI viewport")
                _click_at(target_id, x, y)
            else:
                delta = pixels if action == "scroll_down" else -pixels
                _cdp("Input.dispatchMouseEvent", {
                    "type": "mouseWheel",
                    "x": viewport["width"] // 2, "y": viewport["height"] // 2,
                    "deltaX": 0, "deltaY": delta,
                }, target_id)
        finally:
            _handoff_input_local.user_authorized = False
        return {"ok": True, "action": action, "target_id": target_id,
                "message": "User input sent once. Refresh the screenshot to confirm."}


@mcp.tool()
def browser_handoff_end(control_token: str) -> dict:
    """Return GUI control to AI after a user finishes."""
    return _manual_handoff.finish(control_token)


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
    if isinstance(text, str):
        value["text"] = text[:max_chars]
    verification = _verification_reason(url, text) if isinstance(url, str) and isinstance(text, str) else None
    reason = _restriction_reason(url, text) if isinstance(url, str) and isinstance(text, str) else None
    if reason:
        value["access_status"] = "restricted"
        value["restriction_reason"] = reason
        value["retry_after_seconds"] = _record_restriction(url)
    elif verification:
        value["access_status"] = "verification_required"
        value["verification_reason"] = verification
        value["action"] = "browser_screenshot으로 채팅 내 수동 입력 화면을 열 수 있습니다."
    else:
        value["access_status"] = "ok"
    return value


@mcp.tool()
def browser_elements(target_id: str | None = None, max_items: int = 30) -> dict:
    """List links and input selectors for the currently open page."""
    max_items = max(1, min(max_items, 100))
    expression = """(function(){
      function visible(el){
        var style=getComputedStyle(el), rect=el.getBoundingClientRect();
        return style.display!=='none' && style.visibility!=='hidden' &&
          rect.width>0 && rect.height>0;
      }
      function selectorFor(el){
        if(el.id){
          var idSelector='#'+CSS.escape(el.id);
          if(document.querySelectorAll(idSelector).length===1)return idSelector;
        }
        var parts=[], node=el;
        while(node && node.nodeType===1 && parts.length<8){
          var tag=node.tagName.toLowerCase();
          if(node.id){
            parts.unshift('#'+CSS.escape(node.id));break;
          }
          var parent=node.parentElement;
          if(parent){
            var siblings=Array.prototype.filter.call(parent.children,function(n){
              return n.tagName===node.tagName;
            });
            if(siblings.length>1)tag+=':nth-of-type('+(siblings.indexOf(node)+1)+')';
          }
          parts.unshift(tag);
          node=parent;
        }
        return parts.join(' > ');
      }
      var links=Array.prototype.filter.call(document.querySelectorAll('a[href]'),visible)
        .slice(0,%d).map(function(el){
          return {text:(el.innerText||el.getAttribute('aria-label')||'').trim().slice(0,90),
            href:el.href,selector:selectorFor(el),role:el.getAttribute('role')||''};
        });
      var inputs=Array.prototype.filter.call(
        document.querySelectorAll('input,textarea,button,select,[role="button"]'),visible)
        .slice(0,%d).map(function(el){
          return {tag:el.tagName.toLowerCase(),id:el.id||'',name:el.name||'',
            type:el.type||'',placeholder:el.placeholder||'',
            label:(el.getAttribute('aria-label')||el.innerText||'').trim().slice(0,90),
            selector:selectorFor(el),disabled:!!el.disabled};
        });
      return {links:links,inputs:inputs};
    })()""" % (max_items, max_items)
    value = _evaluate(expression, target_id)
    return value if isinstance(value, dict) else {"result": value}


@mcp.tool()
def browser_observe(target_id: str | None = None,
                    max_elements: int = 35) -> dict:
    """Observe visible controls with short-lived e1/e2 references.

    Returns title, a short page text preview and ref IDs without exposing
    CSS selectors or field values. Re-observe after page navigation or change.
    """
    selected = _target(target_id)
    page_status = browser_page_text(target_id=selected["id"], max_chars=300)
    if page_status.get("access_status") == "restricted":
        return {"ok": False, "access_status": "restricted",
                "reason": page_status.get("restriction_reason", "Site denied access")}
    return _gui_action(selected, "observe", {"max_elements": max_elements})


@mcp.tool()
def browser_act(snapshot_id: str, ref: str, action: str,
                text: str | None = None, target_id: str | None = None) -> dict:
    """Click a safe navigation control or fill/submit a non-sensitive search.

    Actions are executed on the exact element from browser_observe, with a
    90-second expiry and current-page verification. No payment, account
    change, arbitrary form submission or CAPTCHA automation.
    """
    if (not isinstance(snapshot_id, str) or not 8 <= len(snapshot_id) <= 128
            or not isinstance(ref, str) or not 1 <= len(ref) <= 12):
        raise ValueError("Use a snapshot_id and ref returned by browser_observe")
    if action not in {"click", "fill", "search"}:
        raise ValueError("action must be click, fill, or search")
    if text is not None and (not isinstance(text, str) or len(text) > 160):
        raise ValueError("Search text must contain at most 160 characters")
    selected = _target(target_id)
    current = browser_page_text(target_id=selected["id"], max_chars=500)
    if current.get("access_status") in {"restricted", "verification_required"}:
        return {"ok": False, "error": "Site access or manual verification is required",
                "retry_safe": False}
    host = urlsplit(selected.get("url", "")).hostname
    if host:
        if action in {"click", "search"}:
            _pace_navigation(host.lower())
        else:
            _check_access_only(host.lower())
    return _gui_action(selected, "act_ref", {
        "snapshot_id": snapshot_id, "ref": ref,
        "interaction": action, "text": text,
    })


@mcp.tool()
def browser_click(selector: str, target_id: str | None = None) -> dict:
    """Click a CSS element with Playwright; report any new tab or navigation."""
    if not isinstance(selector, str) or not 1 <= len(selector) <= 512:
        raise ValueError("selector must contain 1-512 characters")
    selected = _target(target_id)
    host = urlsplit(selected.get("url", "")).hostname
    if host:
        _pace_navigation(host.lower())
    return _gui_action(selected, "click", {"selector": selector})


@mcp.tool()
def browser_fill(selector: str, value: str, target_id: str | None = None) -> dict:
    """Fill a field using real browser input events. Never log submitted values."""
    if (not isinstance(selector, str) or not 1 <= len(selector) <= 512
            or not isinstance(value, str) or len(value) > 10_000):
        raise ValueError("Invalid selector or value too long")
    selected = _target(target_id)
    return _gui_action(selected, "fill", {"selector": selector, "value": value})


@mcp.tool()
def browser_click_text(text: str, role: str = "button", exact: bool = True,
                       target_id: str | None = None,
                       container_selector: str | None = None) -> dict:
    """Click an accessible label within an optional scoped container.

    When multiple elements match, report ambiguity rather than guessing.
    """
    if not isinstance(text, str) or not 1 <= len(text) <= 150:
        raise ValueError("text must contain 1-150 characters")
    if role not in {"button", "link", "tab", "text"}:
        raise ValueError("role must be button, link, tab, or text")
    if not isinstance(exact, bool):
        raise ValueError("exact must be a boolean")
    if container_selector is not None and (
            not isinstance(container_selector, str)
            or not 1 <= len(container_selector) <= 512):
        raise ValueError("container_selector must contain 1-512 characters")
    selected = _target(target_id)
    host = urlsplit(selected.get("url", "")).hostname
    if host:
        _pace_navigation(host.lower())
    return _gui_action(selected, "click_text", {
        "text": text, "role": role, "exact": exact,
        "container_selector": container_selector,
    })


@mcp.tool()
def browser_fill_and_submit(selector: str, value: str, key: str = "Enter",
                            target_id: str | None = None) -> dict:
    """Fill a search field, then press Enter once and inspect the resulting page."""
    if (not isinstance(selector, str) or not 1 <= len(selector) <= 512
            or not isinstance(value, str) or len(value) > 10_000):
        raise ValueError("Invalid selector or value too long")
    if key != "Enter":
        raise ValueError("Only Enter submission is supported")
    selected = _target(target_id)
    host = urlsplit(selected.get("url", "")).hostname
    if host:
        _pace_navigation(host.lower())
    filled = _gui_action(selected, "fill", {"selector": selector, "value": value})
    if not filled.get("ok") or not filled.get("value_confirmed"):
        return {"ok": False, "stage": "fill", "error": "Field did not retain the input"}
    result = _gui_action(selected, "press", {"selector": selector, "key": key})
    result["input_confirmed"] = True
    return result


@mcp.tool()
def browser_click_at(x: int, y: int, target_id: str | None = None) -> dict:
    """Click exact GUI viewport coordinates once (not for automated CAPTCHA solving)."""
    if any(type(v) is not int for v in (x, y)):
        raise ValueError("Coordinates must be integers")
    selected = _target(target_id)
    host = urlsplit(selected.get("url", "")).hostname
    if host:
        _pace_navigation(host.lower())
    return _gui_action(selected, "click_at", {"x": x, "y": y})


# Named keys only: this MCP tool never accepts raw CDP commands or scripts.
_KEY_EVENTS = {
    "Enter": ("Enter", 13, "\r"),
    "Tab": ("Tab", 9, None),
    "Escape": ("Escape", 27, None),
    "Backspace": ("Backspace", 8, None),
    "Delete": ("Delete", 46, None),
    "ArrowUp": ("ArrowUp", 38, None),
    "ArrowDown": ("ArrowDown", 40, None),
    "ArrowLeft": ("ArrowLeft", 37, None),
    "ArrowRight": ("ArrowRight", 39, None),
    "Home": ("Home", 36, None),
    "End": ("End", 35, None),
    "PageUp": ("PageUp", 33, None),
    "PageDown": ("PageDown", 34, None),
    "Space": ("Space", 32, " "),
}


@mcp.tool()
def browser_keypress(key: str, target_id: str | None = None) -> dict:
    """Press one named key (Enter, Tab, Escape, arrows, PageUp/Down, etc.) in the active page."""
    if key not in _KEY_EVENTS:
        raise ValueError("Unsupported key. Choose one of: " + ", ".join(_KEY_EVENTS))
    target = _target(target_id)
    host = urlsplit(target.get("url", "")).hostname
    if host:
        if key == "Enter":
            _pace_navigation(host.lower())
        else:
            _check_access_only(host.lower())
    code, virtual_key, text = _KEY_EVENTS[key]
    down = {"type": "keyDown", "key": key if key != "Space" else " ",
            "code": code, "windowsVirtualKeyCode": virtual_key}
    if text is not None:
        down["text"] = text
    _cdp("Input.dispatchKeyEvent", down, target["id"])
    up = {"type": "keyUp", "key": down["key"], "code": code,
          "windowsVirtualKeyCode": virtual_key}
    _cdp("Input.dispatchKeyEvent", up, target["id"])
    return {"ok": True, "key": key, "target_id": target["id"]}


@mcp.tool()
def browser_scroll(direction: str = "down", pixels: int = 600,
                   selector: str | None = None, target_id: str | None = None) -> dict:
    """Scroll a page or selected scrollable container in a bounded direction."""
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("direction must be up, down, left or right")
    if not isinstance(pixels, int) or not 1 <= pixels <= 1500:
        raise ValueError("pixels must be an integer between 1 and 1500")
    if selector is not None and (not selector or len(selector) > 512):
        raise ValueError("selector must contain 1-512 characters")
    target = _target(target_id)
    host = urlsplit(target.get("url", "")).hostname
    if host:
        _check_access_only(host.lower())
    axis = "top" if direction in {"up", "down"} else "left"
    amount = pixels if direction in {"down", "right"} else -pixels
    expression = """(function(){
      var el=%s ? document.querySelector(%s) : document.scrollingElement;
      if(!el)return Promise.resolve({ok:false,error:'Scrollable element not found'});
      var before={top:el.scrollTop,left:el.scrollLeft};
      // Explicit instant scrolling avoids CSS scroll-behavior:smooth delaying
      // movement. Read the final coordinates on a later task, not immediately
      // after scrollBy, because Chromium may commit scrolling asynchronously.
      el.scrollBy({%s:%d,behavior:'instant'});
      return new Promise(function(resolve){
        setTimeout(function(){
          var after={top:el.scrollTop,left:el.scrollLeft};
          var moved=after.top!==before.top || after.left!==before.left;
          resolve({ok:true,before:before,after:after,moved:moved,
                   at_boundary:!moved});
        },90);
      });
    })()""" % (json.dumps(selector is not None), json.dumps(selector), axis, amount)
    result = _evaluate(expression, target["id"], await_promise=True)
    return result if isinstance(result, dict) else {"result": result}


@mcp.tool()
def browser_wait_for(selector: str | None = None, text: str | None = None,
                     timeout_seconds: int = 10,
                     target_id: str | None = None) -> dict:
    """Wait for page load or a CSS selector/visible text; stop on access restrictions."""
    if selector is not None and (not selector or len(selector) > 512):
        raise ValueError("selector must contain 1-512 characters")
    if text is not None and (not text or len(text) > 150):
        raise ValueError("text must contain 1-150 characters")
    if selector is not None and text is not None:
        raise ValueError("Choose selector or text, not both")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 20:
        raise ValueError("timeout_seconds must be an integer between 1 and 20")
    target = _target(target_id)
    deadline = time.monotonic() + timeout_seconds
    while True:
        expression = """(function(){
          var body=(document.body ? document.body.innerText : '');
          var visibleText=body.slice(0,30000);
          var matched=false;
          try{
            matched=%s;
          }catch(e){
            return {error:'Invalid CSS selector'};
          }
          return {url:location.href,title:document.title,
                  ready_state:document.readyState,matched:matched,
                  access_text:visibleText.slice(0,2000)};
        })()""" % (
            "(function(){var el=document.querySelector(" + json.dumps(selector)
            + ");if(!el)return false;var rect=el.getBoundingClientRect();"
            + "var style=getComputedStyle(el);return rect.width>0&&rect.height>0"
            + "&&style.display!=='none'&&style.visibility!=='hidden';})()"
            if selector is not None else
            "visibleText.includes(" + json.dumps(text) + ")"
            if text is not None else
            "document.readyState==='complete'"
        )
        result = _evaluate(expression, target["id"])
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected browser page state")
        if "error" in result:
            raise ValueError(result["error"])
        url = result.get("url", "")
        snippet = result.get("access_text", "")
        reason = _restriction_reason(url, snippet)
        if reason:
            return {"ok": False, "access_status": "restricted", "url": url,
                    "restriction_reason": reason,
                    "retry_after_seconds": _record_restriction(url)}
        verification = _verification_reason(url, snippet)
        if verification:
            return {"ok": False, "access_status": "verification_required",
                    "url": url, "verification_reason": verification}
        if result.get("matched"):
            return {"ok": True, "url": url, "title": result.get("title", ""),
                    "ready_state": result.get("ready_state", "")}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"ok": False, "timeout": True, "url": url,
                    "ready_state": result.get("ready_state", "")}
        time.sleep(min(0.5, remaining))


@mcp.tool(meta={"ui": {"resourceUri": SCREENSHOT_UI_URI}, "openai/outputTemplate": SCREENSHOT_UI_URI})
def browser_screenshot(target_id: str | None = None) -> list[TextContent | ImageContent]:
    """Capture a PNG and return it directly to the MCP Apps inline viewer."""
    # Capture is read-only. Retry at most once on a transient CDP transport
    # failure; never retry page clicks or verification submissions.
    try:
        result = _cdp("Page.captureScreenshot", {"format": "png"}, target_id)
    except (TimeoutError, RuntimeError) as exc:
        message = str(exc)
        if not (isinstance(exc, TimeoutError) or "CDP transport error:" in message
                or "did not respond in time" in message):
            raise
        try:
            result = _cdp("Page.captureScreenshot", {"format": "png"}, target_id)
        except Exception as retry_error:
            raise RuntimeError(
                "Screenshot failed after one read-only transport retry: "
                + type(retry_error).__name__
            ) from retry_error
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
    metadata["handoff"] = _manual_handoff.status()
    # Only render the manual-entry UI when the actual open tab shows a
    # recognized verification prompt. Never infer the answer or bypass it.
    try:
        selected = _target(target_id)
        state = _verification_state(selected["id"])
        metadata["target_id"] = selected["id"]
        paused = _workflows.paused_for_target(selected["id"])
        if paused:
            metadata["paused_workflow"] = paused
        if state.get("verification_completed"):
            metadata["verification_status"] = "completed"
        if state.get("verification_reason"):
            viewport = state.get("viewport") or {}
            width, height = viewport.get("width"), viewport.get("height")
            if (isinstance(width, int) and isinstance(height, int)
                    and 0 < width <= 10000 and 0 < height <= 10000):
                token = secrets.token_urlsafe(24)
                now = time.monotonic()
                with _verification_lock:
                    for old_id, info in list(_verification_sessions.items()):
                        if info["expires_at"] < now:
                            _verification_sessions.pop(old_id, None)
                    _verification_sessions[token] = {
                        "target_id": selected["id"],
                        "url": state["url"],
                        "viewport": (width, height),
                        "expires_at": now + VERIFICATION_TTL_SECONDS,
                        "clicks": 0,
                    }
                metadata["verification"] = {
                    "required": True,
                    "id": token,
                    "reason": state["verification_reason"],
                    "viewport": {"width": width, "height": height},
                    "expires_in_seconds": VERIFICATION_TTL_SECONDS,
                }
    except (RuntimeError, ValueError, TypeError):
        # A screenshot must remain available if page inspection fails.
        pass
    return [
        TextContent(type="text", text=json.dumps(metadata)),
        ImageContent(type="image", data=encoded, mime_type="image/png"),
    ]


def _click_at(target_id: str, x: int, y: int) -> None:
    """Use page coordinates so a human-selected input in an iframe can be focused."""
    for event_type in ("mousePressed", "mouseReleased"):
        _cdp("Input.dispatchMouseEvent", {
            "type": event_type, "x": x, "y": y, "button": "left",
            "clickCount": 1,
        }, target_id)


@mcp.tool()
def browser_verification_click(verification_id: str, x: int, y: int) -> dict:
    """Relay ONE coordinate clicked by the human in a CAPTCHA screenshot.

    Does not choose challenge answers, loop, or automatically retry. A bounded
    session stays valid for a finite number of user-initiated interactions.
    """
    if not isinstance(verification_id, str) or not verification_id:
        raise ValueError("A verification ID from browser_screenshot is required")
    if any(not isinstance(n, int) or isinstance(n, bool) for n in (x, y)):
        raise ValueError("Click position must be integer pixels")
    with _verification_lock:
        session = _verification_sessions.get(verification_id)
        if not session or session["expires_at"] <= time.monotonic():
            _verification_sessions.pop(verification_id, None)
            raise ValueError("Verification expired; capture a fresh screenshot")
        width, height = session["viewport"]
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("Click is outside the captured viewport")
        clicks = session.get("clicks", 0)
        if clicks >= 24:
            _verification_sessions.pop(verification_id, None)
            raise ValueError("Maximum manual clicks reached; capture a fresh screenshot")
        session["clicks"] = clicks + 1

    selected = _target(session["target_id"])
    state = _verification_state(selected["id"])
    if (state.get("url") != session["url"]
            or state.get("viewport") != {"width": width, "height": height}
            or not state.get("verification_reason")):
        with _verification_lock:
            _verification_sessions.pop(verification_id, None)
        raise RuntimeError("Verification page changed; capture a fresh screenshot")
    _click_at(selected["id"], x, y)
    return {"ok": True, "clicked": True, "verification_status": "pending",
            "message": "선택한 위치를 GUI Chromium에 전달했습니다. 새 화면을 확인하세요."}


@mcp.tool()
def browser_submit_verification(verification_id: str, answer: str,
                                input_x: int, input_y: int,
                                confirm_x: int, confirm_y: int) -> dict:
    """Submit a user's manually read CAPTCHA answer, using user-chosen screen points.

    Invoke only from an explicit user action in the screenshot MCP Apps form.
    This tool does not recognize, solve, retry, or circumvent challenges.
    """
    if not isinstance(verification_id, str) or not verification_id:
        raise ValueError("A verification ID from browser_screenshot is required")
    if (not isinstance(answer, str) or not answer.strip()
            or len(answer) > MAX_VERIFICATION_ANSWER_CHARS
            or any(ord(c) < 32 or ord(c) == 127 for c in answer)):
        raise ValueError("Enter a single-line verification answer (1-64 characters)")
    coordinates = (input_x, input_y, confirm_x, confirm_y)
    if any(not isinstance(n, int) or isinstance(n, bool) for n in coordinates):
        raise ValueError("Input and confirm coordinates must be integer pixels")

    with _verification_lock:
        session = _verification_sessions.pop(verification_id, None)
    if session is None or session["expires_at"] <= time.monotonic():
        raise ValueError("Verification expired; capture a fresh screenshot")

    width, height = session["viewport"]
    if any(not 0 <= x < width for x in (input_x, confirm_x)) or any(
            not 0 <= y < height for y in (input_y, confirm_y)):
        raise ValueError("Selected points are outside the captured viewport")

    selected = _target(session["target_id"])
    state = _verification_state(selected["id"])
    if (state.get("url") != session["url"]
            or not state.get("verification_reason")
            or state.get("viewport") != {"width": width, "height": height}):
        raise RuntimeError("Verification page changed; capture a fresh screenshot")

    host = urlsplit(state["url"]).hostname
    if host:
        _pace_navigation(host.lower())
    _click_at(selected["id"], input_x, input_y)
    _cdp("Input.insertText", {"text": answer}, selected["id"])
    _click_at(selected["id"], confirm_x, confirm_y)
    # Do not include or persist the answer in the tool result.
    return {"ok": True, "submitted": True, "verification_status": "pending",
            "message": "사용자 입력을 브라우저에 한 번 제출했습니다. 인증 결과를 확인하세요."}


if __name__ == "__main__":
    # Bind localhost only. For remote access use SSH forwarding or an authenticated HTTPS reverse proxy.
    # Only the explicit localhost-only standalone Docker profile may opt in
    # to listening on the container interface for 127.0.0.1 host port mapping.
    bind_host = os.environ.get("HACKBROWSER_MCP_HOST", "127.0.0.1")
    if bind_host not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("HACKBROWSER_MCP_HOST must be 127.0.0.1 or 0.0.0.0")
    mcp.run(transport="streamable-http", host=bind_host,
            port=MCP_PORT, json_response=True)
