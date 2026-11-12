from datetime import datetime,timedelta
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from django.test import TransactionTestCase,override_settings,Client
from django.utils import timezone
from apps.accounts.models import User
from apps.ai_assistant.models import AIRequest,AIResult,AIQuotaBucket,AIUsageAttempt
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import run_once,claim,finish,ProviderResponse
from apps.ai_assistant.adapters import FoundationFakeAdapter
from apps.assignments.services import change_assignee
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerChangeEvent
from apps.customers.services import update_row
from apps.customers.queries import KST
from tests.helpers import TEST_HASHERS,login,user
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,AI_FOUNDATION_TEST_MODE=True,AI_CONFIG=TEST_AI)
class P10Tests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.assign(self.customer)
        self.customer.notes='가짜 상담 관심';self.customer.save();self.client=login(self.employee);self.headers={'HTTP_X_TM_QUEUE_USER':str(self.employee.pk)}

    def body(self,feature='CLEANUP',**values):
        self.customer.refresh_from_db();return {'feature':feature,'customer_id':str(self.customer.pk),'assignment_id':str(self.customer.current_assignment_id),'expected_version':self.customer.version,'idempotency_key':str(uuid4()),**values}
    def post(self,body,status=202):
        response=self.client.post('/api/ai/customer-tasks',body,content_type='application/json',**self.headers);self.assertEqual(response.status_code,status,response.content);return response.json()
    def completed(self,feature='CLEANUP'):
        body=self.body(feature);data=self.post(body);self.assertEqual(run_once()['succeeded'],1);return AIRequest.objects.get(pk=data['task_id'])
    def apply(self,task,changes=None,**values):
        self.customer.refresh_from_db();return update_row(self.employee,{**self.mutation(self.customer),'changes':changes or {'notes':task.result.payload['suggestions']['notes']['value']},'source_ai_result_id':str(task.result.pk),**values})

    def test_three_post_features_schemas_usage_and_readonly_customer(self):
        for feature in ['CLEANUP','SUMMARY','NEXT_QUESTIONS']:
            task=self.completed(feature);response=self.client.get(f'/api/ai/results/{task.result.pk}',**self.headers);self.assertEqual(response.status_code,200)
            data=response.json();self.assertEqual(data['schema_version'],'employee-v1');self.assertTrue(data['is_test']);self.assertEqual(data['assignment_id'],str(self.customer.current_assignment_id))
            self.assertEqual(data['source_customer_version'],1);self.assertTrue(data['source_ids']);self.assertEqual(data['customer_name'],self.customer.customer_name)
            if feature=='NEXT_QUESTIONS':self.assertEqual(len(data['payload']['questions']),3)
        self.customer.refresh_from_db();self.assertEqual(self.customer.notes,'가짜 상담 관심');self.assertEqual(self.customer.version,1)
        self.assertIsNone(self.customer.current_assignment.first_activity_at);self.assertEqual(ConsultationRevision.objects.count(),0);self.assertEqual(AIQuotaBucket.objects.get().successful_count,3)

    def test_apply_normal_mutation_atomic_provenance_before_after_and_replay(self):
        task=self.completed();body={**self.mutation(self.customer),'changes':{'notes':task.result.payload['suggestions']['notes']['value']},'source_ai_result_id':str(task.result.pk)}
        first=update_row(self.employee,body);second=update_row(self.employee,body);self.assertEqual(first,second);self.assertTrue(first['ok'])
        revision=ConsultationRevision.objects.get();self.assertEqual(revision.source,'AI_APPLIED');self.assertEqual(revision.source_ai_result_id,task.result.pk)
        self.assertEqual(revision.before_values['notes'],'가짜 상담 관심');self.assertEqual(revision.after_values['notes'],task.result.payload['suggestions']['notes']['value'])
        self.customer.refresh_from_db();self.assertIsNotNone(self.customer.current_assignment.first_activity_at)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,1);self.assertEqual(AIUsageAttempt.objects.count(),1);self.assertEqual(CustomerChangeEvent.objects.count(),1)

    def test_partial_selection_keeps_other_fields_and_all_default_no_suggestion(self):
        task=self.completed();suggestions=task.result.payload['suggestions']
        for field in ['call_result','visit_at','callback_due_at','housing_status','contract_status']:
            self.assertEqual(suggestions[field]['status'],'NO_SUGGESTION');self.assertIsNone(suggestions[field]['value'])
        self.apply(task);self.customer.refresh_from_db();self.assertEqual(self.customer.housing_status,'');self.assertIsNone(self.customer.visit_at)

    def test_stale_result_rejects_source_attribution_manual_explicit_save_allowed(self):
        task=self.completed();update_row(self.employee,self.mutation(self.customer,'더 새로운 가상 상담'))
        data=self.client.get(f'/api/ai/results/{task.result.pk}').json();self.assertTrue(data['stale'])
        result=self.apply(task);self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'AI_RESULT_STALE')
        self.customer.refresh_from_db();body=self.mutation(self.customer,task.result.payload['suggestions']['notes']['value']);self.assertTrue(update_row(self.employee,body)['ok'])
        self.assertEqual(ConsultationRevision.objects.order_by('-saved_at').first().source,'MANUAL')

    def test_foreign_result_summary_and_arbitrary_source_values_rejected(self):
        task=self.completed();self.assertEqual(self.apply(task,changes={'notes':'모델 제안과 다른 임의 값'})['error']['code'],'AI_SOURCE_MISMATCH')
        summary=self.completed('SUMMARY');self.assertEqual(self.apply(summary,changes={'notes':'가짜 읽기 전용 결과'})['error']['code'],'AI_RESULT_STALE')

    def test_current_assignment_and_actor_checked_for_generation_result_and_apply(self):
        task=self.completed();other=login(self.other)
        self.assertEqual(other.get(f'/api/ai/results/{task.result.pk}').status_code,403)
        self.assertEqual(login(self.admin).get(f'/api/ai/results/{task.result.pk}').status_code,403)
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other))
        self.assertEqual(self.client.get(f'/api/ai/results/{task.result.pk}').status_code,409)
        response=self.client.post('/api/ai/customer-tasks',self.body(),content_type='application/json',**self.headers);self.assertEqual(response.status_code,403)

    def test_no_key_blocks_new_work_but_saved_result_and_core_remain_readable(self):
        task=self.completed()
        with override_settings(AI_FOUNDATION_TEST_MODE=False):
            self.assertFalse(self.client.get('/api/ai/availability').json()['generation_available'])
            self.post(self.body('SUMMARY'),409);self.assertEqual(AIRequest.objects.count(),1)
            self.assertEqual(self.client.get(f'/api/ai/results/{task.result.pk}').status_code,200)
            self.assertEqual(self.client.get('/api/customers',{'view':'mine','site_id':self.site.pk}).status_code,200)

    def test_cache_and_original_key_response_loss_do_not_charge_twice(self):
        body=self.body();data=self.post(body);run_once();same=self.post(body,200);cached=self.post(self.body(),200)
        self.assertEqual(data['task_id'],same['task_id']);self.assertEqual(data['task_id'],cached['task_id']);self.assertTrue(cached['cached'])
        self.assertEqual(AIUsageAttempt.objects.count(),1);self.assertEqual(AIQuotaBucket.objects.get().successful_count,1)

    def test_customer_results_list_checks_assignment_and_never_generates(self):
        task=self.completed();query={'customer_id':str(self.customer.pk),'assignment_id':str(self.customer.current_assignment_id)}
        for _ in range(3):
            data=self.client.get('/api/ai/customer-results',query,**self.headers).json();self.assertEqual(data['items'][0]['result_id'],str(task.result.pk))
        self.assertEqual(AIUsageAttempt.objects.count(),1)
        self.assertEqual(self.client.get('/api/ai/customer-results',{**query,'assignment_id':str(uuid4())},**self.headers).status_code,403)

    def test_schema_blocks_unknown_fields_unfounded_quote_and_null_suggestion(self):
        for change in ['field','quote','null','enum']:
            task=reserve(self.employee,self.body())[0];running=claim();base=FoundationFakeAdapter().execute_task(running,running.input_payload);payload=base.payload
            if change=='field':payload['suggestions']['customer_name']=payload['suggestions']['notes']
            elif change=='quote':payload['suggestions']['notes']['evidence']='입력에 없는 근거'
            elif change=='null':payload['suggestions']['notes']['value']=None
            else:payload['suggestions']['call_result']={**payload['suggestions']['notes'],'value':'UNSUPPORTED'}
            self.assertFalse(finish(task.pk,running.lease_token,response=replace(base,payload=payload)))
        self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)

    def date_result(self,quote,value,known=True):
        origin=datetime(2026,10,10,15,0,tzinfo=KST);received=datetime(2026,11,5,12,0,tzinfo=KST)
        self.customer.notes=quote;self.customer.save()
        if known:
            ConsultationRevision.objects.create(customer=self.customer,assignment=self.customer.current_assignment,actor=self.employee,saved_at=origin,customer_version=self.customer.version,changed_fields=['notes'],before_values={},after_values={'notes':quote},notes=quote,source='MANUAL')
        with patch('django.utils.timezone.now',return_value=received):task=reserve(self.employee,self.body())[0];running=claim()
        response=FoundationFakeAdapter().execute_task(running,running.input_payload);response.payload['suggestions']['visit_at']={'status':'SUGGESTION','value':value,'source_ids':[str(self.customer.pk)],'evidence':quote,'reason':'시간 근거'}
        self.assertTrue(finish(task.pk,running.lease_token,response=response,now=received+timedelta(seconds=1)));task.refresh_from_db();return task.result.payload['suggestions']['visit_at']

    def test_old_relative_date_uses_original_note_timestamp_not_request_day(self):
        item=self.date_result('내일 14:30 방문 확인','2026-10-11T14:30:00+09:00');self.assertEqual(item['status'],'SUGGESTION')

    def test_relative_date_reanchored_to_today_or_unknown_timestamp_becomes_no_suggestion(self):
        item=self.date_result('내일 14:30 방문 확인','2026-11-06T14:30:00+09:00',known=False);self.assertEqual(item['status'],'NO_SUGGESTION');self.assertIsNone(item['value'])

    def test_known_old_note_cannot_move_tomorrow_to_request_date(self):
        item=self.date_result('내일 14:30 방문 확인','2026-11-06T14:30:00+09:00',known=True);self.assertEqual(item['status'],'NO_SUGGESTION');self.assertIsNone(item['value'])

    def test_explicit_absolute_datetime_requires_matching_evidence(self):
        item=self.date_result('2026-11-20 14:30 방문 확인','2026-11-20T14:30:00+09:00',known=False);self.assertEqual(item['status'],'SUGGESTION')

    def test_post_identity_csrf_initial_password_and_request_shape(self):
        self.assertEqual(self.client.post('/api/ai/customer-tasks',self.body(),content_type='application/json').status_code,403)
        for extra in [{'prompt':'임의'}, {'provider':'임의'}, {'model':'임의'}, {'api_key':'임의'}]:self.post({**self.body(),**extra},422)
        self.post(self.body(feature=[]),422)
        enforced=Client(enforce_csrf_checks=True);normal=login(self.employee);enforced.cookies=normal.cookies
        self.assertEqual(enforced.post('/api/ai/customer-tasks',self.body(),content_type='application/json',**self.headers).status_code,403)
        initial=user('01000000004');self.assertEqual(login(initial).post('/api/ai/customer-tasks',self.body(),content_type='application/json',HTTP_X_TM_QUEUE_USER=str(initial.pk)).json()['error']['code'],'PASSWORD_CHANGE_REQUIRED')

    def test_ai_save_receipt_recovery_accepts_source_metadata(self):
        task=self.completed();self.customer.refresh_from_db();body={**self.mutation(self.customer),'changes':{'notes':task.result.payload['suggestions']['notes']['value']},'source_ai_result_id':str(task.result.pk)}
        saved=update_row(self.employee,body)
        query={'entries':[{'key':'fake-ai-entry','site_id':str(self.site.pk),'customer_id':str(self.customer.pk),'assignment_id':body['assignment_id'],'expected_version':body['expected_version'],'inflight':body}]}
        response=self.client.post('/api/employee/queue-check',query,content_type='application/json',**self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['results'][0]['code'],'RECEIPT');self.assertEqual(response.json()['results'][0]['receipt'],saved)

    def test_ai_revision_failure_rolls_back_customer_callback_activity_and_receipt(self):
        task=self.completed()
        with patch('apps.customers.services.ConsultationRevision.objects.create',side_effect=RuntimeError('test-only')):
            with self.assertRaises(RuntimeError):self.apply(task)
        self.customer.refresh_from_db();self.assertEqual(self.customer.notes,'가짜 상담 관심');self.assertIsNone(self.customer.current_assignment.first_activity_at);self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_no_suggestion_null_cannot_clear_existing_call_result(self):
        self.customer.call_result='INTERESTED';self.customer.save();task=self.completed()
        result=self.apply(task,changes={'call_result':None});self.assertEqual(result['error']['code'],'AI_SOURCE_MISMATCH');self.customer.refresh_from_db();self.assertEqual(self.customer.call_result,'INTERESTED')

    def test_other_customer_result_id_cannot_be_attached_to_save(self):
        other=self.customers(offset=7)[0];other.notes='다른 가짜 고객 상담';other.save();self.assign(other)
        task=reserve(self.employee,{**self.body(),'customer_id':str(other.pk),'assignment_id':str(other.current_assignment_id)})[0];run_once();task.refresh_from_db()
        self.assertEqual(self.apply(task,changes={'notes':'다른 가짜 고객 제안'})['error']['code'],'FORBIDDEN');self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_noop_ai_application_does_not_create_revision_or_progress(self):
        task=self.completed();result=self.apply(task,changes={'notes':self.customer.notes});self.assertTrue(result['ok']);self.assertFalse(result['changed']);self.assertEqual(ConsultationRevision.objects.count(),0);self.customer.refresh_from_db();self.assertIsNone(self.customer.current_assignment.first_activity_at)

    def test_echoed_key_in_model_output_is_rejected_before_result_storage(self):
        task=reserve(self.employee,self.body())[0];running=claim();response=FoundationFakeAdapter().execute_task(running,running.input_payload);response.payload['suggestions']['notes']['value']=TEST_AI.api_key
        self.assertFalse(finish(task.pk,running.lease_token,response=response));task.refresh_from_db();self.assertEqual(task.result.payload,{});self.assertNotIn(TEST_AI.api_key,self.client.get(f'/api/ai/tasks/{task.pk}').content.decode());self.assertEqual(AIQuotaBucket.objects.get().successful_count,0)

    def test_availability_rejects_another_accounts_queue_header(self):
        response=self.client.get('/api/ai/availability',HTTP_X_TM_QUEUE_USER=str(self.other.pk));self.assertEqual(response.status_code,403);self.assertEqual(response.json()['error']['code'],'QUEUE_CONTEXT_MISMATCH')

    def custom_suggestion(self,field,value,quote):
        self.customer.notes=quote;self.customer.save();task=reserve(self.employee,self.body())[0];running=claim();response=FoundationFakeAdapter().execute_task(running,running.input_payload)
        response.payload['suggestions'][field]={'status':'SUGGESTION','value':value,'source_ids':[str(self.customer.pk)],'evidence':quote,'reason':'가짜 추천'}
        self.assertTrue(finish(task.pk,running.lease_token,response=response));task.refresh_from_db();return task.result.payload['suggestions'][field]

    def test_missing_price_or_contract_confirmation_is_no_suggestion(self):
        item=self.custom_suggestion('notes','분양가 1억원으로 확인됨','가격은 담당자에게 확인 필요');self.assertEqual(item['status'],'NO_SUGGESTION');self.assertIsNone(item['value'])
        # The failed fact recommendation still forms one valid, explicitly uncertain result.
        self.customer.version+=1;self.customer.save();item=self.custom_suggestion('contract_status','CONTRACTED','관심은 있으나 계약은 검토 중');self.assertEqual(item['status'],'NO_SUGGESTION')

    def test_explicit_contract_confirmation_and_existing_price_remain_grounded(self):
        item=self.custom_suggestion('contract_status','CONTRACTED','계약 체결 완료, 확인된 가격 1억원');self.assertEqual(item['status'],'SUGGESTION')
        self.customer.version+=1;self.customer.save();item=self.custom_suggestion('notes','확인 가격 1억원','확인된 가격 1억원');self.assertEqual(item['status'],'SUGGESTION')

    def test_new_subscription_and_cancellation_statuses_need_explicit_evidence(self):
        for value,quote in [('SUBSCRIBED','청약 접수 완료'),('SUB_CANCELLED','청약 해지 완료'),('CONTRACT_CANCELLED','계약 해지 완료')]:
            item=self.custom_suggestion('contract_status',value,quote)
            self.assertEqual(item['status'],'SUGGESTION')
            self.customer.version+=1;self.customer.save()
        item=self.custom_suggestion('contract_status','CONTRACT_CANCELLED','계약 해지 예정으로 검토 중')
        self.assertEqual(item['status'],'NO_SUGGESTION')

    def test_provider_schema_offers_only_current_business_choices(self):
        from apps.ai_assistant.openai_schema import schema
        from apps.customers.choices import CURRENT_CHOICES
        task=reserve(self.employee,self.body())[0]
        suggestions=schema(task)['properties']['suggestions']['properties']
        for field in ['call_result','contract_status','housing_status']:
            self.assertEqual(suggestions[field]['properties']['value']['enum'],[*CURRENT_CHOICES[field],None])

    def test_housing_ownership_cannot_be_inferred_from_previous_tenancy(self):
        item=self.custom_suggestion('housing_status','무주택','현재 전세로 거주 중')
        self.assertEqual(item['status'],'NO_SUGGESTION')
        self.customer.version+=1;self.customer.save()
        item=self.custom_suggestion('housing_status','무주택','무주택임을 고객이 확인함')
        self.assertEqual(item['status'],'SUGGESTION')

    def test_datetime_output_is_canonical_for_browser_and_normal_save(self):
        item=self.date_result('2026-11-20 14:00 방문 확인','2026-11-20T14+09:00',known=False);self.assertEqual(item['value'],'2026-11-20T14:00:00+09:00')

    def test_non_scalar_suggestion_status_fails_without_leaving_running_task(self):
        task=reserve(self.employee,self.body())[0];running=claim();response=FoundationFakeAdapter().execute_task(running,running.input_payload);response.payload['suggestions']['notes']['status']=[]
        self.assertFalse(finish(task.pk,running.lease_token,response=response));task.refresh_from_db();self.assertEqual(task.status,'FAILED');self.assertEqual(AIQuotaBucket.objects.get().reserved_count,0)
