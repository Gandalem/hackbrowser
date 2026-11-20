#!/usr/bin/env bash
# One non-root Chromium GUI and one localhost CDP MCP, sharing one profile.
set -Eeuo pipefail
mkdir -p "$HOME/.local/share/hackbrowser-mcp/chromium-gui-profile"
profile="$HOME/.local/share/hackbrowser-mcp/chromium-gui-profile"
chmod 700 "$profile"
# --no-sandbox is required in the default Docker environment; this container
# must remain non-root, unprivileged and bound to the host loopback only.
xvfb-run -a -s '-screen 0 1366x900x24 -nolisten tcp' /usr/bin/chromium \
  --no-sandbox --disable-gpu --no-first-run --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 \
  --user-data-dir="$profile" --window-size=1366,900 about:blank &
chromium_pid=$!
mcp_pid=""
cleanup() {
  if [[ -n "$mcp_pid" ]]; then kill "$mcp_pid" 2>/dev/null || true; fi
  kill "$chromium_pid" 2>/dev/null || true
}
trap cleanup EXIT
ready=0
for _ in $(seq 1 50); do
  if curl --noproxy '*' -fsS --max-time 2 \
     http://127.0.0.1:9223/json/version >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$chromium_pid" 2>/dev/null; then
    echo 'GUI Chromium exited unexpectedly' >&2
    exit 1
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo 'GUI Chromium CDP 9223 did not start' >&2
  exit 1
fi
python /app/server.py &
mcp_pid=$!
# If either long-running service exits, stop both; Compose may restart.
wait -n "$chromium_pid" "$mcp_pid"
exit 1
