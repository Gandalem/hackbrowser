#!/usr/bin/env bash
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Run with sudo' >&2; exit 1; }
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
for name in pocmap chromium gui-chromium hackbrowser share oauth; do
  systemctl disable --now "mcpstack-$name.service" 2>/dev/null || true
done
systemctl disable --now mcpstack-share-stop.timer 2>/dev/null || true
if [[ -f "$ROOT/docker-compose.yml" && -f "$ROOT/runtime/private.env" ]]; then
  docker compose --env-file "$ROOT/runtime/private.env" -f "$ROOT/docker-compose.yml" --profile oauth down || true
fi
rm -f /etc/systemd/system/mcpstack-{pocmap,chromium,gui-chromium,hackbrowser,share,oauth,share-stop}.service
rm -f /etc/systemd/system/mcpstack-share-stop.timer
rm -rf /etc/systemd/system/mcpstack-{chromium,gui-chromium,hackbrowser}.service.d
systemctl unmask mcpstack-chromium.service >/dev/null 2>&1 || true
systemctl daemon-reload
echo 'Services stopped. Configuration/secrets and Docker database volume kept.'
if [[ "${1:-}" == '--purge' ]]; then
  echo 'Purge deletes local credentials and deployment files; Docker named data volume is kept.'
  rm -rf -- "$ROOT"
fi
