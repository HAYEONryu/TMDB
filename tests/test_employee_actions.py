"""Preparation is local, read-only, and cannot spend a quota reservation."""
from dataclasses import replace
from uuid import uuid4
from django.test import TestCase, override_settings
from apps.ai_assistant.models import AIRequest, AIQuotaBucket, AIUsageAttempt
from apps.assignments.services import change_assignee
from config.ai import AIConfig
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=True, AI_CONFIG=TEST_AI)
class EmployeeActionPreparationTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.assign(self.customer)
        self.client=login(self.employee);self.headers={'HTTP_X_TM_QUEUE_USER':str(self.employee.pk)}

    def params(self,feature='SUMMARY'):
        self.customer.refresh_from_db()
        return {'feature':feature,'customer_id':str(self.customer.pk),'assignment_id':str(self.customer.current_assignment_id),'expected_version':self.customer.version}

    def test_empty_notes_all_features_reject_before_quota_and_no_customer_text_returned(self):
        for feature in ['CLEANUP','SUMMARY','NEXT_QUESTIONS']:
            params=self.params(feature)
            response=self.client.get('/api/ai/customer-readiness',params,**self.headers)
            self.assertEqual(response.status_code,200);self.assertFalse(response.json()['ready'])
            self.assertEqual(response.json()['code'],'AI_INPUT_REQUIRED')
            self.assertNotIn(self.customer.phone_normalized,response.content.decode())
            response=self.client.post('/api/ai/customer-tasks',{**params,'idempotency_key':str(uuid4())},content_type='application/json',**self.headers)
            self.assertEqual(response.status_code,422)
        for model in [AIRequest,AIQuotaBucket,AIUsageAttempt]:self.assertEqual(model.objects.count(),0)

    def test_readiness_allows_saved_notes_rejects_stale_foreign_and_late_submission(self):
        self.customer.notes='가상 관심과 다음 통화 약속';self.customer.save(update_fields=['notes'])
        params=self.params()
        self.assertTrue(self.client.get('/api/ai/customer-readiness',params,**self.headers).json()['ready'])
        self.assertEqual(self.client.get('/api/ai/customer-readiness',{**params,'expected_version':0},**self.headers).status_code,409)
        other=login(self.other)
        self.assertEqual(other.get('/api/ai/customer-readiness',params,HTTP_X_TM_QUEUE_USER=str(self.other.pk)).status_code,403)
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other))
        self.assertEqual(self.client.get('/api/ai/customer-readiness',params,**self.headers).status_code,409)
        response=self.client.post('/api/ai/customer-tasks',{**params,'idempotency_key':str(uuid4())},content_type='application/json',**self.headers)
        self.assertEqual(response.status_code,409);self.assertEqual(AIRequest.objects.count(),0)

    def test_large_input_gives_preparation_message_without_creating_work(self):
        self.customer.notes='가'*10000;self.customer.save(update_fields=['notes'])
        data=self.client.get('/api/ai/customer-readiness',self.params(),**self.headers).json()
        self.assertFalse(data['ready']);self.assertEqual(data['code'],'AI_INPUT_TOO_LARGE')
        self.assertIn('핵심 상담내용',data['message']);self.assertEqual(AIRequest.objects.count(),0)

    def test_preprocessing_excludes_name_only_audit_but_preserves_redaction(self):
        from apps.ai_assistant.inputs import build
        from apps.customers.services import update_row
        from django.utils import timezone
        self.customer.notes='상담 관심과 방문 문의';self.customer.save(update_fields=['notes'])
        old_name=self.customer.customer_name
        self.assertTrue(update_row(self.employee,self.mutation(self.customer)|{'changes':{'customer_name':'가상 정정 이름'}})['ok'])
        self.customer.refresh_from_db();now=timezone.now()
        payload,sources=build('SUMMARY',customer=self.customer,site=self.site,start=now,end=now,korean_date=now.date())
        self.assertEqual(payload['records'],[])
        self.assertEqual(len(sources),1)
        self.assertNotIn(old_name,str(payload));self.assertNotIn('가상 정정 이름',str(payload))
        from apps.consultations.models import ConsultationRevision
        ConsultationRevision.objects.create(customer=self.customer,customer_version=1,source='BASELINE',saved_at=now,
            changed_fields=[],after_values={'notes':'가상 도입 상담'},notes='가상 도입 상담')
        payload,_=build('SUMMARY',customer=self.customer,site=self.site,start=now,end=now,korean_date=now.date())
        self.assertEqual(len(payload['records']),1);self.assertEqual(payload['records'][0]['source'],'BASELINE')

    def test_disabled_and_unconfirmed_configuration_explains_preparation_without_key(self):
        from tests.test_free_ai_limits import FREE
        for config,expected in [(AIConfig(),'활성화'),(replace(FREE,free_tier_confirmed=False),'무료 등급'),(replace(FREE,configured=False),'API 키')]:
            with override_settings(AI_FOUNDATION_TEST_MODE=False,AI_CONFIG=config):
                response=self.client.get('/api/ai/availability',**self.headers)
                self.assertFalse(response.json()['generation_available']);self.assertIn(expected,response.json()['message'])
                if config.api_key:self.assertNotIn(config.api_key,response.content.decode())

    def test_history_projects_changed_fields_and_keeps_full_database_revision(self):
        import json
        from django.utils import timezone
        from apps.customers.services import update_row
        from apps.consultations.models import ConsultationRevision
        from scripts.verification_evidence import artifact_path
        self.customer.notes='가상 상담 보존 문장 '*300
        self.customer.save(update_fields=['notes'])
        body=self.mutation(self.customer)|{'changes':{'callback_due_at':timezone.now().isoformat()}}
        self.assertTrue(update_row(self.employee,body)['ok'])
        params={'kind':'consultations','assignment_id':str(self.customer.current_assignment_id)}
        response=self.client.get(f'/api/customers/{self.customer.pk}/history',params,**self.headers)
        self.assertEqual(response.status_code,200)
        row=response.json()['data'][0]
        self.assertEqual(set(row['before_values']),{'callback_due_at'})
        self.assertEqual(set(row['after_values']),{'callback_due_at'})
        self.assertNotIn('notes',row)
        revision=ConsultationRevision.objects.get(customer=self.customer)
        self.assertEqual(revision.notes,self.customer.notes)
        self.assertEqual(revision.after_values['notes'],self.customer.notes)
        legacy={**row,'before_values':revision.before_values,'after_values':revision.after_values,'notes':revision.notes}
        old_size=len(json.dumps(legacy,ensure_ascii=False).encode());new_size=len(json.dumps(row,ensure_ascii=False).encode())
        self.assertLess(new_size,old_size/2)
        artifact_path('history-response-size.json').write_text(json.dumps({'synthetic':True,'legacy_row_bytes':old_size,'projected_row_bytes':new_size,'reduction_percent':round(100*(1-new_size/old_size),2),'database_rows_deleted':0}))
