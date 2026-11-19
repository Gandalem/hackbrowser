#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
cd "$ROOT"
echo '=== Systemd ==='
for name in pocmap chromium hackbrowser share oauth; do
  if [[ "$name" == oauth ]] && [[ -r "$ROOT/runtime/public.env" ]] && ! grep -q 'ENABLE_OAUTH=1' "$ROOT/runtime/public.env"; then
    # OAuth is optional in local mode; still display if unexpectedly active.
    :
  fi
  printf '%-20s ' "mcpstack-$name"; systemctl is-active "mcpstack-$name.service" || true
done
echo '=== Docker ==='
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" ps
echo '=== Local endpoint status (no token printed) ==='
for port in 9000 8765 8282 8787 8790 9222; do
  if timeout 2 bash -c "echo >/dev/tcp/127.0.0.1/$port" 2>/dev/null; then
    echo "127.0.0.1:$port LISTENING"
  else
    echo "127.0.0.1:$port not listening"
  fi
done
echo '=== Backend bind audit ==='
if command -v ss >/dev/null 2>&1; then
  ss -ltn | grep -E ':(8282|9222|8765|9000|8787|8790)([[:space:]]|$)' || true
  if ss -ltn | grep -E '(^|[[:space:]])(0\.0\.0\.0|\[::\]|\*):(8282|9222)([[:space:]]|$)' >/dev/null; then
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
echo '=== MCP tool discovery ==='
python3 "$ROOT/scripts/check_mcp.py"
echo '=== Share expiry ==='
python3 - "$ROOT/runtime/secrets/share.json" <<'PY'
import json,sys
from datetime import datetime,timezone
s=json.load(open(sys.argv[1]))
print(datetime.fromtimestamp(s['expires_at'],timezone.utc).isoformat(), 'UTC')
PY
