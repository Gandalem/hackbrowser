"""Bounded user handoff for the one shared GUI Chromium profile.

This is a single-operator convenience feature, NOT user authentication or
multi-tenant session isolation. The MCP Apps card receives an opaque secret
only through its own explicit user-triggered tool call. No password/text input
or unattended CAPTCHA solving is supported by handoff controls.
"""
from __future__ import annotations

import secrets
import threading
import time

HANDOFF_TTL_SECONDS = 10 * 60


class ManualHandoff:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        # All GUI mutation entrypoints and the Playwright worker share this
        # lock. Starting handoff therefore cannot overtake an in-flight click.
        self.lock = threading.RLock()
        self._lease = None

    def _current(self):
        lease = self._lease
        if lease is not None and self.clock() >= lease["deadline"]:
            self._lease = None
            return None
        return lease

    def begin(self, target_id: str, viewport: dict) -> dict:
        with self.lock:
            if self._current() is not None:
                raise RuntimeError("A manual handoff is already active; return control first")
            if not isinstance(target_id, str) or not target_id:
                raise ValueError("A current GUI page target ID is required")
            if not isinstance(viewport, dict):
                raise ValueError("Viewport is unavailable")
            width, height = viewport.get("width"), viewport.get("height")
            if any(type(v) is not int or not 1 <= v <= 10000 for v in (width, height)):
                raise ValueError("Cannot validate the browser viewport")
            token = secrets.token_urlsafe(32)
            self._lease = {
                "token": token,
                "target_id": target_id,
                "deadline": self.clock() + HANDOFF_TTL_SECONDS,
                "viewport": {"width": width, "height": height},
            }
            return {
                "active": True,
                "target_id": target_id,
                "control_token": token,
                "viewport": {"width": width, "height": height},
                "expires_in_seconds": HANDOFF_TTL_SECONDS,
                "message": "AI browser mutations are paused until return or expiry",
            }

    def status(self) -> dict:
        with self.lock:
            lease = self._current()
            if lease is None:
                return {"active": False}
            return {
                "active": True,
                "target_id": lease["target_id"],
                "expires_in_seconds": max(0, int(lease["deadline"] - self.clock())),
            }

    def assert_ai_allowed(self):
        with self.lock:
            if self._current() is not None:
                raise RuntimeError(
                    "Manual control is active. AI browser changes are paused; "
                    "wait until the user returns control or the lease expires."
                )

    def authenticate(self, token: str, target_id: str) -> dict:
        with self.lock:
            lease = self._current()
            if (lease is None or not isinstance(token, str) or
                    not secrets.compare_digest(lease["token"], token) or
                    lease["target_id"] != target_id):
                raise ValueError("Manual handoff token invalid, expired or for another tab")
            return dict(lease["viewport"])

    def finish(self, token: str) -> dict:
        with self.lock:
            lease = self._current()
            if (lease is None or not isinstance(token, str) or
                    not secrets.compare_digest(lease["token"], token)):
                raise ValueError("Handoff expired or token invalid; check handoff status")
            self._lease = None
            return {
                "ok": True,
                "returned_to_ai": True,
                "target_id": lease["target_id"],
                "message": "Manual control ended. Inspect the page before AI continues.",
            }


# Shared across server-side CDP and the dedicated Playwright worker.
manual_handoff = ManualHandoff()
