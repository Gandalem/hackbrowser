#!/usr/bin/env bash
# Deploy source to an existing MCP VM. Preserve runtime secrets and Python virtualenvs.
set -Eeuo pipefail
(( EUID == 0 )) || { echo "Run as root" >&2; exit 1; }
SOURCE="$1"
SHA="$2"
VERSION="${3:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid SHA" >&2; exit 1; }
if [[ -n "$VERSION" && ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid release version" >&2; exit 1
fi
ROOT="/opt/mcp-deployment"
[[ -f "$ROOT/runtime/private.env" && -d "$ROOT/runtime/venv-hackbrowser" ]] || {
  echo "Initial installation required before CI/CD" >&2; exit 1;
}
if [[ -n "$VERSION" && -f "$ROOT/runtime/deployed-version" && -f "$ROOT/runtime/deployed-commit" ]] \
    && [[ "$(cat "$ROOT/runtime/deployed-version")" == "$VERSION" ]] \
    && [[ "$(cat "$ROOT/runtime/deployed-commit")" == "$SHA" ]]; then
  echo "Release already deployed: $VERSION ($SHA); verifying services"
  bash "$ROOT/status.sh"
  python3 "$ROOT/scripts/check_calls.py"
  exit 0
fi
for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
  [[ -e "$SOURCE/$item" ]] || { echo "Missing release component: $item" >&2; exit 1; }
done
if ! cmp -s "$SOURCE/services/hackbrowser/requirements.txt" "$ROOT/services/hackbrowser/requirements.txt"; then
  echo "Python dependencies changed: installer review required" >&2; exit 1
fi
# This release adds an MCP Apps UI. Verify SDK support before touching live
# source or restarting systemd; fail safely if an older venv lacks the module.
"$ROOT/runtime/venv-hackbrowser/bin/python" -c "from mcp.server.apps import Apps"

BACKUP="$(mktemp -d /opt/mcp-deployment-rollback.XXXXXX)"
for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
  [[ ! -e "$ROOT/$item" ]] || cp -a "$ROOT/$item" "$BACKUP/"
done
# Caddyfile lives in persistent runtime, outside the versioned source copy.
# Preserve its previous working contents so a failed deployment can roll back.
if [[ -f "$ROOT/runtime/caddy/Caddyfile" ]]; then
  mkdir -p "$BACKUP/runtime/caddy"
  cp -p "$ROOT/runtime/caddy/Caddyfile" "$BACKUP/runtime/caddy/Caddyfile"
fi
rollback() {
  local code=$?
  trap - ERR
  echo "Deployment failed (exit $code); restoring previous code..." >&2
  for item in services scripts templates docs docker-compose.yml status.sh install.sh; do
    [[ ! -e "$BACKUP/$item" ]] || cp -a "$BACKUP/$item" "$ROOT/"
  done
  if [[ -f "$BACKUP/runtime/caddy/Caddyfile" ]]; then
    cp -p "$BACKUP/runtime/caddy/Caddyfile" "$ROOT/runtime/caddy/Caddyfile"
  fi
  systemctl restart mcpstack-hackbrowser.service mcpstack-share.service || true
  if systemctl is-enabled --quiet mcpstack-oauth.service; then
    systemctl restart mcpstack-oauth.service || true
  fi
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" up -d zap caddy || true
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" exec -T caddy caddy reload --config /etc/caddy/Caddyfile || true
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
# Re-render runtime Caddy routes on every source release. Merely copying
# render_config.py and running "compose up -d" leaves a running container on
# its previous config, so source changes must be applied explicitly.
(
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/runtime/private.env"
  set +a
  MCP_INSTALL_ROOT="$ROOT" python3 "$ROOT/scripts/render_config.py"
)
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile
chmod 0755 "$ROOT/services/hackbrowser/start_chromium_headless.sh"
# Upgrade already-running VMs without reinstalling or resetting MCP credentials.
# Install/check Hangul fonts before restarting the renderer so Chrome sees them.
bash "$ROOT/scripts/ensure_korean_fonts.sh"
"$ROOT/runtime/venv-hackbrowser/bin/python" -m py_compile "$ROOT/services/hackbrowser/server.py"
# Exercise actual module initialization: Python compilation alone does not
# validate extension registration or the ui:// resource on the target SDK.
"$ROOT/runtime/venv-hackbrowser/bin/python" -c "import runpy; runpy.run_path('$ROOT/services/hackbrowser/server.py', run_name='screenshot_ui_preflight')"
systemctl restart mcpstack-chromium.service mcpstack-hackbrowser.service mcpstack-share.service
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" up -d zap caddy
# "up -d" alone does not reload a modified bind-mounted Caddyfile.
docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
# The release must apply updated Compose networking to active OAuth installations.
# Updating the file alone leaves the old internal-only Keycloak container running.
if grep -q '^ENABLE_OAUTH=1$' "$ROOT/runtime/private.env"; then
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" --profile oauth up -d postgres keycloak
  systemctl enable --now mcpstack-oauth.service
  systemctl restart mcpstack-oauth.service
fi
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
if [[ -n "$VERSION" ]]; then
  printf '%s\n' "$VERSION" > "$ROOT/runtime/deployed-version"
  chmod 0644 "$ROOT/runtime/deployed-version"
fi
echo "DEPLOYMENT PASS version=${VERSION:-unknown} commit=$SHA"
bash "$ROOT/status.sh"
python3 "$ROOT/scripts/check_calls.py"
rm -rf -- "$BACKUP"
