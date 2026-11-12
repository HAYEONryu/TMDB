# IP HTTPS 준비 검증 기록

확인일: 2026-11-12 KST. [적용·검증·중단·복구 명령](HTTPS_IP_SETUP.md). 변경 전 코드 HEAD는 `72a808a`이며 실행별 source digest·작업 트리 상태는 아래 원본 결과 JSON에 기록한다. 기존 imports 진단 관련 작업 트리 수정은 이번 HTTPS 커밋에 포함하지 않는다.

## 로컬에서 확인한 결과

가상 사용자와 실행별 별도 PostgreSQL 테스트 DB를 사용했다. 외부 Gemini 호출, 공개 ACME 발급, 실제 고객정보, 실제 서버 설정 변경은 수행하지 않았다. 로컬 Docker 엔진이 없어 이미지를 빌드하거나 실제 Compose 컨테이너를 기동한 결과가 아니다.

로컬 Caddy **2.10.2**, Compose CLI **5.7.0**, 프로젝트 `.venv`의 Django·PostgreSQL 격리 검수 도구와 Chromium을 사용했다. 다음 7개 고유 검사는 최종적으로 통과했다.

| 검사 | 확인 내용 |
|---|---|
| 세 Compose 파일 병합 | 가상 server overlay의 공개 8000 제거, 프록시 80·443만 게시, 기존 서명 키/DB URL·DB 볼륨 보존, AI 활성화 값 추가 없음 |
| Caddy 설정 | 명시적인 Let's Encrypt `shortlived` ACME 발급자, IP 기본 SNI, 프록시 프로토콜 헤더 설정, admin 비활성, 로그 request 제거 |
| HTTPS 설정 모듈 | 공개 IPv4 설정의 Django 검사 성공, 스킴 포함/로컬 IP/디버그/데모 설정 거부 |
| HTTPS 앱 흐름 | 가상 직원 로그인, Secure 쿠키, CSRF, 직원 문맥·상담 저장·DB 반영·healthz 성공, 다른 origin 거부 |
| 리다이렉트·호스트 | HTTP에서 HTTPS 이동, HTTPS 반복 리다이렉트 없음, 허용하지 않은 Host 거부 |
| 실제 로컬 TLS 브라우저 | 임시 내부 CA를 사용하는 로컬 Caddy를 통해 로그인 → 고객 조회 → Web Crypto/Web Locks 가능 → 편집 → 저장 완료 |
| 실행 스크립트 | 다른 작업 디렉터리에서 세 파일 순서 유지, 기존 비밀값의 셸 덮어쓰기 해제, HTTPS 프로필 유지 |

브라우저 검사는 **임시 내부 인증서 검증 예외**를 테스트 컨텍스트에만 설정했다. 운영체제 신뢰 저장소에는 CA를 설치하지 않았으며 운영 서버가 공인 인증서를 발급받았다는 증거가 아니다. 운영 확인에서는 `curl -k`나 브라우저 경고 무시를 사용하지 않는다.

## 실행 기록

원본은 `.local/verification-runs/<실행ID>/results.json`과 같은 디렉터리의 시작·종료 기록이다. Git에는 비밀값이나 원시 요청을 넣지 않으며, 원본 실행 기록을 과거 통과 결과로 덮어쓰지 않는다.

- `20261112T133000778257Z-cc084740f0a14bfa8111b0321d82e98f`: 6개 중 5개 통과, 1개 실패. 브라우저 TLS 저장은 통과. 새 API 검사에서 직원 큐 사용자 헤더를 빠뜨려 실패했다.
- `20261112T133225753541Z-a17344c956ea4b3ea1db7a18f9685088`: 위 API 검사 1개 재검사 실패. 문맥 조회의 헤더만 보완했고 저장 요청에는 여전히 누락되어 있었다. 앱 권한 검사는 정상적으로 요청을 거부했다.
- `20261112T133307127671Z-85f32adb94ca43ffbe22057446283b9e`: 실제 브라우저와 같은 큐 헤더를 넣은 API 검사와 새 실행 스크립트 검사 2개 통과. 위 실패는 새 테스트 작성 오류이며 기존 앱 저장 로직을 완화하지 않았다.

- `20261112T133419443031Z-ea5d7a1176994e7b89e8cdd3a5e33876`: 임시 작업 경로를 `tempfile.gettempdir()`로 바꾼 실행 스크립트 검사 1개 통과.

각 실행에서 `source_unchanged_during_run=true`를 확인했다. 문서의 Bash 코드 블록 16개와 실행 스크립트의 구문을 검사했고 변경 산출물 11개에 로컬 비밀 파일의 키·비밀번호·DB URL 값이 포함되지 않았음을 값 출력 없이 검사했다. 테스트용 PostgreSQL은 검증 후 종료했다.

## 재현

```bash
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label ip-https tests.test_ip_https tests.browser_ip_https
.venv/bin/python scripts/run_final_verification.py stop
```

`.local/bin/caddy`, `.local/bin/docker-compose`, Chromium과 격리 PostgreSQL 도구가 준비된 로컬 검수 환경에서 실행한다. `.local` 도구는 Git clone에 포함되지 않으며 새 서버에서 이 경로를 바로 실행할 수 있다고 가정하지 않는다.

## 남은 실제 서버 확인

- 사용자 실제 `compose.server.yaml`과 `.env`의 병합·이미지 빌드·Caddy validate 및 Django 검사. 로컬에서는 비밀값 없는 가상 server 파일로 검증했다.
- 서버 업체/OS 방화벽과 인터넷에서 80·443 도달 여부, 인증기관 요청 성공·발급 제한 여부.
- 실제 공인 IP SAN 인증서의 신뢰·만료일과 향후 자동 갱신. 준비한 설정만으로 발급/갱신 성공 처리하지 않는다.
- 실제 서버 웹 health, HTTPS 직원 로그인·조회·저장, 외부 8000 차단과 재부팅 후 서비스 복구.
- 기존 운영 미확인 사항(별도 DB 권한, 외부 백업, 운영 서버 성능 등). HTTPS만으로 전체 운영 인수 통과를 뜻하지 않는다.

HTTPS 준비 산출물은 **로컬 검증 통과·서버 적용 대기**다. 실제 서비스의 HTTPS 운영 판정은 위 서버 확인이 끝난 후 내린다.
