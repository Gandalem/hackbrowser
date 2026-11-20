# Isolated browser sessions (work in progress)

This module is an **opt-in foundation**, not yet a multi-user security feature.

`session_pool.py` starts an independent local Chromium process and persistent profile for each **trusted upstream user subject**, with a maximum of two concurrent processes by default. An idle process can be stopped without deleting its profile. Each instance uses a distinct localhost CDP port.

**Not wired to the MCP server yet.** Existing deployments continue to use the single Chromium/CDP endpoint. Do **not** enable a multi-user rollout based on this module alone: the current MCP bridge still has shared mutable state, a fixed CDP address, and shared screenshot/handoff/workflow registries. Keycloak's validated identity must be propagated through the gateway and bound to all tool calls before selecting a session. A client-provided `owner_id` or header is not trusted identity.

Remaining integration requirements:

1. Validate authenticated Keycloak subject and issuer at the gateway, with fail-closed identity propagation and no identity supplied by tool arguments.
2. Pass per-request identity into every browser tool and choose the owner's CDP endpoint (including Playwright, screenshots, tab enumeration and CDP websockets).
3. Partition manual handoff, workflow, snapshot, verification, rate limit and browser-tab state per user. Reject access to another user's IDs, even if guessed.
4. Ensure browser process termination on server shutdown, enforce per-session memory limits, and test profile restore, idle eviction, port conflicts, and concurrent accounts.
5. Run two real OAuth accounts through the proxy to prove that cookies, screenshots, pages and control tokens never cross users.

Existing single-user installation and configuration are unchanged. Avoid exposing any CDP port externally.

Run unit tests from the service directory:

```bash
cd MCP-Deployment/services/hackbrowser
python3 -m unittest -v test_session_pool.py
```
