# v2.0 P1 구현·실행·검증

- 구현·기능 검증: 2026-11-03, Asia/Seoul
- 중단 지점 재개·최종 정리: 2026-11-04, Asia/Seoul
- 범위: [개발 계획](IMPLEMENTATION_PLAN.md)의 P1 환경·키 보호·핵심 스키마·로그인
- 다음 P2 업무 기능은 착수하지 않았다.

## 보존·재사용

착수 초기에는 계획 문서만 보였으나 재확인 중 v1 코드·Git 정보와 계획/진행 문서의 add/add 충돌이 관측됐다. 기존 앱·migration을 보존하고 보완했다. 문서의 양쪽 내용은 `history/*.pre_p1_conflict.txt`, 기존 README/구조 설명은 `history/*.v1_before_p1.txt`에 보관했다. 활성 문서는 v2.0 기준으로 정리했다.

설계서·ZIP 원본은 변경하지 않았다. 명시적 Git reset·merge --continue·push, ZIP 일괄 덮어쓰기, sources/다른 프로젝트 수정은 수행하지 않았다. 실제 개인정보·실제 AI 키·유료 호출·운영 자원·배포를 사용하지 않았다.

## 구현 범위

- 기존 핵심 모델·부분 unique/상태 CHECK/FK·공통 쓰기 잠금·인증·역할·비밀번호/세션 서비스를 보존하고 재검증했다.
- ConsultationRevision과 추가 migration: 고객/할당·실제 actor·시각·버전·변경 전후·notes·source·인덱스·DB 제약. 과거 이력 자동 생성 없음.
- 기존 ignore 규칙에 환경 파일 제외·빈 예시 예외·secrets/백업 제외를 병합했다. 실제 .env.ai는 0600, 예시는 빈 키다.
- web/AI worker만 읽는 명시 로더, 환경변수 우선·파일 보완, AI_ENV_FILE, 미설정/권한/모델/단가 오류 fallback. 일반 관리/scheduler/test는 상속 AI 환경 제거·파일 미로딩.
- 가용 상태 API는 생성 false·미구현 사용량 null. P1에는 유료 provider SDK/생성 전송 경로가 없다.
- fake는 전용 TESTING 설정+테스트 DB에서만 실행하고 is_test를 표시한다. 일반 로더는 fake 선택을 거부한다.
- 키 repr 비노출, 안전한 응답 필드, 앱/Django 메시지·인자·traceback 마스킹.
- Compose web/AI worker만 AI env_file 수신. worker/scheduler는 이 단계에서 DB 연결 점검만 한다.

## 실행 결과

| 실행 | 결과·실제 범위 |
|---|---|
| Python | 공식 3.13.18 소스 SHA-256 확인 후 프로젝트 내부 빌드. 시스템 Python·공용 venv 보존 |
| uv frozen sync | 기존 lock 유지, Django 5.2.18·psycopg 3.3.7·Playwright 1.64.1 등 설치 |
| PostgreSQL | 프로젝트 내부 17.11, loopback 55432. tm_dev/test_tm_dev 분리 |
| migrate/재실행 | 기존 전체와 consultations 0001 적용 / No migrations to apply |
| check / makemigrations --check / migrate --check | 문제 0 / No changes detected / 적용 누락 없음 |
| `manage.py test tests --noinput -v 2` | **75개 통과**. 기존 기록 승계 없이 현재 전체 재실행 |
| `manage.py test tests.browser_flow --noinput -v 2` | **Chromium 흐름 1개 통과**. 실제 HTTP/PG·기본 해시 사용 |
| 가짜 seed | 관리자 1·직원 2 생성, 초기 dodream/변경필수·비-superuser |
| scheduler --once / run_ai_worker | 각각 연결 정상. 새 업무/AI 작업과 외부 AI 호출 없음 |
| Gunicorn | 127.0.0.1:8000 실제 기동. DB health·로그인·Bootstrap 각각 HTTP 200 |
| 실제 Git | .env.ai 제외·비추적 / .env.ai.example 비제외. 값 출력 없이 파일명 검사 |
| 파일 권한 | .env.ai 0600 |
| 공식 Compose | 공식 SHA-256 검증한 5.7.0 단독 파일을 프로젝트 내부 설치 |
| 실제 Compose parser | config --quiet와 ai/proxy 포함 5서비스 정규화 검사 통과. web/AI worker만 AI_API_KEY 이름 수신. 값 출력 없음 |
| 화면 확인 | PC/390px 스크린샷 직접 확인. 가로 넘침 없음, JS 오류·외부 CDN 요청 없음 |
| 재개 후 최종 검사 | 원본 해시·활성 문서 충돌/링크/공백·키 제외/0600·Compose 경계·Python/JS 구문 정상. check/마이그레이션 상태·가짜 3계정 초기 변경필수·관리 명령 AI 키 미로딩 재확인 |
| 프로세스 정리 | 2026-11-04 Gunicorn master/worker 및 전용 PG 정상 종료, exit 0. 개발 데이터 보존 |

인증/모델 일부 테스트는 테스트 전용 MD5로 빠르게 실행한다. 별도의 실제 PBKDF2 검사와 브라우저 흐름은 런타임 해시를 사용하며 운영 해시는 낮추지 않았다. 브라우저 테스트는 별도 DB를 사용해 개발 계정 비밀번호를 변경하지 않는다.

## 검증한 동작

전화 정규화·로그인·최초 변경 전 업무 차단·비밀번호 검증·역할/CSRF·최초 관리자/seed·본인 변경·재설정의 기존 세션 차단·비활성화/재활성화·역할 변경·마지막 관리자 동시 보호·잘못된 세션 ID 거부를 검증했다.

모델 검수는 현장/전화·할당·재콜·삭제 요청·receipt/job unique·상태 CHECK·순환 FK·본문 보존·비활성화 회수·독립 PG advisory lock·timeout/제한 재시도·상담 revision의 actor/시각/timestamptz/버전/source/관계·CASCADE를 포함한다.

설정/보안 검수는 역할별 파일 로딩, 환경변수/빈 값 우선순위, 외부 경로·0600·모델/단가 오류, 일반 env의 AI 값 제외, fake의 일반 설정/DB 차단과 무네트워크/is_test, repr/응답/정적 코드/실제 로그 handler/예외 마스킹을 포함한다. 실제 키 대신 일시적 비밀이 아닌 sentinel을 사용했다.

브라우저에서는 관리자·직원 최초 변경→역할 화면/권한→두 직원 세션→관리자 reset→기존 세션 거부→다시 최초 변경, AI 비활성 상태와 모바일 로그인 화면을 확인했다.

원시 로그는 `.local/p1-tests.log`, `.local/p1-browser.log`, 스크린샷은 `.local/qa/`에 있다. 이전 v1의 테스트 결과를 현재 통과 수치로 사용하지 않는다.

## 준비 중 오류와 해결

- Python 3.9 tarfile의 filter 인자 미지원으로 첫 해제 시도가 실패했다. 공식 해시 확인 후 시스템 tar로 해제하고 Python 3.13.18을 빌드했다.
- 기본 샌드박스의 로컬 PG 조회 권한 경고는 필요한 로컬 검증 명령에만 권한 확장하여 실제 연결·migration·테스트로 확인했다.
- 문서 병합 충돌은 양쪽 원문을 보관하고 활성 v2 문서로 정리했다. 중단된 문서 갱신 패치는 현재 파일 내용을 다시 확인한 뒤 적용했다.

## 미실행·다음 단계

Docker 엔진이 없어 **이미지 build·컨테이너 up·이미지 history/각 레이어의 sentinel 검사**는 미실행이다. Compose 설정 파싱을 이미지 키 미포함의 최종 증거로 보고하지 않는다.

실제 provider·유료 모델 품질·실제 과금·운영 HTTPS·백업/별도 복원·전체 92개 인수 검수는 미실행이다. 현재 키 없이 계정 기능과 health는 동작하지만 전체 고객관리 UI가 완료됐다는 뜻은 아니다.

상담 revision의 저장 서비스 연동과 관리자 현장/DB 그리드·필터/페이지·수동 저장·삭제/복구는 다음 P2 범위다. AI 전체와 한도/비용 집행은 P9 이후이며 이번에는 시작하지 않는다.
