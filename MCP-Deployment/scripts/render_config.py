#!/usr/bin/env python3
"""Generate cloud-neutral Caddy configuration from a small set of settings."""
import os
from pathlib import Path
from urllib.parse import urlsplit

root = Path(os.environ.get("MCP_INSTALL_ROOT", "/opt/mcp-deployment"))
url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
mode = os.environ.get("CADDY_MODE", "public")
oauth = os.environ.get("ENABLE_OAUTH", "0") == "1"
p = urlsplit(url)
if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.path not in {"", "/"}:
    raise SystemExit("PUBLIC_BASE_URL must be a scheme and hostname, without paths, user info or query")
if mode == "public":
    if p.scheme != "https" or p.port is not None or "." not in p.hostname:
        raise SystemExit("public mode requires https://your-public-domain without port")
    address = p.hostname
elif mode in {"local", "external"}:
    address = ":8088"
    if mode == "external" and p.scheme != "https":
        raise SystemExit("external proxy mode requires HTTPS public address")
else:
    raise SystemExit("CADDY_MODE must be public, local or external")

proto = "https" if p.scheme == "https" else "http"
forward_host = p.netloc
forward_port = str(p.port or (443 if proto == "https" else 80))

handlers = [
    "    header Cache-Control \"no-store\"",
    "    handle /healthz {",
    '        respond "ok" 200',
    "    }",
    "    handle /share/* {",
    "        reverse_proxy 127.0.0.1:8790",
    "    }",
    "    handle /captures/* {",
    "        reverse_proxy 127.0.0.1:8790",
    "    }",
]
if oauth:
    # The public admin/master realm endpoints are deliberately unavailable.
    handlers += [
        "    @keycloak {",
        "        path /auth/realms/security-mcp /auth/realms/security-mcp/* /auth/resources/*",
        "    }",
        "    handle @keycloak {",
        "        reverse_proxy 127.0.0.1:8081 {",
        f"            header_up X-Forwarded-Proto {proto}",
        f"            header_up X-Forwarded-Host {forward_host}",
        f"            header_up X-Forwarded-Port {forward_port}",
        "        }",
        "    }",
        "    @oauth_mcp {",
        "        path /pocmap/mcp /hackbrowser/mcp /zap/mcp /.well-known/oauth-protected-resource/*",
        "    }",
        "    handle @oauth_mcp {",
        "        reverse_proxy 127.0.0.1:8787",
        "    }",
    ]
handlers += [
    "    handle {",
    '        respond "Forbidden" 403',
    "    }",
]

site = address + " {\n" + "\n".join(handlers) + "\n}\n"
file = root / "runtime/caddy/Caddyfile"
file.parent.mkdir(parents=True, exist_ok=True)
file.write_text(site)
print("Caddy config:", address, "mode=", mode, "oauth=", oauth)
