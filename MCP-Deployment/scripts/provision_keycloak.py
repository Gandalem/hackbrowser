#!/usr/bin/env python3
"""Initialize Keycloak realm + ChatGPT OAuth clients through loopback Admin REST.

Idempotent; reads credentials from the root-owned runtime/private.env file.
"""
import json
import os
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("MCP_INSTALL_ROOT", "/opt/mcp-deployment"))

def read_env():
    env = {}
    for line in (ROOT / "runtime/private.env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = shlex.split(v)[0] if v else ""
    return env

SETTINGS = read_env()
BASE = "http://127.0.0.1:8081/auth"
REALM = "security-mcp"
PUBLIC = SETTINGS["PUBLIC_BASE_URL"].rstrip("/")
REDIRECT = SETTINGS.get("CHATGPT_REDIRECT_URI", "https://chatgpt.com/connector_platform_oauth_redirect")


def raw_request(path, method="GET", data=None, token=None, form=False):
    url = BASE + path
    headers = {"Accept": "application/json"}
    if form:
        payload = urllib.parse.urlencode(data or {}).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is None:
        payload = None
    else:
        payload = json.dumps(data, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:240]
        raise RuntimeError(f"Keycloak API {method} {path}: HTTP {exc.code}: {body}") from exc


def authorized_request(path, method="GET", data=None):
    return raw_request(path, method, data, TOKEN)


def get_token():
    return raw_request(
        "/realms/master/protocol/openid-connect/token", "POST",
        {"client_id": "admin-cli", "grant_type": "password",
         "username": "mcpadmin", "password": SETTINGS["KEYCLOAK_ADMIN_PASSWORD"]},
        form=True,
    )["access_token"]


TOKEN = None
last_error = None
for attempt in range(60):
    try:
        TOKEN = get_token()
        break
    except (RuntimeError, OSError) as exc:
        # Keycloak may close/reset the connection during its initial bootstrap.
        # Retry rather than aborting on ConnectionResetError (Errno 104).
        last_error = exc
        if attempt < 59:
            time.sleep(3)
if not TOKEN:
    raise SystemExit(
        f"Keycloak admin API unavailable after retries; last error: "
        f"{type(last_error).__name__}: {last_error}. "
        "Check Keycloak logs and the host-only 127.0.0.1:8081 port mapping."
    )

realm_path = "/admin/realms/" + REALM
try:
    authorized_request(realm_path)
except RuntimeError as e:
    if "HTTP 404:" not in str(e):
        raise
    authorized_request("/admin/realms", "POST", {
        "realm": REALM, "enabled": True,
        "accessTokenLifespan": 300,
        "ssoSessionIdleTimeout": 1800,
    })
    print("Created Keycloak realm")


def client_by_id(client_id):
    values = authorized_request(realm_path + "/clients?clientId=" + urllib.parse.quote(client_id))
    return next((v for v in values if v.get("clientId") == client_id), None)


def create_client(data):
    obj = client_by_id(data["clientId"])
    if obj is None:
        authorized_request(realm_path + "/clients", "POST", data)
        obj = client_by_id(data["clientId"])
    if not obj:
        raise RuntimeError("Could not locate Keycloak client " + data["clientId"])
    return obj["id"]


def make_mapper(client_uuid, name, config):
    target = f"{realm_path}/clients/{client_uuid}/protocol-mappers/models"
    existing = authorized_request(target)
    if any(m.get("name") == name for m in existing):
        return
    authorized_request(target, "POST", {
        "name": name, "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
        "config": {"id.token.claim": "false", "access.token.claim": "true", **config},
    })


def ensure_scope(name):
    items = authorized_request(realm_path + "/client-scopes")
    obj = next((x for x in items if x.get("name") == name), None)
    if obj is None:
        authorized_request(realm_path + "/client-scopes", "POST", {
            "name": name, "protocol": "openid-connect",
            "attributes": {
                "include.in.token.scope": "true",
                "display.on.consent.screen": "false",
            },
        })
        items = authorized_request(realm_path + "/client-scopes")
        obj = next((x for x in items if x.get("name") == name), None)
    if obj is None:
        raise RuntimeError("Scope creation failed: " + name)
    return obj["id"]


for service in ("pocmap", "hackbrowser", "zap"):
    resource = f"{PUBLIC}/{service}/mcp"
    resource_client = f"{service}-resource"
    create_client({
        "clientId": resource_client, "enabled": True,
        "protocol": "openid-connect", "publicClient": True,
        "standardFlowEnabled": False, "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
        "attributes": {"resource_url": resource},
    })
    uuid = create_client({
        "clientId": f"chatgpt-{service}", "enabled": True,
        "protocol": "openid-connect", "publicClient": True,
        "standardFlowEnabled": True, "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
        "redirectUris": [REDIRECT], "webOrigins": [],
        "attributes": {"pkce.code.challenge.method": "S256"},
    })
    # Also refresh redirect URI for existing client after explicit operator changes.
    client = authorized_request(realm_path + "/clients/" + uuid)
    if REDIRECT not in client.get("redirectUris", []):
        client["redirectUris"] = [REDIRECT]
        authorized_request(realm_path + "/clients/" + uuid, "PUT", client)
    make_mapper(uuid, f"{service}-audience", {"included.client.audience": resource_client})
    make_mapper(uuid, f"{service}-url-audience", {"included.custom.audience": resource})
    scope_id = ensure_scope(f"mcp:{service}")
    authorized_request(
        f"{realm_path}/clients/{uuid}/default-client-scopes/{scope_id}", "PUT", {}
    )
    print("Configured", service, "OAuth client")

login_user = SETTINGS.get("MCP_LOGIN_USER", "mcp-operator")
login_password = SETTINGS["MCP_LOGIN_PASSWORD"]
user_q = urllib.parse.quote(login_user)
users = authorized_request(realm_path + "/users?username=" + user_q + "&exact=true")
user = next((x for x in users if x.get("username") == login_user), None)
if user is None:
    authorized_request(realm_path + "/users", "POST", {
        "username": login_user, "enabled": True,
    })
    users = authorized_request(realm_path + "/users?username=" + user_q + "&exact=true")
    user = next((x for x in users if x.get("username") == login_user), None)
    if user is None:
        raise RuntimeError("Failed to create Keycloak login user")
    authorized_request(
        f"{realm_path}/users/{user['id']}/reset-password", "PUT",
        {"type": "password", "value": login_password, "temporary": True}
    )
    print("Created login user (temporary password; change at first login)")
else:
    print("Existing login user kept (password unchanged)")

print("Keycloak provisioning complete")
