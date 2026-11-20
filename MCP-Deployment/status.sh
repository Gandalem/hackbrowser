#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
cd "$ROOT"
echo '=== Systemd ==='
for name in pocmap chromium gui-chromium hackbrowser share oauth; do
  if [[ "$name" == oauth ]] && [[ -r "$ROOT/runtime/public.env" ]] && ! grep -q 'ENABLE_OAUTH=1' "$ROOT/runtime/public.env"; then
    # OAuth is optional in local mode; still display if unexpectedly active.
    :
  fi
  printf '%-20s ' "mcpstack-$name"; systemctl is-active "mcpstack-$name.service" || true
done
echo '=== Docker ==='
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" ps
echo '=== Local endpoint status (no token printed) ==='
for port in 9000 8765 8282 8787 8790 9222 9223; do
  if timeout 2 bash -c "echo >/dev/tcp/127.0.0.1/$port" 2>/dev/null; then
    echo "127.0.0.1:$port LISTENING"
  else
    echo "127.0.0.1:$port not listening"
  fi
done
echo '=== Backend bind audit ==='
if command -v ss >/dev/null 2>&1; then
  ss -ltn | grep -E ':(8282|9222|9223|8765|9000|8787|8790)([[:space:]]|$)' || true
  if ss -ltn | grep -E '(^|[[:space:]])(0\.0\.0\.0|\[::\]|\*):(8282|9222|9223)([[:space:]]|$)' >/dev/null; then
    echo 'SECURITY WARNING: ZAP MCP or Chromium CDP may be listening on a non-loopback address.' >&2
  fi
fi
if [[ -r "$ROOT/runtime/public.env" ]] && grep -q '^ENABLE_OAUTH=1$' "$ROOT/runtime/public.env"; then
  echo '=== OAuth / Keycloak readiness ==='
  if ! systemctl is-active --quiet mcpstack-oauth.service; then
    echo '[FAIL] OAuth gateway is inactive' >&2
    exit 1
  fi
  if ! curl -fsS --max-time 5 http://127.0.0.1:8081/auth/realms/master/.well-known/openid-configuration >/dev/null; then
    echo '[FAIL] Keycloak admin API unreachable via localhost:8081' >&2
    exit 1
  fi
  echo '[PASS] Keycloak HTTP API'
  for service in pocmap hackbrowser zap; do
    code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8088/$service/mcp")" || {
      echo "[FAIL] $service OAuth route unreachable" >&2
      exit 1
    }
    if [[ "$code" != '401' ]]; then
      echo "[FAIL] $service OAuth route expected HTTP 401; got $code" >&2
      exit 1
    fi
    echo "[PASS] $service OAuth challenge: HTTP 401"
  done
fi
echo '=== GUI Chromium-only backend ==='
if systemctl is-active --quiet mcpstack-chromium.service; then
  echo '[FAIL] Legacy Headless Chromium is still active' >&2
  exit 1
fi
if ! systemctl is-active --quiet mcpstack-gui-chromium.service; then
  echo '[FAIL] GUI Chromium manager is inactive' >&2
  exit 1
fi
if timeout 2 bash -c 'echo >/dev/tcp/127.0.0.1/9222' 2>/dev/null; then
  echo '[FAIL] Legacy CDP 9222 is listening' >&2
  exit 1
fi
gui_version="$(curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:9223/json/version)" || {
  echo '[FAIL] GUI Chromium CDP 9223 is unavailable' >&2
  exit 1
}
if grep -qi 'HeadlessChrome' <<<"$gui_version"; then
  echo '[FAIL] CDP 9223 is headless, not GUI' >&2
  exit 1
fi
echo '[PASS] GUI Chromium CDP 9223; legacy CDP 9222 disabled'
echo '=== MCP tool discovery ==='
python3 "$ROOT/scripts/check_mcp.py"
echo '=== Share expiry ==='
python3 - "$ROOT/runtime/secrets/share.json" <<'PY'
import json,sys
from datetime import datetime,timezone
s=json.load(open(sys.argv[1]))
print(datetime.fromtimestamp(s['expires_at'],timezone.utc).isoformat(), 'UTC')
PY
