# Isolated browser sessions (opt-in beta)

The OAuth gateway now supports per-user Chromium **and per-user MCP bridge
processes**. Existing deployments stay in `single` mode by default.

## Design

- JWT is validated at the OAuth gateway for the HackBrowser audience, scope,
  authorized client, issuer, signature and expiry.
- The gateway selects a backend from the **verified** issuer + `sub` claim.
  Browser tools never accept a client-selected user ID.
- Each backend has its own Chromium profile, localhost-only CDP port, private
  Xvfb display, MCP HTTP port, and separate in-memory state for screenshots,
  verification, tabs, handoff and workflows.
- The pool refuses new users at its configured limit, without falling back to
  the legacy shared browser. Idle backends exit; persistent profiles remain.
- Anonymous share-link requests to HackBrowser are refused when isolated mode
  is enabled. PocMap and ZAP share-link behavior is unchanged.
- All services still run as the `mcpstack` Linux user: this is application-level
  isolation, **not** a hardened OS/container security boundary against an
  attacker who has code execution on the host.

## Enabling on an existing server (do not reinstall)

Only enable after reviewing the code and with verified OAuth accounts.
The following assumes standard installation at /opt/mcp-deployment.

```bash
sudo install -d -m 0700 -o mcpstack -g mcpstack \
  /opt/mcp-deployment/runtime/isolated-browser-profiles
sudoedit /opt/mcp-deployment/runtime/public.env
```

Set these values in `public.env`:

```dotenv
ENABLE_OAUTH=1
BROWSER_SESSION_MODE=isolated
BROWSER_MAX_SESSIONS=2
BROWSER_IDLE_SECONDS=900
```

Restart the OAuth and share gateways after safely deploying updated service
files (leave existing Chromium and its profile untouched):

```bash
sudo systemctl restart mcpstack-oauth.service mcpstack-share.service
sudo systemctl status mcpstack-oauth.service --no-pager
```

The gateway starts a new Xvfb + Chromium + MCP bridge lazily for the first
authenticated request from each user. No migration of existing personal cookies
is attempted; each user signs in again in their isolated profile.

Switch back to `BROWSER_SESSION_MODE=single` and restart the gateways to
restore existing behavior without deleting isolated user profile directories.

## Limitations and verification needed

- The OCI ARM64 synthetic-user smoke and two real Keycloak JWT staging-account
  routing test both passed. This does not prove hardened multi-tenant isolation;
  interactive ChatGPT authorization-code/PKCE, idle cleanup, and hostile local
  process isolation still require separate checks.
- Isolated processes share the same Unix uid; for untrusted third parties use
  container/user-namespace boundaries and enforce per-process memory quotas.
- No native per-process memory quota is implemented; `MAX_SESSIONS=2` bounds
  the number of active browsers, not total RAM consumption.
- CDP and MCP backends listen on localhost only, but are unauthenticated at that
  level. Prevent other untrusted local processes from accessing those ports.
- Existing MCP sessions may need to reinitialize after idle shutdown or server
  restart; profile cookies persist, but transient MCP states do not.
- Shared persistent profiles are never automatically deleted. Account deletion
  and quota management require additional work.

## OCI real Keycloak JWT staging test

The PR also contains `MCP-Deployment/scripts/smoke_oauth_isolation.py`.
Use it **from a normal account with sudo**, against the existing Keycloak
realm after the synthetic-browser smoke test has passed:

```bash
cd ~/hb-isolation-test.nWOaei
git pull --ff-only origin feat/isolated-browser-session-pool
sudo /usr/bin/python3 MCP-Deployment/scripts/smoke_oauth_isolation.py
```

This integration test temporarily **creates three Keycloak test users and one
confidential direct-grant client in the live realm**, and deletes them at exit.
It needs root access to read `runtime/private.env`; credentials and JWTs are
not printed. Its temporary OAuth gateway binds a distinct loopback port and
runs with the invoking non-root account; it leaves production gateway port
8787, CDP 9223, MCP 8765 and existing user profiles untouched.

It verifies signed Keycloak JWT validation, account-specific backend routing,
synthetic page cookies, real PNG screenshots, cross-user target/handoff denial,
and third-account capacity rejection. The test uses the Keycloak password
grant **only for disposable accounts**, not the interactive ChatGPT PKCE flow.
Do not use it to verify ChatGPT authorization-code redirect behavior.

Cleanup is attempted on both success and failure. Abrupt machine termination
or SIGKILL can interrupt cleanup; if that happens, review/delete **only**
Keycloak entities whose names begin with the generated `hb-smoke-` prefix.
The test never deliberately alters existing Keycloak users or clients.

After any test run, verify cleanup with a **read-only** Keycloak audit:

```bash
sudo /usr/bin/python3 MCP-Deployment/scripts/smoke_oauth_isolation.py --verify-cleanup
sudo ss -lntp | grep -E ':(8787|9223|8765|932[0-9]|952[0-9])\\b'
```

The audit lists only the count of remaining disposable `hb-smoke-*` users and
clients. The port check confirms production listeners and looks for stale test
CDP/MCP processes. No deletion or process termination is performed by either
command. If leftovers are reported, investigate before merging or running the
next staged test.

On 2026-11-21 the user-provided OCI output reported **PASS** for real Keycloak
JWT issuance, invalid/missing JWT denial, two account-specific browser/CDP
routes, page/cookie isolation, PNG screenshots, foreign target/handoff token
denial and third-user capacity refusal. The cleanup message reported only an
attempt; independent cleanup audit remains pending.

## Required end-to-end tests

1. Two valid OAuth accounts have different CDP endpoints, tabs and screenshots.
2. Account A cannot use B's target ID, snapshot ID, verification ID,
   handoff control token or workflow ID.
3. Invalid JWT and missing scopes get 401, not the legacy shared profile.
4. Share-link HackBrowser access gets 403 in isolated mode.
5. With two active users, the third receives 503 without cross-session fallback.
6. Idle browser shutdown, profile restore and OAuth gateway restart work.
7. Concurrent page actions and long-lived SSE streams do not evict active users.
8. Monitor real CPU/RAM on the 3-vCPU/16-GB OCI server.

Unit tests for the pool:

```bash
cd /opt/mcp-deployment/services/hackbrowser
/opt/mcp-deployment/runtime/venv-hackbrowser/bin/python -m unittest -v test_session_pool.py
```
