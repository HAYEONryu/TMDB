# 현재 운영 기준

기준일: 2026-11-08 KST. 최신 사용자 지시가 승인 설계서 v2.0의 이전 수치보다 우선한다. 적용 AGENTS.md는 저장소·상위 경로에서 발견되지 않았다. 이 문서는 **현재 실행·배포 준비의 기준**이며 과거 검수 결과를 갱신한 기록이 아니다.

## 확정 조건과 현재 상태

| 항목 | 현재 기준 |
|---|---|
| 제공자·모델 | `gemini` · `gemini-3.5-flash-lite` 하나, 추론low |
| 비용·전환 | 무료 등급만, 유료 승인 **$0**. 유료 전환·다른 모델/공급자 자동 전환 금지 |
| 활성 인원 | 직원 최대20명, 관리자 최대5명. 비활성 계정은 이력 보존·활성 정원에서 제외 |
| 직원 개인 AI | 상담 정리·요약·다음 질문 합산 한국 날짜 하루40회, 성공+진행/대기 예약≤40 |
| 공용 한도 우선 | 직원 개인 잔여보다 프로젝트 전체 제공자 RPD·RPM·입력 TPM을 먼저 적용. 관리자도 공용 한도 사용 |
| 과거 한도 기록 | **RPD500·RPM15·입력 TPM250,000은 이전 사용자 확인/설정 기록값이다. 현재 계정에서 재확인되지 않았다.** 고정 공식 보장값이나 현재 잔여량으로 사용하지 않는다 |
| 날짜 경계 | 개인은 KST00시. 제공자 RPD는 미국 태평양00시/DST 적용. 앱 원장을 분리한다 |
| 현재 AI 상태 | **AI_ENABLED=false, AI_FREE_TIER_CONFIRMED=false 유지.** 이번 작업에서 키/현재 비밀 파일·확인 상태를 변경하지 않음 |
| 공유 결과 | 주간 브리핑은 일요일 접수·주1회, 직원 코칭은 대상 직원별 하루1회, 현장 가이드는 현장별 하루1회. 관리자 결과 공유·캐시 재조회는 신규 생성 아님 |
| 사용 제한 | 실제 고객정보 사용·외부 서버 배포·호스팅 구매·유료 호출을 실행하지 않음 |

500RPD가 실제 한도라면 직원20명×40회=800회 전체 사용을 보장할 수 없다. 관리자와 전송된 실패, 같은 프로젝트의 다른 앱 사용량은 가용량을 더 줄인다. 개인40회는 상한이며 보장 배분량이 아니다. 확인되지 않은 무료 계정/잔여량 상태에서 실제 호출을 하지 않는다.

## 현재 실행 안내

2026-11-09 사용자 승인: 고객명은 선택이고 연락처만 필수다. 루트·새 비고는 기존 상담기타내용과 별도 텍스트 항목이며 관리자 비고는 관리자만 조회·수정한다. 다운로드 양식은 A~F의 고객명·연락처·고객 거주지·주택상황·비고·관리자 비고 6열이다. 루트는 등록 후 표에서 입력한다. [현재 양식·권한·migration 적용](EXCEL_TEMPLATE_GUIDANCE.md)이 이전 설계서의 고객명 필수·9열 다운로드 기준보다 우선한다.

관리자 대시보드의 **최근 7일 직원별 상담 고객 수**는 오늘을 포함한 한국 날짜7일 동안 실제 변경 저장한 고객을 직원별로 중복 없이 센다. 같은 고객의 비고를2번·재콜을1번 저장해도1명이다. 서로 다른 고객을 저장하면 각각1명이며, 같은 고객을 여러 날짜에 저장해도 기간 전체에서1명이다. 직접 수정·선택 적용 저장만 포함하고 업로드/시스템 기록은 제외한다. 원본 저장 이력은 삭제하거나 합치지 않는다. 이는 이전 대시보드 문서의 저장 횟수 집계보다 우선하는 최신 사용자 승인이다.

[README](../README.md)의 새 빈 DB/가상자료 경로와 [운영·배포 절차](OPERATIONS.md)를 사용한다. 기존 DB의 migration·계정 초기화는 이 준비 작업에 포함되지 않는다. 앱·scheduler·worker는 같은 DB와 승인된 설정을 사용해야 한다. AI는 계속 비활성이다.

`.env.ai.example`은 빈 값 예시로 유지한다. 직접 사용하는 파일의 모델/무료모드 확인과 실제 활성화 승인은 별도이며, 이전 문서의 true 또는 유료 예산값을 복사해 활성화하지 않는다. 월 예산에 과거 값이 남아 있어도 실제 실행은 무료 Lite만 허용한다. 현재 신규 설정의 유료 예산은0을 사용한다.

## 실행별 증거와 개인정보

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label operations-stage1 tests.test_stage1_evidence tests.test_acceptance
.venv/bin/python scripts/verify_docker_release.py --label docker-stage1
.venv/bin/python scripts/run_final_verification.py stop
```

`--label`은 사람이 읽는 이름이며 재사용할 수 있다. 실제 식별자는 UTC시각+UUID인 실행 ID다. 매번 `.local/verification-runs/<실행ID>/`를 새로 생성하고 테스트 DB 이름도 실행마다 다르게 지정한다. `started.json`에 시각·코드 HEAD/소스 해시·작업 트리 변경 여부·공개 명령·결과 위치, `finished.json`에 종료 코드·상태를 기록한다. `events.jsonl`과 `test-events.jsonl`은 구조화 로그, `results.json`은 실행별 결과, `artifacts/<테스트ID 해시>/`는 테스트별 자료다. 기존 파일은 덮어쓰지 않는다.

비밀/고객값을 포함할 수 있는 원시 stdout/stderr·예외 메시지·assert 값·HTTP 본문·쿠키·인증 헤더·브라우저 DOM은 보존하지 않는다. 실패 진단은 예외 종류와 코드 위치만 보존한다. 검수는 폐기용 DB·가상자료만 사용한다. SIGKILL/전원 단절로 `finished.json`이 없으면 **미완료·종료 코드 미확인**이며 통과로 세지 않는다. 완료된 개별 테스트 이벤트가 남을 수 있다. 최초 실패 전 결과를 다른 실행 결과로 채우지 않는다.

과거 `.local/final-test/diagnostic-cascade-results.json`의 대응 원시 로그 1회분은 **유실·복구 불가**다. 과거 데이터 그대로 보존하며 새 실행을 원본 복구로 표시하지 않는다. 이전 실험7회/9,983토큰 기록은 이번 모의 검사와 분리한다.

## 원인 미확정 네트워크 오류

로그인 후 `chrome-error://chromewebdata/` 현상의 원인은 **미확정**이다. 이후 재현되지 않았음을 원인 해결로 표시하지 않는다. 직원 브라우저 검사의 관찰기를 통해 실행 ID·테스트 ID별로 다음을 보존한다.

- Playwright trace에서 API 동작 종류·호출 ID·시각·실패 여부만 추출한 `browser-trace.json`. 비밀번호 fill 값·URL/본문/헤더·스택·DOM·스크린샷·resource·network 원문은 제외한다. 원시 trace는 보호된 임시 디렉터리에서 변환한 뒤 삭제하며 원문으로 대체 보존하지 않는다. 따라서 일반 Playwright trace viewer용 완전한 원본이 아니라 **진단용 allowlist 투영본**이다.
- 실패 요청의 메서드·경로 분류·표준 net 오류 코드. query·고객ID/명·인증정보·본문 제외.
- 서버 스레드 상태·`/healthz` 상태와 Django 로그의 logger/레벨/상태코드. 원문 메시지 제외.

기존 setup 실패 시 Playwright 정리도 유지한다. 새 관찰기의 강제 네트워크 오류 검사는 관찰·비밀 제외 경로를 검증하는 것이며 과거 자연 발생 오류를 재현/해결했다는 뜻이 아니다.

## Docker와 DB 권한

운영 산출물은 [deploy/compose.production.yaml](../deploy/compose.production.yaml)이다. 실제 Docker 검증은 로컬 Unix 소켓 엔진에서만 허용한다. 원격 Docker 컨텍스트·TCP/SSH 엔진은 외부 배포 금지 조건으로 거절한다. 엔진이 없으면 `not_run`이며 정적 검사나 모의 성공으로 대체하지 않는다.

검수 도구는 코드만 allowlist로 별도 컨텍스트에 복사하고 실제 `.env`·`.env.ai`를 읽지 않는다. 가짜 표식을 staging의 비밀 파일에 넣고 scratch/COPY 전체 컨텍스트, 앱 이미지 전체 레이어·history·컨테이너 로그를 검사한다. 가상자료용 고유 Compose 프로젝트/볼륨, 내부 전용 네트워크와 loopback 프록시만 사용한다. AI 비활성·무료확인false로 작업자를 실행하고 외부 AI 경로를 열지 않는다.

새 빈 PostgreSQL은 초기화 관리자 `tm`과 앱 계정 `tm_app`을 분리한다. 앱은 NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION이며 public schema의 앱 migration용 CREATE/USAGE만 허용한다. bootstrap와 앱 DB 비밀번호 파일은 서로 다르다. 기존 볼륨에 초기화 스크립트를 자동 재적용하지 않는다. [Docker 공식 PostgreSQL 설명](https://hub.docker.com/_/postgres)에 따라 POSTGRES_USER는 초기 superuser이므로 앱에 그대로 쓰지 않는다.

실제 Linux에서는 AI 파일은 UID10001 소유·0600으로 web/worker만 읽게 한다. PostgreSQL 초기화 비밀 파일은 해당 이미지의 postgres UID가 읽을 수 있게 준비한다. 권한 문제를0644로 완화하지 않는다. 검수는 가짜 파일을 전용 볼륨에 맞는 UID/0600으로 준비한다. 실제 호스트 bind mount 소유권·Docker Desktop 매핑은 운영 환경에서 별도로 확인한다.

빌드가 성공하면 실행 ID의 결과에 Git HEAD·전체 소스 해시(미커밋 변경 포함)·이미지 content ID·플랫폼·이미지 archive SHA-256을 연결한다. archive로 `docker load`해 같은 산출물을 쓸 수 있지만 공개 registry 전송이나 실제 서버 배포는 하지 않는다. 재빌드가 항상 같은 이미지 ID가 된다고 보장하지 않는다. 검수 오버라이드는 Compose2.24.4 이상 `!override`/`!reset`을 사용한다([공식 merge 규칙](https://docs.docker.com/reference/compose-file/merge/)).

## 다음 단계에 필요한 환경·사용자 결정

비밀번호/API 키는 채팅으로 받지 않는다. 아래에는 비밀이 아닌 방식·이름·경로만 필요하다.

1. **로컬 Docker 엔진:** 사용할 설치/컨텍스트, 로컬 실행 가능 상태. 없으면 무료 로컬 런타임 설치 주체·방식 결정. 실제 build/Compose 근거 전까지18.8-22 미검증.
2. **서버 접속 방식:** 로컬 PC 운영 또는 기존 서버 사용 여부, OS/CPU·접속 방식(SSH/VPN 등)·접속 계정 권한·배포 경로. 자격증명은 보호된 로컬 파일/승인된 비밀 저장소로 준비. 외부 배포는 별도 단계 승인 필요.
3. **도메인/접속 범위:** 내부망 전용 또는 외부 공개, 소유 도메인·DNS 관리 주체·HTTPS 인증서 방식·프록시/방화벽 관리 주체. HSTS 하위 도메인/preload 적용 여부는 도메인 범위 검토 후 결정.
4. **외부 백업:** 별도 장애 영역의 저장소 종류/호스트/경로·전용 계정 권한·SSH host key 확인 방식·암호화 키 보관 위치/담당자·보관기간·용량·복구훈련 주기.
5. **운영 목표:** 허용 데이터 손실(RPO), 복구시간(RTO), 근무시간·23시 상시 실행/절전 정책, 장애 감시·알림 담당자와 수단.
6. **기존 DB 적용:** 대상 클러스터/DB 이름·현재 migration·복제본 사용 가능 여부. 기존 DB 직접 변경이 필요해지면 정확한 대상, 사전 암호화 백업, 별도 복원 검증, 중단·롤백 방식을 먼저 제시한다. 현재는 요청/적용하지 않는다.
7. **무료 AI:** 현재 프로젝트·정확한 모델의 무료 티어/결제 미연결·RPD/RPM/TPM·잔여량 확인일, 같은 프로젝트를 쓰는 다른 앱의 사용 여부. 실사용 활성화와 실제 고객정보 전송/보관 정책은 별도 결정. 지금은 모두 비활성 유지.

역사적 근거: [이전 최종 검수](FINAL_VERIFICATION.md), [당시 P13 92문항](FINAL_ACCEPTANCE.md), 원 설계서·P1~P13 검수 기록. 새 준비 단계 결과는 [OPERATIONS_STAGE1.md](OPERATIONS_STAGE1.md)에 별도로 기록한다. 과거 모델·한도·통과 수를 이 문서 값으로 덮어쓰지 않는다.
