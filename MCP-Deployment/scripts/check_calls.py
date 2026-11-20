#!/usr/bin/env python3
"""Execute one harmless real MCP tool call per backend via the local share gateway."""
import json
import runpy
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
        raise RuntimeError("Missing screenshot metadata")
    metadata = json.loads(texts[0]["text"])
    if metadata.get("bytes") != len(png) or metadata.get("mime_type") != "image/png":
        raise RuntimeError("MCP screenshot metadata mismatch")
    if "download_url" in metadata or "saved_path" in metadata:
        raise RuntimeError("Legacy server screenshot download metadata must not be returned")
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    # Caddy must no longer expose any public screenshot endpoint.
    caddy_config = (ROOT / "runtime/caddy/Caddyfile").read_text()
    if "handle /captures/*" in caddy_config:
        raise RuntimeError("Legacy public screenshot path is still exposed")
    from urllib.error import HTTPError
    try:
        with urlopen("http://127.0.0.1:8088/captures/deprecated.png", timeout=5) as unused:
            raise RuntimeError(f"Legacy screenshot endpoint unexpectedly returned {unused.status}")
    except HTTPError as response:
        if response.code not in (403, 404):
            raise RuntimeError(f"Legacy screenshot endpoint returned unexpected {response.code}")
    print(f"[PASS] hackbrowser/browser_screenshot inline PNG only ({len(png)} bytes)")
except Exception as exc:
    errors.append(f"hackbrowser/browser_screenshot: {exc}")
    print(f"[FAIL] hackbrowser/browser_screenshot: {exc}")

if errors:
    raise SystemExit(1)
print("All three MCP backends passed real tools/call smoke tests")
