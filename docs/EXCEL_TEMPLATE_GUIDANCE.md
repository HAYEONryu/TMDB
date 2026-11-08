# 현재 고객 입력 양식과 텍스트 항목

2026-11-09 KST. 관리자 업로드 화면에서 내려받는 `TM_customer_template.xlsx`는 **A~F의 6열**이다. 고객명은 선택 입력이고 **연락처만 필수**다. 첫 행에는 제목과 입력 안내를 표시하며 데이터는 2행부터 입력한다. 녹색 헤더, 한 시트, 틀 고정, 필터, 빈 데이터 행과 텍스트 서식을 유지한다. 실제 고객정보나 예제 고객 행은 넣지 않는다.

| Excel 열 | 제목 | 입력 형식 |
|---|---|---|
| A | 고객명 | 선택 문자, 최대 100자. 앞뒤 공백 제거. 빈 칸 가능 |
| B | 연락처 | 필수 텍스트. 010 시작 11자리. 하이픈·공백은 정규화. 숫자로 저장해 소실된 앞자리 0은 추측하지 않음 |
| C | 고객 거주지 | 선택 자유 문자, 최대 200자. 앞뒤 공백 제거 |
| D | 주택상황 | 선택 자유 문자, 최대 200자. 앞뒤 공백 제거 |
| E | 비고 | 선택 문자, 최대 10,000자. 줄바꿈 가능. 기존 상담기타내용과 별도 |
| F | 관리자 비고 | 선택 문자, 최대 10,000자. 줄바꿈 가능. 관리자만 조회·수정 |

루트는 엑셀에 넣지 않고 등록 후 고객 표에서 입력한다. 최대 200자의 자유 문자다. 루트·비고·고객 거주지는 관리자와 현재 담당 직원이 조회·수정할 수 있다. 고객명·연락처를 저장 후 수정할 수 없는 기존 정책은 유지한다. 이름 없는 고객도 연락처로 검색할 수 있다.

관리자 비고는 직원의 표·고객 조회·저장/충돌 응답·상담 이력·대기열 복구 응답과 AI 입력에서 제외한다. 직원이 요청을 직접 조작해 수정하거나 필터·정렬·후보값으로 추론하려 해도 거절한다. 관리자에서 직원으로 권한이 바뀐 계정에는 과거 관리자 저장 응답을 재조회해도 비고를 제거한다. 관리자 비고만 수정한 경우 상담 진행으로 표시하지 않으며 직원 상담 이력과 AI 분석 기록에서도 제외한다.

모든 신규 고객은 미할당으로 등록한다. 새 양식의 비고는 `memo`, 기존 상담기타내용은 `notes`, 관리자 비고는 `admin_notes`로 별도 보존한다. 기존 상담과 삭제 승인 시 기존 상담기타내용에 날짜·삭제 문구를 덧붙이는 동작을 바꾸지 않는다.

6열 헤더의 메모와 2~10001행 셀 선택 안내에 상세 조건을 제공한다. 모든 열은 텍스트 입력이며 수식·매크로를 허용하지 않는다. 필수값·길이·현장별 연락처 중복(휴지통 포함)은 서버에서 검사한다. 첫 워크시트만 사용하며 10MB·빈 행 제외 10,000행 제한을 유지한다.

첫 줄의 열 제목과 순서를 검사하므로 설명 문구를 바꾸거나 제목만 남긴 파일도 읽을 수 있다. 이전의 정확한 9열 양식도 계속 읽는다. 이전 파일의 상담기타내용은 계속 기존 `notes`로 가져오며 새 비고로 옮기지 않는다. 이전 양식에서도 고객명은 선택 입력이다. 다른 열 순서·이름·추가 데이터는 거절한다.

## 적용

`customers.0002_customer_metadata` migration은 기존 이름·연락처·상담·주택상황·할당을 유지하고 네 필드를 빈 값으로 추가한다. 새 빈 테스트 DB 전체 migration 및 이전 `customers.0001`에 가상자료를 넣은 업그레이드를 검증했다. 기존 개발·데모 DB나 실제 서버 DB에는 이번 작업에서 적용하지 않았다.

서버 반영 순서:

1. 대상 서버·DB와 현재 이미지/커밋을 확인하고, 앱·스케줄러·AI 작업자의 쓰기를 중단한다.
2. [운영 문서의 암호화 백업·별도 DB 복원 검사](OPERATIONS.md)에 따라 적용 대상 DB를 백업하고 복구 가능성을 확인한다. 운영 DB를 복원 대상으로 쓰지 않는다.
3. 보호된 환경변수와 대상 DB가 준비된 같은 릴리스 환경에서 `python manage.py migrate --plan`으로 계획을 확인한 뒤 승인된 대상에 `python manage.py migrate --noinput`을 적용한다.
4. `python manage.py collectstatic --noinput`을 실행하고 웹·스케줄러를 새 코드로 재시작한다. Docker는 새 코드를 포함한 앱 이미지를 빌드하고 같은 이미지로 migration·정적 파일·앱을 반영한다. 기존 AI 비활성·무료 확인 설정은 바꾸지 않는다.
5. 관리자/직원 권한과 다운로드한 새 양식을 확인한다. 기존 양식 파일을 새 양식으로 덮어쓰지 않는다. 브라우저는 새 정적 파일이 반영되도록 새로고침한다.

역방향 migration은 새 네 필드를 제거하므로 입력한 새 자료가 사라진다. 문제 발생 시 쓰기를 중단하고 백업을 보존한 뒤 호환되는 코드와 별도 복원 경로를 검토한다. 실제 DB를 무조건 되돌리거나 덮어쓰지 않는다.

## 검증 기록

변경 범위 테스트 **226개 통과**: 백엔드 201개, Chromium 실제 화면 4개, Node 직원 저장 대기열 21개. Django 설정·migration drift 검사도 통과했다.

| 실행 ID (UTC) | 결과와 범위 |
|---|---|
| `20261108T155827012742Z-a5c17494e2e44220993cfbc27ae9cdc8` | 91개 통과. 신규 필드·직원 차단·과거 응답 보호·6/9열 업로드·분배/회수·DB 제약·이전 스키마 업그레이드 |
| `20261108T160033494133Z-89b0714c30f348fcb7ab1fb20333f23e` | 110개 통과. 고객 목록/필터·행 저장·직원 대기열·재콜·삭제/복구·AI·통계 회귀 |
| `20261108T160006854584Z-29e93a70b7344914b4672ffb2368ad4d` | 새 6열 업로드→관리자/직원 편집→이력 비공개 흐름, 기존 100초 저장 흐름 통과. 기존 업로드 검사 1개는 고객명 필수라는 이전 테스트 가정 때문에 실패 |
| `20261108T160110962576Z-ab720bc0b0794b428f7dbc834b10e01e` | 위 테스트 가정을 수정한 뒤 기존 업로드 화면 2개 재검증 통과. 실패 기록은 별도로 보존 |
| `20261108T160231111177Z-d4e1d3c25a4e4d3d81fc59de77a73cf6` | Node 대기열 21개 통과. 신규 공용 텍스트 동시 저장, 관리자 비고 staging 거절 포함 |
| `20261108T160234256058Z-187539d74fad459189848d3526ae5bc7` | Django 시스템 검사·migration drift 통과 |

결과는 `.local/verification-runs/<실행ID>/`에 고유 실행 단위로 보존한다. 실제 애플리케이션 생성 XLSX를 Artifact Tool로 읽어 A1:F2의 제목/빈 행을 검사하고 A1:F3을 렌더링해 안내 잘림 없이 표시되는지 확인했다. 메모·입력 안내·텍스트 형식·추가 열 거절도 검사했다. Microsoft Excel/Numbers 앱의 실제 팝업 조작, 실제 서버 반영, 새 Docker 이미지 실행은 이번 검증 범위가 아니다. 실제 고객정보와 외부 AI 호출은 사용하지 않았고 AI 활성화 설정도 변경하지 않았다.

재현:

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label customer-metadata-backend tests.test_customer_metadata tests.test_imports tests.test_p4 tests.test_models
.venv/bin/python scripts/run_final_verification.py test --label customer-metadata-regression tests.test_p2 tests.test_p5 tests.test_p6 tests.test_p9 tests.test_dashboard_reports
.venv/bin/python scripts/run_final_verification.py test --label customer-metadata-browser tests.browser_customer_metadata tests.browser_imports tests.browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions
node --test tests/employee_queue.test.mjs
.venv/bin/python scripts/run_final_verification.py check --label customer-metadata-check
.venv/bin/python scripts/run_final_verification.py stop
```

이전 9열 양식의 당시 요구사항·28개 검사 결과는 [이전 기록 원문](history/EXCEL_TEMPLATE_GUIDANCE_20261109_NINE_COLUMNS.md)에 보존했다. 당시 결과를 현재 변경본의 통과 증거로 사용하지 않는다.
