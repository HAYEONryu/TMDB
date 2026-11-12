"""Shared free-tier capacity, pacing and races; network is always blocked."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from django.db import IntegrityError, close_old_connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.ai_assistant import free_limits
from apps.ai_assistant.gemini_adapter import GeminiAdapter, rate_limit
from apps.ai_assistant.models import AIRequest, AIProviderQuota, AIProviderQuotaDay, AIProviderDispatch, AIQuotaBucket, AIBudgetMonth
from apps.ai_assistant.services import reserve, validate_config
from apps.ai_assistant.worker import claim, finish, reap, run_once, ProviderResponse
from apps.ai_assistant.ledger import settle
from apps.common.transactions import business_write
from apps.customers.models import Customer
from apps.customers.queries import KST
from tests.helpers import TEST_HASHERS, login, user
from tests import test_gemini_adapter as gemini_tests
from tests.test_gemini_adapter import CONFIG as PAID, wire
from tests.test_openai_adapter import payload_for
from tests.test_p4 import Fixtures

FREE = replace(PAID, usage_tier='free', input_price=Decimal(0), output_price=Decimal(0),
    free_tier_confirmed=True, free_project_id='synthetic-free-project', free_rpm=15, free_tpm=250000, free_rpd=500, free_limits_model=PAID.model)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=False, AI_CONFIG=FREE)
class FreeAILimitTests(Fixtures, TransactionTestCase):
    body = gemini_tests.GeminiQueueTests.body
    process = gemini_tests.GeminiQueueTests.process

    def task(self, feature='SUMMARY'):
        task = gemini_tests.GeminiQueueTests.task(self, feature)
        # The fixed clock makes created_at ties; use explicit fixture chronology.
        self.sequence += 1
        AIRequest.objects.filter(pk=task.pk).update(created_at=self.now-timedelta(seconds=1)+timedelta(microseconds=self.sequence))
        return task

    def setUp(self):
        self.now = datetime(2026, 11, 8, 15, tzinfo=KST)
        timer = patch('django.utils.timezone.now', return_value=self.now)
        self.clock = timer.start(); self.addCleanup(timer.stop)
        self.sequence = 0
        network = patch('http.client.HTTPSConnection', side_effect=AssertionError('NO_EXTERNAL_IO'))
        network.start(); self.addCleanup(network.stop)
        self.prepare(); self.customer = self.customers()[0]; self.assign(self.customer)
        self.customer.notes = '가짜 상담 관심'; self.customer.save()
        self.other_customer = self.customers(offset=10)[0]; self.assign(self.other_customer, self.other)
        self.other_customer.notes='가상 상담 기록';self.other_customer.save(update_fields=['notes'])

    def more_tasks(self, count):
        result = []
        for i in range(count):
            actor = user(f'01000000{i+10:03}', initial=False)
            customer = self.customers(offset=100+i)[0]; self.assign(customer, actor)
            customer.notes='가상 상담 기록';customer.save(update_fields=['notes'])
            task=reserve(actor, self.body(customer=customer))[0]
            AIRequest.objects.filter(pk=task.pk).update(created_at=self.now+timedelta(microseconds=i))
            result.append(task)
        return result

    def success_claimed(self, task):
        return finish(task.pk, task.lease_token, response=ProviderResponse(payload_for(task), 1000, 80, 40), now=self.clock.return_value)

    def test_global_reserved_capacity_precedes_personal_balance_and_costs_zero(self):
        with override_settings(AI_CONFIG=replace(FREE, free_rpd=2)):
            first = self.task(); self.task('TEAM_GUIDE')
            self.assertEqual((AIProviderQuotaDay.objects.get().reserved_count, AIProviderQuotaDay.objects.get().sent_count), (2, 0))
            with self.assertRaises(AccessError) as error: reserve(self.other, self.body(customer=self.other_customer))
            self.assertEqual(error.exception.code, 'AI_SERVER_DAILY_LIMIT')
            client = login(self.other); status = client.get('/api/ai/availability').json()
            self.assertEqual(status['remaining_count'], 40)
            self.assertFalse(status['generation_available'])
            self.assertEqual(status['reason'], 'AI_SERVER_DAILY_LIMIT')
            self.assertEqual(status['server_limit']['remaining_count'], 0)
            self.assertIsNotNone(status['next_available_at'])
            bucket = AIQuotaBucket.objects.get(user=self.employee); bucket.successful_count=39; bucket.save()
            with self.assertRaises(AccessError) as error: self.task('CLEANUP')
            self.assertEqual(error.exception.code, 'AI_SERVER_DAILY_LIMIT')
            self.assertEqual(first.reserved_cost, 0)
            self.assertEqual(AIBudgetMonth.objects.get().reserved_usd, 0)

    def test_duplicate_and_manager_shared_result_work_even_when_global_full(self):
        with override_settings(AI_CONFIG=replace(FREE, free_rpd=1)):
            body=self.body('TEAM_GUIDE');task,_=reserve(self.admin,body)
            self.assertFalse(reserve(self.admin,body)[1])
            admin2=user('01000000004', role=User.Role.ADMIN, initial=False)
            shared,created=reserve(admin2,self.body('TEAM_GUIDE'))
            self.assertFalse(created);self.assertEqual(shared.pk,task.pk)
            self.assertEqual(AIProviderQuotaDay.objects.get().reserved_count,1)
            self.assertEqual(self.process(task)[0]['succeeded'],1)
            shared,created=reserve(admin2,self.body('TEAM_GUIDE'))
            self.assertFalse(created);self.assertEqual(shared.pk,task.pk)
            day=AIProviderQuotaDay.objects.get();self.assertEqual((day.sent_count,day.reserved_count),(1,0))

    def test_sent_and_queued_reservations_are_both_counted_and_do_not_expire_at_fifteen_minutes(self):
        task=self.task();other=reserve(self.other,self.body(customer=self.other_customer))[0]
        claimed=claim();self.assertEqual(claimed.pk,task.pk)
        day=AIProviderQuotaDay.objects.get();self.assertEqual((day.sent_count,day.reserved_count),(1,1))
        self.clock.return_value=self.now+timedelta(minutes=16)
        reap();other.refresh_from_db();self.assertEqual(other.status,'RESERVED')
        self.assertEqual(other.attempt_count,0)

    def test_fifteen_rpm_dispatches_exact_capacity_then_waits_without_attempt_and_resumes(self):
        tasks=self.more_tasks(16)
        for task in tasks[:15]:self.assertEqual(self.process(task)[0]['succeeded'],1)
        self.assertEqual(self.process(tasks[15])[0]['processed'],0)
        tasks[15].refresh_from_db();self.assertEqual((tasks[15].status,tasks[15].attempt_count),('RESERVED',0))
        self.assertEqual(tasks[15].error_code,'AI_RATE_WAIT')
        self.assertEqual(AIProviderDispatch.objects.count(),15)
        self.clock.return_value=self.now+timedelta(seconds=60)
        self.assertEqual(self.process(tasks[15])[0]['succeeded'],1)
        self.assertEqual(AIProviderDispatch.objects.count(),16)

    def test_tpm_holds_inflight_maximum_then_reconciles_actual_input(self):
        first=self.task();other=reserve(self.other,self.body(customer=self.other_customer))[0]
        cap=max(first.input_tokens_cap,other.input_tokens_cap)+1000
        self.assertLess(cap,first.input_tokens_cap+other.input_tokens_cap)
        with override_settings(AI_CONFIG=replace(FREE,free_tpm=cap)):
            running=claim();self.assertEqual(running.pk,first.pk)
            self.assertIsNone(claim())
            self.assertEqual(AIProviderDispatch.objects.get().input_tokens,first.input_tokens_cap)
            self.assertTrue(self.success_claimed(running))
            self.clock.return_value+=timedelta(seconds=2)
            running2=claim();self.assertEqual(running2.pk,other.pk)
            self.assertLessEqual(sum(AIProviderDispatch.objects.values_list('input_tokens',flat=True)),cap)

    def test_long_running_or_unknown_call_keeps_minute_reservation_after_sixty_seconds(self):
        self.task();reserve(self.other,self.body(customer=self.other_customer))
        with override_settings(AI_CONFIG=replace(FREE,free_rpm=1)):
            running=claim();self.clock.return_value+=timedelta(seconds=61)
            self.assertIsNone(claim())
            finish(running.pk,running.lease_token,outcome='unknown',now=self.clock.return_value)
            self.assertIsNone(claim())
            reap(now=running.unknown_until)
            self.clock.return_value=running.unknown_until
            self.assertIsNotNone(claim())

    def test_unsent_cancel_releases_daily_reservation_but_sent_failures_do_not(self):
        task=self.task()
        with business_write():settle(task,'CANCELLED',now=self.now)
        day=AIProviderQuotaDay.objects.get();self.assertEqual((day.reserved_count,day.sent_count),(0,0))
        for status in [400,503]:
            task=self.task();self.process(task,status=status)
            if status==503:reap(now=task.unknown_until)
        day.refresh_from_db();self.assertEqual((day.reserved_count,day.sent_count),(0,2))
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)

    def test_day_rollover_expires_old_queue_and_releases_its_reservations(self):
        task=self.task();day=AIProviderQuotaDay.objects.get()
        self.clock.return_value=free_limits.reset_at(day.provider_date)
        reap();task.refresh_from_db();day.refresh_from_db()
        self.assertEqual((task.status,task.error_code,day.reserved_count),('FAILED','AI_QUEUE_EXPIRED',0))
        new=self.task();self.assertNotEqual(new.provider_day_id,day.pk)
        self.assertEqual(AIQuotaBucket.objects.get(pk=task.quota_bucket_id).reserved_count,1)

    def test_free_mode_does_not_use_or_fall_back_to_paid_budget(self):
        AIBudgetMonth.objects.create(month=self.now.date().replace(day=1),charged_usd=Decimal('100'))
        task=self.task();self.assertEqual(self.process(task)[0]['succeeded'],1)
        self.assertEqual((task.charged_cost,task.reserved_cost),(0,0))
        self.assertEqual(AIBudgetMonth.objects.get().charged_usd,100)
        with override_settings(AI_CONFIG=replace(FREE,free_tier_confirmed=False)):
            with self.assertRaises(AccessError):self.task('CLEANUP')
        self.assertEqual(AIRequest.objects.count(),1)

    def test_forty_personal_limit_and_database_constraint_remain_hard_cap(self):
        with override_settings(AI_CONFIG=replace(FREE,free_rpd=100)):
            bucket=AIQuotaBucket.objects.create(user=self.employee,korean_date=self.now.date(),successful_count=39)
            task=self.task('CLEANUP')
            with self.assertRaises(IntegrityError),transaction.atomic():
                AIQuotaBucket.objects.filter(pk=bucket.pk).update(successful_count=40)
            self.assertEqual(self.process(task)[0]['succeeded'],1)
            for feature in ['SUMMARY','NEXT_QUESTIONS']:
                with self.assertRaises(AccessError) as error:self.task(feature)
                self.assertEqual(error.exception.code,'AI_DAILY_LIMIT')
            bucket.refresh_from_db();self.assertEqual((bucket.successful_count,bucket.reserved_count),(40,0))
            self.assertEqual(AIProviderQuotaDay.objects.get().reserved_count,0)

    def race(self,jobs):
        barrier=Barrier(len(jobs))
        def execute(job):
            close_old_connections()
            try:
                barrier.wait()
                try:return job()
                except AccessError as error:return error.code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:return list(pool.map(execute,jobs))

    def test_concurrent_reservations_cannot_take_five_hundredth_slot_twice(self):
        quota=AIProviderQuota.objects.create(scope_key=free_limits.scope_key(FREE))
        AIProviderQuotaDay.objects.create(quota=quota,provider_date=free_limits.provider_day(self.now),sent_count=499)
        body1=self.body();body2=self.body(customer=self.other_customer)
        values=self.race([lambda:str(reserve(User.objects.get(pk=self.employee.pk),body1)[0].pk),
                          lambda:str(reserve(User.objects.get(pk=self.other.pk),body2)[0].pk)])
        self.assertEqual(values.count('AI_SERVER_DAILY_LIMIT'),1)
        self.assertEqual(AIRequest.objects.count(),1)
        self.assertEqual(AIProviderQuotaDay.objects.get().reserved_count,1)

    def test_concurrent_workers_share_single_rpm_slot(self):
        self.task();reserve(self.other,self.body(customer=self.other_customer))
        with override_settings(AI_CONFIG=replace(FREE,free_rpm=1)):
            values=self.race([lambda:bool(claim()),lambda:bool(claim())])
        self.assertEqual(values.count(True),1)
        self.assertEqual(AIProviderDispatch.objects.count(),1)
        self.assertEqual(AIRequest.objects.filter(status='RESERVED',attempt_count=0).count(),1)

    def test_key_rotation_keeps_scope_project_change_cannot_send_old_queue(self):
        task=self.task()
        with override_settings(AI_CONFIG=replace(FREE,api_key='rotated-synthetic')):
            self.assertEqual(free_limits.scope_key(FREE),free_limits.scope_key(replace(FREE,api_key='rotated-synthetic')))
            self.assertEqual(free_limits.snapshot(replace(FREE,api_key='rotated-synthetic'),self.now)['reserved_count'],1)
        with override_settings(AI_CONFIG=replace(FREE,free_project_id='different-project')):
            self.assertIsNone(claim())
        task.refresh_from_db();self.assertEqual(task.status,'FAILED')
        self.assertEqual(AIProviderQuotaDay.objects.get().reserved_count,0)

    def test_previous_model_queue_cannot_be_sent_as_lite_or_reset_old_usage(self):
        task=self.task()
        original=AIProviderQuotaDay.objects.get()
        original.reserved_count=0;original.save()
        old_config=replace(FREE,model='gemini-3.8-flash')
        old_quota=AIProviderQuota.objects.create(scope_key=free_limits.scope_key(old_config))
        old_day=AIProviderQuotaDay.objects.create(quota=old_quota,provider_date=free_limits.provider_day(self.now),sent_count=3,reserved_count=1)
        task.provider_day=old_day;task.model_version=old_config.model;task.save()
        self.assertIsNone(claim())
        task.refresh_from_db();old_day.refresh_from_db()
        self.assertEqual((task.status,task.error_code),('FAILED','AI_CONFIGURATION_CHANGED'))
        self.assertEqual((old_day.sent_count,old_day.reserved_count),(3,0))
        self.assertEqual(free_limits.snapshot(FREE,self.now)['remaining_count'],500)

    def test_429_pauses_entire_server_and_daily_quota_marker_waits_until_reset(self):
        task=self.task();other=reserve(self.other,self.body(customer=self.other_customer))[0]
        response={'error':{'details':[{'retryDelay':'90s'}]}}
        self.process(task,status=429,data=response)
        self.assertEqual((task.status,task.error_code),('FAILED','AI_SERVER_RATE_LIMIT'))
        self.assertIsNone(claim());self.assertEqual(other.attempt_count,0)
        with self.assertRaises(AccessError) as error:self.task('CLEANUP')
        self.assertEqual(error.exception.code,'AI_SERVER_COOLDOWN')
        self.clock.return_value+=timedelta(seconds=91)
        self.assertEqual(self.process(other)[0]['succeeded'],1)
        task=self.task('CLEANUP')
        self.process(task,status=429,data={'error':{'details':[{'violations':[{'quotaId':'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}})
        quota=AIProviderQuota.objects.get()
        self.assertEqual(quota.cooldown_until,free_limits.reset_at(free_limits.provider_day(self.clock.return_value)))

    def test_minute_receipt_survives_original_request_deletion_without_customer_content(self):
        from apps.customers.deletions import hard_delete_customer
        from apps.customers.services import trash_operation
        self.task();running=claim();self.success_claimed(running)
        receipt=AIProviderDispatch.objects.get()
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.customer.pk)],'idempotency_key':str(uuid4())})
        self.customer.refresh_from_db()
        hard_delete_customer(self.admin,self.customer.pk,{'confirm':True,'expected_version':self.customer.version,'idempotency_key':str(uuid4())})
        running.refresh_from_db();running.result.refresh_from_db()
        self.assertFalse(Customer.objects.filter(pk=self.customer.pk).exists())
        self.assertEqual((running.input_payload,running.result.payload),({},{ }))
        self.assertEqual(AIProviderDispatch.objects.get().input_tokens,1000)
        self.assertEqual(AIProviderQuotaDay.objects.get().sent_count,1)
        self.assertFalse({'customer','payload','api_key'} & {field.name for field in AIProviderDispatch._meta.fields})

    def test_unsent_customer_hard_delete_releases_global_reservation(self):
        from apps.customers.deletions import hard_delete_customer
        from apps.customers.services import trash_operation
        task=self.task()
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.customer.pk)],'idempotency_key':str(uuid4())})
        self.customer.refresh_from_db()
        hard_delete_customer(self.admin,self.customer.pk,{'confirm':True,'expected_version':self.customer.version,'idempotency_key':str(uuid4())})
        task.refresh_from_db();day=AIProviderQuotaDay.objects.get()
        self.assertEqual((task.status,day.reserved_count,day.sent_count),('CANCELLED',0,0))

    def test_five_hundredth_slot_available_without_percentage_margin(self):
        quota=AIProviderQuota.objects.create(scope_key=free_limits.scope_key(FREE))
        AIProviderQuotaDay.objects.create(quota=quota,provider_date=free_limits.provider_day(self.now),sent_count=499)
        self.task()
        day=AIProviderQuotaDay.objects.get()
        self.assertEqual((day.reserved_count,day.sent_count),(1,499))
        with self.assertRaises(AccessError) as error:self.task('TEAM_GUIDE')
        self.assertEqual(error.exception.code,'AI_SERVER_DAILY_LIMIT')
        self.assertEqual(AIRequest.objects.count(),1)

    def test_oversized_tpm_request_does_not_leave_any_reservation(self):
        with override_settings(AI_CONFIG=replace(FREE,free_tpm=10)):
            with self.assertRaises(AccessError) as error:self.task()
        self.assertEqual(error.exception.code,'AI_SERVER_INPUT_LIMIT')
        self.assertFalse(AIProviderQuotaDay.objects.exists())
        self.assertFalse(AIQuotaBucket.objects.exists())

    def test_worker_can_fill_remaining_tpm_with_smaller_queued_request(self):
        first=self.task('CLEANUP')
        second=reserve(self.other,self.body(customer=self.other_customer))[0]
        cap=first.input_tokens_cap
        self.assertGreater(cap,second.input_tokens_cap)
        quota=AIProviderQuota.objects.get()
        AIProviderDispatch.objects.create(quota=quota,sent_at=self.now,window_ends_at=self.now+timedelta(seconds=60),input_tokens=cap-second.input_tokens_cap)
        with override_settings(AI_CONFIG=replace(FREE,free_tpm=cap)):
            running=claim()
        self.assertEqual(running.pk,second.pk)
        first.refresh_from_db();self.assertEqual(first.error_code,'AI_RATE_WAIT')
        self.assertEqual(sum(AIProviderDispatch.objects.values_list('input_tokens',flat=True)),cap)

    def test_configuration_rejects_unconfirmed_zero_limits_or_paid_prices(self):
        for config in [replace(FREE,free_tier_confirmed=False),replace(FREE,free_project_id=''),
                       replace(FREE,free_rpd=0),replace(FREE,free_rpm=0),replace(FREE,free_tpm=0),
                       replace(FREE,input_price=Decimal('.75')),replace(FREE,usage_tier='unknown')]:
            with self.subTest(config=config),override_settings(AI_CONFIG=config):
                with self.assertRaises(AccessError):validate_config()
        self.assertFalse(AIProviderQuota.objects.exists())


class ProviderResetTests(SimpleTestCase):
    def test_pacific_reset_changes_with_dst_and_not_kst_midnight(self):
        for when,hour in [(datetime(2026,7,1,6,59,tzinfo=dt_timezone.utc),7),
                          (datetime(2026,11,7,7,59,tzinfo=dt_timezone.utc),8)]:
            reset=free_limits.reset_at(free_limits.provider_day(when)).astimezone(dt_timezone.utc)
            self.assertEqual(reset.hour,hour)
            self.assertEqual(free_limits.provider_day(reset-timedelta(microseconds=1))+timedelta(days=1),free_limits.provider_day(reset))
            self.assertNotEqual(reset.astimezone(KST).hour,0)

    def test_rate_limit_parser_accepts_only_timing_and_quota_identifiers(self):
        self.assertEqual(rate_limit({'_retry_after_seconds':120}),(120,False))
        self.assertEqual(rate_limit({'error':{'details':[{'retryDelay':'1.5s'},{'retryDelay':'secret'}]}}),(60,False))
        self.assertEqual(rate_limit({'error':{'details':[{'violations':[{'quotaId':'per_day'}]}]}}),(60,True))
