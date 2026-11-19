#!/usr/bin/env python3
"""Execute one harmless real MCP tool call per backend via the local share gateway."""
import json
import runpy
import sys
from pathlib import Path

ROOT = Path("/opt/mcp-deployment")
client = runpy.run_path(str(ROOT / "scripts/check_mcp.py"))
rpc = client["rpc"]
meta = client["META"]

checks = (
    ("hackbrowser", "browser_status", {}, "2026-07-28"),
    ("zap", "zap_version", {}, "2024-11-05"),
    ("pocmap", "get_cve_assessment_playbook", {}, "2026-07-28"),
)
errors = []
for service, name, arguments, protocol in checks:
    params = {"name": name, "arguments": arguments}
    if service != "zap":
        params["_meta"] = meta
    try:
        response = rpc(service, "tools/call", params, proto=protocol)
        if response.get("isError"):
            raise RuntimeError(str(response.get("content", ""))[:250])
        content = response.get("content", [])
        if not content or not isinstance(content[0].get("text"), str):
            raise RuntimeError("Missing tool response content")
        message = content[0]["text"]
        if service == "hackbrowser" and not json.loads(message).get("connected"):
            raise RuntimeError("Browser CDP reported disconnected")
        if service == "zap" and not message.strip().startswith("2."):
            raise RuntimeError("Unexpected ZAP version response")
        if service == "pocmap" and "CVE Assessment Playbook" not in message:
            raise RuntimeError("PocMap playbook was not returned")
        print(f"[PASS] {service}/{name}")
    except Exception as exc:
        errors.append(f"{service}/{name}: {exc}")
        print(f"[FAIL] {service}/{name}: {exc}")
if errors:
    raise SystemExit(1)
print("All three MCP backends passed real tools/call smoke tests")
