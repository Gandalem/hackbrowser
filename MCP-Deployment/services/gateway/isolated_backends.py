"""Dedicated MCP bridge per verified OAuth subject.

Each bridge has separate Python globals for tabs, handoff, workflows,
verification tokens and snapshots; its browser runs in a separate Xvfb display.
Only the JWT-verifying OAuth gateway may call acquire().
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "hackbrowser"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from session_pool import SessionPool


class IsolatedBackends:
    def __init__(self, root: Path, *, max_sessions: int = 2,
                 idle_seconds: int = 900, chromium: str = "chromium"):
        self.root = Path(root)
        self.pool = SessionPool(
            self.root / "runtime" / "isolated-browser-profiles",
            chromium=chromium, max_sessions=max_sessions, idle_seconds=idle_seconds,
            port_start=9320, port_end=9399,
        )
        self.lock = threading.RLock()
        self.bridges: dict[str, subprocess.Popen] = {}
        self.inflight: dict[str, int] = {}
        self.bridge_python = self.root / "runtime/venv-hackbrowser/bin/python"
        self.server = self.root / "services/hackbrowser/server.py"

    @staticmethod
    def _reachable(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            return False

    def _stop_bridge(self, key: str) -> None:
        process = self.bridges.pop(key, None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def reap(self) -> None:
        with self.lock:
            # Live SSE streams must not lose their backends while connected.
            now = time.monotonic()
            for key, count in self.inflight.items():
                if count and key in self.pool._sessions:
                    self.pool._sessions[key].last_used = now
            self.pool.reap()
            for key in list(self.bridges):
                session = self.pool._sessions.get(key)
                if session is None or self.bridges[key].poll() is not None:
                    self._stop_bridge(key)
                    if session is not None:
                        self.pool._stop(key)

    def acquire(self, owner: str) -> tuple[str, str]:
        """Return (private backend URL, owner key), or fail without fallback."""
        key = self.pool._key(owner)
        with self.lock:
            self.reap()
            session = self.pool.acquire(owner)
            port = session.port + 200
            proc = self.bridges.get(key)
            if proc is None or proc.poll() is not None:
                self._stop_bridge(key)
                if self._reachable(port):
                    # A foreign service occupies this port; never connect to it.
                    self.pool.release(owner)
                    raise RuntimeError("Dedicated MCP port is unavailable")
                env = os.environ.copy()
                env.update({
                    "HACKBROWSER_CDP_PORT": str(session.port),
                    "HACKBROWSER_MCP_PORT": str(port),
                    "HACKBROWSER_MCP_HOST": "127.0.0.1",
                })
                proc = subprocess.Popen(
                    [str(self.bridge_python), str(self.server)],
                    env=env, cwd=str(self.root),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                )
                self.bridges[key] = proc
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    if self._reachable(port):
                        break
                    time.sleep(0.1)
                else:
                    self._stop_bridge(key)
                    self.pool.release(owner)
                    raise RuntimeError("Dedicated MCP bridge startup timeout")
                if proc.poll() is not None:
                    self._stop_bridge(key)
                    self.pool.release(owner)
                    raise RuntimeError("Dedicated MCP bridge stopped")
            self.inflight[key] = self.inflight.get(key, 0) + 1
            return f"http://127.0.0.1:{port}/mcp", key

    def release(self, key: str) -> None:
        with self.lock:
            self.inflight[key] = max(0, self.inflight.get(key, 0) - 1)
            session = self.pool._sessions.get(key)
            if session:
                session.last_used = time.monotonic()

    def shutdown(self) -> None:
        with self.lock:
            for key in list(self.bridges):
                self._stop_bridge(key)
            self.pool.shutdown()
            self.inflight.clear()
