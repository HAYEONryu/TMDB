# P7 삭제 요청·승인·영구 삭제 검증

2026-11-05, Asia/Seoul. 사용자의 P7 구현·중단 지점 재개 요청에 따라 v2.0과 개발 계획의 P7까지 구현·실행·검증했다. P8은 시작하지 않았다. 설계서 원문·기존 파일·사용자 변경·개발 계정 비밀번호를 보존했다. `sources/`는 수정하지 않았으며 실제 개인정보·유료 호출·운영 배포는 없다.

## 1. 구현 결과

| 범위 | 결과 |
|---|---|
| 직원 요청 | 오늘/나의 DB 행별 버튼·해당 행 저장 선행·확인창·제출 중 중복 방지·요청완료 유지·현재 본인 할당 검사 |
| 요청 상태 | 고객당 PENDING 하나·원래 요청자 보존·요청만으로 버전/상담/할당/진행 변경 없음·승인 전 상담 계속 가능 |
| 관리자 알림 | 대시보드 상단 전체 현장50행·전체 건수·활성60초/진입/복귀/수동 조회·읽기만 수행 |
| 승인 | 최신 비고와10,000자 원문 보존·한국 승인 시각 문구1회·휴지통/할당 종료/승인/revision/receipt 원자성 |
| 경합/실패 | 두 관리자·저장/승인 커밋 순서·실패 롤백·응답 유실 동일 key/body 재확인·복구 후 재삭제 방지 |
| 고객 영구 삭제 | 휴지통 행별 확인·고객/이력/재콜/요청/receipt·같은 현장 업로드 캐시 원문 제거·타 고객/현장 보존 |
| 현장 영구 삭제 | 정확 이름 확인·서명 증명·전체 관련 자료 삭제·기본 현장 대체/마지막 null·URL 갱신·예약 UUID snapshot 보존 |
| 삭제 후 보호 | 옛 직원 대기 저장 거부·자동 새 고객 등록 없음·삭제 metadata만 남기는 재시도 결과·향후 AI 정리 누락 차단 |

기존 삭제 요청 모델·제약을 사용하므로 새 migration/패키지는 없다. 일반 휴지통 이동·복구·분배·회수·자동 저장 규칙은 유지했다. 시스템 승인 문구는 `[YYYY-MM-DD HH:mm] 고객요청으로 인한 삭제`이며 일반 상담 입력 한도 때문에 기존 원문을 잘라내지 않는다.

## 2. 실행한 검사

```sh
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py check
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python manage.py test tests.browser_p7 --noinput -v 2
```

**고유 테스트 총271개 통과: Django256개 + Node15개.** Django는 서버218개·실제 Chromium34흐름·실제 PostgreSQL 1만 건 성능4개다. 기존 P6의242개를 재실행하고 P7 서버21개·브라우저7개·성능1개를 추가했다. 전체 Django 최종 실행102.910초(`.local/p7-tests.log`), Node0.129초(`.local/p7-queue.log`)다. 검수 문항 수와 자동 테스트 개수는 다르며 전체 사이트 완료를 의미하지 않는다.

전체 통과 후 모바일 알림 표의 가로 스크롤/열 너비, 현장 삭제 후 URL 대체, 대기 정보 폐기 후 범위 갱신을 보완했다. 최종 화면의 P7 Chromium7개를 다시 실행해 **7개 모두 통과/14.283초**했다(`.local/p7-browser-final.log`). 이 재실행을 고유271개에 더하지 않았다. 최종 UI 수정 뒤 전체256개를 다시 실행한 것은 아니다.

### 설계서18.7의18항목 대응

| 순서 | 검수 내용 | 실제 근거 |
|---|---|---|
| 1 | 오늘/나의 DB 행별 요청·일괄 없음 | browser_p7: row_request·lost_request, 직원 표 행별 버튼 |
| 2 | 단건 처리·제출 중 클릭 방지 | browser_p7: row_request·lost_request, 단일 전송/본문 검사 |
| 3 | 해당 행 저장 실패 시 요청0 | browser_p7: cancel_confirmation_and_offline_save |
| 4 | 요청완료·새로고침·다른 탭·실패 미완료 | browser_p7: lost_request_response_same_key_reload_and_other_tab_pending |
| 5 | 타인/과거 할당 거부 | test_p7: request_authentication_structure_assignment_and_version |
| 6 | 중복/응답 유실 PENDING 하나 | test_p7: request_is_metadata_only_duplicate_keys_and_current_owner_pending, browser_p7: lost_request |
| 7 | 요청 시 상담/할당/삭제 불변 | test_p7: request_is_metadata_only, browser_p7: row_request |
| 8 | 관리자 전체 현장 동일 목록 | test_p7: global_notifications_pagination_and_read_does_not_approve, browser_p7: approval_global_list |
| 9 | 활성60초·행별 API 없음 | browser_p7: notifications_poll_once_per_visible_minute_and_on_return |
| 10 | 승인 시 최신 상담 사용 | test_p7: approval_latest_notes·save_before_approval, browser_p7: approval_global_list |
| 11 | 휴지통·한국 시각 승인 문구 | test_p7: approval_latest_notes_long_notes_empty_and_no_staff_progress |
| 12 | 빈 비고/10,000자 보존 | 같은 서버 테스트의 빈 값·최대 길이 실제 저장 |
| 13 | 동시 승인/재시도1회 | test_p7: concurrent_approvals_one_note_one_event·two_admins_replay, browser_p7: 승인 응답 유실 |
| 14 | 승인 후 저장 거부·성공 표시 금지 | test_p7: approval_commits_before_waiting_save, browser_p7: blocked_employee_queue |
| 15 | 회수/재분배/비활성화 뒤 승인 | test_p7: request_survives_recall_reassignment_and_inactive_requester·approval_after_recall_without_current_assignment |
| 16 | 일반 삭제 CLOSED·문구 없음 | test_p7: general_trash_closes_pending_without_approval_note |
| 17 | 복구 후 재삭제 없음·새 요청 가능 | test_p7: two_admins_replay_preserves_first_approval_and_restore_is_not_redeleted |
| 18 | 영구 삭제 시 요청/알림 제거 | test_p7: hard_customer_deletes_all_history_receipts·site_deletion, browser_p7: hard_delete2흐름 |

추가로 실제 CSRF/identity 검사, revision 오류 주입 롤백, 독립 PG 연결 저장/승인 양방향 커밋 순서, 알림50+2 페이지·조회 변경0, 활성 고객 영구 삭제 거부·버전 충돌, 같은 전화 새 UUID·다른 현장 같은 전화 보존을 검증했다. VALIDATED 업로드의 삭제된 행은 다시 확정해도 재생성되지 않고 다른 후보는 등록된다. COMMITTED 업로드 원문과 과거 비태깅 receipt도 지우며 원래 집계는 유지한다.

현장 테스트는 오입력·다른 actor·만료 서명 거부·마지막 현장 null·타 현장/예약 snapshot 보존을 포함한다. 브라우저는 실제 PBKDF2 로그인·네트워크 응답 유실·새로고침·같은 본문 재확인·이후 페이지 재조회와390px 화면을 확인했다. 스크린샷 `.local/qa/p7-notifications-mobile.png`, `p7-approval-desktop.png`, `p7-site-deleted-mobile.png`를 검토했고, 모바일 알림은 표 내부에서 가로 스크롤한다.

### 실제 PG 1만 건 성능

| 작업 | 최종 전체 실행 결과 |
|---|---|
| 현장 영구 삭제 | 고객10,000·현재 할당10,000·재콜100·삭제 요청100, **4.181초** |
| 업무 잠금·RSS | **3.769초·165.69MiB** |
| 통과 기준 | 총30초·최대 잠금10초·프로세스 peak RSS512MiB 이내 |
| 업로드 회귀 | 검증2.291/확정2.260·합계4.551초·최대 잠금2.246초 |
| 분배/수동 회수 회귀 | 3.332/0.767·합계4.099초·최대 잠금3.331초 |
| 자동 회수 회귀 | 0.671초·최대 잠금0.650초 |

원시 `.local/p7-performance.json`과 전체 로그를 보존했다. 실제 별도 테스트 DB에서 측정했으며20명 동시 운영 SLA나 운영 전체 데이터 삭제를 검증한 것은 아니다. 기준을 늘리지 않았다.

## 3. 실패 이력·보완

초기 브라우저 폴링 검사는 페이지에 이미 설치된 native timer 뒤에 가짜 시계를 설치해 실패했다. 재로드 전 시계를 설치하도록 수정했다. 이어서 첫 GET 처리 중 visible 복귀 이벤트가 겹칠 때 추가 조회가 생략되는 문제를 확인해 진행 중 조회 뒤 한 번 갱신하고 aria-busy로 완료를 확인하도록 보완했다. 이후 단일 검사·전체256개·최종 브라우저7개를 통과했다. 실패 로그도 보존했다.

초기390px 알림 표가 한국어 글자별로 줄바꿈되는 것을 직접 확인해 표 최소 폭/열 너비·가로 스크롤을 보완했다. 현장 삭제 직후 표는 대체됐지만 URL에 삭제된 현장 ID가 남는 문제도 수정하고 재로드 검증을 추가했다. 사용자 업무 규칙과 설계서는 변경하지 않았다.

샌드박스 내 PG 접근 경고는 필요한 로컬 명령만 권한 확장해 실제 PG에서 재실행했다. PG 시작의 자동 승인 검토 시간 초과1회는 재시도로 해소했으며 최종 미해결 승인 차단은 없다.

## 4. 실행 환경·보호 확인

실제 개발 PG에 연결해 migrate(미적용0)·모델 차이0·check 이상0·collectstatic을 실행했다. 로컬 Gunicorn2 workers의 `/healthz`200·새 보호 API 익명401·변경 정적 파일6개의 HTTP 내용/길이/원본 SHA 일치를 확인했다(`.local/p7-runtime.json`). 개발 DB 사용자3명·고객65건·현재 할당0·미처리 삭제 요청0과 기존 비밀번호를 유지했다. 파괴적 검사는 `test_tm_dev`에서만 수행했고 테스트 DB는 종료 시 제거됐다.

v2.0 원문 SHA-256은 `0c2f3326868454aa654c0d367b5ec7b75e3ecd4f80510fb3c96fbae0657e6194`로 유지한다. `.env.ai`는0600·Git 비추적/제외이고 Docker 제외 규칙을 유지한다. 예시의 키는 비어 있다. 실제 키를 브라우저·로그·이미지에 넣지 않으며 이번 작업에서 실제 공급자 호출은 없다. Docker 엔진이 없으므로 이미지 생성/레이어 검사는 미실행이다.

## 5. 확정 규칙·기본값·미완료

| 구분 | 내용 |
|---|---|
| 사용자 확정 규칙 | 저장 선행·승인 전 상담 유지·한국 시각 문구1회·일반 삭제 CLOSED·회수 후에도 승인·영구 삭제 관련 자료 제거·확인창 |
| 설계서 기본값 | 활성 알림60초·목록 서버 페이지·7일 재시도 보관·공통 업무 잠금·기본 현장 생성순 대체 |
| 구현 기본값 | 알림50행·동률 UUID 정렬·actor/site/key/updated_at 서명 증명·원문 없는 HMAC tombstone·200개씩 receipt 검색 |
| 후속 연동 | P9 실제 AI 모델의 원문/혼합 결과/코칭 참조 재귀 무효화 구현 필요. 현재 미처리 모델 추가 시 원자적 삭제 차단 가드만 검증 |

서버는 오프라인 브라우저의 암호화 대기 입력을 원격 삭제할 수 없다. 해당 값은 현재 할당/삭제 검사로 전송을 거부하고 명시적 폐기를 요구하며 새 고객으로 자동 등록하지 않는다. 백업에 남는 원문의 보관 만료·실제 복원은 후속 운영 단계다. Safari/Firefox·실제 모바일·Docker 실행·운영 HTTPS·유료 API·운영 배포는 검증하지 않았다.

P7을 막는 미해결 문제는 없다. 직접 확인은 [README15절](../README.md#15-p7-삭제-요청승인영구-삭제-확인)을 따른다. 다음 P8은 기본 업무69항목 통합 검수·가짜 seed·키 없음/AI 설정 오류의 기본 업무 격리 확인이다. 이번 요청에서는 진행하지 않는다.

최종 정리: 문서 링크35개·코드블록/충돌·Python compileall·JS20파일 구문·Git diff 검사를 통과했고 원문 SHA·AI 파일0600/비추적/제외·빈 예시 허용을 확인했다(`.local/p7-audit.json`). 개발 DB 사용자3명·고객65건·현재 할당0·PENDING 요청0을 다시 읽어 확인했다. 작업 소유 Gunicorn master/worker·전용 PostgreSQL을 정상 종료했으며 pidfile 제거·8000 포트 리스너 없음·DB 중지 상태를 확인했다(`.local/p7-shutdown.json`). README1절 순서로 다시 실행할 수 있다.
