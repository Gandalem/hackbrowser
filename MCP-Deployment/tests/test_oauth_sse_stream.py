"""Real HTTP SSE forwarding, lease release and gateway restart tests.

Uses actual aiohttp listeners and signed JWTs; the upstream SSE endpoint is an
in-process fixture rather than a real Chromium/MCP bridge. Existing OCI live
tests cover Chromium isolation separately. No network/Keycloak/production access.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import threading
import time
import unittest
from collections import Counter
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import jwt
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric import rsa


GATEWAY = Path(__file__).resolve().parents[1] / "services/gateway/oauth_gateway.py"


class LeaseManager:
    def __init__(self, base):
        self.base = base
        self.active = Counter()
        self.lock = threading.Lock()

    def acquire(self, owner):
        # The production manager returns a private MCP URL per trusted owner.
        subject = owner.rsplit(":", 1)[-1]
        if subject not in {"alice", "bob"}:
            raise RuntimeError("Unexpected fixture owner")
        with self.lock:
            self.active[subject] += 1
        return f"{self.base}/{subject}", subject

    def release(self, key):
        with self.lock:
            self.active[key] -= 1

    def count(self, key):
        with self.lock:
            return self.active[key]


class LiveSseProxyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @staticmethod
    async def bind(app):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    async def asyncSetUp(self):
        async def stream(request):
            label = request.match_info["owner"]
            response = web.StreamResponse(
                status=200, headers={"Content-Type": "text/event-stream"},
            )
            await response.prepare(request)
            try:
                await response.write(f"event: message\\ndata: {label}\\n\\n".encode())
                for _ in range(160):
                    await asyncio.sleep(0.05)
                    await response.write(b": keepalive\\n\\n")
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            return response

        app = web.Application()
        app.router.add_get("/{owner}", stream)
        self.upstream_runner, self.upstream_url = await self.bind(app)
        self.upstream_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
            trust_env=False,
        )
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
            trust_env=False,
        )
        with patch.dict(os.environ, {
            "PUBLIC_BASE_URL": "https://example.test",
            "ENABLE_OAUTH": "1",
            "BROWSER_SESSION_MODE": "isolated",
            "OAUTH_GATEWAY_PORT": "18887",
            "HACKBROWSER_STAGING_TEST_CLIENT": "hb-smoke-0123456789ab",
        }):
            spec = importlib.util.spec_from_file_location("live_sse_gateway", GATEWAY)
            self.gateway = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.gateway)
        self.key_patch = patch.object(
            self.gateway.KEYS, "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=self.key.public_key()),
        )
        self.key_patch.start()
        self.gateway_runner = None
        await self.start_gateway()

    async def start_gateway(self):
        self.manager = LeaseManager(self.upstream_url)
        app = web.Application()
        app["upstream"] = self.upstream_session
        app["isolated"] = self.manager
        app.router.add_route(
            "*", "/hackbrowser/mcp",
            partial(self.gateway.proxy, service="hackbrowser"),
        )
        self.gateway_runner, self.gateway_url = await self.bind(app)

    def token(self, subject):
        return jwt.encode({
            "iss": self.gateway.ISSUER,
            "sub": subject,
            "aud": self.gateway.resource_url("hackbrowser"),
            "scope": "mcp:hackbrowser",
            "azp": "hb-smoke-0123456789ab",
            "exp": int(time.time()) + 180,
        }, self.key, algorithm="RS256")

    async def get_stream(self, subject):
        resp = await self.client.get(
            self.gateway_url + "/hackbrowser/mcp",
            headers={"Authorization": "Bearer " + self.token(subject),
                     "Accept": "text/event-stream"},
        )
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        first = await asyncio.wait_for(resp.content.readuntil(b"\\n\\n"), 3)
        self.assertIn(f"data: {subject}".encode(), first)
        return resp

    async def wait_released(self, manager, subject):
        deadline = asyncio.get_running_loop().time() + 4
        while asyncio.get_running_loop().time() < deadline:
            if manager.count(subject) == 0:
                return
            await asyncio.sleep(0.05)
        self.fail(f"SSE forwarding did not release {subject}'s backend lease")

    async def asyncTearDown(self):
        try:
            await self.client.close()
            if self.gateway_runner:
                await self.gateway_runner.cleanup()
            await self.upstream_session.close()
            await self.upstream_runner.cleanup()
        finally:
            self.key_patch.stop()

    async def test_two_sse_users_disconnect_without_cross_release(self):
        alice = await self.get_stream("alice")
        bob = await self.get_stream("bob")
        manager = self.manager
        self.assertEqual(manager.count("alice"), 1)
        self.assertEqual(manager.count("bob"), 1)
        alice.close()
        await self.wait_released(manager, "alice")
        self.assertEqual(manager.count("bob"), 1)
        bob.close()
        await self.wait_released(manager, "bob")

    async def test_new_sse_stream_after_staging_gateway_restart(self):
        first = await self.get_stream("alice")
        manager = self.manager
        first.close()
        await self.wait_released(manager, "alice")
        await self.gateway_runner.cleanup()
        self.gateway_runner = None
        await self.start_gateway()
        second = await self.get_stream("alice")
        self.assertEqual(self.manager.count("alice"), 1)
        second.close()
        await self.wait_released(self.manager, "alice")


if __name__ == "__main__":
    unittest.main()
