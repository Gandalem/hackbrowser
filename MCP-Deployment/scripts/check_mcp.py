#!/usr/bin/env python3
"""Read-only protocol handshake and tool discovery via share gateway on loopback."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("MCP_INSTALL_ROOT", "/opt/mcp-deployment"))
CONFIG = json.loads((ROOT / "runtime/secrets/share.json").read_text())
BASE = "http://127.0.0.1:8790/share/" + CONFIG["token"]
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "deployment-check", "version": "1.0"},
}


def rpc(service, method, params=None, proto="2026-07-28"):
    payload = {"jsonrpc": "2.0", "method": method}
    if method != "notifications/initialized":
        payload["id"] = 1
    if params is not None:
        payload["params"] = params
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Method": method,
        "MCP-Protocol-Version": proto,
    }
    if method == "tools/call":
        name = (params or {}).get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tools/call requires a non-empty tool name")
        headers["Mcp-Name"] = name
    req = urllib.request.Request(
        f"{BASE}/{service}/mcp",
        data=json.dumps(payload).encode(), headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, body = response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read().decode(errors="replace")
    if status == 202 and not body:
        return {}
    try:
        if body.lstrip().startswith(("data:", "event:")):
            line = next(line for line in body.splitlines() if line.startswith("data:"))
            data = json.loads(line[5:].strip())
        else:
            data = json.loads(body)
    except (StopIteration, ValueError) as exc:
        raise RuntimeError(f"{service} {method}: HTTP {status}, non-JSON body") from exc
    if status not in (200, 202) or "error" in data:
        raise RuntimeError(f"{service} {method}: HTTP {status}, response={str(data)[:300]}")
    return data.get("result", {})


EXPECTED = {"pocmap": 22, "hackbrowser": 20, "zap": 17}
failures = []
for service in EXPECTED:
    try:
        if service == "zap":
            rpc(service, "initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "deployment-check", "version": "1.0"},
            }, proto="2024-11-05")
            rpc(service, "notifications/initialized", {}, proto="2024-11-05")
            result = rpc(service, "tools/list", {}, proto="2024-11-05")
        else:
            rpc(service, "server/discover", {"_meta": META})
            result = rpc(service, "tools/list", {"_meta": META})
        count = len(result.get("tools", []))
        ok = count == EXPECTED[service]
        print(f"{service}: {count}/{EXPECTED[service]} tools {'PASS' if ok else 'CHECK'}")
        if not ok:
            failures.append(service)
    except Exception as exc:
        print(f"{service}: FAIL ({exc})")
        failures.append(service)
if failures:
    raise SystemExit("Discovery failed: " + ", ".join(failures))
print("MCP discovery passed (actual tools/call requires client verification)")
