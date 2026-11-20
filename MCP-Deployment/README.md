# MCP Deployment — 서버 운영 가이드

[빠른 설치](../README.md) · [50개 도구](../docs/TOOLS.md) · [릴리스/OCI 배포](../docs/RELEASE.md) · [구성 출처](docs/PROVENANCE.md)

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

기대 결과: `/healthz`는 **200**, 인증 없는 `/pocmap/mcp`는 **401**, MCP 도구 검색은 PocMap 22 / HackBrowser 22 / ZAP 17개입니다. `check_calls.py`는 세 백엔드의 실제 호출과 HackBrowser PNG 이미지 블록을 확인합니다.

## HackBrowser 스크린샷 미리보기 및 PNG 다운로드

`browser_screenshot`은 MCP `ImageContent`의 PNG 바이트와 크기·MIME 메타데이터를 반환합니다. `ui://hackbrowser/screenshot.html` MCP Apps 뷰어에서 바로 표시하며 채팅 너비에 맞게 축소하고 높이는 최대 440px로 제한합니다.

`PNG 다운로드` 버튼은 브라우저 iframe의 가상 클릭이 아닌 **MCP Apps 표준 `ui/download-file`** 호스트 요청으로 PNG를 저장합니다. 호스트가 다운로드 기능을 광고하지 않으면 ChatGPT에서 사용 가능한 `uploadFile`·`getFileDownloadUrl`·`openExternal` API로 대체 처리합니다. 다운로드 권한 또는 파일 API가 없는 환경에서는 실패 사유를 화면에 표시합니다. 실제 저장은 사용 중인 ChatGPT 클라이언트가 이 기능을 지원해야 합니다.

공개 `/captures/*` URL, 서버의 PNG 다운로드 핸들러, 별도 PNG 파일 저장은 제거했습니다. 외부에 스크린샷 주소를 발급하거나 만료 링크를 채팅에 삽입하지 않습니다. 기존 릴리스에서 생성된 파일은 자동 삭제하지 않습니다.

## 스크린샷 한글 폰트 깨짐(□) 해결

새 설치 시 `install.sh`가 `fonts-noto-cjk`·`fonts-nanum`·`fontconfig`를 설치하고 한국어 글꼴 인식을 검사합니다. 기존 서버는 **재설치하거나 계정을 초기화할 필요 없이** 다음 릴리스 배포 과정에서 `scripts/ensure_korean_fonts.sh`를 실행하고 `mcpstack-gui-chromium.service`를 재시작하도록 수정했습니다.

서버에 직접 확인할 때는 `sudo bash /opt/mcp-deployment/scripts/ensure_korean_fonts.sh --check`를 실행합니다. `[PASS] GUI Chromium Korean fonts available`이면 운영 계정에서 한국어 폰트를 찾을 수 있다는 의미입니다. 이후 한국어가 포함된 웹페이지를 다시 캡처해 실제 렌더링을 확인하세요. 폰트가 잡혀도 웹사이트 자체의 CSS·문자 인코딩 문제는 별도로 점검해야 합니다.

## 빠른 화면 조작과 중복 텍스트 해결

`browser_click_text`의 `container_selector`는 선택적 CSS 범위로, 같은 이름의 링크/버튼이 반복되는 화면에서도 원하는 영역을 명시하도록 돕습니다. 범위에 일치하는 컨테이너가 정확히 하나가 아니거나 해당 영역에 같은 이름이 여러 개라면 임의의 항목을 선택하지 않고 오류를 반환합니다. `browser_elements`로 CSS 위치를 확인한 뒤 범위를 지정하세요. 스크롤 및 Enter 외 방향키는 기존 접근 제한을 존중하면서 페이지 이동용 4초 대기를 사용하지 않습니다.

## 안전한 복합 작업 실행 및 인증 후 재개

`browser_workflow_start(steps, target_id)`는 기존 GUI Chromium 탭에서 최대 8단계의 안전한 탐색 계획을 처리합니다. 한 번 호출할 때 최대 3단계 실행하며, `browser_workflow_status(workflow_id)`로 진행 상태를 조회하고 `browser_workflow_resume(workflow_id)`로 다음 단계부터 이어갑니다. 작업 ID와 단계는 메모리에서 30분 뒤 만료되며 서버 재시작 시 사라집니다.

허용 작업: `navigate`(공개 HTTPS), `search`(암호 필드 없는 GET 검색 폼), `click_link`(안전한 공개 링크), `wait`, `scroll`만 가능합니다. 비밀번호 입력, 결제, 삭제, 계정 변경, 파일 업로드, CAPTCHA 자동 해결, 임의 JavaScript는 제외됩니다. CAPTCHA 또는 로그인 화면에서는 일시 중단하고 사용자 직접 인증 뒤 현재 화면을 다시 검사합니다. 작업 결과가 불확실하거나 사이트 접근이 제한되면 반복 클릭 없이 중단합니다.

예시: `[{"op":"navigate","url":"https://ko.wikipedia.org/wiki/위키백과:대문"},{"op":"search","selector":"#searchInput","text":"건담"},{"op":"wait","text":"건담"},{"op":"scroll","direction":"down","pixels":400}]`

현재 브라우저 세션은 서버 사용자 간 공유되므로 다중 사용자 격리 운영용으로 사용하지 마세요.

## GUI 탭 정리

`browser_close_tabs(target_ids, keep_one_blank=true)`는 `browser_tabs()`가 반환한 정확한 탭 ID만 닫습니다. 전부 닫을 때는 빈 `about:blank` 탭을 하나 새로 만들어 Chromium GUI와 CDP 9223을 유지합니다. 브라우저 프로필, 로그인 쿠키, 저장된 계정은 삭제하지 않습니다. 실패한 종료는 현재 탭 목록을 다시 조회해 확인합니다.

## AI용 Observe → Act (공개 베타)

`browser_observe(target_id, max_elements=35)`는 현재 GUI 탭에서 보이는 링크·버튼·입력 컨트롤을 `e1`, `e2` 같은 단기 참조로 반환합니다. 긴 CSS 선택자를 추측할 필요가 없습니다. 응답에는 `snapshot_id`, 제목, 짧은 본문, 요소의 역할·이름이 포함되며 입력칸 값은 수집하지 않습니다.

`browser_act(snapshot_id, ref, action, text?, target_id?)`는 90초 이내의 최신 참조에 대해서만 실행합니다. 지원 동작은 `click`(안전한 공개 링크·인식된 탐색 버튼), `fill`(검색어 입력), `search`(GET 검색 폼)입니다. 페이지·요소가 변경되면 중단하고 재관찰을 요구합니다. 결제·삭제·계정 변경·파일 업로드·비밀번호 입력·CAPTCHA 자동 해결은 지원하지 않습니다. 실패한 클릭을 자동 반복하지 않습니다. 기존 개별 조작 도구는 호환성을 위해 유지합니다.

브라우저만 설치하는 개발자는 최상위 `standalone/compose.yml`을 사용하면 됩니다. 단독 구성은 로컬 MCP 전용으로 인증이 없으므로 인터넷에 공개하면 안 됩니다. 서버 전체 설치와 OCI OAuth 구성은 기존 방법을 유지합니다.

## Playwright GUI 조작 엔진

좌표 클릭 도구는 Playwright Python `mouse.click(x, y)`를 사용하며, 뷰포트 바깥 좌표는 거부합니다. 텍스트가 여러 요소에 중복 매칭되면 첫 요소를 임의로 클릭하지 않고 `ok:false`와 일치 개수를 반환합니다. 텍스트 클릭 실패 시 `browser_elements`에서 특정 CSS 선택자를 확인하세요.


Playwright는 **이미 실행 중인 GUI Chromium의 로컬 CDP 9223**에만 연결합니다. 새 브라우저/프로필을 생성하거나 로그인 쿠키를 초기화하지 않습니다. 기존 13개 도구는 유지하고, 아래 도구 3개가 추가되어 HackBrowser는 기존 16개 도구와 신규 워크플로 3개로 총 22개입니다.

- `browser_click`: Playwright 실제 클릭, 동작 가능 여부 대기, URL/새 탭 감지
- `browser_fill`: 실제 입력 이벤트와 입력 유지 여부 검사(비밀번호 및 본문 내용은 응답하지 않음)
- `browser_click_text`: `text`, `role`(button/link/tab/text)로 클릭, 중복 매칭 거부
- `browser_fill_and_submit`: 하나의 입력란을 채운 뒤 Enter 한 번 제출
- `browser_click_at`: GUI 뷰포트 좌표를 한 번 클릭하는 보조 기능(자동 CAPTCHA 풀이 용도 아님)

클릭 결과의 `effect_observed`는 URL·본문 변경 또는 새 탭 생성이 관찰되었는지만 뜻합니다. **false여도 클릭 실패라는 뜻은 아닙니다.** 비동기 로딩 이후에는 `browser_wait_for`로 확인하세요. `next_target_id`가 새 탭 ID이면 다음 단계에서는 그 탭을 지정하세요. 보안 확인 및 접근 제한 감지·수동 인증 흐름은 종전과 동일합니다. 기존 서버에 Python 의존성 변경이 있으면 태그 배포 과정에서 해당 venv에 설치하고, CDP/GUI 서비스 설정은 유지합니다.

## GUI Chromium 전용 모드

HackBrowser MCP는 GUI Chromium의 로컬 CDP `127.0.0.1:9223`만 사용합니다. 기존 Headless Chromium 서비스 `mcpstack-chromium.service`는 설치·업데이트 시 비활성화하고 마스킹하며, `9222`에 자동 재연결하지 않습니다. GUI는 Xvfb 가상 디스플레이에서 실행되므로 서버에 모니터가 없어도 실제 GUI 브라우저를 구동합니다. VNC 등 화면 뷰어는 필요할 때만 별도 연결하며 CDP를 외부로 노출하지 않습니다.

기존 서버의 GUI 전환 명령:

```bash
sudo bash /opt/mcp-deployment/scripts/configure_gui_chromium.sh
sudo bash /opt/mcp-deployment/status.sh
```

이전에 수동으로 시작한 GUI Chromium(`9223`)이 있으면 그 세션이 살아 있는 동안 재사용하고, 종료되면 관리 서비스가 새 GUI를 실행합니다. 브라우저 프로필은 자동으로 병합하지 않습니다. **새 GUI는 별도 프로필**을 사용하므로 기존 로그인 쿠키는 필요시 다시 로그인해야 합니다. 상태 점검은 Headless 잔존 포트 `9222`를 오류로 처리합니다.

## 채팅 내 CAPTCHA 수동 입력

네이버의 사용자 확인 화면이 감지되면 `browser_page_text`가 `verification_required`를 반환합니다. `browser_screenshot`의 MCP Apps 화면에는 스크린샷과 **답변 입력칸·입력 위치 선택·확인 위치 선택·제출 버튼**이 함께 표시됩니다.

사용자는 실제 CAPTCHA 이미지를 직접 확인하고, 화면 속 답 입력칸과 확인 버튼 위치를 각각 클릭해 지정한 다음 채팅 카드에 답변을 입력하고 제출합니다. `browser_submit_verification`이 동일한 OCI Chromium 탭에 답변을 1회 전달합니다. 서버는 정답을 추측하거나 자동 재시도하지 않습니다. **제출 완료는 인증 성공을 의미하지 않습니다.** 인증 결과는 이후 화면에서 확인합니다.

일회용 검증 ID는 5분 후 만료됩니다. 브라우저 탭·URL·화면 크기가 달라지면 제출을 거부하며, 별도 파일에 답변을 저장하지 않습니다. 다만 사용자가 입력한 텍스트는 MCP 도구 호출 파라미터로 전달되므로 호스트·도구 호출 기록에 남을 수 있습니다. 계정 비밀번호·복구 코드는 입력하지 마세요. 공개 CDP 포트를 열 필요가 없습니다.

호스트가 MCP Apps의 `tools/call`을 지원해야 채팅 내 제출 기능이 작동합니다. 지원하지 않으면 사용자에게 오류를 표시하며 자동 인증 우회를 시도하지 않습니다.

## MCP Resource not found 대응

ChatGPT 채팅 위젯에서 `{"detail":"MCP Resource not found"}`가 표시되면 정답 오류가 아니라 **호스트에서 MCP 도구 호출을 찾지 못한 것**일 수 있습니다. 서버의 도구 수가 변경된 뒤 연결의 도구 목록이 갱신되지 않았거나 ChatGPT 호스트가 해당 도구 호출을 허용하지 않는 경우입니다. `check_mcp.py`의 서버 도구 검색과 ChatGPT 연결에 노출되는 도구 목록을 각각 확인하세요. 위젯은 초기화 응답의 호출 도구 이름에서 네임스페이스 접두사를 확인하고 적용합니다. 오류가 발생하면 중복 제출하지 말고 ChatGPT의 HackBrowser 연결을 새로고침하거나 재연결한 뒤 새로운 캡처를 실행하세요. 이 변경만으로 클라이언트의 도구 목록 갱신이나 호스트의 MCP 도구 호출 정책까지 보장하지 않습니다.

## CAPTCHA 수동 클릭 및 작업 재개

\`browser_screenshot\`이 CAPTCHA를 인식하면 스크린샷 하단의 카드가 열립니다. 사진 선택형 reCAPTCHA에서는 **이미지 직접 클릭**을 누르고 실제 화면의 체크박스/타일/확인 위치를 클릭하세요. 클릭은 사용자 입력에 한해 \`browser_verification_click\` 도구로 GUI Chromium에 전달됩니다. 텍스트형 확인은 입력 위치·버튼 위치를 지정한 뒤 기존 답변 제출을 사용합니다. 매 클릭 후 새 화면을 조회할 수 있으며 자동 문제 풀이·반복 클릭은 없습니다.

reCAPTCHA 응답 토큰이 확인되면 **AI 작업 계속** 버튼이 표시됩니다. 호스트가 MCP Apps 후속 메시지를 지원하면 기존 대화에서 브라우저 상태 확인과 작업 계속을 요청합니다. 토큰이 없더라도 사용자가 직접 확인한 후 버튼으로 재확인을 요청할 수 있습니다. 제출 성공은 인증 성공을 보장하지 않습니다. 다른 단계가 나오면 다시 사용자가 인증해야 합니다. CAPTCHA 답변은 MCP 도구 호출 인자에 들어가므로 계정 암호/복구 코드는 입력하지 마세요.

## 자동화 접근 제한 대응

HackBrowser는 자동화 접근 차단을 우회하지 않습니다. CAPTCHA에서 사용자가 직접 답변하는 절차와 명시적 사이트 접근 거부는 별도 상태로 처리합니다. 대신 불필요한 요청을 줄이기 위해 **사이트별 페이지 이동과 클릭 간 최소 4초 간격**을 둡니다. `browser_page_text`로 네이버 쇼핑·Google 검색·G마켓의 명시적인 접근 제한 화면이 확인되면 관련 사이트에 **30분 동안 추가 페이지 이동·클릭을 중지**하고 원인을 표시합니다. 대기 시간은 같은 페이지를 반복해서 읽더라도 늘어나지 않으며, 서비스 재시작 이후에는 초기화됩니다.

이 기능은 요청 폭주 예방용으로, 데이터센터 공인 IP의 평판 문제나 사이트의 자동화 정책 제한을 해제하지 않습니다. 사이트에 차단 메시지가 표시되면 반복 요청하거나 사용자 확인 절차를 자동화하지 말고, 브라우저에서 공식 확인·고객센터 절차를 이용하세요. 정상적인 검색 페이지가 필요하면 이용약관이 허용하는 공식 서비스·API를 선택하세요.

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

`private.env`, ZAP 키, 공유 URL을 Git에 올리지 마세요. **8081(Keycloak), 8282(ZAP), 9223(GUI CDP)는 외부에 공개하면 안 됩니다.** 사용자 계정이 여러 개라도 HackBrowser 브라우저 세션과 ZAP 스캔 환경은 공유됩니다. 능동 진단은 승인된 대상에서만 수행하세요.
