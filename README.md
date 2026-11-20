<div align="center">
  <img src="./assets/mcp-deployment-banner.svg" alt="MCP Deployment" width="100%" />
</div>

# MCP Deployment

Ubuntu/Debian 서버에 **PocMap · HackBrowser · OWASP ZAP** MCP를 설치하고 ChatGPT와 연결하는 통합 패키지입니다. Docker·systemd 기반이며 OCI, AWS, NCP, 일반 VM/VPS에서 사용할 수 있습니다.

| MCP | 주요 기능 | 도구 수 |
|---|---|---:|
| **PocMap** | CVE·PoC·취약점 정보 조회 | 22 |
| **HackBrowser** | Chromium 브라우저 AI 제어·화면 캡처 | 11 |
| **OWASP ZAP** | 웹 보안 점검·HTTP 기록·보고서 | 17 |

[50개 도구 전체 보기](docs/TOOLS.md)

## 빠른 설치

**필수:** Ubuntu/Debian + systemd, `sudo`, 인터넷, 권장 RAM 8GB/디스크 15GB. 외부 ChatGPT 연동에는 HTTPS 주소가 필요합니다.

```bash
git clone https://github.com/Gandalem/hackbrowser.git
cd hackbrowser/MCP-Deployment
```

다음 중 환경에 맞는 **한 가지**를 실행합니다.

**① 로컬 전용 (도메인 없음)**

```bash
sudo PUBLIC_BASE_URL=http://127.0.0.1:8088 \
  CADDY_MODE=local ENABLE_OAUTH=0 SHARE_DAYS=7 bash install.sh
```

**② 외부 HTTPS 주소가 이미 연결된 서버 (프록시/터널 사용)**

```bash
sudo PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=external ENABLE_OAUTH=1 SHARE_DAYS=7 bash install.sh
```

**③ 서버 Caddy가 HTTPS를 직접 처리하는 경우 (80/443 사용)**

```bash
sudo PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=public ENABLE_OAUTH=1 SHARE_DAYS=7 bash install.sh
```

`mcp.example.com`은 실제 도메인으로 변경하세요. 이미 설치된 서버의 도메인을 변경하려면 **재설치하지 말고** [서버 운영 가이드](MCP-Deployment/README.md#기존-서버에-외부-https-도메인-적용)를 사용하세요.

## 연결 및 확인

```bash
sudo bash /opt/mcp-deployment/status.sh
sudo cat /opt/mcp-deployment/runtime/access-urls.txt
```

HTTPS + OAuth 설치 시 ChatGPT에 등록할 주소:

| 서비스 | MCP 서버 URL | OAuth Client ID |
|---|---|---|
| PocMap | `https://mcp.example.com/pocmap/mcp` | `chatgpt-pocmap` |
| HackBrowser | `https://mcp.example.com/hackbrowser/mcp` | `chatgpt-hackbrowser` |
| ZAP | `https://mcp.example.com/zap/mcp` | `chatgpt-zap` |

OAuth 공개 클라이언트로 **Client Secret 없이 PKCE S256**을 사용합니다. 로그인 계정은 기본 `mcp-operator`; 최초 비밀번호는 서버의 `runtime/private.env`에 생성됩니다.

> `access-urls.txt`의 공유 URL은 비밀번호와 동일하게 보호하세요. GUI CDP 9223, ZAP 8282, Keycloak 8081 등 내부 포트를 공개하지 마세요.

## 사용·운영 문서

- **[서버 운영 가이드](MCP-Deployment/README.md)** — 로그인 ID/초기 비밀번호 조회, 추가 사용자 생성, 외부 도메인 서버 설정, 상태 확인, 문제 해결
- **[MCP 도구 목록](docs/TOOLS.md)** — 50개 도구별 기능·입력값
- **[릴리스 및 OCI 자동 배포](docs/RELEASE.md)** — Git 태그, CI/CD, 배포 설정·검증
- **[소스 출처·제약](MCP-Deployment/docs/PROVENANCE.md)** — 원본/재구성 범위 및 제한 사항

**검증 범위:** 정적 테스트와 일부 운영 환경 검증이 수행되었으나, 새 VM에서 모든 클라우드 조합의 최초 설치가 검증된 것은 아닙니다.
