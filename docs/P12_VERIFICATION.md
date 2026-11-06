# P12 AI 보안·통합 검수

2026-11-06, Asia/Seoul. P11 완료 기록에서 이어서 P12를 진행했다. 설계서/sources·기존 사용자 변경·개발 계정/비밀번호·고객 자료를 보존한다. 실제 공급자 연결·실제 키 사용·유료 호출·운영 배포는 없다.

## 보강한 부분

- 직원 `employee-v1` 응답에 전체 UTF-8 크기 상한을 추가했다. 800 출력 cap의 테스트 단계 상한은 3,200바이트다. 개별 필드 길이가 유효해도 전체 상한을 넘으면 결과를 저장하지 않고 실패 정산한다. 실제 공급자 tokenizer를 대신하는 품질 보증은 아니다.
- 직원/관리자 응답의 잘못된 Unicode를 거부한다. 인코딩 예외로 worker가 RUNNING에 남는 경로를 막고 실패·예약 해제까지 검증한다.
- 키 없음·잘못된 단가·조직 예산 소진·공급자 실패 중에도 실제 직원 저장 API와 조회가 작동하는지 확인한다.
- 모든 AI 조회·페이지·알림과 scheduler/worker 단발 실행의 새 작업/호출/예약 0, 관리자 세 기능별 동시 요청 공유 slot, 처리 중 회수/재분배/휴지통/비활성화의 결과 거부를 확인한다.
- 동적으로 만든 비밀이 아닌 sentinel을 임시 0600 설정에서 읽어 서버 응답/로그·실제 Chromium 요청/응답/DOM/console/브라우저 저장소를 확인한다. Git 문서·정적 파일·테스트 fixture에 sentinel을 저장하지 않는다. 브라우저는 로그인·직원 정리/선택 적용·관리자 생성/검토/게시 흐름을 실행한다.
- 설계서 AI 23문항과 실제 테스트 ID를 `tests/acceptance_ai.json`에 연결했다. 기본 69문항과 함께 소스 해시/개별 passed 결과를 대조하며 누락·skip·실패·낡은 해시·없는 Docker 증거를 통과로 처리하지 않는다. 해시 범위에 검수 JSON·Git/Docker 제외 규칙·Dockerfile·Compose·빈 AI 예시를 포함했다.

## Git·Compose·Docker 경계

`scripts/verify_ai_boundary.py`는 실제 Git index/ignore·빈 배포 예시·키 파일 권한을 확인한다. Compose는 `--no-env-resolution --no-interpolate`로 5개 서비스를 정규화하므로 실제 `.env.ai` 값을 읽거나 출력하지 않는다. AI 환경 파일은 web/ai_worker에만 연결된다. `.dockerignore`의 필수 규칙 확인은 정적 검사다.

**Docker CLI/엔진이 없어 실제 build context·이미지·각 레이어/history 검사는 미실행이다.** 정적 제외 규칙/Compose 파서 통과를 실제 Docker 검수로 대체하지 않는다. `18.8-22`는 이 증거가 없으므로 미완료로 남긴다. 현재 경계 감사는 Docker가 설치되어도 실제 이미지 검사가 수행되기 전까지 자동으로 이를 통과시키지 않는다.

후속 Docker 검수에는 실제 키 대신 임시 sentinel, 실제 적용되는 `.dockerignore`/Dockerfile, build context·전체 레이어·history·실행 web/worker/scheduler의 환경 경계를 함께 확인해야 한다. 실제 키/운영 자료를 복사하거나 새 과금 서비스를 켜지 않는다.

## 재현

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py test tests.test_p12 tests.browser_p12 tests.test_acceptance --noinput -v 2
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.browser_p10 tests.browser_p11 tests.browser_p12 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions tests.performance_reports --testrunner=config.acceptance_runner.AcceptanceRunner --evidence-label=p12 --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_ai_boundary.py --output .local/p12-boundary.json
.venv/bin/python scripts/verify_acceptance.py --results .local/p12-test-results.json --output .local/p12-basic-acceptance.json --markdown docs/P12_BASIC_ACCEPTANCE.md --stage P12
.venv/bin/python scripts/verify_acceptance.py --suite ai --results .local/p12-test-results.json --boundary .local/p12-boundary.json --output .local/p12-ai-acceptance.json --markdown docs/P12_AI_ACCEPTANCE.md --stage P12
```

Docker 미검증 시 경계 감사와 AI 결과 집계는 의도적으로 exit 1이다. JSON/Markdown의 미완료 사유를 확인한다. 기본69항목 집계·전체 테스트 성공과 별도의 판정이다.

## 실행 결과

**총413개 통과 = Django395개 + Node18개.** Django175.409초·Node0.142초, 서버/권한/복원332·실제 Chromium58·PG1만 건 성능5개다. P11 대비 서버8·브라우저2·근거검사2개를 추가했다. 개별395개 모두 passed·skip0·실행 전후 소스 해시 동일이다.

[기본69/69항목](P12_BASIC_ACCEPTANCE.md)과 [AI22/23항목](P12_AI_ACCEPTANCE.md)을 동일 소스로 대조했다. `18.8-22`의 실제 Docker 증거만 미완료다. 경계 감사·AI 집계의 exit1을 전체 테스트 실패와 혼동하지 않는다.

1만 건 업로드4.951초·분배/회수4.446초·자동 회수0.790초·현장 삭제5.004초·보고서 집계/근거 저장1.972초다. 최대 잠금4.486초·peak RSS351.69MiB로30초/10초/512MiB 기준을 통과했다. 보고서 입력11,704바이트이며 전체 SQL 집계와 표본 범위를 분리한다. 단일 로컬 가짜 자료 기준이며 운영20명 SLA가 아니다.

기본 자료 별도 DB 복원0.619초·163,780바이트0600 dump·전체 테이블 일치, 임시 DB/dump 제거를 재검증했다. AI 테이블이 채워진 별도 복원은 P13 범위다.

실제 개발 PG check 이상0·모델 차이0·미적용 migration0, 사용자3·고객65·현재 할당0·AI 요청/시도/quota0, User/Customer 전체 값 해시(비밀번호 포함) 불변·임시 테스트 DB0이다. 독립 Gunicorn2 workers를 키 없음/설정 오류/임시 가짜 키3경우로 실행해 health/로그인200·익명401·정적11개 SHA 일치·sentinel 로그 미포함·정상 종료를 확인했다. 임시 가짜 키가 설정되어도 일반 서버의 테스트 모드/실제 생성은 비활성이다.

최종 근거는 `.local/p12-tests.log`, `p12-test-results.json`, `p12-queue.log`, `p12-basic-acceptance.json`, `p12-ai-acceptance.json`, `p12-boundary.json`, `p12-runtime.json`, `p12-performance.json`, `p12-restore.json`, `p12-development-data.json`이다. 중간 검수 경로/브라우저 수집 오류도 `p12-focused-*.log`, `p12-browser-*.log`에 보존했다. 최종 파일 감사·검증 소유 서비스 종료를 확인한 뒤 아래에 기록한다.

## 남은 범위

P12의 실제 Docker 경계가 미완료다. P13 운영 백업/암호화/외부 보관·채워진 AI 자료의 별도 DB 복원·HTTPS·실제 모바일/다중 브라우저·20명 SLA도 남았다. 한국어 자유 문장의 의미/사실성·실제 공급자/단가/tokenizer/과금 품질은 미검증이다. 사실성·prompt injection 검사는 지정한 입력/출력과 무네트워크 fake 범위이며 실제 모델의 지시문 공격 내성을 증명하지 않는다.

최종 정리: 원문 SHA 불변·문서 링크93개/코드블록/충돌·JS24파일 구문·Python compileall·Git diff·동일 소스395개/기본69항목/AI22항목을 확인했다(`.local/p12-audit.json`). 검증 소유 Gunicorn과 전용 PostgreSQL을 정상 종료하고 PID 파일 없음·8000/55432 리스너 없음·DB 중지를 확인했다(`.local/p12-shutdown.json`). 개발 자료/비밀번호는 보존했다. 실제 Docker 검수1항목은 계속 미완료다.
