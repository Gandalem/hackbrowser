"""Opt-in isolated Chromium pool. Not an authentication boundary.

Only pass trusted, server-verified user subjects to acquire(). Never accept
an owner ID from a browser tool argument or from a client-supplied header.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import websocket


@dataclass
class BrowserSession:
    owner_id: str
    port: int
    profile_dir: Path
    process: subprocess.Popen
    last_used: float


class SessionPool:
    def __init__(self, profile_root: str | Path, *, chromium: str = "chromium",
                 max_sessions: int = 2, idle_seconds: int = 900,
                 port_start: int = 9320, port_end: int = 9399,
                 display: str | None = None):
        if max_sessions < 1 or idle_seconds < 1 or not (1024 <= port_start <= port_end <= 65535):
            raise ValueError("Invalid session limits or CDP port range")
        self.root = Path(profile_root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.chromium = chromium
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self.port_start = port_start
        self.port_end = port_end
        self.display = display
        self._lock = threading.RLock()
        self._sessions: dict[str, BrowserSession] = {}
        self._opener = build_opener(ProxyHandler({}))

    @staticmethod
    def _key(owner_id: str) -> str:
        if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 512:
            raise ValueError("Trusted stable owner ID required")
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _ready(self, port: int) -> bool:
        try:
            with self._opener.open(Request(f"http://127.0.0.1:{port}/json/version"), timeout=0.3) as response:
                return isinstance(json.load(response), dict)
        except (OSError, ValueError, TimeoutError):
            return False

    def _request_browser_close(self, session: BrowserSession) -> bool:
        """Ask *this pool's* localhost Chromium to flush state and exit.

        CDP Browser.close is preferable to SIGTERM for a persistent profile.
        Never use arbitrary browser-supplied hosts or ports.
        """
        port = session.port
        if not self.port_start <= port <= self.port_end:
            return False
        try:
            with self._opener.open(
                Request(f"http://127.0.0.1:{port}/json/version"),
                timeout=1,
            ) as response:
                info = json.load(response)
            ws_url = info.get("webSocketDebuggerUrl") if isinstance(info, dict) else None
            if not isinstance(ws_url, str):
                return False
            parsed = urlsplit(ws_url)
            if (parsed.scheme != "ws"
                    or parsed.hostname not in {"127.0.0.1", "localhost"}
                    or parsed.port != port
                    or not parsed.path.startswith("/devtools/browser/")
                    or parsed.username or parsed.password):
                return False
            ws = websocket.create_connection(
                ws_url, timeout=2, suppress_origin=True,
            )
            try:
                ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                # Chromium may close the WebSocket before returning a response.
                return True
            finally:
                ws.close()
        except (OSError, ValueError, TimeoutError, websocket.WebSocketException):
            return False

    def _stop(self, key: str) -> None:
        session = self._sessions.pop(key, None)
        if session is None:
            return
        if session.process.poll() is None:
            if self._request_browser_close(session):
                try:
                    # Give Chromium time to flush its persistent cookie DB.
                    session.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    pass
            if session.process.poll() is None:
                try:
                    os.killpg(session.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    session.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(session.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    session.process.wait(timeout=3)
        # Profiles persist across idle shutdown; never erase login data here.

    def reap(self) -> int:
        with self._lock:
            now = time.monotonic()
            stale = [key for key, session in self._sessions.items()
                     if session.process.poll() is not None or now - session.last_used >= self.idle_seconds]
            for key in stale:
                self._stop(key)
            return len(stale)

    def acquire(self, owner_id: str, *, startup_timeout: float = 15) -> BrowserSession:
        """No shared-browser fallback when an isolated session is unavailable."""
        key = self._key(owner_id)
        with self._lock:
            self.reap()
            existing = self._sessions.get(key)
            if existing is not None:
                existing.last_used = time.monotonic()
                return existing
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("Isolated browser session limit reached")
            busy = {session.port for session in self._sessions.values()}
            port = next((p for p in range(self.port_start, self.port_end + 1)
                         if p not in busy and self._port_available(p)), None)
            if port is None:
                raise RuntimeError("No free localhost CDP port")
            profile = self.root / key
            profile.mkdir(mode=0o700, exist_ok=True)
            profile.chmod(0o700)
            env = os.environ.copy()
            if self.display is not None:
                env["DISPLAY"] = self.display
            chromium_args = [self.chromium, "--no-first-run", "--no-default-browser-check",
                             "--disable-gpu", "--disable-background-networking",
                             "--remote-debugging-address=127.0.0.1",
                             f"--remote-debugging-port={port}",
                             f"--user-data-dir={profile}", "--window-size=1366,900",
                             "about:blank"]
            cmd = chromium_args if self.display is not None else [
                "xvfb-run", "-a", "-s", "-screen 0 1366x900x24 -nolisten tcp",
                *chromium_args,
            ]
            process = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            session = BrowserSession(owner_id, port, profile, process, time.monotonic())
            self._sessions[key] = session
            deadline = time.monotonic() + max(0, startup_timeout)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if self._ready(port):
                    return session
                time.sleep(0.1)
            self._stop(key)
            raise RuntimeError("Isolated Chromium did not become ready")

    def release(self, owner_id: str) -> None:
        with self._lock:
            self._stop(self._key(owner_id))

    def shutdown(self) -> None:
        with self._lock:
            for key in list(self._sessions):
                self._stop(key)

    def stats(self) -> dict[str, int]:
        """Never expose owner identity, profile location, or browsing activity."""
        with self._lock:
            self.reap()
            return {"active": len(self._sessions), "limit": self.max_sessions}
