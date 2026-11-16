# 두드림 TM 문구·공통 UI 구현 및 검증

## 기준과 작업 트리

- 기준 및 시작 HEAD: `main` / `7386728bb9215f2ea076e2619f4c0ddc75e93744`.
- 시작 시 작업 트리는 깨끗했습니다. 저장소와 상위 경로에서 별도 `AGENTS.md`는 발견되지 않았습니다. 기존 README의 격리 검증 절차를 사용했습니다.
- 사용자가 제공한 `implementation-reference.md`의 문구 표와 PNG 4장은 문구·배치·색상 참고 자료로 사용했습니다. 예시 수치는 구현에 넣지 않았습니다.
- 변경은 로컬 작업 트리에 남겼습니다. 운영 계정·데이터·서버를 사용하지 않았으며 Git 커밋·푸시·배포는 수행하지 않았습니다.

## 변경 내용과 파일

| 영역 | 변경 파일 | 적용 내용 |
|---|---|---|
| 공통 메뉴·레이아웃 | `templates/base.html`, `static/app.css`, `static/shared-ui.js` | 브랜드 한 번 표시, 홍보 문구·왼쪽 메뉴 제거, 데스크톱 상단 메뉴, 1199px 이하 접는 메뉴, 공통 제목·주요 작업·조회 영역 |
| 계정 | `templates/accounts/login.html`, `password.html` | 같은 폼 폭과 입력·버튼 배치, 간결한 로그인 안내, 최초·재설정 시에만 비밀번호 변경 필요 안내 |
| 대시보드 | `templates/accounts/home.html`, `static/dashboard.js`, `employee-dashboard.js` | 관리자·직원 제목, 마지막 조회 표시, ‘오늘 재콜·방문예약’, 통화 결과 분포, 집계 기준 도움말, 고객 수·배정 횟수 단위 |
| 고객 목록·필터·이력 | `templates/customers/{manage,employee,filter,history,hard-delete}.html`, `static/{customer-grid,employee-grid,customer-query,customer-history,hard-delete}.js` | 저장·지금 저장·복구를 제목 행에 배치, 고객 추가, 검색 결과 인원, 실제 넘치는 표에만 스크롤 안내, 필터·이력 제목·버튼 정리 |
| 배정·계정 관리 | `templates/assignments/manage.html`, `templates/accounts/manage.html`, `static/assignments.js`, `users.js` | 분배 가능 고객 조회, 오늘 배정 회수의 대상·범위 설명, 이관 고객 안내, 변경 저장·비밀번호 재설정 버튼 |
| 업로드 | `templates/imports/upload.html`, `static/imports.js` | 단계형 영역, 등록 내용 확인과 등록 확정 구분, 검증 완료·등록 전 / 등록 완료, 엑셀 행 수와 등록 인원 구분 |
| 보고서·가이드 | `templates/ai/{admin,case,published}.html`, `static/{admin-ai,published-guide,employee-ai}.js` | 보고서 생성·초안 저장·직원에게 게시, 안내자료 변경 영향 확인, 인용 고객의 현재 기록과 요청 시점 구분, 게시 시각 표시 |
| 결과 상태·확인창 | `static/ui-messages.js`, `pending-operation.js`, `employee-queue.js`, `shared-ui.js`, `callback-action.js`, `deletion-action.js`, `deletion-notifications.js` 및 위 화면 스크립트 | 확정 실패와 응답 유실·서버 오류 구분, 같은 요청 재확인 유지, 공통 확인창·실제 동작 버튼·취소, 닫은 뒤 시작 버튼 초점 복귀 |
| 검증 | `tests/browser_common_ui.py`, `browser_dialog_helpers.py`, `ui_messages.test.mjs`, 관련 기존 브라우저 테스트와 `test_auth.py`, `test_p11.py` | 화면 목록·반응형·키보드·응답 유실 추가 검증, 기존 검증의 문구·선택자 갱신, 실행 요일에 의존하던 주간 보고서 표본 정리 |

`apps/`의 권한·서비스·대시보드 집계 코드는 변경하지 않았습니다. 현장 범위, 직원 자동 저장, 관리자 수동 저장, 재시도의 요청 식별자, 필터·페이지네이션, 회수·복구·영구 삭제, 업로드 확정, 보고서 생성·게시 절차를 유지했습니다. ‘오늘 배정 유지’에서 회수 고객 제외 및 재배정 후 최종 담당자 집계는 기존 회귀 테스트로 확인했습니다.

## 화면 확인

다음 경로를 로컬 가상 계정으로 열고 제목·메뉴·주요 작업·결과 문구를 확인했습니다. 주요 화면은 1440px, 390px, 320px에서 확인했습니다.

| 화면 | 경로 | 주요 작업 |
|---|---|---|
| 로그인 / 비밀번호 변경 | `/auth/login`, `/auth/password?change=1` | 로그인 / 비밀번호 변경 |
| 관리자 대시보드 | `/app/admin` | 새로고침 |
| 직원 대시보드 | `/app/employee` | 새로고침, 고객 열기 |
| DB 관리 / 휴지통 | `/app/admin/customers`, `/app/admin/trash` | 저장 / 복구 |
| 오늘 할 일 / 나의 DB | `/app/employee/today`, `/app/employee/mine` | 지금 저장, 목록 새로고침 |
| DB 분배·회수 | `/app/admin/assignments` | 분배 가능 고객 조회, 분배, 선택 직원의 오늘 배정 회수 |
| 사용자 관리 | `/app/admin/users` | 사용자 추가, 변경 저장, 비밀번호 재설정 |
| 엑셀 업로드 | `/app/admin/imports` | 양식 다운로드, 파일 검증, 등록 내용 확인, 등록 확정 |
| AI 보고서 | `/app/admin/ai` | 보고서 생성, 초안 저장, 직원에게 게시 |
| 보고서에 인용된 고객 | `/app/admin/ai/cases/<고객 ID>` | 현재 기록 확인, AI 보고서로 돌아가기 |
| 팀 상담 가이드 | `/app/guides` | 현장 선택, 새로고침 |

- 키보드: 메뉴 Enter·방향키·Tab·Escape, 필터와 고객 이력·계정 확인창의 열기·닫기, 닫은 뒤 시작 버튼 초점 복귀.
- 반응형: 페이지 전체 가로 넘침 방지, 검색줄 줄바꿈, 넓은 표 내부 스크롤, 좁은 확인창의 버튼 줄바꿈.
- 상태: 기본·빈 목록·조회 실패·저장 성공·서버 반영 후 응답만 유실된 상태·동일 요청 재확인.
- 알림 닫기: 취소 시 알림 유지, 확정 시 화면 알림만 제거, 이미 서버에서 처리한 배정은 유지.
- AI는 테스트 전용 가짜 응답으로 생성·검토·게시·조회·무효화 흐름을 확인했습니다.

## 실행 결과

서버·브라우저 테스트는 중복을 제외한 **339개가 최종 통과**했습니다. 초기 대규모 실행은 318개 중 310개 통과·8개 실패였으며, 실패 항목을 수정해 관련 모듈을 재실행했습니다. 이후 공통 확인창 검증을 추가했습니다. 각 실행의 원래 결과와 테스트별 최종 상태를 JSON에 함께 보존했습니다.

최종 테스트 집계와 각 실행의 상세 결과는 [검증 요약 JSON](../outputs/ui-consistency-20261116/verification-summary.json)에 기록합니다. 초기 실패 기록도 원래 실행 디렉터리에 보존하며, 재검증으로 덮어쓰지 않습니다.

- `node --test --test-reporter=dot tests/*.test.mjs`: 50개 통과.
- 모든 `static/*.js`의 `node --input-type=module --check`: 통과.
- `git diff --check`: 통과.
- Django 시스템 점검 및 `makemigrations --check --dry-run`: 통과.
- Django·Playwright 관련 검증은 `scripts/run_final_verification.py test`로 실행했습니다. 실행별로 독립된 테스트 DB와 결과 디렉터리를 사용했습니다.

실행한 주요 모듈:

```text
tests.test_auth
tests.test_dashboard_current_state tests.test_dashboard_reports tests.test_employee_dashboard
tests.test_grid_filters tests.test_customer_create tests.test_customer_metadata tests.test_site_rename
tests.test_consultations tests.test_employee_actions tests.test_imports
tests.test_p4 tests.test_p7 tests.test_p11 tests.test_p12
tests.browser_ui tests.browser_dashboard_actions tests.browser_employee_dashboard tests.browser_common_ui
tests.browser_p2 tests.browser_p4 tests.browser_p6 tests.browser_p7
tests.browser_employee tests.browser_grid_filters tests.browser_customer_create tests.browser_customer_metadata
tests.browser_context_navigation tests.browser_request_id
tests.browser_p10 tests.browser_p11 tests.browser_p12
```

기존 테스트의 문구 변경은 고객 수 ‘명’, 배정 횟수 ‘회’, 엑셀 원본 ‘행’, 실제 버튼 이름에 맞췄습니다. 기존에 없어진 직원 대시보드 요소·열 필터 버튼을 찾던 검증은 기준 커밋에 있는 상담 저장 수치·공통 상세 필터로 갱신했습니다. 주간 보고서 표본은 실행 요일과 관계없이 해당 보고서 주간에 들어가게 했고, 작업 이력 시각은 해당 작업을 찾아 비교합니다. 검증 대상 기능을 삭제하거나 건너뛰지 않았습니다.

## 대표 화면 캡처

- [관리자 대시보드](../outputs/ui-consistency-20261116/admin-dashboard.png)
- [직원 대시보드 · 모바일](../outputs/ui-consistency-20261116/employee-dashboard-mobile.png)
- [고객 목록 · 데스크톱](../outputs/ui-consistency-20261116/customer-list.png) / [모바일](../outputs/ui-consistency-20261116/customer-list-mobile.png)
- [로그인 · 모바일](../outputs/ui-consistency-20261116/login-mobile.png)
- [상세 필터 · 모바일](../outputs/ui-consistency-20261116/filter-mobile.png) / [고객 이력 · 모바일](../outputs/ui-consistency-20261116/history-mobile.png)
- [공통 확인창 · 모바일](../outputs/ui-consistency-20261116/action-confirm-mobile.png)
- [저장 결과 미확인](../outputs/ui-consistency-20261116/save-unconfirmed.png)
- [보고서 초안](../outputs/ui-consistency-20261116/report-draft.png) / [직원 게시 가이드 · 모바일](../outputs/ui-consistency-20261116/published-guide-mobile.png)

전체 화면별 캡처와 테스트별 네트워크 관찰 기록은 각 `.local/verification-runs/<실행 ID>/artifacts/`에 있습니다. 모두 가상 데이터입니다.

## 확인하지 않은 항목

- 운영 서버 반영 및 운영 데이터·실제 계정에서의 동작.
- 실제 AI 제공자 호출·실제 모델 결과 품질.
- 실제 모바일 기기 및 Safari·Firefox. 화면 검증은 로컬 Chromium의 데스크톱·좁은 뷰포트를 사용했습니다.
- 브라우저가 직접 표시하는 페이지 이탈 경고의 플랫폼별 모양. 앱에서 여는 확인창·안내창은 공통 UI를 사용하며, 브라우저의 이탈 보호 동작은 유지합니다.

## 변경 파일 전체 목록

```text
docs/UI_CONSISTENCY_20261116.md
static/admin-ai.js
static/app.css
static/assignments.js
static/callback-action.js
static/customer-columns.js
static/customer-grid.js
static/customer-history.js
static/customer-query.js
static/dashboard.js
static/deletion-action.js
static/deletion-notifications.js
static/employee-ai.js
static/employee-dashboard.js
static/employee-grid.js
static/employee-queue.js
static/hard-delete.js
static/imports.js
static/pending-operation.js
static/published-guide.js
static/shared-ui.js
static/ui-messages.js
static/users.js
templates/accounts/home.html
templates/accounts/login.html
templates/accounts/manage.html
templates/accounts/password.html
templates/ai/admin.html
templates/ai/case.html
templates/ai/published.html
templates/assignments/manage.html
templates/base.html
templates/customers/employee.html
templates/customers/filter.html
templates/customers/hard-delete.html
templates/customers/history.html
templates/customers/manage.html
templates/customers/query-toolbar.html
templates/imports/upload.html
tests/browser_common_ui.py
tests/browser_context_navigation.py
tests/browser_customer_create.py
tests/browser_customer_metadata.py
tests/browser_dashboard_actions.py
tests/browser_dialog_helpers.py
tests/browser_employee.py
tests/browser_employee_dashboard.py
tests/browser_gemini.py
tests/browser_grid_filters.py
tests/browser_http_environment.py
tests/browser_imports.py
tests/browser_ip_https.py
tests/browser_p10.py
tests/browser_p11.py
tests/browser_p12.py
tests/browser_p13.py
tests/browser_p2.py
tests/browser_p4.py
tests/browser_p6.py
tests/browser_p7.py
tests/browser_request_id.py
tests/browser_ui.py
tests/test_auth.py
tests/test_p11.py
tests/ui_messages.test.mjs
outputs/ui-consistency-20261116/*.png
outputs/ui-consistency-20261116/verification-summary.json
```
