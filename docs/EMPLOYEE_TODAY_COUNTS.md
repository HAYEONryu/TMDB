# 직원 오늘 신규 고객 수와 현장 이동 수정

2026-11-12 KST. 사용자 확인에 따라 직원 대시보드의 **오늘 새로 받은 고객**은 한국 날짜 기준으로 오늘 시작된 현재 할당 중, 삭제되지 않았고 현재도 본인이 담당하는 고객 수로 표시한다. 회수·다른 직원 이관·휴지통 이동 후에는 다음 통계 조회/새로고침에서 제외한다. 저장 여부로 제외하지 않으며 이전 날짜에 할당된 고객은 신규 수에 포함하지 않는다.

## 원인과 수정

이전 직원 요약 카드는 `/api/dashboard`의 `assigned_today_unique`를 표시했다. 이 필드는 당일 배정 이력의 고유 고객 수이므로 회수된 고객도 포함했다. 오늘 할 일 목록은 본인의 현재 할당만 조회하므로 카드 1건·목록 0건이 가능했다. 사용자는 실제 사례가 회수된 고객이라고 확인했다.

직원 요약 카드를 기존 서버 필드 `current_assignment_today_held`에 연결하고 설명을 ‘오늘 배정받아 현재 담당 중인 고객’으로 바꿨다. 상세 통계의 기존 이력은 ‘오늘 배정 이력 (회수·이관·삭제 포함)’으로 명시한다. 원본 배정 이력과 기존 API 집계 필드는 보존하며 관리자 배정 이력 통계의 의미도 유지한다. DB migration은 없다.

별도 재현 검사에서 대시보드의 비기본 현장 선택이 ‘오늘 할 일’/‘나의 DB’ 링크로 전달되지 않는 문제도 발견했다. 직원 메뉴·바로가기에서 비기본 현장의 `site_id`를 이어 전달하고, 대시보드도 전달받은 현장을 조회한다. 기본 현장 선택으로 돌아오면 기본 경로를 사용한다. 전역 기본 현장 설정이나 서버의 현재 담당자 권한 조건을 변경하지 않는다.

## 실제 실행한 로컬 검증

별도 PostgreSQL 테스트 DB·가상 사용자·Chromium으로 최종 7개 고유 검사가 통과했다. 실제 고객정보·외부 AI 호출·서버 DB 변경·실제 서버 배포는 수행하지 않았다.

- 회수 후 카드 2→1건, 이관 후 1→0건, 오늘 할 일 0건, 신규 할당 후 1건, 휴지통 이동 후 0건을 확인했다. 상세 배정 이력 3건은 보존된다.
- 기본 현장에 현재 담당 고객 0명, 다른 현장에 1명을 둔 상태에서 대시보드 → 오늘 할 일 → 나의 DB → 대시보드 → 바로가기의 현장과 고객 수가 이어진다. 기본 현장으로 돌아오면 현재 담당 0건을 표시한다.
- 로컬 Caddy TLS를 통과하는 직원 대시보드 → 비기본 현장 선택 → 오늘 할 일 → 편집·저장이 성공했다. 임시 내부 CA 검증 예외는 테스트 브라우저에만 사용했고 실제 공인 인증서 발급/갱신 검사가 아니다.
- 기존 직원 모바일/기본 현장 탐색, HTTP 조회 전용의 현장·필터·세션 종료, KST 당일/지난 재콜 합집합과 우선순위, 서버의 배정 이력/현재 보유 집계 검사가 통과했다.

실행별 원본은 `.local/verification-runs/<실행ID>/results.json` 등에 보존한다.

| 실행 ID | 결과 |
|---|---|
| `20261112T142534992311Z-35004eb2c40045df93aef829a0b3aa38` | 현장 이동 문제 재현 1개 실패. 이동 후 선택 현장이 다른 결함을 확인한 수정 전 기록 |
| `20261112T142704837575Z-a4a009bb9e8049549cadfd53ad84623d` | 현장 전달 수정 및 관련 기존 검사 4개 통과 |
| `20261112T142902142456Z-54d33ca1adc143479e23e9da029c0e0a` | 사용자 확정 기준 적용 후 회수/이관/삭제·현장 이동·HTTPS/HTTP·서버 집계/재콜 검사 6개 통과 |

세 실행 모두 `source_unchanged_during_run=true`다. 과거 통과 기록을 현재 결과로 대체하지 않는다. 검증 후 테스트 DB 프로세스를 종료했다.

재현할 때는 로컬 검수 도구·Chromium이 준비된 환경에서 다음을 사용한다.

```bash
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label employee-today tests.browser_ui.DoodreamUIBrowserTests.test_employee_today_card_excludes_recall_transfer_and_trash_but_preserves_history tests.browser_ui.DoodreamUIBrowserTests.test_employee_selected_dashboard_site_carries_to_today_and_mine tests.browser_ip_https tests.browser_http_environment.EmployeeEnvironmentBrowserTests.test_http_today_site_selection_filters_and_session_end tests.test_p5.EmployeeTests.test_today_kst_boundary_callback_union_priority_and_no_duplicates tests.test_p6.P6Tests.test_dashboard_unique_assignments_current_results_and_explicit_denominators
.venv/bin/python scripts/run_final_verification.py stop
```

## HTTPS 서버 반영

사용자가 HTTPS 설정 성공을 보고한 기존 `/root/TMDB` 서버용이다. 저장 중인 사용자가 있다면 저장 완료를 확인한 뒤 재시작한다. DB migration이나 AI 시작 없이 웹·스케줄러 이미지만 갱신한다. 기존 HTTPS 프록시·비밀 파일·DB 볼륨은 유지한다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh build web scheduler &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh ps
```

배포 후 HTTPS 화면에서 강력 새로고침하고 회수된 직원의 ‘오늘 새로 받은 고객’이 제외되는지 확인한다. 실제 서버의 해당 계정·데이터 결과는 아직 직접 검증하지 않았다. 이전 날짜의 미완료 재콜은 오늘 할 일에 포함되므로 신규 수와 오늘 할 일 전체 행 수가 항상 같아야 하는 것은 아니다.
