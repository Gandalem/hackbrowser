<div align="center">
  <img src="./assets/mcp-deployment-banner.svg" alt="MCP Deployment" width="100%" />
</div>

# MCP Deployment

PocMap · HackBrowser MCP · OWASP ZAP MCP 통합 설치 패키지 (Ubuntu/Debian)

## MCP 및 도구

| MCP | 기능 | 도구 |
|---|---|---:|
| **PocMap** | CVE·PoC·취약점 정보 조회 | 22개 |
| **HackBrowser MCP** | Chromium 브라우저 제어 | 8개 |
| **OWASP ZAP MCP** | 웹 진단·스캔·HTTP 이력·보고서 | 17개 |

<details>
<summary><b>PocMap — 도구 22개</b></summary>

`lookup_cve`, `cve_to_cpe`, `cpe_to_cve`, `discover_product_cves`, `discover_package_cves`, `get_epss_score`, `check_kev_status`, `get_attack_techniques`, `find_github_pocs`, `verify_github_pocs`, `find_metasploit_module`, `find_exploitdb_entry`, `find_nuclei_template`, `find_vulhub_docker`, `find_practice_labs`, `find_bug_bounty_reports`, `find_recent_exploits`, `get_cve_assessment_playbook`, `get_rapid_response_playbook`, `get_bug_bounty_playbook`, `generate_json_report`, `generate_html_report`

</details>

<details>
<summary><b>HackBrowser MCP — 도구 8개</b></summary>

| 도구 | 기능 |
|---|---|
| `browser_status` | 브라우저 상태 |
| `browser_tabs` | 탭 목록 |
| `browser_navigate` | 페이지 이동 |
| `browser_page_text` | 페이지 텍스트 |
| `browser_elements` | 페이지 요소 |
| `browser_click` | 요소 클릭 |
| `browser_fill` | 입력 |
| `browser_screenshot` | 화면 캡처 |

</details>

<details>
<summary><b>OWASP ZAP MCP — 도구 17개</b></summary>

`zap_info`, `zap_version`, `zap_create_context`, `zap_start_spider`, `zap_get_spider_status`, `zap_stop_spider`, `zap_start_ajax_spider`, `zap_get_ajax_spider_status`, `zap_stop_ajax_spider`, `zap_start_active_scan`, `zap_get_active_scan_status`, `zap_stop_active_scan`, `zap_get_passive_scan_status`, `zap_get_history`, `zap_list_resources`, `zap_read_resource`, `zap_generate_report`

</details>

## 설치 명령어

```bash
git clone https://github.com/Gandalem/hackbrowser.git
cd hackbrowser/MCP-Deployment
```

### 로컬 설치

```bash
sudo PUBLIC_BASE_URL=http://127.0.0.1:8088 \
  CADDY_MODE=local ENABLE_OAUTH=0 SHARE_DAYS=7 \
  bash install.sh
```

### HTTPS + OAuth 설치

`mcp.example.com`을 실제 도메인으로 변경합니다.

```bash
sudo PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=public ENABLE_OAUTH=1 SHARE_DAYS=7 \
  bash install.sh
```

### 상태 확인

```bash
sudo bash /opt/mcp-deployment/status.sh
```

### 중지

```bash
sudo bash /opt/mcp-deployment/uninstall.sh
```

> 설치 스크립트는 systemd 기반 Ubuntu/Debian 호스트에서 실행합니다. 외부 MCP 접속에는 HTTPS·인증이 필요하며, 내부 CDP 포트(9222)를 공개하지 마세요.


## 버전 태그 기반 자동 Release / OCI 업데이트

`master`의 일반 커밋은 **CI 검증만** 합니다. 실제 릴리스/OCI 배포는 `vMAJOR.MINOR.PATCH` 태그를 생성하거나 해당 태그로 GitHub Release를 게시할 때 실행됩니다.

```bash
git checkout master
git pull --ff-only origin master
git tag -a v1.0.0 -m "MCP Deployment v1.0.0"
git push origin v1.0.0
```

또는 GitHub의 **Releases → Draft a new release**에서 `v1.0.0` 태그를 선택/생성하고 **Publish release**를 누릅니다. 같은 태그의 이벤트가 중복 발생해도 서버에서 기록된 커밋/버전을 확인해 동일한 정상 배포를 반복하지 않습니다.

자동화 작업: [MCP tagged release and OCI deployment](https://github.com/Gandalem/hackbrowser/actions/workflows/mcp-release.yml)

| 작업 | 결과 |
|---|---|
| CI | ARM64 테스트 및 셸/파이썬 문법 검사 |
| Package | `mcp-deployment-v1.0.0.tar.gz` + SHA-256 체크섬 생성 |
| GitHub Release | 버전별 압축파일과 체크섬 자동 첨부 |
| OCI CD | SSH 복사 → 체크섬 검증 → 코드 반영 → 서비스 재시작 |
| 검증 및 증적 | MCP 47개 도구 검색, 서비스별 실제 도구 호출, CI/CD 로그·PNG 증적 |

**최초 설치:** OCI에는 `MCP-Deployment/install.sh`로 MCP 스택이 먼저 설치되어 있어야 합니다. 자동 CD는 기존 서비스의 소스 코드를 업데이트하며, 기존 `runtime/`의 토큰/키/DB 데이터는 보존합니다. Python 의존성 변경은 자동 배포를 중단하고 설치 단계에서 별도 검토하도록 했습니다.

**GitHub 설정:** Actions의 Repository variable `OCI_DEPLOY_ENABLED=true`, Repository secrets `OCI_SSH_HOST`, `OCI_SSH_USER`, `OCI_SSH_PRIVATE_KEY`, `OCI_SSH_KNOWN_HOSTS`가 필요합니다. 배포 전용 키와 보호된 릴리스 태그 사용을 권장합니다.

**발표용 증적:** 각 Release workflow 실행의 Artifacts에서 `tagged-ci-evidence`와 `tagged-oci-deploy-evidence` ZIP을 다운로드합니다. 태그/릴리스 생성만으로 이미지 배포용 GHCR 컨테이너를 만드는 방식은 아닙니다. 다운로드 파일은 Ubuntu/Debian 설치용 소스 압축파일입니다.
