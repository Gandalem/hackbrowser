# MCP 도구 레퍼런스 (PocMap 22 · HackBrowser 22 · ZAP 17)

[프로젝트 설치](../README.md) · [운영 및 계정 관리](../MCP-Deployment/README.md)

아래 목록은 각 MCP 백엔드가 제공하는 도구의 역할과 입력값 요약입니다. 도구 검색에 표시되는 것과 실제 호출 성공은 다르므로 설치 후 `status.sh` 및 `scripts/check_calls.py` 결과를 별도로 확인합니다.

## MCP 및 도구

| MCP | 기능 | 도구 |
|---|---|---:|
| **PocMap** | CVE·PoC·취약점 정보 조회 | 22개 |
| **HackBrowser MCP** | Chromium 브라우저 제어 | 20개 |
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
<summary><b>HackBrowser MCP — AI GUI Chromium 도구 22개</b></summary>

| 도구 | 기능 | 주요 입력값 |
|---|---|---|
| `browser_status` | GUI Chromium CDP 연결 상태 | 없음 |
| `browser_tabs` | 열린 탭 및 ID 조회 | 없음 |
| `browser_close_tabs` | 지정한 탭 종료 (빈 탭 유지 가능) | `target_ids`, `keep_one_blank` |
| `browser_navigate` | URL 이동 | `url`, `target_id` |
| **`browser_observe`** | 현재 페이지의 제목·텍스트·짧은 요소 참조 반환 | `target_id`, `max_elements` |
| **`browser_act`** | 최신 스냅샷에서 안전한 링크 클릭/검색 입력/GET 검색 제출 | `snapshot_id`, `ref`, `action`, `text`, `target_id` |
| `browser_page_text` | 페이지 표시 텍스트 조회 | `target_id`, `max_chars` |
| `browser_elements` | 기존 CSS 선택자 기반 링크·컨트롤 조회 | `target_id`, `max_items` |
| `browser_click` | CSS로 요소 클릭 | `selector`, `target_id` |
| `browser_click_text` | 역할과 표시 텍스트로 클릭 | `text`, `role`, `exact`, `container_selector`, `target_id` |
| `browser_fill` | CSS로 입력창 수정 | `selector`, `value`, `target_id` |
| `browser_fill_and_submit` | 입력 후 Enter | `selector`, `value`, `target_id` |
| `browser_click_at` | GUI 화면 좌표 클릭 | `x`, `y`, `target_id` |
| `browser_keypress` | 키 입력 | `key`, `target_id` |
| `browser_scroll` | 스크롤 | `direction`, `pixels`, `target_id` |
| `browser_wait_for` | 요소·텍스트·로딩 대기 | `selector`, `text`, `timeout_seconds`, `target_id` |
| `browser_screenshot` | PNG 이미지와 수동 인증 UI | `target_id` |
| `browser_verification_click` | 사용자가 고른 인증 위치 클릭 | `verification_id`, `x`, `y` |
| `browser_submit_verification` | 사용자 직접 입력 CAPTCHA 전달 | `verification_id`, `answer` 및 좌표 |
| `browser_workflow_start` | 안전한 탐색 작업 묶음 실행 | `steps`, `target_id` |
| `browser_workflow_status` | 작업 상태·다음 단계 | `workflow_id` |
| `browser_workflow_resume` | 사용자 인증 후 다음 단계에서 재개 | `workflow_id` |

**AI 사용 권장:** `browser_observe` → `browser_act` → `browser_observe` 또는 `browser_wait_for`로 실제 결과 검증. 최신 참조는 90초 후 만료되고 페이지가 바뀌면 무효화됩니다. 안전한 탐색 외 작업은 별도 명시적 사용자가 제어하는 도구에서만 진행해야 합니다. 민감한 작업을 임의로 우회하지 마세요.

**보안 주의:** 스크린샷과 페이지 텍스트에는 개인 정보가 표시될 수 있습니다. 사용자별 Chromium 프로필은 아직 분리되어 있지 않습니다. 단독 Docker 경로는 OAuth 없이 로컬 접속만 허용합니다.

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

## 실제 호출 확인

```bash
sudo bash /opt/mcp-deployment/status.sh
sudo python3 /opt/mcp-deployment/scripts/check_calls.py
```

스크린샷은 HackBrowser의 `browser_screenshot`이 서버에 PNG를 저장하지 않고 MCP `image/png` 블록을 반환합니다. 클라이언트가 이미지 콘텐츠 렌더링을 지원하지 않으면 채팅에서 그림이 보이지 않을 수 있습니다. ZAP 능동 스캔은 허가된 대상에서만 수행하세요.

- \`browser_verification_click\`: 사용자가 스크린샷에서 직접 선택한 CAPTCHA 위치를 GUI Chromium에 1회 전달합니다. 자동 풀이 또는 우회는 지원하지 않습니다.\n
### GUI Chromium Playwright operations

- `browser_click_text(text, role, exact, target_id)`: find a human-readable button/link/tab/text, click once, detect new tabs
- `browser_fill_and_submit(selector, value, key, target_id)`: fill then press Enter once and verify change
- `browser_click_at(x, y, target_id)`: click GUI viewport coordinates once for ordinary interactions, not CAPTCHA solving
- `browser_click` and `browser_fill` use Playwright's actionability checks, reporting observed URL/content changes and newly opened tabs. CDP 9223 is reused; no profile reinitialization.

### 안전한 GUI 워크플로 (HackBrowser)

- `browser_workflow_start(steps, target_id)`: 공개 HTTPS 탐색, GET 검색, 안전한 링크 클릭, 대기, 스크롤을 최대 8단계 계획으로 묶습니다 (호출당 최대 3단계)
- `browser_workflow_status(workflow_id)`: 현재 단계 및 중단 사유 확인
- `browser_workflow_resume(workflow_id)`: 사용자 수동 인증 후 페이지 검증 및 다음 안전한 단계부터 재개
- 결제·삭제·로그인 정보 입력·CAPTCHA 자동 해결은 실행하지 않음


- `browser_close_tabs(target_ids, keep_one_blank=true)`: 지정한 GUI 페이지 탭을 닫으며, 전체 종료 시 빈 탭 하나로 Chromium을 유지
