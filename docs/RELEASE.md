# 릴리스 및 OCI 자동 배포

[처음 설치](../README.md) · [서버 운영](../MCP-Deployment/README.md)

## 배포 동작

`master`의 일반 커밋만으로는 OCI 배포가 시작되지 않습니다. `vMAJOR.MINOR.PATCH` 형식의 **새 Git 태그**를 푸시할 때 [MCP tagged release and OCI deployment](../.github/workflows/mcp-release.yml)가 실행됩니다. 릴리스 태그는 `master`에 이미 포함된 커밋을 가리켜야 합니다.

| 단계 | 실행 내용 |
|---|---|
| CI | ARM64 환경에서 단위 테스트 및 셸·Python 문법 검증 |
| 패키지 | 설치용 `mcp-deployment-<version>.tar.gz` 및 SHA-256 생성 |
| GitHub Release | 버전별 패키지·체크섬 게시 |
| OCI CD (선택) | SSH 전송 → 체크섬 검증 → 기존 소스 교체 → 서비스 검증 |

## 1. 최초 1회 준비

OCI 서버에 먼저 `MCP-Deployment/install.sh`로 설치를 끝냅니다. 자동 CD는 **최초 설치를 대신하지 않습니다.**

GitHub 저장소의 **Settings → Secrets and variables → Actions**에서 다음을 설정합니다.

- Repository variable: `OCI_DEPLOY_ENABLED=true`
- Repository secrets: `OCI_SSH_HOST`, `OCI_SSH_USER`, `OCI_SSH_PRIVATE_KEY`, `OCI_SSH_KNOWN_HOSTS`

`oci-production` 환경에 대한 접근·승인 정책도 필요한 경우 설정하세요. SSH 키는 별도 배포 전용으로 발급하고 `known_hosts` 지문을 검증합니다.

## 2. 새 버전 배포

```bash
git checkout master
git pull --ff-only origin master
VERSION=v1.0.3   # 실제로 사용하지 않은 새 버전으로 변경
git tag -a "$VERSION" -m "MCP Deployment $VERSION"
git push origin "$VERSION"
```

GitHub Releases에서 **새 태그를 함께 생성**해도 됩니다. 기존 태그의 Release만 재게시·수정해서는 태그 푸시 이벤트가 다시 발생하지 않습니다.

## 3. 배포 결과 확인

워크플로의 `validate-and-package` → `github-release` → `deploy-oci` 순서로 확인합니다. `deploy-oci`는 위 variable이 활성화된 경우에만 실행됩니다.

서버에서:

```bash
sudo bash /opt/mcp-deployment/status.sh
sudo python3 /opt/mcp-deployment/scripts/check_calls.py
sudo cat /opt/mcp-deployment/runtime/deployed-version
```

- `status.sh`: 서비스 포트, Keycloak/OAuth, MCP 47개 도구 검색 확인
- `check_calls.py`: PocMap·HackBrowser·ZAP 실제 무해한 도구 호출 및 PNG 스크린샷 블록 확인
- 워크플로 Artifacts: `tagged-ci-evidence`, `tagged-oci-deploy-evidence` 로그·이미지 증적

## 실패할 때

- `Initial installation required`: 서버에서 `install.sh`로 초기 설치 필요
- `Python dependencies changed`: 자동 배포가 중단됨. 설치기/의존성 변경을 별도 검토
- Keycloak 인증·포트 오류: [서버 운영 문서의 점검 절차](../MCP-Deployment/README.md#문제-해결) 확인
- 기존 릴리스 재배포: 동일 버전이 이미 반영됐는지 `runtime/deployed-version`, `runtime/deployed-commit` 확인

배포 중 `runtime/`의 계정·비밀번호·토큰·DB는 보존하고 코드 백업을 만들어 오류 시 복원을 시도합니다. 배포 성공 전에는 실제 `tools/call` 검사까지 통과해야 합니다.
