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


## 운영자 설정: MCP 로그인 계정 및 외부 도메인 적용

외부 HTTPS 도메인과 DNS/프록시 연결은 이미 준비되어 있다고 가정합니다. 아래 내용은 **서버에서 해야 할 설정**만 다룹니다. 예시 `mcp.example.com`은 본인 도메인으로 변경하세요.

### 1. 로그인 ID·초기 비밀번호 발급 및 조회

새 서버에 **처음 설치할 때** `MCP_LOGIN_USER`로 로그인 ID를 지정할 수 있습니다(생략 시 `mcp-operator`). 초기 로그인 비밀번호와 Keycloak 관리자 비밀번호는 설치 스크립트가 자동 생성합니다. 이미 설치된 서버에서 설치 명령을 다시 실행해도 기존 계정·비밀번호는 초기화되지 않습니다.

```bash
# 외부 HTTPS 프록시/터널이 서버 앞에 있는 경우(HTTPS는 프록시에서 처리)
cd hackbrowser/MCP-Deployment
sudo PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=external ENABLE_OAUTH=1 \
  MCP_LOGIN_USER=mcp-operator SHARE_DAYS=7 bash install.sh
```

서버에서 발급된 정보를 확인합니다. **이 명령은 비밀번호를 터미널에 표시**하므로 화면 공유·로그 저장·GitHub 업로드 시 노출되지 않도록 주의하세요.

```bash
sudo grep -E '^(MCP_LOGIN_USER|MCP_LOGIN_PASSWORD|KEYCLOAK_ADMIN_PASSWORD)=' \
  /opt/mcp-deployment/runtime/private.env
```

| 항목 | 용도 |
|---|---|
| `MCP_LOGIN_USER` / `MCP_LOGIN_PASSWORD` | Keycloak의 MCP 로그인 계정 ID / 최초 임시 비밀번호 |
| Keycloak 관리자 ID `mcpadmin` / `KEYCLOAK_ADMIN_PASSWORD` | Keycloak 관리자 계정 (MCP 일반 로그인과 구분) |
| `chatgpt-pocmap`, `chatgpt-hackbrowser`, `chatgpt-zap` | ChatGPT에 입력하는 각 OAuth **Client ID**. 사용자 로그인 ID가 아니며 공개 클라이언트라 Client Secret은 비움 |

최초 로그인 시 임시 비밀번호를 변경해야 합니다. **변경 후 실제 비밀번호는 조회할 수 없으며**, `private.env`의 `MCP_LOGIN_PASSWORD`는 최초 발급값으로 남습니다. 기존 계정의 비밀번호를 바꿔야 한다면 Keycloak에서 **재설정**하세요. 이미 설치된 서버에서 `MCP_LOGIN_USER`나 비밀번호를 파일에서만 수정하는 것은 기존 Keycloak 사용자 정보를 변경하지 않습니다.

### 1-1. 추가 사용자 계정 생성

기존 `mcp-operator` 계정을 삭제하거나 설치를 다시 실행할 필요는 없습니다. **Keycloak의 `security-mcp` Realm에 로그인 사용자를 추가**합니다. OAuth가 활성화된 서버에서 진행하세요. 새로운 사용자마다 OAuth Client ID를 만들 필요는 없습니다.

1. 서버에서 Keycloak 관리자 비밀번호를 확인합니다. `mcpadmin`은 관리자 ID이며 **일반 MCP 로그인 ID가 아닙니다.** 비밀번호가 화면에 표시되므로 주변에 노출되지 않도록 주의하세요.

   ```bash
   sudo grep '^KEYCLOAK_ADMIN_PASSWORD=' /opt/mcp-deployment/runtime/private.env
   ```

2. Keycloak 컨테이너의 관리자 CLI를 사용합니다. 첫 번째 명령에서 관리자 비밀번호를 입력하라는 메시지가 나오면 위 비밀번호를 입력합니다.

   ```bash
   ROOT=/opt/mcp-deployment
   # 이후 명령에서 공통으로 사용할 Docker Compose 옵션
   DC="sudo docker compose --env-file $ROOT/runtime/private.env -f $ROOT/docker-compose.yml --profile oauth"
   $DC exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
     --server http://127.0.0.1:8080/auth --realm master --user mcpadmin
   ```

3. 사용자 ID를 정해 계정을 생성하고 임시 비밀번호를 지정합니다. 예시 `teamuser02`는 원하는 로그인 ID로 변경하세요.

   ```bash
   NEW_USER=teamuser02
   $DC exec keycloak /opt/keycloak/bin/kcadm.sh create users \
     -r security-mcp -s "username=$NEW_USER" -s enabled=true

   # 임시 비밀번호를 화면과 셸 기록에 노출하지 않고 입력
   read -r -s -p '추가 사용자 임시 비밀번호: ' NEW_PASS; echo
   $DC exec keycloak /opt/keycloak/bin/kcadm.sh set-password \
     -r security-mcp --username "$NEW_USER" \
     --new-password "$NEW_PASS" --temporary
   unset NEW_PASS
   ```

4. 계정 생성 여부를 확인합니다.

   ```bash
   $DC exec keycloak /opt/keycloak/bin/kcadm.sh get users \
     -r security-mcp -q "username=$NEW_USER"
   ```

추가된 사용자는 기존 MCP 접속 주소에서 새 ID·임시 비밀번호로 로그인하고, **첫 로그인 시 본인 비밀번호로 변경**합니다. 계정은 Keycloak 데이터베이스에 저장되며 `runtime/private.env`에 사용자별 비밀번호가 추가되지는 않습니다. 비밀번호 분실 시 관리자가 `set-password --temporary`로 새 임시 비밀번호를 발급할 수 있지만, **기존 비밀번호를 조회할 수는 없습니다.**

> **보안:** 이 구성의 추가 계정들은 동일한 HackBrowser 브라우저 세션과 ZAP 스캔 환경을 공유합니다. 계정 생성만으로 사용자별 브라우저/스캔 격리가 이루어지지 않으므로 신뢰할 수 있는 사용자에게만 발급하세요. `set-password`는 실행 중 프로세스 인자에 임시 비밀번호가 잠시 포함될 수 있으므로 다중 사용자 서버에서는 주의가 필요합니다.

### 2. 이미 설치된 서버에 외부 HTTPS 주소 적용

기존 데이터를 보존하려면 **재설치 대신 환경설정만 변경**합니다. HTTPS 프록시/터널이 외부 TLS를 처리하고 서버의 `8088` 포트로 전달하는 경우 `CADDY_MODE=external`입니다. 서버의 Caddy가 직접 80/443을 받아 HTTPS 인증서까지 처리할 때만 `CADDY_MODE=public`을 사용하세요.

```bash
ROOT=/opt/mcp-deployment
# 기존 비밀번호·토큰 보존을 위해 설정 백업
sudo cp -p "$ROOT/runtime/private.env" "$ROOT/runtime/private.env.bak"
sudoedit "$ROOT/runtime/private.env"
sudoedit "$ROOT/runtime/public.env"
```

파일에서 다음 값을 맞춥니다. 기존 `POSTGRES_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `MCP_LOGIN_PASSWORD` 등 **비밀값은 변경하지 마세요.**

| 설정 파일 | 값 |
|---|---|
| `runtime/private.env` | `PUBLIC_BASE_URL=https://mcp.example.com` / `CADDY_MODE=external` / `ENABLE_OAUTH=1` |
| `runtime/public.env` | `PUBLIC_BASE_URL=https://mcp.example.com` / `ENABLE_OAUTH=1` |

설정을 렌더링하고 Keycloak/OAuth 서비스에 적용합니다.

```bash
ROOT=/opt/mcp-deployment
sudo env MCP_INSTALL_ROOT="$ROOT" PUBLIC_BASE_URL=https://mcp.example.com \
  CADDY_MODE=external ENABLE_OAUTH=1 \
  python3 "$ROOT/scripts/render_config.py"

sudo docker compose --env-file "$ROOT/runtime/private.env" \
  -f "$ROOT/docker-compose.yml" --profile oauth up -d postgres keycloak

# Keycloak이 기동된 후 OAuth 클라이언트와 사용자 설정
until curl -fsS --max-time 5 \
  http://127.0.0.1:8081/auth/realms/master/.well-known/openid-configuration \
  >/dev/null; do sleep 3; done
sudo python3 "$ROOT/scripts/provision_keycloak.py"

sudo systemctl enable --now mcpstack-oauth.service
sudo systemctl restart mcpstack-oauth.service
sudo docker compose --env-file "$ROOT/runtime/private.env" \
  -f "$ROOT/docker-compose.yml" restart caddy
sudo bash "$ROOT/status.sh"
```

외부 도메인을 통한 MCP 주소는 아래와 같습니다. ChatGPT OAuth Client ID는 위 표를 사용하고, 최초 로그인은 `MCP_LOGIN_USER`로 진행합니다.

| MCP | ChatGPT에 등록할 서버 URL |
|---|---|
| PocMap | `https://mcp.example.com/pocmap/mcp` |
| HackBrowser | `https://mcp.example.com/hackbrowser/mcp` |
| ZAP | `https://mcp.example.com/zap/mcp` |

### 3. 서버 측 정상 동작 확인

```bash
# 로컬 게이트웨이 확인
curl -i http://127.0.0.1:8088/healthz
# 로그인 전 MCP 경로는 HTTP 401이 정상(OAuth 인증 요구)
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8088/pocmap/mcp
# 공개 도메인 경로 확인
curl -i https://mcp.example.com/healthz
sudo bash /opt/mcp-deployment/status.sh
```

`/healthz`는 `200`, 인증 없이 호출한 `/pocmap/mcp`는 `401`이 정상입니다. `status.sh`에서는 Keycloak HTTP 응답과 MCP 서비스별 도구 검색을 확인합니다. 외부 HTTPS 프록시는 `Authorization` 및 MCP 관련 헤더를 전달하고 캐시를 사용하지 않아야 합니다. **8081(Keycloak), 9222(CDP), 8282(ZAP) 등 내부 포트는 외부에 공개하지 말고, 8088도 신뢰한 프록시에서만 접근하도록 제한**하세요.

자세한 설치 구조와 기타 운영 제약은 [`MCP-Deployment/README.md`](./MCP-Deployment/README.md)를 참고합니다.

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
