# P12 AI 23항목 검수 결과

실행 완료 시각(UTC): `2026-11-05T17:29:43.829990+00:00`. 실제 실행한 Django 395개 결과와 동일 소스 SHA를 대조했다.

미실행·실패·skip·소스 변경을 통과로 처리하지 않는다. 자동 테스트 수와 검수 문항 수는 다르다.

| ID | 설계서 검수 항목 | 결과 | 실행한 테스트 ID |
|---|---|---|---|
| 18.8-01 | 직원의 세 AI 기능은 버튼을 눌렀을 때만 실행되고 합산 하루 30회로 제한된다. | 통과 | `tests.test_p9.P9Tests.test_shared_three_feature_quota_reservation_limit_and_database_constraint`<br>`tests.browser_p10.P10BrowserTests.test_summary_questions_read_only_and_mobile_no_automatic_generation` |
| 18.8-02 | 화면 진입·자동 저장·예약 작업·관리자 알림 폴링에서 AI 생성 호출이 발생하지 않는다. | 통과 | `tests.test_p12.P12Tests.test_all_read_routes_and_scheduler_create_no_tasks_attempts_or_reservations`<br>`tests.browser_employee.EmployeeBrowserTests.test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions`<br>`tests.browser_p7.P7BrowserTests.test_notifications_poll_once_per_visible_minute_and_on_return` |
| 18.8-03 | 29회 성공 상태에서 여러 탭이 동시에 요청해도 성공+예약 합계가 30회를 넘지 않는다. | 통과 | `tests.test_p9.P9Tests.test_quota29_distinct_keys_race_reserves_only_one_then_success30` |
| 18.8-04 | 동일 요청 키 재시도·결과 재조회·이중 클릭에 호출과 차감이 중복되지 않는다. | 통과 | `tests.test_p9.P9Tests.test_concurrent_same_key_and_quota29_never_double_reserve`<br>`tests.browser_p10.P10BrowserTests.test_lost_submission_response_reload_retries_same_key_and_charges_once` |
| 18.8-05 | 확실한 실패는 예약 횟수를 반환하고, 결과 성공 후 응답 유실은 재조회해 동일 결과를 받는다. | 통과 | `tests.test_p9.P9Tests.test_only_guaranteed_not_performed_retries_once_same_task_without_extra_quota`<br>`tests.browser_p10.P10BrowserTests.test_lost_submission_response_reload_retries_same_key_and_charges_once` |
| 18.8-06 | 외부 처리 여부가 불명확한 timeout을 무조건 새 유료 호출로 재실행하지 않는다. | 통과 | `tests.test_p9.P9Tests.test_unknown_holds_then_releases_once_keeps_conservative_cost_and_rejects_late_success`<br>`tests.test_p9.P9Tests.test_real_worker_process_crash_after_claim_then_restart_does_not_resend` |
| 18.8-07 | 자정 전 접수·자정 후 완료는 접수일 한도로 계산하며 다른 날짜의 예약을 차감하지 않는다. | 통과 | `tests.test_p9.P9Tests.test_kst_day_and_budget_month_remain_at_submission_across_midnight` |
| 18.8-08 | AI 생성 자체는 진행 이력으로 남지 않고, 선택 적용 후 실제 저장한 값만 진행으로 남는다. | 통과 | `tests.test_p10.P10Tests.test_three_post_features_schemas_usage_and_readonly_customer`<br>`tests.test_p10.P10Tests.test_apply_normal_mutation_atomic_provenance_before_after_and_replay`<br>`tests.test_p10.P10Tests.test_noop_ai_application_does_not_create_revision_or_progress` |
| 18.8-09 | AI 처리 중 회수·재분배·삭제·비활성화가 발생하면 직원에게 결과를 노출하거나 적용하지 않는다. | 통과 | `tests.test_p12.P12Tests.test_running_result_revoked_by_recall_reassignment_trash_or_deactivation`<br>`tests.browser_p10.P10BrowserTests.test_recall_between_view_and_apply_clears_private_result_and_never_saves` |
| 18.8-10 | AI 요청 시점과 다른 버전의 고객에 추천을 조용히 덮어쓰지 않는다. | 통과 | `tests.test_p10.P10Tests.test_stale_result_rejects_source_attribution_manual_explicit_save_allowed`<br>`tests.browser_p10.P10BrowserTests.test_stale_result_after_other_save_read_only_no_selected_apply` |
| 18.8-11 | 없는 날짜·가격·계약 여부를 임의로 생성하지 않으며 불명확한 정보는 확인 필요로 표시한다. | 통과 | `tests.test_p10.P10Tests.test_relative_date_reanchored_to_today_or_unknown_timestamp_becomes_no_suggestion`<br>`tests.test_p10.P10Tests.test_missing_price_or_contract_confirmation_is_no_suggestion`<br>`tests.test_p11.P11Tests.test_only_reviewed_valid_knowledge_and_fact_quotes` |
| 18.8-12 | 직원이 다른 직원의 AI 결과 ID를 사용해도 조회되지 않는다. | 통과 | `tests.test_p10.P10Tests.test_current_assignment_and_actor_checked_for_generation_result_and_apply` |
| 18.8-13 | 상담기록 안의 지시문을 실행하거나 외부 URL·도구·SQL을 호출하지 않는다. | 통과 | `tests.test_p12.P12Tests.test_prompt_injection_is_data_and_tools_sql_and_network_are_not_executed`<br>`tests.browser_p10.P10BrowserTests.test_result_renders_html_as_text_and_never_executes_or_links_it`<br>`tests.test_p11.P11Tests.test_source_injection_url_html_key_numeric_claim_fails_closed` |
| 18.8-14 | 일요일 이외 주간 브리핑 생성 요청은 서버에서 거부하고 기존 결과 읽기는 허용한다. | 통과 | `tests.test_p11.P11Tests.test_weekly_sunday_year_boundary_cutoff_shared_slot_and_weekday_read` |
| 18.8-15 | 주간 범위가 한국 시간 월요일 00:00~일요일 요청 시각이며, 아직 지나지 않은 일요일 업무를 포함했다고 표시하지 않는다. | 통과 | `tests.test_p11.P11Tests.test_weekly_sunday_year_boundary_cutoff_shared_slot_and_weekday_read`<br>`tests.test_p11.P11Tests.test_future_revisions_and_system_notes_excluded` |
| 18.8-16 | 관리자 동시 요청에서도 같은 주 브리핑, 같은 직원의 당일 코칭, 같은 현장의 당일 가이드가 중복 생성되지 않는다. | 통과 | `tests.test_p12.P12Tests.test_all_admin_features_share_one_slot_under_concurrent_requests` |
| 18.8-17 | 코칭은 실제 처리자별 30일 이력과 기존 코칭을 사용하고, 데이터가 없으면 부족함을 표시한다. | 통과 | `tests.test_p11.P11Tests.test_inactive_and_promoted_actual_workers_in_weekly_sql_totals`<br>`tests.test_p11.P11Tests.test_last_three_valid_coachings_and_older_actions_are_sources`<br>`tests.test_p11.P11Tests.test_first_coaching_no_history_and_insufficient_comparison` |
| 18.8-18 | 상담 메모 반복 저장을 별도 통화 횟수·별도 고객 반응으로 중복 집계하지 않는다. | 통과 | `tests.test_p11.P11Tests.test_latest_customer_actor_korean_day_and_actual_author_not_assignee`<br>`tests.test_p11.P11Tests.test_reaction_multilabel_distinct_customers_and_classification_cache` |
| 18.8-19 | AI 생성 가이드는 검토·게시 전 직원에게 노출되지 않는다. | 통과 | `tests.test_p11.P11Tests.test_guide_draft_hidden_review_publish_read_only_no_extra_calls`<br>`tests.browser_p11.P11BrowserTests.test_guide_review_publish_employee_read_only_and_mobile` |
| 18.8-20 | 고객·현장 영구 삭제 시 원문뿐 아니라 관련 AI 입력·출력·비교 코칭·가이드의 파생정보 처리도 검증한다. | 통과 | `tests.test_p9.P9Tests.test_recursive_deletion_cycles_unpublishes_and_preserves_usage_other_site`<br>`tests.test_p9.P9Tests.test_source_via_revision_and_site_knowledge_invalidates_and_removes_raw_material`<br>`tests.test_p11.P11Tests.test_deletion_propagates_previous_coaching_and_excludes_future_inputs`<br>`tests.test_p11.P11Tests.test_customer_hard_delete_removes_classification_and_mixed_guide_publication` |
| 18.8-21 | 키 없음·예산 소진·AI 공급자 장애에도 기본 DB 업무가 계속 동작한다. | 통과 | `tests.test_p12.P12Tests.test_missing_key_invalid_config_budget_and_provider_failure_allow_real_customer_save` |
| 18.8-22 | `.env.ai`는 git check-ignore에 포함되고 .env.ai.example은 제외된다. 실제 키 파일이 Git 추적 대상과 Docker 빌드 컨텍스트에 없다. | 미완료 | `tests.test_ai_boundary.AIConfigurationTests.test_file_loaded_only_in_web_and_worker`<br>`tests.test_ai_boundary.AIConfigurationTests.test_non_ai_process_drops_inherited_ai_environment`<br>`boundary:git_secret_boundary` (passed)<br>`boundary:docker_ignore_rules` (passed)<br>`boundary:compose_secret_boundary` (passed)<br>`boundary:docker_build_context` (not_run)<br>`boundary:docker_image_layers` (not_run) |
| 18.8-23 | 실제 키가 브라우저 응답·소스맵·로그·문서·테스트 fixture에 포함되지 않는다. | 통과 | `tests.test_p12.P12Tests.test_generated_secret_never_enters_ai_responses_usage_or_failure_logs`<br>`tests.browser_p12.P12BrowserTests.test_employee_generation_and_encrypted_queue_never_receive_server_key`<br>`tests.browser_p12.P12BrowserTests.test_admin_generation_review_and_publication_never_receive_server_key`<br>`tests.test_ai_boundary.AIConfigurationTests.test_configured_application_and_django_log_handlers_redact` |

실제 공급자는 연결하지 않았으며 유료 호출은 없다. 생성·장애·사실성 검수는 가짜 응답과 지정된 근거 사례 범위다. 자연어 의미·실제 모델 품질 전체를 보증하지 않는다.

경계 원시 근거: `.local/p12-boundary.json`.
- `docker_build_context`: Docker 엔진/CLI가 없어 실제 build context·이미지·각 레이어/history 검사를 실행하지 못함.
- `docker_image_layers`: Docker 엔진/CLI가 없어 실제 build context·이미지·각 레이어/history 검사를 실행하지 못함.

**22/23항목 통과.** 원시 근거: `.local/p12-test-results.json`, `.local/p12-ai-acceptance.json`. 재실행 방법과 제한은 [P12_VERIFICATION.md](P12_VERIFICATION.md)를 따른다.
