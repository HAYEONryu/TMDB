# 최초 관리자와 로컬 DB 초기화

기준일: 2026-11-08 KST. 사용자가 현재 PC의 개발 DB와 데모 DB 초기화를 명시적으로 승인했다. 우분투 서버나 외부 DB에는 접속하지 않았다.

## 최초 관리자 동작

- 아이디 `admin`, 초기 비밀번호 `admin123`, 업무 역할 ADMIN, 활성 상태로 생성한다. Django superuser/staff 권한은 주지 않는다.
- 첫 로그인에서 비밀번호를 변경해야 업무 화면/API를 사용할 수 있다. 비밀번호는 해시로 저장한다.
- `ensure_initial_admin`은 계정이 하나도 없는 DB에서만 생성한다. 중복 실행과 동시 시작에도 한 명만 생성한다. 계정이 하나라도 있으면 비밀번호·활성 상태를 포함해 기존 자료를 변경하지 않는다.
- `create_initial_admin`도 인수 없이 실행하면 같은 동작을 한다. 기존 `--phone`/`--name` 방식의 최초 관리자 생성은 유지한다.
- 최초 관리자도 활성 관리자 최대5명에 포함한다. 아이디와 관리자 역할은 고정하며 이름 수정·비밀번호 변경은 가능하다. 다른 활성 관리자가 있을 때 비활성화할 수 있고, 재시작으로 재활성화하지 않는다.
- 다른 계정의 전화번호 형식 검사는 유지한다. `admin`은 관리자 역할에만 허용하는 예약 아이디이며 일반 계정 생성/변경 API에서 새로 차지할 수 없다. DB 제약에도 같은 조건을 적용했다.
- 관리자 비밀번호 재설정 기능에서 이 계정은 `admin123`으로 재설정하고 모든 기존 세션을 종료하며 다시 첫 변경을 요구한다. 다른 계정의 기존 초기 비밀번호 정책은 유지한다.

새 빈 환경은 migration 후 다음 명령을 실행한다.

```sh
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py ensure_initial_admin
```

새 Docker 앱 이미지에는 `deploy/entrypoint.sh`가 포함된다. 기본 Gunicorn 웹 시작 전에 같은 생성 명령을 실행한다. scheduler/AI worker/migration 명령은 그대로 전달한다. entrypoint는 DB 초기화·flush·자동 migration을 하지 않는다. 기존 DB의 migration은 대상과 백업을 확인한 별도 절차로 적용한다.

Git에는 생성 코드·migration·테스트·안내만 포함한다. 실제 DB·비밀번호 해시·키·백업은 포함하지 않는다.

## 이번 초기화 결과

| 대상 | 개발 DB | 데모 DB |
|---|---|---|
| DB 이름 | tm_dev | tm_demo |
| 로컬 포트 | 55432 | 55433 |
| 현재 계정/활성 관리자 | 1명/1명 | 1명/1명 |
| 고객·현장·분배·상담·AI 요청 | 각각0건 | 각각0건 |
| 실제 초기 로그인·필수 변경 요구 | 통과 | 통과 |

각 클러스터의 실제 data_directory와 대상 DB·포트를 검사하고 접속자가 없는 상태에서 작업했다. 양쪽 모두 **암호화 백업 → 서로 다른 임시 DB에 실제 복원 → 모든 public 테이블의 행 수와 값 해시 대조**를 먼저 완료했다. 두 백업의 복원 검사가 모두 통과한 뒤에만 각 대상에 migration·flush·최초 관리자 생성을 적용했다. 임시 복원 DB와 복호화 임시 파일은 제거했다.

현재 PC의 `.local/demo/site.py`도 같은 생성 함수를 사용하도록 변경했다. 데모를 시작해도 예전 데모 직원 계정을 자동 재생성하지 않는다. 이 PC 전용 실행 도구 자체는 계속 Git 제외이며, 서버는 Git에 포함된 관리 명령/entrypoint를 사용한다. 가상 엑셀 예제 파일은 유지되지만 고객 DB에 자동 업로드하지 않는다.

데모 웹/DB를 AI 없이 실제로 두 번 시작·종료했다. 각 실행에서 HTTP health, `admin` 로그인 후 비밀번호 변경 화면 이동, 관리자1명·고객0건 유지를 확인했다. 검증 후 웹과 두 대상 DB는 종료 상태다.

`.env`, `.env.ai`와 `.local/gemini-experiment/`의 누적 실험 기록은 바이트 단위 불변을 확인했다. 실제 AI 호출0회다. 데모의 루트 AI 설정 선택 표식은 `start --no-ai`로 해제했다. **로컬 DB 초기화는 Google 제공자의 사용량이나 한도를 초기화하지 않는다.** AI를 나중에 켤 때 현재 무료 등급과 실제 잔여량을 다시 확인한다.

## 백업과 복구

암호화 백업 두 파일은 아래 Git 제외 경로에 보존했다.

```text
.local/reset-backups/20261108T132150293629Z-bd7645a12f4d4345bd35bd2b264c0e8a/tm_dev.dump.age
.local/reset-backups/20261108T132150293629Z-bd7645a12f4d4345bd35bd2b264c0e8a/tm_demo.dump.age
```

복구 키 파일은 `.local/recovery-keys/20261108T132150293629Z-bd7645a12f4d4345bd35bd2b264c0e8a/identity.agekey`에0600으로 보존했다. 키 내용은 출력하거나 Git에 추가하지 않는다. 백업과 키는 각각 별도로 안전하게 보관해야 한다. 이번 보관은 현재 PC의 로컬 복구용이며 외부 백업이 아니다.

복구 시에는 [운영 문서의 별도 DB 복원](OPERATIONS.md#별도-db-복원) 절차로 선택한 archive와 identity를 사용한다. 먼저 `tm_restore_*` 새 DB에 복원·검증하고, 현재 DB를 덮어쓰거나 복원 직후 AI 작업자를 자동 시작하지 않는다.

## 검증 근거와 재현

서로 다른 영향 검사 **88개**에 최종 통과 근거가 있다. 인증·권한·계정 관리·DB 제약, 최초 관리자 생성·비밀번호 변경·재설정·동시5개 시작, 기존0001→0002 계정 보존, 실제 Chromium 최초 로그인·이름 수정·기존 전화번호 로그인·모바일 입력 흐름을 포함한다. 전체 P13 재인수 결과는 아니다. 각 실행의 소스 SHA를 따로 보존했으며88개를 하나의 실행에서 통과했다고 표시하지 않는다.

| 실행 ID | 결과 |
|---|---|
| 20261108T131539484079Z-eb2746b483b24bacbeee4fc9d7417835 | 83개 중82통과, 신규 테스트의 반환값 tuple 처리 오류1 |
| 20261108T131804274358Z-b14b687f001d44b5b3850c5f171bef8d | 수정 검사·새 브라우저 흐름2통과, 잘못 지정한 기존 검사 이름의 loader 오류1 |
| 20261108T131952546398Z-c9f5edad089740b19215c6d4a21cdea9 | migration·기존 브라우저3통과, 잘못 지정한 UI 검사 클래스의 loader 오류1 |
| 20261108T132145176417Z-265124d576344076a50e25bebb983278 | 정확한 UI 검사 이름으로1통과 |
| 20261108T132150293629Z-bd7645a12f4d4345bd35bd2b264c0e8a | 두 실제 로컬 DB 백업·복원 대조·초기화·로그인 검증 통과 |
| 20261108T132203509784Z-eb200674f5cb4c809db4181540e8666c | Django check·migration 차이0 통과 |
| 20261108T132324224657Z-088859f3eedf43afbe935c09f6bb046a | 실제 데모 두 번 시작·종료·HTTP 로그인·빈 자료 유지 통과 |

검사 코드의 tuple 처리만 수정했다. loader 오류는 존재하지 않는 검사 이름 지정으로 발생했으며 정확한 이름의 검사를 별도 실행했다. 실패 기록은 덮어쓰지 않았다. 결과는 `.local/verification-runs/<실행ID>/`에 있으며 원시 요청 본문·쿠키·고객값은 보존하지 않았다.

새 가상 DB에서의 재현 명령:

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label bootstrap-admin tests.test_bootstrap_admin tests.test_auth tests.test_models tests.test_p4 tests.browser_bootstrap_admin tests.browser_flow tests.browser_p4.P4BrowserTests.test_user_deactivation_transfer_dirty_guard_reset_and_new_user_first_login tests.browser_ui.DoodreamUIBrowserTests.test_login_brand_keyboard_access_and_mobile_readability
.venv/bin/python scripts/run_final_verification.py check --label bootstrap-admin-check
.venv/bin/python scripts/run_final_verification.py stop
```

**남은 확인:** 실제 Docker 이미지 build/운영 Compose 실행은 로컬 Docker 엔진이 없어 여전히 미검증이다. entrypoint 분기·실패 중단은 셸 subprocess로 검증했으며 실제 컨테이너 실행으로 표현하지 않는다. 우분투 서버·공개 HTTPS·실서버 성능은 이번에 검증하지 않았다.
