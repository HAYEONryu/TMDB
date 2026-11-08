# Gemini 3.8 Flash 연결

> **최신 연결 준비 검수:** [GEMINI_READINESS.md](GEMINI_READINESS.md)를 따른다. 키는 `.env.ai` 파일에서만 읽고 예시 값은 모두 빈 값이다. 사용자 최종 선택으로 로컬Lite 모델을 보존했고 무료 한도 확인false·AI 비활성이다. 이전 단계의 한도 확인/활성화 상태를 현재 확인으로 간주하지 않는다.

> **후속 변경:** 현재 모델은 **Gemini 3.5 Flash Lite**이며 [무료 티어 공용 한도 정책](FREE_AI_USAGE.md)을 사용한다. 직원40회·서버 공용500회·RPM15/TPM250,000·비용0이며 관리자 결과를 공유한다. 아래 Standard 유료 단가·30회·비용 예약은 이전 유료 연결 단계의 기록이다. 실제 활성화에는 최신 무료 안내를 따른다.

2026-11-07, Asia/Seoul. 현재 기본 AI 공급자는 `gemini`, 모델은 **`gemini-3.8-flash`**다. 사용자가 직원도 low로 변경하도록 선택해 **직원·관리자 모두 low**를 사용한다. 실제 유료 API 호출은0회이며 현재 데모는 AI 비활성이다.

## 공식 지원과 가격

- [모델 공식 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash): 정식 모델, 구조화 출력·추론 지원. low/medium/high를 지원하며 none/minimal은 사용하지 않는다.
- [Standard 공식 가격](https://ai.google.dev/gemini-api/docs/pricing): 2026-12-31까지100만 토큰당 입력USD0.75, 출력USD3.75, 캐시 읽기USD0.075. 출력 가격에 추론 토큰을 포함한다. 2027-01-01부터 입력1.50/출력7.50/캐시0.15다. 세금·외부 프로그램 사용량은 별도다.
- [GenerateContent REST](https://ai.google.dev/api/generate-content): 서버에서 고정 Google HTTPS 호스트의 `v1beta/models/gemini-3.8-flash:generateContent`를 한 번 호출한다. 문서상 기존 GenerateContent API 경로이며 현재 신규 Interactions API로의 마이그레이션은 이번 범위에 포함하지 않는다.
- [추론·토큰 한도](https://ai.google.dev/gemini-api/docs/generate-content/thinking): `thinkingLevel=LOW`, 추론 요약 비활성. `maxOutputTokens`는 출력과 추론을 합한 상한이다. 도구·검색·Grounding·파일·미디어·명시적 캐시 생성은 요청하지 않는다. 기본 Standard tier를 사용한다.

가격은 서버 정책과 설정값이 일치해야 한다. 할인 종료 후 구 단가로는 새 요청을 차단하며 단가를 자동 변경하지 않는다. 2027-01-01(UTC) 이후에는 운영자가 입력/출력 단가를1.50/7.50으로 변경하고 web/worker를 재시작해야 한다. 공급자 청구서와 실전 모델 접근 권한은 아직 확인하지 않았다.

## 키와 활성화

입력 파일은 프로젝트 루트의 **`.env.ai`**, Gemini 키 항목은 **`AI_GEMINI_API_KEY`**다. 기존 `AI_API_KEY`의 OpenAI 키 값을 보존했고 Google에 보내지 않는다. 새 Gemini 키 항목이 없을 때만 빈 항목을 추가했다. 기존 Gemini 키가 있다면 그 값도 보존한다. 파일은0600이며 키를 출력하지 않는다.

```dotenv
AI_ENABLED=false
AI_PROVIDER=gemini
AI_MODEL=gemini-3.8-flash
AI_STAFF_REASONING=low
AI_MONTHLY_BUDGET_USD=5
AI_GEMINI_API_KEY=
AI_INPUT_USD_PER_MILLION=0.75
AI_OUTPUT_USD_PER_MILLION=3.75
```

서버의 web/ai_worker 역할만 키를 읽고 `x-goog-api-key` 헤더로 전송한다. URL·브라우저에 넣지 않는다. 실제 환경 파일은 Git·Docker 빌드에서 제외하며 web/worker에만 런타임 파일을 제공한다. 로그 마스킹은 보존한 OpenAI 키와 Gemini 키 모두에 적용한다. 빈 키·지원하지 않는 모델/추론/단가는 전송 전에 차단한다. Docker 엔진에서 실제 이미지/레이어 검사는 이번에도 미검증이다.

향후 유료 사용을 시작할 때만 `.env.ai`의 Gemini 키를 입력하고 `AI_ENABLED=true`로 변경한 뒤 다음 순서를 따른다. **이번 작업에서는 실행하지 않았다.**

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py restart --ai
# 별도 터미널. 이때부터 예약 작업이 실제 유료 전송될 수 있다.
.venv/bin/python .local/demo/site.py worker
```

끄려면 worker 터미널에서 Ctrl+C, `.env.ai`에서 `AI_ENABLED=false`, `site.py restart --no-ai` 순서다. 자세한 시작·종료·재실행은 [활성화 안내](AI_ACTIVATION.md)를 따른다. 현재 사이트는 http://localhost:8010 에서 AI 비활성으로 실행한다.

## 제한과 실패 처리

직원 상담 정리·요약·다음 질문은 KST 하루 합산30회(성공+예약)다. 주간 브리핑은 일요일 접수·월요일 시작 주간1회, 코칭은 직원별 하루1회, 팀 가이드는 현장별 하루1회이며 관리자 간 결과를 공유한다. 기존 규칙을 유지했다.

월 목표USD5는 조직 전체 정산비용+미결예약+새예약을 함께 검사한다. 입력 상한은 직원16000/관리자32000, 출력+추론 합산 상한은2048/4096토큰이다. 2026 단가로 요청당 직원 최대USD0.019680, 관리자 최대USD0.039360을 예약한 뒤 실제 usage로 정산한다. 실제 요청이 이 금액을 항상 사용한다는 의미는 아니다. 출력과 추론을 한 번씩만 합산하고 암묵적 캐시 읽기는 요청 시점 입력 단가의1/10로 별도 정산한다. 명시적 캐시 저장·보관 비용을 발생시키는 요청은 없다.

같은 요청 키·같은 내용은 같은 작업을 반환하고 비용·횟수를 이중 예약하지 않는다. 공급자의400/401/403/404/413/422는 확정 실패, timeout/5xx/비정상 usage는 UNKNOWN으로 두고 자동 재전송하지 않는다. UNKNOWN은 기존10분 후 최대 예약비용으로 보수적 정산한다. 알려진 usage가 있는 거절·잘린 응답·잘못된 모델/JSON/근거는 비용을 기록하고 실패한다. 성공으로 처리하거나 상담값을 자동 적용하지 않는다.

다른 유료 모델·OpenAI로 자동 전환하지 않고, 운영 실패를 가짜 성공으로 대체하지 않는다. 이전 OpenAI 구현은 명시적인 OpenAI 설정의 호환 코드로 보존했으며 현재 Gemini 요청의 fallback으로 사용하지 않는다.

## 검증과 한계

별도 PostgreSQL 테스트 DB·가짜 자료·합성 키·가짜 Gemini 응답을 사용했다. 네트워크 연결을 차단한 채 네이티브 JSON 요청→worker→검증→비용/횟수 정산과 직원·관리자 Chromium 화면까지 확인했다.

| 실행 | 결과 | 소스 SHA |
|---|---|---|
| 신규 Gemini14개+기존 연결·한도·키 경계46개 | 60/60통과,6.407초 | `e89f6fa80d68a1c557491a0c332cf208a7ddda05b3738371cd32f2dc7298983c` |
| 공유 AI 큐·직원·관리자·보안 회귀101개+Gemini 브라우저2개 | 102통과/1오류,52.861초 | `fbda9313ffbe6fd469ea0aa4bbae9304ce7f1d9d2ac0b1bfe6a738ed5c64a022` |
| 실패했던 직원 브라우저1개만 재검사 | 1/1통과,4.108초 | `fddfa3a1290726a446b1381a5ce76f435e95d273cd50884bdfa261530557f858` |

최종적으로 서로 다른 **163개 항목의 통과 근거**를 확보했다. 브라우저 검사의 버튼 이름을 잘못 지정한 오류를 실제 ‘상담 요약’으로 수정했고 통과한 검사는 반복하지 않았다. 첫60개 이후 앱 구현은 변경하지 않고 브라우저 검사를 추가·수정했다. 각 실행 중 소스는 불변이며 전체163개를 최종SHA에서 한 번에 다시 실행했다는 의미는 아니다.

근거는 `.local/gemini-verification.json`, `.local/gemini-regression-verification.json`, `.local/gemini-focused-verification.json`과 각각 연결된 `.local/demo/gemini*-tests.log`다. 폐기용 DB3개는 검사 후 제거했다. 브라우저에서 합성 키가 DOM·요청/응답·콘솔·local/sessionStorage·IndexedDB에 없는지 확인했다. 실제 공급자 인증·유료 청구·출력 품질·운영 네트워크·Docker 이미지·운영 복원·전체92개 인수 항목의 신규 재검증은 포함하지 않았다.
