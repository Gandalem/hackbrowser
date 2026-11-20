"""Keycloak JWT-authorized MCP reverse proxy, with dedicated ZAP key injection.

Adapted from user's working gateway; client-specific grants remain enforced for
OAuth routes. Generic AI clients use the time-limited share path instead.
"""
import asyncio
import os
from contextlib import suppress
from functools import partial
from pathlib import Path

import aiohttp
import jwt
from aiohttp import web
from jwt import PyJWKClient, PyJWTError

ROOT = Path(os.environ.get("MCP_INSTALL_ROOT", "/opt/mcp-deployment"))
PUBLIC = os.environ["PUBLIC_BASE_URL"].rstrip("/")
REALM = "security-mcp"
ISSUER = f"{PUBLIC}/auth/realms/{REALM}"
JWKS = f"http://127.0.0.1:8081/auth/realms/{REALM}/protocol/openid-connect/certs"
ZAP_KEY = ROOT / "runtime/secrets/zap-key"
BACKENDS = {
    "pocmap": "http://127.0.0.1:9000/mcp",
    "hackbrowser": "http://127.0.0.1:8765/mcp",
    "zap": "http://127.0.0.1:8282/",
}
ALLOWED_ORIGINS = {"https://chatgpt.com", "https://chat.openai.com", PUBLIC}
REQUEST_HEADERS = (
    "Accept", "Content-Type", "Mcp-Session-Id", "MCP-Protocol-Version",
    "Last-Event-ID", "Mcp-Method", "Mcp-Name"
)
RESPONSE_HEADERS = {
    "content-type", "mcp-session-id", "mcp-protocol-version", "retry-after",
    "location", "content-encoding",
}
KEYS = PyJWKClient(JWKS, cache_jwk_set=True, lifespan=300, timeout=5)
SESSION_MODE = os.environ.get("BROWSER_SESSION_MODE", "single")
if SESSION_MODE not in {"single", "isolated"}:
    raise ValueError("BROWSER_SESSION_MODE must be single or isolated")
if SESSION_MODE == "isolated" and os.environ.get("ENABLE_OAUTH") != "1":
    raise RuntimeError("Isolated browser mode requires ENABLE_OAUTH=1")



def resource_url(service):
    return f"{PUBLIC}/{service}/mcp"


def metadata_url(service):
    return f"{PUBLIC}/.well-known/oauth-protected-resource/{service}/mcp"


def challenge(service):
    hdr = f'Bearer resource_metadata="{metadata_url(service)}", scope="mcp:{service}"'
    return web.json_response({"error": "unauthorized"}, status=401,
                             headers={"WWW-Authenticate": hdr, "Cache-Control": "no-store"})


def verify_jwt(token, service):
    if jwt.get_unverified_header(token).get("alg") != "RS256":
        raise ValueError("Only RS256 supported")
    signing_key = KEYS.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token, signing_key.key, algorithms=["RS256"], issuer=ISSUER,
        audience=resource_url(service),
        options={"require": ["iss", "sub", "exp", "aud"]},
        leeway=15,
    )
    if claims.get("azp") != f"chatgpt-{service}":
        raise ValueError("OAuth client not authorized for this service")
    if f"mcp:{service}" not in set(str(claims.get("scope", "")).split()):
        raise ValueError("Missing service scope")
    return claims


async def metadata(_request, service):
    return web.json_response({
        "resource": resource_url(service),
        "authorization_servers": [ISSUER],
        "scopes_supported": [f"mcp:{service}"],
        "bearer_methods_supported": ["header"],
    }, headers={"Cache-Control": "no-store"})


async def proxy(request, service):
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return web.Response(status=403, text="Invalid Origin")
    if request.method not in {"GET", "POST", "DELETE", "HEAD"}:
        return web.Response(status=405)
    auth = request.headers.get("Authorization", "")
    if len(auth) > 16384 or not auth.startswith("Bearer "):
        return challenge(service)
    try:
        claims = await asyncio.to_thread(verify_jwt, auth[7:].strip(), service)
    except (PyJWTError, ValueError, KeyError, OSError):
        return challenge(service)
    headers = {k: request.headers[k] for k in REQUEST_HEADERS if k in request.headers}
    headers.update({
        k: v for k, v in request.headers.items()
        if k.lower().startswith("mcp-param-")
    })
    headers["Accept-Encoding"] = "identity"
    if service == "zap":
        try:
            key = ZAP_KEY.read_text().strip()
            if not key:
                raise ValueError("Empty ZAP key")
            headers["Authorization"] = key
        except (OSError, ValueError):
            return web.Response(status=503, text="ZAP key unavailable")
    owner_key = None
    backend = BACKENDS[service]
    if service == "hackbrowser" and SESSION_MODE == "isolated":
        try:
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject.strip():
                return challenge(service)
            backend, owner_key = await asyncio.to_thread(
                request.app["isolated"].acquire, ISSUER + "\\x00" + subject,
            )
        except (OSError, RuntimeError, ValueError):
            return web.Response(status=503, text="Isolated browser session unavailable")
    url = backend + ("?" + request.query_string if request.query_string else "")
    try:
        body = await request.read()
        async with request.app["upstream"].request(
            request.method, url, headers=headers, data=body if body else None,
            allow_redirects=False,
        ) as upstream:
            response_headers = {
                k: v for k, v in upstream.headers.items()
                if k.lower() in RESPONSE_HEADERS
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
    finally:
        if owner_key is not None:
            await asyncio.to_thread(request.app["isolated"].release, owner_key)


async def health(_request):
    return web.Response(text="ok")


async def isolated_cleanup(manager):
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(manager.reap)


async def lifespan(app):
    timeout = aiohttp.ClientTimeout(total=None, connect=5, sock_connect=5, sock_read=None)
    app["upstream"] = aiohttp.ClientSession(timeout=timeout, auto_decompress=False, trust_env=False)
    cleaner = None
    if SESSION_MODE == "isolated":
        from isolated_backends import IsolatedBackends
        app["isolated"] = IsolatedBackends(
            ROOT,
            max_sessions=int(os.environ.get("BROWSER_MAX_SESSIONS", "2")),
            idle_seconds=int(os.environ.get("BROWSER_IDLE_SECONDS", "900")),
            chromium=os.environ.get("CHROMIUM_BIN", "chromium"),
        )
        cleaner = asyncio.create_task(isolated_cleanup(app["isolated"]))
    try:
        yield
    finally:
        if cleaner:
            cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await cleaner
            await asyncio.to_thread(app["isolated"].shutdown)
        await app["upstream"].close()


app = web.Application(client_max_size=16 * 1024 * 1024)
app.cleanup_ctx.append(lifespan)
app.router.add_get("/internal-health", health)
for name in BACKENDS:
    app.router.add_get(f"/.well-known/oauth-protected-resource/{name}/mcp",
                       partial(metadata, service=name))
    app.router.add_route("*", f"/{name}/mcp", partial(proxy, service=name))

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8787, access_log=None)
