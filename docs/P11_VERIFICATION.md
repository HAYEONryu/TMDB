# P11 관리자 AI 3종 검증

2026-11-05, Asia/Seoul. 설계서 v2.0·개발 계획의 P11을 구현했다. 설계서/sources·사용자 변경·기존 계정/비밀번호·개발 고객 자료를 보존했다. 업무 규칙 변경·실제 개인정보·유료 API/자원·운영 배포는 없다. 실제 공급자 전송은 계속 비활성이며 fake는 명시적 테스트 설정과 별도 테스트 DB에서만 작동한다. P12는 진행하지 않는다.

## 구현

| 범위 | 결과 |
|---|---|
| 관리자 화면 | `/app/admin/ai`, 주간/직원/현장 대상 선택, 생성 이력·결과·실제 작성자·한국 시각·근거 고객 기록 링크 |
| 주간 브리핑 | KST 일요일 접수, 월요일00:00~일요일 접수 시각 고정, 연말 월요일 날짜 키, 조직 주1회 공유 slot. 평일은 새 생성 거부·기존 결과 조회 허용 |
| 전체 집계 | 실제 ConsultationRevision.actor·Assignment.employee·Callback 작성/완료자·OperationEvent 처리자/시각으로 서버 SQL 집계. 비활성·관리자로 변경된 실제 작업자 포함. 저장 횟수를 통화 횟수로 표시하지 않음 |
| 고객 반응 | 고객/실제 작성자/KST 날짜별 최신 수동·AI 적용 비고를 선택. 현장/작성자/날짜 층화 표본·모델/분류 버전 캐시. 근거 인용 검증 후 PRICE/LOCATION/TIMING/COMPARISON/OTHER/UNSPECIFIED별 중복 제거 고객 수를 서버 계산. 라벨 간 중복·입력/캐시/미분석/미분류 범위 표시 |
| 기록 확인 | 표본 범위의 재연락 표현/재콜 누락·방문 취소/남은 일정·방문예약/일정 누락을 확인 보조로 표시. 고객 값·재콜·방문 일정을 자동 생성하거나 필수 검증으로 바꾸지 않음 |
| 직원 코칭 | 전 현장 최근30×24시간의 실제 업무, 최근 유효 코칭 최대3건·그 이전 구조화 실행 항목/미확인 과제 입력. 전후 관찰 기간·고객 수, 부족하면 판단 불가. 관리자만 조회하며 직원 전송 없음 |
| 팀 가이드 | 현장 최근30일 반응과 검토·유효 안내자료로 초안 생성. 고객 식별 내용 없는 일반 질문/응대 문구·검토 자료의 원문 사실 인용을 분리. 자료 부족 시 현장 담당자 확인 필요 |
| 검토·게시 | 초안 편집→현재 버전 검토→명시적 게시. 버전 충돌·동일 key 재시도·검토 버전 DB 제약. 새 초안/수정 중에는 별도 게시 스냅샷 유지. 편집/검토/게시/조회는 AI 호출·quota 차감 없음 |
| 직원 화면 | `/app/guides`에서 현장별 게시 본문만 읽기. 초안/상세 고객/코칭/내부 근거는 제공하지 않으며 테스트 결과는 운영 안내와 구분 |
| 원문 삭제 | 모든 전체 집계 고객·선택 원문·안내자료·이전 코칭을 source graph에 연결. 영구 삭제/자료 수정 시 혼합 보고서·파생 코칭·초안 본문·서버 스냅샷을 비우고 게시본 제거. 분류 캐시는 revision 삭제와 CASCADE. 성공 slot·비용·사용 횟수는 환불하지 않음 |
| 동작 경계 | GET/화면 진입은 생성0. 결과 open+visible에서만3초 폴링, 숨김/닫힘/완료 시 중단. 접수 응답 유실은 동일 key로 명시적 확인. 원문/초안은 sessionStorage에 저장하지 않음 |

## 구현 기본값과 한계

사용자 확정 업무 규칙은 그대로다. 아래는 구현 기본값이며 운영 품질 보증이 아니다.

- `admin-v1`은 서버 집계와 모델 서술을 분리한다. 숫자 업무 집계는 AI 응답에서 받지 않는다. 자유 서술의 숫자·성격/말투/순위 추정·외부 URL/HTML·보호값을 보수적으로 거부하고, 모델 근거는 실제 전달한 원문 ID/인용으로 검사한다. 모든 자연어 사실성·익명화·인과 표현을 완벽하게 판별하지는 않는다.
- 관리자 입력은 UTF-8 12,000바이트, 출력은8,000바이트 이하로 제한한다. 실제 공급자 tokenizer가 아닌 테스트 단계의 보수적 상한이다. 전체 SQL 수치·source 연결은 입력 cap 밖의 `AIReportSnapshot`에 저장한다.
- 최신 비고96개 후보를 층화 순환으로 선택하고 byte cap까지 줄인다. 기존 분류가 있으면 재사용하며 분석 고객·분류/미분류 메모 묶음을 따로 표시한다. 모든 비고를 AI로 분석한 것으로 표시하지 않는다. 전체 집계는 표본으로 추정하지 않는다.
- 코칭의 최근3건·그 이전 최대20건의 구조화 항목을 bounded 입력으로 제공한다. 오래된 항목은 건당 최대3개, 최근 본문은 최대5개 영역/실행 항목을 전달하고 byte cap에 따라 줄이며 포함 수·생략 여부를 표시한다. 전후 각각 하루 이상·변경 고객 근거가 모두 있을 때만 관찰 가능으로 표시한다. 인과효과나 순위를 주장하지 않는다.
- 유효 안내자료 최대100개를 후보로 사용하고 입력 cap에 따라 포함 수를 줄인다. 상품 사실은 제공한 검토 자료의 원문 인용만 허용한다. 가이드 일반 문장은 고객 식별/상품 사실을 섞지 않는 제한된 질문·응대 문구에서 선택한다. 관리자는 개인정보/근거 검사를 통과한 초안을 직접 편집할 수 있다. 실제 모델의 자유로운 한국어 문장 품질은 미검증이다.
- 초과 재콜은 예약 작성자, 완료 재콜은 실제 완료자 기준이며 현재 담당자에게 과거 실적을 넘기지 않는다. 전역 OperationEvent에는 현장 차원이 없으므로 현장 가이드에 전역 운영 실적을 귀속하지 않는다. 운영 시각 목록은200개 표시 상한이고 합계는 전체 범위다.
- 검토된 자료 변경은 이를 사용한 기존 게시본도 무효화한다. 단순 초안 수정은 기존 게시본을 유지한다. 원본 무효화 후 동일 성공 slot의 자동 재생성은 없다.

## 재현

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test tests.test_p11 tests.browser_p11 tests.performance_reports --noinput -v 2
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.browser_p10 tests.browser_p11 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions tests.performance_reports --testrunner=config.acceptance_runner.AcceptanceRunner --evidence-label=p11 --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_acceptance.py --results .local/p11-test-results.json --output .local/p11-acceptance.json --markdown docs/P11_BASIC_ACCEPTANCE.md --stage P11
```

**총401개 통과 = Django383개 + Node18개.** Django는 서버/권한/집계/복원322개·실제 Chromium56흐름·PG1만 건 성능5개다. 기존356개에 P11서버35·브라우저9·성능1개를 추가했다. 최종 Django170.086초, Node0.147초. 개별383개 모두 passed·skip0·실행 전후 소스 해시 동일이며 이후 앱 소스를 변경하지 않았다. [기본69/69항목](P11_BASIC_ACCEPTANCE.md)도 동일 소스로 재대조했다.

최종 실제 PG 성능: 업로드5.066초·분배/회수5.394초·자동 회수0.762초·현장 영구 삭제5.005초·보고서 집계/근거 저장1.849초. 보고서1만 건은 입력11,704바이트/표본35묶음/전체수치10,000고객이며 표본으로 전체를 추정하지 않았다. 보고서 잠금1.733초·peak RSS294.36MiB로30초/10초/512MiB 테스트 기준을 통과했다. 이 수치는 단일 로컬 가짜 데이터 측정이며 운영20명 SLA가 아니다.

기본 자료 별도 DB 복원은39개 테이블·163,777바이트0600 dump·0.650초로 일치했다. 임시 DB/dump를 제거했다. AI 관련 테이블은 빈 fixture이므로 **채워진 AI 보고서/게시본 복원 검수는 P13에 남는다.**

실제 개발 PG check 이상0·모델/migration 차이0·미적용0, 정적29파일·Compose config 구문 통과. 키 파일 없음/잘못된 설정 각각 독립 Gunicorn2 workers health/로그인200·익명401·정적11개 내용/길이/SHA 일치·정상 종료를 확인했다. worker --once 처리0/성공0·scheduler --once 완료0/실패0이다. 사용자3명·고객65건·현재 할당0·AI 요청/시도/quota0과 기존 전체 User/Customer digest(비밀번호 포함)가 P10 기록과 일치한다. 테스트/복원 DB 잔존0이다.

중간 실패·수정 기록은 `.local/p11-foundation-tests.log`, `p11-report-tests.log`, `p11-browser-tests.log`, `p11-focused-*.log`, `p11-preflight-*.log`에 보존했다. 최종 근거는 `.local/p11-tests.log`, `p11-queue.log`, `p11-test-results.json`, `p11-acceptance.json`, `p11-performance.json`, `p11-runtime.json`, `p11-restore.json`, `p11-development-data.json`이다. PC·390px 이미지를 직접 확인했다.

## 직접 확인

README1절로 DB/Gunicorn을 시작하고 기존 가짜 관리자 계정으로 로그인한 뒤 **AI 보고서**를 연다. 일반 개발 실행은 키/실제 공급자 어댑터가 없어 새 생성 비활성이며, 기본 고객관리와 기존 결과 조회는 정상이다. 생성→검토→게시 전체 흐름은 위 테스트가 별도 가짜 DB와 실제 Chromium으로 실행한다. 테스트 모드를 개발/운영 DB에 켜거나 실제 키로 fake를 활성화하는 경로는 없다.

가이드 생성→초안 문구 확인→검토 체크→**초안 저장·검토 반영**→**검토본 게시** 순서다. 직원은 **팀 상담 가이드**에서 게시본만 본다. 초안을 다시 바꿔도 재게시 전에는 이전 게시본이 유지된다. 안내자료를 바꾸면 기존 근거 결과·게시본이 무효화되므로 다시 검토해야 한다. 주간 새 생성은 일요일만, 코칭/현장 가이드는 대상별 하루1회 성공 slot을 공유한다.

검사 이미지는 `.local/qa/p11-guide-desktop.png`, `p11-coaching-mobile.png`, `p11-published-mobile.png`다. 가짜 결과 표시는 항상 유지한다.

## 미완료·다음

P12 전체 AI23항목·secret sentinel/클라이언트/로그/Docker 이미지 경계 종합 검수, P13 운영 백업·암호화·외부 보관·AI 자료를 채운 별도 복원·HTTPS·실제 다중 브라우저/모바일·20명 SLA가 남았다. Docker 엔진 부재로 build/up/레이어 검사는 미실행이다. 실제 공급자·공식 단가/tokenizer·한국어 분석 품질·유료 과금/호출·운영 배포도 미실행이다. 이번 요청은 P11까지만 수행한다.

최종 파일 검사: 원문 SHA 불변·AI 파일0600/비추적/제외·빈 예시 허용, 문서 링크78개·코드블록/충돌·Python compileall·JS24파일 구문·Git diff·동일 소스383개 결과/기본69항목을 확인했다(`.local/p11-audit.json`). 검증 소유 Gunicorn/단발 worker/PostgreSQL을 종료했고 PID 파일 없음·8000/55432 리스너 없음·DB 중지를 확인했다(`.local/p11-shutdown.json`). 일반 실행을 다시 확인하려면 README1·19절로 시작한다.
