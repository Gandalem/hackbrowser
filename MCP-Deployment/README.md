# MCP Deployment — 범용 Ubuntu/Debian 재설치 패키지

AWS EC2 전용이 아닌 **Ubuntu/Debian 시스템**에서 동일한 MCP 구성을 다시 배포하는 설치 패키지입니다. VMware/VirtualBox/KVM VM, OCI, NCP, AWS, VPS 및 일반 물리 서버에 사용할 수 있습니다. 컨테이너 내부(systemd 부재)나 Windows Server 설치는 지원하지 않습니다.

| 백엔드 | 설치 | 접속 | 인증 |
|---|---|---|---|
| PocMap | `pocmap[server]==2.9.1` (PyPI) | `127.0.0.1:9000/mcp` | 외부 게이트웨이 |
| HackBrowser MCP | 수집된 CDP 브리지 + 최신 Chromium | `127.0.0.1:8765/mcp` | 외부 게이트웨이 |
| OWASP ZAP MCP | ZAP Docker + `mcp` add-on | `127.0.0.1:8282/` | 별도 ZAP Security Key |
| 공유 게이트웨이 | Python aiohttp | `127.0.0.1:8790` | 7일 만료 비밀 URL |
| 선택적 OAuth | Keycloak + PostgreSQL + JWT gateway | `127.0.0.1:8787` | ChatGPT OAuth/PKCE |
| HTTPS | Caddy 2 Docker | `80/443` (public), `8088` (local/external) | HTTPS / 외부 프록시 |

## 필수 조건

- **Ubuntu/Debian x86_64** VM 또는 일반 서버와 `sudo` 권한, `systemd`, 인터넷 접속, 충분한 메모리(권장 8GB 이상), 저장공간(권장 15GB 이상). ARM64는 Chromium을 선행 설치해야 할 수 있습니다.
- **외부 AI/ChatGPT 연결:** 서버를 가리키는 DNS 도메인, 해당 VM/클라우드 방화벽에서 TCP 80/443 허용, 유효한 HTTPS 인증서 발급 조건. 인증서 발급은 Caddy가 자동으로 수행합니다.
- **로컬 VM 전용:** 도메인 없이 `http://127.0.0.1:8088` 사용 가능. 외부 AI 클라이언트에는 DNS·HTTPS 또는 SSH 터널이 필요합니다.
- 기존 VM에서 Caddy, ZAP, Keycloak 또는 80/443/8090/8282/8765/8787/8790/9000/9222 등의 포트를 사용 중이면 충돌할 수 있습니다. **새 VM에 설치 권장**.

## 설치

압축 해제 후 작업 폴더에서 실행합니다. 외부 HTTPS 도메인이 준비된 경우:

```bash
# Public mode: AWS, OCI, NCP, VMware, bare-metal 모두 동일
sudo PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=public ENABLE_OAUTH=1 SHARE_DAYS=7 \
  bash install.sh
```

로컬 VM 전용 설치(다른 PC의 원격 MCP는 HTTPS 추가 필요):

```bash
sudo PUBLIC_BASE_URL=http://127.0.0.1:8088 \
  CADDY_MODE=local ENABLE_OAUTH=0 SHARE_DAYS=7 \
  bash install.sh
```

CloudFront/로드밸런서/기존 HTTPS 프록시 뒤에 배치할 때는 `CADDY_MODE=external`을 선택합니다. 호스트 TCP 8088로 원본 프록시를 연결하고, 인증 헤더·MCP 헤더를 전달하며 캐시를 비활성화해야 합니다. **외부에서 8088로 직접 접근할 수 없도록 방화벽을 설정**하세요.

설치 프로그램은 Docker, Python 가상환경, 최신 Chromium, systemd 서비스를 준비합니다. 사용자의 기존 키·계정 정보는 포함하지 않으며 **새 공유 토큰과 ZAP 키, Keycloak 관리자 비밀번호를 생성**합니다. 설치를 반복 실행해도 생성된 비밀번호와 만료 시각을 바꾸지 않습니다.

## 접속 주소 확인

```bash
sudo cat /opt/mcp-deployment/runtime/access-urls.txt
```

표시된 `/share/{token}/{service}/mcp` 주소는 URL 자체가 비밀번호입니다. 로그인 없이 접속할 수 있으므로 신뢰하는 사용자에게만 전달하세요. 7일 만료 후 접속이 거부됩니다.

HTTPS+OAuth 모드에서는 추가로 `/pocmap/mcp`, `/hackbrowser/mcp`, `/zap/mcp`를 ChatGPT에 등록할 수 있습니다. 각각 `chatgpt-pocmap`, `chatgpt-hackbrowser`, `chatgpt-zap` 공개 Client ID / PKCE S256을 사용합니다. 최초 로그인 계정은 `mcp-operator`이며 임시 비밀번호는 `/opt/mcp-deployment/runtime/private.env`의 `MCP_LOGIN_PASSWORD`에 있습니다. 로그인 후 비밀번호를 변경하세요.

## HackBrowser 스크린샷 이미지 반환

`browser_screenshot`은 Chromium CDP로 PNG를 캡처한 뒤 두 개의 MCP 콘텐츠 블록을 반환합니다. 첫 번째는 서버의 비공개 저장 경로·파일 크기 등 텍스트 메타데이터이고, 두 번째는 ChatGPT 등 이미지 표시 지원 MCP 클라이언트가 직접 처리할 수 있는 `image/png` 이미지 블록입니다. PNG 사본은 기본적으로 실행 계정의 `~/hackbrowser-mcp-screenshots/`에 권한 `0600`으로 저장됩니다. 이미지는 서버 밖으로 별도 URL로 공개되지 않습니다. 유효하지 않은 PNG 또는 8 MiB 초과 이미지는 거부합니다.

릴리스 자동 배포에서는 기존 MCP 47개 도구 검색 및 3종 호출 검사에 더해 **실제 `browser_screenshot` 호출로 이미지 블록·PNG 서명·메타데이터를 확인**합니다. 이미지 콘텐츠를 표시하지 않는 클라이언트에서는 파일 정보만 보일 수 있습니다.

## 검증 및 관리

```bash
sudo bash /opt/mcp-deployment/status.sh
# 새 7일 공유 주소 발급 (이전 주소 즉시 폐기)
sudo bash /opt/mcp-deployment/renew-share.sh 7
# 서비스만 중지 (설정·DB는 유지)
sudo bash /opt/mcp-deployment/uninstall.sh
```

`status.sh`는 실제 MCP 도구 검색을 검사합니다. 예상 도구 수는 PocMap 22, HackBrowser 8, ZAP 17입니다. 실제 `tools/call` 기능 동작은 연결한 AI에서 추가 확인해야 합니다.

## 중요 제약

- **실제 새 Ubuntu/OCI/NCP VM에서의 전체 설치는 아직 검증되지 않았습니다.** 수집된 서버 설정을 바탕으로 재구성한 배포 스크립트입니다. 압축 내부 소스의 문법·정적 검증을 수행했더라도 Docker 이미지·Chrome·외부 DNS/방화벽 연동은 실제 설치 테스트가 필요합니다.
- 원본에서 **PocMap 소스와 Caddyfile 원본은 수집되지 않았습니다.** PocMap은 공식 PyPI 버전으로 설치하고 Caddy는 플랫폼 중립으로 새로 생성합니다. 원본 Keycloak 사용자 DB, TLS 개인키, AWS CloudFront 구성은 복제하지 않습니다.
- 실제 서버의 **PocMap `verify_github_pocs` 기능은 비활성화**되어 있었습니다. 새 설치에서도 옵션이 바뀌지 않는 한 활성화를 보장하지 않습니다.
- ZAP과 HackBrowser는 여러 사용자가 **같은 스캔/브라우저 세션을 공유**합니다. 원격 공유 URL 유출은 상당한 위험이므로 등록 대상 및 서버 방화벽을 통제하세요. ZAP의 내부 `8282`나 CDP `9222` 포트는 절대 공개하지 마세요.
- 타사 소스·Docker 이미지 및 상업적 재배포 라이선스는 판매 전에 별도 확인이 필요합니다. 자세한 출처와 차이는 `docs/PROVENANCE.md`를 확인하세요.
