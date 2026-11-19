#!/usr/bin/env bash
# Generate a fresh share token and expiration. Existing distributed URLs stop working.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Run with sudo' >&2; exit 1; }
ROOT="${MCP_INSTALL_ROOT:-/opt/mcp-deployment}"
DAYS="${1:-7}"
[[ "$DAYS" =~ ^[0-9]+$ ]] && (( DAYS >= 1 && DAYS <= 365 )) || { echo 'Usage: sudo bash renew-share.sh [days 1-365]' >&2; exit 1; }
export ROOT DAYS
python3 - <<'PY'
import json, os, secrets, time
from pathlib import Path
root=Path(os.environ['ROOT'])
p=root/'runtime/secrets/share.json'
c={'token':secrets.token_urlsafe(32),'expires_at':int(time.time())+int(os.environ['DAYS'])*86400}
p.write_text(json.dumps(c))
p.chmod(0o600)
print('Share token rotated and expiration renewed')
PY
chown mcpstack:mcpstack "$ROOT/runtime/secrets/share.json"
EXPIRATION_UTC="$(python3 - <<'PY'
import json,os
from pathlib import Path
from datetime import datetime,timezone
c=json.loads((Path(os.environ['ROOT'])/'runtime/secrets/share.json').read_text())
print(datetime.fromtimestamp(c['expires_at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
PY
)"
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
systemctl restart mcpstack-share-stop.timer
systemctl enable --now mcpstack-share.service
python3 - <<'PY'
import json,os
from pathlib import Path
from datetime import datetime,timezone
root=Path(os.environ['ROOT'])
s=json.loads((root/'runtime/secrets/share.json').read_text())
values={}
for line in (root/'runtime/private.env').read_text().splitlines():
 if '=' in line:
  k,v=line.split('=',1); values[k]=__import__('shlex').split(v)[0] if v else ''
base=values['PUBLIC_BASE_URL'].rstrip('/')
lines=['Shared MCP URLs (secret; distribute only to authorized users)']
for service in ('pocmap','hackbrowser','zap'):
 lines.append(f'{service}: {base}/share/{s["token"]}/{service}/mcp')
lines.append('Expires UTC: '+datetime.fromtimestamp(s['expires_at'],timezone.utc).isoformat())
(root/'runtime/access-urls.txt').write_text('\n'.join(lines)+'\n')
(root/'runtime/access-urls.txt').chmod(0o600)
PY
printf 'New URLs: sudo cat %s/runtime/access-urls.txt\n' "$ROOT"
