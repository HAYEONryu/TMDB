> **최신 최종 통합 검수(2026-11-08):** [FINAL_VERIFICATION.md](FINAL_VERIFICATION.md) 및 [92문항 현재 결과](FINAL_ACCEPTANCE.md)를 우선합니다. Gemini 3.5 Flash-Lite 무료 전용·유료 승인 $0이며 실제 운영은 보류입니다. 아래는 해당 작성 시점의 기록입니다.

# Lite 전용 환경 설정 정리

2026-11-07. 최신 사용자 지정에 따라 Gemini 허용 모델은 **`gemini-3.5-flash-lite` 하나**다. `gemini-3.8-flash`는 사전 검증과 HTTP 경로 생성에서 거절한다. 이전3.8 준비/복수모델 지원 안내보다 이 문서가 우선한다. 실제 AI 호출은 하지 않았다.

## .env.ai 점검

Gemini 키가 입력된 것을 확인했으나 키 값은 출력하지 않았고 편집 전후 같은 값을 보존했다. 파일0600·Git미추적이다. 제공자gemini, 모델Lite, 무료모드, RPM15/TPM250000/RPD500, 프로젝트ID 형식을 확인했다. 숫자는 이전에 사용자가 제공한 값이며 공급자에 원격 조회한 값은 아니다.

현재 **AI_ENABLED=false, AI_FREE_TIER_CONFIRMED=false**를 유지한다. 파일의 값/형식은 정상적으로 읽히지만 실제 생성은 비활성이다. 실제 모델 접근/키 유효성을 API로 확인하지 않았다. 한도/Free Tier를 AI Studio에서 확인하고 실제 사용을 원할 때만 직접 활성화한다.

## 삭제한 중복 변수

| 제거 변수 | 처리 |
|---|---|
| AI_STAFF_REASONING | Gemini 기본low로 읽음. 관리자도low 유지 |
| AI_INPUT_USD_PER_MILLION | 무료모드에서0으로 산정 |
| AI_OUTPUT_USD_PER_MILLION | 무료모드에서0으로 산정 |
| AI_FREE_LIMITS_MODEL | AI_MODEL과 같은 값으로 산정. 지원모델이Lite 하나여서 중복 지정 불필요 |

이전 OpenAI 키 변수AI_API_KEY는 실제 파일에 이미 없었다. 예시 파일에서도 제거했다. `.env.ai.example`은 Lite 무료 구성의 필요한 항목13개만 남기고 값은 모두 빈 값이다. 실제 파일을 예시로 덮어쓰지 않는다.

AI_ENABLED·AI_PROVIDER·AI_MODEL·AI_GEMINI_API_KEY·AI_USAGE_TIER, 무료확인/프로젝트/3개 한도, 월 예산과 테스트 누적 예산/범위는 실제 서버 로직에 쓰이므로 유지했다. 이전 요청의 월/테스트 예산 분리 안전장치를 임의로 없애지 않았다. 나중에 요금제를paid로 바꾸고 단가를 생략하면 단가를 알 수 없으므로 호출을 차단한다. 무료값0을 유료 요금제로 자동 적용하지 않는다.

## 검증과 한계

실제 파일의 모델/한도·안전한 기본값·키 보존·0600/미추적을 외부 호출 없이 확인했다. 파일 전용 키·예시 빈값·모델 제한·고정HTTP경로/오류·로그 마스킹 등 **DB 없는 단위검사22/22통과(0.279초)**. 문법/공백 점검 통과. 검사 소스SHA `f7c53097903391c43ca945d8700678ceb555ebcbfe3c42848c5c19ea02a97e5f`. 근거 `.local/lite-only-env-check.json`과 이번 도구 실행 결과다.

별도 테스트PostgreSQL 실행은 자동 승인 검토의 사용량 한도로 거절되어 실행되지 않았다. 위험 판정은 아니다. 따라서 이번 변경의 DB/브라우저 검사는 미실행이며 이전232개/41개 결과를 이번 버전 전체 통과로 표기하지 않는다. 기존 개발/데모DB·서비스 상태는 변경하지 않았다.
