# MCP Deployment — 서버 운영 가이드

[빠른 설치](../README.md) · [47개 도구](../docs/TOOLS.md) · [릴리스/OCI 배포](../docs/RELEASE.md) · [구성 출처](docs/PROVENANCE.md)

Ubuntu/Debian **systemd 서버**용입니다. 클라우드 업체와 관계없이 설치할 수 있지만, 새 VM 전체 설치·네트워크 연동은 환경별 확인이 필요합니다. 관리자 권한, 인터넷, 권장 메모리 8GB·디스크 15GB 이상을 준비하세요.

## 설치 모드 선택

| 모드 | 사용 시점 | 서버 설정 |
|---|---|---|
| `local` | 서버 내부만 이용 | `PUBLIC_BASE_URL=http://127.0.0.1:8088`, `ENABLE_OAUTH=0` |
| `external` | **외부 HTTPS 연결이 이미 구성됨** | `PUBLIC_BASE_URL=https://mcp.example.com`, `ENABLE_OAUTH=1` |
| `public` | 서버의 Caddy가 직접 TLS 처리 | `PUBLIC_BASE_URL=https://mcp.example.com`, `ENABLE_OAUTH=1`, TCP 80/443 필요 |

외부 HTTPS 프록시/터널을 사용하는 `external` 모드에서는 서버의 **HTTP 8088**로 연결하고 `Host`, `Authorization`, MCP 관련 헤더를 그대로 전달하며 캐시를 끕니다. 8088은 신뢰한 프록시에서만 접근하도록 제한하세요. 도메인 업체별 연결 절차는 여기서 다루지 않습니다.

새 설치 명령은 [메인 README](../README.md#빠른-설치)에 있습니다. **기존 설치가 있다면 `install.sh`를 재실행해서 계정을 초기화하지 마세요.**

## 로그인 계정 발급 및 조회

처음 설치할 때 `MCP_LOGIN_USER`(기본 `mcp-operator`)를 지정할 수 있습니다. `MCP_LOGIN_PASSWORD`와 `KEYCLOAK_ADMIN_PASSWORD`는 설치 중 자동 생성합니다. 이미 설치된 서버의 값을 다시 설치 명령으로 변경할 수는 없습니다.

```bash
# 화면에 비밀번호가 표시됨 — 화면 공유와 셸 기록에 주의
sudo grep -E '^(MCP_LOGIN_USER|MCP_LOGIN_PASSWORD|KEYCLOAK_ADMIN_PASSWORD)=' \
  /opt/mcp-deployment/runtime/private.env
```

| 계정/값 | 사용처 |
|---|---|
| `MCP_LOGIN_USER` + `MCP_LOGIN_PASSWORD` | MCP 일반 사용자 로그인 및 **최초 임시 비밀번호** |
| `mcpadmin` + `KEYCLOAK_ADMIN_PASSWORD` | Keycloak 관리자 로그인 |
| `chatgpt-pocmap` / `chatgpt-hackbrowser` / `chatgpt-zap` | ChatGPT OAuth **Client ID** (로그인 ID가 아님) |

처음 로그인하면 임시 비밀번호를 변경합니다. 변경 후에는 **현재 비밀번호를 조회할 수 없고** `private.env`에는 초기 발급값이 남습니다. 비밀번호 분실 시 재설정해야 합니다.

## 추가 사용자 생성

기존 `mcp-operator`를 유지하고 **Keycloak `security-mcp` Realm**에 새 사용자를 추가합니다. OAuth가 활성화되어 있어야 합니다.

```bash
ROOT=/opt/mcp-deployment
# 같은 서버에서 Keycloak 관리자 명령 실행
kc() {
  sudo docker compose --env-file "$ROOT/runtime/private.env" \
    -f "$ROOT/docker-compose.yml" --profile oauth exec keycloak \
    /opt/keycloak/bin/kcadm.sh "$@"
}

# 관리자 ID: mcpadmin / 비밀번호: KEYCLOAK_ADMIN_PASSWORD
kc config credentials --server http://127.0.0.1:8080/auth \
  --realm master --user mcpadmin

NEW_USER=teamuser02  # 원하는 새 로그인 ID로 교체
kc create users -r security-mcp -s "username=$NEW_USER" -s enabled=true
read -r -s -p '새 사용자 임시 비밀번호: ' NEW_PASS; echo
kc set-password -r security-mcp --username "$NEW_USER" \
  --new-password "$NEW_PASS" --temporary
unset NEW_PASS
kc get users -r security-mcp -q "username=$NEW_USER"
```

추가 사용자는 기존 MCP 연결 주소에서 새 ID·임시 비밀번호로 로그인한 뒤 비밀번호를 변경합니다. 추가 사용자 비밀번호는 `private.env`에 저장되지 않습니다. 분실 시 관리자가 위 `set-password` 명령으로 **새 임시 비밀번호를 발급**할 수 있습니다. 명령 인자로 전달한 암호는 실행 중 프로세스 목록에 잠시 노출될 수 있으므로 신뢰 가능한 서버에서만 사용하세요.

## 기존 서버에 외부 HTTPS 도메인 적용

DNS/외부 HTTPS 연결은 이미 끝났다고 가정합니다. **서버 설정만 변경**하며 기존 계정·PostgreSQL 데이터·토큰은 유지합니다. 아래 예시는 `external` 모드입니다. 서버 Caddy가 HTTPS를 직접 처리하면 `public`으로 변경하세요.

1. 기존 환경설정을 백업하고 수정합니다.

```bash
ROOT=/opt/mcp-deployment
sudo cp -p "$ROOT/runtime/private.env" "$ROOT/runtime/private.env.bak"
sudoedit "$ROOT/runtime/private.env"
sudoedit "$ROOT/runtime/public.env"
```

| 파일 | 맞춰야 할 항목 |
|---|---|
| `runtime/private.env` | `PUBLIC_BASE_URL=https://mcp.example.com`, `CADDY_MODE=external`, `ENABLE_OAUTH=1` |
| `runtime/public.env` | `PUBLIC_BASE_URL=https://mcp.example.com`, `ENABLE_OAUTH=1` |

`POSTGRES_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `MCP_LOGIN_PASSWORD` 등 **기존 비밀번호와 토큰은 변경하지 마세요.**

2. Caddy 설정을 렌더링하고 Keycloak·OAuth에 적용합니다.

```bash
ROOT=/opt/mcp-deployment
sudo env MCP_INSTALL_ROOT="$ROOT" \
  PUBLIC_BASE_URL=https://mcp.example.com CADDY_MODE=external ENABLE_OAUTH=1 \
  python3 "$ROOT/scripts/render_config.py"
sudo docker compose --env-file "$ROOT/runtime/private.env" \
  -f "$ROOT/docker-compose.yml" --profile oauth up -d postgres keycloak
# Keycloak API 기동 전에는 잠시 실패할 수 있으며, 아래 스크립트는 재시도함
sudo python3 "$ROOT/scripts/provision_keycloak.py"
sudo systemctl enable --now mcpstack-oauth.service
sudo systemctl restart mcpstack-oauth.service
sudo docker compose --env-file "$ROOT/runtime/private.env" \
  -f "$ROOT/docker-compose.yml" restart caddy
sudo bash "$ROOT/status.sh"
```

기존 `runtime/access-urls.txt`에는 예전 공유 주소가 남을 수 있습니다. 갱신이 필요하면 `sudo bash "$ROOT/renew-share.sh" 7`을 실행하세요. **기존 공유 URL은 즉시 폐기**됩니다.

## ChatGPT 연결

| 서비스 | MCP 서버 URL | 공개 OAuth Client ID | Scope |
|---|---|---|---|
| PocMap | `https://mcp.example.com/pocmap/mcp` | `chatgpt-pocmap` | `mcp:pocmap` |
| HackBrowser | `https://mcp.example.com/hackbrowser/mcp` | `chatgpt-hackbrowser` | `mcp:hackbrowser` |
| ZAP | `https://mcp.example.com/zap/mcp` | `chatgpt-zap` | `mcp:zap` |

각각 사용자 지정 OAuth 클라이언트로 등록하고 PKCE S256을 사용합니다. **Client Secret은 비우고** 토큰 엔드포인트 인증 방식은 `none`으로 둡니다. 서버의 리디렉션 설정은 `https://chatgpt.com/connector_platform_oauth_redirect`를 사용합니다. 최초 로그인은 `MCP_LOGIN_USER` 또는 위에서 만든 추가 계정으로 합니다.

## 상태 확인

```bash
sudo bash /opt/mcp-deployment/status.sh
sudo python3 /opt/mcp-deployment/scripts/check_calls.py
curl -i http://127.0.0.1:8088/healthz
# OAuth 활성화 시 인증 없는 MCP 호출은 401이어야 정상
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8088/pocmap/mcp
```

기대 결과: `/healthz`는 **200**, 인증 없는 `/pocmap/mcp`는 **401**, MCP 도구 검색은 PocMap 22 / HackBrowser 8 / ZAP 17개입니다. `check_calls.py`는 세 백엔드의 실제 호출과 HackBrowser PNG 이미지 블록을 확인합니다.

## HackBrowser 스크린샷 미리보기 및 PNG 다운로드

`browser_screenshot`은 MCP `ImageContent`의 PNG 바이트와 크기·MIME 메타데이터를 반환합니다. `ui://hackbrowser/screenshot.html` MCP Apps 뷰어에서 바로 표시하며 채팅 너비에 맞게 축소하고 높이는 최대 440px로 제한합니다.

`PNG 다운로드` 버튼은 브라우저 iframe의 가상 클릭이 아닌 **MCP Apps 표준 `ui/download-file`** 호스트 요청으로 PNG를 저장합니다. 호스트가 다운로드 기능을 광고하지 않으면 ChatGPT에서 사용 가능한 `uploadFile`·`getFileDownloadUrl`·`openExternal` API로 대체 처리합니다. 다운로드 권한 또는 파일 API가 없는 환경에서는 실패 사유를 화면에 표시합니다. 실제 저장은 사용 중인 ChatGPT 클라이언트가 이 기능을 지원해야 합니다.

공개 `/captures/*` URL, 서버의 PNG 다운로드 핸들러, 별도 PNG 파일 저장은 제거했습니다. 외부에 스크린샷 주소를 발급하거나 만료 링크를 채팅에 삽입하지 않습니다. 기존 릴리스에서 생성된 파일은 자동 삭제하지 않습니다.

## 스크린샷 한글 폰트 깨짐(□) 해결

새 설치 시 `install.sh`가 `fonts-noto-cjk`·`fonts-nanum`·`fontconfig`를 설치하고 한국어 글꼴 인식을 검사합니다. 기존 서버는 **재설치하거나 계정을 초기화할 필요 없이** 다음 릴리스 배포 과정에서 `scripts/ensure_korean_fonts.sh`를 실행하고 `mcpstack-chromium.service`를 재시작하도록 수정했습니다.

서버에 직접 확인할 때는 `sudo bash /opt/mcp-deployment/scripts/ensure_korean_fonts.sh --check`를 실행합니다. `[PASS] Headless Chromium Korean fonts available`이면 운영 계정에서 한국어 폰트를 찾을 수 있다는 의미입니다. 이후 한국어가 포함된 웹페이지를 다시 캡처해 실제 렌더링을 확인하세요. 폰트가 잡혀도 웹사이트 자체의 CSS·문자 인코딩 문제는 별도로 점검해야 합니다.

## 문제 해결

| 현상 | 점검 |
|---|---|
| Keycloak `127.0.0.1:8081` 연결 거부 | `docker compose --profile oauth up -d postgres keycloak`로 구성 반영; Keycloak의 `oauth_uplink` 브리지 네트워크·호스트 루프백 게시 확인 |
| OAuth 경로 HTTP 401 | 로그인 전에는 정상. 로그인 후에도 지속되면 Keycloak `security-mcp` Realm, Client ID, 공개 URL, OAuth 발급 토큰 확인 |
| MCP 502 / 브라우저 미연결 | `status.sh`, `journalctl -u mcpstack-hackbrowser.service -n 50 --no-pager` 확인 |
| 외부 주소만 연결 실패 | 서버의 `8088` 접근 경로, HTTPS 프록시 헤더·캐시 및 도메인 해석을 확인 |
| 도구는 보이지만 실행 실패 | `scripts/check_calls.py`로 실제 `tools/call` 결과 확인 |

## 운영 명령과 주의사항

```bash
sudo cat /opt/mcp-deployment/runtime/access-urls.txt # 공유 URL은 비밀번호처럼 보호
sudo bash /opt/mcp-deployment/renew-share.sh 7   # 공유 토큰 교체(기존 URL 무효)
sudo bash /opt/mcp-deployment/uninstall.sh        # 서비스 중지, 설정/DB 보존
```

`private.env`, ZAP 키, 공유 URL을 Git에 올리지 마세요. **8081(Keycloak), 8282(ZAP), 9222(CDP)는 외부에 공개하면 안 됩니다.** 사용자 계정이 여러 개라도 HackBrowser 브라우저 세션과 ZAP 스캔 환경은 공유됩니다. 능동 진단은 승인된 대상에서만 수행하세요.
