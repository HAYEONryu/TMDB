# TM 고객관리

한국어 TM 고객관리 서비스. 현재 **2단계: 프로젝트·디비·로그인 기반**까지 구현했다.

Python 3.13.18 / Django 5.2.18 / PostgreSQL 17.11 / Django Templates / Bootstrap 5.3.8을 사용한다. 의존성은 `uv.lock`, 컨테이너 설치용 해시 잠금은 `requirements.lock`에 있다.

고객 그리드·엑셀·분배·자동 저장·재콜·삭제 요청 접수/승인·23시 회수는 후속 단계다. 이 단계에서는 해당 기능의 데이터 구조를 준비했다. 일반 업무 관리자는 Django superuser가 아니다.

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

Docker 엔진과 Compose가 있는 환경을 위한 구성이다. 현재 컴퓨터에는 엔진이 없어 **빌드·컨테이너 실행은 검증하지 못했다**. YAML 구조와 공식 이미지 태그·arm64/amd64 manifest·digest는 확인했다. Python/PostgreSQL/Caddy 이미지를 digest로 고정했다.

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
| GET `/app/admin`, `/app/employee` | 역할별 기반 확인 화면. 고객관리 기능은 후속 구현 |
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
```

결과: PostgreSQL 통합 테스트 **45개 통과**, 실제 Chromium 흐름 **1개 통과**. 대부분의 단위/통합 테스트만 테스트 전용 MD5 해시로 빠르게 실행한다. 실제 기본 PBKDF2 해시 검증과 브라우저 흐름은 기본 런타임 해시를 사용한다. 운영 해시 설정을 낮추지 않았다.

기준 69개 전체 검수의 완료를 뜻하지 않는다. 자세한 범위·실패 후 수정·제한은 [2단계 검증 기록](docs/VERIFICATION_STAGE2.md)과 [진행 기록](docs/PROGRESS.md)에 있다.

## 7. 구조와 후속 경계

`apps/accounts`, `sites`, `customers`, `assignments`, `callbacks`, `imports`, `operations`로 나누었다. 모델 간 순환 FK는 Django가 분리한 migration으로 적용한다. 스키마·잠금·후속 구현 주의점은 [기반 구조](docs/FOUNDATION.md)를 참조한다.

예약 프로세스 진입점 `python manage.py run_scheduler --once`는 현재 DB 연결만 확인한다. 23시 회수·임시 자료 정리를 수행하거나 완료로 기록하지 않는다. 앱과 scheduler는 Compose에서 같은 이미지를 사용한다. 이후 요청에 지정된 기능만 이어서 구현한다.
