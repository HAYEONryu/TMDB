# P10 직원 AI3종·선택 적용 검증

2026-11-05, Asia/Seoul. 설계서 v2.0과 개발 계획의 P10을 구현했다. 기존 업무 규칙·설계서·sources·사용자 변경·개발 계정/비밀번호·고객 자료를 보존했다. 실제 개인정보·유료 API/자원·배포는 없다. 실제 공급자 어댑터는 비활성이고 fake는 명시적 테스트 설정/DB에서만 실행했다. P11 관리자 보고서는 시작하지 않았다.

## 1. 구현

| 범위 | 구현 결과 |
|---|---|
| 직원 UI | 오늘/나의 DB 행별 정리·요약·질문3버튼, 합산 성공/예약/잔여, 기존 결과 조회, PC 비교표/390px 카드 |
| 접수 | 해당 행 편집 확정→그 행 일반 저장→직원 POST. 실패/충돌/오프라인이면 새 AI 작업0, 다른 행 최초 타이머 유지 |
| 결과 | 기본 미선택·현재 값/제안/근거 비교, 비고 교체 확인·선택 필드만 대기열 반영. 요약/질문은 읽기 전용 |
| schema | employee-v1: 정리6필드 SUGGESTION/NO_SUGGESTION, 요약4영역, 질문3~5개·목적/근거. enum/길이/원문 인용/ID whitelist/키 노출 검사 |
| 날짜/사실 근거 | 원문 작성 시각·접수 KST 날짜 제공. 상대 날짜는 알려진 원문 날짜 기준, 모호한 날짜·입력에 없는 금액·불명확한 계약 상태는 확인 필요/추천 없음. 날짜 ISO 정규화 |
| 일반 저장 | source_ai_result_id와 현재 역할/담당·할당·버전·유효 CLEANUP 제안을 검사. 실제 변경만 AI_APPLIED/revision/진행/receipt와 한 트랜잭션 |
| 지속 대기열 | 선택값·AI 출처/필드를 IndexedDB 암호문에 보관. 응답 유실 재시도/재로그인 복구에서 같은 mutation/source ID 유지 |
| 상태 조회 | 결과 창 open+visible일 때3초 GET, 닫힘/숨김/완료/권한 상실 시 중단. GET은 새 생성 없음·알 수 없는 접수는 동일 key 명시적 확인 |
| 보호/운영 경계 | 텍스트 DOM 표시·임의 URL 제거·회수 시 열린 결과 비움·낡은 버전 선택 적용 거부. 일반 실행은 생성 비활성·기본 업무/기존 결과 유지 |

새 모델/migration/의존성은 없다. P9의 원본 AI FK·quota/비용/worker를 사용한다. P9 foundation-v1 결과는 읽을 수 있지만 직원 선택 적용은 employee-v1의 유효 CLEANUP만 허용한다. 현재 직원3기능은 employee-v1, 관리자 내부 기반은 foundation-v1로 구분한다.

## 2. 재현 명령

```sh
.venv/bin/python scripts/local_db.py start
.venv/bin/python manage.py test tests tests.browser_flow tests.browser_p2 tests.browser_imports tests.browser_p4 tests.browser_employee tests.browser_p6 tests.browser_p7 tests.browser_p10 tests.performance_imports tests.performance_assignments tests.performance_scheduler tests.performance_deletions --testrunner=config.acceptance_runner.AcceptanceRunner --evidence-label=p10 --noinput -v 2
node --experimental-default-type=module --test tests/employee_queue.test.mjs
.venv/bin/python scripts/verify_acceptance.py --results .local/p10-test-results.json --output .local/p10-acceptance.json --markdown docs/P10_BASIC_ACCEPTANCE.md --stage P10
```

**총356개 통과 = Django338개 + Node18개.** Django는 서버/근거/복원287개·실제 Chromium47흐름·PG1만 건 성능4개다. P9의314개에 P10 서버26·브라우저13·Node3개를 추가했다. 최종 Django150.971초(`.local/p10-tests.log`), Node0.137초(`.local/p10-queue-final.log`). 개별338개 모두 passed·skip0·실행 전후 소스 해시 동일이다. 이후 앱 코드는 바꾸지 않고 문서와 로컬 검증 기록만 갱신했다.

기본 **69/69항목 재통과**를 [별도 결과표](P10_BASIC_ACCEPTANCE.md)에 기록했다. `.local/p10-test-results.json`, `p10-acceptance.json`이 원시 근거이며 P8/P9 개별 결과/문서는 보존했다. AI23항목 전체 완료나 실제 유료 모델 품질 검증을 뜻하지 않는다.

| 가짜1만 건 성능 | 최종 결과 | 최대 업무 잠금 |
|---|---|---|
| 업로드 검증/확정 |2.318/2.431·합계4.749초 |2.412초 |
| 랜덤 분배/수동 회수 |3.573/0.765·합계4.338초 |3.571초 |
| 자동 회수 |0.757초 |0.743초 |
| 현장 영구 삭제 |4.830초 |4.309초 |

프로세스 peak RSS149.67MiB, 각 총30초/잠금10초/RSS512MiB 기준을 통과했다.20명 동시 운영 SLA 검증은 아니다. 가짜 기본 자료의 실제 별도 DB 복원도36개 public 테이블을 대조해0.577초에 통과했다(`.local/p10-restore.json`,153,412바이트0600 dump). 이 fixture의 AI 테이블은 비어 있으며 populated AI 운영 복원은 P13에 남는다.

실제 개발 PG의 check 이상0·모델/migration 차이0·미적용0·정적27파일·Compose config 구문을 확인했다. 실제 키/설정 파일을 바꾸지 않고 임시 키 파일 누락/오류 각각의 독립 Gunicorn2 workers에서 health/로그인200·익명 업무401·정적9개 HTTP 내용/길이/SHA 일치를 검증했다(`.local/p10-runtime.json`). worker --once는 처리0/성공0, scheduler --once는 회수0/실패0이다.

개발 User/Customer 전체 값 digest를 이전 단계/이번 실행 전후와 대조해 사용자3명·고객65건·할당0·비밀번호/상담이 그대로임을 확인했다. 개발 AI 요청/시도/quota0·임시 test/restore DB 잔존0이다(`.local/p10-before.json`, `p10-development-data.json`). 모든 생성/선택 적용·파괴적 검사는 별도 가짜 테스트 DB에서만 실행했다.

### 기능별 실제 검사 근거

| 요구 | 실행 검사 |
|---|---|
|3종/생성만으로 변경 없음 | test_p10: three_post_features_schemas_usage_and_readonly_customer, browser: summary_questions_read_only_and_mobile_no_automatic_generation |
| 저장 선행·그 행만 | browser: cleanup_saves_target_only_default_unselected_compare_select_and_real_save·offline_save_failure_no_ai_request_or_quota, Node의 row deadline/AI stage |
| 선택만 적용/원문 보존 | test_p10: apply_normal_mutation_atomic_provenance_before_after_and_replay·partial_selection·no_suggestion_null, browser: selecting_notes_only_keeps_unchecked_call_recommendation_unchanged |
| 실패 원자성/무변경 | test_p10: ai_revision_failure_rolls_back_customer_callback_activity_and_receipt·noop_ai_application_does_not_create_revision_or_progress |
| stale/할당/타인 결과 | test_p10: stale_result_rejects_source_attribution_manual_explicit_save_allowed·current_assignment_and_actor·other_customer_result_id, browser: stale_result_after_other_save·recall_between_view_and_apply |
| 접수/저장 응답 유실 | test_p10: cache_and_original_key_response_loss·ai_save_receipt_recovery, browser: lost_submission_response_reload·lost_ai_applied_save_recovers_receipt |
| 암호화 출처/수동 수정 | browser: selected_ai_queue_survives_offline_reload, Node: AI selection atomic row·lost AI save same source ID·manual override clears provenance |
| 원문 시각 상대 날짜 | test_p10: old_relative_date_uses_original_note_timestamp·known_old_note_cannot_move_tomorrow·unknown timestamp·explicit_absolute_datetime·datetime_output_is_canonical |
| 근거/형식/키 | test_p10: schema_blocks_unknown_fields_unfounded_quote_and_null_suggestion·non_scalar_suggestion_status·echoed_key·missing_price_or_contract_confirmation·explicit_contract_confirmation_and_existing_price |
| 가용성/읽기/CSRF | test_p10: no_key_blocks_new_work_but_saved_result_and_core_remain_readable·availability_rejects_another_accounts_queue_header·post_identity_csrf_initial_password, browser: no_key_disables_buttons_and_existing_result_still_readable |
| 폴링/HTML 비실행 | browser: polling_only_visible_open_dialog·hidden_dialog_does_not_poll_and_return_only_reads_existing_task·result_renders_html_as_text_and_never_executes_or_links_it |

P9의 quota29 경합·KST 자정/월 경계·slot/조직 예산·UNKNOWN/중단 복구·원문 재귀 삭제도 전체 회귀에 포함한다. 기본69항목과 AI23항목은 다르며 이번 결과를 AI23/전체92 완료로 표시하지 않는다. 실제 모델의 한국어 사실성/가격/계약 추론 품질은 fake로 검증할 수 없다.

## 3. 실패·보완 이력

초기 관련71개에서 테스트 helper가 SUMMARY를 CLEANUP payload처럼 읽은 오류와 임의 할당 ID의 기대409/실제403 차이가 있었다. 기존 권한 계약을 유지하고 fixture만 수정했다. 최초 브라우저25개가 통과했지만 테스트의 중복 dialog.accept listener 오류가 로그에 보여 제거했다. 이후28개20.871초·P10/P9/보호 경계89개30.011초·Node18개가 통과했다.

화면 직접 점검에서 전역 dialog max-width 때문에 비교창이 좁았고 모바일 표의 제안 부분이 가려졌다. PC 폭을 넓히고390px은 필드별 원문/제안 카드로 바꿨으며 적용/닫기 버튼을 하단에 유지했다. 최종 화면13개20.603초를 통과했다. 대표 `.local/qa/p10-cleanup-desktop.png`, `p10-cleanup-mobile.png`, `p10-questions-mobile.png`를 직접 검토했다.

전체1차334개155.237초 통과 후 설계서 사실 근거 대조에 따라 가격/계약 추천을 보강했고, 관련69개30.400초가 통과했다. 전체2차336개152.712초를 통과한 뒤 마지막 schema 경계에서 비문자 status를 즉시 실패 처리하고 날짜를 ISO 정규화하도록 보완했다. 마지막 서버26개3.800초가 통과했으며 이 변경을 포함한 최종 전체 실행 결과를 아래에 기록한다. 중간 원시 로그/결과(`p10-tests-first`, `p10-tests-facts`, `p10-focused`, `p10-ui-focused`, `p10-schema-final`)는 삭제하지 않았다.

## 4. 기본값·한계·다음

| 구분 | 내용 |
|---|---|
| 사용자 확정 규칙 | 버튼으로만 생성·그 행 저장 선행·합산30·기본 미선택·실제 저장만 진행·현재 담당/할당/버전 재검사·null/추천 없음 유지 |
| 구현 기본값 | 상태3초·기존 결과 최근10개/현재 할당·표시 중 작업1개·직원 schema/prompt employee-v1·목적/인용 길이 제한·가격 표기 동일 근거 대조·보수적 계약 표현 검사 |
| 보관 | task/result ID·기능·버전 등 metadata만 sessionStorage. 선택한 상담 값과 AI 출처는 기존 AES-GCM IndexedDB payload. 미선택 전체 결과 원문은 영속 브라우저 캐시 없음 |
| 수동 편집/충돌 | 직접 바꾼 필드의 AI 출처 해제. 오래된 결과의 명시적 비교/재적용은 일반 편집으로 저장하며 이전 AI source를 억지로 유지하지 않음 |

가격/계약 표현·날짜 검사는 보수적인 서버 근거 검사이며 모든 자연어의 의미·진실성이나 완전한 익명화를 보장하지 않는다. 실제 공급자 연결/공식 단가·tokenizer·유료 품질/과금 검증은 아직 없다. fake는 테스트 설정과 test_tm_ DB에서만 실행하고 테스트 표시를 붙인다. 키를 채워도 실제 전송을 시작하지 않는다.

직접 확인은 [README18절](../README.md#18-p10-직원-ai3종선택-적용-확인)을 따른다. P11의 일요일 브리핑·실제 처리자30일/이전 코칭·팀 가이드 검토/게시, P12 전체 AI 검수/Docker 레이어, P13 운영 백업/암호화/외부 보관/AI 포함 복원·HTTPS·20명 SLA는 남았다. 이번에는 P10까지 완료하고 다음 P11 요청을 기다린다.

최종 정리: v2.0 원문 SHA 불변·AI 파일0600/비추적/제외·빈 예시 허용, 문서 링크57개/코드블록/충돌·Python compileall·JS21파일 구문·Git diff·동일 소스338개 결과/69문항을 확인했다(`.local/p10-audit.json`). 최종 PC/390px 비교·질문 화면을 직접 검토했다. 검증용 Gunicorn 두 시나리오/단발 worker·전용 PG는 정상 종료했으며 pidfile 제거·8000/55432 리스너 없음·DB 중지를 확인했다(`.local/p10-shutdown.json`). 개발 데이터는 보존했고 README1절 순서로 다시 실행할 수 있다.
