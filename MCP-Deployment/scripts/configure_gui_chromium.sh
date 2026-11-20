#!/usr/bin/env bash
# Idempotent migration: disable the old Headless Chromium unit, manage GUI CDP.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Run as root' >&2; exit 1; }
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
[[ -f "$ROOT/templates/mcpstack.service.in" ]] || {
  echo 'MCP systemd template not found' >&2
  exit 1
}
id mcpstack >/dev/null || { echo 'mcpstack service account is missing' >&2; exit 1; }

if ! command -v xvfb-run >/dev/null || ! command -v Xvfb >/dev/null || ! command -v xauth >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends xvfb xauth
fi

CHROME_BINARY="${CHROMIUM_BIN:-}"
if [[ -z "$CHROME_BINARY" && -x /opt/mcp-chrome/chrome-linux-arm64/chrome ]]; then
  CHROME_BINARY='/opt/mcp-chrome/chrome-linux-arm64/chrome'
fi
if [[ -z "$CHROME_BINARY" ]]; then
  for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME_BINARY="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$CHROME_BINARY" || ! -x "$CHROME_BINARY" || "$CHROME_BINARY" == *' '* ]]; then
  echo 'A GUI-capable Chrome/Chromium executable is required.' >&2
  exit 1
fi

MCP_GROUP="$(id -gn mcpstack)"
install -d -m 0700 -o mcpstack -g "$MCP_GROUP" /var/lib/mcpstack/.runtime
chmod 0755 "$ROOT/services/hackbrowser/start_chromium_gui.sh"

# Bring down the old browser *before* starting the GUI service. Remove the
# legacy unit and mask it to prevent restarts, including after server reboot.
systemctl disable --now mcpstack-chromium.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/mcpstack-chromium.service
rm -rf /etc/systemd/system/mcpstack-chromium.service.d
systemctl daemon-reload
systemctl mask --now mcpstack-chromium.service >/dev/null

sed -e 's|@DESCRIPTION@|GUI Chromium CDP for HackBrowser|g' \
    -e "s|@ROOT@|$ROOT|g" \
    -e "s|@EXEC@|/bin/bash $ROOT/services/hackbrowser/start_chromium_gui.sh|g" \
    -e 's|@AFTER@||g' \
    "$ROOT/templates/mcpstack.service.in" \
    > /etc/systemd/system/mcpstack-gui-chromium.service
install -d -m 0755 /etc/systemd/system/mcpstack-gui-chromium.service.d
cat > /etc/systemd/system/mcpstack-gui-chromium.service.d/10-gui.conf <<EOF
[Service]
Environment=XDG_RUNTIME_DIR=/var/lib/mcpstack/.runtime
Environment=CHROMIUM_BIN=$CHROME_BINARY
EOF

# Existing installations still have After=mcpstack-chromium.service.
# Repoint the bridge without requiring the initial installer to run again.
if [[ -f /etc/systemd/system/mcpstack-hackbrowser.service ]]; then
  sed -i 's/After=mcpstack-chromium.service/After=mcpstack-gui-chromium.service/g' \
    /etc/systemd/system/mcpstack-hackbrowser.service
fi
install -d -m 0755 /etc/systemd/system/mcpstack-hackbrowser.service.d
cat > /etc/systemd/system/mcpstack-hackbrowser.service.d/10-gui-cdp.conf <<'EOF'
[Service]
Environment=HACKBROWSER_CDP_PORT=9223
EOF
systemctl daemon-reload
systemctl enable --now mcpstack-gui-chromium.service
systemctl enable --now mcpstack-hackbrowser.service
systemctl restart mcpstack-hackbrowser.service
echo '[PASS] GUI Chromium-only service configured; CDP 127.0.0.1:9223'
