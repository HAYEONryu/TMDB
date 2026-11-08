# 브라우저 요청 ID 생성 호환성 수정

2026-11-08 KST. 사용자 추가 중 `crypto.randomUUID is not a function` 오류 제보에 따른 수정이다. 실제 사용자 서버의 URL·브라우저 설정은 직접 관찰하지 않았다. 같은 오류는 아래 로컬의 일반 HTTP 환경에서 재현했다.

## 원인과 변경

기존 화면은 요청 중복 방지 키와 저장 mutation ID를 만들 때 `crypto.randomUUID()`를 직접 호출했다. 이 API는 보안 컨텍스트에서만 제공된다. `localhost`는 HTTP에서도 신뢰 가능한 예외여서 기존 로컬 브라우저 검사가 이 문제를 잡지 못했다. 일반 HTTP 서버 주소에서는 이 함수가 없어 사용자 추가 요청을 보내기 전에 오류가 날 수 있다.

`static/request-id.js`의 공통 함수를 추가했다. 기본 `randomUUID()`가 있으면 사용하고, 없으면 암호학적 난수인 `getRandomValues()`로 UUID v4의 버전·variant 비트를 설정한다. 보안 난수 API도 없으면 이해할 수 있는 오류를 표시하고 요청 ID를 생성하지 않는다. Math.random·시각 기반 난수로 바꾸지 않는다.

사용자 생성/수정/비밀번호 재설정, 분배/회수, 고객 저장/담당 변경/삭제, 재콜 완료, 엑셀 업로드, 직원 대기열, AI 요청을 포함해11개 모듈의 직접 호출을 공통 함수로 교체했다. 기존 재시도 시 같은 키와 본문을 유지하는 로직은 그대로다. 계정·비밀번호 정책, 서버 권한 검사, DB schema, AI 설정은 변경하지 않았다.

공식 근거: [randomUUID의 보안 컨텍스트 조건](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/randomUUID), [일반 HTTP에서도 사용할 수 있는 getRandomValues](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/getRandomValues).

## 검증

분리된 폐기용 PostgreSQL과 가상 계정/고객만 사용했다. 기존 개발·데모 DB와 실제 서버는 변경하지 않았고 AI 외부 호출0회다.

| 검사 | 결과 |
|---|---|
| 수정 전 일반 HTTP에서 사용자 추가 | 오류 재현: 요청 후 성공 안내를 확인하지 못함 |
| 일반 HTTP: 계정 생성·이름 수정·비밀번호 재설정 | 통과. isSecureContext=false, randomUUID 미제공, getRandomValues 제공을 브라우저에서 확인 |
| localhost 보안 컨텍스트: 같은 흐름 | 통과. 기본 randomUUID 제공 |
| 분배·회수·직원 저장·담당/사용자 저장·엑셀 응답 유실 재시도 | 영향 브라우저 검사 통과 |
| UUID 형식·버전/variant·선행0·난수 API 미제공·직원 저장 동일 mutation 재시도 | Node 검사25개 통과(기존19+신규6) |
| 정적 JS24개 구문·상대 import 경로·남은 직접 호출 | 통과 |

브라우저6개 검사에 최종 통과 근거가 있다. 일반 HTTP 시험은 Chromium의 DNS 매핑으로 `tm-http.test`를 검수용 loopback 서버에 연결했다. 별도 웹 서버 배포 없이 브라우저가 실제 비보안 컨텍스트로 판단하는 조건이며 randomUUID를 임의로 숨긴 모의 시험이 아니다. localhost 시험은 공개 인증서/실제 HTTPS 연결 검증을 대신하지 않는다.

| 실행 ID | 결과 |
|---|---|
| 20261108T141542232635Z-e60d5661ba3845fb9cfdc55a49a4c01a | 수정 전 HTTP 오류 재현,1개 실패 기록 보존 |
| 20261108T141735376276Z-e9dceadfeada4064a7a8dcbcabf3cb55 | HTTP/기본 API·분배·저장 브라우저4개 통과 |
| 20261108T141834189216Z-e9f8847eae6a43119f5534f97467e427 | 직원 저장·엑셀 재시도 브라우저2개 통과 |

실행별 소스 SHA와 정제 결과는 `.local/verification-runs/<실행ID>/`에 보존했다. Node25개 결과는 실행 터미널에서 확인했으며 별도의 원시 로그 파일은 생성하지 않았다. 공개 HTTPS·실제 사용자 브라우저·운영 Docker 이미지 실행은 미검증이다.

## 서버 적용

직접 Python/Gunicorn으로 실행 중인 서버는 프로젝트 폴더·가상환경에서 최신 코드를 받고 정적 파일을 갱신한 뒤, 사용하는 웹 서비스 관리 방식으로 앱을 재시작한다.

```sh
git pull origin main
python manage.py collectstatic --noinput
```

브라우저에서도 강력 새로고침한다. 운영 설정을 별도로 쓰는 경우 collectstatic도 웹과 동일한 설정/환경에서 실행한다. Docker는 최신 소스가 포함된 새 앱 이미지를 빌드·검증하고 운영 Compose의 이미지 식별자를 갱신해 웹/작업자를 재생성한다. 운영용 Compose는 `image:`를 사용하므로 git pull만으로 컨테이너 내용이 바뀌지 않는다. 이번에는 실제 서버 적용을 실행하지 않았다.

**운영 HTTPS는 여전히 필요하다.** 이 수정은 UUID 생성 오류를 해결하며 일반 HTTP에서 시스템 전체의 동작을 보장하지 않는다. 특히 직원 대기열의 AES-GCM 암호화에는 보안 컨텍스트의 `crypto.subtle`이 필요하다. 암호화를 해제하거나 평문 저장으로 바꾸지 않았다.

재현 명령:

```sh
node --test tests/request_id.test.mjs tests/employee_queue.test.mjs
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label request-id-http-fixed tests.browser_request_id tests.browser_p4.P4BrowserTests.test_distribution_shortage_lost_response_reload_replay_and_today_recall tests.browser_p4.P4BrowserTests.test_assignee_and_user_save_lost_response_replay_and_noop
.venv/bin/python scripts/run_final_verification.py test --label request-id-save-import-regression tests.browser_employee.EmployeeBrowserTests.test_transient_retry_same_mutation_and_no_write_when_recovery_check_fails tests.browser_imports.ImportBrowserTests.test_lost_response_expiry_fatal_rollback_and_transient_retry
.venv/bin/python scripts/run_final_verification.py stop
```
