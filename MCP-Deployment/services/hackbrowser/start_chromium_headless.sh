#!/usr/bin/env bash
set -euo pipefail
# This is a compatible modern CDP alternative, NOT HackBrowser.
# It can be used when Electron 2.x no longer runs on the Ubuntu release.
if [[ -n "${CHROMIUM_BIN:-}" ]]; then
  BIN="$CHROMIUM_BIN"
else
  BIN=''
  for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$candidate" >/dev/null 2>&1; then BIN="$(command -v "$candidate")"; break; fi
  done
fi
if [[ -z "$BIN" || ! -x "$BIN" ]]; then
  echo 'Chromium/Chrome executable not found. Install a current Chromium/Chrome package.' >&2
  echo 'Or specify an executable with CHROMIUM_BIN=/path/to/chrome.' >&2
  exit 1
fi
PROFILE="${CHROMIUM_PROFILE:-$HOME/.local/share/hackbrowser-mcp/chromium-profile}"
mkdir -p "$PROFILE"
chmod 700 "$PROFILE"
# User data dir must differ from the default browser profile for modern Chrome.
# Keep CDP bound to loopback; never disable Chrome sandbox on a normal VM.
exec "$BIN" --headless=new --disable-gpu --no-first-run \
  --no-default-browser-check --disable-background-networking \
  --user-data-dir="$PROFILE" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --window-size=1366,900 about:blank
