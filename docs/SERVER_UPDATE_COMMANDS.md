# 우분투 서버 최신 코드 반영 명령어

기준일: 2026-11-12 KST. 현재 사용자 서버의 `/root/TMDB`, `compose.yaml` + `compose.server.yaml` 조합을 기준으로 한다. 선택형 입력·필터와 상담내용 열 이동을 포함한 최신 `main`을 반영한다. 이 문서를 작성하면서 실제 서버 명령을 실행하지 않았다.

직원의 오늘 신규 고객 수에서 회수·이관·삭제를 제외하는 화면 수정만 반영하려면 [해당 HTTPS 서버 반영 명령](EMPLOYEE_TODAY_COUNTS.md#https-서버-반영)을 사용한다. 그 수정에는 새 migration이 없다. 이전 고객 선택값 migration이 미적용인 서버는 아래 전체 반영 절차를 따른다.

현재 필요한 고객 migration은 `0004_customer_selection_options`까지다. `0004`가 이미 적용됐다면 아래 migration 명령은 추가 변경 없이 끝난다. 미적용이면 `0003` 중복 정책 등 선행 migration도 함께 적용한다. **DB 변경 전에는 현재 DB의 새 백업과 별도 DB 복구 확인을 완료한다.** [백업·복구 방법](OPERATIONS.md#암호화-백업)을 따른다.

기존 `.env`·`.env.ai`·`compose.server.yaml`을 그대로 사용하며 PostgreSQL 컨테이너와 데이터 볼륨은 유지한다. 서버의 Docker·Compose와 PostgreSQL 서비스가 준비된 상태에서 실행한다. 호스트의 Python이나 `.venv`는 사용하지 않는다.

## HTTPS 적용 서버의 반영 명령

[IP HTTPS 적용](HTTPS_IP_SETUP.md)을 완료한 서버는 **이 절차를 사용하고 아래의 HTTP 서버용 두 파일 명령은 사용하지 않는다.** HTTPS 파일이 빠지면 8000 포트가 다시 공개되거나 보안 쿠키·프록시 처리가 해제될 수 있다. 기존 DB 변경 전 백업·별도 복구 확인 조건은 같다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh config --quiet &&
bash scripts/compose_https.sh --profile ai build web scheduler ai_worker &&
bash scripts/compose_https.sh run --rm --no-deps web python manage.py migrate customers 0004_customer_selection_options --plan
```

계획과 백업을 확인한 뒤 실행한다. AI는 중단 상태로 유지하며 PostgreSQL을 재생성하지 않는다.

```bash
cd /root/TMDB &&
bash scripts/compose_https.sh --profile ai stop web scheduler ai_worker &&
bash scripts/compose_https.sh run --rm --no-deps web python manage.py migrate customers 0004_customer_selection_options --noinput &&
bash scripts/compose_https.sh run --rm --no-deps web python manage.py showmigrations customers &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh up -d --no-deps proxy &&
bash scripts/compose_https.sh ps
```

고객 migration 네 개가 모두 `[X]`이고 웹 health가 `healthy`인지 확인한다. `https://165.140.21.197`로 접속해 아래 브라우저 확인 항목과 상담 저장을 확인한다. 인증서·외부 접속 확인은 [HTTPS 안내](HTTPS_IP_SETUP.md#4-확인)를 따른다.

## 1. HTTP 서버: 최신 코드·이미지 준비와 적용 계획 확인

아래 블록을 서버 터미널에 복사해 실행한다. 빌드와 읽기 전용 계획 확인을 먼저 하므로 이 단계에서는 기존 웹을 중단하지 않는다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml --profile ai build web scheduler ai_worker &&
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py migrate customers 0004_customer_selection_options --plan
```

`TM_SERVER_SECRET`·`TM_DB_PASSWORD`의 셸 덮어쓰기만 해제하고 보호된 `.env`의 기존 값을 사용한다. 키나 DB 비밀번호를 새로 만들거나 출력하지 않는다. AI 작업자 이미지를 빌드해도 AI 호출이나 작업자 실행은 발생하지 않는다.

계획에 `0004_customer_selection_options`까지 필요한 변경이 표시되는지 확인한다. 이미 적용한 서버는 `No planned migration operations.`가 표시될 수 있다. 오류·연결 실패·예상하지 않은 역방향 migration이 표시되면 다음 단계로 진행하지 말고 원인을 확인한다.

## 2. HTTP 서버: 쓰기 중단·DB 적용·웹과 스케줄러 재시작

계획과 백업·복구 확인을 마친 뒤 아래 블록을 복사한다. 서비스 중단부터 재시작까지 잠시 접속이 끊긴다. 각 명령은 앞 명령이 성공해야 이어서 실행된다.

```bash
cd /root/TMDB &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml --profile ai stop web scheduler ai_worker &&
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py migrate customers 0004_customer_selection_options --noinput &&
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py showmigrations customers &&
docker compose -f compose.yaml -f compose.server.yaml up -d --no-deps --no-build --force-recreate web scheduler &&
docker compose -f compose.yaml -f compose.server.yaml ps
```

고객 migration 결과에 다음 네 줄이 모두 `[X]`로 표시돼야 한다.

```text
[X] 0001_initial
[X] 0002_customer_metadata
[X] 0003_live_phone_unique
[X] 0004_customer_selection_options
```

이미 적용된 경우 `No migrations to apply.`는 정상이다. 마지막 `ps`에서 웹·스케줄러·PostgreSQL 실행 상태를 확인한다. 웹·PostgreSQL의 health가 `starting`이면 잠시 후 아래 상태 확인을 다시 실행해 `healthy`인지 확인한다. 스케줄러에는 현재 Compose에서 별도 health check가 없으므로 실행 상태를 확인한다.

```bash
cd /root/TMDB &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml ps
```

AI 작업자는 중단 상태로 유지한다. 이 반영 절차는 `.env.ai`의 AI 활성화·무료 확인 상태를 변경하거나 AI 작업자를 다시 시작하지 않는다.

## 3. 브라우저 확인

브라우저를 강력 새로고침한 뒤 다음을 확인한다.

- 계약여부·통화결과·루트·주택보유상황의 입력과 필터가 드롭다운인지 확인한다.
- 열 순서가 고객 거주지 → 주택보유상황 → 상담내용 → 루트 → 비고인지 확인한다. 직원에게 관리자 비고가 표시되지 않아야 한다.
- 엑셀은 새 양식을 다운로드하고 파일을 다시 검증한다. 배포 전의 검증 결과를 그대로 재사용하지 않는다.
- HTTP 직원 화면은 조회 전용이다. 직원 편집·저장은 HTTPS와 지원되는 브라우저에서 확인한다.

## 실패 시

`git pull`·이미지 빌드·계획 확인 중 실패하면 2단계를 실행하지 않는다. 2단계에서 실패하면 이어지는 재시작은 실행되지 않으며 앱이 중단 상태일 수 있다. 실제 오류를 확인한 뒤 이어서 진행한다. DB 초기화·볼륨 삭제·옛 제약 강제 복원으로 처리하지 않는다. 새 코드가 저장된 뒤 옛 migration으로 되돌리면 값·길이 제약이 충돌할 수 있으므로 별도 복원 계획을 검토한다.

키·쿠키·DB URL·고객정보를 포함하는 전체 환경 설정이나 원시 로그를 공유하지 않는다. 오류가 발생한 명령과 비밀값을 제거한 오류 부분만 확인한다. 기존 환경변수 누락 문제는 [복구 안내](SERVER_ENVIRONMENT_RECOVERY.md)를 따른다.

이 문서의 명령은 로컬에서 Bash 문법과 경로·명령 구성을 정적으로 확인했다. 실제 서버에서의 빌드·migration·재시작 성공은 사용자가 실행한 결과로 별도 확인해야 한다.
