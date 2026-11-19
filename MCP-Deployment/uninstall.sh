#!/usr/bin/env bash
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Run with sudo' >&2; exit 1; }
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
for name in pocmap chromium hackbrowser share oauth; do
  systemctl disable --now "mcpstack-$name.service" 2>/dev/null || true
done
systemctl disable --now mcpstack-share-stop.timer 2>/dev/null || true
if [[ -f "$ROOT/docker-compose.yml" && -f "$ROOT/runtime/private.env" ]]; then
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" --profile oauth down || true
fi
rm -f /etc/systemd/system/mcpstack-{pocmap,chromium,hackbrowser,share,oauth,share-stop}.service
rm -f /etc/systemd/system/mcpstack-share-stop.timer
systemctl daemon-reload
echo 'Services stopped. Configuration/secrets and Docker database volume kept.'
if [[ "${1:-}" == '--purge' ]]; then
  echo 'Purge deletes local credentials and deployment files; Docker named data volume is kept.'
  rm -rf -- "$ROOT"
fi
