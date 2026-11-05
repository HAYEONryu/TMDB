# v2.0 P1~P4 기반 구조와 후속 구현 계약

기준: 설계서 v2.0. 기존 모델·인증 기반을 보존하고 상담 이력 구조·AI 설정 격리를 보완했다. 업무 규칙 변경 없음. 이전 문서 원본은 history에 보존했다.

## 데이터 모델

| 도메인 | 모델·주요 보장 |
|---|---|
| accounts | UUID User, 전화번호 unique/010 형식, ADMIN/EMPLOYEE, 변경필수·session_version. 추가 LoginFailure는 HMAC 키·시각만 보관 |
| sites | 공백/영문 대소문자 정규화 name_key unique, singleton GlobalSettings, nullable FK + UUID 스냅샷 기본 현장 이력 |
| customers | 현장+전화 unique는 휴지통 포함, 이름/번호/enum/버전 검사, 조회 인덱스, 상담 변경 필드 이력, CustomerDeletionRequest |
| assignments | 고객당 미종료 할당 하나, 종료 시각/사유 정합성, 직원/할당일 인덱스 |
| callbacks | 고객당 PENDING 하나, 상태/완료자/완료·취소 시각 검사, 예정일 부분 인덱스 |
| imports | 검증/확정/만료/실패 batch, 원본 행 번호별 후보·오류 결과 unique, 검증 집계·확정자/시각, 고객에서 nullable batch 참조 |
| operations | 처리자+작업+key unique, 처리자+mutation unique, 고객 FK receipt, 예약 종류+업무날짜 unique, lease·시도·오류 필드, 비식별 OperationEvent |
| consultations | 고객+버전 unique, 실제 actor/시각·변경 전후·notes·source, FK·상태 CHECK·기간 조회 인덱스 |

도메인 모델 17개와 로그인 제한 보조 모델 1개다. GlobalSettings는 singleton 정수 PK이고 다른 도메인 모델은 UUID PK다. 변경 가능한 엔터티는 생성·수정 시각을 가진다. DateTimeField는 PG timestamptz로 생성하고 UTC 저장·Asia/Seoul 업무 경계를 사용한다.

`Customer.current_assignment`와 Assignment.customer의 순환은 assignments 0001 → customers 0001 → assignments 0002 순서로 연결한다. 종료 사유 CHECK의 NULL 허용 문제는 assignments 0003에서 보완했다. sites 0002는 GlobalSettings 1번 행을 생성한다. 비밀번호·공용 관리자 계정은 migration에 없다.

## 디비 제약과 서비스 검증의 구분

- DB는 unique·부분 unique·enum·형식·버전·상태 CHECK·FK를 보장한다. 소프트 삭제 고객의 current_assignment는 null이어야 한다.
- 현재 할당의 고객 일치·미종료 여부는 `Customer.clean()`에서 검증한다. 삭제 요청의 요청 당시 할당/고객 일치는 `CustomerDeletionRequest.clean()`에서 검사한다. Django `save()`는 `full_clean()`을 자동 호출하지 않으므로 후속 도메인 서비스가 잠금 안에서 재검증해야 한다. 임의 QuerySet update를 업무 API에 노출하지 않는다.
- P2 고객 변경 API는 상담 필드 6개만 허용한다. 관리자도 이름·연락처·담당자·시스템 필드를 수정할 수 없다. 모델 직접 SQL 갱신을 막는 트리거를 구현한 것으로 보고하지 않는다.
- `notes`는 시스템 승인 문구를 추가할 공간이 있어야 하므로 TextField에 디비 길이 상한을 두지 않았다. P2에서 사용자 입력 기본 10,000자/기존 전체 길이 편집 예외를 검증한다.
- Customer·현장 영구 삭제의 최종 서비스는 아직 없다. Django CASCADE와 순환 참조 정리는 모델 테스트로 확인했지만, JSON result/target_ids 안의 개인정보·IdempotencyRecord까지 제거하는 절차는 P7 서비스에 반드시 포함해야 한다. P2부터 저장/휴지통 API가 7일 receipt를 생성한다.

## 쓰기 잠금과 트랜잭션

`apps.common.transactions.business_write()`는 PostgreSQL transaction-level advisory lock `7420192701`을 획득한다. 잠금 순서는 공통 lock → 사용자 ID 정렬 → 필요한 전역 설정 → 현장 ID 정렬 → 고객 ID 정렬 → 할당/재콜이다. 이번 비활성화 서비스는 변경 대상 사용자·고객·할당을 그 순서대로 잠근다. JOIN으로 할당 행을 먼저 잠그지 않도록 고객 잠금에 `of=("self",)`를 쓴다.

잠금 timeout 기본 5,000ms, PostgreSQL 55P03/40P01/40001은 롤백 후 50ms 간격으로 1회만 재시도한다. 재시도에도 실패하면 인증 쓰기 API는 503 `TEMPORARY_UNAVAILABLE`로 응답한다. 무한 재시도하지 않는다. 내부 사용자 접근 변경 서비스도 같은 재시도 규칙을 사용한다.

신규 업무 쓰기는 이 공통 경계를 거쳐야 한다. P2 현장/상담/휴지통·P3 업로드/정리·P4 분배/회수/담당자/사용자 서비스 모두 같은 lock을 사용한다. 삭제 요청·승인은 후속 단계다. 읽기와 엑셀 파싱은 공통 쓰기 lock 밖에서 처리한다.

## 인증·세션

1. Django ModelBackend가 전화번호와 해시를 검증하고 서버 세션을 만든다.
2. DB의 user 활성·session_version을 매 요청 확인한다. 세션 버전이 다르거나 해시 검증이 무효하면 로그아웃 처리한다.
3. `/api/me`, 비밀번호 변경, 로그아웃만 초기 변경 상태에서 허용한다. 업무 API·역할별 페이지는 차단한다. 이 단계에서 공개 경로는 로그인·정적 자산·DB health다.
4. 첫 변경/본인 변경은 현재 비밀번호를 검증한다. 비밀번호 변경과 session_version 증가·작업 이벤트를 한 트랜잭션으로 저장한 뒤 현재 세션의 해시·버전만 갱신한다.
5. 관리자 재설정은 dodream, 변경필수 true, 버전 증가를 한 트랜잭션으로 저장한다. 대상의 기존 세션을 살려두지 않는다. 관리자가 본인을 재설정해도 같다.
6. 서버 역할 검사는 `role`을 사용한다. `is_staff`·`is_superuser` 플래그로 업무 권한을 우회할 수 없다. 마지막 활성 관리자의 비활성화/직원 전환은 직렬화된 서비스 안에서 차단한다.

비활성화 서비스는 모든 현장·날짜에서 미진행 현재 할당만 종료하며 고객 version을 증가시킨다. 진행 할당·상담정보는 유지한다. 직원→관리자 전환만으로 배정을 종료하지 않는다. P4 상태 변경 UI/API도 이 공통 구현을 호출한다.

## 이번에 정한 구현 기본값

설계서 미지정 세부값 중 이번 기능에 필요한 것만 결정했다.

| 항목 | 기본값·이유 |
|---|---|
| 사용자 이름 | 최대 100자, 빈/공백 이름 거부. 현장/고객명과 같은 초기 입력 한도로 설정 |
| 계약 enum | UNKNOWN=미확인, NO_CONTRACT=미계약, CONTRACTED=계약. 승인된 한글 값 변경 없음 |
| 실패 제한 | 900초 창, 계정 실패 5회, 요청 출처 실패 30회. 동시 시도도 같은 DB lock 안에서 검사 |
| 잠금·재시도 | 5초, 최초 포함 최대 2번 시도. DB 상태를 조용히 무시하지 않고 503 표시 |
| 개발 DB | 별도 tm_dev와 test_tm_dev, loopback 55432. 다른 프로젝트와 충돌 방지 |
| 로그인 세션 | 12시간, HttpOnly·SameSite=Lax. 로컬 HTTP 전용에서 Secure=false; 운영 HTTPS 설정은 별도 |

P2 기본 현장·관리자 저장 이동 UX는 계획의 기존 해석대로 구현했다. 미진행 통계 집합·업로드 실패 상태 정책·23시 시작일/lease의 후속 구현은 개발 계획을 따른다. 승인된 업무 규칙을 바꾸지 않았다.

## v2.0 상담 이력

기존 migration을 재생성하지 않고 consultations 0001을 추가했다. 실제 actor·서버 저장 시각·고객 버전·변경 필드·전후 상담 값·notes·source를 보관한다. 알 수 없는 과거 작성자는 BASELINE에서만 nullable로 표현하고 과거 작성일·작성자를 자동 생성하지 않는다.

P1은 구조 검증, P2는 상담 저장과 revision의 원자적 연결까지 완료했다. 실제 변경에만 customer.version·최초 진행 시각·CustomerChangeEvent·MANUAL revision·재콜 변경·MutationReceipt를 함께 저장한다. 무변경은 receipt만 남기고 진행/상담 이력을 만들지 않는다. 미할당 수정은 assignment=null 이력이며 후속 할당에 소급하지 않는다. AI_APPLIED의 원본 AIResult FK는 P9에서 AI 모델과 함께 연결하며 그 전에 추천 적용을 공개하지 않는다. 과거 이력 편집/삭제 API는 없다.

P2 조회는 서버가 권한/현장/화면·검색·열 조건을 적용한 다음 50/100행을 반환한다. 후보값은 본인 열 조건만 제외하고 같은 범위에서 100개씩 반환한다. whitelist 밖 ORM 경로는 받지 않는다. 이름·연락처·담당자는 UI와 일반 저장 API에서 읽기 전용이다.

관리자 대기값은 수동 저장 전까지 브라우저 메모리에 둔다. 이동 전 저장/머무르기/폐기를 선택하고, 실패하면 현재 화면에 남는다. 응답 유실은 원래 mutation과 본문으로 재시도하며 충돌은 최신 서버값 비교 후 새 mutation을 만든다. 직원 IndexedDB/100초 전송은 아래 P5 구조로 구현했다.

일반 휴지통 이동은 현재 할당을 종료하고 미처리 삭제 요청이 있으면 CLOSED/ALREADY_DELETED로 닫는다. 승인 문구를 추가하거나 APPROVED로 바꾸지 않는다. 복구는 상담/재콜/이력 보존·미할당이며, 이미 복구된 행의 새 할당을 늦은 복구 요청이 지우지 않는다. 접수·승인 UI와 영구 삭제는 P7이다.

## P3 엑셀·결과·정리

imports 0002는 기존 migration을 보존하며 validation_summary·committed_at/by를 추가하고, 잘못된 긴 고객명도 행 오류 원문으로 표시할 수 있도록 ImportRowResult.customer_name을 text로 확장한다. 고객 모델의 이름100자 제한은 유지한다.

openpyxl3.1.5·defusedxml0.7.1을 lockfile/hash와 함께 추가했다. 첫 워크시트·정확한9열·텍스트 전화·한글 enum·날짜/시각·행별 길이·수식·매크로를 검사한다. 스트리밍 파싱·XML/ZIP 방어는 lock 밖에서 끝낸다. 첫 유효 연락처만 파일 후보이며, 기존 중복은 휴지통도 포함한다. 원본은 close하고 Django 임시 파일도 삭제한다.

확정은 actor→site→batch를 잠근 뒤 현재 중복을 재검사한다. Customer·PENDING Callback·actor/source=IMPORT/assignment=null Revision·행 결과·batch 상태·집계·receipt를 같은 트랜잭션으로 bulk 저장한다. 할당/진행 이벤트는 만들지 않는다. 성공 후 후보는 삭제한다. 치명 DB 오류는 전체 롤백 후 별도 잠금 트랜잭션으로 FAILED·일반 오류코드만 기록한다. FAILED는 자동 복구하지 않고 재업로드하며, 동일 key 응답은 고정한다. 잠금/연결 오류는503이며 VALIDATED 후보와 같은 key를 유지한다.

P3 receipt는 batch/site UUID와 집계만 보관하며 원문을 복제하지 않는다. 최초 접수 기준 최소7일, 검증 만료+7일을 넘지 않는다. 만료 후 새 key 접수는 막고 기존 유효 key의 성공 응답은 재생한다. 최종 P7 영구 삭제는 여전히 batch/site를 참조하는 receipt의 정리까지 고려해야 한다.

행 원문은24시간 경계부터 조회에서 숨긴다. cleanup_imports 또는60초 scheduler가 후보·행 결과를 지우고 미확정은 EXPIRED로 바꾼다. 집계 batch는 expires_at+7일에 제거하며 이미 등록한 고객.import_batch는 null, 고객·재콜·revision은 유지한다. 정리는 최대50 batch씩 짧은 트랜잭션이며 scheduler의23시 회수 업무는 P6까지 비활성이다.

## P4 분배·회수·사용자

추가 모델/migration 없이 기존 UUID·할당 unique·고객 version·IdempotencyRecord를 재사용했다. apps/assignments/services.py가 분배·오늘 회수·담당자 변경을 담당한다. 활성 직원은 실제 실행 트랜잭션에서 확정하고, 후보는 선택 현장/미삭제/미할당만 포함한다. 부족하면 고객/할당 변경0, 충분하면 PostgreSQL RANDOM 추출·할당 생성·현재 연결·버전 증가·작업/receipt를 같은 트랜잭션으로 저장한다.

오늘 회수는 KST 날짜 경계의 현재 할당 전체다. 진행 건도 포함하고 과거/다른 현장/비활성/관리자로 바뀐 대상은 전체 팀원에서 제외한다. 비활성/관리자 기존 담당은 개별 담당자 변경·회수로 처리한다. 담당 변경의 동일인 재선택은 버전·할당·최초 진행 모두 no-op, 변경/회수는 기존 할당 종료·새 UUID/현재 시각·최초 진행 null이다. 상담·재콜·상담 revision·PENDING 삭제 요청은 건드리지 않는다.

end_locked는 미리 잠근 고객/할당을500개 단위의 상수 UPDATE와 F(version)+1로 갱신한다.1만 건 측정에서 CASE bulk_update의 약10초 잠금 병목을 확인해 최적화했으며 잠금 단위나 업무 규칙은 바꾸지 않았다.

apps/accounts/management_services.py는 사용자 생성·최종 상태 기준 원자적 편집·비활성 회수·이관 조회를 공유한다. 기존 set_user_access는 이 서비스의 호환 진입점이다. 재시도 장식을 중첩하지 않으며 실제 PG 잠금 timeout에서 총2회만 시도한다. 사용자는 삭제하지 않는다. 마지막 활성 관리자 guard는 전체 변경 후 상태로 판단해 같은 배치의 관리자 인계도 가능하다. 사용자 optimistic token은 updated_at ISO 문자열로 별도 스키마를 추가하지 않았다.

전화/역할/활성 변경은 session_version 증가, 이름만 변경은 세션 유지다. 비밀번호 재설정의 키 재생은 최초 변경 이후 다시 dodream으로 되돌리지 않는다. 공개 사용자 응답은 허용 필드만 포함하고 password/해시/is_superuser/is_staff는 포함하지 않는다. 비활성화는 전 현장·전 날짜 미진행만 회수하며 진행은 정확한 담당 UUID의 이관 필요 목록에서 처리한다. 새 관리자/활성 사용자는 초기 변경 절차를 거친다.

P4 receipt는7일 보관한다. 분배·회수·담당자 변경은 성공/확정 업무 오류를 저장하며 사용자 편집/추가·재설정은 성공 결과를 저장한다. 고객명/연락처/상담·사용자 편집 원문·비밀번호를 복제하지 않고 ID·직원명/건수·버전·처리 결과를 남긴다. scheduler가 P4 만료 receipt를 최대1,000개씩 정리한다. DB 오류는 롤백 후 일반503으로 반환하고 SQL/입력 원문을 출력하지 않는다.

정상 UI의 응답 미확인 분배/회수/담당변경/재설정은 계정별 sessionStorage에 ID/버전/수량/시각만 유지한다. 자동 재전송하지 않고 사용자 확인으로 같은 본문/키를 보낸다.7일을 넘거나 시각이 불명확하면 전송하지 않는다. 사용자가 대기 정보만 폐기한 뒤 서버 상태를 확인할 수 있다. 사용자 편집 대기값은 메모리이며 닫기/이동 경고를 제공한다. 직원 IndexedDB·100초 전송과 분리한 P4 관리자 기능이다.

## P5 직원 저장과 브라우저 복구

`apps/customers/employee.py`는 직원 전용 화면·실행 컨텍스트·대기열 검증·저장 진입점이다. `X-TM-Queue-User`를 현재 로그인 UUID/직원 역할과 비교한다. 공용 고객/필터/저장 API도 이 헤더가 있으면 같은 검사를 한다. 로그인 계정이 바뀐 이전 탭이 새 세션 권한으로 대기값을 전송하지 못한다. 쓰기 잠금을 얻은 뒤에도 직원 역할을 재확인한다. 인증·비활성화·최초 비밀번호 변경·CSRF 규칙은 P1 그대로다.

`static/employee-grid.js`는 서버 페이지·필터를 쓰는 직원 Tabulator 화면이다. 업무9열·할당일·저장 상태이며 선택 체크박스와 관리자 작업은 없다. 오늘 조회는 KST 오늘의 현재 할당 OR 오늘/과거 PENDING 재콜이다. overdue는 현재 시각 이전, 다음은 오늘의 미래 재콜, 나머지는 오늘 할당이다. 각 그룹은 재콜 시각·할당 시각·ID로 정렬한다. 재콜 완료·상세 집계는 P6이다.

`static/employee-store.js`는 `tm-employee-queue-v1 / entries` IndexedDB 보관소다. 키는 사용자·현장·고객·할당·브라우저 문서별 UUID를 포함한다. 평문 메타데이터는 이 식별자와 암호문/IV뿐이다. 변경 필드·기준 버전·고정 전송 스냅샷·시각·재시도 상태만 AES-256-GCM으로 암호화한다. 전체 고객 행·변경 전 값·세션·비밀번호·AI 키는 보관하지 않는다. GCM의 추가 인증 데이터에 모든 식별자를 넣어 메타데이터 변조도 검출한다.

로그인된 본인에게만 전달하는 키는 Django SECRET_KEY와 사용자 UUID의 용도 분리 HMAC에서 구하고, 브라우저 메모리의 non-extractable CryptoKey로만 유지한다. localStorage/sessionStorage/IndexedDB에는 키를 쓰지 않는다. SECRET_KEY를 잃거나 바꾸면 이전 대기값을 해독할 수 없으므로 운영 키 교체·백업 정책에서 미저장 대기값 정리를 고려해야 한다. 해독 실패는 기록을 삭제하지 않고 복구 오류를 표시한다. AI 키와는 별도 구조다.

`static/employee-queue.js`의 상태 전이는 다음을 지킨다.

- `pending`은 아직 보내지 않은 최종값이다. 무변경은 만들지 않고 미전송 원복은 제거한다. 첫 유효 입력의 시각을 고정하며 추가 입력으로90초 목표를 연장하지 않는다.
- 전송 직전에 `pending`을 고유 mutation/기준 버전/기존 할당 ID를 가진 `inflight`로 분리하고 보관을 시도한다. 이후 입력은 새 `pending`에만 쓴다. ACK는 확인한 스냅샷만 지우고 새 변경의 기준 버전을 갱신한다. 이후 값이 있으면 유지한다.
- 문서별 entry Web Lock은 살아 있는 다른 탭의 대기열을 중복 복구하지 못하게 한다. 사용자·고객·할당별 send Lock으로 네트워크를 직렬화하되, 버전이 다른 두 탭을 자동 병합하지 않는다. 중단된 여러 lane이 같은 고객에 남으면 수동 비교한다.
- 복구/재시도/실제 전송 전에 현재 담당자·할당·삭제·버전·receipt를 서버에서 확인한다. receipt가 있으면 서버 확인 결과를 사용한다. 다른 최신 변경과 이후 입력이 겹치면 충돌이다.7일 이상은 수동 검토하고 재적용에 새 mutation을 쓴다.
- 회수/재분배/삭제는 자동 재시도하지 않고 내 값의 비교 표시도 숨긴다. 자신이 실제 보유했던 과거 할당만 ASSIGNMENT_CHANGED/CUSTOMER_DELETED로 구체화하고, 관계없는 고객은 FORBIDDEN이며 서버 행을 노출하지 않는다.
- 일시 실패는2/5/15/30/60초 상한 안에서90~100% 무작위 지연을 둔다. offline은 online 이벤트를 기다린다. 인증 오류는 중단하며 다른 계정/역할을 알리는 BroadcastChannel에도 이전 화면과 전송을 중단한다. 메시지는 계정 메타데이터뿐이다.
- 메뉴·검색·필터·페이지·현장·로그아웃은 편집 확정→즉시 flush→성공 후 이동한다. 실패는 재시도/취소/재확인한 폐기다. 종료 이벤트는 경고이며 유일한 보관 수단이 아니다. IDB 용량 오류는 표시하고 즉시 서버 전송을 시도한다. 로컬 삭제 실패도 성공으로 숨기지 않는다.

읽기 전용·XSS 방지 textContent·복사/잘라내기/Cmd/Ctrl C·X/우클릭 제한은 직원 표 범위다. 편집기 커서 선택과 붙여넣기는 허용한다. 이 UI 제한은 개발자 도구·화면 촬영을 차단하는 보안 경계가 아니다. 권한 경계는 서버의 현재 할당/세션 검사다. 구현과 실제 검증 범위는 [P5_VERIFICATION.md](P5_VERIFICATION.md)를 따른다.

## v2.0 프로세스·키·fake

| 진입점 | 역할 | AI 설정 |
|---|---|---|
| WSGI/runserver | web | 명시 로더 허용 |
| run_ai_worker | ai_worker | 로더 허용. P9 DB 큐/예약 정리·테스트 작업 처리, 실제 전송 비활성 |
| run_scheduler | scheduler | 상속 AI 환경 제거·파일 미로딩 |
| 일반 관리 명령 | management | 상속 AI 환경 제거·파일 미로딩 |
| manage.py test | test | test_settings·파일 미로딩·테스트 DB에서만 fake |

config/process.py가 Django setup 전에 역할을 결정한다. 일반 .env에서 AI_*나 역할/설정 모듈을 바꾸는 값을 로딩하지 않는다. 로더는 프로세스 환경 우선·파일 보완, 외부 AI_ENV_FILE·0600 검사, 키/단가/모델 오류 fallback을 적용한다.

AIConfig의 키는 repr에서 제외하고 응답은 허용 필드만 반환한다. 로그 formatter는 메시지·인자·traceback 최종 출력에 키 마스킹을 적용하고 Django 부모 logger도 같은 handler로 설정했다.

fake는 TESTING 설정과 테스트 DB 이름을 모두 검사하며 일반 로더는 fake 선택을 거부한다. P1에는 실제 provider SDK/전송/생성 API가 없었다. P9의 요청/결과/Quota/ReportSlot·비용·파생 결과 삭제 구조는 아래 P9절을 따른다. 실제 전송·생성 버튼은 아직 비활성이다.

## P6 재콜·이력·집계·예약

`apps/callbacks/services.py`는 완료할 일정 ID/버전·고객 버전·기존 할당 ID·요청 key를 받는다. 공통 업무 잠금→정렬한 사용자→현장→고객→할당/일정 순서로 검사한다. 권한/할당 검사를 cached receipt보다 먼저 하고, PENDING 일정만 완료한다. 완료·고객 버전·최초 진행·CustomerChangeEvent·ConsultationRevision·요청 결과는 한 트랜잭션이다. 이미 완료된 **같은 일정** 재시도는 최초 완료자/시각을 유지하고 새 PENDING 일정을 건드리지 않는다. cached 본문에는 고객 행을 넣지 않고 응답 시 현재 행을 다시 붙여 새 일정 셀을 옛 값으로 지우지 않는다.

직원 `flush(true, customerId)`는 그 행만 저장하고 다른 행의 최초 타이머를 유지한다. `CallbackAction`은 완료 요청 중 추가 편집/이중 클릭을 막고 응답 미확인 시 계정별 sessionStorage에 ID/버전/key/시각만 보관한다. 자동으로 새 완료 요청을 만들지 않고 동일 요청 확인·명시적 정보 폐기를 제공한다.7일 지난 요청은 재전송하지 않는다. 관리자 일반 상담의 수동 저장 방식은 유지한다.

`GET /api/customers/<id>/history`는 현재 본인 담당 또는 관리자만 사용할 수 있고 재콜/상담 이력을50건씩 조회한다. 이전 담당자 이력은 현재 담당 고객에 한해 읽는다. 직원의 회수/삭제 고객은 비노출이고 관리자는 휴지통 이력을 읽을 수 있다. UI는 한국어 항목·선택값·KST 날짜·변경 전/후 표를 쓰며 원문을 HTML로 해석하지 않는다.

`GET /api/dashboard`는 REPEATABLE READ/READ ONLY 스냅샷으로 조회한다. 활성 직원의 오늘 할당 이력은 고유 고객과 작업 횟수를 분리한다. 통화결과·오늘 미진행은 오늘 해당 직원에게 할당된 고객 집합과 현재 보유 집합의 교집합이다. 현재 보유 전체 미진행은 별도 분모다. 오늘 이력에서 현재 보유를 뺀 수는 회수/이관/삭제 수로 표시한다. 직원은 자기 지표만 받는다. 조회·현장 변경·수동 새로고침만 요청하며 통계를 자동 폴링하지 않는다. 현장 선택 GET은 전역 기본 현장을 바꾸지 않는다.

operations0002는 기존 ScheduledJobRun에 lease_token/next_retry_at과 SchedulerState를 추가한다. sites0003은 기본 현장 이력에 설정 버전을 추가해 동일 시각 변경 순서를 고정한다. 기존 기록의 새 보조 값은 변경/생성 시각 순서로 채우며 기존 날짜/대상/설정을 수정하지 않는다. 새 이력은 실제 GlobalSettings.version을 기록한다.

`apps/operations/scheduler.py`는 최초 한국 운영 날짜를 영속화하고 날짜별 고유 작업을 만든다. cutoff는 기준일23시이며 변경 이력으로 대상 현장 UUID를 결정해 보존한다. 기록이 불충분하면 DEFAULT_HISTORY_MISSING으로 남기고 임의 현장/0건 성공으로 바꾸지 않는다. 현장이 없거나 이미 삭제된 것이 확인된 경우만0건 완료한다.

claim은 별도 커밋으로 RUNNING·새 token·120초 lease·누적 시도 횟수를 기록한다. execute는 token/lease를 다시 검사하고 공통 잠금 안에서 고객 조건을 재조회한다. 소규모 계정 ID 전체를 정렬 잠금한 뒤 전역 설정·현장·고객·할당 순서로 진행한다. 쓰기가 공통 잠금으로 이미 직렬화된 범위이며, 회수 대상 직원의 대규모 DISTINCT 조인을 피한다. 실제 회수와 완료 기록·OperationEvent는 한 번에 커밋한다. SQL timeout60초·커밋 전 lease 만료 검사가 있고 실패 시 업무 변경을 롤백한 뒤 별도 FAILED를 기록한다. 만료된 옛 token은 새 worker의 작업을 완료할 수 없다.

미진행은 현재 할당의 first_activity_at=null이다. 기준일00:00~cutoff에 할당되었고 아직 현재 할당이며 삭제되지 않은 대상만 회수한다. 지연 중 새 할당·진행 저장을 되돌리지 않는다. 통화결과·기존 상담/재콜 값은 판정 조건이 아니다. 대상 현장은 재시도 때 새 기본 현장으로 바꾸지 않는다. 자동 시도 최대5회·실패 지연60초부터1시간 상한·31작업/tick이고, 마지막 RUNNING도 lease 만료 후 FAILED로 회복한다. `--once --retry-date`는 살아 있는 lease/완료 작업을 중복 실행하지 않으며 누적 횟수를 유지하고 기존 실패 작업만 명시적으로 재시도한다. 요약 실패 수는 미해결 FAILED 수이고 단발 명령은 실패를 성공 종료로 표시하지 않는다.

직원 화면은 서버 컨텍스트 **수신 시각**을 기준으로 클라이언트 시계를 보정하여22:59:30 전후 열린 편집을 확정·전송 시도한다. IndexedDB 복구 지연으로 이 보정 기준을 뒤로 밀지 않는다. online/visible 복귀와 서버가 결정한 실제 커밋 순서를 따르며 오프라인 성공을 약속하지 않는다. 만료 MutationReceipt·재콜/기존 작업 receipt를 각각 최대1000개씩 정리하지만 상담·할당·재콜 원문 이력·완료 작업 기록은 보존한다. 실제 검증과 미실행 범위는 [P6_VERIFICATION.md](P6_VERIFICATION.md)에 있다.

## P7 삭제 요청·승인·영구 삭제

기존 CustomerDeletionRequest·조건부 unique·상담 revision·IdempotencyRecord를 재사용하며 새 모델/migration·의존성은 없다. `apps/customers/deletions.py`의 쓰기는 공통 업무 잠금→정렬한 관련 사용자→전역 설정(필요 시)→현장→고객→할당/재콜/요청 순서로 처리한다. 읽기 알림은 REPEATABLE READ/READ ONLY 스냅샷으로 전체 건수와50행을 한 응답으로 반환한다. 직원 접수는 본인 현재 할당·버전·identity를 검사하며 중복 PENDING은 원래 요청자/할당을 보존한다. 접수 자체는 고객 버전·진행·상담·할당을 바꾸지 않는다.

승인은 현재 상담 원문을 잠근 뒤 시스템 문구·휴지통·할당 종료·요청 승인자/시각·CustomerChangeEvent·SYSTEM_DELETE_NOTE revision·작업/receipt를 한 번에 커밋한다. 빈 비고와10,000자 비고를 그대로 보존하고 시스템 추가분은 일반 사용자 입력 한도를 적용해 자르지 않는다. first_activity_at을 만들지 않는다. 같은 요청의 후속 승인은 최초 메타데이터만 반환하므로 복구한 고객을 재삭제하지 않는다. 일반 삭제는 CLOSED/ALREADY_DELETED로 닫고 승인 문구를 만들지 않는다.

`deletion-action.js`는 해당 행만 flush하고 하나씩 확인/제출한다. 요청완료 확인값을 assignment ID에 묶어 낡은 동일 버전 GET이 지우지 않게 한다. `deletion-notifications.js`는 관리자 진입·수동·복귀·활성60초에만 단일 목록 GET을 수행한다. 조회 도중 복귀 이벤트는 한 번 뒤이어 갱신하고 숨김 상태에서는 timer를 멈춘다. 통계 폴링·자동 승인·AI 호출은 없다.

휴지통 단건 영구 삭제와 현장 영구 삭제는 `erase_customers`를 공유한다. 고객의 순환 current_assignment 연결을 비운 뒤 FK cascade로 할당·재콜·revision·mutation receipt·삭제 요청을 제거한다. target_ids와 과거 구조의 고객 참조를 검사해 generic receipt도 지운다. 고객 단건은 같은 현장·정규화 연락처의 업로드 캐시만 원문 삭제하고 타 현장/타 고객 후보를 보존한다. VALIDATED 후보는 제거·집계 재계산하여 이후 확정으로 재생성되지 않게 하고 COMMITTED 결과의 원래 건수는 유지한다. 현장 삭제는 전체 batch/candidate/result를 함께 제거한다.

영구 삭제용 receipt에는 actor·작업 key·시각·건수와 keyed HMAC만 남기고 고객/현장명·대상 ID 목록·원문을 넣지 않는다. 현장명은 서버의 정확 일치 확인 후 actor/site/key/updated_at에 묶인7일 서명 증명으로 바꾼다. 브라우저 재시도 정보에는 이 증명만 보관하고 입력 이름은 지운다. 같은 key/body 재확인은 대상이 이미 없어도 원래 결과를 반환하며 대기 정보 폐기는 undo가 아니다. 만료 결과는 기존 scheduler 정리 목록에 포함했다.

기본 현장 삭제는 남은 created_at/id 순 첫 현장으로 전환하고 마지막이면 null이다. `change_default`는 None을 허용하며 기본 현장 UUID 이력·버전을 남긴다. 기존 예약 작업의 FK는 null이어도 cutoff 대상 UUID snapshot은 보존한다. UI는 대체 현장/URL·필터를 갱신한다.

P7 당시 `apps/ai_assistant/privacy.py`는 미처리 AI 모델이 생기면 삭제 전체를 롤백하는 guard만 제공했다. P9에서 실제 모델과 원문·혼합 결과·이전 결과의 재귀 무효화를 연결했다(아래 P9절). 오프라인 브라우저의 암호화 대기값은 원격 삭제할 수 없으며 서버에서 삭제/할당 검사를 통과하지 못한 값은 전송 성공으로 처리하지 않고 명시적 폐기 대상으로 유지한다. 당시 검증은 [P7_VERIFICATION.md](P7_VERIFICATION.md)에 기록했다.

## P8 통합 검수·실행 근거

업무 모델/API·의존성은 그대로 유지했다. `tests/test_p8.py`는 실제 PG와 HTTP 테스트 클라이언트로 네 AI 설정 실패별 전체 업무 연동, 삭제된 현장의 옛 큐/업로드 거부, seed 보존, 저장 원복/관리자 주택상황 수정과 미진행 회수를 검증한다. 외부 socket과 fake adapter 실행을 막아 AI 없이 기본 업무가 독립 동작하는지 확인한다.

`config.acceptance_runner.AcceptanceRunner`는 선택 runner이며 기본 실행 설정을 바꾸지 않는다. 실제 unittest 결과에서 개별 passed/failed/error/skipped를 수집하고 실패한 subtest를 나중 성공으로 덮어쓰지 않는다. 실행 전후 apps/config/scripts/static/templates/tests의 관련 코드·검수 매핑을 SHA로 고정한다. `.local/p8-test-results.json`은 원문/traceback 없이 ID·결과·시각·소스 해시만 남긴다.

`scripts/verify_acceptance.py`는 원본18.1~18.7의69문항·순서와 `tests/acceptance_basic.json`을 비교한다. 필요한 테스트가 전부 passed이고 소스가 같을 때만 항목을 통과로 표시하며, suite 전체가 실패하면 종료 코드1이다. skip/누락·소스 변경을 통과로 치환하지 않는다. Markdown 결과와 원시 JSON을 만들며 설계서의 체크박스는 수정하지 않는다.

`tests/test_backup.py`는 테스트 DB만 실제 dump한 뒤 같은 PG 클러스터의 고유 임시 DB에 복원한다.27개 테이블 모든 행의 해시/건수·실제 비밀번호·할당 연결·쓰기 격리를 검사하고 자신이 생성한 DB/0600 dump만 제거한다. 비밀번호는 subprocess argv/로그에 넣지 않고 PG 환경으로만 전달한다. 운영 백업 보관·암호화·AI 포함 복원은 후속 P13이다. 검증 결과/제한은 [P8_VERIFICATION.md](P8_VERIFICATION.md), 문항별 근거는 [P8_ACCEPTANCE.md](P8_ACCEPTANCE.md)를 따른다.

## P9 AI 공통 기반

ai_assistant0001/0002는 AIRequest·AIResult·AIQuotaBucket·AIUsageAttempt·AIReportSlot·SiteKnowledge·AIResultSource·AIBudgetMonth·AIRequestKey를 추가한다. consultations0002는 source_ai_result FK를 연결한다. 기존 업무 migration/모델·비밀번호는 유지한다. quota `(user,korean_date)` unique·성공+예약≤30·계정당 active 요청1개·보고서 feature/scope/period unique·요청자/key unique·원본 참조 정확히1개·금액 비음수 등은 DB 제약이다.

`services.reserve`는 내부 서버 진입점이며 아직 생성 POST는 없다. 공통 업무 잠금→요청자→현장/고객→slot/quota/월 원장 순서로 검사하고 원문 없는 본문 hash·alias를 남긴다. 캐시/공유 작업을 반환한 새 key도 다른 본문으로 재사용하지 못하게 한다. 직원 결과는 요청 직원+현재 할당만, 보고서는 현재 관리자만 조회한다. 관리자가 직원 개인 결과를 우회 조회하지 못한다.

`inputs.build`는 DB에서 현재 상담/근거 revision·유효 검토 안내자료를 최대100개씩 읽고 알려진 이름·전화·이메일·키를 제거한다. 직원4000/관리자12000 UTF-8 bytes 입력 cap은 테스트 단계의 보수적 크기 경계이며 특정 공급자 tokenizer가 아니다. 기능별 의미 schema/프롬프트·30일 코칭/이전 코칭 입력·전체 SQL 집계·분산 표본은 P10/P11에서 확장한다. 현재 foundation-v1 envelope는 기능·bounded text·근거 source whitelist·is_test만 허용한다.

quota와 비용은 접수 KST 날짜/월에 귀속된다. 월 원장의 reserved/charged와 요청별 reserved/charged를 Decimal로 관리한다. 직원800·관리자2000 출력 토큰과 같은 수의 추론 토큰을 출력 단가로 보수 예약하고 입력 cap도 예약한다. 실제 token/단가별 비용은 UsageAttempt에 남기며 성공/실패와 독립한다. 공급자가 결정되지 않아 이 단가/추론 정책을 운영 과금 규칙으로 검증한 것은 아니다. 실제 어댑터 도입 전에 공급자별 청구 단위를 재검증해야 한다. 현재 요청당 유료 호출은 없고 테스트 adapter는 bounded1응답이며 안전한 미수행 재시도만 최대2시도다.

worker.claim은 짧은 트랜잭션에서 RUNNING·token·120초 lease·10분 확인 상한·PREPARED attempt를 기록한다. 외부 I/O 구간에는 트랜잭션/공통 잠금을 유지하지 않는다. 계정당 RESERVED/RUNNING/UNKNOWN1개, 전역 RUNNING/UNKNOWN2개다. 전송 미수행이 보장된 경우만1회 재시도한다. 나머지 예외는 원문 로그 없이 UNKNOWN이고 자동 재전송하지 않는다. lease 만료도 UNKNOWN으로 회복하며10분 만료는 사용자 예약 반환·보수 비용 유지로 종료한다. RESERVED15분 만료는 전송 없이 반환한다. 새 작업을 만드는 것은 내부 명시적 접수뿐이며 worker/scheduler/GET은 생성하지 않는다.

`ledger.settle`은 성공 결과 저장·quota 예약→성공·slot 성공·월 예약→정산을 같은 트랜잭션으로 처리한다. 실패/권한 회수는 quota/미성공 slot만 반환하고 과금된 시도 비용은 남긴다. 종료된 늦은 응답은 결과를 노출하지 않는다. 이미 보수 정산한 비용을 낮추지 않고 새로 확인한 초과 비용만 추가한다. 버전/입력 변경은 결과를 stale로 표시하고 자동 고객 수정/진행 처리는 하지 않는다.

`privacy.invalidate_results`는 고객/revision/knowledge/이전 결과와 AI_APPLIED 근거의 전이 그래프를 방문 집합으로 순회한다. queued 입력·결과 본문/캐시를 제거하고 게시를 해제한다. 실행 중이면 보수 비용을 남기고 취소한다. 이미 성공한 quota/slot·발생 비용은 유지한다. 모든 AIResult는 원문 없는 tombstone으로 남을 수 있으며 Source edge는 제거한다. 추가 미처리 모델의 guard는 유지한다. 실제 별도 PG 연결 경합·worker child process 중단/재시작·삭제 롤백·순환 그래프·권한/CSRF·캐시/alias 검증은 [P9_VERIFICATION.md](P9_VERIFICATION.md)에 기록한다.
