#!/usr/bin/env bash
# Deploy source to an existing MCP VM. Preserve runtime secrets and Python virtualenvs.
set -Eeuo pipefail
(( EUID == 0 )) || { echo "Run as root" >&2; exit 1; }
SOURCE="$1"
SHA="$2"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid SHA" >&2; exit 1; }
ROOT="/opt/mcp-deployment"
[[ -f "$ROOT/runtime/private.env" && -d "$ROOT/runtime/venv-hackbrowser" ]] || {
  echo "Initial installation required before CI/CD" >&2; exit 1;
}
for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
  [[ -e "$SOURCE/$item" ]] || { echo "Missing release component: $item" >&2; exit 1; }
done
if ! cmp -s "$SOURCE/services/hackbrowser/requirements.txt" "$ROOT/services/hackbrowser/requirements.txt"; then
  echo "Python dependencies changed: installer review required" >&2; exit 1
fi
BACKUP="$(mktemp -d /opt/mcp-deployment-rollback.XXXXXX)"
for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
  [[ ! -e "$ROOT/$item" ]] || cp -a "$ROOT/$item" "$BACKUP/"
done
rollback() {
  local code=$?
  trap - ERR
  echo "Deployment failed (exit $code); restoring previous code..." >&2
  for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
    [[ ! -e "$BACKUP/$item" ]] || cp -a "$BACKUP/$item" "$ROOT/"
  done
  systemctl restart mcpstack-hackbrowser.service mcpstack-share.service || true
  if systemctl is-enabled --quiet mcpstack-oauth.service; then
    systemctl restart mcpstack-oauth.service || true
  fi
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" up -d zap caddy || true
  echo "Restored files from $BACKUP. Verify service status." >&2
  exit "$code"
}
trap rollback ERR
cp -a "$SOURCE/services/." "$ROOT/services/"
cp -a "$SOURCE/scripts/." "$ROOT/scripts/"
cp -a "$SOURCE/templates/." "$ROOT/templates/"
cp -a "$SOURCE/docs/." "$ROOT/docs/"
cp "$SOURCE/docker-compose.yml" "$ROOT/docker-compose.yml"
cp "$SOURCE/status.sh" "$ROOT/status.sh"
cp "$SOURCE/install.sh" "$ROOT/install.sh"
chmod 0755 "$ROOT/services/hackbrowser/start_chromium_headless.sh"
"$ROOT/runtime/venv-hackbrowser/bin/python" -m py_compile "$ROOT/services/hackbrowser/server.py"
systemctl restart mcpstack-hackbrowser.service mcpstack-share.service
if systemctl is-enabled --quiet mcpstack-oauth.service; then
  systemctl restart mcpstack-oauth.service
fi
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" up -d zap caddy
healthy=0
for attempt in $(seq 1 18); do
  if bash "$ROOT/status.sh" >/dev/null 2>&1 && python3 "$ROOT/scripts/check_calls.py" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 10
done
if [[ "$healthy" -ne 1 ]]; then
  echo "MCP discovery or actual tool-call verification failed" >&2
  false
fi
trap - ERR
printf '%s\n' "$SHA" > "$ROOT/runtime/deployed-commit"
chmod 0644 "$ROOT/runtime/deployed-commit"
echo "DEPLOYMENT PASS commit=$SHA"
bash "$ROOT/status.sh"
python3 "$ROOT/scripts/check_calls.py"
rm -rf -- "$BACKUP"
