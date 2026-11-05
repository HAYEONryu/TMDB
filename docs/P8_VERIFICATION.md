# P8 기본 업무 통합 검증

2026-11-05, Asia/Seoul. v2.0·개발 계획의 P8까지 구현·실행·검증했다. 기존 P1~P7 코드를 통합 검수하고 재현 가능한 근거 수집 도구를 추가했다. 업무 규칙·설계서 원문·sources·사용자 변경·개발 계정/고객을 보존했다. P9은 시작하지 않았다. 실제 개인정보·유료 API/자원·운영 배포는 없다.

## 1. 이번 구현

| 파일/범위 | 결과 |
|---|---|
| tests/test_p8.py | 네 AI 설정 실패별 전체 업무 연동·삭제 현장의 옛 요청 거부·seed 보존·실제 저장 원복/관리자 수정과 자동 회수 연동7개 |
| tests/test_backup.py | 가짜 PostgreSQL 테스트 DB의 실제 dump·별도 빈 DB 복원·모든 테이블 대조·쓰기 격리1개 |
| tests/acceptance_basic.json | 설계서18.1~18.7의69개 원문·안정된 문항 ID·실제 테스트 ID 매핑 |
| config/acceptance_runner.py | 선택 실행 runner, Django 개별 성공/실패/오류/skip·실행 중 소스 해시 기록, 원문/traceback 복제 없음 |
| scripts/verify_acceptance.py | 원문 문구/순서69개·누락/미실행·소스 변경 대조, JSON/Markdown 결과 생성·실패 시 비정상 종료 |
| tests/test_acceptance.py | 누락/skip/실패를 통과로 표시하지 않음·낡은 소스 거부·subtest 실패 보존3개 |
| 문서 | README16절 실행법·P8_ACCEPTANCE69항목 결과·계획/기반 구조/진행 갱신 |

기존 업무 API·모델·마이그레이션·의존성을 바꿀 필요는 없었다. 승인된 로그인·분배·회수·저장·삭제 규칙을 유지했다. 테스트 보고서의 동일 소스 검증·별도 복원 DB 이름·원문 없는 결과 파일은 검증 도구의 구현 선택이며 업무 규칙 변경이 아니다.

## 2. 실제 실행 결과

```sh
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions --testrunner=config.acceptance_runner.AcceptanceRunner --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_acceptance.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.local/bin/docker-compose --profile ai --profile proxy config --quiet
```

**총282개 테스트 통과 = Django267개 + Node15개.** Django는 서버/검증 도구/복원229개·Chromium34흐름·PG1만 건 성능4개다. 기존 P7의271개 전체를 다시 실행하고 P8의11개를 추가했다. 최종 Django267개126.345초(`.local/p8-tests.log`), Node15개0.128초(`.local/p8-queue.log`)다. 실패/skip 없이 개별267개 결과가 기록됐고 실행 전후 소스가 같았다. 마지막 코드 변경 뒤 전체를 실행했으며 이후에는 문서만 갱신했다.

**기본69/69항목 통과.** [항목별 결과표](P8_ACCEPTANCE.md)는 실제 실행 시각·원문·완전한 테스트 ID를 담는다. `.local/p8-test-results.json`과 `.local/p8-acceptance.json`이 원시 근거다. 문항과 테스트 수는 다르며 AI23항목을 포함한 전체92항목 완료를 뜻하지 않는다. 원문 체크박스는 수정하지 않았다.

| 통합 상황 | 실제 확인 |
|---|---|
| AI 키 파일 없음 | 설정 비활성·기본 고객관리 전체 흐름 성공 |
| 비정상 단가 | NaN/음수 가격으로 AI 미설정, 업무 전체 흐름 성공 |
| 파일 권한 오류 | 별도 임시0644 파일을 AI_CONFIG_PERMISSIONS로 비활성화, 업무 전체 흐름 성공 |
| fake 공급자 | 일반 web 로더에서 AI_TEST_PROVIDER_FORBIDDEN, 업무 전체 흐름 성공 |
| 각 설정의 업무 범위 | 엑셀 검증/확정→분배→직원 오늘 목록→상담/재콜 저장→재콜 완료→삭제 요청/승인→옛 저장 거부→미할당 복구→영구 삭제/replay→비활성 세션 차단 |
| 외부 전송 차단 | socket connect와 fake adapter 실행을 금지한 채 네 업무 흐름 검증. 실제 유료 공급자 호출 없음 |
| 현장 영구 삭제 뒤 | 옛 현장 조회409/SITE_DELETED·queue-check SITE_DELETED·미전송 저장 실패·옛 업로드 확정409, 새 고객 생성 없음 |
| seed 재실행 | 상담 값·고객 버전·현재 할당·삭제 요청·바뀐 비밀번호 해시·기본 현장·revision/현장 수 유지, 명시 flag 없으면 두 명령 거부 |
| 진행/회수 | 직원 저장 후 원래 값으로 다시 저장·관리자의 주택상황 저장은 통화결과가 비어도23시 회수 대상에서 제외, 무변경/조회는 미진행으로 회수 |

실제 Chromium에서는 기존 로그인/최초 변경·현장/필터·엑셀·분배/회수·자동 저장100초·오프라인/브라우저 재시작·계정 격리·복사 제한/붙여넣기·재콜·삭제 요청/승인·영구 삭제와 PC/390px을 재검증했다. 대표 `.local/qa/p5-employee-mobile.png`, `p7-notifications-mobile.png`를 직접 검토했다. 모바일 그리드/알림은 표 내부에서 가로 스크롤한다. 가짜 시계로100초·23시·60초 폴링을 검증했으며 실제 운영의 하루 대기 검사는 아니다.

### 실제 별도 DB 복원

`BasicBackupRestoreTests`는 TESTING=true·test_ DB만 허용한다. 실제 PostgreSQL17 `pg_dump --format=custom --no-owner --no-acl`과 `pg_restore --exit-on-error`를 사용해 **같은 로컬 클러스터의 별도 빈 데이터베이스**에 복원했다. DB 이름은 테스트가 새로 만든 `test_tm_p8_restore_...` 하나만 사용하고 종료 시 제거한다. 다른 호스트나 다른 PostgreSQL 인스턴스로 복원한 검사는 아니다.

- 사용자·세션·현장·할당·상담 revision·미완료/완료 재콜·PENDING/APPROVED 삭제 요청·요청 결과를 포함한27개 public 테이블의 모든 행을 정렬한 JSON SHA와 행수로 대조해 일치했다.
- 실제 PBKDF2 비밀번호 검증, 역할/활성/변경필수 값, 고객→현재 할당 관계를 확인했다.
- 복원 DB의 가짜 상담만 바꾼 뒤 원본27개 테이블이 그대로임을 대조했다.
- 최종 실행 dump108,542바이트·파일0600·생성/복원/대조0.727초다. 임시 dump와 디렉터리·복원 DB를 제거했다.
- `.local/p8-restore.json`에는 원문/비밀번호/덤프 대신 검증 결과·테이블별 건수/해시만 남겼다.

이는 기본 업무 복원 검수다. 운영 백업 자동화·암호화·외부 보관·7일 보존·장애복구 절차와 향후 AI quota/비용/무효화 데이터 복원은 P13에 남는다.

### 실제 PG 1만 건 성능 회귀

| 작업 | 최종 결과 | 최대 업무 잠금 |
|---|---|---|
| 엑셀 검증/확정 | 2.414/2.403·합계4.817초 | 2.389초 |
| 랜덤 분배/수동 회수 | 4.209/5.478·합계9.687초 | 5.471초 |
| 자동 회수 | 5.105초 | 5.084초 |
| 현장 영구 삭제 | 4.420초 | 4.027초 |

프로세스 peak RSS143.89MiB, 기준은 각 총30초·업무 잠금10초·RSS512MiB다. 네 작업 모두 통과했고 합격선을 바꾸지 않았다. 원시 수치는 `.local/p8-tests.log`, `.local/p3-performance.json`, `p4-performance.json`, `p6-performance.json`, `p7-performance.json`에 있다. 각 가짜1만 건 단일 작업의 계측이며20명 동시 운영 SLA 검증은 아니다.

## 3. 실제 실행 환경·실패 이력

Python3.13.18·Django5.2.18·PG17.11·Node22.23.3·설치된 Playwright Chromium을 재사용했다. 새 패키지 설치나 의존성 변경은 없다. 실제 개발 DB check 이상0·모델 차이0·미적용 migration0·collectstatic26파일 유지, Compose config 구문 검사를 통과했다. Docker 엔진은 없어 build/up·이미지 레이어 검사는 미실행이다.

독립 WSGI/Gunicorn2 workers를 **임시 AI 파일 누락**과 **빈 키/잘못된 가격 설정**으로 각각 시작했다. 두 경우 모두 AI_NOT_CONFIGURED·DB health200·로그인200·익명 업무401이며 정적 파일6개의 HTTP 내용/길이/원본 SHA가 일치했다. 실제 프로젝트 `.env.ai`는 바꾸지 않았다. 각 서버는 검사 후 정상 종료0·pidfile 제거·8000 포트 닫힘을 확인했다(`.local/p8-runtime.json`). 네 설정별 전체 업무는 위의 실제 PG 기반 통합 테스트에서 검증했고, 이 독립 Gunicorn 검사에서는 개발 계정 비밀번호를 바꾸지 않고 기동/읽기 응답만 확인했다.

첫 개별 통합 검사에서 삭제된 현장의 업로드 확정 응답을404로 예상한 테스트1개가 실패했다. 기존 계약409/SITE_DELETED가 올바르므로 기대값을 수정하고 오류 코드도 확인하도록 보완했다. 업무 코드는 바꾸지 않았다. 재실행 통합/복원8개2.794초·근거 처리3개0.140초가 통과한 뒤 최종 전체267개를 실행했다. 실패 로그 `.local/p8-focused.log`도 보존했다. 기존 오류 주입 테스트가 남긴500/503 로그는 예상 실패 경로이며 개별 결과는 통과했다.

## 4. 직접 확인·미완료·다음

실행/검수 재현은 [README16절](../README.md#16-p8-기본-업무-통합-검수), 화면 확인은 README1·2·11~15절을 따른다. 실제 개발 DB의 가짜 사용자3명·고객65건·할당0건과 기존 비밀번호를 유지한다. 파괴적 작업과 복원은 테스트 DB에서만 수행했다.

P8 범위의 미해결 차단 문제는 없다. 다음 P9은 AI 요청/결과/quota·비용 예약·worker·테스트 adapter·파생 결과 재귀 무효화다. 직원 하루 합산30회·주간 브리핑·코칭·가이드 본 기능은 아직 구현하지 않았다. 유료 API 호출·유료 자원·운영 배포는 별도 요청 전까지 수행하지 않는다. Docker 실행/레이어·운영 백업/HTTPS·실제 모바일/Safari/Firefox·20명 SLA는 미검증이다. 이번에는 P8까지 완료하고 다음 요청을 기다린다.

최종 정리: 문서 링크47개·코드블록/충돌·Python compileall·JS20파일 구문·Git diff 검사, v2.0 원문 SHA 불변·AI 파일0600/비추적/제외·빈 예시 허용을 확인했다(`.local/p8-audit.json`). 검사 이후 코드/검수 매핑 소스 해시가 그대로이며69항목을 다시 대조했다. 개발 사용자3명·고객65건·현재 할당0·PENDING 요청0을 읽기 전용으로 재확인했고 테스트/복원 DB 잔존0이었다. 작업 소유 Gunicorn은 두 시나리오 각각 종료됐으며 전용 PG도 정상 종료했다.8000/55432 리스너 없음·pidfile 제거·DB 중지를 확인했다(`.local/p8-shutdown.json`). README1절 순서로 다시 실행할 수 있다.
