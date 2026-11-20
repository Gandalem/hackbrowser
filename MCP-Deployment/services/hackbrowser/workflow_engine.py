"""Conservative, resumable browser workflows for one existing GUI tab.

Only GET-style browsing and user-visible searches are permitted. No arbitrary
scripts, purchase actions, file upload, password entry, or CAPTCHA solving.
Workflows are ephemeral and fail closed on ambiguous action results.
"""
from __future__ import annotations

import ipaddress
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

MAX_STEPS = 8
STEPS_PER_CALL = 3
WORKFLOW_TTL_SECONDS = 30 * 60
MAX_WORKFLOWS = 20
MAX_EXECUTION_SECONDS = 23

_ALLOWED_FIELDS = {
    "navigate": {"op", "url"},
    "search": {"op", "selector", "text"},
    "click_link": {"op", "text", "selector", "container_selector"},
    "wait": {"op", "selector", "text", "timeout_seconds"},
    "scroll": {"op", "direction", "pixels"},
}
_RISKY_PATH = re.compile(
    r"(?:^|/)(?:logout|signout|delete|remove|reset|checkout|payment|"
    r"purchase|order|transfer|unsubscribe|withdraw|confirm|submit)(?:/|$|[-_.])",
    re.IGNORECASE,
)
_RISKY_LABEL = re.compile(
    r"(?:결제|구매하기|주문하기|장바구니에 담|계정 삭제|탈퇴|로그아웃|"
    r"송금|이체|삭제|수정 완료|저장하기|pay now|buy now|place order|"
    r"delete|sign out|log out|unsubscribe|transfer funds)",
    re.IGNORECASE,
)


def safe_public_url(url: str) -> bool:
    if not isinstance(url, str) or not 8 <= len(url) <= 2000:
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            return False
        if parts.port not in {None, 443}:
            return False
        if parts.username or parts.password or parts.fragment:
            return False
        if (host in {"localhost", "localhost.localdomain"} or
                host.endswith((".local", ".internal", ".lan", ".home",
                               ".localhost", ".test", ".invalid", ".onion", ".arpa"))):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        if _RISKY_PATH.search(parts.path or "/"):
            return False
        if re.search(r"(?:^|[&?])(logout|delete|remove|submit|pay|checkout)=", parts.query, re.I):
            return False
        return True
    except ValueError:
        return False


def safe_link(url: str, label: str) -> bool:
    return safe_public_url(url) and not _RISKY_LABEL.search(label or "")


def _text(value, maximum, field):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must contain 1-{maximum} characters")
    return value


def validate_steps(raw: list) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STEPS:
        raise ValueError(f"Provide 1-{MAX_STEPS} workflow steps")
    validated = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Step {index + 1} must be an object")
        op = item.get("op")
        if op not in _ALLOWED_FIELDS:
            raise ValueError(f"Step {index + 1}: unsupported operation")
        if set(item) - _ALLOWED_FIELDS[op]:
            raise ValueError(f"Step {index + 1}: unsupported arguments")
        step = {"op": op}
        if op == "navigate":
            url = _text(item.get("url"), 2000, "url")
            if not safe_public_url(url):
                raise ValueError("Workflow URL is not a safe public browsing address")
            step["url"] = url
        elif op == "search":
            step["selector"] = _text(item.get("selector"), 512, "selector")
            step["text"] = _text(item.get("text"), 160, "search text")
        elif op == "click_link":
            has_text = "text" in item
            has_selector = "selector" in item
            if has_text == has_selector:
                raise ValueError("click_link requires exactly one of text or selector")
            field = "text" if has_text else "selector"
            step[field] = _text(item.get(field), 150 if has_text else 512, field)
            if _RISKY_LABEL.search(step[field]):
                raise ValueError("Workflow cannot click a sensitive action")
            if "container_selector" in item:
                if not has_text:
                    raise ValueError("container_selector requires link text")
                step["container_selector"] = _text(
                    item["container_selector"], 512, "container_selector"
                )
        elif op == "wait":
            has_selector = "selector" in item
            has_text = "text" in item
            if has_selector == has_text:
                raise ValueError("wait requires exactly one of selector or text")
            field = "selector" if has_selector else "text"
            step[field] = _text(item.get(field), 512 if has_selector else 150, field)
            timeout = item.get("timeout_seconds", 10)
            if type(timeout) is not int or not 1 <= timeout <= 15:
                raise ValueError("wait timeout must be 1-15 seconds")
            step["timeout_seconds"] = timeout
        elif op == "scroll":
            direction = item.get("direction", "down")
            pixels = item.get("pixels", 600)
            if direction not in {"up", "down", "left", "right"}:
                raise ValueError("scroll direction invalid")
            if type(pixels) is not int or not 1 <= pixels <= 1500:
                raise ValueError("scroll pixels must be 1-1500")
            step.update(direction=direction, pixels=pixels)
        validated.append(step)
    return validated


class WorkflowManager:
    """Short-lived, one-tab, user-resumable workflows; no password persistence."""

    def __init__(self, gate, executor, clock=None):
        self.gate = gate
        self.executor = executor
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.workflows = {}

    def _cleanup(self):
        now = self.clock()
        for task_id, task in list(self.workflows.items()):
            if now - task["created"] >= WORKFLOW_TTL_SECONDS:
                self.workflows.pop(task_id, None)

    @staticmethod
    def _snapshot(task):
        return {
            "workflow_id": task["id"],
            "status": task["status"],
            "target_id": task["target_id"],
            "next_step": task["index"],
            "total_steps": len(task["steps"]),
            "last_action": task["last_action"],
            "last_error": task["last_error"],
            "reason": task["reason"],
            "resume_supported": task["status"] in {
                "yielded", "paused_verification", "paused_login"
            },
        }

    def start(self, steps, target_id):
        normalized = validate_steps(steps)
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Select a live browser target_id")
        with self.lock:
            self._cleanup()
            # Two automation plans must not race on the same GUI tab.
            if any(t["target_id"] == target_id and
                   t["status"] not in {"finished", "stopped"}
                   for t in self.workflows.values()):
                raise RuntimeError("A workflow already controls this tab")
            if len(self.workflows) >= MAX_WORKFLOWS:
                raise RuntimeError("Too many active workflows; finish or let them expire")
            task_id = secrets.token_urlsafe(24)
            task = {
                "id": task_id, "target_id": target_id, "steps": normalized,
                "index": 0, "status": "yielded", "created": self.clock(),
                "last_action": None, "last_error": None, "reason": None,
                "run_lock": threading.Lock(),
            }
            self.workflows[task_id] = task
        return self._advance(task)

    def get(self, workflow_id):
        with self.lock:
            self._cleanup()
            task = self.workflows.get(workflow_id)
            if task is None:
                raise ValueError("Workflow is unknown or has expired")
            return self._snapshot(task)

    def paused_for_target(self, target_id):
        with self.lock:
            self._cleanup()
            for task in reversed(list(self.workflows.values())):
                if (task["target_id"] == target_id and
                        task["status"] in {"paused_verification", "paused_login"}):
                    return self._snapshot(task)
        return None

    def resume(self, workflow_id):
        with self.lock:
            self._cleanup()
            task = self.workflows.get(workflow_id)
            if task is None:
                raise ValueError("Workflow is unknown or has expired")
            if task["status"] not in {
                "yielded", "paused_verification", "paused_login"
            }:
                raise ValueError(
                    "Workflow is finished or stopped; do not replay an uncertain action"
                )
        return self._advance(task)

    def _advance(self, task):
        if not task["run_lock"].acquire(blocking=False):
            return dict(self._snapshot(task), status="busy")
        try:
            started = self.clock()
            performed = 0
            while task["index"] < len(task["steps"]) and performed < STEPS_PER_CALL:
                # Every step is gated, including after manual user verification.
                try:
                    gate = self.gate(task["target_id"])
                except Exception as exc:
                    task.update(status="stopped", reason="gate_failed",
                                last_error=type(exc).__name__)
                    break
                condition = gate.get("state", "ok")
                if condition in {"verification_required", "login_required"}:
                    task.update(
                        status="paused_verification"
                        if condition == "verification_required" else "paused_login",
                        reason=condition, last_error=None,
                    )
                    break
                if condition != "ok":
                    task.update(status="stopped", reason=condition, last_error=None)
                    break

                step = task["steps"][task["index"]]
                task["last_action"] = step["op"]
                try:
                    result = self.executor(task["target_id"], step)
                except Exception as exc:
                    # Never replay a click or form submission automatically.
                    task.update(status="stopped", reason="action_failed",
                                last_error=type(exc).__name__)
                    break
                if not isinstance(result, dict) or not result.get("ok"):
                    task.update(
                        status="stopped", reason="action_failed",
                        last_error="Action result was not confirmed",
                    )
                    break
                if (step["op"] in {"click_link", "search"} and
                        not result.get("effect_observed")):
                    task.update(
                        status="stopped", reason="effect_unconfirmed",
                        last_error="Link/search did not produce an observable change",
                    )
                    break
                next_target = result.get("next_target_id")
                if isinstance(next_target, str) and next_target:
                    task["target_id"] = next_target
                task["index"] += 1
                performed += 1
                task.update(status="yielded", reason=None, last_error=None)
                if result.get("render_pending"):
                    task["reason"] = "render_pending"
                    break
                if self.clock() - started > MAX_EXECUTION_SECONDS:
                    task["reason"] = "time_budget"
                    break

            # Check whether the LAST completed action ended at a challenge,
            # even when there are no more steps to run in this batch.
            if task["status"] == "yielded" and performed:
                try:
                    state = self.gate(task["target_id"]).get("state", "unsafe_page")
                except Exception as exc:
                    task.update(status="stopped", reason="gate_failed",
                                last_error=type(exc).__name__)
                else:
                    if state in {"verification_required", "login_required"}:
                        task.update(
                            status="paused_verification" if state ==
                            "verification_required" else "paused_login",
                            reason=state,
                        )
                    elif state != "ok":
                        task.update(status="stopped", reason=state)
            if (task["index"] == len(task["steps"]) and
                    task["status"] in {"yielded", "paused_verification", "paused_login"}):
                try:
                    end_state = self.gate(task["target_id"]).get("state", "unsafe_page")
                except Exception as exc:
                    task.update(status="stopped", reason="gate_failed",
                                last_error=type(exc).__name__)
                else:
                    if end_state == "ok":
                        task.update(status="finished", reason=None, last_error=None)
                    elif end_state in {"verification_required", "login_required"}:
                        task.update(status="paused_verification" if end_state ==
                                    "verification_required" else "paused_login",
                                    reason=end_state)
                    else:
                        task.update(status="stopped", reason=end_state)
            elif task["status"] == "yielded" and task["reason"] is None:
                task["reason"] = "batch_boundary"
            return self._snapshot(task)
        finally:
            task["run_lock"].release()
