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
