# 기존 우분투 Docker 서버에 IP HTTPS 추가

기준: 2026-11-12. 대상은 `/root/TMDB`, 공개 IPv4 `165.140.21.197`, 기존 `compose.yaml` + 서버 전용 `compose.server.yaml`이다. 사용자가 제공한 출력에서는 Compose 5.7.0, 80·443 미사용, 웹 8000 외부 공개, PostgreSQL 내부 전용이다. 이 문서를 작성하면서 실제 서버 설정·방화벽·인증서 발급을 실행하지 않았다.

로컬 검사 결과와 실제 서버 미확인 항목은 [HTTPS 검증 기록](HTTPS_IP_VERIFICATION.md)에 구분해 보존했다.

도메인 없이 `https://165.140.21.197`로 접속하도록 준비했다. Let's Encrypt의 무료 IP 인증서는 `shortlived` 프로필을 사용하며 유효기간은 160시간이다. Caddy가 발급·갱신을 관리한다. 인증기관 발급 제한·외부 통신 실패 시 성공을 보장하지 않는다. [공식 IP 인증서 안내](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability), [Caddy ACME 프로필](https://caddyserver.com/docs/caddyfile/directives/tls), [자동 갱신](https://caddyserver.com/docs/automatic-https).

## 변경 범위

- `compose.https.yaml`을 기존 두 파일 뒤에 적용한다. `web`의 모든 호스트 포트(8000 포함)를 지우고 Caddy만 TCP 80·443을 공개한다. Compose `!reset`·`!override`를 사용하므로 2.24.4 이상이 필요하며 확인된 5.7.0은 지원한다. [병합 규칙](https://docs.docker.com/reference/compose-file/merge/).
- Caddy 2.10.2의 기존 digest 고정 이미지를 사용한다. 명시적인 Let's Encrypt 발급자·프로필을 사용하며 브라우저가 신뢰하지 않는 내부 CA로 대체하지 않는다. IP 접속의 SNI 부재를 처리하도록 `default_sni`를 설정했다.
- `config.https_settings`로 보안 쿠키·CSRF origin·HTTPS 리다이렉트·프록시 헤더를 적용한다. `web` health check도 올바른 Host와 프록시 헤더를 사용한다. 백엔드 포트 격리가 필수이며 별도 외부 포트·직접 진입점을 추가하지 않는다.
- 기존 DB·볼륨·서명 키·DB 비밀번호를 유지한다. `.env`·`.env.ai`·`compose.server.yaml`을 덮어쓰거나 migration을 실행하지 않는다. `deploy/compose.production.yaml`로 교체하는 절차가 아니다.
- AI 활성화/무료 확인 값은 변경하지 않고 AI 작업자를 중단 상태로 유지한다. 웹·스케줄러·PostgreSQL·프록시에 재부팅 후 재시작 정책을 적용한다. Docker 자체의 부팅 시 실행 여부는 서버에서 별도 확인한다.
- Caddy 인증서·계정 키는 전용 영속 볼륨 `/data`, `/config`에 보관한다. 볼륨은 비밀 저장소로 취급하며 Git·공개 백업에 넣지 않는다. 요청 access log는 켜지 않으며 운영 오류 로그의 request 필드도 제거한다.

## 1. 네트워크 준비

서버 업체의 방화벽/보안그룹에서 이 서버로 들어오는 **TCP 80과 TCP 443**을 허용한다. SSH 포트와 기존 접속 허용은 유지한다. 서버 OS 방화벽도 해당 포트를 허용해야 한다. 외부로는 인증기관 HTTPS 통신과 DNS 조회가 가능해야 한다. Docker 게시 포트에는 UFW 규칙만으로 접근 제한이 적용되지 않을 수 있어, 이번 구성에서는 웹 게시 자체를 제거한다.

UFW 상태 확인은 다음과 같다. 비활성인 방화벽을 이 절차에서 임의로 활성화하거나 초기화하지 않는다.

```bash
sudo ufw status
```

이미 UFW가 활성 상태이고 SSH 허용을 유지한 상태라면 다음으로 웹 포트만 추가한다. 서버 업체 방화벽은 별도로 설정해야 한다.

```bash
sudo ufw allow 80/tcp &&
sudo ufw allow 443/tcp
```

## 2. 코드·이미지·설정 확인

아래 블록은 기존 웹을 중단하지 않는다. 기존 서버 비밀값을 유지하며 Django 검사도 DB migration을 수행하지 않는다. 검사 실패 시 3단계를 실행하지 않는다.

```bash
cd /root/TMDB &&
git pull --ff-only &&
bash scripts/compose_https.sh config --quiet &&
bash scripts/compose_https.sh build web scheduler &&
bash scripts/compose_https.sh pull proxy &&
bash scripts/compose_https.sh run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile &&
bash scripts/compose_https.sh run --rm --no-deps web python manage.py check
```

`scripts/compose_https.sh`는 기존 세 Compose 파일을 항상 같은 순서로 지정하고 `TM_SERVER_SECRET`·`TM_DB_PASSWORD`의 셸 덮어쓰기만 해제한다. 보호된 기존 `.env`를 사용한다. 공개 IP 기본값은 `165.140.21.197`이다. IP가 달라지면 이 문서의 명령을 그대로 실행하지 말고 `TM_HTTPS_IP`, 접속 주소와 외부 통신 경로를 함께 조정한다.

Caddy의 `Unnecessary header_up X-Forwarded-Proto` 경고는 기본 동작을 명시적으로 반복한다는 뜻이다. 검사가 성공한 경우 이 경고 자체는 발급/기동 실패가 아니다.

## 3. HTTPS 적용

모든 사용자가 저장 완료·로그아웃한 뒤 실행한다. 웹 재생성 중 잠시 끊기며, HTTPS는 실제 인증서 발급 완료 후 연결된다. AI 작업자를 실행하지 않는다.

```bash
cd /root/TMDB &&
bash scripts/compose_https.sh --profile ai stop ai_worker &&
bash scripts/compose_https.sh up -d --no-deps --no-build --force-recreate web scheduler &&
bash scripts/compose_https.sh up -d --no-deps proxy &&
bash scripts/compose_https.sh ps
```

이 명령은 PostgreSQL을 재생성하거나 DB 데이터를 변경하지 않는다. PostgreSQL의 새 재시작 정책은 다음으로 기존 컨테이너에 적용한다. 컨테이너를 재생성하거나 재시작하는 명령이 아니다.

```bash
cd /root/TMDB &&
docker update --restart unless-stopped "$(bash scripts/compose_https.sh ps -q postgres)"
```

## 4. 확인

```bash
cd /root/TMDB &&
bash scripts/compose_https.sh ps &&
docker ps --format 'table {{.Names}}\t{{.Ports}}' &&
curl --fail --show-error --silent --output /dev/null --write-out 'HTTPS 상태: %{http_code}\n' https://165.140.21.197/healthz
```

최초 발급 중에는 `curl`이 실패할 수 있다. 잠시 기다린 뒤 확인한다. 계속 실패하면 같은 적용 명령을 반복해 인증서를 재발급하려 하지 말고 80·443 외부 접근, 인증기관 통신, 발급 제한과 프록시 상태부터 확인한다. 필요 시 서버에서 `bash scripts/compose_https.sh logs --tail=60 proxy`를 확인하되 원시 로그를 그대로 공유하지 않는다. 발급 완료와 향후 자동 갱신은 별개로 관찰한다.

- `curl`은 `200`, 웹은 `healthy`여야 한다. 인증서 검사를 생략하는 `-k`를 사용하지 않는다.
- `docker ps`에서 웹에 `0.0.0.0:8000->...` 또는 `[::]:8000->...`가 없어야 한다. 이미지 메타데이터인 `8000/tcp`만 표시되는 것은 게시가 아니다. 공개 포트는 프록시 80·443이다.
- 별도 PC의 브라우저에서 **`https://165.140.21.197/auth/login`**을 연다. `:8000`을 붙이지 않는다. 인증서 경고가 없어야 하고 HTTPS로 다시 로그인한다.
- 직원의 현장·할당 고객 조회, 편집, 저장 완료를 확인한다. 기존 HTTP 탭과 HTTPS 탭은 브라우저 저장소가 다르므로 HTTP 탭의 미저장 편집을 자동 이전한다고 가정하지 않는다.
- 별도 PC에서도 위 HTTPS healthz 명령을 실행한다. 서버 자기 자신에서 성공한 결과만으로 외부 접근 성공을 판단하지 않는다.

인증서 만료일만 확인하는 읽기 전용 명령이다. IP SAN과 기본 신뢰 체인 검증도 수행하며 쿠키·인증정보는 사용하지 않는다.

```bash
python3 - <<'PY'
import datetime, socket, ssl
ip = '165.140.21.197'
with socket.create_connection((ip, 443), timeout=10) as tcp:
    with ssl.create_default_context().wrap_socket(tcp, server_hostname=ip) as tls:
        expiry = tls.getpeercert()['notAfter']
        deadline = datetime.datetime.fromtimestamp(ssl.cert_time_to_seconds(expiry), datetime.timezone.utc)
        remaining = deadline - datetime.datetime.now(datetime.timezone.utc)
        print('certificate_verified: true')
        print('expires_utc:', deadline.isoformat())
        print('remaining_hours:', round(remaining.total_seconds() / 3600, 1))
PY
```

최초 발급 후 만료가 임박하기 전에 자동 갱신으로 만료일이 연장되는지 관찰한다. 잔여 48시간 미만이면 갱신 오류를 조사하고 만료 전 조치한다. 인증서 갱신용 80·443과 영속 볼륨을 계속 유지한다. `down -v`, 인증서 볼륨 삭제, 브라우저 경고 무시는 해결 절차가 아니다.

## 5. 이후 시작·중단·업데이트

**HTTPS를 적용한 서버는 이후에도 항상 이 스크립트를 사용한다.** 기존 두 파일만 지정한 `up`/`run` 명령은 HTTPS 설정을 누락하거나 8000 포트를 다시 노출할 수 있다. [최신 코드 반영 안내](SERVER_UPDATE_COMMANDS.md)의 HTTPS 서버 절차를 사용한다. Docker/서버 전체 종료 시에는 자동 회수·AI 처리가 중단된다.

```bash
# 웹·스케줄러·프록시 재시작 (DB 유지, AI 시작 안 함)
cd /root/TMDB &&
bash scripts/compose_https.sh up -d --no-deps web scheduler proxy
```

```bash
# 앱 중단 (DB·인증서 볼륨 유지)
cd /root/TMDB &&
bash scripts/compose_https.sh --profile ai stop web scheduler ai_worker proxy
```

AI는 별도 무료 등급 확인·활성화 조건을 충족한 뒤에만 [AI 활성화 문서](AI_ACTIVATION.md)를 따른다. 그때도 Compose 명령에는 이 HTTPS 스크립트를 사용한다.

## 6. 실패 시 복구

2단계에서 실패하면 현재 서비스를 유지하고 원인부터 확인한다. 적용 후 HTTPS가 실패하면 프록시와 네트워크를 점검하며 인증서 볼륨과 DB는 보존한다. 이전 HTTP 조회 상태로의 복구가 꼭 필요한 경우에만 다음을 사용한다. 이는 **HTTPS를 해제하고 기존 서버 파일에 정의된 8000 접근을 복원**하며 직원 저장은 다시 제한된다. 안전한 직원 운영 완료를 뜻하지 않는다.

```bash
cd /root/TMDB &&
bash scripts/compose_https.sh stop proxy &&
unset TM_SERVER_SECRET TM_DB_PASSWORD &&
docker compose -f compose.yaml -f compose.server.yaml up -d --no-deps --no-build --force-recreate web scheduler
```

실제 서버 인증서 발급·갱신, 방화벽, 재부팅과 외부 접속은 사용자가 적용 후 결과로 확인할 항목이다. DB 권한 분리·외부 백업·실서버 성능 등 이전 운영 미검증 항목은 HTTPS 추가만으로 통과가 되지 않는다.
