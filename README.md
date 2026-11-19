# HackBrowser MCP · Docker CI/CD

> 기존 MCP 브리지의 테스트·컨테이너화·OCI 자동 배포를 위한 학습 프로젝트

**현재 상태:** MCP 소스 등록 완료 · 자동 소스 검증 구성 · ARM64 Docker 이미지 및 자동 배포는 **미구현**

## 목표 아키텍처

```text
GitHub Push
    ↓
GitHub Actions (tests → ARM64 Docker build)
    ↓
GHCR (versioned container image)
    ↓
OCI Ubuntu ARM64 (Docker Compose pull / update)
    ↓
HackBrowser MCP (remote MCP tools)
```

**중요:** 현재 추가된 GitHub Actions는 Python·Shell 문법과 패키지 구조를 검증하는 **CI 단계만** 실행합니다. GHCR 게시, OCI SSH 배포, 실서비스 테스트는 후속 작업입니다.

## 코드 위치

| 경로 | 역할 |
|---|---|
| [MCP-Deployment/](./MCP-Deployment/) | 현재 진행 중인 MCP 배포 패키지 |
| [MCP-Deployment/services/hackbrowser/](./MCP-Deployment/services/hackbrowser/) | Chromium CDP를 제어하는 Python MCP 브리지 (도구 8개) |
| [MCP-Deployment/tests/](./MCP-Deployment/tests/) | 패키지 정적 테스트 |
| [MCP-Deployment/docs/PROVENANCE.md](./MCP-Deployment/docs/PROVENANCE.md) | 소스 출처 및 제약사항 |
| `src/`, `main.js`, `package.json` | 원래 HackBrowser Electron 프로젝트 (레거시 원본) |

### 원본과 MCP 브리지의 차이

이 저장소는 [hackbrowser/hackbrowser](https://github.com/hackbrowser/hackbrowser)의 **Fork**입니다. 원본 HackBrowser는 Electron 기반이며 현재 유지보수되지 않습니다. 추가된 MCP 배포 패키지는 **원본 Electron 실행파일이 아닌 현대 Chromium + Python/CDP 브리지**를 사용합니다. 따라서 원본 Electron 앱의 ARM64 동작이 검증된 것은 아닙니다.

## 소스 검증

Python 3와 Bash를 설치한 환경에서 아래 명령을 실행합니다.

```bash
python -m pip install PyYAML
python -m unittest discover -s MCP-Deployment/tests -p 'test_*.py' -v
```

이 테스트는 문법·설정·도구 선언을 검사할 뿐 실제 Docker 이미지 빌드, MCP 연결 또는 OCI 배포 성공을 보증하지 않습니다.

## 배포 및 보안

- 대상 서버: OCI Ubuntu 22.04 ARM64 (Ampere A1)
- 계획: ARM64 컨테이너 구축 → GHCR 이미지 게시 → Docker Compose 갱신
- CDP 9222와 내부 MCP 포트를 인터넷에 직접 노출하지 않습니다. 원격 연결에는 HTTPS와 인증이 필요합니다.
- `.env`, 생성된 자격증명, 개인키 및 `runtime/` 디렉터리를 Git에 올리지 않습니다.
- 기존 설치 스크립트는 주로 **Ubuntu 호스트의 systemd**에 MCP를 설치합니다. `MCP-Deployment/docker-compose.yml`만으로 HackBrowser MCP가 컨테이너에서 실행되는 것은 아닙니다. 상세 내용은 [배포 패키지 설명](./MCP-Deployment/README.md)을 확인하세요.

## 출처·라이선스

원본 Electron HackBrowser 코드는 상위 프로젝트의 MIT 라이선스를 따릅니다. MCP 패키지 및 외부 의존성의 출처와 제약은 [PROVENANCE.md](./MCP-Deployment/docs/PROVENANCE.md)에 기록했습니다.
