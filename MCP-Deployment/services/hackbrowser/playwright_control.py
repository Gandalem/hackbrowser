"""Reliable GUI Chromium actions. Attach to the EXISTING CDP session; do not launch browsers.

Playwright's locator.click() emits real input events and waits for actionability.
This helper never solves challenges, modifies profiles, or opens external CDP ports.
"""
from __future__ import annotations

from urllib.parse import urlsplit
import queue
import threading
import time
from concurrent.futures import Future

ACTION_TIMEOUT_MS = 10000
CONNECT_TIMEOUT_MS = 8000
SETTLE_MS = 650
POST_ACTION_WAIT_SECONDS = 2.0


def _find_page(context, selected: dict):
    """Match the requested CDP target exactly; never silently act on another tab."""
    expected_id = selected["id"]
    for page in context.pages:
        session = None
        try:
            session = context.new_cdp_session(page)
            info = session.send("Target.getTargetInfo").get("targetInfo", {})
            if info.get("targetId") == expected_id:
                return page
        except Exception:
            # Some externally launched Chromium builds disallow Target.getTargetInfo.
            pass
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
    candidates = [page for page in context.pages
                  if not page.is_closed() and page.url == selected.get("url")]
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(
        "Cannot uniquely match the selected Chromium tab. "
        "Call browser_tabs() and use a current target_id."
    )


def _safe_targets(list_targets) -> list[dict]:
    try:
        return list_targets()
    except Exception:
        return []


def _body_sample(page) -> str:
    try:
        return page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 6000)"
        )
    except Exception:
        return ""


def _choose_text_locator(page, text: str, role: str, exact: bool,
                         container_selector: str | None = None):
    """Resolve an accessible name in a specific container, without guessing."""
    scope = page
    if container_selector is not None:
        scope = page.locator(container_selector)
        matches = scope.count()
        if matches != 1:
            raise ValueError(
                f"Container selector matched {matches} regions; specify exactly one"
            )
    if role == "text":
        locator = scope.get_by_text(text, exact=exact)
    else:
        locator = scope.get_by_role(role, name=text, exact=exact)
        if locator.count() == 0 and role in {"button", "link", "tab"}:
            locator = scope.get_by_text(text, exact=exact)
    matches = locator.count()
    if matches == 0:
        raise ValueError("No matching visible element; inspect browser_elements")
    if matches > 1:
        raise ValueError(
            f"Multiple elements match ({matches}); specify container_selector "
            "or a more specific CSS selector"
        )
    return locator.first


def _run_connected(browser, selected: dict, action: str, args: dict,
                   list_targets) -> dict:
    """Apply exactly one action with a Playwright connection owned by the worker."""
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PWTimeout
    if not browser.contexts:
        raise RuntimeError("GUI Chromium has no browser context")
    context = browser.contexts[0]
    page = _find_page(context, selected)
    before_targets = _safe_targets(list_targets)
    before_ids = {item["id"] for item in before_targets}
    before_url = page.url
    before_text = _body_sample(page) if action in {"click", "click_text", "press", "click_at", "safe_link", "safe_search"} else ""
    result = {"ok": True, "action": action, "target_id": selected["id"]}
    try:
        if action == "click":
            page.locator(args["selector"]).first.click(timeout=ACTION_TIMEOUT_MS)
        elif action == "click_text":
            locator = _choose_text_locator(
                page, args["text"], args["role"], args["exact"],
                args.get("container_selector"),
            )
            locator.click(timeout=ACTION_TIMEOUT_MS)
        elif action == "safe_link":
            from workflow_engine import safe_link
            if "selector" in args:
                locator = page.locator(args["selector"])
                matches = locator.count()
                if matches != 1:
                    raise ValueError(f"Link selector matched {matches} elements")
                locator = locator.first
            else:
                locator = _choose_text_locator(
                    page, args["text"], "link", True, args.get("container_selector"),
                )
            info = locator.evaluate("""(el) => ({
                tag: el.tagName.toLowerCase(),
                href: el.href || '',
                label: (el.innerText || el.getAttribute('aria-label') || '').trim(),
                download: el.hasAttribute('download')
            })""")
            if (info.get("tag") != "a" or info.get("download")
                    or not safe_link(info.get("href", ""), info.get("label", ""))):
                raise ValueError(
                    "This link is not a safe, public navigation target. "
                    "Use an explicit user-approved browser action instead."
                )
            locator.click(timeout=ACTION_TIMEOUT_MS)
        elif action == "safe_search":
            from workflow_engine import safe_public_url
            locator = page.locator(args["selector"])
            if locator.count() != 1:
                raise ValueError("Search selector must match exactly one input")
            locator = locator.first
            info = locator.evaluate("""(el) => {
                const form = el.form || el.closest('form');
                const type = (el.getAttribute('type') || 'text').toLowerCase();
                const label = (el.name || '') + ' ' +
                    (el.getAttribute('placeholder') || '') + ' ' +
                    (el.getAttribute('aria-label') || '');
                return {
                    tag: el.tagName.toLowerCase(), type,
                    label, form: !!form,
                    method: form ? (form.method || 'get').toLowerCase() : '',
                    action: form ? form.action : '',
                    password: !!(form && form.querySelector('input[type="password"]'))
                };
            }""")
            if (info.get("tag") != "input"
                    or info.get("type") not in {"search", "text"}
                    or not info.get("form") or info.get("method") != "get"
                    or info.get("password")
                    or not safe_public_url(info.get("action", ""))
                    or not __import__("re").search(
                        r"(search|query|keyword|검색|찾기|(^|\s)q(\s|$))",
                        info.get("label", ""), __import__("re").IGNORECASE,
                    )):
                raise ValueError(
                    "Workflow search requires a visible GET search form "
                    "without a password field"
                )
            locator.fill(args["text"], timeout=ACTION_TIMEOUT_MS)
            if locator.input_value() != args["text"]:
                raise ValueError("Search text was not retained")
            locator.press("Enter", timeout=ACTION_TIMEOUT_MS)
        elif action == "fill":
            locator = page.locator(args["selector"]).first
            locator.fill(args["value"], timeout=ACTION_TIMEOUT_MS)
            result["value_confirmed"] = locator.input_value() == args["value"]
        elif action == "press":
            page.locator(args["selector"]).first.press(
                args["key"], timeout=ACTION_TIMEOUT_MS
            )
            result["key"] = args["key"]
        elif action == "click_at":
            viewport = page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            x, y = args["x"], args["y"]
            if not (0 <= x < viewport["width"] and 0 <= y < viewport["height"]):
                raise ValueError("Click position is outside the GUI viewport")
            page.mouse.click(x, y)
        else:
            raise ValueError("Unsupported browser operation")
    except ValueError as exc:
        # Ambiguous visible labels are expected on real sites. Report the
        # reason instead of surfacing an opaque MCP execution exception.
        return {"ok": False, "action": action, "target_id": selected["id"],
                "error": str(exc)}
    except (PWTimeout, PlaywrightError) as exc:
        # Never repeat a click if the outcome is ambiguous.
        return {"ok": False, "action": action, "target_id": selected["id"],
                "error": f"Playwright action failed ({type(exc).__name__}); "
                         "inspect the page before retrying"}

    if action == "fill":
        return result

    # Single-page applications may change location before their new UI commits.
    # Wait only for read-only observations; never click again to force a result.
    deadline = time.monotonic() + POST_ACTION_WAIT_SECONDS
    while True:
        after_targets = _safe_targets(list_targets)
        new_tabs = [
            {"target_id": item["id"], "url": item.get("url", ""),
             "title": item.get("title", "")}
            for item in after_targets if item.get("id") not in before_ids
        ]
        closed = page.is_closed()
        after_url = None if closed else page.url
        after_text = "" if closed else _body_sample(page)
        changed = after_url != before_url
        content_changed = before_text != after_text
        if new_tabs or closed or content_changed or time.monotonic() >= deadline:
            break
        try:
            page.wait_for_timeout(150)
        except PlaywrightError:
            break
    result.update({
        "url_before": before_url,
        "url_after": after_url,
        "url_changed": changed,
        "new_tabs": new_tabs,
        "next_target_id": new_tabs[0]["target_id"] if new_tabs else selected["id"],
        "content_changed": content_changed,
        "effect_observed": bool(changed or new_tabs or content_changed),
        "render_pending": bool(changed and not content_changed and not new_tabs),
    })
    return result

class _GuiWorker:
    """Single owner of sync Playwright. Calls are serialized; session is reused."""

    def __init__(self):
        self.jobs = queue.Queue(maxsize=16)
        self.lock = threading.Lock()
        self.thread = None
        self.started = 0
        # Module must also load when CI imports this file directly by path.
        import sys
        from pathlib import Path
        folder = str(Path(__file__).resolve().parent)
        if folder not in sys.path:
            sys.path.insert(0, folder)
        from semantic_browser import SemanticBrowser
        self.semantic = SemanticBrowser()

    def submit(self, cdp_root, selected, action, args, list_targets):
        result = Future()
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(
                    target=self._run, name="hackbrowser-gui-playwright", daemon=True
                )
                self.thread.start()
        try:
            self.jobs.put_nowait((result, cdp_root, selected, action, args, list_targets))
        except queue.Full:
            raise RuntimeError("GUI browser action queue is full; no action was enqueued")
        # Wait long enough for one 10s action plus a potential pre-action
        # reconnection. A timed-out action must never be implicitly retried.
        try:
            return result.result(timeout=35)
        except TimeoutError:
            # Cancel if still queued; if running, execution may have occurred.
            # Never replay an uncertain browser action.
            result.cancel()
            return {"ok": False, "action": action, "target_id": selected["id"],
                    "error": "GUI worker timed out; inspect before retrying",
                    "retry_safe": False}

    def _run(self):
        from playwright.sync_api import sync_playwright

        browser = None
        with sync_playwright() as playwright:
            while True:
                future, cdp_root, selected, action, args, targets = self.jobs.get()
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    _validate_cdp(cdp_root)
                    if browser is None or not browser.is_connected():
                        # Reconnect only before a new action; no blind replay.
                        self.semantic.invalidate()
                        browser = playwright.chromium.connect_over_cdp(
                            cdp_root, timeout=CONNECT_TIMEOUT_MS
                        )
                        self.started += 1
                    if action in {"observe", "act_ref"}:
                        page = _find_page(browser.contexts[0], selected)
                        if action == "observe":
                            value = self.semantic.observe(
                                page, selected["id"], args["max_elements"],
                            )
                        else:
                            value = self.semantic.act(
                                page, selected["id"], args["snapshot_id"],
                                args["ref"], args["interaction"], args.get("text"),
                            )
                    else:
                        self.semantic.invalidate()
                        value = _run_connected(browser, selected, action, args, targets)
                    future.set_result(value)
                except Exception as exc:
                    # Drop a stale transport, but DO NOT retry this action.
                    browser = None
                    self.semantic.invalidate()
                    future.set_exception(exc)
                finally:
                    self.jobs.task_done()


def _validate_cdp(cdp_root: str) -> None:
    parsed = urlsplit(cdp_root)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port != 9223 or parsed.path not in {"", "/"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise RuntimeError("Only the managed local GUI Chromium CDP 9223 is allowed")


_gui_worker = _GuiWorker()


def run_action(cdp_root: str, selected: dict, action: str, args: dict,
               list_targets) -> dict:
    """Queue a single action on the persistent GUI Playwright connection."""
    _validate_cdp(cdp_root)
    return _gui_worker.submit(cdp_root, selected, action, args, list_targets)
