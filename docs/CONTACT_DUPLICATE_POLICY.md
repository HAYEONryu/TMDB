# 전체 현장 연락처 중복 정책

2026-11-11 KST 최신 사용자 승인. 이전의 현장별/휴지통 포함 중복 기준을 아래 기준으로 변경한다. 과거 검수 실행의 당시 결과는 다시 쓰지 않는다.

| 상황 | 처리 |
|---|---|
| 같은 엑셀에서 같은 연락처 반복 | 첫 번째 유효한 행만 등록 후보, 이후 행은 파일 내 중복으로 제외 |
| 선택 현장의 휴지통 제외 고객에 같은 번호 있음 | 새 업로드 행 제외 |
| 다른 현장의 휴지통 제외 고객에 같은 번호 있음 | 새 업로드 행 제외 |
| 같은/다른 현장의 휴지통에만 같은 번호 있음 | 새 고객으로 등록 가능. 이전 휴지통 기록은 보존 |
| 검증 후 다른 업로드·연락처 정정·복구로 같은 번호가 생김 | 확정 시 다시 검사해 중복 행 제외 |

하이픈·공백을 제거한 010 시작 11자리 연락처로 비교한다. 고객명·비고가 달라도 같은 번호면 중복이다. 중복 제외는 **새 업로드 행의 등록을 건너뛰는 것**이며 원본 엑셀·기존 고객을 삭제하거나 기존 상담·담당·비고를 합치거나 덮어쓰지 않는다. 실패/중복 목록에서 `DUPLICATE_PHONE`과 사유를 표시하고 정상 후보만 등록한다. 업로드 전에 검증했던 파일은 새 기준으로 다시 업로드한다. 옛 기준에서 제외된 행을 기존 검증 결과의 등록 후보로 자동 복원하지 않는다.

연락처 정정도 전체 현장의 휴지통 제외 고객을 검사한다. 휴지통 고객을 복구할 때 같은 번호가 살아 있는 고객으로 존재하거나 복구 대상끼리 중복이면 **선택한 전체 복구를 취소**한다. 중복을 확인하고 복구 대상을 다시 선택해야 한다. 이름·전화번호를 유지한 기존 고객의 상담 편집은 허용한다.

## 기존 데이터와 DB 제약

`customers.0003_live_phone_unique`는 기존 `(현장, 연락처)` 유일 제약을 **휴지통 제외 행에만 적용하는 부분 유일 제약**으로 바꾼다. 전체 현장 연락처 조회용 부분 인덱스도 추가한다. 이 변경이 있어야 같은 현장에 휴지통 기록을 남긴 채 새 고객으로 재등록할 수 있다.

이전 정책에서 허용됐던 현장 간 기존 중복은 자동 삭제·병합·수정하지 않는다. 따라서 전역 유일 DB 제약을 바로 추가하지 않으며 기존 중복도 보존해 migration한다. 새 전역 중복은 업로드 검증/확정·연락처 정정·복구 서비스가 공통 업무 트랜잭션 잠금 안에서 재검사해 방지한다. 모든 앱 쓰기 프로세스를 같은 코드로 맞춰야 한다. DB 스키마 외의 고객 원문·이력·계정·할당을 수정하는 migration은 없다.

역방향으로 되돌리면 옛 제약이 복원된다. 휴지통 번호를 재등록한 자료가 있으면 옛 제약을 만족하지 않을 수 있으므로 무조건 역방향 migrate하지 않는다. 문제 발생 시 쓰기를 중지하고 백업을 보존한 뒤 호환 코드와 별도 복원 DB를 검토한다.

## 검증

분리된 PostgreSQL 17 테스트 DB와 가상 고객만 사용했다. 작업 트리의 변경 영향 검사 138개에 최종 통과 근거가 있다. 기존 미커밋 업로드 진단 검사도 이 작업 트리 검증에 포함돼 있으며 관련 기존 작업은 별도로 보존한다. 실제 고객정보·개발/데모 DB·서버 DB·외부 AI는 사용하지 않았다.

| 실행 ID | 결과 |
|---|---|
| `20261111T094247127030Z-e6ce7acf43f242d0bd6fe951ee76c30a` | 138개 중 137개 통과. 새 휴지통 재등록 브라우저 검사 1개는 업로드 화면으로 이동하는 단계가 빠져 시간 초과. 기존 화면 검사와 백엔드 정책·동시성·migration 보존 검사 통과 |
| `20261111T094424572123Z-cbb1c3ff11e24c4284ae26d5abd2f35f` | 전역 조회 인덱스를 포함한 최종 migration·신규 정책/동시성 11개·DB 제약 20개·화면 진입을 보완한 휴지통 재등록 1개, 총 32개 통과 |
| `20261111T094428512777Z-68a42b42d56b42e3937232138344857a` | Django 시스템 검사·migration drift 통과 |

각 테스트 실행의 소스 불변도 확인했고 `.local/verification-runs/<실행ID>/`에 실패 기록과 재검사를 분리 보존한다. 서로 다른 현장의 동시 업로드, 업로드와 복구/관리자 정정의 경합에서도 새 같은 번호가 한 건만 살아 있도록 검증했다. 0002 가상 DB의 기존 현장 간 중복과 휴지통·상담을 보존한 0003 업그레이드, 새 빈 테스트 DB 전체 migration도 확인했다. 실제 운영 서버 적용·실제 고객 데이터 분포의 성능은 미검증이다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label global-live-contact-policy \
  tests.test_live_contact_policy tests.test_imports tests.test_models \
  tests.test_customer_identity tests.test_customer_metadata tests.test_p2 tests.test_p7 tests.browser_imports
.venv/bin/python scripts/run_final_verification.py check --label global-live-contact-schema
.venv/bin/python scripts/run_final_verification.py stop
```

## 기존 Docker 서버에 적용

2026-11-12 최신 코드에는 [선택값 변경](CUSTOMER_SELECTIONS.md)도 포함되므로 아래 명령은 0004까지 적용한다. 중복 정책 자체의 변경·검증 기록은 위 0003 설명 그대로 보존한다.

실제 서버에 이 작업에서 배포하거나 migration하지 않았다. 적용 대상 DB의 **새 백업과 별도 DB 복구 확인**을 먼저 완료한다([백업·복원](OPERATIONS.md)). 아래는 사용자 서버의 기존 두 Compose 파일을 사용하는 절차다. 비밀 파일과 PostgreSQL 볼륨을 유지한다.

```sh
cd /root/TMDB
git pull --ff-only
unset TM_SERVER_SECRET TM_DB_PASSWORD
docker compose -f compose.yaml -f compose.server.yaml --profile ai build web scheduler ai_worker
docker compose -f compose.yaml -f compose.server.yaml --profile ai stop web scheduler ai_worker
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py migrate --plan
```

계획에서 적용 대상과 `customers.0004_customer_selection_options`까지의 변경을 확인한 뒤 실행한다. 명령이 실패하면 웹을 먼저 재개하지 말고 원인을 확인한다.

```sh
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py migrate customers 0004_customer_selection_options --noinput &&
docker compose -f compose.yaml -f compose.server.yaml run --rm --no-deps web python manage.py showmigrations customers &&
docker compose -f compose.yaml -f compose.server.yaml up -d --no-deps --no-build --force-recreate web scheduler
```

`[X] 0004_customer_selection_options`와 웹 상태를 확인하고 브라우저를 새로고침한다. AI 작업자 이미지만 새 코드로 준비하며 비활성 상태와 무료 확인 설정을 유지한다. 운영 확인은 가상 고객으로 A 등록 후 B 중복 제외, 휴지통 번호의 새 등록, 중복 복구 거절을 확인한다. 기존 고객을 자동 정리하는 작업은 포함하지 않는다.
