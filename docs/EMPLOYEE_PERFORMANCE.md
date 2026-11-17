# 직원 통화·월간 일별 실적

2026-11-17 KST. 현재 `main`의 직원 대시보드·상담 저장·상담 이력·방문예약을 확인하고 구현했다. 작업 시작 HEAD는 `1079c71`이며 기존 미커밋 문서 정리를 보존했다. 운영 데이터·계정·전화 시스템·외부 AI를 사용하지 않았다.

## 확인한 기존 데이터와 선택

기존 `Customer.call_result`는 고객의 최종 상태이며 `ConsultationRevision`은 실제 수정 저장 이력이다. 둘 다 발신 한 번을 나타내지 않는다. 전화 시스템 연동·개별 발신/연결 이력은 없었다. `Customer.visit_at`은 방문예약 날짜이며 실제 방문일이 아니다. 이전 `VISITED`·`REVISITED` 상태에도 확정된 실제 방문일이 없어 방문 수로 바꾸지 않았다.

사용자에게 최소 기록 방식을 제안했고 **통화·실제 방문 기록 추가**를 선택받았다. 신규 `CustomerActivity`에 통화 한 번 또는 실제 방문을 별도로 기록한다. 가망은 저장소의 기존 `INTERESTED`(가망고객) 분류를 재사용한다.

## 데이터 출처와 계산

| 화면 지표 | 출처·계산 |
|---|---|
| 오늘 통화 시도 | `CustomerActivity(kind=CALL).occurred_at`의 한국 날짜가 오늘인 기록 수. 같은 고객의 별도 발신은 각각 1콜 |
| 오늘 연결된 통화 | 위 기록 중 `connection=CONNECTED`인 기록 수. `NOT_CONNECTED`(부재·미응답 포함)·`UNKNOWN`은 제외 |
| 월간 콜 수 | 같은 발신 기록을 한국 날짜별로 집계. 오늘 행과 상단은 같은 응답·읽기 스냅샷의 동일한 기록을 사용 |
| 가망고객 수 | `consultation_saves()`의 직접 저장·실제 적용한 AI 저장 중 `after_values.call_result=INTERESTED`인 기록을 실제 `actor`와 `saved_at` 한국 날짜별 고유 고객으로 집계. 이름·연락처·관리자 비고만 정정, 무변경·업로드·기초/시스템 기록은 제외 |
| 방문고객 수 | `CustomerActivity(kind=VISIT).visited_on`의 실제 방문일별 고유 고객 수. 기록을 입력한 직원에게 귀속. 같은 고객의 같은 날짜 방문 기록은 여러 건이어도 1명 |

모든 지표는 선택 현장·로그인 직원 본인만 조회한다. 직원 ID를 요청 인수로 받지 않는다. 고객의 현재 담당자나 최종 상태로 과거 실적을 재귀속하지 않는다. 회수·재배정·휴지통 이동 후에도 원래 기록 직원의 실적을 유지한다. 기존 영구 삭제에서는 고객/현장과 연관된 기록을 함께 삭제하므로 영구 삭제한 고객의 실적은 남기지 않는다.

## 기록 방법과 중복 방지

- 직원 ‘오늘 할 일’·‘나의 DB’의 작업 칸, 대시보드 고객 목록·오늘 일정의 **통화·방문 기록**을 연다.
- 통화는 한국 시각과 연결·미연결·확인 불가를 선택하고 **통화 기록**을 누른다. 같은 고객에게 두 번 전화했다면 각각 기록한다. 연결 불명확을 연결로 간주하지 않는다.
- 실제 방문은 **실제 방문일**을 입력하고 **실제 방문 기록**을 누른다. 예약일·상담 수정일로 대체하지 않는다. 미래 또는 기록 도입일 이전 날짜는 거절한다.
- 서버가 현재 본인 담당·현장·배정·계정 상태를 다시 확인한다. 새 기록은 현재 담당 고객에만 가능하다. 기존 성공 요청의 동일 재확인은 담당 변경 후에도 본인의 결과만 돌려준다.
- 기록 요청 ID에 직원별 DB 유일 제약을 적용하고 업무 쓰기 잠금을 재사용한다. 이중 클릭·경합·응답 유실 재시도는 동일 요청 ID로 한 번만 기록한다. 같은 ID로 다른 내용을 보내면 거절한다.
- 응답을 받지 못하면 **기록 결과 다시 확인**을 사용한다. 세션 저장소에는 직원별 요청 메타데이터만 남기고 고객명·전화번호·상담 내용은 저장하지 않는다. 페이지를 새로고침해도 동일 요청으로 확인할 수 있다. 브라우저의 세션 저장소 사용이 거절되면 현재 페이지의 메모리에서만 재확인할 수 있으므로 새로 기록하기 전에 최근 내 기록을 확인한다.

통화·방문 기록은 직원이 입력한 근거이며 자동 전화 연동이 아니다. 통화마다 빠짐없이 기록해야 실제 업무 전체와 맞는다. 기록 자체는 기존 고객 결과·예약·상담 저장·자동 회수 진행 상태를 변경하지 않는다. 가망 분류 등 상담 변경은 기존 상담 편집·저장으로 별도 반영한다. 기존 암호화 자동 저장·수동 저장·기본 현장·권한은 유지한다.

## 조회 가능 범위와 빈 상태

이번 달을 기본으로 열며 월 입력으로 이전 달을 선택할 수 있다. 1일부터 월말까지 날짜순이고 미래 날짜는 **—**다. 집계 근거가 있는 날짜에 기록이 없으면 **0**, 도입 이전·시작일 미확인·결과 스냅샷 부족은 **집계 자료 없음**이다.

- 통화·방문은 migration에서 만든 `PerformanceTracking.started_at`의 한국 날짜부터다. 도입 당일은 일부 시간대의 기록이므로 화면에 일부 실적임을 설명하고 셀에도 표시한다. 도입 이전 달을 조회할 수는 있지만 이 두 지표는 자료 없음이다. 기존 상담 저장·예약으로 과거 실적을 채우지 않는다.
- 가망 이력의 시작은 상담 변경 감사 기록을 도입한 `consultations.0001_initial` 적용 시각이다. 도입일은 일부 실적일 수 있다. 감사 도입일보다 과거 시각의 이력이 일부 남아 있어도 그 사이 기간 전체의 완전성을 보장할 수 없어 도입일을 앞당기지 않는다. 해당 직원·현장의 실제 상담 저장에 결과 스냅샷이 빠진 날짜는 정확한 고유 고객 수를 확인할 수 없어 자료 없음으로 표시한다. 보관되지 않은 과거 상담을 현재 상태로 복원하지 않는다.
- 가장 이른 자료 월과 각 출처의 시작일을 화면에 표시한다. 같은 현장·월의 갱신 실패는 마지막 성공 결과를 유지한다. 최초 실패는 조회 실패이며 자료 없음/0과 다르다. 현장·월 변경과 늦은 응답은 이전 수치를 섞지 않는다.

## 변경 파일

| 영역 | 파일 |
|---|---|
| 기록 모델·DB 제약·도입 시점 | `apps/consultations/models.py`, `migrations/0003_performancetracking_customeractivity.py` |
| 기록 권한·검증·중복 방지·최근 내 기록 | `apps/consultations/activities.py` |
| 읽기 전용 월간 집계 API | `apps/operations/employee_performance.py`, `config/urls.py` |
| 기록 창·결과 재확인 | `templates/customers/activity-record.html`, `static/activity-recorder.js` |
| 대시보드·기존 고객 표 연결 | `templates/accounts/home.html`, `templates/customers/employee.html`, `static/employee-dashboard.js`, `static/employee-grid.js` |
| 월 선택·집계 상태·반응형 | `static/employee-performance.js`, `static/app.css` |
| 검증 | `tests/test_employee_performance.py`, `tests/browser_employee_performance.py` 및 기존 관련 검사 |

기존 DB 적용에는 새 consultation migration이 필요하다. 실제 서버·데모 DB에는 이번 작업에서 적용하지 않았다. 대상 백업·별도 복원 확인 뒤 같은 릴리스의 migration 계획 확인·적용·정적 파일 갱신·웹/스케줄러 재시작은 [기존 업데이트 절차](SERVER_UPDATE_COMMANDS.md)를 따른다. 업데이트 절차는 새 상담 migration도 포함하도록 전체 앱 `python manage.py migrate --plan` / `python manage.py migrate --noinput`으로 갱신했다.

## 로컬 검증

실행별 결과와 제한은 아래 최종 검증 기록에 추가한다. PostgreSQL 17 폐기용 DB·가상 계정·Chromium만 사용하고 기존 운영·개발·데모 DB는 사용하지 않는다.

최종 서버·브라우저 검사 **67개 모두 통과**, 실행 중 소스 변경 없음. 실행 ID는 `20261117T015832553459Z-688da35ec2fd438192785c26b12e3dfe`다. Node 기존 검사 **50개 통과**, Django 시스템·migration drift 검사도 통과했다(`20261117T015731364037Z-56f967664f414996bf90464001cf969b`). Python/JS 구문과 공백·문서 링크 검사를 통과했다.

- 같은 고객 2회 발신·1회 연결, 미연결·확인 불가 제외, 오늘 행과 상단 일치.
- 요청 재전송·동시 요청·서버 저장 후 응답 유실·페이지 새로고침 후 같은 요청 ID 재확인에서 중복 없음.
- 가망의 날짜별 고유 고객·실제 작성자, 이름/연락처/관리자 비고 정정·시스템/업로드 제외, 최종 상태가 달라져도 기록 당시 실적 유지.
- 실제 방문일 사용·같은 날 중복 제거·방문예약/이전 방문 상태 제외, 담당 변경·회수·휴지통 후 원래 직원 실적 유지.
- 한국 자정·UTC 날짜 차이·윤년 2월 말·월 경계·미래 날짜, 다른 직원/현장 수치 미노출·위조 요청/CSRF 차단.
- 기존 데이터 업그레이드 시 고객·상담 이력 보존, 가짜 과거 발신·방문 기록 생성 없음, 도입 시각 기록.
- 초기·빈 자료·조회 실패/재시도·마지막 성공 결과 유지·늦은 현장 응답 무시·월 선택, 기록 창 키보드 닫기/시작 버튼 초점 복귀, 1440/390/320px.

초기 API 검사에서는 재확인 응답의 시각 표현(KST/UTC) 불일치와 테스트용 세션/CSRF 준비 오류를 확인해 수정했다. 추가 업그레이드 검사에서는 모의 시계와 migration 기본값의 시계가 달라 실패했고, 도입 시각을 migration 실행 시 명시적으로 기록한 뒤 재검증했다. 초기 실패 기록은 원래 실행 디렉터리에 보존하며 최종 통과로 덮어쓰지 않았다.

[검증 요약](../outputs/employee-performance-20261117/verification-summary.json) · [데스크톱](../outputs/employee-performance-20261117/employee-performance-1440.png) · [390px](../outputs/employee-performance-20261117/employee-performance-390.png) · [320px](../outputs/employee-performance-20261117/employee-performance-320.png).

재현 명령:

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label employee-performance \
  tests.test_employee_performance tests.test_employee_dashboard tests.test_dashboard_current_state \
  tests.test_consultations tests.test_employee_actions tests.test_models \
  tests.browser_employee_performance tests.browser_employee_dashboard tests.browser_common_ui
.venv/bin/python scripts/run_final_verification.py check --label employee-performance-system
node --test --test-reporter=dot tests/*.test.mjs
.venv/bin/python scripts/run_final_verification.py stop
```

실제 전화 시스템·사용자의 실제 발신 누락 여부·실제 방문 사실·운영 서버 배포·운영 DB migration·공인 HTTPS는 확인하지 않았다. 직원이 입력한 사실의 범위를 넘는 자동 추정은 하지 않는다. 검증용 DB 프로세스는 작업 종료 시 중지한다.
