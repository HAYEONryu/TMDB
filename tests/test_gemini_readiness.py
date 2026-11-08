"""25-actor capacity and independent cumulative budgets; synthetic I/O only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch, Mock
from uuid import uuid4
from django.db import close_old_connections
from django.test import override_settings, SimpleTestCase
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.ai_assistant.models import AIRequest, AIQuotaBucket, AIProviderQuotaDay, AIBudgetMonth, AITestBudget
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import claim, finish, run_once, reap, ProviderResponse
from apps.ai_assistant.gemini_adapter import _post, GeminiAdapter
from apps.ai_assistant import gemini_policy
from apps.customers.models import Customer
from apps.customers.queries import KST
from tests import test_gemini_adapter as previous
from tests.helpers import user, login


class GeminiReadinessTests(previous.GeminiQueueTests):
    # Load only this class's added methods in the focused run; inherited methods
    # remain part of the explicit regression run.
    def test_20_staff_5_admin_concurrent_reservations_and_global_two_workers(self):
        free=replace(previous.CONFIG,usage_tier='free',input_price=Decimal(0),output_price=Decimal(0),
            free_tier_confirmed=True,free_limits_model=previous.CONFIG.model,free_project_id='synthetic-capacity',free_rpm=100,free_tpm=1000000,free_rpd=1000)
        staff=[self.employee,self.other]+[user(f'01000001{i:03}',initial=False) for i in range(18)]
        admins=[self.admin]+[user(f'01000002{i:03}',role=User.Role.ADMIN,initial=False) for i in range(4)]
        bodies=[]
        for i,actor in enumerate(staff):
            customer=self.customers(offset=100+i)[0];self.assign(customer,actor)
            bodies.append((actor,self_body(customer)))
        bodies.extend((actor,{'feature':'TEAM_GUIDE','site_id':str(self.site.pk),'idempotency_key':str(uuid4())}) for actor in admins)
        def race(jobs):
            barrier=Barrier(len(jobs))
            def execute(job):
                close_old_connections()
                try:barrier.wait();return job()
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:return list(pool.map(execute,jobs))
        with override_settings(AI_CONFIG=free):
            values=race([lambda actor=actor,body=body:reserve(User.objects.get(pk=actor.pk),body)[0].pk for actor,body in bodies])
            self.assertEqual(len(set(values)),21)
            self.assertEqual(len(set(values[20:])),1)
            self.assertEqual(AIProviderQuotaDay.objects.get().reserved_count,21)
            self.assertEqual(AIQuotaBucket.objects.count(),20)
            self.assertTrue(all(row.reserved_count==1 and row.successful_count==0 for row in AIQuotaBucket.objects.all()))
            jobs=race([lambda:claim() for _ in range(5)])
            active=[job for job in jobs if job is not None]
            self.assertEqual(len(active),2)
            self.assertEqual(AIRequest.objects.filter(status='RUNNING').count(),2)
            self.assertIsNone(claim())
            for job in active:
                self.assertTrue(finish(job.pk,job.lease_token,response=ProviderResponse(previous.payload_for(job),1000,80,40)))
            for actor in admins:
                response=login(actor).get('/api/ai/tasks/'+str(values[-1]))
                self.assertEqual(response.status_code,200)
            self.assertEqual(AIRequest.objects.count(),21)

    def test_five_admins_share_all_three_period_slots_and_reads_do_not_send(self):
        admins=[self.admin]+[user(f'01000003{i:03}',role=User.Role.ADMIN,initial=False) for i in range(4)]
        with patch('django.utils.timezone.now',return_value=datetime(2026,11,8,15,tzinfo=KST)):
            for feature in ['WEEKLY_BRIEFING','EMPLOYEE_COACHING','TEAM_GUIDE']:
                tasks=[reserve(actor,self.body(feature))[0] for actor in admins]
                self.assertEqual(len({task.pk for task in tasks}),1)
                self.assertEqual(self.process(tasks[0])[0]['succeeded'],1)
                tasks[0].refresh_from_db()
                for actor in admins:
                    self.assertFalse(reserve(actor,self.body(feature))[1])
                    self.assertEqual(login(actor).get(f'/api/ai/results/{tasks[0].result.pk}').status_code,200)
            self.assertEqual(AIRequest.objects.count(),3)
            from apps.ai_assistant.models import AIUsageAttempt
            self.assertEqual(AIUsageAttempt.objects.filter(transport_started_at__isnull=False).count(),3)

    def test_cumulative_test_budget_survives_month_rollover_and_releases_failures(self):
        config=replace(previous.CONFIG,test_budget_usd=Decimal('.03'),test_budget_scope='synthetic-campaign')
        with override_settings(AI_CONFIG=config):
            task=self.task();self.assertEqual(self.process(task)[0]['succeeded'],1)
            budget=AITestBudget.objects.get();self.assertEqual(budget.charged_usd,task.charged_cost)
            self.assertEqual(budget.reserved_usd,0)
            budget.charged_usd=config.test_budget_usd-task.reserved_cost;budget.save()
            month_start=datetime(2026,12,8,12,tzinfo=KST)
            with patch('django.utils.timezone.now',return_value=month_start):
                Customer.objects.filter(pk=self.customer.pk).update(version=2)
                task=self.task()
                other=self.customers(offset=20)[0];self.assign(other,self.other)
                with self.assertRaises(AccessError) as error:reserve(self.other,self_body(other))
                self.assertEqual(error.exception.code,'AI_TEST_BUDGET_LIMIT')
                state=login(self.other).get('/api/ai/availability').json()
                self.assertFalse(state['generation_available']);self.assertEqual(state['reason'],'AI_TEST_BUDGET_LIMIT')
                self.assertEqual(AIBudgetMonth.objects.get(month='2026-12-01').charged_usd,0)
                self.process(task,status=400)
                budget.refresh_from_db();self.assertEqual(budget.reserved_usd,0)
                self.assertTrue(reserve(self.other,self_body(other))[1])

    def test_zero_cumulative_budget_and_unknown_prices_block_before_io(self):
        with override_settings(AI_CONFIG=replace(previous.CONFIG,test_budget_usd=Decimal(0),test_budget_scope='zero')):
            with self.assertRaises(AccessError) as error:self.task()
            self.assertEqual(error.exception.code,'AI_TEST_BUDGET_LIMIT')
        with override_settings(AI_CONFIG=replace(previous.CONFIG,input_price=None)):
            with self.assertRaises(AccessError):self.task()
        self.assertFalse(AIRequest.objects.exists())

    def test_explicit_lite_model_uses_same_adapter_and_never_falls_back(self):
        config=replace(previous.CONFIG,model='gemini-3.5-flash-lite',input_price=Decimal('.30'),output_price=Decimal('2.50'))
        with override_settings(AI_CONFIG=config):
            task=self.task();data=previous.wire(previous.payload_for(task));data['modelVersion']=config.model
            self.assertEqual(self.process(task,data=data)[0]['succeeded'],1)
            self.assertEqual(task.model_version,config.model)

    def test_unknown_attempt_accounts_for_both_budgets_without_retry(self):
        with override_settings(AI_CONFIG=replace(previous.CONFIG,test_budget_usd=Decimal('1'),test_budget_scope='unknown')):
            task=self.task();self.process(task,error=TimeoutError())
            self.assertEqual(run_once()['processed'],0)
            budget=AITestBudget.objects.get();self.assertEqual(budget.reserved_usd,task.reserved_cost)
            reap(now=task.unknown_until);budget.refresh_from_db();task.refresh_from_db()
            self.assertEqual((budget.reserved_usd,budget.charged_usd),(0,task.reserved_cost))
            self.assertEqual(task.attempt_count,1)

    def test_transport_start_is_separate_from_claim_success_and_duplicate_send(self):
        task=self.task();running=claim()
        self.assertIsNone(running.attempts.get().transport_started_at)
        from apps.ai_assistant.worker import mark_transport_started
        self.assertTrue(mark_transport_started(running))
        self.assertFalse(mark_transport_started(running))
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)
        finish(running.pk,running.lease_token,outcome='failed',response=ProviderResponse({}))
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)
        usage=login(self.admin).get('/api/ai/usage').json()
        self.assertEqual((usage['transport_started_count'],usage['retry_started_count']),(1,0))


def self_body(customer):
    return {'feature':'SUMMARY','customer_id':str(customer.pk),'assignment_id':str(customer.current_assignment_id),
            'expected_version':customer.version,'idempotency_key':str(uuid4())}


class GeminiConfigReadinessTests(SimpleTestCase):
    def test_compact_free_lite_file_derives_only_safe_defaults(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from config.ai import load_ai_config
        with TemporaryDirectory(dir='/private/tmp') as directory:
            path=Path(directory)/'.env.ai'
            path.write_text('AI_ENABLED=false\nAI_PROVIDER=gemini\nAI_MODEL=gemini-3.5-flash-lite\nAI_GEMINI_API_KEY=synthetic-only\nAI_USAGE_TIER=free\nAI_FREE_TIER_CONFIRMED=false\nAI_FREE_PROJECT_ID=synthetic-project\nAI_FREE_RPM=15\nAI_FREE_TPM=250000\nAI_FREE_RPD=500\n')
            path.chmod(0o600)
            cfg=load_ai_config(directory,role='web',environment={})
            self.assertFalse(cfg.enabled)
            self.assertEqual((cfg.input_price,cfg.output_price,cfg.staff_reasoning,cfg.free_limits_model),(Decimal(0),Decimal(0),'low','gemini-3.5-flash-lite'))
            self.assertFalse(gemini_policy.supported(replace(cfg,enabled=True)))
            self.assertTrue(gemini_policy.supported(replace(cfg,enabled=True,free_tier_confirmed=True)))
            paid=load_ai_config(directory,role='web',environment={'AI_USAGE_TIER':'paid'})
            self.assertFalse(paid.configured)
            self.assertFalse(gemini_policy.supported(replace(cfg,enabled=True,free_tier_confirmed=True,model='gemini-3.8-flash')))

    def test_credentials_require_file_and_free_limits_are_bound_to_model(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from config.ai import load_ai_config
        from dotenv import dotenv_values
        with TemporaryDirectory(dir='/private/tmp') as directory:
            path=Path(directory)/'.env.ai';path.write_text('AI_GEMINI_API_KEY=synthetic-file-only\n');path.chmod(0o600)
            env={'AI_PROVIDER':'gemini','AI_MODEL':'gemini-3.5-flash-lite','AI_GEMINI_API_KEY':'synthetic-env-ignored'}
            self.assertEqual(load_ai_config(directory,role='web',environment=env).api_key,'synthetic-file-only')
            path.unlink()
            self.assertEqual(load_ai_config(directory,role='web',environment=env).api_key,'')
        from tests.test_free_ai_limits import FREE
        self.assertTrue(gemini_policy.supported(FREE))
        self.assertFalse(gemini_policy.supported(replace(FREE,model='gemini-3.8-flash')))
        self.assertFalse(gemini_policy.supported(replace(FREE,free_limits_model='')))
        example=Path(__file__).resolve().parents[1]/'.env.ai.example'
        self.assertTrue(all(not value for value in dotenv_values(example,interpolate=False).values()))

    def test_transport_uses_explicit_allowlisted_model_endpoint(self):
        response=Mock(status=200);response.read.return_value=b'{}';response.getheader.return_value='standard'
        for model in gemini_policy.MODELS:
            with patch('http.client.HTTPSConnection') as factory:
                factory.return_value.getresponse.return_value=response
                _post(b'{}','synthetic',model=model)
                self.assertEqual(factory.return_value.request.call_args.args[1],f'/v1beta/models/{model}:generateContent')
        with patch('http.client.HTTPSConnection') as factory:
            with self.assertRaises(Exception):_post(b'{}','synthetic',model='unreviewed/model')
            factory.assert_not_called()
