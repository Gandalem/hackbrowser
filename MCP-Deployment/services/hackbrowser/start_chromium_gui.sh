#!/usr/bin/env bash
# A real GUI Chromium running on a private virtual X display (no headless mode).
set -Eeuo pipefail

if [[ -n "${CHROMIUM_BIN:-}" ]]; then
  BIN="$CHROMIUM_BIN"
else
  BIN=''
  for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      BIN="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$BIN" || ! -x "$BIN" ]]; then
  echo "GUI Chromium executable not found; set CHROMIUM_BIN." >&2
  exit 1
fi
for command in xvfb-run Xvfb xauth curl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "GUI Chromium requires $command." >&2
    exit 1
  }
done
PROFILE="${CHROMIUM_GUI_PROFILE:-$HOME/.local/share/hackbrowser-mcp/chromium-gui-profile}"
mkdir -p "$PROFILE"
chmod 0700 "$PROFILE"

# The previous OCI GUI session was started manually at :99 / CDP 9223.
# Keep that *visible* browser session while it is active, then take ownership
# automatically when it exits or after the next reboot. Never use CDP 9222.
version_url='http://127.0.0.1:9223/json/version'
version="$(curl --noproxy '*' -fsS --max-time 3 "$version_url" 2>/dev/null || true)"
if [[ -n "$version" ]]; then
  if grep -qi 'HeadlessChrome' <<<"$version"; then
    echo 'Refusing CDP 9223: a headless browser is already using it.' >&2
    exit 1
  fi
  echo 'Existing GUI Chromium on 127.0.0.1:9223; using it until it exits.'
  while curl --noproxy '*' -fsS --max-time 3 "$version_url" >/dev/null 2>&1; do
    sleep 3
  done
fi

# Port collisions with non-CDP processes must fail rather than switching ports.
if timeout 2 bash -c 'echo >/dev/tcp/127.0.0.1/9223' 2>/dev/null; then
  echo 'CDP port 9223 is occupied by an unknown process; refusing fallback.' >&2
  exit 1
fi

# xvfb-run creates a real X11 desktop (usually DISPLAY=:99). The browser
# renders GUI windows even without a VNC viewer attached.
exec xvfb-run -a -s '-screen 0 1366x900x24 -nolisten tcp' "$BIN" \
  --disable-gpu --no-first-run --no-default-browser-check \
  --disable-background-networking \
  --user-data-dir="$PROFILE" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9223 \
  --window-size=1366,900 about:blank
