# P3 엑셀 업로드 검증

실행일2026-11-04, `/Users/hayeon/Documents/TMDB`. 기준은 v2.0 설계서12장·13.7·18.2와 개발 계획 P3다. 프로젝트 docs의 설계서 해시는 기존 `0c2f3326868454aa654c0d367b5ec7b75e3ecd4f80510fb3c96fbae0657e6194`와 동일하며 수정하지 않았다. Downloads의 이전 원본/ZIP 경로는 현재 없어 ZIP의 최종 재해시는 미실행이다.

## 구현과 정책 구분

| 구분 | 적용값 |
|---|---|
| 사용자 업무 규칙 | 이름·전화 일반 수정 금지, 기존 상담 보존, 관리자 권한·첫 비밀번호 변경·CSRF, 가짜 자료만 사용 |
| 설계서 형식 | 첫 워크시트, 정확한9열 이름/순서, 담당직원 빈 값, 고객명/텍스트 전화 필수, 빈 계약=미확인 |
| 설계서 형식 | 수식/매크로 거부, 숫자 연락처 0 임의 복원 금지, 빈 행 제외·원본 행 번호, KST 날짜+시각·요일 재계산 |
| 설계서 기본값 | xlsx10MiB·10,000데이터 행, 후보/검증 결과24시간, idempotency7일, 기존 중복은 휴지통 포함 |
| P3 구현 기본값 | ZIP 구성원 최대1,000·압축 해제 합계128MiB. 희소 XML 행/열은 Excel 최대 범위를 검사하고 파싱 폭은9열로 제한 |
| P3 구현 기본값 | 결과 페이지100행. 결과는 모든 관리자에게 공유하며 직원에게는 API도 거부 |
| P3 날짜 해석 | Excel 셀은 날짜·시각이 함께 표시되는 서식, 문자열은 YYYY-MM-DD HH:mm 및 한글 요일 표시를 앞/뒤에 허용. 날짜만 있는 값은 행 오류 |
| P3 실패 정책 | 치명 DB 오류는 전체 롤백→FAILED·후보 제거·재업로드, 같은 key는 같은 실패. 잠금/연결 오류는503·같은 key 재시도 |
| P3 보관 정책 | 확정/FAILED 후보 즉시 제거. 행 원문은 검증부터24시간, batch 집계는 그 뒤7일. 기존 유효 key 결과는 접수 기준 최소7일, 검증 만료+7일 상한 |
| P3 정리 정책 | 만료 경계부터 GET에서 원문을 숨김. scheduler60초/cleanup_imports가 실제 삭제. 최대50 batch씩, 등록 고객/상담은 보존 |
| P3 성능 기준 | 가짜1만 행 전체<30초·프로세스 peak RSS<512MiB·쓰기 잠금 구간<10초. 이번 로컬 검수 기본값이며 운영 SLA가 아님 |

빈 양식의 열은 **담당직원명 / 고객명 / 고객 연락처 / 통화결과 / 방문예약 날짜 / 계약여부 / 상담기타내용 / 재콜일정 / 주택상황**이다. 시스템 열과 고객 데이터는 포함하지 않는다.

원본 파일은 메모리/임시 파일에서만 읽고 검증 후 close한다. ZIP 파일을 디스크에 풀지 않고, `read_only=True, data_only=False, keep_links=False`와 defusedxml을 사용한다. 파서 경고에 원문이 실리지 않도록 처리하고 입력 오류는 관리자 행 결과로만 표시한다. openpyxl3.1.5·defusedxml0.7.1·et-xmlfile2.0.0과 해시를 lockfile에 고정했다. [openpyxl 보안 안내](https://openpyxl.readthedocs.io/en/stable/#security), [read-only 안내](https://openpyxl.readthedocs.io/en/stable/optimized.html).

## 실제 실행

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.performance_imports --noinput -v 2
.venv/bin/python manage.py run_scheduler --once
.venv/bin/python manage.py cleanup_imports
.venv/bin/python manage.py collectstatic --noinput
```

최종 **138개 통과,26.089초**. 서버132개(기존105+P3 27)·실제 Chromium5흐름(기존3+P3 2)·성능1개. PostgreSQL17.11 `test_tm_dev` 생성/삭제, Python3.13.18·Django5.2.18. 개발 고객65·import batch0을 유지했다.

| 검수 | 근거/결과 |
|---|---|
| 권한·CSRF | 직원/최초 변경 미완료의 템플릿·검증·결과·확정 차단, 실제 multipart·CSRF 없는 요청 거부 |
| 양식·파일 | 빈9열/연락처 텍스트, 다른 헤더/순서 전체 거부, 첫 시트만·숨긴 다른 시트 무시, 빈 행 제외·원본 행 번호 |
| 행 검증 | 담당직원·전화 숫자/+82/잘못된 앞번호·필수/길이/enum·수식·Excel 오류·시각 없는 날짜·UTC 범위 오류를 행 실패로 처리 |
| 날짜 | Excel datetime, 한글 요일 표시 문자열, 잘못 적은 요일은 버리고 실제 날짜 유지, KST→UTC 일시 |
| 중복 | 앞선 형식 오류는 번호를 예약하지 않음, 첫 유효 행만 후보, 휴지통도 중복, 다른 현장 같은 번호 허용 |
| 확정 | 검증 후 고객0, 확정 때 최신 중복 재검사·정상 행만 등록, 기존 상담 덮어쓰기0 |
| 상담 이력 | 미할당·IMPORT actor/시각/버전1·재콜·notes 스냅샷. Assignment/CustomerChangeEvent 생성0 |
| 원자성 | revision/bulk 삽입에 치명 오류 주입 후 Customer/Callback/Revision 모두0, 별도 FAILED 결과·후보 삭제·same-key 실패 고정 |
| 일시 오류 | OperationalError503에서 VALIDATED/후보 유지·receipt0, 같은 key 재시도 성공 |
| 경합 | 독립 PG 연결 같은 batch/key 생성1번, 두 batch 같은 번호는 성공1/중복1, 정리-만료 확정 경합 고객0 |
| 결과·보관 | 105실패 행100+5 페이지·연락처 원문·파일 없이 조회.24시간 원문 숨김/삭제·추가7일 metadata 삭제·고객/revision 유지 |
| 보안·원본 | 임시 파일 성공/실패 후 삭제, 매크로·ZIP 경로/크기·XML 엔티티·위조 차원·거대 희소 행·범위 밖 열 거부, 파서/500 로그 원문 없음 |
| 실제 브라우저 | 빈 양식 다운로드·검증·재검사·확정·새로고침 결과·실패 원문·HTML 텍스트·직원403·390px 넘침0·외부 요청/JS 오류0 |
| 실제 응답 유실 | 서버200 응답 뒤 브라우저 전달 중단→서버 COMMITTED 확인. 동일 key 재시도 고객/revision 추가0 |
| 오류 UI | 만료409·치명500 재업로드·일시503 동일 key 재시도, 실패를 성공으로 표시하지 않음 |
| P2 회귀 보완 | 조회 완료 전 현장 생성 클릭 유실을 실행 버튼 비활성화로 수정, 기존 수동 저장·그리드·삭제/복구 재통과 |

원시 기록은 `.local/p3-tests.log`다. 중간 테스트 harness/순서 의존 오류와 P2 UI 오류도 PROGRESS8.2에 남겼다. 의도적인500/503 로그는 실패 경로 주입이며 최종 suite 실패가 아니다.

## 1만 행 실제 측정

가짜1만 고객·상담 메모·방문일·통화결과,2,500건 재콜을 포함한 **309,678bytes xlsx**를 새 테스트 DB에서 처리했다. 파일 파싱은 공통 lock 밖이며, 검증 저장과 확정은 같은 PostgreSQL 업무 lock/bulk insert를 사용한다.

| 지표 | 최종값 |
|---|---:|
| 검증(파싱+DB 후보/결과 저장) | 2.190초 |
| 확정(현재 중복 검사+고객/재콜/revision/receipt) | 2.321초 |
| 전체 | **4.512초** |
| Python 프로세스 최대 RSS | **153.61MiB** |
| 업무 lock 획득 후 종료까지 | 검증1.038초 / 확정2.304초 |
| 생성 결과 | Customer10,000 / Revision10,000 / Callback2,500 / Candidate0 |

macOS26.5.2 arm64, Python3.13.18, PG170011. 원시 `.local/p3-performance.json`. RSS는 파서뿐 아니라 Django/테스트 프로세스 누적 peak이며 측정법은 Darwin ru_maxrss bytes→MiB다.20명 동시 부하·최대 길이 메모로 채운 모든 조합·운영 VM 성능을 측정한 것은 아니다. 별도 성능 명령으로 재현할 수 있다.

## 직접 확인

1. README1절 DB→migrate→collectstatic→Gunicorn, 별도 터미널 scheduler를 실행한다.
2. 관리자01000000001로 로그인한다. 초기 dodream이면 첫 비밀번호 변경을 마친다. 이미 변경한 값은 보존했다.
3. DB 관리→엑셀 업로드→빈 양식을 받거나 `.local/qa/p3_demo_upload.xlsx`를 선택한다. 새 현장 기준 총4·가능2·파일 중복1·형식 오류1이다.
4. 검증만으로 고객이 추가되지 않는 것을 확인하고 업로드 확정→등록 확정을 누른다. 새2건·실패2건을 확인한다.
5. 현재 주소를 다시 열어 파일 없이 행별 결과를 확인한다. 같은 파일을 다시 검증하면 기존 중복으로 실패하고 원래 상담정보가 유지된다.

실제 Gunicorn에서도 health/login/정적 JS200과 원본 SHA 일치, 비로그인 템플릿401을 확인했다. 스크린샷은 `.local/qa/p3-preview-desktop.png`, `p3-result-desktop.png`, `p3-result-mobile.png`, 실제 다운로드 빈 양식은 `TM_customer_template.xlsx`다.

검증 종료 후 작업 소유 Gunicorn·전용 PostgreSQL을 정상 종료했고 개발 고객65건을 보존했다. 다시 실행할 때는 README 순서를 따른다.

Docker 엔진이 없어 build/up/이미지 레이어 검사는 **미실행**이다. P4 분배/회수/사용자 관리, P5 직원 자동 저장, P6 상세 통계/23시, P7 승인/영구 삭제, AI·유료 호출·운영 배포·백업 복원·전체92개 검수도 이번 완료 범위가 아니다. 다음 P4는 사용자 지시를 기다린다.
