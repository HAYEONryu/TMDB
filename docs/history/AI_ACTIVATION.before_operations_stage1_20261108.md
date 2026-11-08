> **최신 최종 통합 검수(2026-11-08):** [FINAL_VERIFICATION.md](FINAL_VERIFICATION.md) 및 [92문항 현재 결과](FINAL_ACCEPTANCE.md)를 우선합니다. Gemini 3.5 Flash-Lite 무료 전용·유료 승인 $0이며 실제 운영은 보류입니다. 아래는 해당 작성 시점의 기록입니다.

# AI 키 보존·경계 점검·활성화

> **후속 Lite 전용 변경:** [최신 환경 점검](LITE_ENV.md)을 따른다. Gemini3.8 지원을 제거하고 `.env.ai` 중복변수4개를 삭제했다. 아래 복수모델/변수 설명은 이전 단계의 기록이다. 키 보존·AI 비활성 유지, 이번 DB 없는22개 검사 통과.

> **최신 연결 준비 검수:** [GEMINI_READINESS.md](GEMINI_READINESS.md)를 따른다. 키는 `.env.ai` 파일에서만 읽고 예시 값은 모두 빈 값이다. 사용자 최종 선택으로 로컬Lite 모델을 보존했고 무료 한도 확인false·AI 비활성이다. 이전 단계의 한도 확인/활성화 상태를 현재 확인으로 간주하지 않는다.

> **현재 정책: Gemini 3.5 Flash Lite 무료 티어·직원40회·서버 공용500회·RPM15/TPM250,000·관리자 결과 공유.** [최신 무료 사용 정책·예약·대기·검증](FREE_AI_USAGE.md)이 이전 유료 모델 설정 안내보다 우선한다. AI는 여전히 비활성이다.

2026-11-07, Asia/Seoul. **현재 모델은 Gemini 3.5 Flash Lite, 직원·관리자 모두 low다. 실제 유료 호출0회이며 AI는 비활성이다.** [현재 무료 연결·한도·검증](FREE_AI_USAGE.md)을 먼저 확인한다. 아래 과거 OpenAI 보안 감사 수치는 당시 검사 범위이며, 이번 변경 검증과 구분한다.

## 입력할 파일과 현재 상태

프로젝트 루트의 **`/Users/hayeon/Documents/TMDB/.env.ai`**에 키를 입력한다. 이 파일의 기존 **OpenAI 키 값과 기존 Gemini 키 값은 보존**하고 모델·단가·추론 설정만 변경했다. 권한0600, `AI_ENABLED=false`다. 기존 `AI_API_KEY`는 Google에 전송하지 않는다. 키 값이나 키 해시는 출력·문서·검사 결과에 기록하지 않았다. 파일이 없는 경우에만 빈 키·비활성 `.env.ai.example`을0600으로 생성하는 절차로 점검했다.

현재 provider `gemini`, model `gemini-3.5-flash-lite`, `AI_STAFF_REASONING=low`, `AI_USAGE_TIER=free`다. 사용자가 확인한 Free Tier 프로젝트·RPM15/TPM250000/RPD500과 확인true를 로컬 파일에 설정했다. 입력/출력 단가는0, 이전 월 예산USD5 값은 보존했다. 무료 모드에서는 이 월 예산을 소모하거나 초과 시 유료로 전환하지 않는다. **Gemini 키는 `AI_GEMINI_API_KEY`에 입력**하며 기존 OpenAI 키를 재사용하지 않는다. 원격 계정·키·사용량은 조회하지 않았다. 미확인 티어·키 누락·한도0·무료 모드의 유료 단가는 생성 차단 사유다.

web·ai_worker 역할만 키 파일을 읽는다. scheduler·management·test는 AI 환경값을 제거하고 파일을 읽지 않는다. Gemini 키는 서버의 `x-goog-api-key` 헤더로만 전송하고 URL·클라이언트 설정에 넣지 않는다. 두 키를 모두 로그 마스킹 대상으로 등록한다.

## 점검 결과

| 영역 | 결과와 한계 |
|---|---|
| Git | `.env.ai` 제외·미추적. 마지막 감사의 추적 파일276개·인덱스·조회 가능한 커밋 이력 blob335개에서 현재 키 일치0건 |
| Docker | `.dockerignore`의 실제 환경 파일 제외·빈 예시 예외, 키 ARG/ENV 없는 Dockerfile, web/ai_worker만 AI 파일을 런타임에 받는 Compose 확인. **CLI·엔진 부재로 실제 build context·이미지·레이어/history는 미검증** |
| 브라우저 | Chromium 직원/관리자 검사2개 통과. 합성 키가 DOM·요청/응답 본문/헤더·콘솔·local/sessionStorage·IndexedDB에 없음. 현재 키도 정적/템플릿/수집 자산101개에서 일치0건 |
| 환경 파일 URL | 데모의 `/.env.ai`, `/.env`, `/static/.env.ai` 모두404. 로그인·healthz200 |
| 로그 | 프로젝트 로컬 로그142개에서 현재 키 일치0건. 기존 로그 마스킹·예외/공급자 실패 합성 키 검사의 통과 근거 재사용 |
| 운영 fake 금지 | TESTING=false에서400·503·timeout은 실패/UNKNOWN으로 남고 fake 호출0건·유효 결과0·성공 횟수0. 테스트 flag를 켜도 운영 fake 어댑터 거절 |

Docker 정적 감사의 exit1은 실제 이미지/레이어 미검증을 뜻한다. 정적 제외 규칙 확인을 실제 Docker 검증 완료로 표시하지 않는다.

## 한도·주기·비용

| 항목 | 서버 규칙 |
|---|---|
| 직원 | 상담 정리·요약·다음 질문 **KST 하루 합산40회**, 성공+예약≤40. 직원 `gemini-3.5-flash-lite/low` |
| 주간 브리핑 | 일요일 접수만 가능, 월요일 시작 주간 단위1회. 관리자들이 작업/성공본 공유 |
| 직원 코칭 | 대상 직원별 KST 하루1회, 관리자 간 공유 |
| 팀 상담 가이드 | 현장별 KST 하루1회, 관리자 간 공유 |
| 관리자 | 기존 ADMIN 역할, `gemini-3.5-flash-lite/low`, 확인한 무료 프로젝트 고정 |
| 무료 공용 한도 우선 | 서버 전체 **전송+예약≤500회/태평양 날짜**. 개인 잔여가 있어도 공용 소진 시 중단. 관리자도 포함. 이전 월USD5 값은 보존하지만 무료 요청을 유료로 전환하지 않음 |
| 예약 | 신규 공용1회+직원 개인1회를 선예약. worker가 분당15회·입력250,000토큰을 예약하고 대기 후 전송. 무료 비용은0 |
| 중복 | 같은 key/body는 같은 작업, 같은 key의 다른 body는 충돌. 캐시/관리자 같은 주기 결과 반환은 새 비용·횟수 예약 없음 |
| 동시성 | 계정당 미결1개, 전체 RUNNING/UNKNOWN 합산2개. 기존 동시성·트랜잭션 검증 근거 재사용 |
| 확정 실패 | 미사용 예약 해제, 알려진 과금 실패는 usage 정산. 직원 성공 횟수에는 포함하지 않고 관리자 실패 slot 해제 |
| 전송 유실 | timeout·5xx 등은 UNKNOWN·자동 재호출 없음. 시작 후10분 뒤 예약 비용으로 보수적 정산·횟수 예약 해제. 늦은 응답으로 성공/적용하지 않음 |

**운영 공급자 실패를 가짜 성공으로 대체하지 않는다.** 실제 작업 자동 재시도·다른 유료 모델 전환도 없다. 조회/scheduler는 새 생성을 시작하지 않는다. 선택·저장 전 AI가 고객정보를 바꾸지 않는다.

## 분리형 데모에서 향후 활성화

**지금은 활성화하지 않았다.** 현재 데모 웹 localhost:8010·PostgreSQL55433/`tm_demo`는 모두 중지 상태이며 그대로 보존했다. 별도 검사용 PostgreSQL55434만 사용했다. 다음 `site.py start --no-ai`가 신규 마이그레이션을 적용한다. 기존 개발 DB55432/`tm_dev`도 중지·보존한다. 기본 데모 설정은 루트 AI 파일을 읽지 않으므로 파일의 enable 값만 바꾸면 자동 활성화되지 않는다.

실제 무료 생성을 시작할 때, 해당 Google 프로젝트가 결제 미연결 Free Tier임을 재확인한 뒤 다음 순서로 실행한다.

1. 편집기로 루트 `.env.ai`를 열어 **`AI_GEMINI_API_KEY`에 Google Gemini API 키를 입력**한다. 기존 OpenAI 키는 보존한다. 모델·단가·예산은 위 값으로 유지하고 **`AI_ENABLED=true`**로 바꾼다. 키를 터미널 인수나 채팅에 넣지 않고0600을 유지한다.
2. 기존 worker가 있다면 해당 터미널에서 Ctrl+C로 종료한 뒤, 프로젝트 루트에서 **데모만** 재시작한다.

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py restart --ai
```

3. 별도 터미널에서 같은 데모 설정/DB를 쓰는 worker를 실행한다. **이 단계부터 예약 작업을 실제 Google API로 전송한다. 확인한 Free Tier 프로젝트를 사용해야 한다.**

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py worker
```

4. http://localhost:8010 에서 새로고침/로그인하고 생성 버튼을 사용한다. 설정을 바꿨다면 worker 종료→`restart --ai`→worker 재실행 순서를 따른다. 모델·권한·옵션 오류는 실패 상태와 설정/계정을 직접 확인한다.

`--ai`는 키를 복사·덮어쓰지 않고 로컬 opt-in 표시 파일만 만든다. `demo_ai_settings.py`가 기존 데모 DB를 유지하면서 web/worker 역할에만 루트 `.env.ai`를 읽는다. 임시 합성 키로 역할 차단·비활성 유지·현재 비활성 데모의 worker 시작 거부를 검사했다. 실제 활성화·원격 티어/사용량·독립 프로세스 실전 생성은 미검증이다. `.local/demo`의 보조 도구는 Git 제외 로컬 파일이므로 다른 컴퓨터에는 별도 준비가 필요하다.

## 비활성화·종료·재실행

worker 터미널에서 **Ctrl+C**로 종료한다. 루트 `.env.ai`를 `AI_ENABLED=false`로 바꾸되 키는 보존한다. 아래 명령으로 루트 AI 파일을 읽지 않는 기본 데모로 재시작한다.

```sh
.venv/bin/python .local/demo/site.py restart --no-ai
.venv/bin/python .local/demo/site.py status
```

모두 종료할 때는 worker 종료 후 `site.py stop`, AI가 꺼진 상태로 켤 때는 `site.py start --no-ai`를 사용한다. stop은 자료와 AI 모드 표시 파일을 보존하므로 안전한 재실행에는 `--no-ai`를 명시한다. 이미 전송된 요청의 공용 사용량은 비활성화로 돌려주지 않는다.

## 이전 OpenAI 단계의 근거

새 운영 정책5개+Chromium 비밀값2개 **7/7 통과,7.179초,실패/오류/skip0**. 별도 `test_tm_ai_operating` DB에서 가짜 자료·합성 키·가짜 공급자 응답만 사용하고 DB를 제거했다. 현재 소스 SHA는 `686bd4890ee943862ef58ca810fa401d8a04bf3839d97ca6393d08c6a0980500`다. 검사 시작 HEAD는 `354ef598a0edcc60415ce8cc3922e9550a79bb0d`, 마지막 확인 HEAD는 `67106acfae53e7580f7455e98607b5694c211015`로 바뀌었으나 검사 후 구현/검수 소스 SHA는 같다. 기존142개 검사 때의 AI 구현·설정·기존 테스트 파일의 개별 해시도 불변이고 새 테스트 파일만 추가했다.

재현: `.venv/bin/python .local/demo/verify_ai_operating.py`. 원시 로그 `.local/demo/ai-operating-tests.log`, 결과 `.local/ai-operating-tests.json`, 비밀값 감사 `.local/ai-env-audit.json`, 파일 보존 `.local/ai-env-preservation.json`, Docker 정적 감사 `.local/ai-env-static-boundary.json`, 자료 보존/테스트 DB 제거 `.local/ai-env-runtime.json`이다. 실제 계정 접근·유료 청구·공급자 품질·Docker 이미지·운영 배포는 미검증이다.
