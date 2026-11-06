# P13 인수·운영 준비 검증

2026-11-06, Asia/Seoul. 사용자의 다음 단계 구현·검증 요청으로 P13 운영 준비를 구현했다. P12의 실제 Docker 경계는 엔진 부재로 계속 미완료다. 실제 운영 자원 생성·배포·유료 호출·실제 AI 공급자 연결은 하지 않았다. 기존 코드/사용자 변경·개발 계정·비밀번호·고객 자료를 보존한다.

## 구현

| 범위 | 결과 |
|---|---|
| 백업 명령 | `manage.py backup_database`, PostgreSQL17 dump를 age 공개 recipient로 바로 암호화. 백업 평문 파일을 만들지 않으며0600 파일·0700 경로·동시 실행 잠금·실패 코드 제공 |
| 보관·전달 | SHA-256 확인 후 원자적 완료 파일 공개. 파일 저장소와 엄격한 host key/BatchMode의 SSH 전송·원격 checksum·보관 코드. 전달 성공 후에만 기본7일의 이름이 검증된 완료 파일을 정리 |
| 복원 명령 | `restore_database`:전체 age 인증/복호화 후 새 `tm_restore_*` DB에만 복원. 잘못된 키/변조는 DB 생성0·기존/원본 DB 덮어쓰기 거부·pg_restore 실패 시 이번에 만든 DB만 제거 |
| 채워진 AI 복원 | 상담·AI_APPLIED·재콜·결과/근거·이전 코칭 graph·분류·게시본·무효 결과·UNKNOWN·quota/비용 예약 자료를 실제 생성. 암호화 백업→별도 PostgreSQL 복원→전체 테이블 값 해시·관계·원본 독립성 대조 |
| 운영 HTTPS | opt-in `production_settings`, 약한 secret/개발 비밀번호/DEBUG/seed 거부, Secure cookie·HTTPS redirect·신뢰 프록시 헤더·해당 도메인1시간 HSTS. Caddy가 전달 스킴을 덮어씀 |
| 운영 Compose | 개발 Compose와 분리한5서비스·프록시만 공개 포트·DB 비밀번호 파일·web/worker만 AI env·불변 digest/권한/경로 사전 검사. 실제 Docker 실행은 미검증 |
| 여러 브라우저 | 실제 로컬 Caddy TLS에서 Chromium/Firefox/WebKit 데스크톱·WebKit390px 터치 화면의 로그인·저장·오프라인 복구·Secure cookie·문서 가로 넘침0 검사 |
| 동시20명 | 19직원+1관리자·1만 고객·별도 세션·실제 Gunicorn2 workers×4 threads·조회100/저장100 HTTP·계정 범위 검사. 조회 p95<2초·저장 p95<3초를 테스트 기본값으로 사용 |
| 조회 성능 보완 | 현재 할당의 직원/ID 부분 인덱스 migration·직원의 현재 할당 ID를 먼저 선택하는 조회. 통계 추정이 빗나갈 때 직원별 할당을 고객마다 반복 탐색하는 계획을 피함 |
| 종합 인수 | 동일 소스의 기본69+AI23=92문항 집계. 새 복원 검사도 기본 백업 문항의 필수 증거로 연결. 없는 Docker 증거·누락/skip·낡은 소스는 통과시키지 않음 |
| 운영 문서 | [운영 절차](OPERATIONS.md), 보호된 환경 예시·호스트 백업 service/timer·롤백/별도 복원·삭제 자료 재등장 주의·데이터 손실/보관·미검증 범위 |

## 재현

운영 검증 도구는 프로젝트 `.local/bin`/`.cache`에만 설치한다. age1.3.2·Caddy2.10.2의 공식 release SHA-256을 고정 확인했다. Firefox/WebKit은 프로젝트의 잠긴 Playwright와 일치하는 빌드를 사용한다. 시스템 서비스는 설치·활성화하지 않는다.

```sh
.venv/bin/python scripts/install_verification_tools.py --tool age
.venv/bin/python scripts/install_verification_tools.py --tool caddy
PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" .venv/bin/python -m playwright install chromium firefox webkit
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test tests.test_p13 tests.browser_p13 tests.performance_concurrent tests.test_acceptance --noinput -v 2
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.browser_p10 tests.browser_p11 tests.browser_p12 tests.browser_p13 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions tests.performance_reports tests.performance_concurrent --testrunner=config.acceptance_runner.AcceptanceRunner --evidence-label=p13 --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_ai_boundary.py --output .local/p13-boundary.json
.venv/bin/python scripts/verify_acceptance.py --results .local/p13-test-results.json --output .local/p13-basic-acceptance.json --markdown docs/P13_BASIC_ACCEPTANCE.md --stage P13
.venv/bin/python scripts/verify_acceptance.py --suite ai --results .local/p13-test-results.json --boundary .local/p13-boundary.json --output .local/p13-ai-acceptance.json --markdown docs/P13_AI_ACCEPTANCE.md --stage P13
.venv/bin/python scripts/verify_acceptance.py --suite all --results .local/p13-test-results.json --boundary .local/p13-boundary.json --output .local/p13-acceptance.json --markdown docs/P13_ACCEPTANCE.md --stage P13
```

현재 Docker 경계 증거가 없어 경계 감사·AI/전체92항목 집계는 의도적으로 exit1이다. 전체 테스트 성공과 환경 미검증까지 포함한 인수 전체 완료는 별도의 판정이다.

## 실행 결과

**총435개 통과 = Django417개 + Node18개.** 최종 Django213.044초·Node0.127초, 서버/권한/복원349·실제 브라우저62·PG 성능6개다. P12 대비 서버16·브라우저4·20세션 부하1·전체 근거검사1개를 추가했다. 개별417개 모두 passed·skip0·실행 전후 소스 해시 동일이다.

[기본69/69](P13_BASIC_ACCEPTANCE.md)·[AI22/23](P13_AI_ACCEPTANCE.md)·[전체91/92](P13_ACCEPTANCE.md)를 동일 소스로 확인했다. 미완료 문항은 `18.8-22`의 실제 Docker 증거다. 이 집계는 공개 HTTPS/외부 보관소 등 추가 운영 검증의 완료를 뜻하지 않는다.

암호화 백업171,412바이트·전체39테이블(채워진 AI12테이블) 복원·대조·정리1.355초다. 게시본/파생 근거·무효화·UNKNOWN·비용·quota와 원본 독립성을 확인했다. 잘못된 키/변조/기존 DB/부적합 dump·실패 정리·전송 실패·보관/동시 실행도 검증했다. 실제 외부 호스트 전송은 없다.

20독립 세션·200요청의 조회 p95 **0.192초**, 저장 p95 **0.268초**, 최대0.223/0.317초·실패0이다. 전체 진행 시간은 로그인 포함3.842초다. 같은 소스의1만 건 업로드5.392초·분배/회수4.997초·자동 회수0.986초·현장 삭제6.023초·보고서2.038초, 이5개 성능 검사 최대 잠금5.483초·peak RSS341.12MiB로 기존30초/10초/512MiB 기준도 통과했다.

실제 로컬 Caddy TLS의 임시 인증서를 Python 신뢰 저장소로 확인했다. HTTPS redirect·위조 전달 스킴 거부·Secure/HttpOnly cookie·CSRF·Chromium/Firefox/WebKit와 터치 화면의 저장/오프라인 복구를 실행했다. 브라우저는 임시 인증서 오류를 허용하므로 공개 CA 검증을 대신하지 않는다. 운영 Caddy 실제 adapt와 Compose 파서/사전 검사를 실행했으며 공개 운영 서비스를 시작하지 않았다.

개발 사용자3·고객65·현재 할당0·AI 요청/시도/quota0, User/Customer 전체 값/비밀번호 해시 불변·부분 인덱스 적용·임시 테스트/복원 DB0이다. 실제 개발 PG check 이상0·모델 차이0·미적용 migration0이다.

초기 PATH의 pg_dump16.15를 잘못 선택한 문제를 프로젝트 PostgreSQL17 우선 선택으로 수정했다. 20명 검사에서 추정1행/실제1만 행의 nested loop가 직원 할당을 반복 탐색하는 계획을 관찰했다. 인덱스만 추가한 중간 검사도 목표를 넘겨 현재 할당 사전 선택을 함께 적용한 뒤 같은 혼합 검수와 전체 회귀를 통과했다. 벽시계 기반 복원 시간을 단조 시계로 교정해 최종 전체 회귀를 다시 실행했다. 실패·첫 통과·진단 기록도 보존했다.

최종 근거는 `.local/p13-tests.log`, `p13-test-results.json`, `p13-queue.log`, `p13-basic-acceptance.json`, `p13-ai-acceptance.json`, `p13-acceptance.json`, `p13-encrypted-restore.json`, `p13-concurrency.json`, `p13-performance.json`, `p13-production-preflight.json`, `p13-boundary.json`, `p13-development-data.json`, `p13-{chromium,firefox,webkit,webkit-touch}.json`이다. 중간 기록은 `p13-focused*.log`, `p13-load*.log`, `p13-query-profile.jsonl`, `p13-tests-first.log`, `p13-test-results-first.json`이다. 최종 파일 감사·서비스 종료는 아래에 기록한다.

## 남은 검증

- Docker CLI/엔진 부재:실제 build context·이미지·전체 레이어/history·운영 Compose 기동은 미실행이다. 18.8-22는 미완료다.
- 외부 보관소/자격증명 미지정:암호화/로컬 별도 저장소 실제 전달·복원, SSH 성공/실패/보관의 단위 검증까지 수행한다. 실제 외부 전송·별도 장애 영역 보관·Linux timer 활성화는 미실행이다.
- 공개 도메인 미지정:실제 로컬 TLS와 설정 구문/배포 검사까지 수행한다. 공개 CA/운영 리다이렉트/네트워크 격리는 미검증이다. subdomain/preload를 켜지 않는 선택에 따라 Django W005/W021을 남긴다.
- 물리 모바일/실제 Edge 기기·운영 VM의20명 SLA는 미검증이다. 터치 화면은 에뮬레이션이며20명은 독립 HTTP 세션이다. 짧은 지정 패턴 측정으로 지속 부하/장애 중 SLA를 보장하지 않는다.
- 실제 공급자/모델의 한국어 품질·tokenizer·공식 단가/과금·실제 유료 호출은 미검증/비활성이다.

## 중단 지점 재개 후 최종 확인

2026-11-06, 마지막 파일 감사와 서비스 종료 기록을 마무리했다. 현재 소스 SHA가 위417개 Django 테스트 통과 당시와 일치하고, 모든 개별 결과와 기본69·AI22·전체91항목의 근거가 일치한다. Django 전체 재실행은 하지 않았다. Node18개는 다시 실행해 전부 통과했다. 문서 링크113개·코드블록/충돌·JS24파일 구문·Python compileall·Git diff·Git/Compose 비밀값 경계 검사를 통과했다. 실제 Docker 검사는 계속 미실행이다.

프로젝트 전용 DB에서 check·모델 차이·미적용 migration 모두0, 현재 할당 인덱스 존재, 기존 사용자3명·고객65건·비밀번호/전체 값 해시 불변·임시 DB0을 재확인했다. DB를 정상 종료해 PID 파일과8000/55432 리스너가 없음을 확인했다. 근거는 `.local/p13-audit.json`, `p13-resume-queue.log`, `p13-resume-boundary.json`, `p13-resume-development-data.json`, `p13-shutdown.json`에 보존했다. 기존 개발 자료와 계정은 그대로이며 직접 실행은 README1절을 따른다.
