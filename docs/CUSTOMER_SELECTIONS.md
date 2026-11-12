# 고객 항목 선택 목록

2026-11-12 KST 최신 사용자 승인. 관리자·직원의 고객 그리드에서 다음 고정 목록을 사용한다. 한 항목에는 한 값만 선택하며 자유 문자는 새 값으로 저장할 수 없다.

| 항목 | 표시 순서대로 선택값 |
|---|---|
| 계약여부 | 청약 · 청약해지 · 계약해지 · 계약 |
| 루트 | 티엠 · 사이드 · 대표콜 · 개인관리 · 워킹 · 재방 |
| 주택보유상황 | 무주택 · 1주택 · 다주택 · 생애최초 |
| 통화결과 | 가망고객 · 삭제 요망 · 거절 · 다음현장 연락 요청 · 부재 |

기존 연락처만 필수인 등록 정책은 유지한다. 미입력 자료를 억지로 특정 값으로 바꾸지 않으며 편집할 때 목록에서 선택한다. 직원 편집은 기존 HTTPS/브라우저 지원 조건을 유지한다. HTTP는 조회 전용이다.

‘삭제 요망’ 선택 자체는 통화결과만 저장한다. 실제 삭제는 기존 행별 삭제 요청 → 관리자 승인 → 휴지통 절차를 따른다. 청약·해지 상태를 계약 건수로 더하지 않으며 계약 건수는 기존처럼 현재/조회 기간의 `CONTRACTED` 상태를 기준으로 센다.

## 기존 자료와 코드

저장된 예전 재통화·방문예약·방문·재방, 미계약, 전세/자가 같은 주택상황 및 자유 입력 루트는 삭제하거나 새 의미로 자동 매핑하지 않는다. 그리드·이력은 현재 목록 밖의 값을 `이전값: ...`로 구분한다. 원래 값 그대로 상담 등 다른 항목을 저장할 수 있지만, 다른 고객에게 새로 입력하거나 새 목록으로 바꾼 뒤 다시 옛 값으로 입력할 수는 없다.

2026-11-12 추가 요청으로 부재(`NO_ANSWER`)를 입력·필터·엑셀·AI 허용 목록에 다시 포함한다. 기존 부재 기록을 그대로 사용하며 이 추가에는 새 migration이 없다. 부재 추가 검증은 가상 DB·Chromium의 9개 검사 통과(실행 ID `20261112T120924894679Z-041fc728ed94413599b866e3b7536bd9`). 관리자/직원 저장·필터 목록과 공통 서버/AI 선택값을 확인했고 실행 중 소스 변경은 없었다. 실제 서버 반영과 외부 AI 호출은 수행하지 않았다.

기존 관심 코드 `INTERESTED`는 가망고객 표시로 재사용한다. `REJECTED`(거절)·`CONTRACTED`(계약)도 기존 코드를 유지한다. 신규 코드는 통화결과 `DELETE_REQUEST`·`NEXT_SITE`, 계약여부 `SUBSCRIBED`·`SUB_CANCELLED`·`CONTRACT_CANCELLED`다. `UNKNOWN`은 기존 미입력 계약 상태 보존용이며 새 선택 목록에 추가하지 않는다.

`customers.0004_customer_selection_options`는 통화결과·계약여부의 저장 길이를 24자로 확장하고 기존/신규 코드를 함께 보관할 DB 제약을 적용한다. 주택보유상황·루트의 모델 선택 메타데이터도 갱신한다. 기존 고객·상담·할당·원문 값을 수정하는 데이터 migration은 없다. 기존 값 보존을 위해 DB는 옛 값도 읽을 수 있고, 새 입력 제한은 공통 서버 서비스가 검사한다. 새 상태가 저장된 후에는 옛 길이·제약으로 무조건 되돌릴 수 없다.

AI 요청의 허용 enum과 로컬 검증도 새 목록을 사용한다. 청약·해지 추천에는 완료/접수 등 명시적 근거를 요구하며 예정·검토 문구로 상태를 확정하지 않는다. 전세 같은 거주 형태만으로 무주택·1주택 등을 추정하지 않고 보유상황의 명시적 인용 근거를 요구한다. 외부 호출 없이 가짜 AI로 확인했고 활성화/무료 확인 설정은 바꾸지 않았다.

## 엑셀

다운로드 양식은 기존 6열을 유지하며 D열만 **주택보유상황**으로 바꾼다. D열에 네 선택값의 드롭다운·입력 안내·오류 안내를 제공한다. 루트는 기존 승인대로 엑셀 열에 추가하지 않고 등록 후 표에서 선택한다.

기존 ‘주택상황’ 제목의 6열/9열 파일도 읽지만 새 업로드 값은 현재 선택 목록으로 검증한다. 예전 자가·전세 등의 값을 임의로 무주택·1주택으로 추정하지 않고 해당 행의 오류를 표시한다. 검증 완료 뒤 확정할 때도 선택값을 재검사하므로 배포 전에 검증한 파일은 새로 검증하는 것을 권장한다.

## 최신 빈 값·필터 동작

2026-11-13 추가 요청에 따라 빈 선택값은 `-`로 표시하고 편집 목록에도 `-`를 제공해 기존 값을 지울 수 있다. 필터의 최신 화면·값 없음/있음·제외·날짜·후보 검색·실패 복원 기준과 검증은 [고객정보 빈 값과 필터](GRID_FILTERS.md)를 따른다. 아래 2026-11-12 검증 설명은 당시 기록으로 보존한다.

## 필터와 열 순서

2026-11-12 추가 요청에 따라 계약여부·통화결과·주택보유상황·루트 필터도 **드롭다운 select**로 선택한다. 목록의 ‘전체’로 해당 조건을 해제하거나 ‘빈 값’으로 미입력을 찾을 수 있다. 네 고정 목록은 해당 값의 고객이 없어도 표시한다. 권한 범위에 저장된 이전 값은 별도 그룹으로 제공하며 후보가 많으면 ‘이전값 더 보기’로 이어서 조회한다. 필터를 다시 열면 선택한 값을 유지하고 ‘이 열 초기화’로 해제할 수 있다.

루트 드롭다운은 정확히 같은 값으로 검색한다. 예를 들어 ‘티엠’ 선택은 ‘티엠 소개’ 같은 이전 자유문자 값을 포함하지 않는다. 직원에게 다른 직원의 이전 값 후보나 고객을 제공하지 않는다. HTTP 조회 전용 화면에서도 이 필터를 사용할 수 있다.

상담내용 열은 관리자·직원 모두 주택보유상황 바로 뒤로 이동했다. 해당 구간은 **고객 거주지 → 주택보유상황 → 상담내용 → 루트 → 비고**다. 전체 순서는 [고객 그리드 문서](CUSTOMER_GRID_EDITING.md)를 따른다. 이번 필터·열 순서 변경에 추가 migration은 없으며 기존 0004 적용 조건은 유지한다.

필터·열 순서 변경 영향 범위는 로컬 가상 DB와 실제 Chromium의 54개 검사로 확인했다. `20261112T021848228341Z-12bb23d7d9ee4859b821d2911d77da77`은 54개 중 51개 통과, 드롭다운의 접근성 이름 식별이 불명확해 브라우저 3개 실패했다. label 연결과 aria-label을 명확히 한 뒤 `20261112T022127325092Z-2fe2dd6a0e334ed1b15f8ab3bbac577a`에서 해당 검사와 HTTP 조회를 포함한 4개가 통과했다. 선택·재진입·초기화·빈 계약 상태·이전값·직원 권한·정확한 열 순서를 검증했고 실행별 소스 불변을 확인했다. 실패 기록은 덮어쓰지 않고 보존한다. 이 기록은 아래 최초 선택값 변경 검증과 별개다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label choice-filters-column-order \
  tests.test_customer_choices.CustomerChoiceTests tests.test_customer_metadata.CustomerMetadataTests \
  tests.test_p2 tests.browser_customer_metadata \
  tests.browser_p2.AdminGridBrowserTests.test_grid_paging_filters_manual_save_trash_restore_site_default_and_mobile \
  tests.browser_employee.EmployeeBrowserTests.test_filters_mobile_dates_and_visual_evidence \
  tests.browser_http_environment.EmployeeEnvironmentBrowserTests.test_http_today_site_selection_filters_and_session_end
.venv/bin/python scripts/run_final_verification.py stop
```

## 최초 선택값 검증 기록

분리된 PostgreSQL 17·가상 사용자/고객과 Chromium을 사용했다. 실행별 소스 변경 없음과 결과를 `.local/verification-runs/<실행ID>/`에 보존한다. 운영 DB·개발/데모 DB·실제 고객정보·실제 AI 호출·외부 배포는 사용하지 않았다.

| 실행 ID | 결과 |
|---|---|
| `20261112T020426847470Z-f735920bf2f84cbebfa62c4b328f6984` | 변경 영향 173개 중 169개 통과. 네 목록의 관리자/직원 편집·서버/엑셀 검증·migration 보존·기존 AI/통계 흐름 통과. 이전 주택 자유 입력/명칭을 가정한 브라우저 검사 3개와 테스트 문자열 교체로 잘못 바뀐 메시지 기대값 1개 실패 |
| `20261112T020733084693Z-7c01ac02ce6648f6bf63155fff9d8805` | 자유 입력 오류 검사를 고객 거주지로 옮기고 새 열 제목을 반영한 뒤 관련 15개 중 14개 통과. 추가된 청약/해지 AI 근거·정확한 제공자 enum, 기존 통합 7개와 migration 복구 확인 포함. 메시지 기대값 오타 1개는 남음 |
| `20261112T020900443431Z-4d0cb46834a04b7998f90e27e01a5fc0` | 위 기대값 오타 수정 후 해당 현장명·미저장 상담 보호 검사 재실행 통과 |
| `20261112T021315985176Z-885598246eb9484b930b447e9b894d3d` | 전세 기록만으로 무주택을 추천하는 것을 막고 명시적 확인 근거일 때만 추천하는 가짜 AI 검사 통과 |
| `20261112T020526258481Z-251719f21c7a4a1489ef514a54ae790e` | Django 시스템 검사·migration drift 통과 |

현재 범위의 중복 제외 184개 검사에 통과 근거가 있으며 모두 한 실행에서 통과했다고 표시하지 않는다. 작업 트리의 기존 미커밋 업로드 진단 검사도 포함한 결과이고 관련 기존 작업은 별도 보존한다. 새 빈 테스트 DB 전체 migration과 0003 가상 DB의 예전 값 보존·긴 새 코드 저장을 확인했다. 실제 운영 반영·서버 성능은 별도 확인 대상이다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label customer-selections \
  tests.test_customer_choices tests.test_p2 tests.test_customer_metadata tests.test_imports \
  tests.test_p9 tests.test_p10 tests.test_dashboard_reports tests.test_p8 \
  tests.test_live_contact_policy.LiveContactMigrationTests \
  tests.browser_customer_metadata tests.browser_employee tests.browser_p2
.venv/bin/python scripts/run_final_verification.py stop
```

## 서버 반영

현재 필요한 migration은 `0004_customer_selection_options`까지다. 기존 0003이 미적용이면 함께 적용되며, 이미 0004가 적용됐다면 추가 DB 변경 없이 이미지와 웹·스케줄러를 갱신한다.

복사·붙여넣기 명령은 [우분투 서버 최신 코드 반영 명령어](SERVER_UPDATE_COMMANDS.md)에 모았다. 현재 DB의 새 백업과 별도 DB 복구 확인 후 **최신 코드·이미지 준비 및 계획 확인 → 쓰기 중단·migration·재시작 → 브라우저 확인** 순서로 수행한다. 이 문서를 작성하면서 실제 서버는 변경하지 않았다.
