# 고객정보 빈 값과 필터

2026-11-13 KST 최신 사용자 요청 기준. 관리자 DB 관리·휴지통과 직원 오늘 할 일·나의 DB는 같은 빈 값 표시와 필터 화면을 사용한다.

## 빈 값 표시와 편집

미입력 고객명·선택값·문자·날짜는 `-`로 표시한다. 계약여부의 `UNKNOWN`도 `-`다. 신규 항목의 기존 빈 값 기본값을 유지하며 DB에 표시용 하이픈을 일괄 저장하지 않는다.

- 계약여부·통화결과·주택보유상황·루트: 선택 목록 첫 항목인 `-`를 선택해 다시 비운다.
- 고객명·상담내용·거주지·비고·관리자 비고: 입력 내용을 지운 뒤 저장한다.
- 방문·재콜 날짜: 날짜 입력 내용을 지워 저장한다. 재콜 날짜 삭제는 일정 취소이며 완료 처리는 별도다.
- 관리자는 **저장**, 직원은 **지금 저장** 또는 기존 자동 저장으로 확정한다.

연락처는 계속 필수다. 관리자 비고는 관리자만 조회·수정하며 직원은 현재 담당 고객의 허용된 항목만 수정한다. 담당자 변경·할당일·휴지통 읽기 전용 등 기존 권한을 유지한다. 명시적으로 문자 `-`를 입력한 일반 텍스트와 실제 미입력은 DB에서 서로 다르므로, 문자를 비우려면 내용을 지운다.

## 필터 사용법

열 제목의 `▾`로 연다. **적용**은 조회 성공 후 확정하고, **취소/Esc**는 변경 없이 닫는다. **이 열 해제**는 해당 열만 지우고, 표 위 **필터 초기화**는 전체 열 조건을 지운다. 여러 열은 AND 조건이며 기존 검색어·현장·본인 담당 범위도 함께 적용한다. 적용한 조건을 표 위에 요약하고 활성 열 버튼을 강조한다.

| 열 종류 | 제공 조건 |
|---|---|
| 계약여부·통화결과·주택보유상황·루트 | 전체, `-`, 고정 선택값, 권한 범위의 이전 값. 일치하는 값만/선택한 값 제외 |
| 고객명·연락처·담당직원명 | 전체, 선택한 값만, 선택한 값 제외, 값 없음/있음. 후보 검색·100개씩 페이지 이동·현재 페이지 선택/해제 |
| 상담내용·거주지·비고·관리자 비고 | 내용 포함, 전체, 값 없음/있음 |
| 방문예약·재콜·할당 날짜 | 날짜 범위, 전체, 값 없음/있음. 오늘·최근 7일·이번 달 빠른 선택 |

후보 검색은 후보 목록을 좁히며 고객 필터 자체는 **적용**으로 확정한다. 선택은 후보 검색·페이지 이동 후에도 유지된다. ‘이 페이지 선택’은 보이는 후보만 추가하고 다른 페이지의 선택을 보존한다. ‘전체’를 선택해 적용하면 해당 열 조건이 해제된다. 연락처 후보 검색은 화면처럼 하이픈·공백이 들어간 형식도 지원한다. 이전 자유문자 루트 필터가 남아 있으면 사용자가 값을 바꾸기 전까지 유지한다.

날짜는 한국 시간 기준이며 종료일의 마지막 시각도 포함한다. 최근 7일은 오늘 포함 7일이다. 종료일이 시작일보다 빠르면 전송 전에 안내한다. 빠른 선택 날짜는 브라우저 시계를 KST로 변환하므로 PC 시계도 정확해야 한다.

적용·해제 조회가 실패하면 기존 필터와 그리드를 유지하고 모달에서 재시도한다. 후보 조회 실패는 다시 검색할 수 있으며 진행 중 중복 조회/적용을 제한한다. 닫힌 필터의 늦은 응답은 다음 필터에 반영하지 않는다. 후보 조회는 10초 지연 시 재시도 안내를 표시한다. 이 제한은 목록 조회 전체의 제한 시간을 변경하는 것은 아니다.

## 검증과 재현

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
