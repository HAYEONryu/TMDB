import io
import json
import os
import subprocess
import sys
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import connection, close_old_connections, IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.ai import AIConfig
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.accounts.services import set_user_access
from apps.ai_assistant.adapters import FoundationFakeAdapter
from apps.ai_assistant.inputs import source_ids
from apps.ai_assistant.models import AIRequest, AIResult, AIResultSource, AIQuotaBucket, AIBudgetMonth, AIReportSlot, AIUsageAttempt, SiteKnowledge
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import claim, finish, reap, run_once, ProviderResponse, NotPerformed, OutcomeUnknown, ProviderFailed
from apps.assignments.services import change_assignee
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer, CustomerChangeEvent
from apps.customers.deletions import hard_delete_customer, hard_delete_site, confirm_site
from apps.customers.services import trash_operation, update_row
from apps.customers.queries import KST
from apps.common.transactions import BUSINESS_LOCK_KEY
from tests.helpers import TEST_HASHERS, login, user
from tests.test_p4 import Fixtures

TEST_AI = AIConfig(enabled=True, configured=True, provider="test-only", model="foundation-test-v1", api_key="TEST_ONLY_P9_KEY",
                   input_price=Decimal("0.1"), output_price=Decimal("0.3"))


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=True, AI_CONFIG=TEST_AI)
class P9Tests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare(); self.customer = self.customers()[0]; self.assignment = self.assign(self.customer)

    def body9(self, feature="SUMMARY", **values):
        self.customer.refresh_from_db()
        return {"feature":feature,"customer_id":str(self.customer.pk),"assignment_id":str(self.customer.current_assignment_id),
                "expected_version":self.customer.version,"idempotency_key":str(uuid4()),**values}

    def task(self, **values): return reserve(self.employee, self.body9(**values))[0]
    def response(self, task, **values):
        base = FoundationFakeAdapter().execute_task(task, task.input_payload)
        return ProviderResponse(**{**base.__dict__, **values})

    def guide(self, **values):
        return reserve(self.admin, {"feature":"TEAM_GUIDE","site_id":str(self.site.pk),"idempotency_key":str(uuid4()),**values})[0]

    def hard(self, customer=None):
        c=customer or self.customer
        trash_operation(self.admin,{"site_id":str(c.site_id),"customer_ids":[str(c.pk)],"idempotency_key":str(uuid4())})
        c.refresh_from_db()
        return hard_delete_customer(self.admin,c.pk,{"confirm":True,"expected_version":c.version,"idempotency_key":str(uuid4())})

    def test_reservation_idempotency_cache_success_and_no_customer_activity(self):
        body=self.body9(); task,new=reserve(self.employee,body); self.assertTrue(new)
        self.assertEqual(reserve(self.employee,body)[0].pk,task.pk)
        self.assertEqual(task.quota_bucket.reserved_count,1)
        with self.assertRaises(AccessError) as conflict: reserve(self.employee,{**body,"feature":"CLEANUP"})
        self.assertEqual(conflict.exception.code,"IDEMPOTENCY_CONFLICT")
        self.assertEqual(run_once(),{"processed":1,"succeeded":1})
        cache_body=self.body9(); cached,new=reserve(self.employee,cache_body); self.assertFalse(new); self.assertEqual(cached.pk,task.pk)
        self.assertEqual(reserve(self.employee,cache_body)[0].pk,task.pk)
        with self.assertRaises(AccessError) as alias_conflict:reserve(self.employee,{**cache_body,'feature':'CLEANUP'})
        self.assertEqual(alias_conflict.exception.code,'IDEMPOTENCY_CONFLICT')
        task.refresh_from_db(); task.quota_bucket.refresh_from_db(); self.assertEqual((task.quota_bucket.successful_count,task.quota_bucket.reserved_count),(1,0))
        self.assertEqual(task.input_payload,{})
        self.customer.refresh_from_db(); self.assignment.refresh_from_db(); self.assertEqual(self.customer.version,1); self.assertIsNone(self.assignment.first_activity_at)
        self.assertEqual(ConsultationRevision.objects.count(),0); self.assertEqual(CustomerChangeEvent.objects.count(),0); self.assertEqual(AIUsageAttempt.objects.count(),1)

    def test_no_paid_or_fake_generation_outside_explicit_test_database(self):
        for values in [{"TESTING":False},{"AI_FOUNDATION_TEST_MODE":False},{"AI_CONFIG":AIConfig()}]:
            with override_settings(**values):
                with self.assertRaises(AccessError): self.task()
                self.assertEqual(run_once()["processed"],0)
        self.assertFalse(AIRequest.objects.exists())
        with patch.dict(connection.settings_dict,{"NAME":"tm_dev"}):
            with self.assertRaises(AccessError): self.task()

    def test_role_assignment_version_and_untrusted_input_rejected(self):
        for actor,body in [(self.other,self.body9()),(self.admin,self.body9()),(self.employee,self.body9(assignment_id=str(uuid4()))),
                           (self.employee,self.body9(expected_version=999)),(self.employee,{**self.body9(),"prompt":"임의 지시"}),
                           (self.employee,self.body9(expected_version=True))]:
            with self.assertRaises(AccessError): reserve(actor,body)
        self.assertEqual(AIRequest.objects.count(),0); self.assertEqual(AIBudgetMonth.objects.count(),0)

    def test_shared_three_feature_quota_reservation_limit_and_database_constraint(self):
        for feature in ["CLEANUP","SUMMARY","NEXT_QUESTIONS"]:
            self.task(feature=feature); self.assertEqual(run_once()["succeeded"],1)
        bucket=AIQuotaBucket.objects.get(); self.assertEqual(bucket.successful_count,3)
        bucket.successful_count=39; bucket.save()
        Customer.objects.filter(pk=self.customer.pk).update(version=2)
        task=self.task(); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,1)
        with self.assertRaises(IntegrityError), transaction.atomic(): AIQuotaBucket.objects.filter(pk=bucket.pk).update(successful_count=40)
        self.assertEqual(run_once()["succeeded"],1)
        with self.assertRaises(AccessError) as limited:self.task(feature="NEXT_QUESTIONS")
        self.assertEqual(limited.exception.code,"AI_DAILY_LIMIT")
        client=login(self.employee); data=client.get('/api/ai/availability').json(); self.assertEqual((data['successful_count'],data['remaining_count']),(40,0)); self.assertIsNotNone(data['next_available_at'])

    def test_budget_reservation_failure_cost_and_unconfigured_core_independence(self):
        with override_settings(AI_CONFIG=AIConfig(**{**{f:getattr(TEST_AI,f) for f in TEST_AI.__dataclass_fields__},"monthly_budget_usd":Decimal("0.000001")})):
            with self.assertRaises(AccessError) as error:self.task()
            self.assertEqual(error.exception.code,"AI_BUDGET_LIMIT")
        self.assertFalse(AIRequest.objects.exists()); self.assertFalse(AIQuotaBucket.objects.exists())
        task=self.task(); running=claim(); response=self.response(running)
        finish(task.pk,running.lease_token,response=response,outcome="failed")
        task.refresh_from_db(); budget=AIBudgetMonth.objects.get(); self.assertEqual(budget.reserved_usd,0); self.assertGreater(budget.charged_usd,0)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)
        self.assertEqual(login(self.employee).get('/api/customers',{'view':'mine','site_id':self.site.pk}).status_code,200)

    def test_kst_day_and_budget_month_remain_at_submission_across_midnight(self):
        at=datetime(2026,12,31,23,59,tzinfo=KST)
        with patch('django.utils.timezone.now',return_value=at):task=self.task(); running=claim()
        finish(task.pk,running.lease_token,response=self.response(running),now=at+timedelta(minutes=2))
        task.refresh_from_db(); self.assertEqual(task.korean_date,at.date()); self.assertEqual(task.budget_month.month,at.date().replace(day=1))
        self.assertEqual(AIQuotaBucket.objects.get().korean_date,at.date()); self.assertEqual(AIBudgetMonth.objects.count(),1)

    def test_one_task_per_account_and_two_global_claims_including_unknown(self):
        self.task()
        with self.assertRaises(AccessError) as error:self.task(feature="CLEANUP")
        self.assertEqual(error.exception.code,"AI_BUSY")
        second=self.customers(offset=2)[0]; self.assign(second,self.other)
        reserve(self.other,{**self.body9(),"customer_id":str(second.pk),"assignment_id":str(second.current_assignment_id)})
        self.guide(); one,two=claim(),claim(); self.assertIsNotNone(one); self.assertIsNotNone(two); self.assertIsNone(claim())
        finish(one.pk,one.lease_token,outcome="unknown"); self.assertIsNone(claim())
        finish(two.pk,two.lease_token,response=self.response(two)); self.assertIsNotNone(claim())

    def test_only_guaranteed_not_performed_retries_once_same_task_without_extra_quota(self):
        task=self.task()
        class Adapter:
            def execute_task(self,*args):raise NotPerformed()
        self.assertEqual(run_once(Adapter())["processed"],1); task.refresh_from_db(); self.assertEqual((task.status,task.attempt_count),("RESERVED",1))
        run_once(Adapter()); task.refresh_from_db(); self.assertEqual((task.status,task.attempt_count),("FAILED",2))
        self.assertEqual(AIRequest.objects.count(),1); self.assertEqual(AIUsageAttempt.objects.count(),2); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)
        self.assertEqual(AIBudgetMonth.objects.get().charged_usd,0); self.assertEqual(run_once()["processed"],0)

    def test_unknown_holds_then_releases_once_keeps_conservative_cost_and_rejects_late_success(self):
        task=self.task(); running=claim(); response=self.response(running)
        finish(task.pk,running.lease_token,outcome="unknown")
        self.assertEqual(AIQuotaBucket.objects.get().reserved_count,1)
        self.assertEqual(reap(now=running.started_at+timedelta(minutes=9)),0)
        self.assertEqual(reap(now=running.started_at+timedelta(minutes=10)),1)
        self.assertEqual(reap(now=running.started_at+timedelta(minutes=11)),0)
        self.assertFalse(finish(task.pk,running.lease_token,response=response,now=running.started_at+timedelta(minutes=11)))
        task.refresh_from_db(); self.assertEqual(task.status,"FAILED"); self.assertEqual(task.charged_cost,task.reserved_cost)
        self.assertFalse(task.result.valid); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)

    def test_lost_worker_lease_becomes_unknown_never_reexecuted(self):
        task=self.task(); running=claim()
        self.assertEqual(reap(now=running.started_at+timedelta(seconds=121)),1)
        task.refresh_from_db(); self.assertEqual(task.status,"UNKNOWN"); self.assertIsNone(claim())
        reap(now=running.started_at+timedelta(minutes=10)); self.assertEqual(AIUsageAttempt.objects.count(),1)

    def test_schema_enum_foreign_sources_oversized_response_and_non_test_marker_fail(self):
        for change in [{"feature":"UNKNOWN"},{"source_ids":[str(uuid4())]},{"text":"가"*2000},{"is_test":False},{"extra":"SQL"}]:
            task=self.task(); running=claim(); base=self.response(running)
            self.assertFalse(finish(task.pk,running.lease_token,response=ProviderResponse(**{**base.__dict__,"payload":{**base.payload,**change}})))
            task.refresh_from_db(); self.assertEqual(task.status,"FAILED"); self.assertFalse(task.result.valid)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0); self.assertGreater(AIBudgetMonth.objects.get().charged_usd,0)

    def test_version_change_marks_stale_without_ai_activity_or_automatic_apply(self):
        task=self.task(); running=claim(); update_row(self.employee,self.mutation(self.customer,'작업 중 새 가상 상담'))
        finish(task.pk,running.lease_token,response=self.response(running))
        task.refresh_from_db(); self.assertTrue(task.result.stale); self.assertEqual(ConsultationRevision.objects.count(),1)
        response=login(self.employee).get(f'/api/ai/results/{task.result.pk}')
        self.assertTrue(response.json()['stale']); self.customer.refresh_from_db(); self.assertEqual(self.customer.notes,'작업 중 새 가상 상담')

    def test_revoked_authority_cancels_before_call_or_after_response_with_cost_kept(self):
        task=self.task(); running=claim(); change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer))
        self.assertFalse(finish(task.pk,running.lease_token,response=self.response(running)))
        task.refresh_from_db(); self.assertEqual(task.status,'CANCELLED'); self.assertGreater(task.charged_cost,0)
        self.assertEqual(login(self.employee).get(f'/api/ai/results/{task.result.pk}').status_code,409)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)

    def test_sunday_week_slot_shared_admins_and_failed_slot_released(self):
        sunday=datetime(2026,11,8,23,59,tzinfo=KST); body={'feature':'WEEKLY_BRIEFING','idempotency_key':str(uuid4())}
        with patch('django.utils.timezone.now',return_value=sunday-timedelta(days=1)), self.assertRaises(AccessError) as error: reserve(self.admin,body)
        self.assertEqual(error.exception.code,'AI_SUNDAY_ONLY')
        with patch('django.utils.timezone.now',return_value=sunday):
            task,_=reserve(self.admin,body); admin2=user('01000000004',role='ADMIN',initial=False)
            same,new=reserve(admin2,{**body,'idempotency_key':str(uuid4())}); self.assertEqual(same.pk,task.pk); self.assertFalse(new)
            running=claim()
        finish(task.pk,running.lease_token,response=self.response(running),now=sunday+timedelta(minutes=2))
        self.assertEqual(task.period_key,'2026-11-02'); self.assertEqual(AIReportSlot.objects.get().success_result_id,task.result.pk)
        with patch('django.utils.timezone.now',return_value=sunday): self.assertEqual(reserve(admin2,{**body,'idempotency_key':str(uuid4())})[0].pk,task.pk)

    def test_knowledge_review_version_invalidation_and_permission_no_ai_calls(self):
        admin=login(self.admin); url=f'/api/sites/{self.site.pk}/knowledge'
        body={'title':'가상 안내','body':'확인된 가짜 안내자료','reviewed':True,'is_valid':True}
        self.assertEqual(login(self.employee).get(url).status_code,403)
        response=admin.post(url,body,content_type='application/json'); self.assertEqual(response.status_code,201); kid=response.json()['id']
        task=self.guide(); self.assertIn(kid,{str(source.knowledge_id) for source in task.result.sources.all()}); run_once()
        revised=admin.patch(f'{url}/{kid}',{**body,'body':'수정 가짜 안내','expected_version':1,'reviewed':False,'is_valid':False},content_type='application/json')
        self.assertEqual(revised.status_code,200); task.result.refresh_from_db(); self.assertFalse(task.result.valid); self.assertEqual(task.result.payload,{})
        self.assertEqual(admin.patch(f'{url}/{kid}',{**body,'expected_version':1},content_type='application/json').status_code,409)
        self.assertEqual(AIUsageAttempt.objects.count(),1); self.assertIsNotNone(AIReportSlot.objects.get().success_result_id)

    def test_recursive_deletion_cycles_unpublishes_and_preserves_usage_other_site(self):
        first=self.task(); run_once(); second=self.guide(); run_once()
        third=reserve(self.admin,{'feature':'EMPLOYEE_COACHING','employee_id':str(self.employee.pk),'idempotency_key':str(uuid4())})[0]; run_once()
        for source,target in [(first,second),(second,third),(third,first)]: AIResultSource.objects.create(result=target.result,previous_result=source.result)
        AIResult.objects.filter(pk=second.result.pk).update(guide_status='PUBLISHED',published_at=timezone.now())
        other=self.customers(site=self.second)[0]; self.assign(other,self.other)
        untouched=reserve(self.other,{**self.body9(),'customer_id':str(other.pk),'assignment_id':str(other.current_assignment_id)})[0]; run_once()
        before=AIBudgetMonth.objects.get().charged_usd; count=AIQuotaBucket.objects.get(user=self.employee).successful_count
        self.hard()
        for task in [first,second,third]:
            task.refresh_from_db(); result=task.result; self.assertFalse(result.valid); self.assertEqual(result.payload,{}); self.assertEqual(task.input_payload,{})
            self.assertIsNone(result.published_at); self.assertEqual(result.sources.count(),0)
        untouched.result.refresh_from_db(); self.assertTrue(untouched.result.valid)
        self.assertEqual(AIBudgetMonth.objects.get().charged_usd,before); self.assertEqual(AIQuotaBucket.objects.get(user=self.employee).successful_count,count)
        self.assertEqual(AIUsageAttempt.objects.count(),4)

    def test_source_deletion_cancels_pending_and_running_without_refunding_billed_estimate(self):
        task=self.task(); running=claim(); self.hard(); task.refresh_from_db()
        self.assertEqual(task.status,'CANCELLED'); self.assertEqual(task.charged_cost,task.reserved_cost)
        self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0); self.assertFalse(finish(task.pk,running.lease_token,response=ProviderResponse({'secret':'late'})))
        self.assertEqual(task.result.payload,{})

    def test_status_result_usage_access_no_new_calls_and_test_label_not_secret(self):
        task=self.task(); run_once(); staff=login(self.employee); admin=login(self.admin); other=login(self.other)
        for _ in range(3):
            self.assertEqual(staff.get(f'/api/ai/tasks/{task.pk}').status_code,200)
            data=staff.get(f'/api/ai/results/{task.result.pk}').json(); self.assertTrue(data['is_test']); self.assertIn('테스트',data['test_message'])
            self.assertNotIn(TEST_AI.api_key,json.dumps(data)); self.assertEqual(other.get(f'/api/ai/tasks/{task.pk}').status_code,403)
            self.assertEqual(admin.get(f'/api/ai/results/{task.result.pk}').status_code,403)
        self.assertEqual(staff.get('/api/ai/usage').status_code,403); self.assertEqual(admin.get('/api/ai/usage').status_code,200)
        self.assertEqual(AIUsageAttempt.objects.count(),1); self.assertEqual(AIQuotaBucket.objects.get().successful_count,1)

    def test_inputs_bound_identifiers_removed_and_missing_evidence_not_invented(self):
        self.customer.notes=f'{self.customer.customer_name} {self.employee.name} 010-1234-5678 fake@example.com {TEST_AI.api_key} 내일'; self.customer.save()
        task=self.task(); encoded=json.dumps(task.input_payload,ensure_ascii=False)
        for text in [self.customer.customer_name,self.employee.name,'010-1234-5678','fake@example.com',TEST_AI.api_key]: self.assertNotIn(text,encoded)
        self.assertIn('내일',encoded); self.assertEqual(task.input_payload['records'],[])
        # Size failure must roll back every reservation.
        running=claim(); finish(task.pk,running.lease_token,outcome='not_performed'); running=claim(); finish(task.pk,running.lease_token,outcome='not_performed')
        self.customer.notes='가'*10000; self.customer.version+=1; self.customer.save()
        with self.assertRaises(AccessError) as error:self.task()
        self.assertEqual(error.exception.code,'AI_INPUT_TOO_LARGE'); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)

    def test_external_io_has_no_transaction_or_business_lock_and_finish_failure_rolls_back(self):
        task=self.task(); test=self
        class Adapter:
            def execute_task(self,request,payload):
                test.assertFalse(connection.in_atomic_block)
                def acquire():
                    close_old_connections()
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_try_advisory_lock(%s)',[BUSINESS_LOCK_KEY]); locked=cursor.fetchone()[0]
                            if locked:cursor.execute('SELECT pg_advisory_unlock(%s)',[BUSINESS_LOCK_KEY])
                            return locked
                    finally:close_old_connections()
                with ThreadPoolExecutor(max_workers=1) as pool:test.assertTrue(pool.submit(acquire).result())
                return test.response(request)
        with patch('apps.ai_assistant.worker.AIResult.save',side_effect=IntegrityError('test-only')):
            with self.assertRaises(IntegrityError):run_once(Adapter())
        task.refresh_from_db(); self.assertEqual(task.status,'RUNNING'); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,1); self.assertFalse(task.result.valid)
        self.assertEqual(AIBudgetMonth.objects.get().charged_usd,0)

    def test_concurrent_same_key_and_quota29_never_double_reserve(self):
        body=self.body9(); barrier=Barrier(2)
        def reserve_thread(same):
            close_old_connections()
            try:
                barrier.wait()
                actor=User.objects.get(pk=self.employee.pk)
                try:return str(reserve(actor,body if same else {**body,'idempotency_key':str(uuid4())})[0].pk)
                except AccessError as error:return error.code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(reserve_thread,[True,True]))
        self.assertEqual(values[0],values[1]); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,1); self.assertEqual(AIRequest.objects.count(),1)

    def test_worker_command_once_no_new_tasks_and_no_raw_failure_log(self):
        output=io.StringIO(); call_command('run_ai_worker',once=True,stdout=output); self.assertEqual(AIRequest.objects.count(),0)
        self.task(); call_command('run_ai_worker',once=True,stdout=output); self.assertEqual(AIUsageAttempt.objects.count(),1)
        self.assertNotIn(TEST_AI.api_key,output.getvalue())

    def race(self, jobs):
        barrier=Barrier(len(jobs))
        def run(job):
            close_old_connections()
            try:
                barrier.wait()
                try:return job()
                except AccessError as error:return error.code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:return list(pool.map(run,jobs))

    def test_quota29_distinct_keys_race_reserves_only_one_then_success30(self):
        AIQuotaBucket.objects.create(user=self.employee,korean_date=timezone.localdate(),successful_count=39)
        bodies=[self.body9(),self.body9(feature='CLEANUP')]
        values=self.race([lambda body=b: str(reserve(User.objects.get(pk=self.employee.pk),body)[0].pk) for b in bodies])
        self.assertEqual(len(set(values)&{'AI_BUSY','AI_DAILY_LIMIT'}),1)
        bucket=AIQuotaBucket.objects.get(); self.assertEqual((bucket.successful_count,bucket.reserved_count),(39,1))
        run_once(); bucket.refresh_from_db(); self.assertEqual((bucket.successful_count,bucket.reserved_count),(40,0))

    def test_concurrent_admin_slot_and_month_budget_cannot_overreserve(self):
        admin2=user('01000000004',role='ADMIN',initial=False)
        bodies=[{'feature':'TEAM_GUIDE','site_id':str(self.site.pk),'idempotency_key':str(uuid4())} for _ in range(2)]
        values=self.race([lambda actor=a,body=b: str(reserve(User.objects.get(pk=actor.pk),body)[0].pk) for a,b in zip([self.admin,admin2],bodies)])
        self.assertEqual(values[0],values[1]); self.assertEqual(AIRequest.objects.count(),1)
        running=claim(); finish(running.pk,running.lease_token,outcome='not_performed'); running=claim(); finish(running.pk,running.lease_token,outcome='not_performed')
        # A failed report slot is available for an explicit new request.
        self.assertIsNone(AIReportSlot.objects.get().current_request_id)
        other=self.customers(offset=9)[0]; self.assign(other,self.other)
        staff_bodies=[self.body9(),{**self.body9(),'customer_id':str(other.pk),'assignment_id':str(other.current_assignment_id)}]
        config=AIConfig(**{**{f:getattr(TEST_AI,f) for f in TEST_AI.__dataclass_fields__},'monthly_budget_usd':Decimal('0.000900')})
        with override_settings(AI_CONFIG=config):
            values=self.race([lambda actor=a,body=b: str(reserve(User.objects.get(pk=actor.pk),body)[0].pk) for a,b in zip([self.employee,self.other],staff_bodies)])
        self.assertEqual(values.count('AI_BUDGET_LIMIT'),1)
        self.assertLessEqual(AIBudgetMonth.objects.get().reserved_usd,config.monthly_budget_usd)

    def test_simultaneous_claims_only_two_different_tasks(self):
        self.task(); other=self.customers(offset=8)[0]; self.assign(other,self.other)
        reserve(self.other,{**self.body9(),'customer_id':str(other.pk),'assignment_id':str(other.current_assignment_id)})
        self.guide()
        def job():
            task=claim(); return str(task.pk) if task else None
        values=self.race([job,job,job]); claimed=[value for value in values if value]
        self.assertEqual(len(claimed),2); self.assertEqual(len(set(claimed)),2)
        self.assertEqual(AIUsageAttempt.objects.count(),2)

    def test_reservation_failure_rolls_back_quota_budget_slot_and_placeholder(self):
        with patch('apps.ai_assistant.services.AIResultSource.objects.bulk_create',side_effect=IntegrityError('test-only')):
            with self.assertRaises(IntegrityError):self.task()
        for model in [AIRequest,AIResult,AIQuotaBucket,AIBudgetMonth,AIReportSlot]: self.assertEqual(model.objects.count(),0)

    def test_pending_source_deletion_releases_reservations_without_charge(self):
        task=self.task(); self.hard(); task.refresh_from_db()
        self.assertEqual(task.status,'CANCELLED'); self.assertEqual(task.charged_cost,0)
        self.assertEqual(AIBudgetMonth.objects.get().reserved_usd,0); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)
        self.assertEqual(AIUsageAttempt.objects.count(),0); self.assertEqual(run_once()['processed'],0)

    def test_source_via_revision_and_site_knowledge_invalidates_and_removes_raw_material(self):
        update_row(self.employee,self.mutation(self.customer,'지워야 하는 가짜 원문'))
        knowledge=SiteKnowledge.objects.create(site=self.site,title='가짜 안내',body='가짜 본문',is_valid=True,reviewed_by=self.admin,reviewed_at=timezone.now())
        task=self.guide(); run_once()
        self.assertTrue(task.result.sources.filter(revision__customer=self.customer).exists())
        self.hard(); task.result.refresh_from_db(); self.assertFalse(task.result.valid)
        body={'idempotency_key':str(uuid4())}; body.update(confirm_site(self.admin,self.site.pk,{'idempotency_key':body['idempotency_key'],'confirm_name':self.site.name}))
        hard_delete_site(self.admin,self.site.pk,body)
        self.assertFalse(SiteKnowledge.objects.filter(pk=knowledge.pk).exists()); self.assertFalse(AIResultSource.objects.exists())

    def test_initial_password_csrf_and_cross_actor_headers_guard_common_apis(self):
        initial=user('01000000004')
        self.assertEqual(login(initial).get('/api/ai/usage').json()['error']['code'],'PASSWORD_CHANGE_REQUIRED')
        client=login(self.admin); url=f'/api/sites/{self.site.pk}/knowledge'
        self.assertEqual(client.get(url,HTTP_X_TM_ACTOR=str(self.employee.pk)).status_code,403)
        from django.test import Client
        strict=login(self.admin,client=Client(enforce_csrf_checks=False)); strict.enforce_csrf_checks=True
        # Use a separate CSRF-enforcing client with the same authenticated session.
        enforced=Client(enforce_csrf_checks=True); enforced.cookies=strict.cookies
        self.assertEqual(enforced.post(url,{'title':'가짜'},content_type='application/json').status_code,403)

    def test_real_worker_process_crash_after_claim_then_restart_does_not_resend(self):
        task=self.task(); database=connection.settings_dict
        database_url=f"postgresql://{quote(database['USER'],safe='')}:{quote(database['PASSWORD'],safe='')}@{database['HOST']}:{database['PORT']}/{database['NAME']}"
        environment={key:value for key,value in os.environ.items() if not key.startswith('AI_')}
        environment.update(DJANGO_SETTINGS_MODULE='config.test_settings',DATABASE_URL=database_url)
        bootstrap="import django;django.setup();from django.test import override_settings;from apps.ai_assistant.worker import claim;"
        crash=bootstrap+"\nwith override_settings(AI_FOUNDATION_TEST_MODE=True):\n task=claim()\n assert task is not None\n import os;os._exit(23)"
        result=subprocess.run([sys.executable,'-c',crash],env=environment,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,23); task.refresh_from_db(); self.assertEqual(task.status,'RUNNING')
        AIRequest.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1),unknown_until=timezone.now()-timedelta(seconds=1))
        restart=bootstrap+"\nfrom django.core.management import call_command\nwith override_settings(AI_FOUNDATION_TEST_MODE=True):\n call_command('run_ai_worker',once=True)"
        result=subprocess.run([sys.executable,'-c',restart],env=environment,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0); task.refresh_from_db(); self.assertEqual(task.status,'FAILED')
        self.assertEqual(task.attempt_count,1); self.assertEqual(AIUsageAttempt.objects.count(),1); self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)
        self.assertEqual(task.charged_cost,task.reserved_cost)

    def test_worker_unknown_exception_is_not_retried_and_known_failure_usage_is_billed(self):
        task=self.task()
        class UnknownAdapter:
            def execute_task(self,*args):raise OutcomeUnknown('test-only private provider detail')
        self.assertEqual(run_once(UnknownAdapter()),{'processed':1,'succeeded':0})
        task.refresh_from_db(); self.assertEqual(task.status,'UNKNOWN'); self.assertEqual(run_once()['processed'],0)
        reap(now=task.unknown_until)
        next_task=self.task(feature='CLEANUP'); test=self
        class FailedAdapter:
            def execute_task(self,request,payload):raise ProviderFailed(test.response(request))
        self.assertEqual(run_once(FailedAdapter())['succeeded'],0); next_task.refresh_from_db()
        self.assertEqual(next_task.status,'FAILED'); self.assertGreater(next_task.charged_cost,0)

    def test_deletion_failure_rolls_back_ai_graph_quota_and_domain_together(self):
        task=self.task(); running=claim(); before=AIBudgetMonth.objects.get().reserved_usd
        with patch('apps.customers.deletions.erase_receipts',side_effect=RuntimeError('test-only')):
            with self.assertRaises(RuntimeError):self.hard()
        task.refresh_from_db(); self.assertEqual(task.status,'RUNNING'); self.assertTrue(task.input_payload)
        self.assertEqual(AIBudgetMonth.objects.get().reserved_usd,before); self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())
