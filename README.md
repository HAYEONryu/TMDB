# 두드림 TM 고객관리

현재 실행·운영 준비의 단일 기준은 [현재 운영 기준](docs/CURRENT_OPERATING_BASELINE.md)입니다. **Gemini3.5 Flash-Lite 무료 전용·유료 승인 $0·직원 AI 합산 KST 하루40회·활성 직원20명/관리자5명**이며 프로젝트 전체 제공자 한도가 개인 상한보다 우선합니다. **AI 비활성·무료확인false를 유지**합니다.

RPD500·RPM15·입력 TPM250,000은 현재 계정에서 재확인되지 않은 이전 기록값입니다.500회라면 직원20명의40회 전체 사용(800회)을 보장할 수 없습니다. 실제 고객정보 사용·외부 서버 배포·구매·유료 호출은 이번 단계에 포함하지 않습니다.

관리자 현장/엑셀/분배·회수/고객·계정/삭제 승인/휴지통, 직원 상담 저장·오늘 및 지난 재콜·삭제 요청,23시 미진행 자동 회수와 선택형 AI 보조가 구현되어 있습니다. Python3.13/Django5.2/PostgreSQL17을 사용합니다.

## 격리 검수 시작

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label operations-stage1 tests.test_stage1_evidence tests.test_acceptance tests.test_free_ai_migration
.venv/bin/python scripts/run_final_verification.py stop
```

같은 label을 재사용해도 실행 ID·디렉터리·테스트 DB는 새로 생성됩니다. 결과는 `.local/verification-runs/<실행ID>/`의 `started.json`, `finished.json`, `results.json`, 구조화 로그와 테스트별 산출물로 보존합니다. 원시 요청/쿠키/비밀번호/고객정보가 들어갈 수 있는 stdout·예외 본문은 저장하지 않습니다. [네트워크 진단·증거 형식](docs/CURRENT_OPERATING_BASELINE.md)을 확인하세요.

Docker 실기 검수는 로컬 엔진이 있을 때만 실행합니다. 엔진이 없으면 미검증으로 남습니다.

```sh
.venv/bin/python scripts/verify_docker_release.py --label docker-stage1
```

## 로컬 가상 시연

아래는 **현재 PC의 가상자료용 데모** 실행 방법입니다. `.local/demo/site.py`와 기존 데모 설정·PostgreSQL17이 준비된 환경에서 사용합니다. `.local`은 Git 제외이므로 새 checkout에 이 도구가 있다고 가정하지 않습니다. 실제 운영 서버의 Docker 절차는 [운영 문서](docs/OPERATIONS.md)를 사용하세요.

**`start`와 `restart`는 데모 DB에 migration도 실행합니다.** 기존 DB에 미적용 migration이 있으면 실행 전에 대상·백업·복원 방식을 확인하세요. AI 작업자나 스케줄러가 이미 실행 중이면 아래 종료 순서로 먼저 종료한 뒤 재시작합니다.

### AI 없이 시작

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py start --no-ai
```

웹이 이미 실행 중이라면 `start --no-ai` 대신 `restart --no-ai`를 사용합니다. 접속 주소는 **http://localhost:8010/auth/login** 입니다. 데모 DB는 `tm_demo`, 포트는 `55433`이며 아래 새 환경의 `8000` 포트와 구분합니다.

### AI 포함 시작 전 준비

현재 운영 기준은 **`AI_ENABLED=false`, `AI_FREE_TIER_CONFIRMED=false` 유지**입니다. 다음은 무료 확인과 별도 활성화 승인을 마친 뒤 사용하는 절차이며, 이 안내를 추가했다고 AI가 활성화되는 것은 아닙니다.

1. Google AI Studio에서 해당 프로젝트의 무료 등급·결제 미연결, 정확한 모델 사용 가능 여부, 현재 RPM·입력 TPM·RPD와 잔여량, 다른 앱의 공용 사용량을 확인합니다. 이전 RPD500·RPM15·입력 TPM250,000을 현재 확인값으로 복사하지 않습니다. 무료 사용을 확인할 수 없으면 비활성을 유지합니다.
2. 보호된 `.env.ai`에 `AI_PROVIDER=gemini`, `AI_MODEL=gemini-3.5-flash-lite`, `AI_USAGE_TIER=free`, `AI_MONTHLY_BUDGET_USD=0`과 실제 확인한 프로젝트 ID·한도를 설정합니다. 키는 `AI_GEMINI_API_KEY`에만 보관하며 파일 권한은 `0600`이어야 합니다. 기존 파일을 예시로 덮어쓰거나 키를 채팅·명령 인수·Git·로그에 넣지 않습니다.
3. 무료 확인과 활성화가 승인된 후에만 `AI_FREE_TIER_CONFIRMED`와 `AI_ENABLED`를 활성화합니다. 자세한 조건은 [AI 설정·키 관리](docs/AI_ACTIVATION.md)를 따릅니다. 유료 전환이나 다른 모델로 자동 전환하지 않습니다. 이 데모에서는 가상자료만 사용합니다.

### AI 포함 시작 순서

터미널 1에서 웹·DB를 시작하거나 재시작합니다. `--ai`는 루트 `.env.ai` 사용을 선택하는 옵션이며 무료 확인·활성화 설정을 대신하지 않습니다.

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py restart --ai
```

브라우저에서 **http://localhost:8010/auth/login** 에 접속합니다. 웹·DB가 준비된 뒤 터미널 2에서 AI 작업자를 실행합니다.

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py worker
```

23시 자동 회수와 만료 자료 정리를 사용하려면 터미널 3에서 같은 데모 DB를 사용하는 스케줄러를 실행합니다. AI 없이 실행할 때도 자동 회수에는 이 과정이 필요합니다.

```sh
cd /Users/hayeon/Documents/TMDB
PYTHONPATH="$PWD/.local/demo:$PWD" DJANGO_SETTINGS_MODULE=demo_settings \
  .venv/bin/python manage.py run_scheduler
```

AI 작업자와 스케줄러 터미널은 실행 상태로 유지합니다. PC가 종료되거나 절전 상태가 되면 정상 처리를 보장할 수 없습니다. 웹·DB 상태는 다음으로 확인할 수 있습니다. 이 상태 명령은 AI 작업자·스케줄러 실행 여부나 실제 AI 응답 성공을 확인하는 명령은 아닙니다.

```sh
.venv/bin/python .local/demo/site.py status
```

### 종료·재시작

1. 화면에서 저장 완료를 확인하고 새 AI 요청을 중단합니다.
2. AI 작업자 터미널에서 **Ctrl+C**를 누르고 현재 처리와 프로세스 종료를 기다립니다.
3. 스케줄러 터미널에서도 **Ctrl+C**를 누르고 종료를 기다립니다.
4. 마지막으로 웹·DB를 종료합니다.

```sh
cd /Users/hayeon/Documents/TMDB
.venv/bin/python .local/demo/site.py stop
```

데모 데이터는 보존됩니다. **브라우저만 닫으면 서버는 종료되지 않으며, `site.py stop`은 별도로 실행한 AI 작업자와 스케줄러를 종료하지 않습니다.** 다시 AI까지 사용하려면 위 시작 순서대로 실행합니다.

AI를 비활성화하고 고객관리만 계속 사용하려면 먼저 AI 작업자를 종료하고, 보호된 `.env.ai`의 `AI_ENABLED=false`를 설정한 뒤 다음으로 웹·DB를 재시작합니다. 스케줄러도 먼저 종료한 후 필요하면 다시 실행합니다.

```sh
.venv/bin/python .local/demo/site.py restart --no-ai
```

## 새 환경 준비

새 환경은 `uv.lock`/`requirements.lock`의 의존성, PostgreSQL17, 보호된 `.env`와 비활성 `.env.ai`를 준비합니다. **승인된 새 빈 DB에 한해서** migration/collectstatic/최초 관리자 생성 후 실행합니다. 기존 비밀 파일·DB를 예시로 덮지 않습니다.

```sh
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py create_initial_admin
.venv/bin/gunicorn config.wsgi:application --config gunicorn.conf.py --worker-class gthread --threads 4
# 별도 터미널
.venv/bin/python manage.py run_scheduler
```

로컬 접속은 `http://127.0.0.1:8000/auth/login`, DB health는 `/healthz`입니다. 종료 시 앱·scheduler를 먼저 종료하고 해당 DB 관리 도구로 DB를 종료합니다. 초기/재설정 비밀번호는 변경 전 업무 API가 차단됩니다. 실제 운영에서 가상 seed·개발 DB 자격증명을 사용하지 않습니다.

## 문서와 과거 기록

- [현재 운영 기준·미확인 환경·다음 결정](docs/CURRENT_OPERATING_BASELINE.md)
- [운영·배포·백업·복원](docs/OPERATIONS.md)
- [AI 비활성·키 관리](docs/AI_ACTIVATION.md)
- [crypto.randomUUID 오류 수정·서버 정적 파일 적용](docs/REQUEST_ID_COMPATIBILITY.md)
- [HTTP 환경 전체 점검·직원 HTTPS 조건·도메인 없는 접속 방법](docs/HTTP_ENVIRONMENT_AUDIT.md)
- [운영 준비1단계 결과](docs/OPERATIONS_STAGE1.md)
- [이전 최종 검수](docs/FINAL_VERIFICATION.md)·[당시92문항](docs/FINAL_ACCEPTANCE.md)
- [이전 시작 안내 원문](docs/history/README.before_operations_stage1_20261108.md)

과거 보고서는 당시 모델·한도·코드·결과의 역사적 증거입니다. 현재 설정 안내로 복사하지 않습니다. 과거 유실 원시 로그는 복구 불가이며 새 실행 기록과 구분합니다.
