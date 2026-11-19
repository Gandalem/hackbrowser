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
# Verify that the screenshot tool returns a real MCP image block, not only a server path.
try:
    import base64
    response = rpc(
        "hackbrowser", "tools/call",
        {"name": "browser_screenshot", "arguments": {}, "_meta": meta},
        proto="2026-07-28",
    )
    if response.get("isError"):
        raise RuntimeError(str(response.get("content", ""))[:250])
    blocks = response.get("content", [])
    images = [block for block in blocks if block.get("type") == "image"]
    texts = [block for block in blocks if block.get("type") == "text"]
    if len(images) != 1 or images[0].get("mimeType") != "image/png":
        raise RuntimeError("Missing inline MCP image/png content block")
    png = base64.b64decode(images[0].get("data", ""), validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Returned image content is not PNG")
    if not texts:
        raise RuntimeError("Missing saved file metadata")
    metadata = json.loads(texts[0]["text"])
    if metadata.get("bytes") != len(png) or not metadata.get("saved_path"):
        raise RuntimeError("Image/file metadata mismatch")
    print(f"[PASS] hackbrowser/browser_screenshot inline PNG ({len(png)} bytes)")
except Exception as exc:
    errors.append(f"hackbrowser/browser_screenshot: {exc}")
    print(f"[FAIL] hackbrowser/browser_screenshot: {exc}")

if errors:
    raise SystemExit(1)
print("All three MCP backends passed real tools/call smoke tests")
