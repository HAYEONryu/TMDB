# 2단계 기반 구조와 후속 구현 계약

기준: 설계서 v1.1. 업무 규칙 변경 없음. 이번 단계는 모델·인증 기반이다.

## 데이터 모델

| 도메인 | 모델·주요 보장 |
|---|---|
| accounts | UUID User, 전화번호 unique/010 형식, ADMIN/EMPLOYEE, 변경필수·session_version. 추가 LoginFailure는 HMAC 키·시각만 보관 |
| sites | 공백/영문 대소문자 정규화 name_key unique, singleton GlobalSettings, nullable FK + UUID 스냅샷 기본 현장 이력 |
| customers | 현장+전화 unique는 휴지통 포함, 이름/번호/enum/버전 검사, 조회 인덱스, 상담 변경 필드 이력, CustomerDeletionRequest |
| assignments | 고객당 미종료 할당 하나, 종료 시각/사유 정합성, 직원/할당일 인덱스 |
| callbacks | 고객당 PENDING 하나, 상태/완료자/완료·취소 시각 검사, 예정일 부분 인덱스 |
| imports | 검증/확정/만료/실패 batch, 원본 행 번호별 후보·오류 결과 unique, 고객에서 nullable batch 참조 |
| operations | 처리자+작업+key unique, 처리자+mutation unique, 고객 FK receipt, 예약 종류+업무날짜 unique, lease·시도·오류 필드, 비식별 OperationEvent |

도메인 UUID 모델 16개와 로그인 제한 보조 모델 1개다. GlobalSettings는 singleton 정수 PK라는 의도적 예외다. 모든 변경 가능한 도메인 엔터티는 생성·수정 시각을 가진다. Django `DateTimeField`는 PostgreSQL timestamptz로 생성되며 USE_TZ=true로 UTC 저장, 업무 날짜는 Asia/Seoul 기준이다.

`Customer.current_assignment`와 Assignment.customer의 순환은 assignments 0001 → customers 0001 → assignments 0002 순서로 연결한다. 종료 사유 CHECK의 NULL 허용 문제는 assignments 0003에서 보완했다. sites 0002는 GlobalSettings 1번 행을 생성한다. 비밀번호·공용 관리자 계정은 migration에 없다.

## 디비 제약과 서비스 검증의 구분

- DB는 unique·부분 unique·enum·형식·버전·상태 CHECK·FK를 보장한다. 소프트 삭제 고객의 current_assignment는 null이어야 한다.
- 현재 할당의 고객 일치·미종료 여부는 `Customer.clean()`에서 검증한다. 삭제 요청의 요청 당시 할당/고객 일치는 `CustomerDeletionRequest.clean()`에서 검사한다. Django `save()`는 `full_clean()`을 자동 호출하지 않으므로 후속 도메인 서비스가 잠금 안에서 재검증해야 한다. 임의 QuerySet update를 업무 API에 노출하지 않는다.
- 고객명·연락처 수정 금지는 후속 등록/수정 서비스의 허용 필드 검사로 보장할 계약이다. 현재 고객 변경 API는 없다. 모델 직접 SQL 갱신을 막는 트리거를 구현한 것으로 보고하지 않는다.
- `notes`는 시스템 승인 문구를 추가할 공간이 있어야 하므로 TextField에 디비 길이 상한을 두지 않았다. 사용자 입력 기본 10,000자/복구 후 기존 전체 길이 편집 예외는 해당 수정 API 구현 시 검증한다.
- Customer·현장 영구 삭제의 최종 서비스는 아직 없다. Django CASCADE와 순환 참조 정리는 모델 테스트로 확인했지만, JSON result/target_ids 안의 개인정보·IdempotencyRecord까지 제거하는 절차는 후속 서비스에 반드시 포함해야 한다. 현재 receipt를 생성하는 업무 API는 없다.

## 쓰기 잠금과 트랜잭션

`apps.common.transactions.business_write()`는 PostgreSQL transaction-level advisory lock `7420192701`을 획득한다. 잠금 순서는 공통 lock → 사용자 ID 정렬 → 필요한 전역 설정 → 현장 ID 정렬 → 고객 ID 정렬 → 할당/재콜이다. 이번 비활성화 서비스는 변경 대상 사용자·고객·할당을 그 순서대로 잠근다. JOIN으로 할당 행을 먼저 잠그지 않도록 고객 잠금에 `of=("self",)`를 쓴다.

잠금 timeout 기본 5,000ms, PostgreSQL 55P03/40P01/40001은 롤백 후 50ms 간격으로 1회만 재시도한다. 재시도에도 실패하면 인증 쓰기 API는 503 `TEMPORARY_UNAVAILABLE`로 응답한다. 무한 재시도하지 않는다. 내부 사용자 접근 변경 서비스도 같은 재시도 규칙을 사용한다.

신규 업무 쓰기는 이 공통 경계를 거쳐야 한다. 분배·상담 변경·삭제 요청·승인·업로드 확정의 실제 서비스와 요청별 receipt 생성은 후속 단계다. 읽기와 엑셀 파싱은 공통 쓰기 lock 밖에서 처리한다.

## 인증·세션

1. Django ModelBackend가 전화번호와 해시를 검증하고 서버 세션을 만든다.
2. DB의 user 활성·session_version을 매 요청 확인한다. 세션 버전이 다르거나 해시 검증이 무효하면 로그아웃 처리한다.
3. `/api/me`, 비밀번호 변경, 로그아웃만 초기 변경 상태에서 허용한다. 업무 API·역할별 페이지는 차단한다. 이 단계에서 공개 경로는 로그인·정적 자산·DB health다.
4. 첫 변경/본인 변경은 현재 비밀번호를 검증한다. 비밀번호 변경과 session_version 증가·작업 이벤트를 한 트랜잭션으로 저장한 뒤 현재 세션의 해시·버전만 갱신한다.
5. 관리자 재설정은 dodream, 변경필수 true, 버전 증가를 한 트랜잭션으로 저장한다. 대상의 기존 세션을 살려두지 않는다. 관리자가 본인을 재설정해도 같다.
6. 서버 역할 검사는 `role`을 사용한다. `is_staff`·`is_superuser` 플래그로 업무 권한을 우회할 수 없다. 마지막 활성 관리자의 비활성화/직원 전환은 직렬화된 서비스 안에서 차단한다.

비활성화 내부 서비스는 모든 현장·날짜에서 미진행 현재 할당만 종료하며 고객 version을 증가시킨다. 진행 할당·상담정보는 유지한다. 직원→관리자 전환만으로 배정을 종료하지 않는다. 상태 변경 UI/API는 후속 단계에서 연결한다.

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

기본 현장·관리자 저장 이동 UX·미진행 통계 집합·업로드 실패 상태 정책·23시 시작일/lease 정책은 이번 업무 기능에 연결하지 않았으므로 아직 미정이다. 승인된 업무 규칙을 바꾸지 않았다.
