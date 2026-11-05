# P2 관리자 현장·DB 검증

실행일: 2026-11-04, Asia/Seoul. 위치: `/Users/hayeon/Documents/TMDB`. 기준: 개발설계서 v2.0 + IMPLEMENTATION_PLAN의 P2. 설계서/원본/sources 변경·유료 실행·배포 없음.

## 구현과 기본값

사용자 확정 규칙인 이름/연락처 수정 금지·최초 비밀번호 변경·서버 권한 검사·수동 관리자 저장·업무 이력 기반 진행·상담정보 보존을 유지했다. 첫 현장만 기본 지정하고, 명시적 기본 설정 전까지 사용자의 현장 선택은 전역 값에 영향을 주지 않는다.

| 항목 | P2 구현 |
|---|---|
| 확정 업무 규칙 | 관리자 이름·번호 일반 변경 API 거부, 직원 본인 현재 할당만 접근, 최초 변경 전 업무 차단 |
| 설계서 기본값 | 50/100행·최대100, 기본 생성 내림차순+ID, 현재 페이지만 선택, idempotency 7일 |
| 설계서 기본값 | 상담 10,000자와 기존 전체 길이 예외, 빈 계약=미확인, 날짜 KST/저장 UTC, 무변경은 미진행 |
| 계획의 문구 해석 | 관리자 이동은 저장/머무르기/변경 폐기. 저장 실패 시 현재 화면에 남음 |
| P2 구현 기본값 | 후보 100개 페이지, 후보 검색, 한 열 선택/제외 최대 1,000개. 전체 선택은 제외 목록 방식으로 표현 |
| P2 구현 기본값 | 날짜 범위 YYYY-MM-DD, KST 시작일 포함/종료일 다음날 미만. 화면 날짜 분 단위, API는 timezone-aware ISO 또는 KST local 일시 |
| P2 구현 기본값 | 정렬 선택 메뉴는 허용 목록만 전달, 행당 새 mutation UUID. 응답 미확인은 기존 요청 그대로 재시도 |
| P2 구현 기본값 | 요청 본문16MiB. 100행×10,000자 Unicode/escaped JSON을 수용하며 업무별 행/문자 한도는 그대로. 초과는 JSON413 |
| 후속 단계 경계 | 담당자 변경 P4, 직원 자동 저장 P5, 완료/통계 P6, 삭제 요청 승인/영구 삭제 P7 |

현장 생성 후에는 그 화면에서 새 현장을 연다. 일반 새 화면·새로고침은 전역 기본 현장에서 시작하며 열린 탭은 강제 전환하지 않는다. 대시보드의 현장 선택은 건수만 조회하고 설정 버튼이 전역 값을 변경한다.

## 실제 검증

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 --noinput -v 2
```

최종 **108개 통과**. 서버 105개(기존75+P2 30), Chromium 흐름 3개(기존1+P2 2). PostgreSQL `test_tm_dev`를 생성·삭제했고 개발 `tm_dev`와 분리했다. 실행 로그 `.local/p2-tests.log`, P2 브라우저 중간 개별 실행 `.local/p2-browser.log`.

| 검수 | 테스트 근거/실제 결과 |
|---|---|
| 현장·기본값 | 첫 자동 지정, 공백/영문 대소문자 중복, 2명 동시 중복은 1개 성공, 명시 설정·낡은 버전 거부·무변경 이력 0 |
| 권한·개인정보 | 직원 다른 고객/후보/오류 응답 차단, admin 페이지·삭제/복구/건수403, 임의 ORM 경로·페이지 크기·날짜·본문 거부 |
| 검색·필터·페이지 | 65건의 50+15/100행, 안정 순서, 전화 하이픈, 같은 열 OR/다른 열 AND/빈 값/제외/메모/KST 경계. 후보106개는100+6 |
| 상담 원자성 | 실제 수정에만 version·최초 진행·event·revision·callback·receipt, revision 삽입 오류 주입 시 모두 롤백 |
| 긴 메모 배치 | 100행×10,000자 한국어 상담을 escaped JSON으로 실제 저장100건. 본문 한도 초과는 JSON413·상담 쓰기0 |
| 진행 규칙 | 무변경·정규화 원복은0, 저장 후 원복은 진행 유지. 관리자 수정도 진행, 미할당 수정은 미래 할당에 소급하지 않음 |
| 경합·재시도 | 독립 연결 같은 버전 동시 수정은 성공1/충돌1. 같은 mutation 동시 요청은 revision/receipt1. 실패 receipt 유지·만료·권한 회수 재검사 |
| 상담 날짜 | 재콜 생성/변경/취소와 revision 원자성. 실제 브라우저에서 방문일시 입력·KST 표시·날짜 필터 |
| 휴지통 | 할당 종료·상담/재콜/이력 유지·일반 삭제의 요청 CLOSED·미할당 복구. 동일 키 동시 작업1, 누락 ID 일괄 취소, 늦은 복구가 새 할당 보존 |
| 실 브라우저 | 수동 저장 전 DB 불변, 더블클릭 이름 readonly, 이동 머무르기/폐기/저장, 충돌 서버/내 값 비교·명시 재적용, 입력 실패 이동 금지 |
| 실제 응답 유실 | Playwright가 서버 성공 응답을 받은 뒤 브라우저 전달을 끊음. 재시도 본문/키 동일·버전/이력 증가0·편집 잠금 확인 |
| UI·키 경계 | 메모 HTML이 실행되지 않음, 외부 CDN 요청/JS 오류0, 헤더/행 가로 정렬, 390px 문서 넘침0. P1 키/로그/fake 회귀도 재통과 |

화면을 직접 검토했다: `.local/qa/p2-grid-desktop.png`, `p2-grid-mobile.png`, `p2-conflict.png`. 모바일 그리드는 내부 가로 스크롤을 사용한다. 중간 테스트 오류와 UI 경합을 수정한 과정은 PROGRESS 7.2에 남겼다.

개발 실행도 별도로 했다. `seed_demo` 기존 3계정 보존, `seed_demo_customers` 최초65/재실행0, BASELINE65. `collectstatic` 후 Gunicorn 2 worker에서 `/healthz` DB 정상·`/auth/login`·`/static/customer-grid.js`·Tabulator 모두 HTTP200. 관리자의 최초 변경필수 상태를 유지했다.

실행 중 collectstatic 뒤의 캐시 차이로 자산 바이트 비교가 한 번 실패하여, 수집 후 새 프로세스로 재기동했다. grid/api/dashboard/Tabulator 4개 자산 모두 원본 SHA와 일치함을 실제 HTTP로 재확인했다. DB 상태 명령의 정상 중지 traceback도 수정하고 실행/중지를 실제 검증했다. 검증용 Gunicorn과 전용 PG는 정상 종료했고 데이터는 보존했다.

## 직접 확인

1. README 1절의 DB start → migrate → collectstatic → Gunicorn을 실행하고 `http://127.0.0.1:8000/auth/login`을 연다.
2. 가상관리자 `01000000001 / dodream`으로 최초 비밀번호를 변경한다. 이미 변경했다면 기존 비밀번호를 사용한다.
3. DB 관리에서 65건·이전/다음·50/100행·열 ▾ 필터·하이픈 전화 검색을 확인한다.
4. 상담 셀 더블클릭 → 변경 → 저장 전 DB 불변 → 저장을 확인한다. 이름/연락처는 수정할 수 없다.
5. 미저장 편집 후 페이지/현장/메뉴를 바꾸고 머무르기·변경 폐기·저장하고 이동을 각각 확인한다. 두 탭에서 같은 고객을 저장하면 나중 탭은 충돌 비교가 나타난다.
6. 체크 후 휴지통 이동을 확인하고 휴지통에서 복구한다. 상담은 그대로이며 담당은 미할당이다.
7. 현장을 새로 만들면 새 현장이 열리고 전역 기본값은 유지된다. 대시보드 설정 버튼으로만 변경한다. 다른 열린 탭은 유지되고 새 화면/새로고침은 새 기본값을 따른다.

## 정적 의존성과 미검증

Tabulator **6.3.1**, MIT. 공식 릴리스의 JS·Bootstrap5 CSS·LICENSE를 `static/vendor/tabulator/`에 보관하며 외부 CDN을 요청하지 않는다. [공식 릴리스](https://github.com/olifolkerd/tabulator/releases/tag/6.3.1), [공식 편집 API](https://www.tabulator.info/docs/6.x/edit/). 실제 자산·라이선스·그리드 동작을 검증한 태그를 고정했으며 설계서의 Tabulator 선택을 바꾸지 않았다.

| 파일 | SHA-256 |
|---|---|
| tabulator.min.js | e952272c3b2afa4ebb60cef5db8cbe9cbaabaa52b50c3cd3d22993ca5215a6ff |
| tabulator.min.css | 1f5810a81211dcbf5e9d7ba835f1404a3f90746484408025a13edce055e33737 |
| LICENSE | 6031e51b8450fa6047887f018951c8cf1456d98a5a08291774410c13696de18e |

P3 이후 엑셀·분배·직원 지속 대기열/자동 저장·재콜 완료/상세 통계/예약·삭제 요청 승인/영구 삭제·AI 기능은 아직 구현하지 않았다. 관리자 메모리 대기값은 브라우저 종료 후 복구를 보장하지 않으며 닫기 경고를 제공한다.

Docker 엔진이 없어 build/up/레이어 검사는 **미실행**이다. 백업 복원·실제 AI·운영 HTTPS·전체92개 인수 완료도 보고하지 않는다. 유료 API 호출·유료 자원·운영 배포 없음. 다음 단계는 **P3 엑셀**이며 사용자 지시를 기다린다.
