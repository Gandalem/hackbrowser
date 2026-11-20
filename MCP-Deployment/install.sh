#!/usr/bin/env bash
# Portable Linux deployment for PocMap, local-CDP HackBrowser, ZAP, Keycloak and MCP gateways.
# Deploys on an Ubuntu/Debian host (VMware, VirtualBox, AWS, OCI, NCP, VPS, bare metal).
set -Eeuo pipefail
umask 077

if (( EUID != 0 )); then
  echo "Run: sudo bash install.sh" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "Requires a systemd-based Ubuntu or Debian host." >&2; exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" ]]; then
  echo "Currently supports Ubuntu/Debian; detected $ID" >&2; exit 1
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
if [[ "$ROOT" == *" "* || "$ROOT" == *"'"* || "$ROOT" == *'"'* ]]; then
  echo "MCP_INSTALL_ROOT must not contain spaces or quotes" >&2; exit 1
fi

# Keep existing configuration on repeated installations. Do not unexpectedly reset keys.
EXISTING=0
if [[ -f "$ROOT/runtime/private.env" ]]; then
  EXISTING=1
  # This file is generated locally and writable only by root.
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/runtime/private.env"
  set +a
  echo "Existing installation detected; keeping URL, passwords and share expiry."
fi

if (( ! EXISTING )); then
  if [[ -z "${PUBLIC_BASE_URL:-}" ]]; then
    if [[ -t 0 ]]; then
      read -r -p 'Public MCP base URL [http://127.0.0.1:8088]: ' PUBLIC_BASE_URL
      PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1:8088}"
    else
      PUBLIC_BASE_URL="http://127.0.0.1:8088"
    fi
  fi
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL%/}"
  if [[ -z "${CADDY_MODE:-}" ]]; then
    if [[ "$PUBLIC_BASE_URL" == https://* ]]; then CADDY_MODE=public
    else CADDY_MODE=local; fi
  fi
  if [[ -z "${ENABLE_OAUTH:-}" ]]; then
    if [[ "$PUBLIC_BASE_URL" == https://* ]]; then ENABLE_OAUTH=1
    else ENABLE_OAUTH=0; fi
  fi
  SHARE_DAYS="${SHARE_DAYS:-7}"
  CHATGPT_REDIRECT_URI="${CHATGPT_REDIRECT_URI:-https://chatgpt.com/connector_platform_oauth_redirect}"
  MCP_LOGIN_USER="${MCP_LOGIN_USER:-mcp-operator}"
fi

export ROOT MCP_INSTALL_ROOT="$ROOT" PUBLIC_BASE_URL CADDY_MODE ENABLE_OAUTH SHARE_DAYS CHATGPT_REDIRECT_URI MCP_LOGIN_USER
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y python3
fi
python3 - <<'PY'
from urllib.parse import urlsplit
import os
p = urlsplit(os.environ['PUBLIC_BASE_URL'])
mode = os.environ['CADDY_MODE']
assert p.scheme in ('http','https') and p.hostname and not p.username and not p.password
assert p.path in ('','/') and not p.query and not p.fragment
assert mode in ('public','local','external')
assert os.environ['ENABLE_OAUTH'] in ('0','1')
assert os.environ['SHARE_DAYS'].isdigit() and 1 <= int(os.environ['SHARE_DAYS']) <= 365
if mode=='public':
  assert p.scheme == 'https' and p.port is None and '.' in p.hostname
if mode=='external':
  assert p.scheme == 'https'
if os.environ['ENABLE_OAUTH']=='1' and p.scheme!='https':
  raise SystemExit('OAuth requires a trusted HTTPS PUBLIC_BASE_URL')
print('Deployment mode:', mode, 'OAuth:', os.environ['ENABLE_OAUTH'])
PY

# Copy source without touching any existing runtime or credentials.
mkdir -p "$ROOT/services" "$ROOT/scripts" "$ROOT/templates" "$ROOT/docs" "$ROOT/runtime/secrets" "$ROOT/runtime/caddy/data" "$ROOT/runtime/caddy/config" "$ROOT/runtime/zap"
if [[ "$SOURCE_DIR" != "$ROOT" ]]; then
  cp -a "$SOURCE_DIR/services/." "$ROOT/services/"
  rm -f -- "$ROOT/services/gateway/screenshot_download.py"
  cp -a "$SOURCE_DIR/scripts/." "$ROOT/scripts/"
  cp -a "$SOURCE_DIR/templates/." "$ROOT/templates/"
  cp -a "$SOURCE_DIR/docs/." "$ROOT/docs/"
  cp "$SOURCE_DIR/docker-compose.yml" "$ROOT/docker-compose.yml"
  cp "$SOURCE_DIR/config.env.example" "$ROOT/config.env.example"
  cp "$SOURCE_DIR/status.sh" "$ROOT/status.sh"
  cp "$SOURCE_DIR/renew-share.sh" "$ROOT/renew-share.sh"
  cp "$SOURCE_DIR/uninstall.sh" "$ROOT/uninstall.sh"
  cp "$SOURCE_DIR/install.sh" "$ROOT/install.sh"
  cp "$SOURCE_DIR/README.md" "$ROOT/README.md"
fi

# Dedicated unprivileged service account; ZAP container retains its upstream image user.
if ! id mcpstack >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/mcpstack --shell /usr/sbin/nologin mcpstack
fi
MCP_GROUP="$(id -gn mcpstack)"
# Optional per-user browser profiles. Keep private to the service account.
install -d -m 0700 -o mcpstack -g "$MCP_GROUP" "$ROOT/runtime/isolated-browser-profiles"
chown root:"$MCP_GROUP" "$ROOT/runtime/secrets"
chmod 0750 "$ROOT/runtime/secrets"

if (( ! EXISTING )); then
  python3 - <<'PY'
import os, json, secrets, time, shlex
from pathlib import Path
root = Path(os.environ['ROOT'])
secret = lambda: secrets.token_urlsafe(30)
fields = {
 'PUBLIC_BASE_URL': os.environ['PUBLIC_BASE_URL'],
 'CADDY_MODE': os.environ['CADDY_MODE'],
 'ENABLE_OAUTH': os.environ['ENABLE_OAUTH'],
 'SHARE_DAYS': os.environ['SHARE_DAYS'],
 'CHATGPT_REDIRECT_URI': os.environ['CHATGPT_REDIRECT_URI'],
 'MCP_LOGIN_USER': os.environ['MCP_LOGIN_USER'],
 'POSTGRES_PASSWORD': secret(),
 'KEYCLOAK_ADMIN_PASSWORD': secret(),
 'MCP_LOGIN_PASSWORD': secret(),
}
# Inputs have already been validated. No user-supplied newlines or = signs.
for key, val in fields.items():
 if '\n' in val or '\r' in val or '\x00' in val:
  raise SystemExit('Invalid newline/null in config field: '+key)
priv = root/'runtime/private.env'
priv.write_text(''.join(k+'='+shlex.quote(v)+'\n' for k,v in fields.items()))
priv.chmod(0o600)
zapkey = secret()
(root/'runtime/secrets/zap-key').write_text(zapkey)
share = {'token':secrets.token_urlsafe(32), 'expires_at': int(time.time()) + int(fields['SHARE_DAYS'])*86400}
(root/'runtime/secrets/share.json').write_text(json.dumps(share))
print('Fresh installation secrets and unique time-limited sharing key generated')
PY
fi

# Read generated settings again so install and restart paths behave the same.
set -a
# shellcheck disable=SC1091
source "$ROOT/runtime/private.env"
set +a
export ROOT PUBLIC_BASE_URL CADDY_MODE ENABLE_OAUTH MCP_INSTALL_ROOT="$ROOT"
chown mcpstack:"$MCP_GROUP" "$ROOT/runtime/secrets/share.json" "$ROOT/runtime/secrets/zap-key"
chmod 0600 "$ROOT/runtime/secrets/share.json" "$ROOT/runtime/secrets/zap-key"
chmod 0600 "$ROOT/runtime/private.env"

cat > "$ROOT/runtime/public.env" <<EOF
PUBLIC_BASE_URL=$PUBLIC_BASE_URL
MCP_INSTALL_ROOT=$ROOT
ENABLE_OAUTH=$ENABLE_OAUTH
EOF
chmod 0644 "$ROOT/runtime/public.env"

# ZAP default Docker user is uid 1000. Keep its readable config outside the shipped archive.
ZAP_SECURITY_KEY="$(cat "$ROOT/runtime/secrets/zap-key")"
cat > "$ROOT/runtime/zap/mcp.properties" <<EOF
mcp.enabled=true
mcp.port=8282
mcp.securityKeyEnabled=true
mcp.securityKey=$ZAP_SECURITY_KEY
mcp.secureOnly=false
EOF
chown 1000:1000 "$ROOT/runtime/zap/mcp.properties"
chmod 0400 "$ROOT/runtime/zap/mcp.properties"
unset ZAP_SECURITY_KEY

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg python3 python3-venv python3-pip

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  # Prefer distro packages; fall back to the official Docker repository for Compose v2.
  apt-get install -y docker.io || true
  if ! apt-get install -y docker-compose-v2; then
    apt-get install -y docker-compose-plugin || true
  fi
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    . /etc/os-release
    mkdir -p /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker-mcp.list
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
fi
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  echo 'Docker Compose v2 unavailable' >&2; exit 1
fi

# The GUI launcher also requires a private X virtual display, even on servers.
# Keep platform-specific Chromium selection for OCI ARM64 and other Linux hosts.
apt-get install -y --no-install-recommends xvfb xauth
ARCH="$(dpkg --print-architecture)"
CHROME_BINARY=''
if [[ "$ARCH" == 'arm64' ]]; then
  CHROME_VERSION="${CHROME_CFT_VERSION:-158.0.8127.36}"
  if [[ ! "$CHROME_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Invalid Chrome version: $CHROME_VERSION" >&2; exit 1
  fi
  CHROME_BINARY='/opt/mcp-chrome/chrome-linux-arm64/chrome'
  if [[ ! -x "$CHROME_BINARY" ]]; then
    apt-get install -y --no-install-recommends \
      unzip libnss3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 \
      libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgtk-3-0
    chrome_zip="$(mktemp --suffix=.zip)"
    curl -fL --retry 3 -o "$chrome_zip" \
      "https://storage.googleapis.com/chrome-for-testing-public/$CHROME_VERSION/linux-arm64/chrome-linux-arm64.zip"
    install -d -m 0755 /opt/mcp-chrome
    unzip -oq "$chrome_zip" -d /opt/mcp-chrome
    rm -f "$chrome_zip"
    chmod -R a+rX /opt/mcp-chrome
  fi
else
  for binary in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$binary" >/dev/null 2>&1; then
      CHROME_BINARY="$(command -v "$binary")"; break
    fi
  done
  if [[ -z "$CHROME_BINARY" && "$ARCH" == 'amd64' ]]; then
    chrome_deb="$(mktemp --suffix=.deb)"
    curl -fL --retry 3 -o "$chrome_deb" \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y "$chrome_deb"
    rm -f "$chrome_deb"
    CHROME_BINARY="$(command -v google-chrome-stable)"
  fi
fi
[[ -n "$CHROME_BINARY" && -x "$CHROME_BINARY" ]] || {
  echo "No supported GUI Chrome/Chromium browser found for $ARCH" >&2
  exit 1
}
bash "$ROOT/scripts/ensure_korean_fonts.sh"

# Three separate venvs minimize dependency conflicts.
python3 -m venv "$ROOT/runtime/venv-pocmap"
"$ROOT/runtime/venv-pocmap/bin/python" -m pip install --disable-pip-version-check 'pocmap[server]==2.9.1'
python3 -m venv "$ROOT/runtime/venv-hackbrowser"
"$ROOT/runtime/venv-hackbrowser/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/services/hackbrowser/requirements.txt"
python3 -m venv "$ROOT/runtime/venv-gateway"
"$ROOT/runtime/venv-gateway/bin/python" -m pip install --disable-pip-version-check 'aiohttp>=3.12,<4' 'PyJWT[crypto]>=2.10,<3'
"$ROOT/runtime/venv-gateway/bin/python" -m py_compile "$ROOT/services/gateway/"*.py
"$ROOT/runtime/venv-hackbrowser/bin/python" -m py_compile \
  "$ROOT/services/hackbrowser/server.py" "$ROOT/services/hackbrowser/playwright_control.py"
# venvs are created by root under umask 077; services run as mcpstack.
chmod -R a+rX "$ROOT/runtime/venv-pocmap" "$ROOT/runtime/venv-hackbrowser" "$ROOT/runtime/venv-gateway"

python3 "$ROOT/scripts/render_config.py"

# Ensure script path and login home are accessible by mcpstack, not writable by it.
chmod 0755 "$ROOT/services/hackbrowser/start_chromium_gui.sh"
chmod 0755 "$ROOT" "$ROOT/runtime" "$ROOT/services" "$ROOT/scripts"

make_unit() {
  local service="$1" desc="$2" exec_line="$3" after="$4"
  sed -e "s|@DESCRIPTION@|$desc|g" \
      -e "s|@ROOT@|$ROOT|g" \
      -e "s|@EXEC@|$exec_line|g" \
      -e "s|@AFTER@|$after|g" \
    "$ROOT/templates/mcpstack.service.in" > "/etc/systemd/system/mcpstack-$service.service"
}
make_unit pocmap 'PocMap MCP' "$ROOT/runtime/venv-pocmap/bin/pocmap-mcp --transport http --host 127.0.0.1 --port 9000" ''
make_unit hackbrowser 'HackBrowser GUI CDP MCP bridge' "$ROOT/runtime/venv-hackbrowser/bin/python $ROOT/services/hackbrowser/server.py" 'After=mcpstack-gui-chromium.service'
make_unit share 'Time-limited generic MCP gateway' "$ROOT/runtime/venv-gateway/bin/python $ROOT/services/gateway/shared_gateway.py" ''
make_unit oauth 'Keycloak OAuth JWT MCP gateway' "$ROOT/runtime/venv-gateway/bin/python $ROOT/services/gateway/oauth_gateway.py" ''

systemctl daemon-reload
systemctl enable --now mcpstack-pocmap.service
CHROMIUM_BIN="$CHROME_BINARY" bash "$ROOT/scripts/configure_gui_chromium.sh"
systemctl enable --now mcpstack-share.service

cd "$ROOT"
# Pull/run key services; bridge and gateways bind 127.0.0.1 only.
docker compose --env-file "$ROOT/runtime/private.env" up -d zap
docker compose --env-file "$ROOT/runtime/private.env" run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile
docker compose --env-file "$ROOT/runtime/private.env" up -d caddy

if [[ "$ENABLE_OAUTH" == '1' ]]; then
  docker compose --env-file "$ROOT/runtime/private.env" --profile oauth up -d postgres keycloak
  python3 "$ROOT/scripts/provision_keycloak.py"
  systemctl enable --now mcpstack-oauth.service
else
  systemctl disable --now mcpstack-oauth.service >/dev/null 2>&1 || true
fi

# Expire and stop the share process. Expiry is also enforced by the proxy itself.
EXPIRATION_UTC="$(python3 - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
config=json.loads((Path(os.environ['ROOT'])/'runtime/secrets/share.json').read_text())
print(datetime.fromtimestamp(config['expires_at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
PY
)"
cat > /etc/systemd/system/mcpstack-share-stop.service <<'EOF'
[Unit]
Description=Stop temporary shared MCP access
[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl stop mcpstack-share.service
EOF
cat > /etc/systemd/system/mcpstack-share-stop.timer <<EOF
[Unit]
Description=Disable temporary MCP share after expiration
[Timer]
OnCalendar=$EXPIRATION_UTC
Persistent=true
Unit=mcpstack-share-stop.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now mcpstack-share-stop.timer

python3 - <<'PY'
import json, os
from pathlib import Path
from datetime import datetime, timezone
root=Path(os.environ['ROOT'])
config=json.loads((root/'runtime/secrets/share.json').read_text())
base=os.environ['PUBLIC_BASE_URL'].rstrip('/')
lines=[
 'MCP DEPLOYMENT - PRIVATE CONNECTION INFORMATION',
 'Shared URLs are bearer credentials: only share with authorized users.',
 '',
 *[f'{s}: {base}/share/{config["token"]}/{s}/mcp' for s in ('pocmap','hackbrowser','zap')],
 '',
 'Expires UTC: '+datetime.fromtimestamp(config['expires_at'],timezone.utc).isoformat(),
]
if os.environ['ENABLE_OAUTH']=='1':
 lines.extend(['','OAuth ChatGPT:'] + [f'{s}: {base}/{s}/mcp (Client ID chatgpt-{s})' for s in ('pocmap','hackbrowser','zap')])
 lines.append('Keycloak user: mcp-operator; first-login password stored in runtime/private.env')
p=root/'runtime/access-urls.txt'
p.write_text('\n'.join(lines)+'\n')
p.chmod(0o600)
PY

printf '\n=== MCP deployment installed ===\n'
printf 'Cloud/VM neutral: %s\n' "$PUBLIC_BASE_URL"
printf 'Mode: %s; OAuth: %s; share duration: %s days\n' "$CADDY_MODE" "$ENABLE_OAUTH" "$SHARE_DAYS"
printf 'Private connection URLs: sudo cat %s/runtime/access-urls.txt\n' "$ROOT"
printf 'Verify after all backends are ready: sudo bash %s/status.sh\n' "$ROOT"
printf 'Review Caddy/Docker service readiness with: docker compose -f %s/docker-compose.yml ps\n' "$ROOT"
