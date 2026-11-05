# 2단계 실행·검증 결과

> v1.1의 과거 실행 이력이다. 현재 v2.0 결과는 [P1 검증 기록](P1_VERIFICATION.md)을 따르며 아래 통과 수치를 승계하지 않는다.

- 실행일: 2026-11-03, Asia/Seoul
- 환경: macOS arm64, 프로젝트 Python 3.13.18, Django 5.2.18, PostgreSQL 17.11
- DB: 프로젝트 내부 클러스터 `127.0.0.1:55432`; 앱 `tm_dev`, 테스트 `test_tm_dev`
- 가짜 계정·가짜 고객만 사용. 설계서 원본·sources·기존 다른 프로젝트는 수정하지 않음.

## 통과

| 실행 | 결과 |
|---|---|
| 공식 Python 소스 SHA-256 검증·빌드 | 3.13.18 실행 확인. uv 관리 다운로드 목록 부재를 소스 빌드로 해결 |
| uv sync·lock·해시 requirements export | 프로젝트 .venv 설치 완료. Docker용 잠금 파일 생성 |
| PostgreSQL 실제 migrate | 모든 migration 적용. 재실행은 No migrations to apply |
| `manage.py check` | 문제 0개 |
| `makemigrations --check --dry-run` | No changes detected |
| `manage.py test tests --noinput -v 2` | **45개 통과**, 1.174초. 매번 별도 테스트 DB 생성·삭제 |
| `manage.py test tests.browser_flow --noinput -v 2` | **1개 통과**, 9.887초. 실제 Chromium·HTTP·PostgreSQL·기본 해시 사용 |
| `seed_demo` 2회 | 신규 3계정 생성 후 재실행은 기존 유지. 초기 변경필수/비-superuser 확인 |
| `run_scheduler --once` | PostgreSQL 연결 확인. 후속 업무 예약을 성공 처리하지 않음 |
| `collectstatic --noinput` | Bootstrap/CSS/JS/라이선스 4파일 수집 |
| 실제 Gunicorn·HTTP | healthz=200/DB ok, 로그인=200, Bootstrap CSS=200 |
| Compose YAML 구조 | web/scheduler 동일 이미지·DB 포트 비공개·loopback web 포트 확인 |
| 공개 공식 이미지 manifest | Python 3.13.18/PostgreSQL 17.11/Caddy 2.10.2의 Linux arm64/amd64 지원·digest 확인 및 고정 |

## 검증한 동작

- 관리자·직원 초기 dodream 로그인, 하이픈 전화번호 정규화, 잘못된 계정의 일반 오류.
- 최초 비밀번호 변경 전 업무 API·페이지·재설정 차단, `/api/me`의 본인 상태 조회만 허용.
- 현재 비밀번호·새 비밀번호·확인 검증, 짧음/과다 길이/숫자 전용/불일치 거부.
- 관리자/직원 역할별 접근, 직원의 재설정 금지, superuser 플래그로 업무 역할 우회 불가.
- 본인 비밀번호 변경 후 현재 세션 유지·다른 세션 무효화.
- 관리자 재설정 후 기존 두 브라우저 세션 무효화·dodream 재로그인·최초 변경 재요구. 관리자 본인 재설정도 세션 무효화.
- 비활성화·역할 변경 세션 무효화. 비활성화 동안 요청하지 않았던 세션도 재활성화 후 복구되지 않음.
- 마지막 관리자 보호, 관리자 두 명의 동시 자기 비활성화에서도 한 명 유지.
- 로그인·비밀번호 변경·재설정·로그아웃 CSRF, GET 로그아웃 거부.
- 실패 빈도 제한·만료·HMAC 저장, 비밀번호 원문 비저장, 실제 PBKDF2 기본 해시.
- 현장 정규화 동시 unique, 고객 전화번호 휴지통 포함 unique/현장 간 중복 허용, enum·버전·상태 제약.
- 현재 할당·PENDING 재콜·PENDING 삭제 요청 부분 unique, 요청 당시 고객/할당 검증, CASCADE, notes 시스템 추가 공간.
- 공통 advisory lock의 독립 연결 경합, 실제 lock timeout·제한 재시도·503·잠금 해제 후 재로그인.
- 브라우저에서 PC/390px 로그인·비밀번호 변경 화면 확인, 가로 넘침 없음, JS page error 0개·외부 CDN 요청 0개.

스크린샷은 `.local/qa/login-desktop.png`, `first-password.png`, `admin-home.png`, `employee-home.png`, `login-mobile.png`에 있고 직접 확인했다. 원시 실행 로그는 `.local/stage2-tests.log`, `.local/stage2-browser.log`다. 이 파일들은 저장소에 포함하지 않는 로컬 검증 산출물이다.

## 실패와 보완

첫 서버 테스트는 41개 중 할당 종료 사유 검증 1개가 실패했다. SQL CHECK가 NULL 평가를 허용하는 경우를 발견해 종료 시 `end_reason IS NOT NULL`을 명시하는 assignments 0003 migration으로 보완했다. 이후 관련 테스트 및 전체 테스트가 통과했다. 추가 경합·세션 사례를 포함한 최종 서버 테스트는 45개다.

초기 browser 실행의 staticfiles 미수집 경고는 collectstatic 후 해소했다. 첫 Gunicorn 기본값은 사용자 홈 제어 소켓을 사용했으므로 프로세스를 정상 종료하고 `gunicorn.conf.py`에서 제어 소켓을 비활성화한 설정으로 다시 실행했다.

## 미실행·제한

- Docker 엔진/Compose가 현재 호스트에 없어 `docker compose build/up/config` 명령은 미실행. YAML 파싱·manifest 확인을 컨테이너 실행 통과로 간주하지 않는다.
- 대화 옆 in-app browser 열기는 해당 browser가 제공되지 않아 실패했다. 별도로 실행한 Chromium 자동화·스크린샷·HTTP 검증은 통과했다.
- scheduler는 연결·프로세스 진입점만 있으며 23시 회수·자료 정리·lease 재실행은 후속 단계다.
- 고객 그리드·데이터 API·업로드·분배·자동 저장·통계·재콜 작업·삭제 요청 접수/승인과 최종 영구 삭제 정리는 미구현. 모델 제약 검증을 이 업무 기능의 완료로 보고하지 않는다.
- 설계서 18장의 **전체 69개 인수 시나리오는 아직 완료하지 않았다**. 이번 검증은 기반·계정과 모델 제약 범위다.
- 운영 HTTPS·백업/복원·외부 저장소 전송·배포·성능 인수는 미실행. 유료 서비스 신청 없음.
