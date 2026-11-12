# DB 저장·조회와 메모리 최적화

2026-11-13 KST. 이전의 ‘25.9KB → 378B’는 **가상 이력 한 건을 조회하는 응답 내용**의 크기였다. 378B는 378바이트다. DB 전체나 이력 원본이 378바이트가 됐다는 뜻이 아니다. 이번에는 별도로 신규 저장 중복과 서버 조회 메모리를 줄이고 측정했다.

실제 고객정보·운영 DB·기존 개발/데모 DB를 변경하지 않았다. AI 외부 호출·유료 사용·외부 배포도 하지 않았다. 기존 이력의 일괄 재작성/삭제, 인덱스 삭제, DB 메모리 설정 변경은 하지 않았다.

## 적용한 변경

### 새 이력 저장 중복 감소

이전에는 재콜 날짜나 통화결과만 수정해도 before/after JSON 두 개에 변경되지 않은 긴 상담내용·비고·관리자 비고 등이 복사됐다. 앞으로 생성하는 이력에서는 **변경되지 않은 장문 필드만 생략**한다.

- 실제로 바꾼 필드의 변경 전·후 값, 변경자·시각·버전·할당은 보존한다.
- 상담내용을 바꾸면 원문 전후를 보존하고, 일반 상담/재콜 변경에는 AI 근거용 상담 원문도 별도 컬럼에 보존한다.
- 고객명·연락처·관리자 비고만 정정한 기록은 상담 분석 대상이 아니므로 같은 상담 원문을 별도 컬럼에 또 복사하지 않는다. 고객 본문과 해당 항목의 변경 전후는 유지한다.
- 대시보드와 AI에서 필요한 통화결과·계약·날짜 등 작은 상태 값은 보존한다.
- 재콜 완료와 삭제 승인도 같은 기준을 적용한다. 삭제 승인으로 추가된 상담 문구의 전후 값은 유지한다.
- 기존 이력과 최초 도입 기록은 재작성하지 않는다. 이전 전체 스냅샷과 새 축약 스냅샷을 모두 조회할 수 있다.

따라서 **기존 DB 파일이 즉시 줄어들지는 않는다.** 앞으로 이력이 누적될 때 불필요한 중복 증가를 줄이는 변경이다. 이력 보존 기간을 임의로 단축하거나 실제 변경 내용을 없애는 작업이 아니다. 새 migration은 없다.

### 조회 메모리 감소

이전 API는 큰 JSON을 Python으로 가져온 뒤 필요한 키만 골랐다. 현재는 PostgreSQL에서 변경 필드를 투영하고 작은 결과를 가져온다. 50개 페이지·정렬·권한·기존 기록 호환은 유지한다.

직원 고객 목록/저장 응답에서는 관리자 비고를 읽지 않고, 담당자 이름 때문에 계정 전체 정보까지 가져오던 조회도 줄였다. AI 직원/관리자 근거 조회에서도 사용하지 않는 이력 컬럼과 관련 고객의 큰 필드를 가져오지 않는다. 미조회 필드가 뒤늦게 추가 쿼리를 만드는지 관련 API·AI·브라우저 검사로 확인했다.

이는 조회 작업을 DB로 옮기는 부분도 있으므로 Python 메모리가 줄었다고 PostgreSQL 메모리까지 같은 비율로 줄었다고 해석하지 않는다. [Django 최적화 문서](https://docs.djangoproject.com/en/5.2/topics/db/optimization/)도 속도·메모리·DB 작업 간의 균형과 변경 후 측정을 요구한다.

### 웹 프로세스 수 선택

Docker의 Gunicorn은 `config/gunicorn.py`를 사용한다. **기본값은 기존과 같은 2 workers × 4 threads**이며 자동 요청 수 기반 재시작은 꺼져 있다. 실제 `.env`는 수정하지 않았다.

| 설정 | 기본값 | 범위/의미 |
|---|---|---|
| `TM_WEB_WORKERS` | 2 | 1~4, 웹 작업 프로세스 수 |
| `TM_WEB_THREADS` | 4 | 1~8, 각 작업 프로세스의 처리 스레드 |
| `TM_WEB_MAX_REQUESTS` | 0 | 0이면 요청 수 기반 교체 안 함. 필요 시 별도 관찰 후 사용 |
| `TM_WEB_MAX_REQUESTS_JITTER` | 교체 활성 시 50 | 작업자 교체 시점 분산. 교체 비활성 기본은 0 |

메모리가 부족한 서버는 보호된 `.env`의 해당 공개 설정 두 개만 `TM_WEB_WORKERS=1`, `TM_WEB_THREADS=4`로 바꾸는 선택지가 있다. 파일을 예시 파일로 덮어쓰지 않는다. worker 감소는 동시에 처리하는 여유와 장애 격리를 줄일 수 있다. 현재 서버 RAM/CPU·부하 측정 없이 일괄적으로 1개가 더 좋다고 판단하지 않는다.

`max_requests`는 누수 영향을 제한하기 위한 주기적 교체 장치이지 누수를 고치거나 최대 메모리를 보장하는 설정이 아니다. 기본값은 그대로 유지한다. [Gunicorn 설정](https://gunicorn.org/reference/settings/), [Docker 메모리 대응 안내](https://gunicorn.org/guides/docker/).

## 실제 실행한 측정

환경: macOS 27.2 ARM64, Python 3.13.18, PostgreSQL 17.11, 로컬 가상자료. Docker 엔진이 없는 환경이라 실제 이미지 빌드/컨테이너 시험은 아니다. Docker와 같은 Gunicorn 설정 파일을 읽는 로컬 Gunicorn을 사용했다. 운영 Ubuntu의 CPU·RAM·디스크·네트워크 성능으로 단정하지 않는다.

### 이력 조회·신규 저장 샘플

| 측정 | 이전 | 개선 후 |
|---|---:|---:|
| 이력 50행 조회의 Python 추적 할당 최고치 중앙값 | 2,140,362B | 66,050B |
| 같은 조회의 처리시간 중앙값 | 6.748ms | 2.904ms |
| 새 이력 형식을 비교한 300행 임시 테이블 전체 크기 | 7,553,024B | 2,637,824B |

조회는 한 번씩 준비 실행 후 이전/개선 경로를 번갈아 3회 측정했다. 변경된 값이 같은지도 비교했다. Python 추적 메모리는 **96.91% 감소**했으나 프로세스 RSS 전체·PostgreSQL 메모리 측정값은 아니다.

저장 비교는 6,010자 가상 상담문, 각각 2,000자 비고/관리자 비고가 있는 고객의 재콜 날짜 변경을 가정했다. 같은 JSON/text 컬럼으로 만든 별도 PostgreSQL 임시 테이블에 300행씩 넣고 TOAST 등을 포함한 relation 크기를 측정했다. 샘플은 **65.08% 감소**했다. 실제 revision 테이블의 모든 컬럼/인덱스·다른 테이블·7일 요청 영수증은 포함하지 않아 **전체 운영 DB가 65% 줄어든다는 뜻이 아니다.** 상담내용 자체를 수정하는 기록은 전후 원문을 유지하므로 절감률이 다르다. 임시 테이블은 측정 후 제거했다.

### 직원20·관리자5 동시 사용

가상 고객 10,000명·25개 로그인 세션·세션별 5회 조회/저장, 측정 요청 250개씩 비교했다. AI 외부 호출은 0회다.

| 측정 | 2 workers × 4 threads | 1 worker × 4 threads |
|---|---:|---:|
| 실패 요청 | 0 | 0 |
| 조회 p95 | 0.242초 | 0.220초 |
| 저장 p95 | 0.302초 | 0.228초 |
| 로그인 포함 전체 경과 | 4.462초 | 4.940초 |
| 웹 master+worker 최대 합산 RSS | 154.22MiB | 92.30MiB |
| 관찰 연결 포함 DB 연결 최고 수 | 10 | 6 |

RSS는 약 50ms 간격으로 master/worker의 값을 합산했다. 공유 페이지 중복 집계와 샘플 사이 최고치 누락이 가능하며 OS·DB·스케줄러·프록시 전체 메모리는 아니다. 1 worker에서 일부 p95가 더 낮았어도 전체 경과는 더 길었다. 짧은 로컬 시험에서 통과한 것이며, 큰 엑셀 업로드와 실제 서버 장시간 부하의 성능 보장은 아니다. 기본값은 2개로 유지한다.

## 운영 서버에서 추가로 할 일

### 먼저 읽기 전용으로 확인

아래 진단 명령은 **업데이트 후 이미지에 포함**된다. DB/테이블 크기, 추정 행 수·정리 대상 행 수, autovacuum 시각, 연결 수와 일부 메모리 설정만 출력한다. 고객 값·비밀번호·DB 접속 URL·진행 중 SQL은 출력하지 않는다. 통계 행 수는 정확한 COUNT가 아닌 추정치다. 5초 제한과 읽기 전용 트랜잭션을 사용한다.

```bash
cd /root/TMDB &&
bash scripts/compose_https.sh exec -T web python manage.py database_usage
```

함께 `free -h`, `docker stats --no-stream`으로 서버와 컨테이너를 확인한다. `free`의 단순 남은 값보다 `available`, swap 사용, 컨테이너 메모리 추세를 본다. 해당 실제 서버 수치는 아직 받지 못했으므로 이번 문서에서 서버별 DB 메모리 값을 확정하지 않는다.

### 절약 우선순위

1. **스케줄러 정상 실행 유지**: 기존 코드가 60초 주기로 만료 업로드 자료와 7일이 지난 요청 영수증을 제한된 묶음으로 정리한다. 자동 회수도 담당하므로 메모리 절약 목적으로 끄지 않는다. 신규 정리 정책이나 이력 삭제 작업은 추가하지 않았다.
2. **AI 미사용 시 AI 작업자 미기동**: 무료 확인·실사용 승인이 없는 상태에서 작업자를 추가로 켜지 않는다. AI 자료 보존 기간은 캐시·근거·감사 요구에 맞춰 별도 결정한다.
3. **웹 worker 수는 실제 사용량을 보고 선택**: 1 worker 옵션을 사용할 수 있지만 현재 운영 RAM/부하 확인 후 결정한다. 변경 후 엑셀 업로드·저장·25명 사용과 OOM/응답 시간을 관찰한다.
4. **PostgreSQL 값을 크게 올리지 않기**: `work_mem`은 연결 하나에 한 번만 쓰는 고정 메모리가 아니며 여러 정렬/해시 연산에 따라 합산된다. 웹과 DB가 한 서버에 있으므로 전용 DB 서버의 메모리 비율을 그대로 적용하지 않는다. `shared_buffers`, `work_mem`, `max_connections`는 진단 후 정한다. [PostgreSQL 메모리 설명](https://www.postgresql.org/docs/17/runtime-config-resource.html).
5. **디스크는 DB 이외 항목도 확인**: Docker 로그 회전, 사용하지 않는 이미지, 암호화 백업 보관 기간·외부 전달 상태를 점검한다. `docker system prune --volumes`, 백업 무차별 삭제는 실행하지 않는다. 큰 이력/AI 테이블의 보관 기간 변경이나 기존 행 재작성은 실제 용량·백업/복구·원본 보존 방식을 먼저 정해야 한다.
6. **autovacuum 유지**: 일반 VACUUM은 정리된 공간을 재사용하게 돕지만 OS 파일 크기를 즉시 줄이는 작업과 다르다. `VACUUM FULL`은 테이블을 재작성하고 강한 잠금을 사용하므로 상시 절약 명령으로 사용하지 않는다. 이번 작업에서는 실행하지 않았다. [PostgreSQL 정리 설명](https://www.postgresql.org/docs/17/routine-vacuuming.html).

## 검증·서버 반영

고유 검사 **244개가 최종 통과**했다. 저장 전후 값·미진행 판정·현재 담당 권한·고객명 정정·재콜·삭제 승인·AI 근거/날짜/캐시·대시보드·이력 화면·HTTPS를 확인했다. 비밀/관리자 비고가 직원 응답에 나타나지 않고 조회가 추가 쿼리로 불어나는지도 검사했다.

| 실행 ID | 결과 |
|---|---|
| `20261112T153007090575Z-4bbf24fa435e4e189fc154cb637ad8bf` | 215개 중 214개 통과. 새 성능 가상자료가 필수 source 값을 누락해 benchmark 1개 실패. DB 분류 제약은 정상적으로 거부 |
| `20261112T153232654566Z-59f997f5c23e43da9da7f98db4041b9d` | 가상자료 source 보완 후 benchmark·1/2 worker 실제 HTTP 부하·브라우저 30개 통과 |
| `20261112T153237000631Z-ec42b4f0564b48909e71c41f103f32ba` | Django 설정·migration drift 검사 통과 |

원본은 `.local/verification-runs/<실행ID>/`의 JSON과 artifacts다. 테스트 실행 중 소스 변경 없음도 확인했다. `database-memory-benchmark.json`, `final-25-concurrency.json`, `low-memory-25-concurrency.json`에 수치를 보존했다. 마지막 실행이 전체 검사를 반복한 뜻은 아니다. 테스트 DB·임시 테이블·웹 프로세스는 종료했다.

```bash
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label database-memory tests.test_database_optimization tests.performance_database_memory tests.performance_concurrent.FullCapacityHTTPTests tests.performance_concurrent.LowMemoryFullCapacityHTTPTests
.venv/bin/python scripts/run_final_verification.py stop
```

**새 migration이나 기존 DB 일괄 변경은 없다.** HTTPS 서버에서는 저장 중인 작업을 마친 뒤 아래로 반영한다. 비밀 파일·DB 볼륨·AI 활성화 값은 유지한다. 실제 Docker 이미지 빌드/운영 서버 실행 성공은 적용 후 별도로 확인한다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh build web scheduler &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh ps
```

기본 설정 그대로라면 웹은 2 workers × 4 threads로 실행된다. 이미 별도 AI 작업자를 운영 중인 환경은 작업자도 웹과 같은 이미지 버전으로 관리한다. 위 명령은 AI 작업자를 새로 기동하지 않는다.
