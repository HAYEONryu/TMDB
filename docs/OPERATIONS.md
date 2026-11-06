# 운영·백업·복원 절차

이 문서는 배포 준비 산출물이다. 실제 운영 서버/도메인/외부 저장소를 생성하거나 배포하지 않았다. 실제 Docker 이미지·공개 인증서·외부 보관소·물리 모바일 검증은 별도로 필요하다. 일반 실행의 실제 AI 공급자 호출은 계속 비활성이다.

## 운영 설정과 사전 검사

`deploy/compose.production.yaml`은 개발 Compose와 별개로 사용한다. 두 파일을 합치면 개발 웹 포트/가짜 환경변수가 섞일 수 있으므로 운영 명령에 항상 `-f deploy/compose.production.yaml`을 명시한다. 프록시만80/443을 공개하며 DB와 웹 백엔드는 호스트 포트를 열지 않는다. 신뢰 프록시 밖에서 백엔드에 접속할 수 없어야 한다.

`deploy/production.env.example`, `deploy/app.env.example`, `.env.ai.example`을 참고해 실제 파일은 checkout 밖 `/srv/tmdb/secrets` 등에0600으로 만든다. 배포 보간 파일에는 도메인·불변 이미지 digest·비밀파일 경로만 둔다. 앱 파일에는 운영 전용 무작위 secret·DB URL·DEBUG/가짜 seed 비활성을 둔다. AI 파일은 web/ai_worker만 사용하고 scheduler/백업 프로세스에는 전달하지 않는다. DB 비밀번호 파일의 값과 앱 DB URL의 자격증명은 운영자가 일치시킨다. 예시의 가짜 값이나 빈 비밀번호를 운영에 사용하지 않는다.

```sh
.venv/bin/python scripts/verify_production.py --env-file /srv/tmdb/secrets/deployment.env
docker compose --env-file /srv/tmdb/secrets/deployment.env -f deploy/compose.production.yaml --profile ai config --quiet
```

사전 검사는 파일 내용을 출력하지 않고 digest 고정·포트·AI 파일 범위·비밀파일 위치/권한을 검사한다. Docker 런타임/이미지 존재/공개 HTTPS를 검증한 것으로 표시하지 않는다. 실제 이미지 digest는 이미지를 빌드·검사한 환경에서 확정한다. PostgreSQL/Caddy의 고정 digest와 앱 의존성 lock은 유지했다. 앱 Gunicorn은2 workers×4 threads이며 실제 동일 구성의 로컬20계정 부하 검증을 제공한다.

운영 웹/worker/scheduler는 `config.production_settings`를 사용한다. DEBUG/가짜 seed·약한 secret/개발 DB 비밀번호·잘못된 도메인을 거부한다. HTTPS 리다이렉트·Secure 세션/CSRF cookie·신뢰 프록시 헤더를 설정한다. Caddy가 외부 `X-Forwarded-Proto`를 실제 접속 스킴으로 덮어쓴다. HSTS는 해당 도메인1시간부터 시작하고 subdomain/preload는 켜지 않는다. Django deploy 검사의 W005/W021은 이 선택에 따른 경고다. 도메인/하위 도메인 전체 검토 없이 preload나 장기 HSTS를 켜지 않는다.

## 배포·롤백 순서

1. 동일 소스의 전체 테스트·92문항 결과·운영 사전 검사를 확인한다. 미검증 항목을 숨기지 않는다.
2. 배포 직전 암호화 백업의 성공 종료·외부 전달·복구용 키 보관을 확인한다.
3. 검증한 불변 이미지로 DB 준비 → migration → 최초 관리자 생성 → 웹/예약 프로세스를 순서대로 실행한다. 운영에서 seed를 사용하지 않는다.
4. 프록시를 열고 실제 도메인의 인증서/HTTP 리다이렉트/Secure cookie/CSRF·정적 파일/로그인/역할·조회·저장을 확인한다. healthz는 DB 연결도 검사한다. 웹·DB 포트를 외부에서 직접 열지 않는다.
5. 실패 시 이전 이미지로 복귀한다. DB migration 되돌리기는 데이터/인덱스 영향과 호환성을 따로 판단한다. 복원을 무조건 실행하거나 기존 DB를 자동 덮어쓰지 않는다.

현재 새 migration은 직원별 현재 할당 조회를 위한 부분 인덱스와 AI 추론 수준·캐시 사용량 컬럼(`ai_assistant.0005`)이다. 운영 적용 전 백업과 실제 자료량의 인덱스 생성 잠금 시간을 확인한다. OpenAI 연결의 활성화 조건·공식 단가·검증 범위는 [연결 안내](OPENAI_CONNECTION.md)를 따른다. 이번 OpenAI 작업은 기존 개발 DB를 실행·변경하지 않았으며 운영 배포·유료 호출도 하지 않았다.

## 암호화 백업

백업은 웹/예약 프로세스와 별도의 운영 명령이다. 호스트의 PostgreSQL17 `pg_dump`/`pg_restore`와 age가 필요하다. 앱 이미지 안에 이 운영 도구가 준비되어 있다고 가정하지 않는다. age 설치 도구는 공식 배포의 SHA-256을 고정 확인하며 프로젝트 내부에 설치한다.

```sh
.venv/bin/python scripts/install_verification_tools.py --tool age
```

복구 키는 별도 복구용 호스트에서 새로 생성한다. 기존 파일을 덮지 않는다. 개인 identity는 백업 호스트와 별도로 안전하게 보관하며 공개 recipient만 백업 설정에 옮긴다. 키를 채팅·Git·문서·로그에 기록하지 않는다.

```sh
umask 077
.local/bin/age-keygen -o /복구용_별도_경로/tmdb.agekey
.local/bin/age-keygen -y /복구용_별도_경로/tmdb.agekey
```

`deploy/backup.env.example`을 참고해 운영 서버의0600 환경 파일을 준비한다. 백업용 Django secret은 독립 무작위 값이어도 되며, 실제 AI 키는 필요하지 않다. `DATABASE_URL`의 전용 계정은 필요한 전체 테이블을 읽을 수 있어야 한다. 앱 계정에 복원용 CREATE DATABASE 권한을 부여하지 않고 복구 환경의 별도 계정을 사용한다.

- `BACKUP_DIRECTORY`:0700 임시 암호문/완료 파일 경로.
- `BACKUP_RECIPIENT`:age 공개 recipient. 개인 복호화 키는 백업 명령에 필요 없다.
- `BACKUP_DESTINATION`: `ssh://backup@backup.example.com/srv/tmdb` 또는 `file:///별도/마운트/경로`. SSH는 지정된0600 identity와 known_hosts·BatchMode·엄격한 호스트 키 확인을 사용한다. 원격 Linux의 ssh/scp/sha256sum/find/stat/ln 도구와0700 경로가 필요하다. 원격 계정은 전용 백업 경로만 사용하도록 운영 환경에서 제한한다.
- `BACKUP_RETENTION_DAYS`:기본7일. 성공적으로 전달된 새 백업이 생긴 뒤에만 유효 이름의 오래된 완료 파일을 정리한다. 실패 시 기존 백업을 지우지 않는다. 운영자 파일·다른 이름·심볼릭 링크는 정리하지 않는다.

명령은 `pg_dump → age`로 직접 스트리밍해 백업용 평문 dump를 디스크에 남기지 않는다. 파일 권한은0600, 임시 디렉터리는0700이다. 저장소 전송은 암호문만 사용하고 SHA-256 일치를 확인한 뒤 완료 파일을 공개한다. 계정별 작업이 동시에 실행되면 로컬 파일 잠금으로 중복 실행을 거부한다. 성공 응답의 `delivery_verified`는 전달 무결성을 뜻한다. `offsite_verified=false`는 실제 저장소의 물리적 장애 영역을 도구가 증명하지 않았다는 뜻이다. 같은 서버의 다른 디렉터리나 같은 볼륨 사본을 외부 백업으로 간주하지 않는다.

Linux 운영자가 `deploy/tmdb-backup.service`·`.timer`의 계정/경로를 준비한 후 설치·활성화한다. 현재 Mac에서는 systemd를 설치하거나 활성화하지 않았다. 타이머는 한국03시+최대5분 지연·중단 후 catch-up이며 기본 보관7일이다. 다른 파일 마운트 목적지를 쓰면 service의 ReadWritePaths도 추가한다.

```sh
systemctl start tmdb-backup.service
systemctl status tmdb-backup.service
journalctl -u tmdb-backup.service -n 20
systemctl enable --now tmdb-backup.timer
systemctl list-timers tmdb-backup.timer
```

수동 명령은 보호된 환경변수가 준비된 서버에서 `.venv/bin/python manage.py backup_database`이다. 원문 stderr/비밀번호/DB URL을 출력하지 않고 안정적인 오류 코드와 비0 종료로 실패를 표시한다. 운영 모니터링에서 비0 종료·최근 성공 시각·저장소 용량·키 유효성·별도 복원 결과를 확인한다. 외부 알림은 이번 작업에서 전송하지 않았다. 일일 백업의 데이터 손실 가능성은 대략24시간+지연이며 실패가 누적되면 더 길어진다.

## 별도 DB 복원

외부 저장소에서 암호문을 복구 환경으로 가져오고 해당 시점의 identity를 준비한다. 복구 환경의 `.env`/비밀 관리로 PostgreSQL 연결을 준비한다. 운영 웹/worker/scheduler와 네트워크를 분리한 상태에서 실행한다.

```sh
.venv/bin/python manage.py restore_database --archive /복구/선택한.dump.age --identity /복구/키/tmdb.agekey --target tm_restore_review_20261106
```

도구는 전체 암호문 인증/복호화가 끝난 후에만 `tm_restore_*` 이름의 **새 DB**를 만든다. 잘못된 키·변조 파일은 DB를 만들지 않는다. 기존 DB/현재 원본 DB는 덮어쓰지 않는다. pg_restore 실패 시 이번에 만든 DB를 제거하고 평문 임시 파일을 정리한다. 정상 복원 뒤에도 웹/worker를 자동 시작하지 않는다. 복호화 중 임시 평문을 사용할 수 있으므로 복구 호스트의 디스크 암호화·권한·용량과 강제 종료 시 잔여 파일 정리도 운영자가 확인한다.

복원한 DB에서 계정/비밀번호·현재 할당·상담/AI_APPLIED 출처·재콜/삭제 요청, AI quota/비용 예약/UNKNOWN·이전 결과 graph·분류·게시본·무효화 상태를 검증한다. 이번 자동 테스트는 이 자료를 실제로 채워 암호화→별도 DB 복원 후 전체 테이블 값 해시와 관계를 대조한다. 원본 DB는 수정하지 않는다.

운영에서는 복원된 세션을 폐기하고 복원 시각 이후의 영구 삭제·권한 변경을 신뢰할 수 있는 운영 기록과 대조해 재반영한다. 백업 보관 중인 삭제 자료는 복원하면 재등장할 수 있다. 검증되지 않은 복원 DB를 공개하거나 worker/예약 작업을 켜지 않는다. 검사 통과 후 별도 승인된 배포 절차로 연결 대상을 바꾼다. 이전 이미지·백업·복구 키를 보관 기간 동안 유지한다.

## 로컬 검증과 운영 검증의 구분

P13의 HTTPS는 임시 인증서를 Python 신뢰 저장소로 확인한 실제 로컬 Caddy TLS이다. 브라우저에서는 임시 인증서 오류 허용 설정을 사용하므로 공개 CA 검증을 대신하지 않는다. Chromium/Firefox/WebKit 데스크톱과 WebKit 터치390px를 실행하며 물리 모바일/실제 Edge 기기는 별도다. 20명·1만 고객·실제2 workers×4 threads HTTP 측정은 로컬 가짜 자료와 정해진 요청 패턴이다. 운영 VM의20명 SLA를 인증하지 않는다.

공식 근거: [age 사용법·형식](https://github.com/FiloSottile/age/tree/v1.3.2), [Django 프록시/HTTPS 설정](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header), [Caddy 전달 헤더](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers). 현재 설치 도구와 실제 검증 결과/남은 범위는 [P13 검증 기록](P13_VERIFICATION.md)에 기록한다.
