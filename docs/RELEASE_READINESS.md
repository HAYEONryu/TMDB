> **최신 최종 통합 검수(2026-11-08):** [FINAL_VERIFICATION.md](FINAL_VERIFICATION.md) 및 [92문항 현재 결과](FINAL_ACCEPTANCE.md)를 우선합니다. Gemini 3.5 Flash-Lite 무료 전용·유료 승인 $0이며 실제 운영은 보류입니다. 아래는 해당 작성 시점의 기록입니다.

# 릴리스 준비 상태 대조 보고서

> **2026-11-07 Lite 전용 환경 정리:** Gemini허용모델을Lite하나로제한하고실제.env.ai의중복변수4개를제거했다. 키·한도·두예산·AI비활성보존. DB없는22/22개검사0.279초통과, SHA `f7c53097903391c43ca945d8700678ceb555ebcbfe3c42848c5c19ea02a97e5f`. 자동승인검토사용량한도로검사PostgreSQL실행이거절되어DB/브라우저재검증은미실행이다(위험판정아님). [현재 변수·검증 한계](LITE_ENV.md).

> **2026-11-07 Gemini 종합 연결 준비 검수:** v2.0/P13/현재 기록·코드를 대조하고 적용AGENTS 없음 확인.3.8 Flash 공식 ID/API/구조화 출력/usage/오류를 확인했으며 사용자 후속 선택으로 로컬모델Lite는 보존했다. 환경설정 기반 명시적 모델 선택·파일 전용 비밀값·빈 예시·별도 테스트 누적 예산/월 예산·전송시작/재시도 집계를 보완했다. 직원20+관리자5명 동시성·관리자5명의3종 공유·선택적용/권한/주입/실패·232개 최신 통과 근거 확보. 후속98/98·마지막26/26통과, 최종SHA `3800c50a072a398829a4605730cdb03f697fbfd44b4a6fb5b87cf5879480a99a`. 비밀값 소스/로그/Git 일치0·실제 파일미추적·600, Compose읽기전용파일 마운트 정적검사 통과. Docker실기·공급자 실제 접근/품질/사용량은 미검증, 실제 AI0회·AI 비활성·원본DB 중지상태 보존. [최신 환경값·검증·재시작](GEMINI_READINESS.md).

> **2026-11-07 Gemini 3.5 Flash Lite:** 현재 고정 모델은 `gemini-3.5-flash-lite`, 무료 공용 한도는 RPM15/입력TPM250,000/RPD500이다. 직원40회·관리자 결과 공유·서버 공용 예약 우선·분당 대기·추론low를 유지했다. 관련41/41검사15.288초 통과, SHA `e2ba4e64ceb6a575e4207561e82693facb6c2e2daa6c14e924ef021df08f1090`. 기존 키/자료·중지된 데모 상태 보존, 실제 API0회·AI 비활성. [최신 정책·전환 검증](FREE_AI_USAGE.md).

> **2026-11-07 무료 티어 공용 한도:** 최신 사용자 요구로 직원 개인 한도를40회로 변경하고, 확인받은 무료 프로젝트의 공용 RPD20/RPM5/입력TPM250,000을 먼저 적용했다. 접수·진행 중 요청도 선예약하고 분당 여유가 생길 때 DB 대기열에서 전송한다. 관리자 결과 공유·무료 비용0·자동 유료 전환 금지. 서로 다른188개 항목의 최신 통과 근거 확보, 개인정보 삭제 검토 누락 수정 후 관련28/28통과, v5→v6 보존 마이그레이션1/1통과. 최종SHA `681a37c026bd3c05ecf8bc2495f755cb15b2ce5bf9e92782ec5dc24bc7b151fb`. 기존 데모/개발DB는 중지 상태로 보존했고 별도 테스트PostgreSQL55434만 사용했다. 실제 호출0회·AI 비활성, 전체92개·Docker·운영 인수 신규 통과를 뜻하지 않는다. [최신 정책·실행별 근거](FREE_AI_USAGE.md).

> **2026-11-07 Gemini 전환:** 기본 모델을 `gemini-3.8-flash`로 바꾸고 사용자의 선택대로 직원·관리자 모두 low를 적용했다. 기존 OpenAI 키를 보존하고 Gemini 키는 별도 서버 항목으로 분리했다. 월USD5·하루 합산30회·관리자 주기·중복/예약/실패 규칙을 유지한다. 가짜 응답/격리 PostgreSQL 검사60/60, 공유 회귀102통과/1개 브라우저 버튼 이름 오류 후 해당1/1재검사 통과로 **163개 서로 다른 항목의 통과 근거**를 확보했다. 최종 소스 SHA `fddfa3a1290726a446b1381a5ce76f435e95d273cd50884bdfa261530557f858`. 실제 유료 호출0회·AI 비활성, 전체92개·Docker·운영 복원 신규 검증은 포함하지 않았다. [모델·단가·구현·실행별 근거](GEMINI_CONNECTION.md).

> **2026-11-07 그래프 현장 선택 후속 수정:** 관리자 상담결과 그래프에서 현장을 직접 선택하고 기간은 **전체 기간/금주/오늘**로 분리했다. 상단 현장 선택과 양방향 연동한다. 변경 관련 PostgreSQL·Chromium 검사2/2통과(4.802초), 소스 SHA `01dee7f3341791db4b67ae2491109171e7dd15df821610b46f6c91ff1f291646`. 서버 집계·권한은 변경하지 않았고 기존 통과 검사는 재사용했다. 전체92항목·Docker·복원 검사를 반복하지 않았다. [최신 사용법·검증](BLUE_DASHBOARD.md#현장기간-선택-후속-수정--2026-11-07).

> **2026-11-07 네이비·블루 전체 화면/팀장 통계:** 직원 버전을 포함한 모든 공통 화면에 왼쪽 메뉴·블루 컨셉을 적용했다. 팀장의 오늘 할당DB, 직원별 최근7일 상담기록, 현장 전체/이번주/오늘 상담결과, 직원별 분배·영업 진행을 실제 집계로 연결했다. 신규 서버10+기존 서버2+브라우저22의34항목 통과 근거, 최종25/25통과54.000초,31화면/상태 확인. 소스 SHA `7ff9b3864eef41c347a4e5645ac22912d79e2f9fc3e83b7a89655b8e3fb77564`. 초기 테스트 fixture 오류와 실패 항목 재검사·기존 통과 재사용을 구분했다. **아래92항목 전체를 이 버전에서 새로 통과시킨 것은 아니다.** 기존 자료·개발 DB 보존, AI 요청/시도0·비활성으로 실행 중이다. [집계 기준·화면·검증](BLUE_DASHBOARD.md), `.local/blue-dashboard-audit.json`을 따른다.

> **2026-11-07 두드림 TM UI/UX 변경:** 로고·제목과 로그인/메뉴/대시보드/업무 표를40~50대의 읽기·조작 편의 중심으로 개선했다. 화면22조합 확인, 변경 영향에 따라 재검사한 브라우저25개 항목 통과 근거·Node19/19통과. 재확인과 대기값 폐기가 겹치는 로컬 기록 경합도 수정했다. 초기 DB 연결 오류와 간헐 실패/재현·수정·재검사 범위는 [화면 개선 기록](UI_REDESIGN.md)에 구분했다. 최종 소스 SHA는 `6a44b5f6205db39879e79bf24ca40a40335cdea0e28a4a840f9bb91eb5af9c2f`이며 SVG 해시는 별도 감사에 포함한다. **아래92문항을 최종 화면 버전 전체 검증으로 갱신하지 않았다.** 데모 업무 자료·개발 DB 보존, AI 요청/시도0·비활성, 실행 중이다. 원시 근거는 `.local/ui-final-audit.json`이다.

> **2026-11-07 키 보존·운영 정책 후속 점검:** 기존 `.env.ai`의 키/전체 바이트 보존·0600·비활성·월USD5. 추가 운영 정책5개+Chromium 비밀값2개7/7 통과(7.179초). 기존142개 검사 구현 파일 해시가 같아 결과를 재사용했다. 새 테스트 추가 후 소스 SHA는 `686bd4890ee943862ef58ca810fa401d8a04bf3839d97ca6393d08c6a0980500`다. Git 추적/인덱스/조회 가능한 이력·정적 자산·로컬 로그에 현재 키 일치0건, 환경 파일 URL404, 역할별 로딩 차단을 확인했다. Docker 실제 이미지/레이어는 CLI·엔진 부재로 계속 미검증이다. 운영 실패의 가짜 성공 대체·자동 유료 모델 전환은 없고 실제 유료 호출0회다. **92문항 전체를 새 버전에서 재검증하지 않았다.** 파일/실행 명령은 [AI 활성화 안내](AI_ACTIVATION.md), 근거는 `.local/ai-env-audit.json`, `.local/ai-operating-tests.json`이다.

> **2026-11-07 OpenAI 연결 후속 변경:** 테스트 전용 어댑터만 있던 서버에 실제 `gpt-6-luna` Responses 연결을 추가했다. 직원 `none`·관리자 `low`·Standard를 고정하며 실제 작업의 자동 재시도/유료 모델 전환은 없다. 새18개+영향받는 기존124개, **142/142 서버 검사 통과(19.464초)**. 실제 API는 호출하지 않았으며 계정별 모델 접근·실제 청구·한국어 품질은 미검증이다. 검사 구현 소스 SHA는 `d5f8079edc44b3c6559aa6a8faf15f0e3501930b1a6606be6eff118ccfed336f`, HEAD는 아래와 동일하다. 별도 `test_tm_openai_adapter`를 제거했고 데모에 추가 컬럼 migration만 적용했다. 데모 업무 자료와 중지된 개발 DB 제어 파일 해시 불변, 데모 AI 요청/시도0·웹 정상이다. Git/Compose 비밀값 경계는 통과했으나 실제 Docker 검사는 여전히 미검증이다. **아래92문항 전체를 새 버전에서 재검증한 결과로 갱신하지 않는다.** 상세·공식 단가·재현은 [OpenAI 연결 검증](OPENAI_CONNECTION.md), 원시 로그는 `.local/demo/openai-tests.log`, 후속 근거는 `.local/openai-verification.json`이다.

> **2026-11-07 후속 데모 변경:** 아래 92문항/435개 결과는 2026-11-06 검토 시점의 스냅샷이다. 이후 직원 날짜 입력 방향키·Tab 충돌을 수정하고 관련 브라우저 검사2개를 별도 데모 테스트 DB에서 통과했다. 현재 소스 SHA는 `8c982193e1aa6e4855c6e0022953e0603b2128279288c74943a37b7f44212fce`이며 아래 P13 SHA와 다르다. 변경 파일은 `static/employee-grid.js`와 `tests/browser_employee.py`다. 전체 인수 검사를 재실행하거나 기존91항목을 새 버전 전체 검증으로 갱신하지 않았다. 실행 상태·계정·수정과 검증 범위는 [분리형 데모 안내](DEMO_WALKTHROUGH.md)를 따른다.

검토일: **2026-11-06, Asia/Seoul**. 근거 대조 시각: `2026-11-06T16:24:27+09:00`.

**92개 인수 항목: 통과 91 · 실패 0 · 미검증 1. 기본 업무의 로컬 시연은 가능하며, 운영 인수·배포 준비 완료 판정은 보류한다.** 미검증은 `18.8-22`의 실제 Docker 빌드 컨텍스트/이미지 경계다. 아래 통과는 가짜 자료·테스트 전용 AI 응답과 명시된 환경에서의 결과이며 실제 공급자 품질이나 운영 환경 전체를 보증하지 않는다.

이번에는 설계서·코드·테스트 정의·기존 원시 결과를 읽고 버전을 대조했다. **Django·Node·브라우저·부하·백업 복원 테스트 재실행은 0개**다. 앱 코드와 검수 매핑이 최종 P13 통과 버전에서 바뀌지 않았고 현재 실패 근거도 없어 통과 검사를 반복하지 않았다. PostgreSQL 상태와 설치 버전·Docker CLI 유무만 조회했으며 DB/웹/worker를 시작하지 않았다. 실제 고객자료 열람·업로드·가공, 실제 비밀값 열람, 유료 AI 호출, 서버 구매, 배포는 수행하지 않았다.

## 검사한 코드 버전과 근거의 유효성

| 구분 | 확인한 값 |
|---|---|
| Git HEAD | `354ef598a0edcc60415ce8cc3922e9550a79bb0d` · detached HEAD |
| 작업 트리 | 기존 수정·미추적 구현 파일이 있는 상태. HEAD 커밋만으로 현재 검증 코드를 식별할 수 없다. 커밋/파일 정리/체크아웃은 하지 않았다. |
| 현재 구현·검수 소스 SHA-256 | `d683ceabe5f400dff956242e6e6afbbe528169dd005adf16f4db722604270a42` |
| P13 최종 검사 소스 SHA-256 | `d683ceabe5f400dff956242e6e6afbbe528169dd005adf16f4db722604270a42` · 현재와 일치 |
| 설계서 | v2.0 · SHA-256 `0c2f3326868454aa654c0d367b5ec7b75e3ecd4f80510fb3c96fbae0657e6194` · 원문 불변 |
| 기존 Django 완료 시각 | `2026-11-06T03:19:54.400338+09:00` (원시 UTC: `2026-11-05T18:19:54.400338+00:00`) |
| 기존 테스트 결과 | Django 417/417 passed · 실패/오류/skip 0 · 실행 중 소스 불변. 그 안에 서버/권한/복원 349, 브라우저 62, PG 성능 6개 포함 |
| 기존 Node 결과 | P13 18/18 통과. 앞선 중단 재개 시 18/18 재통과 로그도 존재. 이번에는 재실행하지 않음 |
| 현재 설치 정보 | Python 3.13.18 / Django 5.2.18 / psycopg 3.3.7 / gunicorn 25.3.0 / playwright 1.64.1 / whitenoise 6.12.0 / openpyxl 3.1.5 |

공통 SHA는 `scripts/verify_acceptance.py:source_digest`가 정한 **227개 파일**의 상대 경로와 바이트를 정렬해 계산한다. `apps/config/scripts/static/templates/tests`의 `.py/.js/.mjs/.css/.html`, 인수 매핑 JSON, `deploy` 파일, Dockerfile/Compose/제외 규칙, 배포용 빈 환경 예시, 의존성 lock을 포함한다. 문서, `.local/.cache/.venv`, 수집된 `staticfiles`, 실제 `.env/.env.ai`, 실행 중 DB/운영 비밀값은 포함하지 않는다. 따라서 코드 SHA 일치가 환경·자료·의존성 설치 상태까지 같다는 의미는 아니다.

공통 SHA 밖의 루트 실행 설정도 내용과 Git 차이를 확인했다. 둘 다 HEAD 이후 변경이 없으며 별도 현재 해시는 다음과 같다. 이 해시를 P13의 공통 SHA에 소급 포함한 것으로 취급하지 않는다.

| 파일 | 현재 SHA-256 |
|---|---|
| [gunicorn.conf.py](../gunicorn.conf.py) | `44ee97b51e24de37f6a1306406d1f52acbf93e9c5dfb6bfa100c00f7ae8546cf` |
| [Caddyfile](../Caddyfile) | `169fd4df88582f9a2f985696f99876e19e0534640b36f2055fd26b4c272da4f9` |

각 문항의 설계서 원문/순서/수, 매핑된 테스트 정의의 존재, 개별 passed 결과, 경계 근거와 동일 소스 여부를 확인했다. P13의 `incomplete`는 이 보고서에서 원인을 분리해 `미검증`으로 표시했다. `실패`는 현재 유효한 테스트의 assertion 실패·실행 오류가 있는 경우이며, 환경이 없어 실행하지 않은 경우와 구분한다.

추적 자료: [설계서 v2.0](<TM_고객관리_개발설계서.md>), [최신 진행 기록](PROGRESS.md), [P13 검증 기록](P13_VERIFICATION.md), [P13 전체 결과표](P13_ACCEPTANCE.md), [기본 69항목 매핑](../tests/acceptance_basic.json), [AI 23항목 매핑](../tests/acceptance_ai.json). 원시 결과·227개 파일 해시·각 테스트 위치와 본 검토의 판정은 [.local/release-readiness-audit.json](../.local/release-readiness-audit.json)에 저장했다. `.local`은 Git 제외 경로이므로 이 저장소를 다른 환경으로 전달할 때 원시 검증 자료도 별도로 보존해야 한다.

## PostgreSQL·브라우저·Docker·백업 복원

| 영역 | 기존 실제 실행/검증 | 판정과 한계 |
|---|---|---|
| PostgreSQL | PostgreSQL 17.11 (`170011`), 실제 별도 연결·잠금·동시성·중단/재시작·migration·1만 건 성능 검사. P13 소스와 일치 | 로컬 PostgreSQL 검증 통과. SQLite 대체 검증이 아님. 이번 상태 조회는 중지 상태. 운영 DB/역할/네트워크/자료량 검증은 미실행 |
| 브라우저 | 기존 Chromium 58흐름에 P13 TLS 4흐름을 더한 브라우저 62개. P13은 Chromium/Firefox/WebKit 데스크톱 및 WebKit 390×844 터치 화면에서 로그인·저장·오프라인 복구·Secure cookie·가로 넘침 확인 | 로컬 범위 통과. 설치 빌드 디렉터리 Chromium 1248 / Firefox 1555 / WebKit 2370, Playwright 1.64.1. P13 JSON은 브라우저 제품 버전 문자열을 기록하지 않음. 실제 Chrome/Edge/물리 iPhone·Android 기기 인증 아님 |
| HTTPS | 임시 CA를 Python 신뢰 저장소로 확인한 로컬 Caddy TLS, HTTP→HTTPS 308·위조 스킴 헤더·HSTS·CSRF/cookie 검사 | 로컬 TLS 통과. 브라우저 `ignore_https_errors=True`; 공개 CA·실제 도메인의 인증서 검증은 미검증 |
| Docker | Compose 파싱·5서비스·web/ai_worker만 AI 파일 연결·Git/.dockerignore·운영 사전 검사 | 정적 부분 통과. 현재 Docker CLI 없음. 실제 build/up, 빌드 컨텍스트, 이미지 전체 레이어/history, 운영 컨테이너 기동은 미검증. `18.8-22` 전체를 통과로 올리지 않음 |
| 기본 자료 백업/복원 | 가짜 계정·할당·상담·재콜·삭제 요청을 dump→별도 빈 DB로 실제 복원. 현재 원시 근거 39테이블·164,187바이트·0.563초, 비밀번호 유효성·할당 관계·원본 독립성·정리 확인 | 통과. 삭제 요청 2건이 포함된 근거는 `p8-restore.json`이며 P13 전체 실행이 갱신한 파일이다. 파일명의 P8을 실행 버전으로 오해하지 않음 |
| 암호화/AI 포함 복원 | PostgreSQL 17 dump→age 1.3.2 암호화 171,412바이트→복호화→새 DB 복원. 39테이블 전체 값 해시 일치, AI 12테이블 실제 자료 존재, 1.355초·원본 독립성·임시 DB 제거 | 통과. AI_APPLIED·UNKNOWN·비용/예약·이전 코칭 graph·분류·게시·무효화 검증. 이 fixture의 삭제 요청 테이블은 0건이므로 위 기본 fixture와 함께 근거로 사용 |
| 복원 환경의 독립성 | 같은 로컬 PostgreSQL 클러스터 안의 다른 빈 DB에 복원. 로컬 별도 디렉터리로 암호문 전달 | 별도 DB 복원 통과. 다른 서버/다른 장애 영역·실제 SSH 전송·외부 저장소·보관 주기 운용은 미검증 (`offsite_verified=false`) |
| 20세션 부하 | 19직원+1관리자, 1만 고객, Gunicorn 2 workers×4 threads, 조회100/저장100, 실패0. 조회 p95 0.192초·저장 p95 0.268초 | 로컬 가짜 자료/지정 패턴 기준 통과. 운영 VM의 지속 부하·장애/복구 중 SLA는 미검증 |

근거: [p13-performance](../.local/p13-performance.json), [p13-concurrency](../.local/p13-concurrency.json), [p8-restore](../.local/p8-restore.json), [p13-encrypted-restore](../.local/p13-encrypted-restore.json), [p13-production-preflight](../.local/p13-production-preflight.json), [p13-resume-boundary](../.local/p13-resume-boundary.json), [p13-chromium](../.local/p13-chromium.json), [p13-firefox](../.local/p13-firefox.json), [p13-webkit](../.local/p13-webkit.json), [p13-webkit-touch](../.local/p13-webkit-touch.json). 개별 환경 JSON은 모두 자체적으로 코드 SHA를 포함하는 형식은 아니므로, 해당 생성 테스트가 같은 SHA의 P13 최종 실행에서 passed였는지와 최종 raw 로그를 함께 확인했다.

## 구현 대조 범위와 문항별 판정

아래 파일의 권한·버전·잠금·멱등성·저장/회수·AI 차단·삭제 및 복원 경로를 매핑된 테스트와 대조했다. 전체 테스트 수 435개와 인수 문항 수 92개는 다른 수치다.

| 설계 절 | 구현 대조 위치 | 통과 | 실패 | 미검증 |
|---|---|---:|---:|---:|
| 18.1 권한·계정 | [apps/accounts/middleware.py](../apps/accounts/middleware.py)<br>[apps/accounts/services.py](../apps/accounts/services.py)<br>[apps/accounts/management_services.py](../apps/accounts/management_services.py)<br>[apps/customers/access.py](../apps/customers/access.py)<br>[apps/customers/queries.py](../apps/customers/queries.py)<br>[apps/customers/services.py](../apps/customers/services.py) | 6 | 0 | 0 |
| 18.2 현장·업로드 | [apps/sites/services.py](../apps/sites/services.py)<br>[apps/imports/excel.py](../apps/imports/excel.py)<br>[apps/imports/services.py](../apps/imports/services.py)<br>[apps/customers/deletions.py](../apps/customers/deletions.py) | 9 | 0 | 0 |
| 18.3 분배·수동 회수 | [apps/assignments/services.py](../apps/assignments/services.py)<br>[apps/assignments/models.py](../apps/assignments/models.py)<br>[static/assignments.js](../static/assignments.js) | 7 | 0 | 0 |
| 18.4 저장·경합 | [apps/customers/services.py](../apps/customers/services.py)<br>[apps/customers/employee.py](../apps/customers/employee.py)<br>[static/employee-queue.js](../static/employee-queue.js)<br>[static/employee-store.js](../static/employee-store.js)<br>[static/employee-grid.js](../static/employee-grid.js) | 11 | 0 | 0 |
| 18.5 자동 회수·진행 | [apps/operations/scheduler.py](../apps/operations/scheduler.py)<br>[apps/customers/services.py](../apps/customers/services.py)<br>[apps/accounts/services.py](../apps/accounts/services.py)<br>[apps/assignments/services.py](../apps/assignments/services.py) | 9 | 0 | 0 |
| 18.6 재콜·삭제·운영 | [apps/customers/queries.py](../apps/customers/queries.py)<br>[apps/callbacks/services.py](../apps/callbacks/services.py)<br>[apps/customers/deletions.py](../apps/customers/deletions.py)<br>[apps/operations/backups.py](../apps/operations/backups.py)<br>[static/employee-grid.js](../static/employee-grid.js) | 9 | 0 | 0 |
| 18.7 직원 삭제 요청·관리자 승인 | [apps/customers/deletions.py](../apps/customers/deletions.py)<br>[static/deletion-action.js](../static/deletion-action.js)<br>[static/deletion-notifications.js](../static/deletion-notifications.js) | 18 | 0 | 0 |
| 18.8 AI 기능·사용 한도·결과 적용 | [apps/ai_assistant/services.py](../apps/ai_assistant/services.py)<br>[apps/ai_assistant/worker.py](../apps/ai_assistant/worker.py)<br>[apps/ai_assistant/employee_schema.py](../apps/ai_assistant/employee_schema.py)<br>[apps/ai_assistant/admin_schema.py](../apps/ai_assistant/admin_schema.py)<br>[apps/ai_assistant/reports.py](../apps/ai_assistant/reports.py)<br>[apps/ai_assistant/privacy.py](../apps/ai_assistant/privacy.py)<br>[apps/ai_assistant/apply.py](../apps/ai_assistant/apply.py)<br>[static/employee-ai.js](../static/employee-ai.js)<br>[static/admin-ai.js](../static/admin-ai.js) | 22 | 0 | 1 |
| **합계** | | **91** | **0** | **1** |

모든 `통과`는 **기존 결과 재사용**이다. 각 링크는 현 코드의 해당 테스트 정의이며 실행 결과는 `.local/p13-test-results.json`에서 ID별로 확인했다. 전체 테스트 ID는 `tests/acceptance_*.json` 및 `.local/release-readiness-audit.json`에 보존했다.

### 18.1 권한·계정

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.1-01 | 직원이 다른 직원의 고객 ID·할당 ID를 보내도 조회·저장이 거부된다. | **통과** | [test_p2.P2ApiTests.test_scoped_filters_candidates_and_errors_never_disclose_other_employee](../tests/test_p2.py#L121)<br>[test_p5.EmployeeTests.test_recall_same_employee_new_assignment_does_not_rebind_old_queue](../tests/test_p5.py#L62) |
| 18.1-02 | 직원의 필터 후보값에 타인 DB 값이 포함되지 않는다. | **통과** | [test_p2.P2ApiTests.test_scoped_filters_candidates_and_errors_never_disclose_other_employee](../tests/test_p2.py#L121) |
| 18.1-03 | 관리자도 고객명·연락처 수정 API를 사용할 수 없다. | **통과** | [test_p2.P2ApiTests.test_save_batch_partial_success_and_whole_row_validation](../tests/test_p2.py#L164) |
| 18.1-04 | 초기·재설정 비밀번호가 dodream이며 변경 전 업무 API는 차단된다. | **통과** | [test_auth.AuthenticationTests.test_admin_and_employee_login_initial_password_gate](../tests/test_auth.py#L38)<br>[test_auth.AuthenticationTests.test_reset_invalidates_all_sessions_and_requires_initial_change_again](../tests/test_auth.py#L94) |
| 18.1-05 | 비활성화·재설정 후 다른 브라우저의 기존 세션이 다음 요청부터 차단된다. | **통과** | [test_auth.AuthenticationTests.test_deactivation_invalidates_session_and_reactivation_does_not_restore_it](../tests/test_auth.py#L126)<br>[test_auth.AuthenticationTests.test_reset_invalidates_all_sessions_and_requires_initial_change_again](../tests/test_auth.py#L94) |
| 18.1-06 | 마지막 활성 관리자를 제거할 수 없다. | **통과** | [test_p4.P4Tests.test_last_admin_guard_and_atomic_handover_and_promotion_preserves_assignment](../tests/test_p4.py#L222)<br>[test_p4.P4ConcurrencyTests.test_two_last_admin_deactivations_keep_one_admin](../tests/test_p4.py#L312) |

### 18.2 현장·업로드

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.2-01 | 현장 중복 생성의 동시 요청도 하나만 성공한다. | **통과** | [test_p2.P2ConcurrencyTests.test_site_normalization_concurrent_one_success](../tests/test_p2.py#L365) |
| 18.2-02 | 기본 현장 변경은 작업 중인 화면을 강제 전환하지 않고 다음 화면부터 적용된다. | **통과** | [browser_p2.AdminGridBrowserTests.test_grid_paging_filters_manual_save_trash_restore_site_default_and_mobile](../tests/browser_p2.py#L81) |
| 18.2-03 | 첫 현장·기본 현장 삭제·마지막 현장 삭제의 빈 상태가 정상이다. | **통과** | [test_p2.P2ApiTests.test_sites_first_default_normalized_duplicate_and_explicit_default](../tests/test_p2.py#L65)<br>[test_p7.P7Tests.test_site_deletion_default_fallback_then_none_and_original_name_not_in_receipt](../tests/test_p7.py#L130) |
| 18.2-04 | 고객명·연락처 누락, 잘못된 enum·날짜·담당자 값은 행 오류로 표시된다. | **통과** | [test_imports.ImportTests.test_first_valid_phone_wins_invalid_earlier_does_not_reserve_phone](../tests/test_imports.py#L127)<br>[test_imports.ImportTests.test_numeric_phone_is_never_repaired_and_invalid_types_enums_lengths](../tests/test_imports.py#L133)<br>[test_imports.ImportTests.test_dates_excel_datetime_strings_weekday_ignored_and_date_only_rejected](../tests/test_imports.py#L141)<br>[test_imports.ImportTests.test_formula_staff_and_extra_columns_fail_rows_not_entire_valid_file](../tests/test_imports.py#L121) |
| 18.2-05 | 010 하이픈 유무는 동일 연락처로 취급한다. 다른 현장의 같은 번호는 등록된다. | **통과** | [test_imports.ImportTests.test_existing_duplicates_include_trash_but_different_site_allowed](../tests/test_imports.py#L152)<br>[test_imports.ImportTests.test_first_valid_phone_wins_invalid_earlier_does_not_reserve_phone](../tests/test_imports.py#L127) |
| 18.2-06 | 휴지통 중복·파일 내 중복·동시 업로드 중복이 기존 상담정보를 덮어쓰지 않는다. | **통과** | [test_imports.ImportTests.test_existing_duplicates_include_trash_but_different_site_allowed](../tests/test_imports.py#L152)<br>[test_imports.ImportConcurrencyTests.test_two_batches_same_phone_revalidate_under_lock](../tests/test_imports.py#L355) |
| 18.2-07 | 검증 당시 정상이어도 확정 전에 생긴 중복을 다시 검사한다. | **통과** | [test_imports.ImportTests.test_commit_revalidates_new_duplicates_and_replay_counts_do_not_change](../tests/test_imports.py#L182) |
| 18.2-08 | 같은 업로드 확정 재시도가 이중 등록되지 않는다. | **통과** | [test_imports.ImportConcurrencyTests.test_same_batch_same_key_exactly_once](../tests/test_imports.py#L349) |
| 18.2-09 | 1만 행 처리의 메모리·응답 시간을 측정하고 시간 초과를 조용히 무시하지 않는다. | **통과** | [performance_imports.ImportPerformanceTests.test_10000_rows_actual_postgresql](../tests/performance_imports.py#L27) |

### 18.3 분배·수동 회수

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.3-01 | 직원 4명·잔여 95건·각 30건 요청은 0건 처리되며 23개씩 가능 알림을 표시한다. | **통과** | [test_p4.P4Tests.test_four_employees_95_customers_30_each_allocates_zero_and_suggests23](../tests/test_p4.py#L67)<br>[browser_p4.P4BrowserTests.test_distribution_shortage_lost_response_reload_replay_and_today_recall](../tests/browser_p4.py#L51) |
| 18.3-02 | 관리자 두 명이 동시에 분배해도 같은 DB의 현재 할당은 하나다. | **통과** | [test_p4.P4ConcurrencyTests.test_two_admin_distributions_have_no_overlap](../tests/test_p4.py#L293) |
| 18.3-03 | 더블클릭·응답 유실·동일 key 재시도에도 분배가 한 번만 실행된다. | **통과** | [test_p4.P4ConcurrencyTests.test_same_key_distribute_once](../tests/test_p4.py#L299)<br>[browser_p4.P4BrowserTests.test_distribution_shortage_lost_response_reload_replay_and_today_recall](../tests/browser_p4.py#L51) |
| 18.3-04 | 분배 중 직원 비활성화와 경합해도 비활성 직원에게 유효한 새 배정이 남지 않는다. | **통과** | [test_p4.P4ConcurrencyTests.test_deactivation_racing_distribution_leaves_no_new_active_assignment_to_disabled_user](../tests/test_p4.py#L305) |
| 18.3-05 | 수동 회수는 오늘의 현재 할당 전체를 회수하며 진행 DB도 포함한다. 과거 할당은 제외한다. | **통과** | [test_p4.P4Tests.test_manual_recall_today_all_includes_progress_but_not_other_site_or_past](../tests/test_p4.py#L115) |
| 18.3-06 | 회수 후 상담정보·재콜 이력은 유지된다. | **통과** | [test_p4.P4Tests.test_manual_recall_today_all_includes_progress_but_not_other_site_or_past](../tests/test_p4.py#L115) |
| 18.3-07 | 동일 직원 재선택은 할당일을 초기화하지 않는다. 다른 직원 선택은 새 할당을 생성한다. | **통과** | [test_p4.P4Tests.test_assignee_noop_reassign_clear_and_old_buffer_rejection](../tests/test_p4.py#L141) |

### 18.4 저장·경합

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.4-01 | 변경이 없는 동안 자동 저장 API를 호출하지 않는다. | **통과** | [browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions](../tests/browser_employee.py#L64) |
| 18.4-02 | 정상 온라인·활성 화면에서 연속 입력해도 첫 변경 후 100초 이내 전송을 시작한다. | **통과** | [browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions](../tests/browser_employee.py#L64) |
| 18.4-03 | 같은 셀 반복 변경은 마지막 값만 전송한다. | **통과** | [browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions](../tests/browser_employee.py#L64) |
| 18.4-04 | 요청 중 새로 입력한 값이 이전 응답으로 삭제되지 않는다. | **통과** | [browser_employee.EmployeeBrowserTests.test_inflight_later_edit_and_lost_response_recovery](../tests/browser_employee.py#L95) |
| 18.4-05 | 응답 유실 후 같은 mutation 재시도는 이력·수정을 중복 생성하지 않는다. | **통과** | [test_p2.P2ConcurrencyTests.test_replayed_mutation_concurrent_once](../tests/test_p2.py#L354)<br>[browser_employee.EmployeeBrowserTests.test_inflight_later_edit_and_lost_response_recovery](../tests/browser_employee.py#L95) |
| 18.4-06 | 한 행의 충돌이 다른 정상 행의 성공을 막지 않는다. | **통과** | [test_p5.EmployeeTests.test_partial_batch_atomic_rows_and_noop_does_not_mark_activity](../tests/test_p5.py#L89) |
| 18.4-07 | 버전 충돌을 조용히 덮어쓰지 않는다. | **통과** | [test_p2.P2ApiTests.test_version_conflict_requires_fresh_mutation_and_keeps_failed_receipt](../tests/test_p2.py#L238)<br>[browser_employee.EmployeeBrowserTests.test_multitab_explicit_conflict_and_reassignment_blocks_old_queue](../tests/browser_employee.py#L107) |
| 18.4-08 | 회수·동일인 재배정 이후 이전 할당의 대기열은 저장되지 않는다. | **통과** | [test_p4.P4Tests.test_same_employee_after_recall_has_new_assignment_and_stale_buffer_rejected](../tests/test_p4.py#L157)<br>[browser_employee.EmployeeBrowserTests.test_multitab_explicit_conflict_and_reassignment_blocks_old_queue](../tests/browser_employee.py#L107) |
| 18.4-09 | 오프라인·새로고침·브라우저 재시작 후 동일 계정의 대기열을 검증·복구한다. | **통과** | [browser_employee.EmployeeBrowserTests.test_offline_encrypted_persistent_browser_restart_user_isolation](../tests/browser_employee.py#L81) |
| 18.4-10 | 다른 계정은 이전 계정의 미전송 값을 표시·전송하지 않는다. | **통과** | [browser_employee.EmployeeBrowserTests.test_offline_encrypted_persistent_browser_restart_user_isolation](../tests/browser_employee.py#L81) |
| 18.4-11 | 저장 실패 중 화면 이동·로그아웃에 명시적 선택을 요구한다. | **통과** | [browser_employee.EmployeeBrowserTests.test_navigation_logout_failure_cancel_retry_and_confirmed_discard](../tests/browser_employee.py#L120) |

### 18.5 자동 회수·진행

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.5-01 | 오늘 23시 이전 현재 할당·미진행·기본 현장 DB만 자동 회수한다. | **통과** | [test_p6.P6Tests.test_recall_boundaries_existing_values_and_completed_job_replay](../tests/test_p6.py#L124) |
| 18.5-02 | 통화결과가 비어 있어도 상담내용·주택상황 등 실제 저장이 있으면 회수하지 않는다. | **통과** | [test_p8.P8IntegrationTests.test_saved_revert_and_admin_housing_edit_survive_recall_but_noop_does_not](../tests/test_p8.py#L145) |
| 18.5-03 | 저장된 값 원복·관리자 상담 수정도 진행으로 남는다. | **통과** | [test_p8.P8IntegrationTests.test_saved_revert_and_admin_housing_edit_survive_recall_but_noop_does_not](../tests/test_p8.py#L145) |
| 18.5-04 | 저장 전 원복·무변경 저장·조회·필터는 진행으로 만들지 않는다. | **통과** | [test_p2.P2ApiTests.test_noop_normalization_never_progresses](../tests/test_p2.py#L212)<br>[browser_employee.EmployeeBrowserTests.test_reverted_unsent_values_do_not_create_activity_and_datetime_fields](../tests/browser_employee.py#L153)<br>[test_p8.P8IntegrationTests.test_saved_revert_and_admin_housing_edit_survive_recall_but_noop_does_not](../tests/test_p8.py#L145) |
| 18.5-05 | 과거 할당·다른 현장·23시 이후 새 할당은 회수하지 않는다. | **통과** | [test_p6.P6Tests.test_recall_boundaries_existing_values_and_completed_job_replay](../tests/test_p6.py#L124)<br>[test_p6.P6Tests.test_delayed_job_does_not_undo_saved_activity_or_new_assignment](../tests/test_p6.py#L144) |
| 18.5-06 | 저장과 회수 경합은 커밋 순서에 따라 일관되게 처리한다. | **통과** | [test_p6.P6Tests.test_saved_commit_wins_against_automatic_recall](../tests/test_p6.py#L239)<br>[test_p6.P6Tests.test_automatic_recall_commit_wins_against_late_save](../tests/test_p6.py#L243) |
| 18.5-07 | 기본 현장이 변경돼도 재시도는 cutoff 시점의 현장을 유지한다. | **통과** | [test_p6.P6Tests.test_failure_rollback_fixed_cutoff_site_and_retry_after_default_changes](../tests/test_p6.py#L134) |
| 18.5-08 | 서버 중단 후 누락 실행·중복 실행이 중복 회수나 새 할당 손상을 일으키지 않는다. | **통과** | [test_p6.P6Tests.test_real_process_exits_after_claim_then_restart_recovers_without_duplicate](../tests/test_p6.py#L250)<br>[test_p6.P6Tests.test_delayed_job_does_not_undo_saved_activity_or_new_assignment](../tests/test_p6.py#L144) |
| 18.5-09 | 비활성화 회수는 모든 현장·모든 날짜의 현재 미진행 할당에 적용된다. | **통과** | [test_p4.P4Tests.test_deactivation_all_sites_dates_only_unprogressed_keeps_progress_and_reactivation_does_not_restore](../tests/test_p4.py#L209) |

### 18.6 재콜·삭제·운영

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.6-01 | 오늘의 DB는 오늘 할당 OR 오늘/과거 미완료 재콜이며 한 고객은 한 행이다. | **통과** | [test_p5.EmployeeTests.test_today_kst_boundary_callback_union_priority_and_no_duplicates](../tests/test_p5.py#L116) |
| 18.6-02 | 재콜 완료 후 기한 경과 목록에서 빠지고 이력은 남는다. | **통과** | [browser_p6.P6BrowserTests.test_complete_saves_row_first_leaves_today_and_preserves_history](../tests/browser_p6.py#L55) |
| 18.6-03 | 완료 요청 재시도가 이후 생성된 새 일정을 완료시키지 않는다. | **통과** | [test_p6.P6Tests.test_complete_atomic_progress_revision_and_replay_preserves_new_schedule](../tests/test_p6.py#L59)<br>[browser_p6.P6BrowserTests.test_lost_completion_response_reload_retry_preserves_new_callback](../tests/browser_p6.py#L67) |
| 18.6-04 | 휴지통 복구는 기존 통화결과를 유지하고 미할당 상태로 복구한다. | **통과** | [test_p2.P2ApiTests.test_soft_delete_close_request_restore_preserves_business_history](../tests/test_p2.py#L270) |
| 18.6-05 | 개별 영구 삭제 후 같은 번호 재등록이 가능하고 이전 내용·이력은 조회되지 않는다. | **통과** | [test_p7.P7Tests.test_hard_customer_deletes_all_history_receipts_and_allows_new_uuid](../tests/test_p7.py#L107) |
| 18.6-06 | 현장 삭제 후 관련 조회·미전송 저장·업로드 확정이 안전하게 거부된다. | **통과** | [test_p8.P8IntegrationTests.test_deleted_site_rejects_all_old_reads_queue_writes_and_upload_commit](../tests/test_p8.py#L121) |
| 18.6-07 | 직원 그리드에서 복사·우클릭·잘라내기는 제한되고 편집·붙여넣기는 가능하다. | **통과** | [browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions](../tests/browser_employee.py#L64)<br>UI 이벤트 제한 범위. 화면 촬영/개발자 도구 등 모든 반출을 막는다는 의미는 아님. |
| 18.6-08 | 직원용 고객정보 다운로드 경로가 없다. | **통과** | [test_p5.EmployeeTests.test_page_employee_only_and_no_selection_or_export_controls](../tests/test_p5.py#L33)<br>[test_imports.ImportTests.test_staff_and_initial_login_cannot_read_validate_commit_or_results](../tests/test_imports.py#L93) |
| 18.6-09 | 백업을 별도 환경에 실제 복원하고 계정·할당·상담·재콜 정합성을 확인한다. | **통과** | [test_backup.BasicBackupRestoreTests.test_actual_dump_restore_separate_database_accounts_assignments_notes_callbacks_requests](../tests/test_backup.py#L40)<br>[test_p13.P13BackupTests.test_encrypted_populated_ai_backup_restores_every_table_and_relations](../tests/test_p13.py#L111)<br>실제 별도 DB 복원 통과. 같은 클러스터이며 외부 호스트 복원은 미검증. |

### 18.7 직원 삭제 요청·관리자 승인

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.7-01 | 오늘의 DB·나의 DB에 행별 삭제 요청 버튼이 있고 체크박스 일괄 요청은 없다. | **통과** | [browser_p7.P7BrowserTests.test_row_request_saves_only_target_and_keeps_editing_until_approval](../tests/browser_p7.py#L59)<br>[browser_p7.P7BrowserTests.test_lost_request_response_same_key_reload_and_other_tab_pending](../tests/browser_p7.py#L68) |
| 18.7-02 | 한 요청은 고객 한 건만 처리하고 제출 중 추가 클릭을 막는다. | **통과** | [browser_p7.P7BrowserTests.test_row_request_saves_only_target_and_keeps_editing_until_approval](../tests/browser_p7.py#L59) |
| 18.7-03 | 해당 행 미저장 내용의 저장에 실패하면 삭제 요청은 생성하지 않는다. | **통과** | [browser_p7.P7BrowserTests.test_cancel_confirmation_and_offline_save_do_not_submit](../tests/browser_p7.py#L64) |
| 18.7-04 | 접수 성공 후 `요청완료`가 표시되고 새로고침·다른 탭에서도 유지된다. 실패를 완료로 표시하지 않는다. | **통과** | [browser_p7.P7BrowserTests.test_lost_request_response_same_key_reload_and_other_tab_pending](../tests/browser_p7.py#L68) |
| 18.7-05 | 직원이 타인의 고객 ID나 과거 할당 ID로 요청하면 거부된다. | **통과** | [test_p7.P7Tests.test_request_authentication_structure_assignment_and_version](../tests/test_p7.py#L51) |
| 18.7-06 | 동일 고객의 중복 요청·응답 유실 재시도에 PENDING 요청이 하나만 생긴다. | **통과** | [test_p7.P7Tests.test_request_is_metadata_only_duplicate_keys_and_current_owner_pending](../tests/test_p7.py#L44)<br>[browser_p7.P7BrowserTests.test_lost_request_response_same_key_reload_and_other_tab_pending](../tests/browser_p7.py#L68) |
| 18.7-07 | 요청만으로 휴지통 이동·담당자 해제·상담정보 변경이 일어나지 않는다. | **통과** | [test_p7.P7Tests.test_request_is_metadata_only_duplicate_keys_and_current_owner_pending](../tests/test_p7.py#L44)<br>[browser_p7.P7BrowserTests.test_row_request_saves_only_target_and_keeps_editing_until_approval](../tests/browser_p7.py#L59) |
| 18.7-08 | 모든 관리자 대시보드에 현재 선택 현장과 관계없이 같은 전체 현장 요청이 표시된다. | **통과** | [test_p7.P7Tests.test_global_notifications_pagination_and_read_does_not_approve](../tests/test_p7.py#L91)<br>[browser_p7.P7BrowserTests.test_approval_global_list_lost_response_latest_notes_and_blocked_employee_queue](../tests/browser_p7.py#L75) |
| 18.7-09 | 알림 조회는 활성 대시보드에서만 기본 60초 주기로 수행하며 행마다 API를 호출하지 않는다. | **통과** | [browser_p7.P7BrowserTests.test_notifications_poll_once_per_visible_minute_and_on_return](../tests/browser_p7.py#L85) |
| 18.7-10 | 승인 전 고객 상담내용이 바뀌어도 승인 시 최신 내용에 삭제 문구를 덧붙인다. | **통과** | [test_p7.P7Tests.test_save_before_approval_uses_latest_note_and_approval_before_save_rejects](../tests/test_p7.py#L191) |
| 18.7-11 | 승인하면 휴지통으로 이동하고 `[한국 시간 승인일시] 고객요청으로 인한 삭제`가 상담기타내용에 추가된다. | **통과** | [test_p7.P7Tests.test_approval_latest_notes_long_notes_empty_and_no_staff_progress](../tests/test_p7.py#L57) |
| 18.7-12 | 빈 비고·10,000자 비고에서도 기존 내용을 훼손하지 않고 승인 문구가 기록된다. | **통과** | [test_p7.P7Tests.test_approval_latest_notes_long_notes_empty_and_no_staff_progress](../tests/test_p7.py#L57) |
| 18.7-13 | 두 관리자 동시 승인·응답 유실 재시도에도 문구·삭제·할당 종료가 한 번만 적용된다. | **통과** | [test_p7.P7Tests.test_concurrent_approvals_one_note_one_event](../tests/test_p7.py#L169)<br>[test_p7.P7Tests.test_two_admins_replay_preserves_first_approval_and_restore_is_not_redeleted](../tests/test_p7.py#L69)<br>[browser_p7.P7BrowserTests.test_approval_global_list_lost_response_latest_notes_and_blocked_employee_queue](../tests/browser_p7.py#L75) |
| 18.7-14 | 승인 후 직원 저장은 거부되고 미전송 자료를 성공으로 처리하지 않는다. | **통과** | [test_p7.P7Tests.test_approval_commits_before_waiting_save](../tests/test_p7.py#L196)<br>[browser_p7.P7BrowserTests.test_approval_global_list_lost_response_latest_notes_and_blocked_employee_queue](../tests/browser_p7.py#L75) |
| 18.7-15 | 요청 후 회수·재분배·직원 비활성화가 있어도 관리자 승인으로 처리할 수 있다. | **통과** | [test_p7.P7Tests.test_request_survives_recall_reassignment_and_inactive_requester](../tests/test_p7.py#L75)<br>[test_p7.P7Tests.test_approval_after_recall_without_current_assignment](../tests/test_p7.py#L157) |
| 18.7-16 | 일반 삭제로 이미 처리된 요청은 CLOSED로 종료되며 별도 승인 문구가 중복 생성되지 않는다. | **통과** | [test_p7.P7Tests.test_general_trash_closes_pending_without_approval_note](../tests/test_p7.py#L80) |
| 18.7-17 | 복구 후 이전 승인은 되돌리지 않고 필요한 경우 새로운 삭제 요청을 할 수 있다. | **통과** | [test_p7.P7Tests.test_two_admins_replay_preserves_first_approval_and_restore_is_not_redeleted](../tests/test_p7.py#L69) |
| 18.7-18 | 고객·현장 영구 삭제 시 관련 요청과 알림이 함께 제거된다. | **통과** | [test_p7.P7Tests.test_hard_customer_deletes_all_history_receipts_and_allows_new_uuid](../tests/test_p7.py#L107)<br>[test_p7.P7Tests.test_site_deletion_removes_import_sources_and_preserves_other_site_and_job_snapshot](../tests/test_p7.py#L160) |

### 18.8 AI 기능·사용 한도·결과 적용

| ID | 설계서 v2.0 인수 항목 | 판정 | 기존 검증 근거 / 제한 |
|---|---|---|---|
| 18.8-01 | 직원의 세 AI 기능은 버튼을 눌렀을 때만 실행되고 합산 하루 30회로 제한된다. | **통과** | [test_p9.P9Tests.test_shared_three_feature_quota_reservation_limit_and_database_constraint](../tests/test_p9.py#L98)<br>[browser_p10.P10BrowserTests.test_summary_questions_read_only_and_mobile_no_automatic_generation](../tests/browser_p10.py#L71) |
| 18.8-02 | 화면 진입·자동 저장·예약 작업·관리자 알림 폴링에서 AI 생성 호출이 발생하지 않는다. | **통과** | [test_p12.P12Tests.test_all_read_routes_and_scheduler_create_no_tasks_attempts_or_reservations](../tests/test_p12.py#L80)<br>[browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions](../tests/browser_employee.py#L64)<br>[browser_p7.P7BrowserTests.test_notifications_poll_once_per_visible_minute_and_on_return](../tests/browser_p7.py#L85) |
| 18.8-03 | 29회 성공 상태에서 여러 탭이 동시에 요청해도 성공+예약 합계가 30회를 넘지 않는다. | **통과** | [test_p9.P9Tests.test_quota29_distinct_keys_race_reserves_only_one_then_success30](../tests/test_p9.py#L301) |
| 18.8-04 | 동일 요청 키 재시도·결과 재조회·이중 클릭에 호출과 차감이 중복되지 않는다. | **통과** | [test_p9.P9Tests.test_concurrent_same_key_and_quota29_never_double_reserve](../tests/test_p9.py#L272)<br>[browser_p10.P10BrowserTests.test_lost_submission_response_reload_retries_same_key_and_charges_once](../tests/browser_p10.py#L81) |
| 18.8-05 | 확실한 실패는 예약 횟수를 반환하고, 결과 성공 후 응답 유실은 재조회해 동일 결과를 받는다. | **통과** | [test_p9.P9Tests.test_only_guaranteed_not_performed_retries_once_same_task_without_extra_quota](../tests/test_p9.py#L139)<br>[browser_p10.P10BrowserTests.test_lost_submission_response_reload_retries_same_key_and_charges_once](../tests/browser_p10.py#L81) |
| 18.8-06 | 외부 처리 여부가 불명확한 timeout을 무조건 새 유료 호출로 재실행하지 않는다. | **통과** | [test_p9.P9Tests.test_unknown_holds_then_releases_once_keeps_conservative_cost_and_rejects_late_success](../tests/test_p9.py#L148)<br>[test_p9.P9Tests.test_real_worker_process_crash_after_claim_then_restart_does_not_resend](../tests/test_p9.py#L367) |
| 18.8-07 | 자정 전 접수·자정 후 완료는 접수일 한도로 계산하며 다른 날짜의 예약을 차감하지 않는다. | **통과** | [test_p9.P9Tests.test_kst_day_and_budget_month_remain_at_submission_across_midnight](../tests/test_p9.py#L122) |
| 18.8-08 | AI 생성 자체는 진행 이력으로 남지 않고, 선택 적용 후 실제 저장한 값만 진행으로 남는다. | **통과** | [test_p10.P10Tests.test_three_post_features_schemas_usage_and_readonly_customer](../tests/test_p10.py#L37)<br>[test_p10.P10Tests.test_apply_normal_mutation_atomic_provenance_before_after_and_replay](../tests/test_p10.py#L46)<br>[test_p10.P10Tests.test_noop_ai_application_does_not_create_revision_or_progress](../tests/test_p10.py#L160) |
| 18.8-09 | AI 처리 중 회수·재분배·삭제·비활성화가 발생하면 직원에게 결과를 노출하거나 적용하지 않는다. | **통과** | [test_p12.P12Tests.test_running_result_revoked_by_recall_reassignment_trash_or_deactivation](../tests/test_p12.py#L146)<br>[browser_p10.P10BrowserTests.test_recall_between_view_and_apply_clears_private_result_and_never_saves](../tests/browser_p10.py#L147) |
| 18.8-10 | AI 요청 시점과 다른 버전의 고객에 추천을 조용히 덮어쓰지 않는다. | **통과** | [test_p10.P10Tests.test_stale_result_rejects_source_attribution_manual_explicit_save_allowed](../tests/test_p10.py#L60)<br>[browser_p10.P10BrowserTests.test_stale_result_after_other_save_read_only_no_selected_apply](../tests/browser_p10.py#L86) |
| 18.8-11 | 없는 날짜·가격·계약 여부를 임의로 생성하지 않으며 불명확한 정보는 확인 필요로 표시한다. | **통과** | [test_p10.P10Tests.test_relative_date_reanchored_to_today_or_unknown_timestamp_becomes_no_suggestion](../tests/test_p10.py#L121)<br>[test_p10.P10Tests.test_missing_price_or_contract_confirmation_is_no_suggestion](../tests/test_p10.py#L175)<br>[test_p11.P11Tests.test_only_reviewed_valid_knowledge_and_fact_quotes](../tests/test_p11.py#L119)<br>지정된 날짜·가격·계약/인용 사례와 보수적 schema 검사. 실제 모델의 자유 문장 사실성 전반은 미검증. |
| 18.8-12 | 직원이 다른 직원의 AI 결과 ID를 사용해도 조회되지 않는다. | **통과** | [test_p10.P10Tests.test_current_assignment_and_actor_checked_for_generation_result_and_apply](../tests/test_p10.py#L71) |
| 18.8-13 | 상담기록 안의 지시문을 실행하거나 외부 URL·도구·SQL을 호출하지 않는다. | **통과** | [test_p12.P12Tests.test_prompt_injection_is_data_and_tools_sql_and_network_are_not_executed](../tests/test_p12.py#L97)<br>[browser_p10.P10BrowserTests.test_result_renders_html_as_text_and_never_executes_or_links_it](../tests/browser_p10.py#L125)<br>[test_p11.P11Tests.test_source_injection_url_html_key_numeric_claim_fails_closed](../tests/test_p11.py#L101) |
| 18.8-14 | 일요일 이외 주간 브리핑 생성 요청은 서버에서 거부하고 기존 결과 읽기는 허용한다. | **통과** | [test_p11.P11Tests.test_weekly_sunday_year_boundary_cutoff_shared_slot_and_weekday_read](../tests/test_p11.py#L54) |
| 18.8-15 | 주간 범위가 한국 시간 월요일 00:00~일요일 요청 시각이며, 아직 지나지 않은 일요일 업무를 포함했다고 표시하지 않는다. | **통과** | [test_p11.P11Tests.test_weekly_sunday_year_boundary_cutoff_shared_slot_and_weekday_read](../tests/test_p11.py#L54)<br>[test_p11.P11Tests.test_future_revisions_and_system_notes_excluded](../tests/test_p11.py#L65) |
| 18.8-16 | 관리자 동시 요청에서도 같은 주 브리핑, 같은 직원의 당일 코칭, 같은 현장의 당일 가이드가 중복 생성되지 않는다. | **통과** | [test_p12.P12Tests.test_all_admin_features_share_one_slot_under_concurrent_requests](../tests/test_p12.py#L117) |
| 18.8-17 | 코칭은 실제 처리자별 30일 이력과 기존 코칭을 사용하고, 데이터가 없으면 부족함을 표시한다. | **통과** | [test_p11.P11Tests.test_inactive_and_promoted_actual_workers_in_weekly_sql_totals](../tests/test_p11.py#L77)<br>[test_p11.P11Tests.test_last_three_valid_coachings_and_older_actions_are_sources](../tests/test_p11.py#L108)<br>[test_p11.P11Tests.test_first_coaching_no_history_and_insufficient_comparison](../tests/test_p11.py#L105) |
| 18.8-18 | 상담 메모 반복 저장을 별도 통화 횟수·별도 고객 반응으로 중복 집계하지 않는다. | **통과** | [test_p11.P11Tests.test_latest_customer_actor_korean_day_and_actual_author_not_assignee](../tests/test_p11.py#L69)<br>[test_p11.P11Tests.test_reaction_multilabel_distinct_customers_and_classification_cache](../tests/test_p11.py#L92) |
| 18.8-19 | AI 생성 가이드는 검토·게시 전 직원에게 노출되지 않는다. | **통과** | [test_p11.P11Tests.test_guide_draft_hidden_review_publish_read_only_no_extra_calls](../tests/test_p11.py#L125)<br>[browser_p11.P11BrowserTests.test_guide_review_publish_employee_read_only_and_mobile](../tests/browser_p11.py#L68) |
| 18.8-20 | 고객·현장 영구 삭제 시 원문뿐 아니라 관련 AI 입력·출력·비교 코칭·가이드의 파생정보 처리도 검증한다. | **통과** | [test_p9.P9Tests.test_recursive_deletion_cycles_unpublishes_and_preserves_usage_other_site](../tests/test_p9.py#L209)<br>[test_p9.P9Tests.test_source_via_revision_and_site_knowledge_invalidates_and_removes_raw_material](../tests/test_p9.py#L346)<br>[test_p11.P11Tests.test_deletion_propagates_previous_coaching_and_excludes_future_inputs](../tests/test_p11.py#L154)<br>[test_p11.P11Tests.test_customer_hard_delete_removes_classification_and_mixed_guide_publication](../tests/test_p11.py#L159) |
| 18.8-21 | 키 없음·예산 소진·AI 공급자 장애에도 기본 DB 업무가 계속 동작한다. | **통과** | [test_p12.P12Tests.test_missing_key_invalid_config_budget_and_provider_failure_allow_real_customer_save](../tests/test_p12.py#L52)<br>합성 자료·가짜 공급자 실패 주입. 실제 공급자 장애 실험이 아님. |
| 18.8-22 | `.env.ai`는 git check-ignore에 포함되고 .env.ai.example은 제외된다. 실제 키 파일이 Git 추적 대상과 Docker 빌드 컨텍스트에 없다. | **미검증** | [test_ai_boundary.AIConfigurationTests.test_file_loaded_only_in_web_and_worker](../tests/test_ai_boundary.py#L43)<br>[test_ai_boundary.AIConfigurationTests.test_non_ai_process_drops_inherited_ai_environment](../tests/test_ai_boundary.py#L124)<br>Git/정적 제외/Compose는 passed. `docker_build_context`, `docker_image_layers`는 not_run. 실제 빌드 증거가 없어 전체 항목 미검증. |
| 18.8-23 | 실제 키가 브라우저 응답·소스맵·로그·문서·테스트 fixture에 포함되지 않는다. | **통과** | [test_p12.P12Tests.test_generated_secret_never_enters_ai_responses_usage_or_failure_logs](../tests/test_p12.py#L201)<br>[browser_p12.P12BrowserTests.test_employee_generation_and_encrypted_queue_never_receive_server_key](../tests/browser_p12.py#L104)<br>[browser_p12.P12BrowserTests.test_admin_generation_review_and_publication_never_receive_server_key](../tests/browser_p12.py#L129)<br>[test_ai_boundary.AIConfigurationTests.test_configured_application_and_django_log_handlers_redact](../tests/test_ai_boundary.py#L113)<br>임시 생성한 합성 키의 전체 경로 검사. 실제 키 파일은 읽거나 비교하지 않았으며 운영 키 값 자체의 유출 감사는 수행하지 않음. |

## 실패·변경분 재검증 판단과 로컬 시연

| 대상 | 현재 확인 | 이번 조치 |
|---|---|---|
| P13 이후 구현/매핑 변경 | 227파일 공통 SHA가 최종 검사와 동일. 문서 변경 및 `.local` 정리 기록은 앱 소스 변경에 해당하지 않음 | 재검증 대상 변경 0건. 통과 테스트 재실행 0개 |
| 이전 pg_dump 도구 선택 실패 | 현재 `apps/operations/backups.py:tool`이 프로젝트 PostgreSQL17 경로를 PATH보다 우선. 최종 백업/복원 테스트 passed와 실제 복원 근거 존재 | 해결된 과거 실패로 분류. 재실행 안 함 |
| 이전 20세션 조회 성능 실패 | 현재 할당 ID 사전 선택과 `assignment_owner_current_idx` migration이 현재 코드에 존재. 최종 동시 HTTP/권한/성능 검수 통과 | 해결된 과거 실패로 분류. 재실행 안 함 |
| 초기 fixture/경고 분류·복원 시간 기록 | 최종 fixture와 monotonic/perf_counter 시간 기록 반영, 최종 417개 모두 통과. HSTS W005/W021은 subdomain/preload를 켜지 않은 선택으로 별도 기록 | 현재 실패로 재집계하지 않음 |
| Docker 미실행 | CLI/엔진 없음. 이전 집계 명령의 exit1은 없는 런타임 근거 때문에 발생 | 실패 1건으로 오기하지 않고 미검증 1건 유지. 설치/구매/배포 안 함 |
| 로컬 시연 차단 결함 | 현 코드·기존 동일 버전 검증 범위에서 신규 결함 발견 없음 | 앱 코드 수정 없음. 결함 없이 기존 비밀번호·할당·자료를 바꾸지 않음 |

**시연 가능 범위:** 가짜 자료의 로그인/최초 비밀번호 변경·현장/업로드·분배/회수·직원 저장/재콜·삭제 요청/승인·휴지통 등 기본 업무. 현재 DB/웹은 실행 상태가 아니며, [README 1절](../README.md)의 PostgreSQL 시작→migration→collectstatic→Gunicorn과 별도 scheduler 실행 절차를 사용한다. 이미 변경한 예제 계정의 비밀번호를 초기값으로 간주하거나 재설정하지 않는다. 앞선 개발 자료 보존 점검은 가짜 사용자3명·고객65건·임시 DB0이며 이번에는 DB 내용에 재접속하지 않았다.

**AI 시연 제한:** 직원3종·관리자3종의 신규 생성은 일반 로컬/운영 실행에서 실제 공급자 미연결로 거부된다. `services.validate_config()`와 `worker.claim()`이 차단하며, fake는 `TESTING`·`AI_FOUNDATION_TEST_MODE`·폐기 가능한 `test_tm_*` DB를 모두 만족해야 한다. AI 기능 통과는 이 테스트 전용 환경의 상태/예약/결과/선택 적용/게시 검증이다. 일반 앱에서 AI 6종을 실제 생성할 수 있는 완성본으로 설명해서는 안 된다. 이 차단을 제거하거나 개발 DB에 fake 결과를 주입하지 않았다. 이번 요청의 유료 호출 제외 범위에서 공급자 연결을 새로 구현하지 않는다.

## 운영 환경에서 별도로 확인할 항목

다음은 위 92문항과 중복되는 부분이 있어도 별도의 운영 인수 조건으로 남긴다. 로컬 통과를 근거로 운영 완료로 올리지 않는다.

| 항목 | 상태 | 완료에 필요한 근거 |
|---|---|---|
| Docker 실제 경계 및 기동 | 미검증 · 18.8-22에 포함 | 엔진이 있는 승인된 검수 환경에서 실제 context·이미지 전체 레이어/history의 비밀값 제외, 고정 digest, Compose 기동·health·정적 파일·migration 검증 |
| 운영 백업 목적지/장애 영역 | 미검증 | 별도 호스트/계정의 실제 전달·checksum·SSH host key·최소 권한, 서로 다른 장애 영역 보관, 해당 보관본의 격리 복원·정합성 |
| 백업 운용/복구 체계 | 미검증 | Linux timer 활성화·03시 KST/catch-up·실패 감지·보관7일·키 별도 보관·용량/모니터링·정기 복구 훈련. 하루 백업의 손실 가능성은 대략24시간+지연으로 운영 승인 필요 |
| 공개 HTTPS/네트워크 | 미검증 | 실제 도메인의 공개 CA·리다이렉트·Secure cookie/CSRF·정적 파일, 프록시 밖 backend/DB 접근 차단. HSTS subdomain/preload는 도메인 범위 검토 후 결정 |
| 실제 기기/브라우저 | 미검증 | 실제 Edge/Chrome 및 필요한 iOS/Android 기기의 저장·복구·입력·가로 넘침·Web Crypto/IndexedDB 지원 확인 |
| 운영20명 SLA/장애 | 미검증 | 확정된 서버 자원·실제 네트워크·예상 자료량에서 지속/혼합 부하·DB 지연·중단/재시작·자동 회수 지연·장애 복구 측정 |
| 실제 AI 공급자 | 미구현·미검증 | 별도 승인 후 공급자 어댑터·모델/공식 단가/tokenizer/추론 과금·타임아웃/청구 정합성·한국어 품질/근거·개인정보 전송 및 보관 조건 검증. 이번 단계에서는 호출하지 않음 |
| 운영 비밀값·DB 권한·배포 산출물 | 미검증 | 현재 미커밋/미추적 구현까지 포함하는 변경 불가 릴리스 스냅샷, 실제 이미지/설정 식별, 전용 DB/백업/복구 계정, checkout 밖0600 파일·회전, 원시 검증 자료 보존. 실제 운영 키 값 유출 감사는 별도 |
| 운영 복원 후 정리/롤백 | 절차만 준비 | 복원된 세션 폐기, 백업 이후 영구 삭제·권한 변경 재반영, worker/scheduler 격리, 이전 이미지·migration 호환성·복귀 절차를 실제 운영 전환 전에 검증 |

절차 근거: [운영·백업·복원 절차](OPERATIONS.md). 운영 도메인·서버·외부 보관소/자격증명은 이번 검토에서 지정하거나 생성하지 않았다.

## 이번 산출물과 보존

이번 변경은 이 보고서와 `.local/release-readiness-audit.json`의 대조 근거다. 앱/테스트/마이그레이션·기존 P13 결과·계정/비밀번호·고객 자료·실제 비밀파일은 변경하지 않았다. 현재 소스가 변하면 이 보고서의 SHA와 비교한 뒤 영향받은 항목을 미검증으로 돌리고 해당 검사만 재실행해야 한다. Docker/운영 미검증 항목은 필요한 환경 근거가 생기기 전까지 통과로 변경하지 않는다.
