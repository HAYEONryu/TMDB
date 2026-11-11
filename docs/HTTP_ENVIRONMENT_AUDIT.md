# HTTP 서버 접속 환경 점검과 수정

2026-11-11 변경: HTTP 직원 화면의 전체 차단을 **조회 전용**으로 보완했다. 현장 선택·본인 담당 고객 조회·검색을 허용하고 편집·저장·AI 생성 및 암호화 키 요청은 중단한다. [현재 직원 접속 동작과 검증](EMPLOYEE_LOGIN_ACCESS.md)이 아래 이전 검수의 화면 전체 숨김 동작보다 우선한다. 아래 2026-11-08 검수 실행·횟수는 당시 결과로 보존한다.

기준일: 2026-11-08 KST. 사용자가 공개 IP의8000번 HTTP 주소로 실행 중이라고 알려주었고, 도메인은 아직 없다고 답했다. 서버의 로그인 페이지와 공개 JS에 대한 비인증 GET만 시도했지만 이 실행 환경에서는 URLError로 연결하지 못했다. 서버 로그인·고객 조회·설정 변경·배포·유료 호출은 실행하지 않았다. 실제 서버 적용 여부와 외부 접속 상태는 미검증이다.

## 점검 범위와 처리

자체 JS27개와 포함된 Tabulator의 직접 보안 API 참조를 점검했다. 소스에서 실제 사용하는 브라우저 API를 기준으로 수정했으며 모든 브라우저·확장 프로그램·미래 버전의 동작을 보장한다는 뜻은 아니다.

| 기능/API | HTTP·브라우저 제한 | 처리 |
|---|---|---|
| crypto.randomUUID | 일반 HTTP에서 미제공 | 이전 공통 UUID v4/getRandomValues 대체 처리를 유지하고 HTTP 계정 생성·수정·재설정으로 재검증 |
| crypto.subtle / AES-GCM | 보안 컨텍스트 필요 | 직원 편집 전에 확인. HTTP에서는 조회 전용·HTTPS 안내, 고객 편집·암호화 키 요청·저장 요청 중단. 평문 보관으로 바꾸지 않음 |
| navigator.locks | 보안 컨텍스트·지원 브라우저 필요 | 시작·행 잠금·전송 전에 검사. 잠금이 없으면 안내하고 전송 중단, 기존 대기값 유지 |
| indexedDB | HTTP 자체의 제한은 없지만 권한/저장 정책으로 접근·열기 실패 가능 | API 없음·접근 거절·실제 open 거절을 구분해 안내. 보관소를 열지 못하면 편집을 시작하지 않음 |
| TextEncoder / TextDecoder | 구형 브라우저에서 미제공 가능 | 모듈을 읽는 즉시 생성자 오류가 나지 않도록 하고 직원 저장 사전 검사에서 안내 |
| AbortSignal.timeout | 일부 브라우저 미지원 | 이 메서드 의존성을 제거하고 AbortController/타이머 사용. 응답 본문 처리까지10초 제한 유지. 본문 AbortError를 상위 코드가 삼켜도 성공으로 판단하지 않음 |
| BroadcastChannel | API가 있어도 저장 정책으로 생성·전송 거절 가능 | 선택형 탭 알림의 생성·전송 예외를 처리. 서버의 권한/세션/할당 검사 유지 |
| sessionStorage | 저장 정책으로 접근 거절 가능 | 기존 try/catch와 메모리상 동일 요청 재시도를 유지. 접근을 차단한 실제 브라우저에서도 계정 생성/수정/재설정 검증 |
| structuredClone·dialog.showModal·fetch·FormData·Intl·ResizeObserver 등 | 일반 HTTP 전용 제한 없음. 지원하는 현대 브라우저 필요 | 동작하는 API를 불필요하게 대체하지 않음. HTTP 관리자·엑셀·표·모바일·재시도 흐름으로 확인 |
| Clipboard·Service Worker·Geolocation·파일시스템 선택 API | 일부 API는 HTTPS 필요 | 현재 자체 앱에서 해당 기능을 호출하지 않음. 직원 복사/우클릭 제한과 다운로드 미제공 유지 |

HTTP로 로그인한 화면에는 현재 연결 상태를 안내한다. 직원 고객 화면은 저장 지원 조건이 부족하면 조회 전용으로 전환한다. 현장 선택·검색·페이지 이동·현재 담당 고객과 이력 조회를 제공하며 저장 버튼·재콜 완료·삭제 요청·AI 조작은 제한한다. 일반 HTTP의 직원 암호화 키/context와 저장 API 요청은 보내지 않는다. 평문 대기값을 만들지 않는다. 실제 보관소 열기가 실패한 경우에는 기존 복구 안내와 편집 차단을 유지한다. 로그아웃은 사용할 수 있다. 직원 대시보드 같은 조회 화면도 기존 권한 범위에서 동작한다.

보관소를 연 뒤 편집 중 용량 부족이 생기는 기존 실패 처리와 즉시 서버 저장/이동 방지 동작은 유지했다. 기존 암호화 대기값을 삭제하거나 미확인 저장을 성공으로 표시하지 않는다. HTTP 로그인과 고객정보 전송의 네트워크 암호화는 JS 호환 함수로 해결되지 않는다.

공식 근거: [Web Crypto 보안 컨텍스트](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto), [Web Locks 조건](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/locks), [신뢰 가능한 localhost 예외](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts).

## 검증 근거

아래는 2026-11-08 당시 검증이다. 분리된 폐기용 PostgreSQL·가상 계정·가상 고객만 사용했다. 당시 브라우저 검사18개와 JS 검사41개에 최종 통과 근거가 있다. 각 실행의 코드 SHA는 따로 기록했고59개를 최종 SHA의 한 실행에서 모두 통과했다고 표현하지 않는다. P13 전체 재인수나 우분투 서버 검증이 아니며 최신 조회 전용 변경의 통과 근거로 대체하지 않는다.

- HTTP에서 계정 생성/수정/재설정, 엑셀 검증/확정, 분배 부족 시 취소·분배 재시도·회수, 담당 변경·사용자 저장 재시도, 직원 비활성화 후 기존 세션 거절.
- HTTP에서 직원 편집 차단과 HTTPS 안내, 키/context·저장 요청 없음, 로그아웃 가능.
- HTTPS에 준하는 localhost 보안 컨텍스트에서 crypto.subtle/locks 미제공, IndexedDB 접근/open 거절을 각각 주입해 편집 전 차단 확인.
- AbortSignal.timeout을 제거해도 직원 저장·새로고침 후 값 보존 확인.
- 선택형 BroadcastChannel 생성 거절 및 sessionStorage 거절 상태에서 HTTP 계정 관리 확인.
- 정상 보안 컨텍스트에서 암호화 보관·오프라인 재실행·다중 탭 충돌·담당 변경·저장 중 용량 부족·세션 변경·응답 유실 복구 회귀 확인.
- UUID·CSPRNG·저장 지원 판정·잠금 소실 시 대기값 보존·시간 제한과 timer 정리·탭 알림의 메타데이터만 전달하는 JS 검사.

HTTP 시험은 Chromium에서 실제 isSecureContext=false인 로컬 주소를 사용했다. 페이지 시험의 tm-http.test는 loopback DNS 매핑, Playwright의 별도 요청 도구도 사용하는 관리자 시험은0.0.0.0 숫자 목적지를 사용한다. 검수 웹 서버 자체는 localhost에 바인딩하며 원격 배포가 아니다. API 부재/권한 거절 주입 시험은 실제 HTTP 시험과 구분한다.

| 실행 ID | 결과 |
|---|---|
| 20261108T143437751693Z-1fb41963f13944fc874e6c5abd6080c6 | 12개 중9통과·HTTP 검수 fixture/DNS/정리 오류3 |
| 20261108T143602901940Z-06ebde65e9b64776b3ebfda9f3853204 | 기존 암호화/저장 회귀5개 통과 |
| 20261108T143803993061Z-89ee3e3305ad47908f9905c0fe998f6b | HTTP 관리자3개 중 세션 종료1통과·fixture/DNS 오류2 |
| 20261108T144117664585Z-0994b4d1082f4967ac098d79575ac5f3 | HTTP 관리자3개 중2통과·분배 fixture CSRF helper 누락1 |
| 20261108T144227358396Z-9a8922a1d33542d295b8c7ff9f92b443 | 누락 helper 연결 후 분배1개 통과 |
| 20261108T144348772212Z-5f6eedd39d944702985a76cbb64438d7 | JS40개 통과·정적 API inventory |
| 20261108T144546489105Z-dc39577a9e6044198c416ff40499e59e | 추가된 보관소 open 거절 검사·기존 저장 중 용량 부족 검사2개 통과 |
| 20261108T144547594195Z-e19aabb9a91645e2bf21550e31d54ff1 | 최신 JS41개 통과·자체 JS27개 구문/API inventory 확인 |

초기 HTTP 관리자 시험의 Playwright route.fetch/APIRequestContext는 브라우저 전용 DNS 규칙을 공유하지 않아 실패했고, 종료 중 같은 오류가 드러났다. 숫자 로컬 목적지와 브라우저 기반 세션 상태 확인으로 검수 fixture를 수정했다. 재사용 fixture에서 빠진 CSRF helper도 연결했다. 자연 발생 서버 장애나 앱 권한 오류를 수정한 것으로 표현하지 않는다. 실패 기록은 `.local/verification-runs/<실행ID>/`에 그대로 남겼고 성공 결과로 덮어쓰지 않았다. 사용하지 않게 된 초기 fixture의 비활성화 시험은 새 브라우저 시험으로 교체했으며 현재 검사 목록 기준으로 통과를 집계한다.

쿠키·인증 헤더·요청 본문·고객값·암호화 키·원시 예외는 새 검수 보고서에 기록하지 않았다. AI 실제 호출0회, 기존 개발/데모 DB 변경0, AI 설정·키 변경0이다. 실제 공개 HTTPS·해당 서버의 브라우저 조작·Docker 빌드/재시작은 미검증이다.

## 서버에 적용

직접 Python/Gunicorn 실행 환경은 웹과 같은 가상환경·설정으로 수행한다.

```sh
git pull origin main
python manage.py collectstatic --noinput
```

그 후 사용 중인 웹 프로세스를 재시작하고 브라우저를 강력 새로고침한다. DB 초기화나 비밀번호 변경 절차는 포함하지 않는다. Docker는 최신 앱 이미지를 빌드·검증하고 운영 Compose의 이미지 식별자를 갱신해 재생성해야 한다. 서버 적용은 이번에 실행하지 않았다.

## 도메인이 없는 경우

**공개 직원 서비스에는 신뢰 가능한 HTTPS 접속이 필요하다.** 도메인이 없어도 IP 주소용 공인 인증서가 가능하다. Let's Encrypt는2026-01-15부터 IPv4/IPv6 인증서를 일반 제공하며 shortlived 프로필의 유효기간은160시간이므로 자동 갱신이 필수다. [공식 안내](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)

IP 인증서를 지원하는 ACME 클라이언트,80/443 검증/서비스 포트, TLS 프록시, 갱신·재로드·볼륨 보존을 서버에서 준비하고 실제 검증해야 한다. 현재 저장소의 Caddy 설정에 IP만 넣으면 공인 IP 인증서가 자동 준비된다고 보장하지 않는다. 서버 접속·인증서 발급·방화벽 변경은 이번 범위에서 실행하지 않았다.

현재처럼 서버의8000번 HTTP 앱이 동작하는 환경에서 관리자 PC의 임시 확인은 SSH 터널을 사용할 수 있다. 자신의 SSH 접속 계정·인증 방식으로 아래 SERVER_IP와 YOUR_SSH_USER를 바꾸고, PC에서 실행한다.

```sh
ssh -N -L 127.0.0.1:18000:127.0.0.1:8000 YOUR_SSH_USER@SERVER_IP
```

접속 주소는 `http://127.0.0.1:18000/app/admin`이다. 서버 앱이127.0.0.1/localhost Host를 허용해야 한다. 이미 HTTPS 전용 운영 설정을 쓰는 경우 리다이렉트·Secure 쿠키·프록시 조건을 별도로 맞춰야 하며 보안 설정을 임의로 해제하지 않는다. 터널을 쓰는 동안 인터넷 구간은 SSH로 보호되고 브라우저는 loopback을 신뢰 가능한 컨텍스트로 취급한다. 종료는 터미널 Ctrl+C이며 앱 서버 자체를 종료하지 않는다. 공개 직원용 HTTPS 준비와 구분하며 이 서버를 대상으로 실제 SSH 연결을 검증하지는 않았다. [OpenSSH -L 설명](https://man.openbsd.org/ssh#L)

재현:

```sh
node --test tests/browser_environment.test.mjs tests/request_id.test.mjs tests/employee_queue.test.mjs
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label http-environment-focused tests.browser_http_environment
.venv/bin/python scripts/run_final_verification.py test --label https-storage-regression tests.browser_employee.EmployeeBrowserTests.test_offline_encrypted_persistent_browser_restart_user_isolation tests.browser_employee.EmployeeBrowserTests.test_multitab_explicit_conflict_and_reassignment_blocks_old_queue tests.browser_employee.EmployeeBrowserTests.test_quota_failure_attempts_server_and_blocks_navigation_when_both_fail tests.browser_employee.EmployeeBrowserTests.test_session_invalid_stops_retries_and_account_switch_hides_values tests.browser_employee.EmployeeBrowserTests.test_inflight_later_edit_and_lost_response_recovery
.venv/bin/python scripts/run_final_verification.py stop
```
