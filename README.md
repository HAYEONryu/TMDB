# TM 고객관리

한국어 TM 고객관리 서비스. 설계서 **v2.0의 P9: AI 공통 기반**까지 구현·로컬 검증했다. 기본 업무69항목과 총314개 테스트를 통과했다.

Python 3.13.18 / Django 5.2.18 / PostgreSQL 17.11 / Django Templates / Bootstrap 5.3.8을 사용한다. 의존성은 `uv.lock`, 컨테이너 설치용 해시 잠금은 `requirements.lock`에 있다.

관리자 현장·고객 그리드·수동 저장·휴지통·엑셀·분배/회수·담당자 변경·사용자 관리, 직원 오늘 할 일/나의 DB·자동 저장·재콜 완료·이력·상세 통계·23시 예약 회수·삭제 요청/승인·영구 삭제를 사용할 수 있다. AI 본 기능은 후속 단계다. 일반 업무 관리자는 Django superuser가 아니다.

기존 기반 코드를 보존하고 상담 이력 `ConsultationRevision`, 서버 전용 `.env.ai` 로더·프로세스 분리·테스트 전용 fake·로그 마스킹을 추가했다. P9에 AI 요청/결과·30회 quota·비용 예약·DB worker·파생 원문 삭제 기반을 연결했다. 직원 생성 버튼은 P10, 보고서는 P11 범위이며 실제 공급자 전송 경로는 비활성이다.

현재 결과는 [P9 검증 기록](docs/P9_VERIFICATION.md)·[기본69항목 재검수](docs/P9_BASIC_ACCEPTANCE.md), 이전 결과는 [P1](docs/P1_VERIFICATION.md)·[P2](docs/P2_VERIFICATION.md)·[P3](docs/P3_VERIFICATION.md)·[P4](docs/P4_VERIFICATION.md)·[P5](docs/P5_VERIFICATION.md)·[P6](docs/P6_VERIFICATION.md)·[P7](docs/P7_VERIFICATION.md)·[P8](docs/P8_VERIFICATION.md), 순서는 [개발 계획](docs/IMPLEMENTATION_PLAN.md), 활동은 [진행 기록](docs/PROGRESS.md)을 따른다. 이전 문서와 병합 충돌의 양쪽 내용은 `docs/history/`에 보존했다.

## 1. 현재 컴퓨터에서 실행 — 실제 검증한 경로

작업 위치는 `/Users/hayeon/Documents/TMDB`다. 프로젝트 전용 Python `.local/python-3.13.18`과 `.venv`가 준비되어 있다. 기존 프로젝트나 시스템 서비스를 사용하지 않는다.

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/gunicorn config.wsgi:application
```

접속: **http://127.0.0.1:8000/auth/login**. DB 연결 확인: http://127.0.0.1:8000/healthz.

23시 자동 회수·누락/실패 재실행과 임시 자료 정리를 위해 DB가 실행 중인 상태에서 별도 터미널로 다음 프로세스도 실행한다.60초마다 작업을 확인하고 만료 후보·행 원문·기간이 끝난 요청 결과를 정리한다. 한 번 실행은 `--once`, 업로드만 정리는 `python manage.py cleanup_imports`를 사용한다. 예약 시작일과 재시도는 아래14절을 따른다.

```sh
.venv/bin/python manage.py run_scheduler
```

종료할 때는 scheduler와 Gunicorn을 Ctrl+C로 먼저 종료한 뒤 아래 DB stop을 실행한다.23시 회수를 자동 실행하려면 서버와 scheduler가 계속 실행 중이어야 한다.

`.env`가 없는 새 checkout에서만 다음을 실행한 뒤 개발 값을 확인한다. 기존 `.env`를 덮어쓰지 않는다.

```sh
cp -n .env.example .env
```

`scripts/local_db.py`는 `/opt/homebrew/opt/postgresql@17/bin`을 사용하며 프로젝트 내부 `.local/postgres17`에만 클러스터를 만든다. 다른 경로에 PostgreSQL 17이 있으면 `TM_PG_BIN`으로 지정한다. 포트는 `127.0.0.1:55432`, DB는 `tm_dev`, 가짜 개발 계정은 `tm / tm-local-only`다. 이 계정은 로컬 테스트 DB 생성을 위해 클러스터 관리 권한을 가진다. 운영용 계정 구성이 아니다.

서버는 Ctrl+C로 종료한다. DB 상태 확인·종료:

```sh
.venv/bin/python scripts/local_db.py status
.venv/bin/python scripts/local_db.py stop
```

소스 수정 중 자동 재시작이 필요하면 Gunicorn 대신 `.venv/bin/python manage.py runserver 127.0.0.1:8000`을 사용할 수 있다. 검증 때 실행한 서버는 종료했으며 다시 시작하는 명령은 위와 같다.

## 2. 최초 관리자와 가짜 테스트 계정

빈 DB에 최초 업무 관리자 생성:

```sh
.venv/bin/python manage.py create_initial_admin
```

전화번호·이름을 대화형으로 입력한다. 가짜 값으로 비대화형 실행도 가능하다.

```sh
.venv/bin/python manage.py create_initial_admin --phone 01000000010 --name 가상최초관리자
```

활성 관리자가 이미 있으면 최초 생성 명령은 거부한다. 공용 운영 계정을 코드에 하드코딩하지 않는다. 생성된 계정은 `role=ADMIN`, `is_superuser=false`, `is_staff=false`다.

로컬 가짜 계정 생성:

```sh
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py seed_demo_customers
```

`ALLOW_DEMO_SEED=true`일 때만 실행된다. 이번 실행용 로컬 DB에는 아래 가짜 계정 3개가 준비되어 있다. seed를 다시 실행해도 기존 계정·변경한 비밀번호를 덮어쓰지 않는다. 이름/역할이 다른 계정과 예제 번호가 충돌하면 중단한다.

| 역할 | 가짜 로그인 전화번호 | 신규 계정 초기 비밀번호 |
|---|---|---|
| 관리자 | `01000000001` | `dodream` |
| 직원 | `01000000002` | `dodream` |
| 직원 | `01000000003` | `dodream` |

`dodream`은 설계서대로 유지한다. 첫 로그인·재설정 후에는 현재 비밀번호를 확인하고 다른 8~128자 비밀번호로 바꿔야 업무 경로를 사용할 수 있다. Django의 유사성·흔한 비밀번호·숫자 전용 검증도 적용한다. 비밀번호 원문은 디비·세션·로그·응답에 저장하지 않는다.

## 3. 새 환경 준비

기본 경로는 Python 3.13.18과 PostgreSQL 17, uv가 준비된 환경에서 다음과 같다.

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --frozen --python /설치된/python3.13
```

이번 Mac의 uv 0.12.21 다운로드 목록에는 3.13.18이 없어 공식 소스로 빌드했다. 같은 방법을 재현하려면 Xcode Command Line Tools, OpenSSL 3, make가 필요하다. 아래는 **새 환경에서만** 사용할 빌드 절차이며 다른 프로젝트 Python을 변경하지 않는다.

```sh
mkdir -p .local/build
curl --fail --location https://www.python.org/ftp/python/3.13.18/Python-3.13.18.tar.xz -o .local/build/Python-3.13.18.tar.xz
shasum -a 256 .local/build/Python-3.13.18.tar.xz
```

공식 SHA-256과 일치해야 다음으로 진행한다:
`abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68`.

```sh
tar -xf .local/build/Python-3.13.18.tar.xz -C .local/build
cd .local/build/Python-3.13.18
./configure --prefix=/Users/hayeon/Documents/TMDB/.local/python-3.13.18 --with-openssl=/opt/homebrew/opt/openssl@3 --with-ensurepip=install
make -j4
make install
cd ../../..
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --frozen --python .local/python-3.13.18/bin/python3.13
```

위 prefix는 이 프로젝트의 현재 절대 경로이므로 다른 컴퓨터에서는 해당 checkout 경로로 바꾼다. 이번 소스 빌드에서 선택 모듈 `_gdbm`, `_lzma`, `_tkinter`는 설치되지 않았으며 현재 앱·psycopg·브라우저 검증에는 사용하지 않는다. SSL과 현재 앱 의존성은 실행 검증했다. 참고: [Python 3.13.18 공식 소스](https://www.python.org/downloads/release/python-31318/).

## 4. Docker Compose 실행 경로 — 엔진 실행 미검증

Docker 엔진이 있는 환경을 위한 구성이다. 현재 컴퓨터에는 엔진이 없어 **이미지 빌드·컨테이너 실행·이미지 레이어 검사는 미실행**이다. 공식 해시를 검증한 Compose 5.7.0 단독 실행 파일을 `.local/bin/docker-compose`에 준비했으며 실제 config 파서로 5개 서비스와 키 전달 범위를 검증했다. 기존 고정 이미지 digest는 유지했다.

현재 컴퓨터에서는 엔진 없이 아래 설정 검사를 실행할 수 있다.

```sh
.local/bin/docker-compose --profile ai --profile proxy config --quiet
```

다음 빌드·실행 명령은 Docker 엔진이 준비된 환경에서만 사용한다. 새 checkout에서는 빈 `.env.ai.example`을 `.env.ai`로 별도 복사하고 0600 권한을 준다. 기존 실제 파일을 덮어쓰지 않는다.

```sh
docker version
docker compose version
docker compose config --quiet
docker compose build
docker compose up -d postgres
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py create_initial_admin
docker compose up -d web scheduler
```

가짜 계정이 필요하면 최초 관리자 명령 대신 `docker compose run --rm web python manage.py seed_demo`를 명시적으로 실행한다. 위 직접 실행 서버가 8000 포트를 사용 중이면 먼저 종료한다. Compose는 호스트 DB와 별도의 영속 볼륨을 사용하며 postgres 포트를 호스트에 공개하지 않는다.

선택 프록시: `docker compose --profile proxy up -d proxy` → `http://127.0.0.1:8080`. 이 프록시는 로컬 HTTP 구성이며 운영 도메인·HTTPS 구성은 후속 운영 단계다. 운영에서는 가짜 secret/DB 비밀번호·DEBUG·개발 권한을 그대로 쓰지 않는다. 유료 신청·운영 배포는 수행하지 않았다.

종료는 `docker compose down`. 데이터 보존을 위해 `down -v`는 일반 종료 절차에 포함하지 않는다.

## 5. 인증 API와 기반 서비스

같은 출처의 Django 세션과 CSRF를 사용한다. 로그인 페이지 GET으로 CSRF 쿠키를 받은 뒤 쓰기 요청은 폼의 `csrfmiddlewaretoken` 또는 `X-CSRFToken`을 보낸다. JSON 로그인 형식은 `{"phone":"01000000001","password":"dodream"}`이다.

| 경로 | 기능 |
|---|---|
| GET/POST `/auth/login` | 한국어 폼 / 세션 로그인 |
| POST `/auth/logout` | 세션 종료. GET은 405 |
| GET/POST `/auth/password` | 현재 비밀번호·새 비밀번호·확인. JSON 키는 `current_password`, `new_password`, `new_password_confirm` |
| GET `/api/me` | 본인 ID·이름·역할·변경필수 여부·설정 버전. 비밀번호 변경 전에도 허용 |
| GET `/api/access/admin` | 관리자 권한 검사 |
| GET `/api/access/employee` | 직원 권한 검사 |
| POST `/api/users/<UUID>/reset-password` | 관리자만 재설정. 비밀번호 원문 반환 없음 |
| GET `/app/admin`, `/app/employee` | 관리자 기본 현장·기본 건수 / 직원 기반 화면 |
| GET `/healthz` | PostgreSQL 연결 확인, 장애 시 503 |

관리자는 초기 비밀번호 변경을 마쳐야 다른 사용자를 재설정할 수 있다. 대상 UUID는 `seed_demo` 출력이나 관리 명령의 생성 결과에서 확인한다. 재설정 UI는 후속 사용자 관리 단계에 연결한다. 재설정은 해당 계정의 모든 기존 세션을 무효화하고 dodream/변경필수 상태로 전환한다. 본인 재설정도 현재 세션을 무효화한다.

본인 비밀번호 변경은 현재 세션만 유지하고 다른 세션은 다음 요청부터 차단한다. 매 요청마다 DB의 활성 상태·`session_version`을 검사한다. 비활성화/역할 변경의 내부 서비스 `apps.accounts.services.set_user_access`도 버전을 증가시킨다. 비활성화 시 미진행 현재 할당만 전 현장·전 날짜에서 회수하며 진행 DB·상담정보를 유지한다. 이 서비스의 관리 UI/API는 후속 단계다. 마지막 활성 관리자 제거는 동시 요청에서도 막는다.

로그인 실패 기본값은 계정별 15분 5회, 요청 출처별 15분 30회다. IP 허용/차단 기능이 아니라 실패 빈도 제한이다. DB에는 전화번호/IP 원문 대신 HMAC 키만 남기며 창이 지난 기록은 다음 로그인 시 정리한다. 잠금 대기는 기본 5초, 잠금/데드락/직렬화 실패 재시도는 1회 후 503으로 안내한다. 환경변수로 조절한다.

## 6. 테스트

프로젝트 로컬 DB가 실행 중이어야 한다. 테스트는 별도 `test_tm_dev`를 생성·삭제하며 `tm_dev`의 가짜 계정 비밀번호를 변경하지 않는다. 기존 업무 DB를 테스트 대상으로 지정하지 않는다.

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test tests --noinput -v 2
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" .venv/bin/python -m playwright install chromium
.venv/bin/python manage.py test tests.browser_flow --noinput -v 2
.venv/bin/python manage.py test tests.browser_p2 --noinput -v 2
.venv/bin/python manage.py test tests.browser_imports --noinput -v 2
.venv/bin/python manage.py test tests.performance_imports --noinput -v 2
.venv/bin/python manage.py test tests.browser_p4 tests.performance_assignments --noinput -v 2
.venv/bin/python manage.py test tests.browser_employee --noinput -v 2
.venv/bin/python manage.py test tests.test_p6 tests.browser_p6 tests.performance_scheduler --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
```

2026-11-05 P8 최종 검증의 명령·수치·로그는 [P8 검증 기록](docs/P8_VERIFICATION.md)에 있다. 기존 P1~P7 전체 테스트도 현재 코드에서 다시 실행했다. 대부분의 인증/모델 테스트는 테스트 전용 MD5로 빠르게 실행하고, 실제 기본 PBKDF2 검사·브라우저 흐름·복원 계정은 런타임 해시를 사용한다. 운영 해시는 낮추지 않았다. `manage.py test`는 전용 `config.test_settings`와 별도 PG 테스트 DB를 사용한다. Node 검증은 Node22의 기본 test runner를 쓰며 npm 설치가 필요 없다. 전체 실행과69항목 근거 생성은 아래16절을 따른다.

설계서 v2.0의 **전체 92개 인수 항목 완료를 뜻하지 않는다**. 현재 범위·제한은 [P8 검증 기록](docs/P8_VERIFICATION.md)과 [진행 기록](docs/PROGRESS.md)에 있다. VERIFICATION_STAGE2.md는 이전 v1 실행 이력이다.

## 7. 구조와 후속 경계

`apps/accounts`, `sites`, `customers`, `assignments`, `callbacks`, `imports`, `operations`, `consultations`, `ai_assistant`로 나누었다. 순환 FK는 분리한 migration으로 적용한다. 스키마·잠금·후속 계약은 [기반 구조](docs/FOUNDATION.md)를 참조한다.

예약 프로세스 진입점 `python manage.py run_scheduler --once`는 KST23시/누락 회수·만료 업로드·일반 요청 결과 정리를 수행한다. 앱과 scheduler는 Compose에서 같은 이미지를 사용한다. 실제 컨테이너 실행은 엔진 부재로 미검증이다.

## 8. AI 설정과 보호 경계

로컬 `.env.ai`는 빈 키·AI_ENABLED=false로 준비했다. 실제 키는 필요 없다. 키·모델·단가를 채워도 P1에는 실제 provider 전송 기능이 없다. 새 checkout에서 파일이 없을 때만 복사한다.

```sh
cp -n .env.ai.example .env.ai
chmod 600 .env.ai
git check-ignore -v -- .env.ai
git ls-files --error-unmatch -- .env.ai
```

마지막 명령은 비추적이므로 종료 코드 1이 정상이다. `git check-ignore -- .env.ai.example`도 비제외이므로 종료 코드 1이어야 한다. 실제 키·파일 내용을 출력하거나 Git에 추가하지 않는다.

web/AI worker만 명시적으로 `.env.ai`를 읽는다. 프로세스 환경변수 우선·파일 누락값 보완, AI_ENV_FILE 외부 경로·0600 검사·미설정 fallback을 적용한다. 일반 `.env`로 AI 값을 로딩하지 않으며 일반 관리/scheduler/test 진입점은 상속된 AI 환경을 제거한다. Compose도 web/AI worker에만 AI env_file을 전달한다.

`/api/ai/availability`는 로그인·최초 변경 후 조회 가능하다. P9부터 직원 자신의 KST 오늘 DB bucket의 성공/예약/남은 횟수를 반환한다. 기록이 없으면0/0/30이며 관리자 직원 quota 값은 null이다. 생성 가능은 계속 false다. 실제 생성 버튼과 기능별 결과/선택 적용은 P10 이후다.

fake는 전용 TESTING 설정과 `test_tm_` 접두어 DB에서만 실행하고 is_test=true를 반환한다. 일반/운영 로더의 AI_PROVIDER=fake는 거부한다. DEBUG=true만으로 테스트 환경이 되지 않는다. 테스트는 네트워크 차단 상태에서 가짜 응답을 확인한다.

Git 제외·0600·프로세스 분리·repr/응답/정적 코드/앱 및 Django 로그·traceback 마스킹은 비밀이 아닌 임시 sentinel로 검증했다. Docker 이미지의 각 레이어 검사는 엔진 부재로 미실행이다.

## 9. 직접 확인하는 순서

1. 1절의 DB·migration·collectstatic·Gunicorn 명령으로 실행하고 로그인 주소를 연다.
2. 신규 가짜 관리자 `01000000001 / dodream`으로 로그인한다. 처음에는 비밀번호 변경 화면이 열린다.
3. 현재 dodream과 새 8~128자 비밀번호를 입력한다. 관리자 화면과 `/api/access/admin`의 200 응답을 확인한다.
4. 로그아웃하고 신규 가짜 직원 `01000000002 / dodream`으로 최초 변경을 수행한다. 직원 화면은 열리고 `/api/access/admin`은 403이어야 한다.
5. `/api/ai/availability`에서 generation_available=false를 확인한다. 생성 버튼·가짜 운영 결과는 제공하지 않는다.
6. 비밀번호 변경·재설정과 다른 세션 무효화는 테스트 명령으로 검증할 수 있다. 재설정 API는 5절, 사용자 관리 UI는 후속 단계다.
7. 관리자 상단 **DB 관리**에서 가짜 고객 65건을 확인한다. 없으면 서버와 별도 터미널에서 `seed_demo_customers`를 실행한다. 셀을 더블클릭해 상담내용을 바꾼 뒤 저장 전후를 비교한다. 이름·연락처는 편집되지 않아야 한다.
8. 열 제목 ▾ 필터·50/100행·이전/다음·검색을 확인한다. 편집 후 이동하면 저장/머무르기/변경 폐기 선택이 나온다. 저장 실패 시 해당 페이지에 남는다.
9. 고객을 체크하고 선택 휴지통 이동 → 삭제 확인 → 휴지통 메뉴 → 선택 복구를 확인한다. 상담정보는 유지되고 담당자는 미할당이다.
10. 현장을 추가하면 그 현장을 연다. 대시보드에서 현장만 선택하면 건수만 바뀌고 **기본 현장 설정**을 눌러야 전역 기본값이 바뀐다. 이미 열린 탭은 유지되며 새 화면/새로고침부터 기본값을 사용한다.

사용자가 이미 비밀번호를 변경했다면 본인이 바꾼 값을 사용한다. 브라우저 테스트는 별도 DB를 쓰므로 개발 계정의 비밀번호를 변경하지 않으며 seed_demo 재실행도 기존 값을 초기화하지 않는다.

## 10. P2 업무 API와 경계

| 경로 | 기능 |
|---|---|
| GET/POST `/api/sites` | 로그인 사용자 현장 목록 / 관리자 생성 |
| PATCH `/api/settings/default-site` | 관리자, site_id·expected_version으로 설정 |
| GET `/api/sites/<UUID>/counts` | 관리자 선택 현장 전체/미할당/휴지통 건수 |
| GET `/api/customers` | 권한 범위의 서버 검색·열 필터·정렬·50/100행 페이지 |
| GET `/api/customers/filter-options` | 현재 권한/현장/다른 열 조건 내 후보값, 100개씩 |
| POST `/api/customers/batch-update` | 최대 100행, 행별 원자적 저장·충돌/실패 결과 |
| POST `/api/customers/soft-delete`, `/restore` | 관리자, 현재 페이지 선택 최대 100건과 작업 키 |
| GET `/app/admin/customers`, `/app/admin/trash` | 관리자 DB 관리 / 읽기 전용 휴지통·복구 |

상담 저장 예시: `{"rows":[{"customer_id":"UUID","assignment_id":null,"mutation_id":"새 UUID","expected_version":1,"changes":{"notes":"가짜 메모"}}]}`. 직원은 현재 assignment_id가 필수이고 본인 현재 담당만 가능하다. 관리자는 조회 때 받은 assignment_id 또는 null을 보낸다. 변경 허용 필드는 call_result·visit_at·contract_status·notes·callback_due_at·housing_status다. 날짜는 ISO 일시이며 시간대 생략 시 한국 시각으로 해석한다.

동일 mutation_id 재시도는 같은 본문으로 보낸다. 응답 유실 행은 편집을 잠그고 같은 요청으로 재시도한다. 충돌은 서버값과 비교한 뒤 새 버전·새 mutation_id로 명시적으로 다시 적용한다. 이 관리자 대기값은 메모리에만 있으며, 직원의 IndexedDB/100초 자동 저장은 P5에서 구현한다.

설계서의 확정 업무 규칙은 유지했다. P2의 후보 100개 페이지·열당 선택/제외 1,000개 한도 등 구현 기본값은 [검증 기록](docs/P2_VERIFICATION.md)에 구분했다.

## 11. P3 엑셀 업로드

관리자 **DB 관리 → 엑셀 업로드** 또는 `/app/admin/imports`에서 사용한다. 직원·최초 비밀번호 미변경 계정은 다운로드·검증·결과·확정 API 모두 접근할 수 없다.

1. **빈 입력 양식 다운로드** 후 첫 시트의 9개 헤더 이름/순서를 유지한다. 고객 데이터 내보내기는 제공하지 않는다.
2. 담당직원명은 비우고 고객명·문자열 연락처를 입력한다. 통화결과/계약은 한글 허용값, 날짜는 `YYYY-MM-DD HH:mm` 또는 날짜·시각 서식의 Excel datetime을 사용한다. 날짜만 있거나 0이 빠진 숫자 연락처는 오류다.
3. 현장·파일 선택 → **파일 검증**. 아직 고객을 생성하지 않는다. 등록 가능·파일 중복·휴지통 포함 기존 중복·형식 오류를 보여준다.
4. **업로드 확정 → 등록 확정**. 같은 현장의 현재 중복을 다시 검사하고 정상 행만 미할당으로 등록한다. 재콜과 IMPORT 상담 이력도 함께 생성하며 직원 진행 이력은 만들지 않는다.
5. 실패 목록은 원본 Excel 행 번호·고객명·마스킹하지 않은 관리자용 연락처·코드·사유를 100행씩 보여준다. 현재 `?batch_id=...` 주소로 원본 파일 없이 다시 확인한다.

가짜 검수 파일은 `.local/qa/p3_demo_upload.xlsx`다. 다른 개발 고객과 겹치지 않는 새 현장에서 검증하면 총4건·등록 가능2·파일 내 중복1·형식 오류1이다. 재업로드하면 이미 등록된 연락처는 중복으로 실패하며 상담정보를 덮어쓰지 않는다. `.local/qa/TM_customer_template.xlsx`는 브라우저에서 실제 다운로드한 빈 양식이다. 두 파일 모두 로컬 검수용이며 Git/Docker에 포함되지 않는다.

| API | 동작 |
|---|---|
| GET `/api/imports/template` | 관리자 빈 xlsx 양식 |
| POST `/api/imports/validate` | multipart의 site_id + file 하나, 최대10MiB/10,000데이터 행 |
| GET `/api/imports/<UUID>?page=1&kind=failed` | 결과 집계와 행 페이지. kind=failed/ready/all |
| POST `/api/imports/<UUID>/commit` | JSON `{"site_id":"UUID","idempotency_key":"새 UUID"}` |

응답이 유실되면 같은 확정 키·본문으로 재시도한다. 같은 batch는 다른 키로 다시 요청해도 고객이 추가 생성되지 않는다. 성공 replay는 최초 접수 기준 최소7일(검증 만료+7일 상한) 보관하며, 검증 만료 이후 새 키 확정은 거부한다. 잠금/연결 등 일시 오류는503·재시도 가능, 치명 DB 오류는 고객·재콜·revision 전체 롤백 후 **FAILED**로 기록하고 재업로드를 요구한다. FAILED의 동일 키는 같은 실패 결과를 반환한다.

원본은 검증 후 닫아 삭제하고, 유효 후보는 확정/FAILED 즉시 제거한다. 행별 원문은 검증 후24시간, 집계 metadata는 그 뒤7일까지 보관한다. 조회는24시간 경계부터 원문을 숨기며 실제 삭제는 scheduler/정리 명령이 수행한다. 메타데이터 삭제는 이미 등록한 고객·상담 이력을 삭제하지 않는다.

추가 기술 한도와 실패/보관 정책은 [P3 검증 기록](docs/P3_VERIFICATION.md)에 구분했다.

## 12. P4 분배·회수·담당자·사용자 관리

관리자 메뉴 **DB 분배·회수**에서 현장→확인→직원/전체 팀원→직원당 수량→분배 순으로 실행한다. 현장을 바꾸면 확인·잔여 수·수량을 초기화한다. 실행 시 활성 직원과 미삭제·미할당 고객을 다시 확인하고 PostgreSQL에서 균등 랜덤 추출한다. 부족하면0건 처리하고 가능한 직원당 수량을 안내한다. 직원4명·잔여95·각30 요청은 **23개씩 가능**, 배정0건이다.

**오늘 할당 회수**는 확인 모달 뒤 실행하며, 선택 현장·실행 시점 활성 직원·오늘 현재 할당 전체를 회수한다. 진행 건도 포함하고 과거 할당은 제외한다. 실제 대상/건수는 다시 계산한다. 상담정보·재콜·기존 진행 이력·삭제 요청은 유지한다.

DB 관리의 담당직원 셀 **담당 변경**은 상담 저장과 별도다. 미저장 상담이 있으면 먼저 저장/머무르기/폐기를 선택한다. 같은 직원은 no-op, 다른 활성 직원은 새 assignment_id·현재 할당 시각·미진행으로 시작하고, 미할당 선택은 날짜와 무관하게 해당 건을 회수한다. 비활성/관리자로 바뀐 기존 담당은 그대로 표시하지만 신규 배정 목록에서 제외한다. 할당일은 MM/DD, 전체 한국 시각은 툴팁이다.

**사용자 관리**에서 이름·전화번호·비활성화·관리자 여부를 편집하고 저장→`수정을 반영하시겠습니까?`로 확정한다. 한 번의 변경은 전부 저장하거나 전부 취소한다. 중복 번호·낡은 버전·마지막 활성 관리자 제거는 거부한다. 전화번호 맞교환은 기존 번호를 먼저 변경한 뒤 수행한다. 이름만 변경하면 세션을 유지하고, 전화번호·역할·활성 상태 변경은 해당 사용자의 기존 세션을 무효화한다.

비활성화는 모든 현장/날짜의 미진행 현재 할당만 회수하며, 진행 건은 아래 **이관 필요 목록**에 남는다. 링크로 정확한 현장/담당자 조건의 DB 관리를 열어 이관·회수한다. 재활성화해도 자동 재배정하지 않는다. 직원→관리자 전환은 기존 담당 DB/재콜을 유지한다.

사용자 추가는 활성·초기 dodream·최초 변경필수이며 비밀번호를 응답/화면에 반환하지 않는다. 재설정도 기존 세션을 종료하고 최초 변경을 요구한다. 본인 권한/전화번호 변경·본인 재설정 후에는 다시 로그인한다. 사용자를 삭제하는 기능은 없다.

| API | 계약 |
|---|---|
| GET `/api/assignments/availability?site_id=UUID` | 관리자 참고 잔여 수·활성 직원 |
| POST `/api/assignments/distribute` | site_id·employee_id(all 또는 UUID)·quantity(직원당 양의 정수)·idempotency_key |
| POST `/api/assignments/recall-preview` | site_id·employee_id, 오늘 현재 대상 수 |
| POST `/api/assignments/recall` | site_id·employee_id·idempotency_key |
| POST `/api/customers/<UUID>/assignee` | site_id·employee_id(UUID 또는 null)·assignment_id(UUID 또는 null)·expected_version·idempotency_key |
| GET/POST `/api/users` | 관리자50명 페이지/검색 / name·phone·role·idempotency_key 생성 |
| POST `/api/users/batch-update` | rows1~100·idempotency_key. 각 행 id/name/phone/role/is_active/expected_version |
| GET `/api/users/transfer-needed` | 전체 현장의 비활성 보유 진행 DB,50건 페이지 |
| POST `/api/users/<UUID>/reset-password` | 새 UI는 idempotency_key를 보냄. 기존 빈 요청도 호환 |

사용자 expected_version은 GET에서 받은 수정 시각 문자열, 고객 expected_version은 정수 버전이다. 임의 비밀번호/is_superuser/is_staff 필드를 받지 않는다. 일반 고객 저장 API는 계속 이름·번호·담당자 수정을 거부한다.

분배·회수·담당자 변경·재설정의 응답 미확인은 계정별 sessionStorage에 **요청 ID·대상 ID·버전·수량·접수 시각만** 보관하고 새로고침 후 동일 요청 확인을 제공한다.7일이 지난 대기 요청은 재전송을 차단하고 현재 상태 확인·명시적 폐기를 요구한다. 자동 재전송하지 않으며 대기 정보 폐기는 이미 서버에서 끝난 작업을 되돌리지 않는다. 직원 IndexedDB 지속 대기열은 아래 P5 기능이다. 사용자 편집 대기값은 메모리이며 닫기 경고를 제공한다. P4 요청 결과는7일 뒤 조회 차단·scheduler로 정리한다.

## 13. P5 직원 화면·자동 저장 확인

1. 위 실행 명령으로 DB와 앱을 시작한다. 관리자 로그인 후 **DB 분배·회수**에서 가짜 고객 일부를 가짜 직원에게 분배한다. 기존 DB는 사용자3명·고객65건·할당0건을 보존했으므로 분배 전 직원 표는 비어 있다.
2. 직원 `01000000002` 또는 `01000000003`으로 로그인한다. 아직 초기 비밀번호인 계정은 `dodream`으로 로그인한 뒤 최초 변경을 완료한다. 이전에 변경한 비밀번호는 그대로 유지했다.
3. **오늘 할 일**(`/app/employee/today`) 또는 **나의 DB**(`/app/employee/mine`)에서 현장을 선택한다. 상담 셀 더블클릭 → 내용 편집 → 약90초 대기 또는 **지금 저장**을 누른다. 같은 셀의 추가 입력으로 최초 전송 시점을 연장하지 않는다. 고객명·연락처·담당자·할당일은 수정할 수 없다.
4. 개발자 도구 Network를 Offline으로 전환해 편집하면 오프라인 대기와 저장 대기 패널이 표시된다. 이 상태의 메뉴 이동·로그아웃은 저장 재시도/취소/명시적 폐기 선택을 요구한다. Online 복구 후 기한이 지난 대기값은 서버 확인을 거쳐 바로 전송한다.
5. 저장 대기 중 새로고침·브라우저 재시작 후 같은 계정으로 로그인하면 현재 권한·할당·버전을 확인해 복구한다. 다른 계정에서는 대기값을 표시·전송하지 않는다. 브라우저의 사이트 데이터 삭제는 대기값을 지우므로 저장 확인 전에는 실행하지 않는다.
6. 두 탭에서 같은 고객을 편집하고 차례로 저장하면 뒤의 탭은 충돌을 표시한다. **비교·확인**에서 서버 값과 내 값을 확인한 뒤 다시 적용·저장 또는 폐기를 선택한다. 회수·동일 직원 재배정 후에는 이전 할당 대기값을 재적용할 수 없다.

최신 Chrome/Edge의 IndexedDB·Web Crypto·Web Locks를 기준으로 구현했고 실제 검증은 Chromium에서 수행했다. localhost HTTP는 로컬 테스트용이며 운영 HTTPS 설정은 P12에서 검증한다. 계정별 암호화 키는 실행 중 메모리에만 있고 `.env.ai`나 AI API 키와 관계가 없다. 대기열에는 전체 고객 DB·비밀번호·세션 토큰을 저장하지 않는다. 앱이 닫힌 동안에는 전송하지 않으며, 미리 기록을 완료한 대기값을 다음 로그인 때 복구한다.

조회·무변경·저장 전 원복은 진행 이력을 만들지 않는다. 실제 커밋만 고객 버전·최초 진행·상담 revision을 원자적으로 갱신한다. 재콜 완료/취소 이력·상세 통계·23시 자동 회수는 아래 P6에 포함하며 삭제 요청/승인은 P7, AI 버튼은 P10 이후다.

직접 확인은 기존 가짜 고객을 사용하거나 P3 가짜 파일로 새 현장을 준비한다. 확인→직원당 소량 분배→DB 관리 담당/할당일 확인→상담 저장→오늘 할당 회수·상담 보존을 확인한다. 비활성화·권한/전화 변경은 그 가짜 계정의 세션을 종료하므로 기존 비밀번호/계정을 임의 초기화하지 않는다.

P7 삭제 요청·승인·영구 삭제는 아래15절, P8 통합 검수는16절, P9 공통 기반은17절을 따른다. 다음 단계는 **P10 직원 AI 3종**이며 이번 요청에서는 시작하지 않는다. Docker 실행·운영 배포·유료 API 호출은 수행하지 않았다.

## 14. P6 재콜·통계·23시 예약 확인

1. 서버 실행 후 관리자 대시보드에서 현장을 바꾸면 해당 현장 통계를 조회한다. **기본 현장 설정**을 누르기 전에는 전역 설정을 바꾸지 않는다. 고유 고객 수와 할당 작업 횟수, 현재 보유·오늘 할당 중 현재 보유·회수/이관/삭제 수, 미진행 두 집합을 따로 표시한다. 자동 폴링은 없고 **통계 새로고침**으로 다시 조회한다.
2. 관리자에게 가짜 고객을 분배받은 직원은 대시보드에서 자신의 오늘 고유 할당·오늘/과거 미완료 재콜·기한 경과·신규 할당 현재 보유 수를 확인한다. 직원은 다른 직원의 상세 통계를 조회할 수 없다.
3. 직원 표의 재콜일정에 날짜를 저장하고 **재콜 완료**를 누른다. 해당 행의 미저장 상담을 먼저 저장하며 다른 행의 대기 시간은 유지한다. 완료 후 재콜 셀이 비고 이력에 완료 시각/처리자가 남는다. **오늘 할당된 고객은 오늘 할 일에 계속 남는다**. 과거 할당이고 다른 오늘 조건이 없으면 목록에서 빠진다.
4. **상담·재콜 이력**에서 재콜의 미완료/완료/취소 및 상담의 변경 전·후 값을 확인한다. 날짜를 비워 저장하면 취소 이력이 남는다. 관리자 DB 관리·휴지통에서도 이력을 조회할 수 있다. 완료 응답을 못 받으면 상단 **재콜 완료 결과 다시 확인**을 사용한다. 새 일정이 생겨도 이전 완료 요청은 새 일정을 건드리지 않는다.
5. scheduler는 한국 시간23시 cutoff의 기본 현장과 그날00:00~23:00 현재 할당 중 `first_activity_at`이 없는 고객만 회수한다. 통화결과·기존 메모·재콜의 빈 값 여부로 판단하지 않는다. 새 할당·저장된 진행은 지연 실행에서도 유지한다. 직원 활성 화면은22:59:30 전후 편집 확정·즉시 전송을 시도한다. 오프라인 성공을 보장하는 것은 아니다.

`.env`의 `SCHEDULER_START_DATE`가 비어 있으면 **처음 예약 프로세스를 실행한 한국 날짜**를 DB에 보존한다. 이후 재시작에서도 그 날짜부터 누락 작업을 확인한다. 더 이른 운영 시작일이 필요하면 최초 실행 전에 `YYYY-MM-DD`를 지정한다. 이미 보존한 날짜를 환경변수 변경만으로 덮어쓰지 않는다. 미래 시작일은 거부한다. 최초 시작일 전의 과거 회수를 임의 생성하지 않는다.

기본120초 lease·DB token으로 중단 작업을 회복한다. 자동 시도는 날짜별 최대5회, 실패 후60/120/240/480초 등의 지연이며1시간을 상한으로 둔다. 한 tick에서 최대31개 작업을 준비/처리한다. 상한에 도달한 FAILED 작업은 운영자가 원인을 확인한 후 해당 날짜를 명시해 한 번 재시도할 수 있다. 아래 날짜는 실제 기존 실패 작업 날짜로 바꾼다.

```sh
.venv/bin/python manage.py run_scheduler --once
.venv/bin/python manage.py run_scheduler --once --retry-date YYYY-MM-DD
```

재시도는 기존 cutoff·대상 현장을 유지하고 누적 시도 횟수를 지우지 않는다. 살아 있는 lease나 완료 작업을 중복 실행하지 않는다. 단발 명령은 미해결 FAILED 작업이 있으면 성공 종료로 보고하지 않는다. 상태 확인은 읽기 전용 명령으로 할 수 있다.

```sh
.venv/bin/python manage.py shell -c 'from apps.operations.models import ScheduledJobRun; print(list(ScheduledJobRun.objects.order_by("-business_date").values("business_date","cutoff","target_site_id_snapshot","status","attempt_count","lease_expires_at","affected_count","last_error_code")[:31]))'
```

현재 로컬 예약 시작일은 `2026-11-05`다. 실제 가짜 DB는 사용자3명·고객65건·현재 할당0건을 보존했으며 과거 날짜를 강제로 회수하지 않았다.23시 동작·실제 프로세스 중단/재시작·1만 건 성능은 별도 테스트 DB에서 검증했다. 실행 기록과 구현 기본값은 [P6 검증 기록](docs/P6_VERIFICATION.md)을 따른다.

## 15. P7 삭제 요청·승인·영구 삭제 확인

1. 1절의 DB start → migrate → collectstatic → Gunicorn 순서로 실행하고 http://127.0.0.1:8000/auth/login 에 접속한다. 2절의 가짜 관리자/직원 계정을 사용한다. 최초 비밀번호 변경을 완료한 뒤 관리자가 가짜 고객 일부를 직원에게 분배한다. 기존 계정 비밀번호는 보존했다.
2. 직원 **오늘 할 일/나의 DB**에서 상담을 편집한 후 해당 행의 **삭제 요청**을 누른다. 그 행만 먼저 저장하고 확인창을 표시한다. 취소하거나 저장이 실패하면 요청하지 않는다. 성공하면 **요청완료**가 표시되고 새로고침·다른 탭에서도 유지된다. 요청만으로 고객을 삭제하거나 담당자를 해제하지 않으며 승인 전 상담 편집을 계속할 수 있다.
3. 관리자 대시보드 상단 **고객정보 삭제 요청**에서 전체 현장의 요청을 확인한다. 선택 현장과 관계없이 동일 목록이며 승인 버튼의 확인창에서 확정한다. 최신 상담기타내용 끝에 `[YYYY-MM-DD HH:mm] 고객요청으로 인한 삭제`가 한국 승인 시각으로 한 번만 추가되고 휴지통으로 이동한다. 일반 휴지통 이동은 이 문구를 추가하지 않고 대기 요청을 닫는다.
4. 승인 후 직원의 이전 대기 저장은 거부되고 성공으로 표시되지 않는다. 차단된 대기값은 저장 대기 패널에서 확인·명시적으로 폐기한다. 복구는 미할당이며 이전 승인을 다시 실행해도 재삭제되지 않는다. 새로 분배받은 직원은 필요한 경우 새 삭제 요청을 할 수 있다.
5. 관리자 **휴지통**의 행별 **영구 삭제**에서 가짜 고객 한 건을 확인 후 삭제한다. 고객·상담/할당/재콜 이력·관련 요청/알림·대상 원문이 든 서버 요청 결과와 업로드 캐시가 제거된다. 같은 현장·연락처를 나중에 등록하면 새 UUID가 된다. 체크박스 일괄 영구 삭제는 제공하지 않는다.
6. 관리자 **DB 관리 → 현장 영구 삭제**는 현장명을 정확히 입력하고 **영구 삭제 확인**으로 실행한다. 해당 현장과 고객·관련 자료를 삭제한다. 기본 현장이면 가장 먼저 생성된 남은 현장으로 바꾸고, 마지막 현장이면 기본 현장을 비운다. 화면 URL도 대체 현장으로 바꿔 새로고침 시 삭제된 현장을 다시 선택하지 않는다.
7. 응답을 확인하지 못하면 상단의 **같은 요청 결과 다시 확인**을 사용한다. 새로고침 뒤에도 같은 키·본문으로 확인하며 자동으로 새 요청을 만들지 않는다. 대기 정보 폐기는 이미 완료된 서버 작업을 되돌리지 않는다. 현장명 입력은 확인 직후 비우며 재시도 정보에 원문 이름을 저장하지 않는다.

영구 삭제는 앱에서 복구할 수 없다. 기존 백업의 만료·보관 정책과 실제 복원 검증은 후속 운영 단계다. 서버가 연결되지 않은 브라우저의 암호화 미전송 입력을 원격으로 지울 수는 없으며, 해당 입력의 재전송은 현재 할당/삭제 검사로 거부한다. 원문을 새 고객으로 자동 재등록하지 않는다.

P7의 삭제·승인·1만 건 성능 검사는 별도 `test_tm_dev`의 가짜 자료에서 수행했다. 개발 DB의 사용자3명·고객65건·현재 할당0건은 유지했다. 알림만 활성 대시보드에서60초 단위로 조회하고 통계는 자동 폴링하지 않는다. P9에서 실제 AI 모델의 queued 입력·결과·전이 참조를 재귀 무효화/원문 제거하도록 연결했다. 추가 미처리 모델이 생기면 삭제를 차단하는 가드도 유지한다.

검증 명령·18.7 항목별 근거는 [P7 검증 기록](docs/P7_VERIFICATION.md)을 따른다. P8 통합 검수는 아래16절을 따른다.

## 16. P8 기본 업무 통합 검수

아래 명령은 기존 PostgreSQL 개발 DB와 분리한 `test_tm_dev`를 생성·삭제한다. Chromium은 이미 설치되어 있다. 다른 환경에서만6절의 브라우저 설치 명령을 먼저 실행한다. 복원 검사는 같은 로컬 클러스터에 고유한 `test_tm_p8_restore_...` 임시 DB를 만들므로 테스트 계정에 DB 생성 권한이 필요하다. PostgreSQL17의 pg_dump/pg_restore 기본 경로는 `/opt/homebrew/opt/postgresql@17/bin`이고 다른 위치는 `TM_PG_BIN`으로 지정한다.

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions --testrunner=config.acceptance_runner.AcceptanceRunner --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_acceptance.py
```

`AcceptanceRunner`는 실제 Django 개별 결과와 소스 해시를 `.local/p8-test-results.json`에 남긴다. 마지막 명령은 원본69문항·테스트 ID·미실행/skip/실패·소스 변경을 확인한 뒤 [69항목 결과표](docs/P8_ACCEPTANCE.md)를 생성한다. 일부 테스트만 실행한 보고서로69항목 전체 통과를 표시할 수 없다. 다른 테스트가 실패하면 문항 근거가 통과했더라도 전체 검수 명령은 실패 종료한다. 소스나 검수 매핑을 바꾸면 전체 검사부터 다시 실행한다. 기존 결과표를 열어보는 것과 새 검사를 실행하는 것은 구분한다.

AI 키 없음·단가 오류·파일 권한 오류·fake 공급자 거부의 네 경우에 엑셀 등록→분배→직원 저장→재콜 완료→삭제 요청/승인→복구→영구 삭제가 정상 동작했다. 실제 외부 AI 전송과 fake adapter 실행을 막은 상태로 검사했다. 독립 Gunicorn도 키 파일 누락/설정 오류 각각 정상 기동했고 로그인200·DB health200·익명 업무401을 확인했다. 실제 `.env.ai`는 변경하지 않았다.

복원 테스트는 가짜 자료를0600 임시 dump로 저장하고 **같은 PostgreSQL 클러스터의 별도 빈 DB**에 실제 복원한다.27개 public 테이블의 모든 행 값 해시·행수와 계정 비밀번호·할당 연결을 비교하고, 복원 DB만 변경해 원본이 유지되는지도 확인한다. 임시 DB와 dump는 종료 시 제거하며 `.local/p8-restore.json`에는 원문 대신 건수·해시·검증 결과만 남긴다. 이 검사는 운영 백업 자동화·암호화·외부 보관·7일 보존 정책의 완료를 뜻하지 않는다.

직접 화면을 확인하려면1·2절대로 서버 실행/가짜 계정 로그인 후11절 업로드→12절 소량 분배→13절 직원 편집/저장→14절 재콜 완료→15절 삭제 요청/승인을 확인한다. 최초 비밀번호 변경을 요구하면 완료하고, 기존에 바꾼 비밀번호는 그대로 사용한다. 현재 개발 데이터 사용자3명·고객65건·할당0건을 보존했으므로 먼저 분배해야 직원 표에 고객이 보인다.

P9 공통 기반은 아래17절을 따른다. 직원 생성/추천 적용과 브리핑/코칭/가이드 기능별 UI·분석은 P10/P11이다. Docker 실행/레이어·운영 백업/HTTPS·20명 동시 SLA도 후속 검증이다. 유료 API·유료 자원·운영 배포는 수행하지 않았다.

## 17. P9 AI 공통 기반 확인

기본 앱은1절 순서로 실행한다. 기존 개발 자료/계정은 그대로 사용한다. DB worker는 별도 터미널에서 다음 명령으로 실행할 수 있다. 현재 실제 공급자 전송은 연결하지 않았고 새 생성 POST/버튼도 아직 없으므로 일반 로컬 실행에서는 AI 작업0건이다. 키를 넣어도 유료 호출을 시작하지 않는다.

```sh
.venv/bin/python manage.py run_ai_worker --once
.venv/bin/python manage.py run_ai_worker
```

두 번째 명령은2초마다 이미 접수된 DB 작업을 확인한다. Ctrl+C/SIGTERM으로 정상 종료한다. scheduler도 만료된 AI 작업 정리만 수행하며 새 AI 작업을 만들지 않는다. fake 실행은 코드의 TESTING=true·AI_FOUNDATION_TEST_MODE=true·test_tm_ DB를 모두 확인하고 API/환경변수로 활성화할 수 없다. 전용 테스트에서만 생성되며 결과에는 항상 테스트 표시가 붙는다.

| API | 현재 제공 범위 |
|---|---|
| GET `/api/ai/availability` | 역할별 기능·직원 자신의 KST 오늘 성공/예약/잔여·다음 날짜. 생성 가능 false |
| GET `/api/ai/tasks/<UUID>` | 현재 권한을 검사한 작업 상태, 원문/키 노출 없음 |
| GET `/api/ai/results/<UUID>` | 접근 가능한 결과·테스트 표시·오래된 버전 표시. GET은 새 호출 없음 |
| GET `/api/ai/usage?month=YYYY-MM-01` | 관리자 기능별 성공/실패/취소/미확인·시도/토큰·예약/정산 USD |
| GET/POST `/api/sites/<UUID>/knowledge` | 관리자 현장 안내자료100개 페이지·등록 |
| PATCH `/api/sites/<UUID>/knowledge/<UUID>` | 관리자 버전 검사·수정/검토본 지정, 관련 결과 무효화 |

안내자료 POST는 `title`, `body`, `reviewed`, `is_valid`를 받으며 PATCH에는 `expected_version`도 필요하다. 유효 자료는 같은 관리 요청에서 검토해야 한다. 내용을 수정한 뒤 검토하지 않으면 reviewed=false/is_valid=false로 저장한다. 직원에게는 안내자료 관리 API를 공개하지 않는다. 실제 팀 가이드 생성/게시 화면은 P11에 구현한다.

내부 예약 서비스는 직원 기능 합산 성공+예약≤30, 계정 처리 중1개, 전역 RUNNING/UNKNOWN2개를 적용한다. 접수 KST 날짜/월을 고정하고 월 USD5 기본 예산에서 입력 상한과 출력/추론 상한 비용을 먼저 예약한다. 성공만 사용자 횟수로 전환하고 과금된 실패 비용도 보존한다. 모델 미선정 상태의 테스트 단가는 비용 로직 검증용이며 실제 공급자 가격/과금 방식은 아직 검증하지 않았다.

전송 미수행이 확실한 오류만 같은 작업에서1회 재시도한다. 불명확한 응답은 UNKNOWN으로 두고 자동 재호출하지 않는다. 시작 후10분이 지나면 횟수 예약을 반환하고 보수적 비용을 유지한다. 종료된 작업의 늦은 응답은 성공/적용으로 바꾸지 않는다. 원본 영구 삭제는 입력/응답/캐시·연관 보고서/코칭을 재귀적으로 지우고 게시를 해제하며 이미 성공한 quota/slot·발생 비용은 되돌리지 않는다.

```sh
.venv/bin/python manage.py test tests.test_p9 --noinput -v 2
```

위 검사는 별도 가짜 테스트 DB에서 예약·작업·결과·삭제를 실제 실행한다. 실제 worker 강제 중단/재시작과 독립 PG 연결의 동시 경합도 포함한다. 전체 회귀와 기본69항목 재검수 명령·제한은 [P9 검증 기록](docs/P9_VERIFICATION.md)을 따른다. 다음 P10은 직원 버튼·행 저장 선행·기능별 schema/결과·선택 적용 UI다. 이번에는 시작하지 않는다.
