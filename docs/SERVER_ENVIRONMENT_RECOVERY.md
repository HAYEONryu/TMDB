# Docker 환경변수 누락과 기존 SECRET_KEY 복원

2026-11-09 KST. 서버 소스가 `ae64561`인데 기존 컨테이너에서는 고객 migration이 `0001_initial`만 표시됐다. 새 이미지를 빌드한 뒤 관리 명령은 `DJANGO_SECRET_KEY` 누락으로 DB 연결 전에 중단됐다. 두 Compose 파일을 합친 설정에서도 web·scheduler·ai_worker 모두 키 누락, DATABASE_URL 설정됨이 확인됐다. 실제 등록 실패의 전체 원인은 아직 확정하지 않았다.

이 서버의 Compose 파일은 `/root/TMDB/compose.yaml`과 `/root/TMDB/compose.server.yaml`이다. 현재 작동하는 기존 스케줄러 `tmdb-scheduler-1`의 설정에서 원래 키를 얻어 복구한다. 키를 새로 생성하면 기존 세션과 암호화된 직원 대기 자료에 영향을 줄 수 있으므로 교체하지 않는다. `.env`를 이미지에 다시 포함시키지 않는다.

## 기존 키 복원

### 읽기 전용 설정 진단

복구 후에도 세 서비스에서 키가 누락되면 다음 명령으로 설정 구조만 확인한다. 호스트 Python에는 Django가 필요 없다.

```sh
cd /root/TMDB
python3 scripts/recover_runtime_secret.py --diagnose
```

`--diagnose`는 환경 파일을 수정하거나 원본 컨테이너에서 키를 읽지 않는다. Compose 설정을 내부에서 읽어 셸 키 설정 유무, 서비스별 inline 키의 설정 형태, 환경 파일 이름과 프로젝트 `.env` 포함 여부만 출력한다. 실제 키·환경변수 값·전체 Compose 설정은 출력하지 않는다. `environment`가 맵형이거나 `KEY=value` 목록형인 경우를 모두 처리한다. 이전 수동 진단 명령은 목록형 설정에서 `AttributeError`로 중단됐으므로 이 명령으로 대체한다.

### 복원 실행

```sh
cd /root/TMDB
git pull --ff-only
unset TM_SERVER_SECRET TM_DB_PASSWORD
python3 scripts/recover_runtime_secret.py --source-container tmdb-scheduler-1 \
  --reference-variable TM_SERVER_SECRET --database-password-variable TM_DB_PASSWORD
```

이 명령은 호스트의 Python 표준 라이브러리만 사용한다. 호스트에 Django나 pip 패키지를 추가하지 않는다. 원래 컨테이너의 Django 설정을 management 역할로 읽으며 DB 연결·AI 요청은 수행하지 않는다. 키와 환경 파일은 subprocess의 비공개 입출력으로만 처리하고 출력에는 상태·설정 확인 대상·백업 위치만 넣는다.

`unset TM_SERVER_SECRET TM_DB_PASSWORD`는 현재 셸의 덮어쓰기만 제거해 프로젝트 `.env`에서 참조 변수를 읽도록 한다. 환경 파일이나 실행 중인 컨테이너의 기존 키·DB 비밀번호를 지우지 않는다.

도구는 다음을 수행한다.

1. 원본 컨테이너의 Compose 파일 경로가 현재 프로젝트와 같은지 검사한다.
2. 기존 스케줄러가 실제 사용하는 SECRET_KEY를 읽는다. 키 값은 화면이나 명령 인자에 출력하지 않는다.
3. 새 `.local/runtime-secret-recovery-<UUID>/` 디렉터리(0700)에 현재 `.env`를 `app.env.before`(0600)로 백업한다. 이 경로는 Git·Docker 빌드 컨텍스트 제외 대상이다.
4. 기본 모드는 `.env`의 DJANGO_SECRET_KEY를 기존 키로 설정한다. `--reference-variable TM_SERVER_SECRET`을 지정하면 실제 Compose 참조가 세 서비스 모두 이 이름과 일치하는지 확인한 뒤 DJANGO_SECRET_KEY와 TM_SERVER_SECRET에 같은 기존 키를 설정한다. 관련 없는 설정은 유지하며 지정한 참조 변수에 다른 값이 이미 있으면 덮어쓰지 않는다. `.env` 권한은 0600으로 설정한다.
5. 실제 `docker compose ... config`를 내부에서 읽어 web·scheduler·ai_worker에 같은 키가 전달되는지 비교한다. 전체 설정이나 키는 출력하지 않는다. 검사 실패 시 기존 `.env` 내용과 권한을 복원한다.

성공 상태는 `restored_existing_secret`이다. 이미 같은 키가 설정되어 있으면 `already_configured`로 종료하며 기존 백업을 덮어쓰지 않는다. 다른 키가 이미 설정되어 있으면 덮어쓰지 않고 중단한다. 병렬 실행과 작업 중 환경 파일 변경도 검사한다.

`VERIFY_FAILED_ORIGINAL_ENV_RESTORED`이면 기존 `.env`로 돌아간 상태다. 아래 수정 이력의 검증 오류가 수정된 최신 도구를 사용한다. 여전히 실패하면 `details.services`의 `missing`·`different`·`matches_existing`만 확인한다. 실제 키는 출력하지 않는다. `compose.server.yaml`이나 셸 환경에서 키를 빈 값으로 덮어쓰는 경우에도 같은 상위 오류 코드가 발생할 수 있으므로, 이 코드만으로 서버 설정 오류를 확정하지 않는다. `SOURCE_COMPOSE_PROJECT_MISMATCH`이면 원본 컨테이너를 잘못 지정했을 수 있다. `DOCKER_COMMAND_FAILED`이면 원본 컨테이너 실행 상태나 Docker 접근을 확인한다. 원본 컨테이너·이미지·볼륨을 삭제하거나 임의의 새 키로 대체하지 않는다. 원시 `.env`·Compose 전체 설정·컨테이너 환경값을 채팅에 보내지 않는다.

## 복원 후 확인

성공한 경우 새 이미지에서 읽기 전용 확인을 실행한다.

```sh
docker compose -f compose.yaml -f compose.server.yaml \
  run --rm --no-deps web python manage.py showmigrations customers
```

새 migration이 포함되어 있고 아직 적용하지 않았다면 `[ ] 0002_customer_metadata`가 표시돼야 한다. 이 도구는 서비스 재시작이나 DB migration을 수행하지 않는다. 실제 적용은 [대상 DB 백업·migration·재시작 절차](EXCEL_TEMPLATE_GUIDANCE.md)로 이어가며 대상·백업·복구 방식을 먼저 확인한다. 기존 AI 활성화와 무료 등급 확인 설정을 바꾸지 않는다.

## 검증 범위

가상 설정으로 9개 검사 통과: 기존 키 유지·다른 설정 보존·비공개 백업과 권한·재실행·다른 키 덮어쓰기 거절·다른 프로젝트 거절·검증 실패 원복·편집 경합·비밀값을 포함한 오류 출력 차단·심볼릭 링크 거절을 포함한다. 원본 컨테이너에서 실행할 코드도 별도의 가상 Django 설정으로 실행해 특수문자 키와 여러 줄 환경값 보존을 확인했다.

```sh
.venv/bin/python -m unittest tests.test_runtime_secret_recovery
```

로컬 Docker 엔진이나 실제 우분투 서버에서 이 도구를 실행한 결과는 아직 없다. 실제 서버 복원 성공과 DB 등록 성공은 사용자 실행 결과로 별도 확인한다. 기존 고객 기능 검수 결과를 이 환경 복구의 성공 증거로 재사용하지 않는다.

가상 검증 실행 ID: `20261109T120912772801Z-87ed3e43327d407e8d0559d11f61b546`. 결과는 `.local/verification-runs/<실행ID>/`에 보존한다.

## 실제 Compose 출력 검증 보완

최초 도구 실행에서 서버는 `VERIFY_FAILED_ORIGINAL_ENV_RESTORED`를 반환했다. 이후 실제 Compose CLI로 가상 키를 검사해 도구의 비교 오류를 재현했다. `docker compose config --format json`은 리터럴 `$`를 `$$`로 표시한다. 최초 도구는 이 출력 표현을 실제 키와 그대로 비교해 잘못 실패할 수 있었다. 비교 전에 이 표현을 한 번 해석하도록 수정했다. Python-dotenv와 Compose가 역슬래시를 처리하는 차이도 검사해 양쪽에서 기존 값을 유지하는 단일 인용 표현을 우선 사용한다. 유효한 표현을 확인할 수 없으면 성공으로 처리하지 않고 원래 환경 파일을 보존한다.

수정본은 가상 단위 검사와 실제 Compose CLI 5.7.0의 환경 파일 해석·JSON 출력을 포함해 **19개 검사 통과, 건너뛰기 0개**다. `$`·`$$`·`$$$`·따옴표·역슬래시가 있는 가상 키의 보존, 빈 inline 환경값에 의한 진짜 실패와 원복, 비밀값 없는 진단을 포함한다. 실제 Compose 검사는 Docker 엔진이나 컨테이너 실행 없이 수행했다. 서버의 이번 실패가 같은 원인인지는 서버 키를 보지 않았으므로 확정하지 않으며, 수정본 재실행 결과로 확인한다. 앞선 9개 가상 검사 기록은 당시 결과로 보존한다.

수정 검증 실행 ID: `20261109T132016414651Z-f0199443af214358a8f55a44644ac3d8`. 기존 실행 산출물을 덮어쓰지 않고 별도 디렉터리에 보존했다.

목록형 환경설정 진단 보완 후에는 실제 Compose 목록형·맵형 해석과 읽기 전용 동작·값 비노출을 포함해 23개 검사 통과, 건너뛰기 0개다. 실행 ID는 `20261109T132845318179Z-b2b28d56f17f4b3fb65b5c06a91a16e3`이며 이전 19개 검사 기록도 보존한다. 실제 서버의 키 누락 원인과 복구 성공은 `--diagnose` 및 서버 재실행 결과로 계속 확인해야 한다.

## 서버에서 확인한 변수명 불일치

추가 사용자 확인 결과 세 서비스의 DJANGO_SECRET_KEY는 모두 TM_SERVER_SECRET을 참조했다. 초기 복구 도구가 `.env`의 DJANGO_SECRET_KEY만 설정해도 이 참조 변수는 채워지지 않으므로, Compose의 inline 환경값이 빈 값으로 덮어쓸 수 있다. 이 서버의 현재 복구 명령은 위의 `--reference-variable TM_SERVER_SECRET` 포함 명령이다. 다른 서버에 같은 변수명을 임의로 적용하지 않는다.

참조 이름은 단순 변수 표현에서 이름만 추출하며 기본값·실제 키는 출력하지 않는다. 복구는 명시한 SECRET 계열 변수명이 세 서비스의 실제 참조와 모두 일치할 때만 진행한다. DATABASE_URL 같은 다른 설정을 복구 대상으로 지정하거나, 다른 키가 이미 설정되어 있으면 중단한다. 새 키를 생성하지 않으며 Docker Compose 파일도 변경하지 않는다.

실제 Compose CLI에 동일한 `DJANGO_SECRET_KEY=${TM_SERVER_SECRET:-}` 설정을 구성해 기존 키의 양쪽 이름 복원·세 서비스 전달·기존 기타 설정 보존·재실행·원본 백업을 검증했다. 실제 서버의 환경 복구 및 등록 성공은 사용자 실행 결과로 별도 확인한다. 이 설정 문제의 원인 확인은 최초 고객 등록 실패의 모든 원인을 확정했다는 뜻이 아니다.

참조 변수 보완 후 26개 검사 통과, 건너뛰기 0개다. 최종 실행 ID는 `20261109T134736288187Z-ff664bd3565a43328ac4033a8a7bd874`이며 앞선 실행 `20261109T133813278343Z-83d40162b51349e5a09115d4166a1497`도 별도 보존했다. 실제 서버 데이터·Docker 엔진·외부 AI 요청은 이 가상 검증에 사용하지 않았다.

## DB 비밀번호 참조 복구

앱 키 복구 뒤 사용자 로그에서 `fe_sendauth: no password supplied`를 확인했다. 사용자가 비밀값 없이 확인한 결과 세 서비스의 DATABASE_URL 비밀번호 부분은 모두 TM_DB_PASSWORD를 참조했다. 이 서버의 현재 복구 명령에는 위의 `--database-password-variable TM_DB_PASSWORD`도 포함한다.

도구는 같은 기존 컨테이너의 Django DB 설정에서 이미 사용하는 비밀번호를 비공개 입출력으로 읽는다. 명시한 PASSWORD 계열 변수명이 세 서비스의 URL 비밀번호 참조와 일치해야 한다. `.env`에 기존 비밀번호를 복원하며 PostgreSQL 역할 비밀번호를 바꾸거나 SQL을 실행하지 않는다. 앱 키가 이미 정상이어도 DB 비밀번호 복구는 따로 검사한다.

수정 전후의 유효 DATABASE_URL을 기존 컨테이너의 DB 호스트·포트·DB명·사용자와 비교한다. 연결 대상이 다르거나 다른 비밀번호가 이미 설정되어 있으면 중단한다. 복원 후 해석된 비밀번호까지 기존 설정과 같은지 검사하고 실패하면 원래 `.env`로 돌아간다. URL에 그대로 넣을 수 없는 특수문자로 값이 달라져도 성공으로 처리하지 않는다. `database_settings_match_source=true`는 이 설정 비교를 뜻하며 실제 인증·접속 성공을 뜻하지 않는다. 실제 연결은 다음 읽기 전용 `showmigrations` 실행 결과로 확인한다.

키·비밀번호·DB URL 전체는 화면이나 오류에 출력하지 않는다. 앱 외부 AI 설정은 바꾸지 않으며 서비스·DB를 재시작하거나 migration을 적용하지 않는다. 기존 `.env` 백업은 앞과 같은 고유 디렉터리와 0600 권한으로 보존한다.

실제 Compose 설정 해석을 포함한 33개 가상 검사에서 비밀번호 복원·키가 이미 정상인 상태·대상 변경 거절·다른 값 보존·원래 비밀번호 미확인 시 중단·URL 특수문자 실패 원복을 확인했다. 실제 서버 비밀번호나 DB 연결은 이 검사에 사용하지 않았다.

검증 실행 ID: `20261109T141840324525Z-a4676e390b2c4c1ca3bc099cbe21e552`. 이전 환경 복구 검사 기록은 각각의 실행 디렉터리에 보존한다.
