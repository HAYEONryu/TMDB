# 관리자 대시보드 계약 건수

2026-11-11 KST. 관리자 첫 화면의 **상담결과 비율** 카드 아래에 **계약 건수·계약률**을 표시한다. 같은 카드의 현장과 조회 기간 선택을 적용한다. 계약은 상담결과와 동시에 해당할 수 있는 별도 상태이므로 도넛의 상담결과 분포는 그대로 유지하고, 별도 요약으로 표시한다.

| 조회 기간 | 계약 집계 |
|---|---|
| 전체 기간 | 선택 현장의 휴지통 제외 현재 고객 중 계약여부가 ‘계약’인 고객. 미할당도 포함 |
| 금주 | 월요일 00시부터 다음 월요일 00시 미만 중 조회 시점까지 직접 저장·AI 선택 적용 저장한 고객의 기간 내 마지막 계약 상태 |
| 오늘 | 한국 날짜 00시부터 다음 날 00시 미만 중 조회 시점까지 직접 저장·AI 선택 적용 저장한 고객의 기간 내 마지막 계약 상태 |

계약 건수는 같은 고객을 여러 번 저장해도 한 번만 센다. 계약률은 계약 고객 수를 차트 중앙의 동일한 집계 고객 수로 나눈 값이다. 고객이 없으면 0건·0%를 표시한다. 다른 현장·휴지통·미래 저장·업로드 및 시스템 기록은 기존 기간 집계 규칙에 따라 제외한다. 기간 이력에 계약 상태가 없는 오래된 기록은 현재 상태로 추정하지 않고 계약 수에서 제외한다.

`/api/dashboard`의 관리자 전용 `manager.distribution.contracted_total`로 수량을 제공한다. 상담결과와 계약 상태를 같은 그룹 쿼리로 집계하고 기존 읽기 전용 스냅샷을 사용한다. 직원에게 관리자 계약 집계를 추가로 제공하지 않는다. 기간·현장 변경 중에는 로딩을 표시하며 실패하면 이전 계약 숫자를 지운다. DB 스키마 변경은 없다.

## 검증

분리된 PostgreSQL 17 가상 DB와 실제 Chromium 화면에서 **17개 검사 통과**. 전체·금주·오늘, 같은 고객 반복 저장, 기간 마지막 상태, 현재 상태와 과거 상태의 차이, 빈 현장, 휴지통과 다른 현장 제외, 과거 누락 필드, 직원 접근 차단, 기존 쿼리 수 상한, 모바일 화면, 조회 실패 시 이전 수치 제거를 확인했다.

실행 ID: `20261111T080849309388Z-4905cdf41f694c809aaba79d4048bec9`. 결과와 PC·모바일 화면은 `.local/verification-runs/<실행ID>/`에 보존한다. 실행 중 소스 변경 없음도 확인했다. 실제 고객정보나 외부 AI 호출을 사용하지 않았고 개발·데모 DB 및 실제 서버는 변경하지 않았다. 로컬 결과는 운영 서버 성능이나 실제 배포 성공을 증명하지 않는다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label dashboard-contract-counts tests.test_dashboard_reports tests.browser_ui
.venv/bin/python scripts/run_final_verification.py stop
```

## 기존 Docker 서버 반영

현재 사용자 서버는 `compose.yaml`과 `compose.server.yaml`을 함께 사용한다. 최신 코드를 받는 것만으로 실행 이미지가 갱신되지는 않으므로 이미지를 다시 빌드하고 웹·스케줄러를 같은 릴리스로 재생성한다. `.env`의 복원된 TM_SERVER_SECRET·TM_DB_PASSWORD와 `.env.ai`의 기존 설정을 유지한다. 이번 변경에는 추가 migration이 없다. 이전 `customers.0002_customer_metadata` 적용 상태는 별도다.

```sh
cd /root/TMDB
git pull --ff-only &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml build web scheduler &&
docker compose -f compose.yaml -f compose.server.yaml \
  up -d --no-deps --no-build --force-recreate web scheduler
```

기존 PostgreSQL 컨테이너·볼륨을 재생성하지 않는다. AI 작업자나 외부 AI 요청을 새로 실행하지 않는다. 재생성 시 웹 서비스가 잠시 중단될 수 있다. 브라우저를 새로고침한 뒤 관리자 첫 화면에서 현장·기간에 따른 계약 건수와 계약률을 확인한다. 실제 서버 반영은 사용자가 위 절차를 수행한 뒤 별도로 검증해야 한다.
