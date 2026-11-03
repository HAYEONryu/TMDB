# TM 고객관리 진행 기록

- 기준 시각: 2026-11-03, Asia/Seoul
- 기준 설계: `TM_고객관리_개발설계서.md` v1.1, 수정일 2026-10-30
- 프로젝트: `/Users/hayeon/Documents/TMDB`
- 개발 계획: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- 현재 상태: **2단계 프로젝트·디비·로그인 기반 완료. 실제 PostgreSQL·서버 45개 테스트·브라우저 1개 흐름 검증. Docker 엔진 실행은 미검증. 다음 사용자 요청 대기.**
- 최신 상세 결과: [VERIFICATION_STAGE2.md](VERIFICATION_STAGE2.md), 실행: [README](../README.md), 구조: [FOUNDATION.md](FOUNDATION.md).
- 아래 1~4절은 1단계 당시의 기록이다. 최신 완료·미완료·다음 작업은 5절을 따른다.

## 1. 완료 항목

- [x] Downloads의 설계서 v1.1 전체 973행 확인. 첨부 문서의 전체 구현 지시와 이번 요청의 계획 전용 범위를 구분.
- [x] 적용 경로의 `AGENTS.md` 존재 여부 확인. 해당 파일 없음. 별도 ChatGPT 프로젝트 미러 지침은 읽었으나 TMDB 경로 적용 대상이 아님을 기록.
- [x] 현재 Documents 저장소·TMDB·기존 프로젝트 구조 확인. TMDB는 빈 폴더였음.
- [x] 기존 furbebe의 README·패키지 설정 확인. 보호견 도메인과 FastAPI/React 구조라 TM 기반으로 재사용하지 않기로 판단.
- [x] 새 TM 프로젝트 위치를 `/Users/hayeon/Documents/TMDB`로 정하고 설계서 기술 구성 유지.
- [x] 도구 버전·PATH·DB readiness·패키지 상태·공간 확인.
- [x] PostgreSQL 17.11 임시 클러스터 실제 실행·SQL·트랜잭션 advisory lock·정상 종료 확인.
- [x] 설계서 충돌·미지정 정책을 조항·영향·해결 시점과 함께 계획서에 기록.
- [x] P0~P11 개발 구간과 완료 조건, 설치·환경변수·로컬 실행·테스트·복원 방법 작성.
- [x] 18.1~18.7 필수 검수 총 69개 항목을 개발 구간·검증 방식에 연결.
- [x] 계획·진행 기록 두 Markdown 파일 작성.
- [x] 문서 최종 정합성 검사 13개 통과. 결과와 실행 범위를 이 기록에 반영.

## 2. 실제 실행·검증 결과

| 검사 | 결과 | 근거·제한 |
|---|---|---|
| 설계서 식별 | 확인 | v1.1 / 973행 / SHA-256 `5a97604423c005bafd30ceb36fad4e43496565a7c978865730df08734d62ac57` |
| AGENTS 탐색 | 확인 | 상위 경로 및 Documents 하위 숨김 파일 포함 확인. 적용되는 파일 없음. `.agents` 사용자 홈 경로는 존재하지 않음 |
| 기존 코드·Git | 확인 | TMDB 초기 비어 있음. Documents 추적 파일 목록 없음. 기존 미추적 `.DS_Store`, `.localized`, `Codex/`, `furbebe/`, `secrets.toml` 보존. secrets.toml 내용은 읽지 않음 |
| Python·uv | 일부 준비 | 기본 Python 3.9.6, 추가 3.12.15, uv 0.12.21. Python 3.13 설치 확인 못함 |
| uv 기본 캐시 | 최초 실패·대체 조회 성공 | 기본 캐시 경로 쓰기 제한. `uv --no-cache python list --only-installed`로 설치 목록 조회 성공 |
| Docker·Caddy | 미준비 | docker/caddy 명령 없음. Docker.app·OrbStack.app 없음. Compose·이미지·HTTPS 검증 미실행 |
| PostgreSQL 바이너리 | 확인 | 기본 psql/pg_config 16.15, 명시 17 경로의 postgres/psql 17.11 |
| 로컬 5432 readiness | 미응답 | `127.0.0.1:5432 - no response`. 기존 서비스나 DB를 시작·변경하지 않음 |
| PostgreSQL 임시 smoke 1차 | 실패 | 기본 샌드박스의 공유 메모리 생성 제한. initdb exit 1, SQL 미실행 |
| PostgreSQL 임시 smoke 재검증 | 통과 | 같은 검사 권한 확장 실행: initdb/start/SQL/stop 모두 exit 0. SQL에서 server_version=17.11, BEGIN, `pg_advisory_xact_lock(7420192701)`, SELECT 1, ROLLBACK 성공 |
| 임시 DB 정리 | 완료 | `/private/tmp/tm-stage1-pg-*` 내 빈 클러스터만 사용. TCP 수신 없이 Unix 소켓. 종료 후 임시 디렉터리 삭제 |
| Homebrew 패키지 조회 | 일부 실패 | 캐시 갱신/tap 쓰기 제한. 설치나 시스템 설정 변경 성공으로 보고하지 않음. PG17 설치 확인은 바이너리 직접 호출 근거 |
| Node/npm/Git | 확인 | 22.23.3 / 10.9.9 / 2.50.1 |
| Python 기본 환경 앱 패키지 | 미발견 | django/psycopg/openpyxl/playwright import spec 없음. 다른 프로젝트 환경은 변경하지 않음 |
| 공식 지원·패치 조사 | 확인 | 계획서 3.1에 공식 링크와 확인값 기록. 아직 설치·의존성 조합 검증은 아님 |
| 검수 항목 계수 | 통과 | 18.1=6, 18.2=9, 18.3=7, 18.4=11, 18.5=9, 18.6=9, 18.7=18, 합계 69 |
| 문서 존재·내용·링크·원본 불변 | 통과 | Python 검사 스크립트 exit 0, 13/13 통과. 요청한 두 파일만 존재·원본 해시·버전·필수 내용·P0~P11·69개 검수 매핑·코드블록·상대 링크·편집 잔여 표기·임시 DB 정리·각 파일 공백 검사 |
| Django·브라우저·업무 동시성 테스트 | 미실행 | 애플리케이션 구현 금지 단계로 실행할 코드·migration·테스트 없음. 임시 DB smoke를 앱 테스트 통과로 간주하지 않음 |

PostgreSQL smoke용 래퍼 프로세스의 종료 코드만으로 성공을 판단하지 않았으며 각 하위 명령의 결과를 확인했다. 1차 실패와 재검증 성공을 모두 남겼다. 로그·예시·임시 DB에는 실제 고객 개인정보를 사용하지 않았다.

문서 검증은 시스템 Python으로 실행했으며 앱 패키지 설치 없이 완료했다. 원문 검수 개수의 재계수 결과를 계획서 표와 대조했고, 두 파일 각각 `git diff --no-index --check /dev/null <파일>`로 공백 오류가 없음을 확인했다. 이 검사는 문서 구조·정합성 검증이며 미래 업무 기능의 테스트 통과를 의미하지 않는다.

## 3. 미완료·미해결 문제

| 구분 | 상태·영향 | 다음 해결 작업 |
|---|---|---|
| 환경 E1 | Python 3.13 및 Docker/Compose 미준비. 앱·Compose 실행 전 해결 필요 | 프로젝트 전용 Python 또는 고정 컨테이너와 Docker 실행 환경 준비 |
| 환경 E2 | 기본 PostgreSQL은 16이고 일반 샌드박스는 공유 메모리 제한 | PostgreSQL 17 명시 경로/Compose 사용. 임시 실행은 검증했지만 상시 앱 DB·테스트 DB는 아직 없음 |
| C1 관리자 저장 범위 | 공통 이동 전 저장과 관리자 수동 저장의 교차 동작 미확정 | 관리자 UI 구현 전 저장/머무르기/폐기 동작 확인. 조용한 자동 저장 금지 |
| M1 실패 업로드 | FAILED 복구·같은 key 재시도·만료 정책 미구체화 | 업로드 구현 전 상태 전이·receipt 계약 정의 |
| M2~M5 기술 기본값 | 운영 시작일, lease/timeout, 로그인 제한, 업로드 결과 보존 수치 미정 | 해당 구간 전 설정과 검증 기준 기록 |
| M6 통계 | ‘미진행 건수’의 전체/오늘 집합 범위 확인 필요 | 통계 구현 전 라벨·집계 조건 확정 |
| M7~M8 인수·API | 성능 합격 수치와 세부 API 형식 미정 | 실제 측정 및 API 계약 구체화 |
| M9 운영 입력 | 도메인·실제 백업 목적지·암호화 자격증명 미정 | 로컬 작업 차단 아님. 운영 요청이 있을 때 별도 구성 |
| 애플리케이션 전체 | 미구현 | 이번 요청에 따라 의도적으로 시작하지 않음 |

C2 notes 길이 예외는 설계서 7.8에 이미 해법이 있어 업무 변경 없이 반영할 항목이다. 설계서 자체는 수정하지 않았다. 미지정 구현 기본값과 확인이 필요한 업무 흐름을 구분했으며, 모든 항목의 근거는 계획서 6절에 있다.

## 4. 다음 작업 — 별도 요청 전 실행하지 않음

1. 사용자가 전달할 다음 단계 범위를 확인하고 해당 경로 지침·원본 버전을 재확인한다.
2. 기반 환경이 범위에 포함되면 Docker/Compose·Python 3.13·잠금 의존성·가짜 `.env.example`·PostgreSQL 개발/테스트 DB를 준비한다.
3. 모델이 범위에 포함되면 사용자 UUID 모델을 최초 migration 전에 정의하고 도메인 제약·공통 쓰기 잠금부터 구현한다.
4. 해당 단계의 실제 실행·테스트 결과, 실패·미실행 사유, 남은 문제를 이 기록에 갱신한다.

이번 1단계로 생성하는 프로젝트 산출물은 `docs/IMPLEMENTATION_PLAN.md`, `docs/PROGRESS.md` 두 파일이다. 기존 파일·sources·설계서 원본을 수정하지 않고 앱 구현·의존성 설치·유료 신청·운영 배포·다음 단계 착수는 하지 않는다.

## 5. 2단계 — 프로젝트 기반·디비·로그인

실행일: 2026-11-03, Asia/Seoul. 사용자 2단계 요청으로 구현을 시작했다. 1단계의 구현 금지는 해당 단계 범위였으며 이번 요청에 따라 해제되었다. 설계서 원본 SHA-256은 유지한다.

### 5.1 완료 항목

- [x] Python 3.13.18 공식 소스 해시 확인·프로젝트 내부 빌드, Django 5.2.18 전용 .venv 설치.
- [x] uv.lock 및 해시 포함 requirements.lock, .env.example, .gitignore·.dockerignore 작성.
- [x] PostgreSQL 17.11 전용 로컬 클러스터·tm_dev 구성. 다른 프로젝트 DB·시스템 Python·OS 서비스를 변경하지 않음.
- [x] 16개 도메인 모델 및 로그인 실패 제한 보조 모델, unique·부분 unique·CHECK·FK·인덱스·migration 구현.
- [x] CustomerDeletionRequest 포함: PENDING 하나·상태 정합성·요청 당시 할당 FK·승인/종료 기록 구조. 실제 접수·승인 API는 후속 범위.
- [x] 공통 PostgreSQL 쓰기 advisory lock·5초 timeout·1회 재시도·실패 시 503 기반.
- [x] 실제 빈 DB migrate 및 재실행, 생성 누락 검사 통과.
- [x] 전화번호 로그인·관리자/직원 역할·서버 세션·CSRF·초기 변경 게이트·비밀번호 검증 구현.
- [x] dodream 초기/재설정 유지, 비밀번호 해시만 저장. 미변경 계정의 업무 경로 차단.
- [x] 현재 비밀번호 확인 후 최초/본인 변경, 현재 세션만 유지·다른 세션 무효화.
- [x] 관리자 재설정 API·내부 서비스, 대상 모든 기존 세션 무효화·최초 변경 재요구.
- [x] 비활성화·역할 변경 내부 서비스와 session_version 연동. 마지막 관리자 보호와 미진행 회수 규칙을 함께 구현·검증. 관리 UI/API는 후속 범위.
- [x] create_initial_admin 및 반복 실행해도 기존 비밀번호를 보존하는 seed_demo 제공.
- [x] 한국어 로그인·비밀번호 변경·역할별 기반 확인 화면, 로컬 Bootstrap 자산 제공.
- [x] Dockerfile·Compose·선택 Caddy 로컬 구성, 이미지 태그/manifest/digest 고정.
- [x] scheduler 진입점·DB 연결 점검 제공. 업무 예약은 실행하지 않는 상태로 명확히 표시.
- [x] PostgreSQL 통합 45개·Chromium 1개 흐름·실제 Gunicorn HTTP 검증 완료.
- [x] README·기반 구조·검증 결과 작성, 구현 계획과 이 기록 갱신.

### 5.2 실제 실행 및 결과

| 실행·검사 | 결과 |
|---|---|
| Python 소스 다운로드/해시/빌드 | 공식 SHA-256 일치, 3.13.18 설치. uv 목록에 해당 패치 없음은 소스 빌드로 해결 |
| uv sync / export | Django 5.2.18·psycopg 3.3.7 등 잠금 설치. 시스템·다른 프로젝트 venv 보존 |
| local_db.py start | 프로젝트 .local/postgres17, 127.0.0.1:55432, PostgreSQL 170011 |
| migrate / 재실행 | 전체 적용 / No migrations to apply |
| manage.py check / makemigrations --check | 문제 0개 / No changes detected |
| test tests --noinput -v 2 | 최종 **45개 통과**, 1.174초, 별도 test_tm_dev 생성·삭제 |
| test tests.browser_flow --noinput -v 2 | 최종 **1개 통과**, 9.887초. 관리자/직원 최초 변경·역할·두 세션 재설정·모바일 배치 |
| 최초 테스트 실패 | 41개 중 종료 사유 CHECK 1개 실패. PostgreSQL NULL 평가 문제를 migration 0003으로 수정한 뒤 전체 통과 |
| seed_demo 두 번 | 가짜 관리자 1·직원 2명 생성 / 두 번째 기존 유지. 모두 must_change_password=true·is_superuser=false |
| run_scheduler --once | PostgreSQL 연결 확인. 미구현 업무를 완료 처리하지 않음 |
| collectstatic | 정적 자산 4개 수집 |
| Gunicorn 실제 실행 | 127.0.0.1:8000 기동. healthz=200, 로그인=200, Bootstrap=200 |
| 이미지 공개 manifest | Python/PostgreSQL/Caddy 태그·arm64/amd64·digest 확인. 실행 성공을 의미하지 않음 |
| Compose YAML | 파싱·4개 서비스·공유 앱 이미지·포트 제한·latest 미사용 검사 통과 |
| PC·좁은 화면 스크린샷 | .local/qa에 저장 후 눈으로 확인. 잘림·가로 넘침 없음. JS 오류·외부 CDN 요청 없음 |

실패 빈도 제한은 설계서 미지정 기본값을 900초·계정 5회·출처 30회로 구체화했다. 사용자 이름 100자, 계약 내부 enum, 잠금 timeout/재시도, 개발 DB 분리도 FOUNDATION.md에 이유와 함께 기록했다. 승인된 업무 규칙·설계서 원문은 바꾸지 않았다.

### 5.3 미완료·제한

- Docker 엔진·Compose 명령이 없어 컨테이너 build/up/config는 미실행이다. 검증한 실행 경로는 호스트 Python 3.13.18 + 실제 PostgreSQL 17.11이다.
- 대화 옆 in-app browser는 제공되지 않아 열지 못했다. 별도 Chromium 자동 검증·스크린샷 검토는 통과했다.
- 기존 기본 PostgreSQL PATH는 여전히 16이므로 프로젝트 스크립트가 17 경로를 명시한다. Codex 샌드박스의 로컬 DB 접속·공유 메모리 제한은 필요한 검증 명령에만 권한 확장하여 수행했다.
- 고객 목록/그리드·엑셀·분배·자동 저장·재콜 작업·통계·23시 회수·삭제 요청 접수/승인·영구 삭제의 최종 정리 서비스는 미구현이다. 데이터 구조와 인증 기반만 이번에 제공했다.
- 비밀번호 재설정·사용자 접근 상태 변경의 전체 관리 UI는 후속 단계다. 재설정 API와 접근 상태 내부 서비스는 이번에 검증했다.
- 고객명/번호 일반 수정 금지와 notes 입력 길이 예외는 후속 수정 API에서 적용해야 한다. 현재 고객 변경 API는 없다.
- 운영 HTTPS·실제 백업 저장소·복원·배포·전체 69개 인수 검수·1만 행 성능 측정은 미실행이다.
- 계획의 C1 저장 이동 UX, M1 업로드 실패, M2 예약 시작일/lease, M5 결과 보존, M6 통계 집합 등은 해당 후속 단계 전에 구체화할 항목으로 유지한다. M4 로그인 실패 제한은 이번에 해결했다.

### 5.4 다음 작업

사용자가 지정할 다음 단계 요청을 기다린다. 이 단계에서 다음 업무 기능을 임의로 착수하지 않는다. 다음 요청에서는 기존 models/migrations·공통 잠금·권한 검사를 재사용하고, 해당 기능의 실제 구현·실행·테스트와 진행 기록을 갱신한다.

검증용 앱 서버와 프로젝트 DB는 작업 종료 때 정상 종료한다. 사용자는 README의 local_db.py start → migrate → collectstatic → gunicorn 순서로 다시 실행할 수 있다. 새로 만든 .env와 DB에는 가짜 개발 값만 있으며 sources·설계서 원본·기존 사용자 파일은 보존했다. 유료 서비스 신청·운영 배포·외부 메시지 전송은 하지 않았다.
