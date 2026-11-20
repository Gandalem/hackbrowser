"""Reliable GUI Chromium actions. Attach to the EXISTING CDP session; do not launch browsers.

Playwright's locator.click() emits real input events and waits for actionability.
This helper never solves challenges, modifies profiles, or opens external CDP ports.
"""
from __future__ import annotations

from urllib.parse import urlsplit

ACTION_TIMEOUT_MS = 10000
CONNECT_TIMEOUT_MS = 8000
SETTLE_MS = 650


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


def _choose_text_locator(page, text: str, role: str, exact: bool):
    if role == "text":
        locator = page.get_by_text(text, exact=exact)
    else:
        locator = page.get_by_role(role, name=text, exact=exact)
        if locator.count() == 0 and role in {"button", "link", "tab"}:
            locator = page.get_by_text(text, exact=exact)
    matches = locator.count()
    if matches > 1:
        raise ValueError(
            f"Multiple elements match ({matches}); use a more specific label or CSS selector"
        )
    return locator.first


def run_action(cdp_root: str, selected: dict, action: str, args: dict,
               list_targets) -> dict:
    """Perform exactly one action, then report observed navigation/popup state.

    The attached browser is not closed; exiting sync_playwright only disconnects
    the temporary automation transport, preserving the GUI profile/cookies.
    """
    if urlsplit(cdp_root).hostname != "127.0.0.1" or not cdp_root.endswith(":9223"):
        raise RuntimeError("Only the managed local GUI Chromium CDP 9223 is allowed")
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            cdp_root, timeout=CONNECT_TIMEOUT_MS
        )
        if not browser.contexts:
            raise RuntimeError("GUI Chromium has no browser context")
        context = browser.contexts[0]
        page = _find_page(context, selected)
        before_targets = _safe_targets(list_targets)
        before_ids = {item["id"] for item in before_targets}
        before_url = page.url
        before_text = _body_sample(page) if action in {"click", "click_text", "press", "click_at"} else ""
        result = {"ok": True, "action": action, "target_id": selected["id"]}
        try:
            if action == "click":
                page.locator(args["selector"]).first.click(timeout=ACTION_TIMEOUT_MS)
            elif action == "click_text":
                locator = _choose_text_locator(
                    page, args["text"], args["role"], args["exact"]
                )
                locator.click(timeout=ACTION_TIMEOUT_MS)
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
                page.mouse.click(x, y, timeout=ACTION_TIMEOUT_MS)
            else:
                raise ValueError("Unsupported browser operation")
        except (PWTimeout, PlaywrightError) as exc:
            # Never repeat a click if the outcome is ambiguous.
            return {"ok": False, "action": action, "target_id": selected["id"],
                    "error": f"Playwright action failed ({type(exc).__name__}); "
                             "inspect the page before retrying"}

        if action == "fill":
            return result

        try:
            page.wait_for_timeout(SETTLE_MS)
        except PlaywrightError:
            pass  # The click may have closed/navigated the original tab.
        after_targets = _safe_targets(list_targets)
        new_tabs = [
            {"target_id": item["id"], "url": item.get("url", ""),
             "title": item.get("title", "")}
            for item in after_targets
            if item.get("id") not in before_ids
        ]
        after_url = None if page.is_closed() else page.url
        changed = bool(after_url != before_url)
        result.update({
            "url_before": before_url,
            "url_after": after_url,
            "url_changed": changed,
            "new_tabs": new_tabs,
            "next_target_id": new_tabs[0]["target_id"] if new_tabs else selected["id"],
            "content_changed": (
                bool(before_text != _body_sample(page)) if not page.is_closed() else False
            ),
        })
        result["effect_observed"] = bool(
            result["url_changed"] or result["new_tabs"] or result["content_changed"]
        )
        return result
