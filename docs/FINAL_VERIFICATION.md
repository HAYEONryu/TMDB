# 최종 통합 검증과 운영 판정

검수일: **2026-11-08, Asia/Seoul**. 최신 사용자 확정 조건을 승인 기준으로 사용한다. 프로젝트·상위 디렉터리에서 적용 가능한 AGENTS.md는 발견되지 않았다. 승인 설계서 v2.0과 기존 P13의 92개 ID를 유지하되 직원 30회는 **40회**, 전체 약20명/관리자5명 미만은 **직원20명+관리자5명**, 과거 유료 AI 정책은 **Gemini Lite 무료 전용·유료 승인 $0**으로 대체한다. 과거 검수 문서를 현재 통과 근거로 사용하지 않는다.

**판정: 전체 실제 운영은 보류. 가상 자료를 쓰는 로컬 기본 고객관리 검수·시연은 조건부 가능.** 현재 AI는 비활성·무료 확인 false이며 이를 임의로 켜지 않았다. 현재 무료 티어/원격 잔여량, 공개 HTTPS, 외부 백업, 운영 서버 자원/성능·실제 23시 관찰이 미검증이다. 호스팅 구매·배포·실제 고객 업로드·외부 AI 추가 요청은 하지 않았다.

## 최종 실행 결과

최종 동일 소스의 수치와 92문항 표는 [FINAL_ACCEPTANCE.md](FINAL_ACCEPTANCE.md) 및 이 문서 하단의 실행 수치를 따른다. 개별 테스트의 실패·skip·미실행·소스 변경을 통과시키지 않는다. 원시 로그/JSON은 `.local/final-test/`에 보존하며 실제 키나 고객정보를 넣지 않는다. 이전 실험 응답은 재생성하지 않았다.

검수 환경은 Apple Silicon/macOS의 Python3.13, Django5.2, PostgreSQL17, Gunicorn2 workers×4 threads, Playwright Chromium/Firefox/WebKit이다. 일반 개발/데모와 다른 **127.0.0.1:55435·tm_final_test** 클러스터와 `test_tm_final_*`, `tm_restore_*` 폐기용 DB를 사용했다. 개발/데모 DB에 접속·migration·초기화·암호 재설정을 하지 않았다. 보호된 `.env`/`.env.ai`의 변경 여부는 비밀값을 출력하지 않고 확인한다.

## 실제 화면·업무 흐름

아래는 현재 서버 API와 Playwright 실제 로컬 브라우저를 함께 검증한 범위다. 브라우저·모의 시계 결과를 물리 기기/운영 환경 결과로 확대하지 않는다. 자세한 각 ID는 최종 92문항 표에 연결한다.

| 흐름 | 현재 검증 근거 |
|---|---|
| 관리자·직원 초기 로그인, dodream 변경 강제, 재설정 후 기존 세션 차단 | `test_auth`, `browser_flow`, `browser_p4` |
| 전역 기본 현장, 열려 있는 화면 보존·다음 화면 반영 | `test_p2`, `browser_p2`, `browser_ui` |
| 엑셀 필수값·전화번호 정규화·현장별/휴지통/파일/동시 중복·확정 재검사 | `test_imports`, `browser_imports`, `performance_imports` |
| 랜덤 분배·직원별 수량·부족 시 0건/전체 취소·중복 요청 | `test_p4`, `browser_p4`, `performance_assignments` |
| 수동 회수·재분배·이전 담당자/동일인 재배정 전 대기 저장 차단 | `test_p4`, `test_p5`, `browser_employee` |
| 오늘 및 지난 미완료 재콜, 완료 재시도·이력 | `test_p5`, `test_p6`, `browser_p6` |
| 고객명·연락처 수정 불가, 관리자만 담당자 변경, 직원의 타인 자료 거절 | `test_p2`, `test_p4`, `test_p5` |
| 첫 편집 후 100초 이내 요청 시작·무변경 요청 없음·저장 상태·실패 재시도·오프라인 복구 | `browser_employee`, `employee_queue.test.mjs` |
| 직원 복사·잘라내기·우클릭 제한, 편집/붙여넣기 가능·다운로드 경로 없음 | `test_p5`, `browser_employee` (화면 보호이며 화면 캡처/개발자 도구 유출 방지 보장은 아님) |
| 행별 삭제 요청→요청완료→전체 관리자 알림→승인→휴지통 | `test_p7`, `browser_p7`; 최신 비고 보존, 한국 승인일시와 “고객요청으로 인한 삭제” 1회 추가, 긴 비고도 보존 |
| 복구·비활성화·모든 기존 세션 차단·모든 현장/날짜 미진행 할당 회수 | `test_auth`, `test_p4`, `browser_p4`, `browser_p7` |
| 현장명 재입력·영구 삭제·파생 AI/요청/업로드 자료 정리 | `test_p7`, `test_p8`, `browser_p7`, `performance_deletions` |

## 발견한 문제와 수정

- 권한을 직원→관리자→직원으로 바꾸면 기존 할당/고객 버전이 같아 이전 AI 결과를 재조회·적용할 수 있었다. 직원 AI 결과의 조회/적용과 목록, 캐시에 요청 당시 `session_version`을 연결했다. 변경 전 결과를 숨기고 새 세션에서 새 요청을 만들 수 있게 했다. `StalePermissionResultTests`는 실제 역할 변경 후 조회403·적용 거절·상담 이력0·새 작업 분리를 확인한다.
- 활성 계정 생성·재활성화·역할 변경에서 정원을 강제하지 않았다. 같은 업무 잠금 안에서 최종 배치 상태의 직원20·관리자5를 검사한다. 마지막 자리 동시 생성은1건만 성공한다. 비활성 계정 이력은 유지하며 정원에서 제외한다. 기존 정원 초과 설치는 증가를 막되 감축/기존 계정 정리는 가능하다.
- 과거 유료 어댑터 호환 코드가 명시적 유료 설정에서 실행될 여지가 있었다. **실제 실행(`TESTING=false`)의 접수/claim/전송 시작에서 무료 Gemini3.5 Flash-Lite만 허용**한다. 과거 월 예산값이 남아 있어도 유료 사용을 승인하지 않는다. 이전 공급자/유료 프로토콜 검사는 폐기용 테스트 환경의 합성 응답으로만 유지했다.
- 공용 소진과 분당 대기를 분리해 “공용 AI 사용 한도 소진” 안내를 제공한다.
- 과거 주간 브리핑 브라우저 검사는 실행일이 평일이라고 가정해 실제 일요일에 실패했다. 테스트에서 평일 availability를 명시적으로 제공하도록 고쳤다. 서버의 일요일 접수 규칙은 별도 가상 시계 검사로 유지한다.
- 통계 브라우저 검사의 첫 막대 순서 의존을 없애고 해당 직원 이름과 값을 함께 검사한다. 최초 전체 검사에서1회 실패한 뒤 집중 재현에서는 통과한 순서 의존 항목이다. 실제 집계 정답은 서버 집계 검사와 함께 대조한다.
- 새 검수 도구의 초기 오류(서비스 반환 tuple 처리, NO_SUGGESTION의 null을 저장하던 fixture, 복원 MD5 테스트 해셔, DB 재시작의 포트 인수 누락)를 수정했다. 포트 누락으로 검수 전용 DB가5432에서 시작됐던 것은 지정 포트55435로 복귀시켰고, 검수 DB만 정리한 후 재실행했다. 앱 결함과 테스트/도구 결함을 구분하며 초기/집중 실패 로그와 후속 준비 실패의 개별 결과 JSON을 보존한다.

## 23시 회수·저장 경합과 재시작

가상 KST 시계로 당일00시부터23시 cutoff까지의 **기본 현장·현재 할당·할당 후 실제 상담 변경이 없는 항목**만 회수한다. 저장 전 원복/무변경/조회는 진행이 아니며, 실제 저장 후 원복·관리자 상담 변경은 진행이다. 기존 상담 내용이 있어도 할당 이후 실제 변경이 없으면 미진행이다. 과거 할당·다른 현장·cutoff 이후 새 할당은 보존한다. 정확히23시 할당은 기존 승인된 `<= cutoff` 기준에 포함한다.

`test_p6`, `test_p8`, `MixedRecallTests`에서 저장 선커밋/회수 선커밋, 저장·분배·회수3자 경합, 자정 후 재실행, 지연 실행·기본 현장 변경·작업 중 프로세스 종료/lease 재획득·중복 완료 방지를 검증한다. lease 시간만 가상으로 진행한 부분을 실제 대기 관찰로 기록하지 않는다. AI worker의 실제 프로세스 claim 후 종료·재시작도 `test_p9`에서 검증하고 UNKNOWN을 자동 재전송하지 않는다.

**실제 벽시계 23시 자동 실행 관찰은 미검증**이다. PC 절전/종료·시간대·NTP·scheduler 상시 실행, 다음 시작 시 catch-up을 운영 환경에서 관찰해야 한다. 대기열·할당은 DB에 보존되지만 PC가 꺼진 동안 실행되는 것은 아니다.

`verify_final_recovery.py`는 검수 전용 DB를 immediate shutdown하고 WAL 복구한 뒤 같은 앱/세션에서 저장 자료 조회를 확인한다. DB 중단 중 `/healthz`503을 확인한다. 앱 프로세스 그룹 SIGKILL 후 새 Gunicorn으로 재시작해서도 같은 세션/저장 자료를 확인한다. 실제 개발/데모 DB에는 적용하지 않는다.

## AI·무료 한도·실제 실험 원장

모델은 **`AI_PROVIDER=gemini`, `AI_MODEL=gemini-3.5-flash-lite`**, 추론low, 무료 전용이다. 공식 모델 ID와 무료 입력/출력 가격은 [모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)와 [가격표](https://ai.google.dev/gemini-api/docs/pricing)에 기재되어 있다. 공식 자료 재조회일은 **2026-11-08 KST**다. 문서 직접 열기의 markdown/redirect 오류 후 공식 도메인의 검색 색인으로 확인했으며, 인증된 AI Studio 계정의 현재 한도를 조회한 것으로 간주하지 않는다.

| 범위 | 정책·확인 수준 |
|---|---|
| 직원 개인 | 상담 정리·요약·다음 질문 합산 성공+예약≤40. 한국 날짜 접수일에 귀속. 실패는 성공 횟수로 세지 않고 예약을 반환한다. UNKNOWN은 확정 전까지 예약 유지 |
| 관리자 | 조직 주간 브리핑은 KST 일요일 접수·월요일 시작 주1회, 직원 코칭은 직원별 하루1회, 가이드는 현장별 하루1회. 관리자5명이 같은 결과를 공유하며 재조회/캐시는 새 외부 요청을 만들지 않음 |
| 프로젝트 한도 | 기록/로컬 설정은 **RPD500·RPM15·입력 TPM250,000**. 2026-11-07 23:49 KST 사용자 무료 티어 확인 기록, 11-08 00:01~00:08 KST 실제 가상자료 실험 응답 존재. 현재 무료 티어·원격 잔여량은 **미검증**이며 설정값을 최신 공식 보장값으로 표시하지 않음 |
| 예약 순서 | 공용 RPD의 전송+대기/진행 예약을 먼저 검사한 뒤 개인40회. 여러 요청/worker가 마지막 공용 자리를 초과 예약하지 않음 |
| 분당 제한 | 전송 전 RPM/입력 TPM 예약. 진행/UNKNOWN은 보수적 입력 상한을 유지, 정상 usage로 조정. 부족하면 서버 큐 대기, 일일 날짜가 지난 미전송 작업은 만료·예약 반환 |
| 시간대 | 앱 개인40회는 **KST00시**. [Google 공식 한도 설명](https://ai.google.dev/gemini-api/docs/rate-limits)에 따라 프로젝트 RPD는 **미국 태평양00시**(한국 서머타임16시/표준시17시). `America/Los_Angeles`로 DST를 계산하며 두 날짜 원장을 분리 |
| 비용/전환 | 유료 승인 **$0**. 유료 티어·타 모델/타 공급자·모의 성공으로 자동 대체하지 않는다. 무료는 계정 상태이며 API 옵션이 과금을 강제로 무료로 만들지는 않음. [공식 결제 안내](https://ai.google.dev/gemini-api/docs/billing/)의 티어 확인 필요 |

**RPD500은 직원20명×40회=800회보다 작다. 전 직원에게 하루40회를 모두 보장할 수 없다.** 관리자 요청·전송된 실패·다른 앱의 같은 프로젝트 사용량도 여유를 줄인다. 개인40회는 최대치이며 보장 배분량이 아니다. 관리자 생성/캐시 재사용과 업무 우선순위로 분배하고 필요하면 AI 없이 상담을 계속한다. 이 검수에서는 유료 전환이나 모델 변경을 해결책으로 실행하지 않는다.

이전 실험 원장 `.local/gemini-experiment/state.json`과 `final-verification.json`을 읽고 종료 상태를 보존했다. **이전7회+이번0회=누적7회**, 실제 응답의 입력5,735·출력4,248·생각0·캐시0·총9,983토큰이다. 응답7건 중 직원4·관리자3이며 첫 날짜 제안 보완용 CLEANUP 재검사1회를 포함한다. 직원의 성공 횟수와 외부 전송 횟수는 서로 다른 지표다. 이 원장은 이전10회 상한으로 종료되어 그대로 재실행해도 추가 호출을 거절한다. 이번 최대2회·전체 최대12회 허용보다 더 보수적으로 추가 호출0회를 유지했으며 원장을 초기화/범위 변경하지 않았다. 이번 모의 응답 토큰은 실제 제공자 사용량에 합산하지 않는다. 실제 청구서/과금 확인은 미검증이며 무료 사용자 확인 기록과 앱 비용0 기록을 공급자 청구 감사로 대체하지 않는다.

`test_free_ai_limits`, `test_gemini_readiness`, `test_gemini_adapter`, `test_p9`~`test_p12`, `browser_free_ai`, `browser_gemini`, `test_final_integration`은 실패/성공/진행/UNKNOWN/캐시, 공용499→500 마지막 자리 경합, RPM15→대기→재개, TPM 선예약,429,권한/담당자/삭제 후 적용 차단, 키 없음/장애 중 실제 일반 상담 저장을 검사한다. 외부 transport는 합성 응답이며 실제 한도를 소진시키지 않는다.

## 사용자 안내와 운영 대응

| 상황 | 사용자 안내·처리 | 운영 대응 |
|---|---|---|
| 공용 RPD 소진 | “공용 AI 사용 한도 소진”. 개인 잔여가 있어도 새 생성 중단, 기존 결과·일반 고객관리 계속 | availability의 `server_limit.reset_at`과 공급자 사용량 확인. 태평양 자정 이후에도429면 외부 사용·공급자 상태 확인. 키 추가/모델 변경/유료 전환 금지 |
| RPM/TPM 대기 | 대기 시각·접수/진행 상태 표시, 서버 큐 보존 | 정상 worker와 공용 쿨다운 확인. 같은 요청을 반복 생성하지 않고 task 조회. 날짜 경계 만료는 다음 날짜에 사용자가 새 요청 |
| 제공자429 | 분당이면 Retry-After/대기, 일일 quota ID면 태평양 자정까지 공용 중단 | 전송된 실패도 RPD에 남긴다. 동일 프로젝트를 쓰는 다른 앱의 사용 확인. 무제한 재시도 없음 |
| timeout/5xx/불명확 usage | 결과 확인 중 UNKNOWN·이후 실패, 자동 재전송 없음 | 기존 작업 ID·전송 시작 표식·원장 확인. UNKNOWN 최대10분 보수적 정리 후 필요 시 사용자가 새 요청. 정산 안 된 작업을 수동 성공 처리하지 않음 |
| 키 미설정/무료 미확인/유료·모델 오설정 | AI 설정 안내, 일반 고객관리 정상 | 파일0600·서버 역할·정확한 모델/무료확인/한도 확인. 재시작 전 대기 작업 검토. 로그/브라우저에 키를 넣지 않음 |
| 권한·담당자·원본 변경 | 이전 AI 결과 조회/적용 거절 또는 stale 표시, 최신 자료로 일반 편집 | 오래된 큐를 성공으로 처리하거나 새 담당자에게 묵시적으로 재결합하지 않음 |

## 시작·종료·재시작·백업·복구

전체 절차는 [OPERATIONS.md](OPERATIONS.md)와 [README.md](../README.md), 가상 데모는 `.local/demo/site.py --help`를 따른다. 아래는 **절차 안내**이며 이 검수에서 운영 DB를 시작/배포한 것은 아니다.

- 로컬 가상 시연: `.venv/bin/python .local/demo/site.py start --no-ai`, 재시작은 `restart --no-ai`, 종료는 `stop`. AI worker는 실행하지 않는다. 이 도구가 없는 새 checkout은 README의 PostgreSQL→보호된 환경→migration→collectstatic→Gunicorn→별도 `run_scheduler` 순서를 따른다.
- 일반 앱: `.venv/bin/gunicorn config.wsgi:application --config gunicorn.conf.py --worker-class gthread --threads 4`; scheduler는 별도 `.venv/bin/python manage.py run_scheduler`. `--once`로1회 점검하며 실패 날짜는 `--retry-date YYYY-MM-DD --once`로 원인 해결 후 재시도한다. 서비스 관리자/PID 소유권을 확인해 해당 프로세스만 종료한다.
- AI는 기본 비활성. 현재 무료 티어와 정확한 프로젝트/모델의 한도·잔여량을 다시 확인하고 `.env.ai`를0600으로 준비한 후에만 명시적으로 활성화한다. web/worker가 같은 DB·설정을 사용해야 한다. worker는 `.venv/bin/python manage.py run_ai_worker`,1회는 `--once`; 같은 작업 UNKNOWN을 새 호출로 재실행하지 않는다. 끌 때는 worker 종료→AI_ENABLED=false→web 재시작한다. 유료 설정은 허용하지 않는다.
- 앱/DB 재시작: 전용 백업 성공 확인→worker/scheduler/웹 중지→DB 정상 중지·시작→migration 상태 확인→웹 health/login→scheduler→필요한 경우만 AI worker 순서다. PC용 PostgreSQL 도구는 `scripts/local_db.py start|status|stop`; 해당 개발 클러스터만 조작한다. 강제 중단은 이번 폐기용 검수에만 사용했다.
- 백업: `BACKUP_DIRECTORY`, `BACKUP_RECIPIENT`, `BACKUP_DESTINATION` 등 보호된 운영 설정을 준비하고 `.venv/bin/python manage.py backup_database`. PostgreSQL17 `pg_dump`를 age로 바로 암호화하며 완료/전달/checksum·비0 종료·보관7일을 점검한다. 평문/키/DB URL을 로그에 쓰지 않는다.
- 복구: `.venv/bin/python manage.py restore_database --archive /별도/선택.dump.age --identity /별도/키.agekey --target tm_restore_review_YYYYMMDD`. **없는 새 tm_restore_* DB에만** 복원한다. 운영/현재 DB를 덮지 않는다. 세션 폐기·백업 이후 영구 삭제/권한 변경 재반영·계정/상담/할당/재콜/AI 원장·로그인 검증 후 별도 전환 판단. worker/scheduler는 격리한 상태로 유지한다.

## 재현

외부 AI를 호출하지 않는 로컬 검수이며 프로젝트 도구가 준비되어 있어야 한다. PostgreSQL 공유 메모리/로컬 소켓·브라우저 실행은 샌드박스 밖 권한이 필요할 수 있다. 자동으로 패키지를 설치하거나 외부 자원을 구매하지 않는다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label release
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/run_final_verification.py check
.venv/bin/python scripts/verify_final_recovery.py
.venv/bin/python scripts/verify_ai_boundary.py --output .local/final-test/boundary.json
.venv/bin/python scripts/audit_final_security.py
.venv/bin/python scripts/report_final_verification.py
.venv/bin/python scripts/run_final_verification.py stop
```

초기 감사용 `.local/final-test/protected-before.json`은 실제 파일 변경 여부의 내부 해시만 담는다. 새 checkout에서 이 파일이 없으면 보안 감사 전에 `.env`·`.env.ai` 파일의 SHA-256을 같은 키의 JSON으로 기록한다(내용/키를 출력하지 않음). 경계 검사는 Docker 엔진 부재로 exit1이며 해당 항목은 미검증으로 남는 것이 정상이다. 테스트/복원 DB는 각 검사 후 제거한다. 첫 전체 진단 `integration.log`는528개 중526통과/2실패였고, 소스 수정 중 실행되어 최종 근거로 사용하지 않는다. 후속 전체 진단은 브라우저 첫 준비의 네트워크 오류 뒤 Playwright 정리 누락으로79개 테스트가 오류 처리됐다(일부 teardown 중복 오류157건). `.local/final-test/diagnostic-cascade-results.json`에 개별 결과를 보존했고 그 실행의 원시 로그는 재실행 과정에서 덮어써 보존하지 못했다. 준비 단계에도 cleanup을 등록해 후속 오염을 차단했다. 집중 검사의 fixture 오류도 보존하며 최종 표는 `release-results.json`의 현재 동일 소스 실행만 사용한다.

## 로컬 PC와 외부 서버의 추가 준비

| 항목 | 로컬 PC 운영 | 외부 서버 운영 |
|---|---|---|
| 상시 실행 | 절전/종료 방지·자동 시작·전원/디스크·KST/NTP·23시 관찰·scheduler/worker 재시작 감시 | 프로세스 관리자·헬스/실패 감시·재시작 정책·서버 자원·실제25명 지속 부하/장애 시험 |
| 접속 | localhost 가상 시연 범위. 다른 직원이 접속할 LAN/HTTPS·방화벽·도메인은 미검증 | 승인된 도메인/공개CA HTTPS·Secure cookie/CSRF·프록시 밖 웹/DB 차단·방화벽. 현재 구매/배포 금지 유지 |
| 비밀/배포 | 파일0600·Git미추적·현재 키 소스/정적/로그 감사. 현재 로컬 DEBUG=false 확인·실제 운영 전용 설정은 별도 검증 | checkout 밖 전용 비밀·최소 DB 권한·키회전·컨테이너UID 권한·불변 이미지·실제 Docker context/레이어·기동 검증 |
| 백업 | 다른 장애 영역으로 암호화 보관·주기 자동 실행/실패 감지·별도 복원 훈련 | 실제 외부 저장소/계정/SSH host key·권한·용량/보관·Linux timer03시 KST/catch-up·복구 책임자와 RPO/RTO |
| AI | 무료 티어와 잔여량 재확인 전 비활성.500회로800회 보장 불가 안내 | 같은 프로젝트를 쓰는 모든 앱/인스턴스의 사용량 조정·동일 DB 공용 원장·공급자429 대응·실제 고객자료 전송/보관 정책 검토 |

최종 차단 조건은 현재 무료 티어/잔여 확인, 실제 운영 비밀·DEBUG=false/자격증명 준비, Docker 실제 경계·기동, 외부 접속/공개 HTTPS/DB 격리, 외부 백업 자동화·복원 훈련, 실제 서버25명 부하/감시, 실제23시 관찰이다. 가짜 자료 로컬 검수의 통과와 실제 고객을 받는 운영 허용은 구분한다.

## 최종 확정 수치와 근거

- 최종 완료: **2026-11-08 00:58 KST**. Django **534/534통과**, 실패0·오류0·skip0, **262.912초**. JavaScript **19/19통과**, 총 **553개**. 실행 전후 소스 SHA 동일: `41edabbb244bc09da073f368e9eef456d9c8ba21bb3101535d31da54be10434d`.
- P13 기본 **69/69**, AI **22/23**, 합계 **91통과·0실패·1미검증**. 미검증 ID는 `18.8-22`의 실제 Docker context/이미지 레이어 검사다. 정적 Git/ignore/Compose 경계 검사는 통과했다.
- 직원20+관리자5·1만 고객·독립 세션25개·조회125+저장125=250 HTTP 요청에서 실패0. 로그인 포함4.497초. 조회 p95 **0.242초**/최대0.260초, 저장 p95 **0.282초**/최대0.311초. DB 연결 peak **10개**(관찰용 연결 포함), Gunicorn master+worker 합산 sampled RSS peak **158.81MiB**,63개 표본/목표50ms 간격이다. RSS 공유 페이지가 중복될 수 있고 표본 사이 peak는 놓칠 수 있다. 짧은 로컬 측정으로 운영 서버의 성능·동시 AI 생성 지연·장기 메모리 안정성을 보장하지 않는다.
- 현재43개 테이블을 age 암호화 백업→없는 별도 DB로 복원→전체 값/관계 대조, 관리자·직원 실제 Django 로그인/역할 API 확인. 암호문189,437바이트, 채워진 AI12테이블, 복원/대조/로그인3.460초. 다른 DB 쓰기가 원본에 영향을 주지 않았다. 복원 DB/평문 임시 파일은 제거했다. 실제 외부 저장소 복원은 미검증이다.
- 검수 DB WAL 복구+health/기존 세션 자료 재확인 **0.434초**, 앱 그룹 강제 종료 후 기동+확인 **0.289초**. 중단 중health503 확인. scheduler와 AI worker의 claim 후 실제 프로세스 종료/재시작은 최종 `test_p6`/`test_p9`에서 통과했다. 이는 단일 로컬 검수 자원의 측정이며 운영 RTO가 아니다.
- 보호 파일 불변, 현재 키의 소스/정적/로그/문서·Git 인덱스/조회 가능한 Git 객체 일치0건. 키파일0600·Git미추적, 현재 로컬 DEBUG=false, AI_ENABLED=false·무료확인false. 테스트는 서버의 권한 검사와 합성 키의 브라우저 DOM/요청응답/저장소/콘솔/로그 비노출도 확인했다. Docker 이미지와 실제 운영 배포 설정의 비밀 경계는 미검증이다.
- 외부 AI는 **이번0·누적7회**, 실제 누적9,983토큰. 유료 사용/구매/배포/실제 고객 업로드0. 기존 개발/데모 DB와 종료된 실험 원장은 보존한다.

재현 근거는 `.local/final-test/release.log`, `release-results.json`, `queue.log`, `acceptance.json`, `boundary.json`, `security.json`, `recovery.json`, `metrics/`다. `evidence-index.json`은 이 파일들의 SHA-256을 보존한다. 초기/집중 실패는 `integration.log`, `regressions-before.log`, `regressions-after.log`, `focused-fixes.log`, `new-coverage.log`, `extra-final.log`, `diagnostic-cascade-results.json`에서 구분한다. 최종 통과 이후 앱/테스트 코드는 변경하지 않았다.
