# 직원·관리자 HTML 기준 화면 적용

기준 자료는 사용자가 제공한 `tmdb-figma-followup/employee.html`, `admin.html`이다. 작업 시작 시 브랜치는 `main`, HEAD는 `5cc57ecd9de73631e09022e0e66a8d2aa61b9256`이고 작업 트리는 깨끗했다. 작업 도중 외부에서 `40c3b29aba9c17f878f627dde8542573d7432eb2` 커밋이 생겼다. 에이전트는 커밋·푸시·운영 배포를 실행하지 않았으며 해당 기록을 보존했다.

## 적용 화면

- 직원 대시보드: 월간 실적을 마지막 영역으로 배치하고 월 합계, 일별 콜 그래프, 날짜 선택과 일별 수치를 추가했다. 기존 오늘 카드·집계 의미는 유지했다. 오늘 재콜·방문예약 고객명은 버튼 형태의 텍스트이며 표 아래에서 전체 상담내용·연락처·일정을 펼치고 닫는다. 닫기 후 해당 고객명으로 초점을 돌린다.
- 오늘의 TM·나의 DB: 두 화면의 업무 열을 최종 TM 날짜, 고객명, 연락처, 통화결과, 삭제요청, 고객 거주지, 재콜 일정, 주택보유상황, 상담내용, 방문예약 날짜, 계약 여부로 통일했다. 이력·AI·실제 통화/방문 기록과 저장상태 유틸리티는 업무 열 뒤에 유지한다. 비고·루트 등 저장 데이터와 API 필터는 삭제하지 않는다. 날짜가 없으면 `-`와 연한 주황색을 함께 표시한다.
- 직원 목록은 서버 전체 검색·필터·정렬과 50행 단위 이어 읽기를 사용한다. 키보드 사용자를 위한 `고객 더 불러오기` 버튼도 제공한다. 저장 버튼은 두 목록 모두 목록 새로고침 옆에 있다. 직원의 암호화 대기열·90초 자동 저장·이동 시 저장 보호는 기존 구현을 사용한다.
- 관리자 대시보드: 조회 현장·마지막 조회·현재 고객/담당/휴지통 수와 기본 현장 설정을 같은 카드에 배치했다. 간결한 가로 막대 → 삭제 요청 승인 → 직원별 월간 실적 → 직원별 업무량 순서로 표시한다. 기존 상세 차트와 추가 상담·계약 통계는 펼쳐서 볼 수 있다. 이관 필요와 휴지통·사용자 관리 메뉴도 유지한다.
- DB 관리: 현장·검색·상세 필터를 정렬하고 업무 열 제목으로 서버 정렬을 지원한다. 담당 변경 버튼은 직원명 옆에 유지한다. 고객 추가·엑셀 업로드 진입을 상단에 두고 기존 입력/검증/수동 저장·확정 API와 미확인 결과 재시도 방식을 유지한다.
- DB 분배·회수: 직원 표의 전체/개별 선택, 선택 인원과 직원별 보유·오늘 배정·미완료 TM 수를 표시한다. 분배 확인과 직원별 회수 인원 확인을 제공한다. 개별 직원 또는 전체를 받는 기존 API에 선택 직원 목록도 허용하며 동일한 서비스·권한·멱등 처리 경로를 재사용한다.
- AI 보고서: 종류별 담는 내용·생성 조건·직원/현장 입력과 서비스 공통 상태 안내, 생성·검토·게시 동작을 유지하고 같은 스타일을 적용했다.
- `followup.css`의 모든 규칙은 `body.tm-refresh` 아래에 한정한다. 휴지통·사용자 관리에는 이 클래스를 주지 않는다. 기존 `app.css`, 휴지통에 렌더되는 템플릿 분기, 사용자 관리 화면과 두 라우트를 유지했다.

## 조회 현장과 서비스 기본 현장

저장 대상은 기존 `GlobalSettings.default_site_id`다. 기존 `PATCH /api/settings/default-site`와 버전 검사·변경 이력을 그대로 사용한다. 대시보드 조회 현장과 별개인 모달에서 저장한다. 저장 성공/충돌 재조회 시에도 대시보드 조회 현장을 바꾸지 않는다.

조회 현장 변경은 대시보드 URL의 조회 조건만 갱신하며 일반 관리자 메뉴 링크에 해당 현장을 덮어쓰지 않는다. 관리자 업무 화면과 직원 화면을 명시적 현장 없이 새로 열면 기존 `/api/sites`의 서비스 기본값을 사용한다. 사용자가 명시한 `site_id` 링크·개별 작업 문맥은 기존대로 유지한다. 목업의 localStorage 기본 현장 저장을 옮기지 않았다.

기존 자동 회수 스케줄러는 실행 중일 때 마감 시점의 서비스 기본 현장을 사용한다. 조회 현장 선택은 이 값에 영향을 주지 않는다.

## 집계와 기록

| 표시 항목 | 데이터·계산 기준 |
|---|---|
| 오늘 통화 시도·월간 콜 수 | `CustomerActivity(kind=CALL)`의 직원·현장·한국 날짜별 기록 수. 같은 고객 2회는 2콜 |
| 연결된 통화 | 같은 개별 통화 중 `connection=CONNECTED`만 포함. 미연결·확인 불가는 제외 |
| 가망고객 수 | 기존 `consultation_saves()`의 INTERESTED 스냅샷, 실제 기록 직원, 한국 날짜별 고유 고객. 기록 당시 배정이 MANUAL_RECALL/AUTO_RECALL로 종료됐으면 원래 날짜에서 제외 |
| 실제 방문고객 수 | `CustomerActivity(kind=VISIT).visited_on` 날짜별 고유 고객. 방문예약·최종 고객 상태로 추정하지 않음 |
| 월간 합계 | 기존 일별 값의 합. 서로 다른 날짜의 같은 고객은 각 날짜 실적에 포함. 자료가 일부인 월은 `일부 기간` 표시 |
| 일별 통화결과 | 기존 날짜별 고객의 마지막 명시적 결과 변경 이력. 월간 가망의 회수 제외와 별개인 기존 의미 유지 |
| 최종 TM 날짜 | 현재 배정에서 담당 직원이 남긴 개별 CALL 기록의 마지막 시각을 한국 날짜로 표시. 이름·상담 저장 시각으로 추정하지 않음 |
| 오늘 배정 유지 | 조회 시점의 현재 유효 배정 기준. 회수·재배정·휴지통 이동을 반영 |
| 미완료 이월·TM 회수 | 기존 공통 `with_tm_state()` 사용. 결과를 비우면 최신 변경이 이전 완료보다 우선하며 오늘까지 미완료 재콜이 있으면 미완료 |

직원 월간 조회와 새 관리자 `GET /api/dashboard/staff-performance`는 같은 `performance()` 및 `monthly_totals()`를 사용한다. 관리자만 직원별 정보를 조회할 수 있다. 기존 관리자 상담 통계의 작성자 기준도 공통으로 사용한다. 현재 직원의 상담 기록과 배정 이력으로 작성자를 확인할 수 있는 과거 직원의 기록이 집계 대상이다. 과거 자료 범위는 기존 기록 도입일과 보관 이력에 따른다. 배정 연결이 없는 이전 직원의 가망 기록은 현재 담당자로 회수 여부를 추정하지 않고 기존대로 유지한다.

정상 0, 집계 자료 없음, 조회 실패를 구분한다. 미래 일자는 `—`다. 조회 실패를 0으로 바꾸거나 저장 실패 문구를 표시하지 않는다. 목업의 예시 고객·가상 집계·브라우저 저장 방식은 제품 코드에 추가하지 않았다.

## 이어 읽기 일관성

`GET /api/customers?pagination=infinite`는 서버에서 조건과 정렬을 먼저 적용한다. 동률은 고객 ID로 순서를 고정하고 `next_cursor`를 반환한다. 서명된 다음 조회 정보에는 사용자·권한·조회 조건·전체 정렬 ID 집합의 해시·한국 날짜·다음 위치만 포함되며 고객 원문이나 별도 영속 저장소를 추가하지 않는다.

각 조회는 같은 읽기 트랜잭션 안에서 대상 해시와 행을 확인한다. 이어 읽는 중 대상·순서·한국 날짜가 바뀌거나 20분이 지나면 `LIST_CHANGED`로 중단하고 처음부터 새로 조회하도록 안내한다. 다른 계정·조건의 커서를 재사용할 수 없다. 조건 변경은 새 커서 없이 첫 결과부터 시작한다. 화면에서도 중복 ID를 합치지 않고 오류로 알린다. 관리자 DB 관리·휴지통의 기존 페이지 조회 API는 유지한다.

매 이어 읽기마다 전체 정렬 ID를 검증하므로 대상이 매우 큰 운영 규모에서의 부하 수치는 별도 확인 대상이다. 로컬에서는 125명, 동률 정렬·조건 변경·회수/담당 변경·자정 변경을 검증했다.

## 분배·회수 확인

- 오늘 배정 회수: 선택 현장·선택 직원의 오늘 현재 배정 전체. 완료/부재 처리 고객도 포함한다.
- 미완료 TM 회수: 배정일과 무관하게 선택 현장·선택 직원의 현재 TM 상태가 미완료인 고객 전체. 직원 화면의 검색·페이지·필터와 무관하다.
- 미완료 회수는 기존 서명된 대상 확인과 실행 시 공통 상태 재검증을 사용한다. 완료·재배정·직원 상태·자정으로 대상이 달라지면 전체 처리를 중단하고 최신 대상 재확인을 요구한다.
- 현재 배정 종료와 미배정 복귀는 기존 `end_locked()`를 사용한다. 상담·재콜·실제 통화/방문 기록은 보존한다. 처리 결과 확인 재시도는 기존 멱등 키를 재사용한다.

## 주요 변경 파일

| 구분 | 파일 |
|---|---|
| 공통·화면 | `templates/base.html`, `templates/accounts/home.html`, `templates/customers/employee.html`, `templates/customers/manage.html`, `templates/assignments/manage.html`, `templates/ai/admin.html`, `templates/imports/upload.html` |
| 스타일 | `static/followup.css` |
| 목록·정렬 | `static/customer-columns.js`, `static/customer-query.js`, `static/server-sort.js`, `static/employee-grid.js`, `static/customer-grid.js`, `apps/customers/queries.py`, `apps/customers/pagination.py`, `apps/customers/views.py` |
| 대시보드·실적 | `static/dashboard.js`, `static/site-dashboard.js`, `static/employee-dashboard.js`, `static/employee-performance.js`, `static/daily-call-results.js`, `static/performance-view.js`, `static/staff-performance.js`, `apps/operations/employee_performance.py`, `apps/operations/dashboard_reports.py`, `apps/consultations/queries.py`, `config/urls.py` |
| 분배·회수 | `static/assignments.js`, `apps/assignments/services.py`, `apps/assignments/tm_recall.py` |
| 신규 검증 | `tests/test_html_followup.py`, `tests/browser_html_followup.py` |
| 회귀 검증 갱신 | `tests/browser_admin_tm_operations.py`, `tests/browser_common_ui.py`, `tests/browser_daily_call_results.py`, `tests/browser_grid_filters.py`, `tests/browser_today_tm.py`, `tests/browser_ui.py` |
| 테스트 격리 보완 | `tests/test_customer_metadata.py`: 이전 스키마 검사 후 모든 최신 migration leaf 복원 |

## 검증 기록

통합 테스트 233개가 통과했다. 이 중 브라우저 검증은 73개다. 기본 현장 실제 변경과 전체 직원 선택을 보완한 뒤 관련 테스트 51개도 통과했다. 두 실행의 범위는 겹친다. Node 테스트 24개, Django 시스템 검사와 마이그레이션 검사도 통과했다. 실행 결과와 소스 해시는 [검증 요약](../outputs/html-followup-20261118/verification-summary.json)에, 화면 비교는 [화면 비교 보고서](../design-qa.md)에 기록했다.

운영 서버·실제 계정·실제 고객·외부 AI 생성은 사용하지 않았다. 운영 배포와 실기기·다른 브라우저 엔진, 운영 규모 부하 검증은 실행하지 않았다. 내장 브라우저 연결을 사용할 수 없어 기존 로컬 Chromium 테스트 도구로 화면과 상호작용을 검증했다. 운영 scheduler를 시작·중지하거나 자동 회수 설정을 바꾸지 않았다.

승인 대기 제안은 없다. 요청 범위의 기존 권한·기록·집계 규칙을 재사용했으며 미승인 업무 기능은 추가하지 않았다.
