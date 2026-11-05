# P9 AI 공통 기반 검증

2026-11-05, Asia/Seoul. 설계서 v2.0·개발 계획의 P9까지 구현·실행·검증했다. 기존 업무 규칙·설계서 원문·sources·사용자 변경·개발 데이터/비밀번호를 보존했다. 실제 개인정보·유료 API/자원·운영 배포는 없다. 직원 생성/추천 적용 UI(P10)와 보고서 의미 분석/게시 UI(P11)는 이번에 시작하지 않았다.

## 1. 구현 결과

| 범위 | 실제 구현 |
|---|---|
| 모델/제약 | AIRequest·Result·QuotaBucket·UsageAttempt·ReportSlot·SiteKnowledge·ResultSource·월 비용 원장·원문 없는 요청 key 별칭. quota 합계≤30·계정 active1개·slot/key unique·source 정확히1개·금액 비음수 |
| migration | ai_assistant0001/0002·consultations0002(source_ai_result FK). 기존 migration은 재작성하지 않음 |
| 내부 접수 | 서버 권한/역할/현재 할당/버전·KST 기간/일요일·key/body·slot/cache·횟수/비용 원자적 예약. 생성 POST는 아직 비공개 |
| 비용 | 접수 KST 월·Decimal 단가 snapshot/버전·입출력/추론 예약·실패 비용/성공 사용자 횟수 분리 |
| worker | DB claim/token·트랜잭션 밖 adapter·계정1/전역2·안전한 미실행 재시도1회·UNKNOWN10분·중단 복구·queued15분 만료 |
| 조회/안내자료 | 상태/결과 GET·현재 권한·원문 없는 작업 상태·관리자 비용 집계·현장 자료100행/버전/검토 API |
| 삭제 | queued 입력·결과 본문/캐시·이전 결과/AI_APPLIED 근거 전이 그래프의 재귀 무효화·순환 보호·게시 해제·quota/비용 메타데이터 보존 |
| 테스트 표시 | TESTING·명시 TEST_MODE·test_tm_ DB 세 조건, is_test/안내문. 일반/운영에서 fake 및 실제 전송 모두 차단 |

기능별 상세 schema·프롬프트/상대 날짜 해석·직원 선택 적용은 P10, 전체 SQL 집계/30일·이전 코칭/분산 표본·가이드 게시 흐름은 P11에서 확장한다. P9 foundation-v1은 공통 기능 코드·bounded text·근거 ID whitelist·테스트 marker의 envelope 검증이다. 이를 실제 상담 품질/보고서 완료로 표시하지 않는다.

## 2. 실행한 검증

```sh
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions --testrunner=config.acceptance_runner.AcceptanceRunner --evidence-label=p9 --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_acceptance.py --results .local/p9-test-results.json --output .local/p9-acceptance.json --markdown docs/P9_BASIC_ACCEPTANCE.md --stage P9
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py check
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py run_ai_worker --once
.venv/bin/python manage.py run_scheduler --once
.local/bin/docker-compose --profile ai --profile proxy config --quiet
```

**총314개 테스트 통과 = Django299개 + Node15개.** Django는 서버/근거/복원261개·실제 Chromium34흐름·실제 PG1만 건 성능4개다. 기존 P8의282개에 P9 추가32개를 더했다. 최종 Django116.449초(`.local/p9-tests.log`), Node0.136초(`.local/p9-queue.log`). 개별299개 모두 passed·skip0·실행 전후 소스 해시 일치다. 이후 앱 코드는 변경하지 않고 문서/로컬 검증 기록만 추가했다.

기존 **기본 업무69/69항목 재통과**를 같은 결과/소스 해시로 대조했다([결과표](P9_BASIC_ACCEPTANCE.md)). `.local/p9-test-results.json`, `p9-acceptance.json`을 별도 보관하여 P8의 개별 결과/검수 문서를 덮어쓰지 않았다. AI23문항 전체나 총92문항 완료를 뜻하지 않는다.

### P9의 실제32개 검사

| 검증 | 근거/결과 |
|---|---|
| quota/원자성 | 세 직원 기능 같은 bucket·성공29+예약1 DB제약·다른 key 동시 요청1개만 예약·실패 예약 반환·원자적 접수 실패 전체 rollback |
| idempotency/cache | 같은 key1작업·다른 body 충돌·완료 캐시0추가 시도/차감·캐시/공유 반환의 새 key도 본문 고정 |
| 동시 slot/예산 | 두 관리자의 같은 slot1작업·실패 slot 반환·두 직원의 남은 월 예산 동시 예약1개만 성공 |
| claim/I/O | 독립 PG 연결 동시 claim3개 중2개·서로 다른 작업·UNKNOWN도 전역 한도 포함·외부 I/O 중 다른 연결이 공통 lock 획득·in_atomic_block=false |
| 접수 날짜/월 |12월31일23:59 KST 접수→1월1일 완료에도 원래 일 quota·12월 원장 정산 |
| 미수행 재시도 | 확실한 NotPerformed만 같은 작업 최대2시도·추가 quota 없음·두 실패 후0원 종료·일반 예외는 UNKNOWN/무재호출 |
| UNKNOWN/lease |120초 lease 만료→UNKNOWN·10분 전 예약 유지·10분 후1회 해제/보수 비용·늦은 응답 성공 차단·중복 정산 없음 |
| 실제 중단/재시작 | 실제 child process가 claim 커밋 후 os._exit(23). 테스트에서 lease/확인 상한을 과거로 당긴 뒤 새 worker process 실행→FAILED·attempt1·예약 반환·보수 비용, 재전송 없음 |
| 실패/회수 | schema/enum/외부 source/너무 긴 응답/테스트 marker 오류는 사용자 성공 차감0·과금 시도 보존. 회수/권한 상실은 결과 취소·비용 유지 |
| 오래된 버전 | 작업 중 실제 상담 저장→AI 결과 stale·일반 상담 값/진행 이력 자동 변경 없음 |
| 삭제 그래프 | 고객/revision/knowledge/이전 결과·순환 연결·다른 현장 같은 번호 보존·게시 해제·입력/본문 제거·성공 quota/비용 유지 |
| 삭제 중/실패 | RESERVED 삭제는 예약 반환/비용0, RUNNING 삭제는 보수 비용/취소. privacy 처리 뒤 erase_receipts 오류 주입 시 AI 상태/원장과 도메인 삭제 모두 rollback |
| 권한/CSRF/조회 | 최초 변경·직원/관리자/다른 직원·현재 할당·actor header·CSRF. 관리자도 직원 개인 결과 우회 불가. GET 반복 시도/차감0 |
| 입력/키 보호 | 서버 DB 구성·알려진 이름/전화/이메일/키 제거·근거 부족 빈 기록 유지·입력 cap 실패 예약0·정적/JSON/로그에 테스트 키 노출 없음 |

최초 개별22개3.451초·관련 회귀84개9.708초·최종 개별32개5.339초를 통과했고, 원자성 오류 주입을 실제 삭제 연동 뒤로 강화한 다음 전체299개에서도 재통과했다. 중간 코드 검토에서 캐시/공유 결과에 사용된 새 key의 별칭 고정 필요를 확인해 AIRequestKey를 추가했다. 합격 기준이나 업무 규칙을 낮추지 않았다. `.local/p9-focused.log`, `p9-regressions.log`, `p9-final-focused.log`를 보존했다.

### 기존 성능/복원 회귀

| 가짜1만 건 작업 | 최종 시간 | 최대 업무 잠금 |
|---|---|---|
| 업로드 검증/확정 |2.271/2.386·합계4.657초 |2.371초 |
| 분배/수동 회수 |3.447/0.754·합계4.202초 |3.446초 |
| 자동 회수 |0.676초 |0.663초 |
| 현장 영구 삭제 |4.651초 |4.130초 |

프로세스 peak RSS155.69MiB. 각 총30초/업무 잠금10초/RSS512MiB 기준을 통과했다.20명 동시 운영 SLA 검증은 아니다. 기본 가짜 데이터의 실제 dump/별도 DB 복원도 재실행해 현재36개 public 테이블을 대조했다(`.local/p9-restore.json`,0.652초). 이 복원 fixture의 AI 테이블은 비어 있으며 populated quota/비용/무효화 상태까지 포함한 최종 운영 복원은 P13에 남는다.

## 3. 실제 로컬 실행/보존

개발 PostgreSQL에 migration3개를 적용하고 모델 차이0·check 이상0·미적용 migration0·정적26파일 유지·Compose config 구문 통과를 확인했다. 의존성/실제 키 파일을 변경하지 않았다. migration 전후 User/Customer 전체 값의 digest를 대조해 사용자3명·고객65건·현재 할당0·비밀번호/세션/상담이 그대로임을 확인했다. 개발 DB AIRequest/Attempt/QuotaBucket0·임시 test/restore DB 잔존0이다(`.local/p9-before.json`, `p9-development-data.json`). 가짜 AI 데이터는 테스트 DB에서만 생성했다.

실제 `run_ai_worker --once`는 처리0/성공0, scheduler --once는 회수0/실패0이다. 실제 worker daemon도 기동해 첫 DB 점검 응답을 확인한 뒤 SIGTERM 종료0/0.076초를 확인했다(`.local/p9-worker-runtime.json`). 장시간2초 반복 운영을 검증한 것은 아니다. worker는 새 작업을 만들지 않았고 실제 외부 공급자 전송은 없다.

키 파일 누락/잘못된 가격 설정 각각으로 독립 WSGI/Gunicorn2 workers를 기동해 AI_NOT_CONFIGURED·health200·로그인200·익명 업무401·정적6파일 HTTP 내용/길이/원본 SHA 일치를 확인했다. 각각 정상 종료했다(`.local/p9-runtime.json`). 이 독립 서버 점검에서는 기존 비밀번호를 바꾸지 않고 기동/읽기 응답만 확인했다. 권한 있는 공통 AI API·안내자료 변경은 별도 PG 통합 테스트에서 검증했다. Docker 엔진이 없어 이미지 build/up/레이어는 미실행이다.

## 4. 기본값과 미완료

| 구분 | 적용 |
|---|---|
| 확정 업무 규칙 | 직원 합산30·일요일 신규 브리핑·명시적 접수만 작업 생성·현재 담당 재검사·실패/회수 예약 반환·비용 보존·원문 재귀 삭제 |
| 설계 기본값 | 계정1개/전역2개·UNKNOWN확인10분·직원800/보고서2000 출력·월 USD5·미수행 재시도1회 |
| P9 구현 기본값 | 접수 KST월 귀속·Decimal12자리 비용·추론 cap을 출력 cap과 동일하게 예약·120초 lease·15분 queued만료·2초 worker loop·공통 envelope-v1·4000/12000 UTF-8bytes 입력 cap·100근거 상한 |
| 후속 기능 | 상세 의미 schema·추천 필드/상대 날짜·선택 적용/AI_APPLIED 저장(P10), 실제 SQL 집계·30일/이전 코칭·분산 표본·검토/게시 UI(P11) |

현재 실제 모델/공급자 SDK는 연결하지 않았다. 테스트 단가/UTF-8 크기 경계/추론 예약 정책은 운영 tokenizer나 실제 청구 검증이 아니다. 입력의 알려진 식별값 제거가 완전한 익명화를 보장하지 않는다. 향후 공급자 선택 시 공식 단가·출력/추론 청구 단위·timeout 확인 기능·모델 지원을 확인하고 같은 비용 경계에 연결해야 한다. 현재 adapter는 bounded 단일 테스트 응답이며 내부 다중 유료 분할 호출은 실행하지 않는다. 확실한 미수행 재시도 외의 자동 유료 재호출은 없다.

P9 필수 범위에 남은 차단 문제는 없다. 실제 유료 품질/과금·Docker 레이어·전체 AI23문항·운영 백업/암호화/외부 보관/AI 포함 복원·HTTPS·실제 모바일/다중 브라우저·20명 SLA는 미검증이다. 직접 확인/전용 검사 재현은 [README17절](../README.md#17-p9-ai-공통-기반-확인)을 따른다. 다음은 **P10 직원 AI3종**이며 이번에는 진행하지 않는다.

최종 정리: 원문 SHA-256 불변·AI 파일0600/비추적/제외·빈 예시 허용, 문서 링크52개/코드블록/충돌·Python compileall·JS20파일 구문·Git diff를 확인했다(`.local/p9-audit.json`). 마지막 소스에서도299개 결과/69문항을 재대조했고 대표 직원 모바일 화면을 검토했다. Gunicorn 두 시나리오·worker daemon·전용 PostgreSQL은 정상 종료했으며 pidfile 제거·8000/55432 리스너 없음·DB 중지를 확인했다(`.local/p9-shutdown.json`). 개발 데이터는 보존했고 README1절로 다시 실행할 수 있다.
