"""Short-lived semantic references for an EXISTING GUI Chromium page.

Playwright's CSS engine traverses open shadow roots. We additionally inspect
bounded, attached iframes without collecting input values or form secrets.
All ElementHandles are owned by the persistent Playwright worker thread.
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
MAX_FRAMES = 8
MAX_CANDIDATES_PER_FRAME = 200


def _frames(page):
    """Main document first, then bounded child frames; no frame mutation."""
    try:
        frames = list(page.frames)
    except (AttributeError, TypeError):
        frames = []
    if not frames:
        return [page]  # Lightweight fake page and older API compatibility.
    try:
        main = page.main_frame
        if main in frames:
            frames.remove(main)
            frames.insert(0, main)
    except AttributeError:
        pass
    return frames[:MAX_FRAMES]


class SemanticBrowser:
    def __init__(self, now=None):
        self.now = now or time.monotonic
        self.snapshot = None

    def invalidate(self):
        old = self.snapshot
        self.snapshot = None
        if old:
            for handle, _, _, _ in old["items"].values():
                try:
                    handle.dispose()
                except Exception:
                    pass

    def observe(self, page, target_id: str, max_elements=35) -> dict:
        if type(max_elements) is not int:
            raise ValueError("max_elements must be an integer")
        max_elements = max(1, min(max_elements, MAX_OBSERVED_ELEMENTS))
        self.invalidate()
        token = secrets.token_urlsafe(18)
        items = {}
        output = []
        frames = _frames(page)
        for frame_index, frame in enumerate(frames):
            if len(output) >= max_elements:
                break
            try:
                frame_url = frame.url
                handles = frame.query_selector_all(SELECTOR)
            except Exception:
                # Detached/cross-origin frames may be unavailable. The main
                # page can still be usable, so do not fail the whole snapshot.
                continue
            retained = set()
            try:
                for handle in handles[:MAX_CANDIDATES_PER_FRAME]:
                    if len(output) >= max_elements:
                        break
                    try:
                        details = handle.evaluate(DESCRIBE_ELEMENT_JS)
                        if not isinstance(details, dict):
                            continue
                        # Keep email/password/OTP, tokens and other sensitive
                        # inputs out of the model-facing observation.
                        if details.get("tag") == "input":
                            from semantic import _BLOCKED_INPUT
                            label = (
                                str(details.get("name", "")) + " " +
                                str(details.get("label", ""))
                            )
                            if _BLOCKED_INPUT.search(label):
                                continue
                        ref = f"e{len(output) + 1}"
                        public = clean_public_details(details, ref)
                        public["frame"] = frame_index
                        output.append(public)
                        items[ref] = (handle, details, frame, frame_url)
                        retained.add(id(handle))
                    except Exception:
                        pass
            finally:
                # Do not keep a thousand handles from a large ecommerce page.
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
            "elements": output, "frames_scanned": min(len(frames), MAX_FRAMES),
            "truncated": len(output) >= max_elements,
            "expires_in_seconds": SNAPSHOT_TTL_SECONDS,
            "hint": "Use browser_act(snapshot_id, ref, action). "
                    "Re-observe if the page/frame changes or a reference expires.",
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
        handle, observed, frame, initial_frame_url = snapshot["items"][ref]
        try:
            if (getattr(frame, "is_detached", lambda: False)()
                    or frame.url != initial_frame_url):
                raise ValueError("Element frame navigated or detached; observe again")
            current = handle.evaluate(DESCRIBE_ELEMENT_JS)
            if not isinstance(current, dict):
                raise ValueError("Element is not visible anymore")
            # Same handle, same semantic meaning and form behavior. Also
            # prohibit a formerly enabled control becoming disabled.
            for field in ("tag", "role", "label", "href", "type", "form_method",
                          "form_action", "form_has_password", "disabled"):
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
            # Lost action replies are ambiguous. NEVER replay automatically.
            return {"ok": False, "error": f"Action uncertain: {type(exc).__name__}",
                    "retry_safe": False}
        finally:
            self.invalidate()
        return {"ok": True, "action": action, "target_id": target_id,
                "message": "Action dispatched. Observe or wait to confirm outcome."}
