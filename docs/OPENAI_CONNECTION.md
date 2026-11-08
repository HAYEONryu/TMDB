# OpenAI 서버 연결과 가짜 응답 검증

> 이전 OpenAI 연결 구현·검증 기록이다. 현재 기본 모델은 **Gemini 3.8 Flash**로 변경했다. [현재 연결 안내](GEMINI_CONNECTION.md)와 [활성화 절차](AI_ACTIVATION.md)를 따른다. OpenAI는 명시적 설정 시에만 사용하는 기존 호환 코드로 남아 있으며 자동 대체 경로가 아니다.

> 후속 키 보존·운영 한도 점검과 **현재 데모의 활성화/worker/비활성화 명령**은 [AI 활성화 안내](AI_ACTIVATION.md)를 따른다. 기존 키·전체 바이트를 보존했고 현재 AI_ENABLED=false·월USD5다. 서버 구현은142개 검사 때와 같으며 추가 운영/브라우저 검사7개를 통과했다. 새 테스트 추가 후 소스 SHA는 후속 안내의 값이다. 아래 실제 파일 미열람 기록은 이전 연결 구현 단계의 기록이다.

확인일: **2026-11-07, Asia/Seoul**. 이번 작업은 코드 구현·공식 문서 조회·가짜 응답 검증이다. 실제 OpenAI 생성/모델 목록 API 요청, 실제 키 열람·수정, 유료 호출은 하지 않았다. 기존 개발 DB는 실행하거나 migration하지 않았다.

## 확인 결과

변경 전에는 `FoundationFakeAdapter`와 테스트 DB 전용 worker만 있었고, 실제 공급자 설정은 예약 단계에서 항상 거절했다. 현재는 `openai_adapter.py`의 HTTPS `POST https://api.openai.com/v1/responses`와 실제 작업의 worker 선택 경로를 구현했다. SDK 추가 없이 Python 표준 HTTPS 클라이언트의 인증서 검증을 사용한다. API 키는 서버 Authorization 헤더에만 넣는다.

다른 모델·다른 공급자·다른 단가를 지정하면 예약을 거절한다. 클라이언트는 모델/추론 수준/도구/단가를 지정할 수 없다. 서버가 다음 정책을 결정하고 요청 행에 모델·추론 수준·단가·상한·정책 버전을 고정한다.

| 대상 | 모델 | 추론 effort | 실행/서비스 | 총 출력 상한 |
|---|---|---|---|---|
| 직원 상담 정리·요약·다음 질문 | `gpt-6-luna` | `none` | `reasoning.mode=standard`, `service_tier=default` | 800토큰 |
| 팀장/관리자 주간 브리핑·코칭·가이드 | `gpt-6-luna` | `low` | 동일 | 2,000토큰 |

이 앱의 팀장 권한은 기존 `ADMIN` 역할이다. 출력 상한에는 추론 토큰이 포함된다. `low`에서도 부족하면 `incomplete`를 실패로 처리하고 알려진 비용은 기록한다. 출력 상한·추론 수준을 자동으로 올리지 않는다. 실제 한국어 생성 품질과 이 상한의 충분함은 미검증이다.

## 공식 지원과 Standard 단가

[공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-luna)에 정확한 모델 ID `gpt-6-luna`가 등재되어 있다. Responses API·Chat Completions, 텍스트 입출력·이미지 입력, 스트리밍·함수 호출·Structured Outputs를 지원한다. 오디오·비디오 입력/출력과 fine-tuning은 지원하지 않는다. 컨텍스트는 1,050,000, 최대 출력은 128,000토큰이다. 문서에 노출되는 공통 endpoint 목록 전체를 이 모델의 지원 목록으로 해석하지 않았다.

추론 effort는 `none`, `low`, `medium`(기본값), `high`, `xhigh`, `max`를 지원한다. 따라서 요청된 직원 `none`과 관리자 `low`를 명시한다. `standard`와 `pro` reasoning mode는 별도 옵션이며, 본 구현은 `standard`만 사용한다. [추론 옵션·출력 과금 근거](https://developers.openai.com/api/docs/guides/reasoning)

미국 달러, **100만 토큰당 Standard 요금**이다. [공식 가격표](https://developers.openai.com/api/docs/pricing)

| 종류 | USD/100만 토큰 |
|---|---:|
| 일반 입력 | $0.10 |
| 캐시 입력 읽기 | $0.01 |
| 캐시 쓰기 30분 | $0.125 |
| 캐시 쓰기 12시간 | $0.25 |
| 출력·추론 | $0.50 |

272K를 초과하는 입력은 전체 요청에 입력/캐시 2배·출력 1.5배가 적용된다. 본 구현은 직원 16,000·관리자 32,000 입력 상한과 그보다 작은 자료/전송 본문 바이트 제한으로 이 구간에 진입하지 않는다. 지역별 처리 추가 요금·세금·계정별 계약 조건은 이 Standard 표에 포함하지 않는다. 공식 등재는 확인했지만 **사용자의 키/프로젝트에 이 모델 접근 권한·잔액이 있는지는 확인하지 않았다.**

`temperature`, `top_p`, `top_logprobs`는 전송하지 않는다. 특히 추론을 사용하는 요청에서는 이 샘플링 옵션의 지원 제약을 고려해야 한다. 본 구현은 모든 역할에서 생략한다. [공식 모델 사용 안내](https://developers.openai.com/api/docs/guides/latest-model)

## 전송·응답·비용 처리

- 신뢰된 서버 지침과 자료 JSON을 분리하고 `text.format`의 strict JSON Schema를 사용한다. 모든 객체를 닫고 필드를 필수로 지정한다. 생성 뒤 기존 로컬 검증으로 출처·인용·필드/enum·날짜·숫자·권한을 다시 검사한다. 관리자 결과는 `is_test=false`를 검증하고 서버 집계만 수치로 사용한다. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- `store=false`, `stream=false`, 도구 없음, 고정 호스트/경로, 45초 소켓 timeout, 응답 최대 1MiB로 제한한다. 리다이렉트·SDK 자동 재시도·모델 대체 경로는 없다. `store=false`를 무보관/ZDR 보증으로 해석하지 않는다.
- `prompt_cache_options={mode: explicit, ttl: 30m}`을 사용하고 breakpoint·prewarm은 보내지 않는다. 불필요한 가변 자료 캐시 쓰기를 줄인다. 캐시 읽기/쓰기 usage는 별도로 기록한다. 12시간 쓰기나 모순/누락 usage가 반환되면 결과 미확인으로 처리해 저가 정산을 막는다. [캐시 옵션과 usage](https://developers.openai.com/api/docs/guides/prompt-caching)
- API `output_tokens`는 추론 토큰을 이미 포함한다. 원장에서는 일반 출력과 추론을 한 번만 분리해 합산한다. 입력은 일반 입력/캐시 읽기/30분 쓰기를 각각 정산한다. 예약은 모든 입력이 30분 쓰기로 청구되는 최악의 경우와 총 출력 상한을 합친다. 직원 $0.0024·관리자 $0.005를 작업당 예약한다. 실제 청구서 검증은 아니다.
- 요청 거부 HTTP 400/401/403/404/413/422는 실패·미사용 비용으로 종료한다. 미지원 모델/옵션도 동일하다. timeout·연결 끊김·429·5xx·리다이렉트·알 수 없는 usage는 `UNKNOWN`으로 보류하고 10분 뒤 예약 비용으로 보수적 정산한다. **실제 작업의 자동 재호출과 다른 유료 모델 전환은 없다.**
- refusal·incomplete·잘못된 JSON/근거는 실패이며 usage가 알려지면 비용을 기록한다. 원시 HTTP 응답·공급자 오류 본문·키는 로그/화면/원장에 저장하지 않는다. 검증을 통과한 결과만 별도 결과 테이블에 저장·표시하고, 원장에는 안전한 공급자 요청 ID와 토큰/비용만 기록한다. 기존 권한 취소·합산30회·전역 동시2개·월 예산·원문 삭제·수동 선택 적용 규칙을 유지한다.

## 설정과 실행

현재 데모는 AI 비활성 상태로 유지했으며 실제 `.env`·`.env.ai`는 열람·변경하지 않았다. **이번에 worker를 활성화하거나 유료 호출을 실행하지 않았다.** 향후 별도로 활성화할 경우에만 아래 절차를 따른다.

1. 운영 대상 DB를 확인하고 migration `0005_openai_request_policy_usage`를 적용한다. 추론 수준과 캐시 사용량 컬럼만 추가하며 고객/계정을 초기화하지 않는다. 기존 운영 백업 복원은 새 스키마에서 추가 검증해야 한다.
2. 기존 파일을 덮어쓰지 말고 `.env.ai.example`과 비교해 서버 전용 0600 파일에 `AI_PROVIDER=openai`, `AI_MODEL=gpt-6-luna`, 단가 `0.10`/`0.50`, 예산과 키를 설정한다. 키는 문서·브라우저·명령행 인수에 입력하지 않는다. `AI_ENABLED=false`에서는 요청을 예약/실행하지 않는다.
3. 유료 기능을 사용하기로 한 환경에서만 `AI_ENABLED=true`로 변경하고 web/worker가 같은 설정·DB를 사용하도록 재시작한다. worker 명령은 `.venv/bin/python manage.py run_ai_worker`이며 Ctrl+C로 종료한다. 생성 버튼의 명시적 POST가 작업을 예약한다. 조회와 scheduler는 새 AI 작업을 만들지 않는다.
4. 미지원 응답·잔액·권한 문제는 설정/계정을 직접 확인한다. 자동 대체 모델은 없다. 비활성화는 `AI_ENABLED=false` 후 web/worker 재시작으로 수행한다. 이미 전송된 요청의 청구를 취소하는 기능은 아니다.

## 가짜 응답 검증 결과

**142/142 통과, 19.464초, 실패·오류·skip 0.** 새 연결 검사18개와 변경 영향을 받는 기존 `test_ai_boundary`, P9·P10·P11·P12 서버 검사124개를 실행했다. PostgreSQL17 데모 클러스터55433의 별도 `test_tm_openai_adapter` DB를 만들고 검사 후 제거했다. 데모 `tm_demo`와 개발 `tm_dev`를 테스트 DB로 사용하지 않았다. 기존 92개 인수 항목 전체·브라우저·Docker·운영 복원을 다시 실행한 결과가 아니다.

검사한 HEAD는 `354ef598a0edcc60415ce8cc3922e9550a79bb0d`(기존 미커밋 구현 포함), 구현/검수 SHA는 `d5f8079edc44b3c6559aa6a8faf15f0e3501930b1a6606be6eff118ccfed336f`다. `source_digest`의 기존 파일 범위로 계산했다. 원시 기록은 `.local/openai-verification.json`과 `.local/demo/openai-tests.log`다. 데모 재실행 후 업무5개 테이블의 값/관계 해시 불변·개발 PostgreSQL 제어 파일 불변/중지·테스트 DB 제거·migration 차이0·check 이상0·healthz/login 200·AI 요청/시도0을 확인했다. 데모는 **http://localhost:8010**에서 AI 비활성 상태로 실행 중이다.

검증한 경로는 실제 예약→worker 분기→가짜 HTTP 응답→파싱→근거/권한 검증→정산이다. 6개 기능의 모델/추론 수준·Standard 고정·strict schema·비용·거부/미완성·통신 유실·권한 회수·실제 작업 재시도 금지 등을 검사했다. 실제 HTTPS 전송 함수도 가짜 연결 객체로 호스트·경로·인증 헤더·단일 POST·연결 종료를 검사했다. 테스트 설정에서 실전 transport를 직접 선택하면 전송 전에 차단한다.

현재 컴퓨터의 안전한 재현 스크립트: `.venv/bin/python .local/demo/verify_openai.py`. 스크립트와 원시 로그 `.local/demo/openai-tests.log`는 Git 제외 로컬 자료다. 다른 환경에서는 **별도 테스트용 PostgreSQL의 DATABASE_URL을 명시한 상태**에서 다음을 실행한다. 기본 개발 DB 주소를 그대로 쓰지 않는다.

```sh
DJANGO_SETTINGS_MODULE=config.test_settings TEST_DATABASE_NAME=test_tm_openai_adapter \
  .venv/bin/python manage.py test tests.test_openai_adapter tests.test_ai_boundary \
  tests.test_p9 tests.test_p10 tests.test_p11 tests.test_p12 --noinput -v 2
```

실제 결제/인증/계정별 모델 접근·한국어 품질·실제 tokenizer/지연/청구서는 미검증이다. 운영 호출을 가짜 응답 검증으로 통과 처리하지 않는다. 코드·원장 구현은 [openai_adapter.py](../apps/ai_assistant/openai_adapter.py), [정책](../apps/ai_assistant/openai_policy.py), [테스트](../tests/test_openai_adapter.py)를 따른다.
