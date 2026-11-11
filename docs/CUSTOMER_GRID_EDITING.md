# 고객 그리드 편집과 열 순서

2026-11-11 KST 사용자 승인 기준. 관리자는 고객정보(DB) 화면에서 셀을 클릭해 수정한 뒤 **저장**한다. 고객명·연락처도 관리자에게만 수정 가능하다. 직원은 현재 담당 고객의 상담 정보만 수정하며 기존 100초 이내 저장 요청·실패 재시도 흐름을 유지한다.

## 표시 순서와 권한

관리자 고객 표의 데이터·작업 열은 다음 순서를 사용한다.

1. 고객명
2. 연락처
3. 계약여부
4. 관리자 비고
5. 담당직원명
6. 통화결과
7. 상담내용
8. 재콜일정
9. 방문예약 날짜
10. 고객 거주지
11. 주택상황
12. 루트
13. 비고
14. 할당일
15. 작업
16. 저장상태

직원 표는 위 순서에서 **관리자 비고만 제외**한다. 관리자 표 맨 앞의 행 선택 체크박스는 일괄 작업을 위해 유지한다. 휴지통은 읽기 전용이며 기존 현장 표시·복구 작업을 유지한다. 공통 열 정의는 `static/customer-columns.js`에 있다.

| 항목 | 관리자 | 직원 |
|---|---|---|
| 고객명·연락처 | 수정 가능 | 조회만 가능, 조작한 저장 요청도 서버에서 거절 |
| 관리자 비고 | 조회·수정 가능 | 표·조회 API·저장/충돌 응답·이력·AI 입력에서 제외 |
| 계약여부·통화결과·상담내용·재콜일정·방문예약 날짜·고객 거주지·주택상황·루트·비고 | 수정 가능 | 현재 담당 고객만 수정 가능 |
| 담당직원명 | 기존 **담당 변경** 절차로 변경 | 조회만 가능 |
| 할당일·저장상태 | 시스템 표시 | 시스템 표시 |

새 비고(`memo`)는 상담내용(`notes`)과 별개다. 고객명은 최대 100자, 빈 값 허용이며 앞뒤 공백을 제거한다. 연락처는 010으로 시작하는 11자리 텍스트가 필수이고 하이픈·공백을 정규화한다. 같은 현장에 동일 연락처가 있으면 **휴지통 포함** 중복으로 거절하며 해당 행의 다른 수정값도 저장하지 않는다. 서로 다른 현장에서는 같은 연락처를 허용한다.

관리자 정정 시 변경 전·후 고객명/연락처를 기존 변경 이력에 기록하고 고객 버전을 올린다. 이름·연락처·관리자 비고만 정정한 경우 상담 진행으로 표시하지 않는다. 다른 사용자의 이전 버전 저장은 충돌로 거절하며 비교 화면에서 최신 고객명·연락처를 확인한 후 재적용 또는 폐기를 선택한다. 회수·재분배·삭제된 고객은 기존 권한 검사로 이전 저장을 차단한다. 정정 전 이름도 AI 입력에서 계속 가린다.

DB 필드나 migration은 추가하지 않는다. 이전 메타데이터 기능의 `customers.0002_customer_metadata`는 기존 선행 조건이다.

## 검증과 재현

로컬의 분리된 PostgreSQL 17 테스트 DB·가상 사용자/고객과 실제 Chromium에서 **백엔드 208개·브라우저 18개 통과**. 마지막 충돌 비교 화면 보완 후 영향받는 브라우저 4개를 다시 실행해 통과했다. 중복 제외 226개 검사, 재검사 포함 230회 실행이다. 각 실행에서 소스 변경 없음도 확인했다.

| 실행 ID | 결과 |
|---|---|
| `20261111T083933207348Z-fb988c3bcdad439493b720ae593ca929` | 백엔드 208개: 관리자 정정·직원 위조 요청 차단·필수값·현장별/휴지통 중복·동시 중복 정정·정정 이력·멱등성·오래된 저장 거절·AI 이름 가림 및 기존 고객/분배/재콜/AI 회귀 |
| `20261111T083940743852Z-0e97c62ffaff441994927f0b7c4c42a2` | 브라우저 18개: 정확한 열 순서·관리자 셀 편집·직원 읽기 전용·관리자 비고 비공개·기존 100초/오프라인/재시도/충돌/모바일 흐름 |
| `20261111T085819917348Z-1afe3645034e4a17b8351d718a32fbce` | 충돌 비교 화면 보완 후 4개 재검사: 최신 고객명/연락처 확인·이전 대기값 폐기·다중 탭/재분배 차단·관리자 충돌/응답 유실 재시도·기존 메타데이터 흐름 |

결과는 `.local/verification-runs/<실행ID>/`에 보존한다. 마지막 실행은 화면 변경 검증이며 이전 백엔드 결과를 다시 실행한 것으로 표시하지 않는다. 실제 고객정보·외부 AI 요청을 사용하지 않았고 개발·데모 DB와 실제 서버도 변경하지 않았다. AI 비활성·무료 확인 설정을 유지했다. 실제 Docker 이미지 재빌드·운영 서버 반영 성공은 이 로컬 검사로 검증하지 않았다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label customer-grid-admin-identity \
  tests.test_customer_identity tests.test_customer_metadata tests.test_p2 tests.test_p4 \
  tests.test_p5 tests.test_p6 tests.test_p9 tests.test_p10 tests.test_p11
.venv/bin/python scripts/run_final_verification.py test --label customer-grid-layout-browser \
  tests.browser_customer_metadata tests.browser_p2 tests.browser_employee
.venv/bin/python scripts/run_final_verification.py stop
```

## 기존 Docker 서버 반영

사용자 서버의 `compose.yaml`과 서버에 보관된 `compose.server.yaml`을 함께 사용한다. `.env`의 복원된 설정과 `.env.ai`의 비활성 상태를 유지한다. 이번 변경에는 새 migration이 없으며 기존 메타데이터 migration 적용 여부는 별도로 확인한다.

```sh
cd /root/TMDB
git pull --ff-only &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml build web scheduler &&
docker compose -f compose.yaml -f compose.server.yaml \
  up -d --no-deps --no-build --force-recreate web scheduler
```

웹·스케줄러 재생성 중 잠시 중단될 수 있다. PostgreSQL 볼륨은 보존하고 AI 작업자는 새로 시작하지 않는다. 브라우저를 새로고침한 뒤 관리자와 직원 각각의 열·수정 권한을 확인한다. 실제 서버 실행은 사용자가 수행한 후 별도로 확인해야 한다.
