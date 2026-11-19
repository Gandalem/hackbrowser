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
<summary><b>PocMap — CVE·PoC·위협 정보 도구 22개</b></summary>

| 도구 | 기능 | 주요 입력·참고 |
|---|---|---|
| `lookup_cve` | CVE 설명, CVSS·CWE, 영향 제품, EPSS·KEV 및 참고 자료를 조회 | CVE ID |
| `cve_to_cpe` | CVE에 연결된 영향 제품·버전의 CPE 식별자를 확인 | CVE ID |
| `cpe_to_cve` | CPE로 식별한 제품에 알려진 CVE 목록을 검색 | CPE 2.3 식별자 |
| `discover_product_cves` | 제품명·버전으로 취약점을 탐색하고 영향 여부의 일치 수준을 구분 | 제품명, 버전(선택), 제조사(선택) |
| `discover_package_cves` | 라이브러리·패키지 버전의 취약점과 수정된 버전을 OSV 기반으로 조회 | 패키지 생태계·이름, 버전(가능하면 지정) |
| `get_epss_score` | 향후 30일 내 실제 악용 가능성을 추정하는 EPSS 점수를 조회 | CVE ID |
| `check_kev_status` | CISA KEV(실제 악용 확인 취약점) 등재 여부를 조회 | CVE ID |
| `get_attack_techniques` | 해당 CVE와 연결된 MITRE ATT&CK 공격 기법 및 영향 매핑을 확인 | CVE ID; 매핑 없을 수 있음 |
| `find_github_pocs` | CVE 관련 GitHub PoC 저장소, 출처, 최근 활동과 신뢰도 정보를 검색 | CVE ID, 결과 제한(선택) |
| `verify_github_pocs` | GitHub PoC 저장소의 소스·파일을 확인해 코드 존재와 CVE 관련성을 평가 | CVE ID; 기본 비활성화(별도 명시적 활성화 필요) |
| `find_metasploit_module` | CVE에 해당하는 Metasploit 스캐너·익스플로잇 모듈을 찾음 | CVE ID |
| `find_exploitdb_entry` | ExploitDB의 관련 공개 익스플로잇·PoC 항목을 조회 | CVE ID |
| `find_nuclei_template` | CVE 진단에 이용할 수 있는 Nuclei YAML 템플릿을 검색 | CVE ID |
| `find_vulhub_docker` | Vulhub의 취약 환경 Docker 실습 자료와 경로를 찾음 | CVE ID |
| `find_practice_labs` | Vulhub·Hack The Box 등 실습 환경과 문제 자료를 검색 | CVE ID |
| `find_bug_bounty_reports` | 공개 버그바운티 분석·제보 사례와 기술 보고서를 검색 | CVE ID |
| `find_recent_exploits` | 최근 공개된 취약점 및 PoC·악용 위험 지표를 조건별로 탐색 | 기간·심각도·EPSS 등 필터(선택) |
| `get_cve_assessment_playbook` | CVE 조사부터 위험 우선순위·조치 방안까지 단계별 평가 절차 제공 | 입력 없이 호출 |
| `get_rapid_response_playbook` | 긴급 취약점의 탐지·차단·패치·의사소통 대응 절차 제공 | 입력 없이 호출 |
| `get_bug_bounty_playbook` | 버그바운티 조사·검증·재현 증적·보고서 제출 절차 제공 | 입력 없이 호출 |
| `generate_json_report` | 하나 이상의 CVE에 대한 종합 분석 결과를 구조화된 JSON으로 생성 | CVE ID 하나 이상(쉼표 구분) |
| `generate_html_report` | 하나 이상의 CVE에 대한 종합 분석을 HTML 보고서로 생성 | CVE ID 하나 이상(쉼표 구분) |

- **유의:** `verify_github_pocs`는 기본 설정에서 사용이 차단되어 있으며 외부 PoC 소스 다운로드를 허용하는 별도 옵션이 필요합니다. 검색된 PoC가 곧 검증된 작동 코드라는 의미는 아닙니다.
- **데이터 해석:** 외부 데이터 소스가 실패하거나 정보가 부족한 경우, 결과가 비어 있다는 이유만으로 ‘취약점 없음’ 또는 ‘악용되지 않음’이라고 판단하지 않습니다.

</details>

<details>
<summary><b>HackBrowser MCP — Chromium 브라우저 제어 도구 8개</b></summary>

| 도구 | 기능 | 주요 입력·참고 |
|---|---|---|
| `browser_status` | 로컬 Chrome DevTools Protocol(CDP) 연결 및 탭 수 확인 | 입력 없이 호출 |
| `browser_tabs` | 열린 탭·웹뷰의 제목, URL, `target_id` 목록 조회 | 입력 없이 호출 |
| `browser_navigate` | 대상 탭을 지정한 HTTP(S) URL로 이동 | `url`, `target_id`(선택) |
| `browser_page_text` | 열린 페이지의 제목·URL·표시 텍스트 추출 | `target_id`(선택), `max_chars`(최대 30,000) |
| `browser_elements` | 페이지의 링크와 입력창·버튼 요소 정보를 수집 | `target_id`(선택), `max_items`(최대 100) |
| `browser_click` | CSS 선택자로 찾은 페이지 요소를 클릭 | `selector`, `target_id`(선택) |
| `browser_fill` | CSS 선택자로 입력창에 값을 지정하고 `input`/`change` 이벤트 발생 | `selector`, `value`, `target_id`(선택) |
| `browser_screenshot` | 브라우저 화면을 PNG로 캡처하고 MCP 클라이언트에 이미지(`image/png`)를 직접 반환하며, 서버에도 비공개 PNG로 저장 | `target_id`(선택); 이미지 콘텐츠와 저장 경로·바이트 수 동시 반환 |

- **탭 지정:** 기본 탭 대신 특정 화면을 다루려면 `browser_tabs`로 `target_id`를 확인한 뒤 전달합니다.
- **화면 캡처:** `browser_screenshot`은 MCP의 **텍스트 메타데이터 + `image/png` 이미지 콘텐츠**를 반환하고, 서버에도 접근 권한 `0600`의 PNG를 저장합니다. 클라이언트가 이미지 콘텐츠 표시를 지원해야 실제 채팅에서 이미지가 보입니다. 8 MiB를 초과하거나 PNG가 아닌 응답은 거부합니다.

</details>

<details>
<summary><b>OWASP ZAP MCP — 웹 진단 도구 17개</b></summary>

| 도구 | 기능 | 주요 입력·참고 |
|---|---|---|
| `zap_info` | ZAP 실행 환경의 기본 정보 확인 | 입력 없이 호출 |
| `zap_version` | 실행 중인 OWASP ZAP 버전 조회 | 입력 없이 호출 |
| `zap_create_context` | 검사 범위를 URL·정규식으로 정의하는 Context 생성 | `name`, `url`, 포함/제외 정규식(선택) |
| `zap_start_spider` | 링크와 URL을 따라 탐색하는 전통적인 Spider 시작 | 대상 URL 또는 Context 이름 |
| `zap_get_spider_status` | Spider 진행 상태와 완료 여부 조회 | 시작 시 반환한 `scan_id` |
| `zap_stop_spider` | 진행 중인 Spider 중지 | `scan_id` |
| `zap_start_ajax_spider` | JavaScript 기반 동적 사이트 탐색용 AJAX Spider 시작 | 대상 URL 또는 Context 이름 |
| `zap_get_ajax_spider_status` | AJAX Spider 진행 상태 조회 | `scan_id`; 0/50/100 단계형 진행률 |
| `zap_stop_ajax_spider` | 진행 중인 AJAX Spider 중지 | `scan_id` |
| `zap_start_active_scan` | 정의한 대상에 능동 취약점 진단 요청 실행 | 대상 URL 또는 Context, `policy`(선택) |
| `zap_get_active_scan_status` | 능동 스캔 진행률·상태 조회 | `scan_id` |
| `zap_stop_active_scan` | 진행 중인 능동 스캔 중지 | `scan_id` |
| `zap_get_passive_scan_status` | 수집된 트래픽에 대한 패시브 스캔 대기 건수 확인 | 입력 없이 호출 |
| `zap_get_history` | ZAP HTTP 히스토리의 요청·응답 헤더 및 본문 일부 조회 | 히스토리 `id`, 조회 필드·본문 범위(선택) |
| `zap_list_resources` | 경보·히스토리·보고서 템플릿 등 접근 가능한 리소스 URI 열거 | 입력 없이 호출 |
| `zap_read_resource` | 리소스 URI를 지정해 관련 정보 조회 | `uri` |
| `zap_generate_report` | ZAP 보고서 템플릿을 사용하여 결과 파일 생성 | `file_path`, `template`, `title`(선택) |

- **스캔 순서:** 보통 `zap_create_context` → `zap_start_spider`/`zap_start_ajax_spider` → 상태 확인 → `zap_start_active_scan` → `zap_generate_report` 순서로 사용합니다.
- **주의:** 능동 스캔은 실제 HTTP 요청을 전송하고 서비스 상태에 영향을 줄 수 있으므로 **허가받은 대상**에만 수행하세요. 생성한 보고서도 ZAP이 실행되는 서버의 파일 경로에 저장됩니다.

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

`master`의 일반 커밋은 **CI 검증만** 합니다. 실제 릴리스/OCI 배포는 `vMAJOR.MINOR.PATCH` 형식의 **새 태그를 푸시할 때만** 실행됩니다.

```bash
git checkout master
git pull --ff-only origin master
git tag -a v1.0.1 -m "MCP Deployment v1.0.1"
git push origin v1.0.1
```

또는 GitHub의 **Releases → Draft a new release**에서 **새 태그**를 생성하면 태그 푸시 이벤트로 자동화가 시작됩니다. 기존 태그의 Release를 게시하거나 수정하는 동작만으로는 배포가 다시 실행되지 않습니다. 동일 버전 재시도 시에는 서버의 배포 기록과 상태를 확인합니다.

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
