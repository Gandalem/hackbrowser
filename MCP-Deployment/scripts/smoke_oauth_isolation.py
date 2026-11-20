#!/usr/bin/env python3
"""Run real Keycloak JWT -> staging gateway -> isolated browsers on OCI.

Run with sudo from the PR checkout. The script reads root-only private.env
without printing passwords/tokens; the staging gateway and browsers run as
the unprivileged invoking user. The production OAuth gateway, MCP endpoint,
Chromium and profiles remain untouched. All test realm users and client are
deleted on exit, including assertion failures.
"""
from __future__ import annotations

import json
import hashlib
import threading
import os
import pwd
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from keycloak_pkce import authorization_code

SOURCE = Path(__file__).resolve().parents[1]
LIVE = Path("/opt/mcp-deployment")
OPEN = build_opener(ProxyHandler({}))
REALM = "security-mcp"
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2026-07-28",
}
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "oci-oauth-isolation-test", "version": "1.0"},
}


class MarkerSite(BaseHTTPRequestHandler):
    def do_GET(self):
        marker = {"/alice": "ALICE", "/bob": "BOB"}.get(self.path)
        if marker is None:
            self.send_error(404)
            return
        body = (
            "<!doctype html><html><head><title>SMOKE-" + marker
            + "</title></head><body><h1>SMOKE-" + marker
            + "</h1><div id='ck'></div>"
            + "<script>document.getElementById('ck').textContent=document.cookie</script>"
            + "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "testowner=" + marker + "; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def request(url, method="GET", data=None, token=None, form=False, timeout=25):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        payload = (urlencode(data).encode() if form
                   else json.dumps(data).encode())
        headers["Content-Type"] = ("application/x-www-form-urlencoded" if form
                                   else "application/json")
    else:
        payload = None
    req = Request(url, data=payload, headers=headers, method=method)
    try:
        with OPEN.open(req, timeout=timeout) as response:
            body = response.read(15_000_000)
            if not body:
                return response.status, None
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, body.decode(errors="replace")
    except HTTPError as exc:
        # Never print raw Keycloak token errors: some versions may echo
        # user-supplied credentials in error_description.
        try:
            error = json.loads(exc.read(8192))
        except (ValueError, UnicodeDecodeError):
            error = None
        if isinstance(error, dict):
            code = error.get("error")
            description = error.get("error_description")
            safe_codes = {"invalid_grant", "invalid_client", "unauthorized_client",
                          "invalid_request", "access_denied"}
            reason_map = {
                "Account is not fully set up": "incomplete_profile_or_required_action",
                "Invalid user credentials": "invalid_user_credentials",
                "Client not allowed for direct access grants": "direct_grant_disabled",
                "Invalid client credentials": "invalid_client_credentials",
            }
            return exc.code, {
                "error": code if code in safe_codes else "unclassified",
                "reason": reason_map.get(description, "unspecified"),
            }
        return exc.code, None


def expect(status, wanted, description, details=None):
    if status != wanted:
        safe_detail = ""
        if isinstance(details, dict):
            code = details.get("error")
            reason = details.get("reason")
            if code in {"invalid_grant", "invalid_client", "unauthorized_client",
                        "invalid_request", "access_denied"}:
                safe_detail = f"; Keycloak error={code}"
            if reason in {"incomplete_profile_or_required_action",
                          "invalid_user_credentials", "direct_grant_disabled",
                          "invalid_client_credentials"}:
                safe_detail += f"; reason={reason}"
        raise RuntimeError(
            f"{description}: HTTP {status}, expected {wanted}{safe_detail}"
        )


def read_private_env():
    values = {}
    for line in (LIVE / "runtime/private.env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw = line.split("=", 1)
        words = shlex.split(raw)
        values[name] = words[0] if words else ""
    return values


def unused_local_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def decode_mcp(result):
    blocks = result.get("content", [])
    decoded = []
    for item in blocks:
        if item.get("type") == "text":
            try:
                decoded.append(json.loads(item["text"]))
            except ValueError:
                decoded.append({"text": item["text"]})
    return decoded[0] if len(decoded) == 1 else decoded


def mcp_call(port, jwt_token, name, args=None):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args or {},
                                     "_meta": META}}).encode()
    headers = dict(MCP_HEADERS)
    if jwt_token:
        headers["Authorization"] = "Bearer " + jwt_token
    headers["Mcp-Method"] = "tools/call"
    headers["Mcp-Name"] = name
    req = Request(f"http://127.0.0.1:{port}/hackbrowser/mcp",
                  payload, headers, method="POST")
    try:
        with OPEN.open(req, timeout=60) as response:
            code = response.status
            raw = response.read(15_000_000).decode()
    except HTTPError as exc:
        return exc.code, None, None
    if raw.lstrip().startswith(("event:", "data:")):
        raw = next(line[5:].strip() for line in raw.splitlines()
                   if line.startswith("data:"))
    obj = json.loads(raw)
    if "error" in obj:
        return code, {"isError": True}, obj["error"]
    result = obj.get("result", {})
    return code, result, decode_mcp(result)


def good(port, token, name, args=None):
    status, response, value = mcp_call(port, token, name, args)
    if status != 200 or not isinstance(response, dict) or response.get("isError"):
        raise RuntimeError(f"{name} failed (HTTP {status}); no tokens logged")
    return response, value


def flatten_tabs(value):
    if isinstance(value, dict) and "result" in value:
        value = value["result"]
    if isinstance(value, dict) and "target_id" in value:
        value = [value]
    if not isinstance(value, list) or not value:
        raise RuntimeError("No browser tab returned by staging OAuth gateway")
    return value


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: root access is needed only to read Keycloak admin credentials")
    caller = os.environ.get("SUDO_USER")
    if not caller or caller == "root":
        raise SystemExit("Use sudo from an ordinary OCI account, not a root login")
    account = pwd.getpwnam(caller)
    env = read_private_env()
    public = env["PUBLIC_BASE_URL"].rstrip("/")
    keycloak = "http://127.0.0.1:8081/auth"
    resource = f"{public}/hackbrowser/mcp"
    prefix = "hb-smoke-" + secrets.token_hex(6)
    client_id = prefix
    client_secret = secrets.token_urlsafe(32)
    user_passwords = [secrets.token_urlsafe(28) for _ in range(3)]
    users = [f"{prefix}-{suffix}" for suffix in ("alice", "bob", "charlie")]
    created_users = []
    client_uuid = None
    stage_process = None
    stage_root = None
    site = None
    site_thread = None

    if not (SOURCE / "services/hackbrowser/server.py").is_file():
        raise RuntimeError("Run from the HackBrowser PR branch checkout")
    for path in (LIVE / "runtime/venv-gateway/bin/python",
                 LIVE / "runtime/venv-hackbrowser/bin/python"):
        if not path.exists():
            raise RuntimeError(f"Missing service interpreter: {path}")
    # Preflight BEFORE creating temporary Keycloak identities: isolated
    # gateway imports session_pool, which needs websocket-client even though
    # the normal single-session gateway does not.
    gateway_python = LIVE / "runtime/venv-gateway/bin/python"
    gateway_module_check = subprocess.run(
        [str(gateway_python), "-c", "import aiohttp, jwt, websocket"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12,
        check=False,
    )
    if gateway_module_check.returncode:
        raise RuntimeError(
            "Staging gateway Python dependencies missing; install "
            "websocket-client>=1.8,<2 in runtime/venv-gateway "
            "before running the PKCE integration test"
        )
    chrome = next((path for name in ("google-chrome-stable", "chromium", "google-chrome")
                   if (path := shutil.which(name))), None)
    if not chrome:
        raise RuntimeError("Chromium executable not found")
    gateway_port = unused_local_port()
    pkce_mode = sys.argv[1:] == ["--pkce"]
    callback_port = unused_local_port() if pkce_mode else None
    callback_uri = f"http://127.0.0.1:{callback_port}/callback" if pkce_mode else None
    print("[INFO] Staging on loopback only; production ports remain untouched", flush=True)

    status, token_response = request(
        keycloak + "/realms/master/protocol/openid-connect/token",
        "POST", {"client_id": "admin-cli", "grant_type": "password",
                 "username": "mcpadmin",
                 "password": env["KEYCLOAK_ADMIN_PASSWORD"]}, form=True)
    expect(status, 200, "Keycloak admin authentication")
    admin_token = token_response["access_token"]
    realm_api = keycloak + "/admin/realms/" + REALM

    def admin(path, method="GET", data=None):
        return request(realm_api + path, method, data, token=admin_token)

    if "--verify-cleanup" in sys.argv:
        if sys.argv[1:] != ["--verify-cleanup"]:
            raise SystemExit("Only --verify-cleanup is supported")
        # Read-only review: never delete other accounts, clients, or profiles.
        counts = {}
        for kind, field in (("users", "username"), ("clients", "clientId")):
            first = 0
            matches = 0
            while first < 10000:
                status, items = admin(f"/{kind}?first={first}&max=100")
                expect(status, 200, f"List Keycloak {kind}")
                if not isinstance(items, list):
                    raise RuntimeError("Unexpected Keycloak listing response")
                matches += sum(
                    1 for item in items
                    if isinstance(item, dict)
                    and str(item.get(field, "")).startswith("hb-smoke-")
                )
                if len(items) < 100:
                    break
                first += len(items)
            else:
                raise RuntimeError("Keycloak listing exceeded safety page limit")
            counts[kind] = matches
        print("[INFO] Read-only Keycloak check; no credentials or tokens shown")
        for kind in ("users", "clients"):
            print(f"[INFO] Residual hb-smoke {kind}: {counts[kind]}")
        if any(counts.values()):
            raise SystemExit("[WARN] Temporary Keycloak identities remain; review before merging")
        print("[PASS] No hb-smoke Keycloak users or clients remain")
        return
    if len(sys.argv) != 1 and not pkce_mode:
        raise SystemExit("Usage: smoke_oauth_isolation.py [--pkce|--verify-cleanup]")

    try:
        status, scopes = admin("/client-scopes")
        expect(status, 200, "Scope lookup")
        scope = next((s for s in scopes if s.get("name") == "mcp:hackbrowser"), None)
        if scope is None:
            raise RuntimeError("Existing mcp:hackbrowser scope was not found")

        # No edits to the active ChatGPT OAuth client or existing users.
        status, _ = admin("/clients", "POST", {
            "clientId": client_id, "secret": client_secret, "enabled": True,
            "protocol": "openid-connect", "publicClient": False,
            "standardFlowEnabled": pkce_mode, "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": not pkce_mode, "serviceAccountsEnabled": False,
            "redirectUris": [callback_uri] if pkce_mode else [],
            "attributes": {"pkce.code.challenge.method": "S256"} if pkce_mode else {},
        })
        expect(status, 201, "Create temporary OAuth test client")
        status, found = admin("/clients?clientId=" + quote(client_id))
        expect(status, 200, "Find temporary OAuth client")
        match = next((c for c in found if c.get("clientId") == client_id), None)
        if not match:
            raise RuntimeError("Temporary client not discoverable for cleanup")
        client_uuid = match["id"]

        status, _ = admin(f"/clients/{client_uuid}/protocol-mappers/models", "POST", {
            "name": "smoke-resource-audience", "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {"id.token.claim": "false",
                       "access.token.claim": "true",
                       "included.custom.audience": resource},
        })
        expect(status, 201, "Create test client audience mapper")
        status, _ = admin(
            f"/clients/{client_uuid}/default-client-scopes/{scope['id']}",
            "PUT", {})
        expect(status, 204, "Assign existing MCP client scope")

        tokens = []
        for user, password in zip(users, user_passwords):
            # Keycloak 26 user-profile checks can deny direct grants even
            # when requiredActions is empty if names/email are missing.
            status, _ = admin("/users", "POST", {
                "username": user,
                "firstName": "Isolation",
                "lastName": "Smoke",
                "email": user + "@example.invalid",
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
            })
            expect(status, 201, "Create temporary user")
            status, found = admin("/users?username=" + quote(user) + "&exact=true")
            expect(status, 200, "Find temporary user")
            match = next((x for x in found if x.get("username") == user), None)
            if not match:
                raise RuntimeError("Temporary user not discoverable for cleanup")
            created_users.append(match["id"])
            status, _ = admin(
                "/users/" + quote(match["id"]) + "/reset-password",
                "PUT", {"type": "password", "value": password, "temporary": False},
            )
            expect(status, 204, "Set permanent password for disposable user")
            status, user_profile = admin("/users/" + quote(match["id"]))
            expect(status, 200, "Read disposable user profile")
            actions = user_profile.get("requiredActions") or []
            if actions:
                # Do not override the realm's required MFA or ToS policy.
                raise RuntimeError(
                    "Disposable account has required actions; direct grant "
                    + "cannot proceed under this realm policy: "
                    + ",".join(sorted(str(a)[:40] for a in actions))
                )
            if pkce_mode:
                code, verifier = authorization_code(
                    base_url=keycloak, public_base=public, realm=REALM,
                    client_id=client_id, redirect_uri=callback_uri,
                    username=user, password=password,
                )
                status, value = request(
                    keycloak + f"/realms/{REALM}/protocol/openid-connect/token",
                    "POST", {"client_id": client_id, "client_secret": client_secret,
                             "grant_type": "authorization_code", "code": code,
                             "redirect_uri": callback_uri, "code_verifier": verifier},
                    form=True,
                )
                expect(status, 200, "Exchange real Keycloak PKCE code", value)
            else:
                status, value = request(
                    keycloak + f"/realms/{REALM}/protocol/openid-connect/token",
                    "POST", {"client_id": client_id, "client_secret": client_secret,
                             "grant_type": "password", "username": user,
                             "password": password}, form=True)
                expect(status, 200, "Issue real user JWT", value)
            tokens.append(value["access_token"])
        print(
            "[PASS] Three real Keycloak "
            + ("authorization-code/PKCE S256" if pkce_mode else "direct-grant")
            + " JWTs issued to distinct temporary accounts", flush=True,
        )
        if pkce_mode:
            code, verifier = authorization_code(
                base_url=keycloak, public_base=public, realm=REALM,
                client_id=client_id, redirect_uri=callback_uri,
                username=users[0], password=user_passwords[0],
            )
            altered = ("A" if verifier[0] != "A" else "B") + verifier[1:]
            status, value = request(
                keycloak + f"/realms/{REALM}/protocol/openid-connect/token",
                "POST", {"client_id": client_id, "client_secret": client_secret,
                         "grant_type": "authorization_code", "code": code,
                         "redirect_uri": callback_uri, "code_verifier": altered},
                form=True,
            )
            if status != 400:
                raise AssertionError("Keycloak accepted mismatched S256 PKCE verifier")
            print("[PASS] Incorrect PKCE verifier was refused", flush=True)
            status, value = request(
                keycloak + f"/realms/{REALM}/protocol/openid-connect/token",
                "POST", {"client_id": client_id, "client_secret": client_secret,
                         "grant_type": "password", "username": users[0],
                         "password": user_passwords[0]}, form=True,
            )
            if status not in (400, 401, 403):
                raise AssertionError("Temporary PKCE client accepted password grant")
            print("[PASS] PKCE-only client refused direct password grant", flush=True)

        # Ensure an independent runtime root and a non-root staging gateway.
        stage_root = Path(tempfile.mkdtemp(prefix="hb-oauth-stage-"))
        for rel in ("services", "runtime", "runtime/isolated-browser-profiles"):
            (stage_root / rel).mkdir(parents=True, exist_ok=True)
        (stage_root / "services/hackbrowser").symlink_to(
            SOURCE / "services/hackbrowser", target_is_directory=True)
        (stage_root / "services/gateway").symlink_to(
            SOURCE / "services/gateway", target_is_directory=True)
        (stage_root / "runtime/venv-hackbrowser").symlink_to(
            LIVE / "runtime/venv-hackbrowser", target_is_directory=True)
        for rel in ("", "services", "runtime", "runtime/isolated-browser-profiles"):
            os.chown(stage_root / rel, account.pw_uid, account.pw_gid)
        os.chmod(stage_root / "runtime/isolated-browser-profiles", 0o700)

        stage_env = os.environ.copy()
        stage_env.update({
            "HOME": account.pw_dir, "MCP_INSTALL_ROOT": str(stage_root),
            "PUBLIC_BASE_URL": public, "ENABLE_OAUTH": "1",
            "BROWSER_SESSION_MODE": "isolated",
            "BROWSER_MAX_SESSIONS": "2",
            "BROWSER_IDLE_SECONDS": "600",
            "OAUTH_GATEWAY_PORT": str(gateway_port),
            "HACKBROWSER_STAGING_TEST_CLIENT": client_id,
            "CHROMIUM_BIN": chrome,
        })
        # The stage log lives under the disposable stage root and is
        # destroyed during cleanup; never print its potentially sensitive body.
        stage_log = stage_root / "runtime/gateway-staging.log"
        with stage_log.open("wb") as stage_stderr:
            stage_process = subprocess.Popen(
                [str(LIVE / "runtime/venv-gateway/bin/python"),
                 str(SOURCE / "services/gateway/oauth_gateway.py")],
                cwd=stage_root, env=stage_env, user=account.pw_uid,
                group=account.pw_gid, stdout=subprocess.DEVNULL,
                stderr=stage_stderr, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if stage_process.poll() is not None:
                raise RuntimeError(
                    "Staging OAuth gateway exited before health check "
                    f"(exit status {stage_process.returncode}); "
                    "check gateway Python dependencies and startup configuration"
                )
            try:
                status, _ = request(
                    f"http://127.0.0.1:{gateway_port}/internal-health", timeout=2)
                if status == 200:
                    break
            except (URLError, TimeoutError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Staging OAuth gateway startup timed out")

        # Every request passes through actual JWT validation and routing.
        status, _, _ = mcp_call(gateway_port, None, "browser_status")
        expect(status, 401, "Reject missing JWT")
        status, _, _ = mcp_call(gateway_port, "not-a-jwt", "browser_status")
        expect(status, 401, "Reject invalid JWT")
        print("[PASS] Missing and invalid JWTs denied", flush=True)

        _, first = good(gateway_port, tokens[0], "browser_status")
        _, second = good(gateway_port, tokens[1], "browser_status")
        if not (isinstance(first, dict) and isinstance(second, dict)
                and first["connected"] and second["connected"]
                and first["cdp"] != second["cdp"]):
            raise AssertionError("Different JWT subjects did not receive different Chromium")
        print("[PASS] Real Keycloak subjects routed to different Chromium endpoints", flush=True)

        _, tabs_a = good(gateway_port, tokens[0], "browser_tabs")
        _, tabs_b = good(gateway_port, tokens[1], "browser_tabs")
        a_target = flatten_tabs(tabs_a)[0]["target_id"]
        b_target = flatten_tabs(tabs_b)[0]["target_id"]
        if a_target == b_target:
            raise AssertionError("Different JWT users shared a browser target")
        site = ThreadingHTTPServer(("127.0.0.1", 0), MarkerSite)
        site_thread = threading.Thread(target=site.serve_forever, daemon=True)
        site_thread.start()
        site_url = "http://127.0.0.1:" + str(site.server_address[1])
        for jwt_token, target, marker in ((tokens[0], a_target, "alice"),
                                          (tokens[1], b_target, "bob")):
            good(gateway_port, jwt_token, "browser_navigate",
                 {"url": site_url + "/" + marker, "target_id": target})
        for jwt_token, target, marker, other in (
            (tokens[0], a_target, "ALICE", "BOB"),
            (tokens[1], b_target, "BOB", "ALICE")
        ):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                _, page = good(gateway_port, jwt_token, "browser_page_text",
                               {"target_id": target})
                if isinstance(page, dict) and ("testowner=" + marker) in page.get("text", ""):
                    if ("testowner=" + other) in page["text"]:
                        raise AssertionError("Cross-user cookie leakage")
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("Expected user-specific cookie not visible")
        print("[PASS] Real OAuth users have distinct pages and cookies", flush=True)

        image_digests = []
        for jwt_token, target in ((tokens[0], a_target), (tokens[1], b_target)):
            response, _ = good(gateway_port, jwt_token, "browser_screenshot",
                               {"target_id": target})
            images = [x["data"] for x in response.get("content", [])
                      if x.get("type") == "image" and x.get("mimeType") == "image/png"]
            if len(images) != 1:
                raise AssertionError("Missing PNG screenshot from OAuth gateway")
            image_digests.append(hashlib.sha256(images[0].encode()).hexdigest())
        if image_digests[0] == image_digests[1]:
            raise AssertionError("OAuth sessions returned identical screenshots")
        print("[PASS] Distinct PNG screenshots through Keycloak OAuth", flush=True)

        _, result = good(gateway_port, tokens[0], "browser_handoff_begin",
                         {"target_id": a_target})
        control_token = result["control_token"]
        try:
            status, response, _ = mcp_call(
                gateway_port, tokens[1], "browser_handoff_end",
                {"control_token": control_token})
            if status != 200 or not response.get("isError"):
                raise AssertionError("Other user's handoff token was accepted")
            status, response, _ = mcp_call(
                gateway_port, tokens[1], "browser_page_text",
                {"target_id": a_target})
            if status != 200 or not response.get("isError"):
                raise AssertionError("Other user's target ID was accepted")
        finally:
            good(gateway_port, tokens[0], "browser_handoff_end",
                 {"control_token": control_token})
        print("[PASS] Cross-user target ID and handoff token refused via OAuth", flush=True)

        status, _, _ = mcp_call(gateway_port, tokens[2], "browser_status")
        expect(status, 503, "Third account capacity limit")
        print("[PASS] Third valid Keycloak account denied at session capacity", flush=True)
        print("[RESULT] " + ("PKCE S256 " if pkce_mode else "")
              + "OAuth two-user isolation staging smoke PASSED", flush=True)

    finally:
        if site is not None:
            site.shutdown()
            site.server_close()
            if site_thread:
                site_thread.join(timeout=3)
        if stage_process is not None:
            if stage_process.poll() is None:
                os.killpg(stage_process.pid, signal.SIGTERM)
                try:
                    stage_process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    os.killpg(stage_process.pid, signal.SIGKILL)
                    stage_process.wait()
        if stage_root is not None:
            shutil.rmtree(stage_root, ignore_errors=False)
        cleanup_ids = list(created_users)
        for username in users:
            try:
                status, matches = admin(
                    "/users?username=" + quote(username) + "&exact=true")
                if status == 200:
                    cleanup_ids.extend(item["id"] for item in matches
                                       if item.get("username") == username)
            except (OSError, RuntimeError):
                print("[WARN] Could not recheck temporary users", file=sys.stderr)
        for user_uuid in reversed(list(dict.fromkeys(cleanup_ids))):
            try:
                status, _ = admin("/users/" + quote(user_uuid), "DELETE")
                if status not in (204, 404):
                    print("[WARN] Test user cleanup failed (HTTP status)", file=sys.stderr)
            except (OSError, RuntimeError):
                print("[WARN] Test user cleanup failed", file=sys.stderr)
        if not client_uuid:
            try:
                status, clients = admin("/clients?clientId=" + quote(client_id))
                if status == 200:
                    match = next((c for c in clients if c.get("clientId") == client_id), None)
                    client_uuid = match["id"] if match else None
            except (OSError, RuntimeError):
                print("[WARN] Could not recheck temporary client", file=sys.stderr)
        if client_uuid:
            try:
                status, _ = admin("/clients/" + quote(client_uuid), "DELETE")
                if status not in (204, 404):
                    print("[WARN] Test client cleanup failed (HTTP status)", file=sys.stderr)
            except (OSError, RuntimeError):
                print("[WARN] Test client cleanup failed", file=sys.stderr)
        print("[INFO] Staging runtime removed and temporary Keycloak entities cleanup attempted",
              flush=True)


if __name__ == "__main__":
    main()
