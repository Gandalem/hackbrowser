"""Short-lived share-link MCP gateway; loopback-only upstreams.

Derived from the working deployment export; no public endpoint is created here.
Caddy is the only internet-facing component.
"""
import asyncio
import hmac
import json
import os
import time
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(os.environ.get("MCP_INSTALL_ROOT", "/opt/mcp-deployment"))
CONFIG = ROOT / "runtime/secrets/share.json"
ZAP_KEY = ROOT / "runtime/secrets/zap-key"
BACKENDS = {
    "pocmap": "http://127.0.0.1:9000/mcp",
    "hackbrowser": "http://127.0.0.1:8765/mcp",
    "zap": "http://127.0.0.1:8282/",
}
HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "host", "authorization", "x-origin-token", "origin", "accept-encoding",
}
RESPONSE_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
}


async def proxy(request):
    if request.method not in ("GET", "HEAD", "POST", "DELETE"):
        return web.Response(status=405)
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return web.Response(status=503, text="Share configuration unavailable")
    if time.time() >= int(config["expires_at"]):
        return web.Response(status=410, text="Temporary MCP link expired")
    token = request.match_info["token"]
    if not hmac.compare_digest(token, str(config["token"])):
        return web.Response(status=404)
    service = request.match_info["service"]
    if service == "hackbrowser" and os.environ.get("BROWSER_SESSION_MODE", "single") == "isolated":
        return web.Response(status=403, text="Browser sharing disabled in isolated mode")
    backend = BACKENDS.get(service)
    if backend is None:
        return web.Response(status=404)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["Accept-Encoding"] = "identity"
    if service == "zap":
        try:
            key = ZAP_KEY.read_text().strip()
            if not key:
                raise ValueError("missing key")
            headers["Authorization"] = key
        except (OSError, ValueError):
            return web.Response(status=503, text="ZAP key unavailable")
    url = backend + ("?" + request.query_string if request.query_string else "")
    try:
        body = await request.read()
        async with request.app["http"].request(
            request.method, url, headers=headers,
            data=body if body else None, allow_redirects=False
        ) as upstream:
            response_headers = {
                k: v for k, v in upstream.headers.items()
                if k.lower() not in RESPONSE_HOP
            }
            response_headers["Cache-Control"] = "no-store"
            response = web.StreamResponse(status=upstream.status, headers=response_headers)
            await response.prepare(request)
            if request.method != "HEAD":
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
            await response.write_eof()
            return response
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return web.Response(status=502, text="MCP upstream unavailable")
    except ConnectionResetError:
        raise


async def health(_request):
    return web.Response(text="ok")


async def lifespan(app):
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_connect=15, sock_read=None)
    app["http"] = aiohttp.ClientSession(timeout=timeout, auto_decompress=False, trust_env=False)
    yield
    await app["http"].close()


app = web.Application(client_max_size=16 * 1024 * 1024)
app.cleanup_ctx.append(lifespan)
app.router.add_get("/internal-health", health)
app.router.add_route("*", "/share/{token}/{service}/mcp", proxy)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8790, access_log=None)
