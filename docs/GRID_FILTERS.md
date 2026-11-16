# 고객정보 빈 값과 필터

2026-11-15 KST 최신 사용자 요청 기준. 관리자 DB 관리·휴지통과 직원 오늘 할 일·나의 DB는 같은 빈 값 표시와 필터 화면을 사용한다.

## 빈 값 표시와 편집

미입력 고객명·선택값·문자·날짜는 `-`로 표시한다. 계약여부의 `UNKNOWN`도 `-`다. 신규 항목의 기존 빈 값 기본값을 유지하며 DB에 표시용 하이픈을 일괄 저장하지 않는다.

- 계약여부·통화결과·주택보유상황·루트: 선택 목록 첫 항목인 `-`를 선택해 다시 비운다.
- 고객명·상담내용·거주지·비고·관리자 비고: 입력 내용을 지운 뒤 저장한다.
- 방문·재콜 날짜: 날짜 입력 내용을 지워 저장한다. 재콜 날짜 삭제는 일정 취소이며 완료 처리는 별도다.
- 관리자는 **저장**, 직원은 **지금 저장** 또는 기존 자동 저장으로 확정한다.

연락처는 계속 필수다. 관리자 비고는 관리자만 조회·수정하며 직원은 현재 담당 고객의 허용된 항목만 수정한다. 담당자 변경·배정일·휴지통 읽기 전용 등 기존 권한을 유지한다. 명시적으로 문자 `-`를 입력한 일반 텍스트와 실제 미입력은 DB에서 서로 다르므로, 문자를 비우려면 내용을 지운다.

## 필터 사용법

조회 컨트롤은 **현장 → 고객 검색 → 검색 버튼 → 상세 필터 → 정렬** 순서다. 검색은 Enter 또는 검색 버튼으로 확정하며 이름 부분 일치와 공백·하이픈을 제거한 전화번호를 찾는다. 전화번호 검색은 숫자와 공백·하이픈으로만 구성되고 실제 숫자가 있는 입력에만 적용한다. 하이픈만 입력한 값은 전체 전화번호와 일치하지 않는다. 빈 검색어로 검색하면 검색 조건을 지운다.

열 헤더의 필터 버튼은 **상세 필터** 패널로 모았다. 위쪽의 통화결과·재콜일정·방문예약 날짜·계약여부를 빠르게 지정하고, 관리자는 담당직원도 지정할 수 있다. 통화결과의 나머지 값은 ‘다른 통화결과 보기’에서 선택한다. 접힌 **추가 조건**에서는 역할별 필드를 골라 기존 다중 선택·정확 일치·제외·포함·날짜·빈 값 조건을 편집한다. 위쪽과 추가 조건은 필드별로 같은 임시 값을 쓰고 현재 모드를 표시한다. 직원은 담당직원명과 관리자 비고 필터를 사용할 수 없다.

| 열 종류 | 제공 조건 |
|---|---|
| 계약여부·통화결과·주택보유상황·루트 | 전체, 미입력, 현재 선택값, 조회 범위의 이전 값. 여러 값 정확 일치/선택한 값 제외 |
| 고객명·연락처·담당직원명(관리자만) | 전체, 선택한 값만, 선택한 값 제외, 미입력/입력된 항목. 후보 검색·100개씩 더 불러오기·보이는 값 모두 선택/선택 해제 |
| 상담내용·거주지·비고·관리자 비고(관리자만) | 내용 포함, 전체, 미입력/입력된 항목 |
| 방문예약·재콜·할당 날짜 | 날짜 범위, 전체, 미입력/입력된 항목. 최근 7일·이번 달 빠른 선택 |
| 재콜일정 | 추가로 서버 시각 기준 ‘오늘’·‘기한 지남’ |

**필터 적용**을 누를 때만 고객 목록을 한 번 조회한다. 취소·닫기·Esc는 임시 변경을 버리고 상세 필터 버튼으로 초점을 돌린다. **필터 지우기**는 패널의 임시 상세 조건만 지운다. 목록의 **조건 초기화**는 적용된 검색어·상세 조건·담당직원 유입 조건과 URL의 담당직원 유입값을 지우고 첫 페이지로 이동한다. 현장·정렬·페이지당 행 수와 오늘 할 일의 조회 범위는 유지한다. 적용·개별 조건 제거·초기화는 관리자 미저장 확인과 직원 자동 저장·실패/충돌 확인을 거친다.

적용된 검색어·상세 조건·담당직원 유입 조건을 목록 위에서 각각 제거할 수 있다. 상세 필터 (N)은 상세 조건 필드 수로, 검색어와 유입 조건은 포함하지 않는다. 같은 필드의 여러 값은 OR, 다른 필드와 검색어는 AND다. 미입력은 기존 NULL·빈 문자·계약여부 UNKNOWN 규칙을 따른다. 이전 자유문자 루트 필터는 값을 바꾸기 전까지 유지한다.

날짜는 한국 시간 기준이며 입력한 종료일 전체를 포함한다. 재콜 ‘오늘’은 서버 시각의 KST 00:00 이상 다음 날 00:00 미만, ‘기한 지남’은 서버 현재 시각 미만이다. 둘 다 미완료 재콜만 조회하며 당일 예정 시각이 지난 고객은 두 조건에 모두 해당한다. API는 `callback_due_at: {"preset": "today"}` 또는 `{"preset": "overdue"}`를 지원한다. 다른 필드나 미지원 preset은 거절한다. 일반 날짜의 빠른 기간은 브라우저 시계를 KST로 변환한다.

목록은 로딩·실패·조건에 맞는 고객 없음·담당 고객 없음·오늘 할 일 없음·휴지통 비어 있음을 구분한다. 조건이 있는 0건 화면에는 조건 초기화를 제공한다. 조회 실패 시 마지막 성공 조건·목록·건수를 유지하며 다시 조회할 수 있다. 오래된 목록 응답과 닫힌 패널의 후보 응답은 최신 결과에 반영하지 않는다. 결과 건수와 상태는 보조기기에 알린다. 작은 화면은 컨트롤을 줄바꿈하고 고객 표 안에서 가로 스크롤한다.

## 2026-11-15 로컬 검증 범위

별도 PostgreSQL 테스트 DB와 가상 사용자·고객으로 기존 필터, 셀 편집, 저장 보호, 역할별 조회, 휴지통 복구 및 새 경계 사례를 검사한다. 새 DB 필드나 migration은 없다. 실행별 결과와 화면은 `.local/verification-runs/`에 보존한다. 현장 관리 메뉴와 열 표시 메뉴는 이번 범위에 포함하지 않는다.

```bash
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label unified-customer-query \
  tests.test_grid_filters tests.test_p2 tests.test_p5 tests.test_p6 \
  tests.test_customer_choices tests.test_customer_metadata \
  tests.browser_grid_filters tests.browser_customer_metadata \
  tests.browser_p2 tests.browser_p7 tests.browser_employee
.venv/bin/python scripts/run_final_verification.py check --label unified-customer-query-check
.venv/bin/python scripts/run_final_verification.py stop
```

## 이전 검증과 재현 (2026-11-13)

분리된 PostgreSQL 17 테스트 DB·가상 사용자/고객·실제 Chromium에서 변경 영향 범위 **고유 검사 77개가 최종 통과**했다. 한 실행에서 77개를 모두 실행했다고 표시하지 않는다. 실제 고객정보·개발/데모 DB·운영 서버·외부 AI 호출은 사용하지 않았다. 외부 AI 요청 수는 0회다.

| 실행 ID | 결과 |
|---|---|
| `20261112T163038522350Z-ebb47104771f4c5f85804f36ae623449` | 76개 중 75개 통과. 신규 빈 값 표시 테스트가 존재하지 않는 DOM 행 속성을 사용해 1개 실패 |
| `20261112T163230470338Z-5bd38f71f63e48cb965b1da8765bfa95` | 해당 1개 재실행 실패. 고객값을 남기지 않는 필드별 요소 존재 여부로 잘못된 선택자를 확인 |
| `20261112T163317176081Z-63970376ec8a4027b964e636283771e4` | 가상 연락처 기반 선택자로 수정한 해당 1개 통과. 관리자·직원 네 선택값 입력 후 `-`로 저장되는지 확인 |
| `20261112T163359063971Z-6d5006bfc30b44e8bf301bce5cc55ec4` | 연락처 후보 검색 하이픈 처리와 모달 전환 보완 후 관련 40개 모두 통과. 서버 필터·권한·네 브라우저 시나리오·HTTP 조회 전용 회귀 포함 |
| `20261112T163545632363Z-f16c9cda4fd2478cb7de73976a0881d3` | Django 시스템 검사·migration drift 통과. JavaScript 네 파일의 Node 구문 검사도 별도로 통과 |

각 실행에서 소스 변경 없음을 확인했고 실패 원본을 덮어쓰지 않았다. `.local/verification-runs/<실행ID>/`에 결과·진단 위치·가상자료 화면을 보존한다. 관리자/직원 모달을 1440×960과 390×844에서 확인했으며 가로 화면 넘침·하단 버튼 접근성도 검사했다. 저장 충돌·암호화 보관·기존 자동 저장·관리자 비고 비노출·기존 값 보존·휴지통/복구 흐름은 변경 영향 회귀 검사에 포함했다. 실제 서버 적용과 사용자 브라우저 환경은 별도 확인 대상이다.

```bash
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label grid-empty-filter-ux \
  tests.test_grid_filters tests.test_customer_choices.CustomerChoiceTests \
  tests.test_p2 tests.test_customer_metadata tests.browser_grid_filters \
  tests.browser_customer_metadata tests.browser_employee \
  tests.browser_p2.AdminGridBrowserTests.test_grid_paging_filters_manual_save_trash_restore_site_default_and_mobile \
  tests.browser_http_environment.EmployeeEnvironmentBrowserTests.test_http_today_site_selection_filters_and_session_end
.venv/bin/python scripts/run_final_verification.py check --label grid-empty-filter-check
.venv/bin/python scripts/run_final_verification.py stop
```

## 기존 HTTPS 서버 반영

이번 변경은 새 migration이 없다. 이전 고객 migration 0004까지 적용한 기존 서버에서 아래 명령을 실행한다. 미적용 서버는 [전체 업데이트 절차](SERVER_UPDATE_COMMANDS.md)를 먼저 따른다. 이 작업에서 실제 서버 배포는 실행하지 않았다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh build web scheduler &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh ps
```

완료 후 브라우저를 강력 새로고침하고 관리자/직원 화면에서 `-` 선택 저장, 값 없음 조회, 날짜 범위·필터 해제를 확인한다.
