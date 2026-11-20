"""Short-lived element references for an existing Playwright GUI page.

Every browser operation runs on the Playwright worker thread. References are
private ElementHandles, not CSS or user-writable DOM attributes. Each
observation invalidates previous refs, and acts fail closed on stale pages.
"""
from __future__ import annotations

import secrets
import time

from semantic import (
    DESCRIBE_ELEMENT_JS, MAX_OBSERVED_ELEMENTS, SNAPSHOT_TTL_SECONDS,
    allow_action, clean_public_details,
)

SELECTOR = (
    'a[href],button,input:not([type="hidden"]),select,'
    '[role="button"],[role="tab"],[role="link"],[role="searchbox"]'
)


class SemanticBrowser:
    def __init__(self, now=None):
        self.now = now or time.monotonic
        self.snapshot = None

    def invalidate(self):
        old = self.snapshot
        self.snapshot = None
        if old:
            for handle, _ in old["items"].values():
                try:
                    handle.dispose()
                except Exception:
                    pass

    def observe(self, page, target_id: str, max_elements=35) -> dict:
        if not isinstance(max_elements, int) or isinstance(max_elements, bool):
            raise ValueError("max_elements must be an integer")
        max_elements = max(1, min(max_elements, MAX_OBSERVED_ELEMENTS))
        self.invalidate()
        token = secrets.token_urlsafe(18)
        handles = page.query_selector_all(SELECTOR)
        items = {}
        output = []
        # Bounding work is important for portals with thousands of links.
        for handle in handles[:max_elements * 5]:
            if len(output) >= max_elements:
                break
            try:
                details = handle.evaluate(DESCRIBE_ELEMENT_JS)
                if not isinstance(details, dict):
                    handle.dispose()
                    continue
                # Avoid sensitive inputs even in the visible element list.
                if details.get("tag") == "input":
                    from semantic import _BLOCKED_INPUT
                    label = str(details.get("name", "")) + " " + str(details.get("label", ""))
                    if _BLOCKED_INPUT.search(label):
                        handle.dispose()
                        continue
                ref = f"e{len(output) + 1}"
                output.append(clean_public_details(details, ref))
                items[ref] = (handle, details)
            except Exception:
                try:
                    handle.dispose()
                except Exception:
                    pass
        # Drop unused handles instead of retaining potentially private DOM.
        retained = {id(x[0]) for x in items.values()}
        for handle in handles:
            if id(handle) not in retained:
                try:
                    handle.dispose()
                except Exception:
                    pass
        self.snapshot = {
            "id": token, "target_id": target_id, "url": page.url,
            "created": self.now(), "items": items,
        }
        try:
            title = page.title()[:160]
            body_text = page.evaluate(
                "() => (document.body?.innerText || '').slice(0, 1800)"
            )
        except Exception:
            title, body_text = "", ""
        return {
            "snapshot_id": token, "target_id": target_id, "url": page.url,
            "title": title, "text": body_text,
            "elements": output, "expires_in_seconds": SNAPSHOT_TTL_SECONDS,
            "hint": "Use browser_act(snapshot_id, ref, action). "
                    "Observe again if a page changes or a reference expires.",
        }

    def act(self, page, target_id: str, snapshot_id: str,
            ref: str, action: str, text: str | None = None) -> dict:
        snapshot = self.snapshot
        if (snapshot is None or snapshot["id"] != snapshot_id or
                snapshot["target_id"] != target_id or
                self.now() - snapshot["created"] >= SNAPSHOT_TTL_SECONDS or
                page.url != snapshot["url"]):
            self.invalidate()
            return {"ok": False, "error": "Snapshot expired or page changed; observe again",
                    "retry_safe": False}
        if ref not in snapshot["items"]:
            return {"ok": False, "error": "Unknown element ref; observe again",
                    "retry_safe": False}
        if action not in {"click", "fill", "search"}:
            raise ValueError("action must be click, fill or search")
        if action in {"fill", "search"} and (
                not isinstance(text, str) or not 1 <= len(text) <= 160):
            raise ValueError("Search text must contain 1-160 characters")
        handle, observed = snapshot["items"][ref]
        try:
            current = handle.evaluate(DESCRIBE_ELEMENT_JS)
            if not isinstance(current, dict):
                raise ValueError("Element is not visible anymore")
            # Same object, same role/destination/label and form semantics.
            # A detached/replaced or repurposed node must not be clicked.
            for field in ("tag", "role", "label", "href", "type", "form_method",
                          "form_action", "form_has_password"):
                if current.get(field) != observed.get(field):
                    raise ValueError("Element changed since observation")
            allowed, reason = allow_action(action, current)
            if not allowed:
                return {"ok": False, "error": reason, "retry_safe": False}
            if action == "click":
                handle.click(timeout=8000)
            elif action == "fill":
                handle.fill(text, timeout=8000)
            else:
                handle.fill(text, timeout=8000)
                if handle.input_value() != text:
                    raise ValueError("Search input was not retained")
                handle.press("Enter", timeout=8000)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "retry_safe": False}
        except Exception as exc:
            # Navigation or connection may have succeeded before error.
            return {"ok": False, "error": f"Action uncertain: {type(exc).__name__}",
                    "retry_safe": False}
        finally:
            # Never permit double-clicking a ref if a response is lost.
            self.invalidate()
        return {"ok": True, "action": action, "target_id": target_id,
                "message": "Action dispatched. Observe or wait to confirm outcome."}
