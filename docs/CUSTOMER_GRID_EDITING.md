# 고객 그리드 편집과 열 순서

2026-11-12 KST 최신 사용자 승인 기준. 관리자는 고객정보(DB) 화면에서 셀을 클릭해 수정한 뒤 **저장**한다. 직원도 현재 담당 고객의 **고객명과 상담 정보**를 수정할 수 있다. 연락처 수정은 관리자만 가능하며 직원의 기존 100초 이내 저장 요청·실패 재시도 흐름을 유지한다.

## 표시 순서와 권한

관리자 고객 표의 데이터·작업 열은 다음 순서를 사용한다.

1. 고객명
2. 연락처
3. 계약여부
4. 관리자 비고
5. 담당직원명
6. 통화결과
7. 재콜일정
8. 방문예약 날짜
9. 고객 거주지
10. 주택보유상황
11. 상담내용
12. 루트
13. 비고
14. 할당일
15. 작업
16. 저장상태

직원 표는 위 순서에서 **관리자 비고만 제외**한다. 관리자 표 맨 앞의 행 선택 체크박스는 일괄 작업을 위해 유지한다. 휴지통은 읽기 전용이며 기존 현장 표시·복구 작업을 유지한다. 공통 열 정의는 `static/customer-columns.js`에 있다.

| 항목 | 관리자 | 직원 |
|---|---|---|
| 고객명 | 수정 가능 | 현재 담당 고객만 수정 가능 |
| 연락처 | 수정 가능 | 조회만 가능, 조작한 저장 요청도 서버에서 거절 |
| 관리자 비고 | 조회·수정 가능 | 표·조회 API·저장/충돌 응답·이력·AI 입력에서 제외 |
| 계약여부·통화결과·상담내용·재콜일정·방문예약 날짜·고객 거주지·주택보유상황·루트·비고 | 수정 가능 | 현재 담당 고객만 수정 가능 |
| 담당직원명 | 기존 **담당 변경** 절차로 변경 | 조회만 가능 |
| 할당일·저장상태 | 시스템 표시 | 시스템 표시 |

계약여부·통화결과·주택보유상황·루트는 [현재 고정 선택 목록](CUSTOMER_SELECTIONS.md)으로 편집한다. 새 비고(`memo`)는 상담내용(`notes`)과 별개다. 고객명은 최대 100자, 빈 값 허용이며 앞뒤 공백을 제거한다. 연락처는 010으로 시작하는 11자리 텍스트가 필수이고 하이픈·공백을 정규화한다. 최신 사용자 승인에 따라 새 연락처로 정정할 때 **전체 현장의 휴지통 제외 고객**에 같은 번호가 있으면 해당 행 전체를 거절한다. 휴지통에만 있는 번호는 사용할 수 있다. [최신 중복 정책·DB 변경](CONTACT_DUPLICATE_POLICY.md)이 이전 현장별/휴지통 포함 규칙보다 우선한다.

고객명/연락처 정정 시 변경 전·후 값을 기존 변경 이력에 기록하고 고객 버전을 올린다. 이름·연락처·관리자 비고만 정정한 경우 상담 진행으로 표시하지 않는다. 직원의 이름만 정정한 저장도 상담 고객 수와 오늘·주간 상담결과 집계에서 제외한다. 다른 사용자의 이전 버전 저장은 충돌로 거절하며 비교 화면에서 최신 고객명·연락처를 확인한 후 재적용 또는 폐기를 선택한다. 회수·재분배·삭제된 고객은 기존 권한 검사로 이전 저장을 차단한다. 정정 전 이름도 AI 입력에서 계속 가린다.

이 문서의 최초 그리드 편집 변경에는 DB 필드나 migration을 추가하지 않았다. 이후 최신 중복 정책은 `customers.0003_live_phone_unique`가 필요하다. 아래 검증 기록과 최초 그리드 배포 설명은 당시 변경 범위의 기록이며 새 중복 정책 적용은 위 링크의 절차를 따른다.

## 2026-11-12 직원 고객명 편집 검증

직원 ‘오늘 할 일’·‘나의 DB’에서 고객명 셀을 편집하면 기존 암호화 저장 대기열을 통해 자동 저장하거나 ‘지금 저장’으로 전송한다. 앞뒤 공백 제거·최대 100자·빈 값 허용을 서버와 화면에 적용했다. 연락처·관리자 비고는 직원 요청을 서버에서 거부하며 다른 직원/미할당 고객과 회수 후 옛 할당의 저장도 거부한다. 이름 정정과 상담 내용을 함께 저장하면 기존 상담 진행 기준을 적용한다.

입력 제한 검증 중 Esc로 편집을 취소한 후 늦은 change 이벤트가 입력 오류를 다시 만들던 문제를 발견했다. 편집 종료 뒤의 이벤트를 무시하도록 수정하고 취소·기존 자동 저장 시계·암호화 보관·다중 탭 충돌을 재검증했다.

별도 PostgreSQL 테스트 DB·가상자료·Chromium으로 **Django/브라우저 고유 검사 117개와 Node 저장 대기열 검사 22개가 최종 통과**했다. 실제 외부 AI 요청, 실제 고객정보, 개발/데모/서버 DB 변경은 수행하지 않았다. Django 설정·migration drift 검사도 통과했고 이번 수정에 새 migration은 없다. 이름 변경 이력의 AI 입력 가림도 모의 구성으로 확인했다.

| 실행 ID | 결과 |
|---|---|
| `20261112T143535985443Z-cb2d4a21732d43d98403c515165e8a25` | 100개 중 99개 통과. 새 이름 편집 검사에서 잘못된 입력을 Esc로 취소한 후 오류가 남아 1개 실패 |
| `20261112T143722079299Z-82eae771116d4a29866d9375eb5cda15` | 종료된 편집기의 이벤트 처리 수정 후 해당 검사·열/권한·기존 잘못된 입력·자동 저장 시계 4개 통과 |
| `20261112T143844013220Z-0291a9091b8549b8acffef100eb5f0d1` | 이름만 바꾼 저장을 상담 집계에서 제외한 후 관리자 보고서 회귀 14개 통과 |
| `20261112T143847754538Z-e4048d51d0e04327bdba2122fd702241` | Django 설정·migration drift 검사 통과 |
| `20261112T143934104391Z-95cf2681e7234dcd8e3b48a14c7eaab8` | 로컬 Caddy TLS를 거친 직원 이름 편집·상담 동시 저장 1개 통과 |

원본은 `.local/verification-runs/<실행ID>/`에 보존하며 테스트 실행 중 source 변경 없음도 확인했다. 마지막 실행이 전체 검사를 반복한 결과라는 뜻은 아니다. 변경 영향에 맞춰 재검증했다. Node 22개는 아래 명령의 터미널 실행 결과이며 Django 실행 ID에 포함되지 않는다. 로컬 TLS 검사의 임시 내부 CA 예외는 테스트 브라우저에만 설정했으며 실제 서버 공인 인증서·배포 성공을 뜻하지 않는다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label employee-name tests.test_customer_identity tests.test_customer_metadata tests.test_p5 tests.test_p2 tests.test_p10 tests.test_dashboard_reports tests.browser_customer_metadata tests.browser_employee.EmployeeBrowserTests.test_multitab_explicit_conflict_and_reassignment_blocks_old_queue tests.browser_employee.EmployeeBrowserTests.test_invalid_first_input_is_not_reported_saved_and_navigation_requires_choice tests.browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions tests.browser_ip_https
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/run_final_verification.py stop
```

## 이전 검증 기록 (2026-11-11)

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

사용자가 HTTPS 적용을 완료한 서버는 세 Compose 파일을 함께 지정하는 스크립트를 사용한다. `.env`와 `.env.ai`를 유지한다. **이번 직원 고객명 편집에는 새 migration이 없다.** 이전 고객 선택값 migration이 미적용인 서버는 [최신 전체 반영 절차](SERVER_UPDATE_COMMANDS.md)를 먼저 따른다. 아래는 기존 migration이 적용된 HTTPS 서버의 이미지 갱신 절차다.

```sh
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh build web scheduler &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh ps
```

저장 중인 사용자의 저장 완료를 확인한 뒤 적용한다. 웹·스케줄러 재생성 중 잠시 중단될 수 있다. PostgreSQL 볼륨은 보존하고 AI 작업자는 새로 시작하지 않는다. HTTPS 화면을 강력 새로고침한 뒤 직원의 고객명 편집·저장을 확인한다. 실제 서버 실행은 사용자가 수행한 후 별도로 확인해야 한다.
