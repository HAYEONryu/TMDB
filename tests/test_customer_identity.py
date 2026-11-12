"""Admin correction permissions and global live contact checks, synthetic data only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from apps.ai_assistant.inputs import build
from apps.ai_assistant.models import Feature
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.services import update_row
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerIdentityTests(Fixtures,TestCase):
    def setUp(self):
        self.prepare()
        self.customer=Customer.objects.create(site=self.site,customer_name='이전가상고객',phone_normalized='01093000001',
            notes='이전가상고객은 다음 연락을 희망합니다.',admin_notes='SYNTHETIC_PRIVATE_ADMIN_NOTE')
        self.assignment=self.assign(self.customer)

    def mutation(self,changes,customer=None):
        customer=customer or self.customer;customer.refresh_from_db()
        return dict(customer_id=str(customer.pk),assignment_id=str(customer.current_assignment_id) if customer.current_assignment_id else None,
                    mutation_id=str(uuid4()),expected_version=customer.version,changes=changes)

    def test_admin_corrects_identity_normalizes_phone_and_keeps_audit_and_idempotency(self):
        body=self.mutation({'customer_name':' 정정가상고객 ','phone_normalized':'010-9300-0002'})
        result=update_row(self.admin,body)
        self.assertTrue(result['ok']);self.assertEqual(result['row']['customer_name'],'정정가상고객')
        self.assertEqual(result['row']['phone_normalized'],'01093000002')
        revision=ConsultationRevision.objects.get(customer=self.customer)
        self.assertEqual(revision.before_values['customer_name'],'이전가상고객')
        self.assertEqual(revision.before_values['phone_normalized'],'01093000001')
        self.assertEqual(revision.after_values['customer_name'],'정정가상고객')
        self.assertEqual(revision.after_values['phone_normalized'],'01093000002')
        self.assignment.refresh_from_db();self.assertIsNone(self.assignment.first_activity_at)
        self.assertEqual(update_row(self.admin,body),result)
        noop=update_row(self.admin,self.mutation({'phone_normalized':'010-9300-0002'}))
        self.assertFalse(noop['changed']);self.assertEqual(noop['version'],2)
        self.assertEqual(ConsultationRevision.objects.filter(customer=self.customer).count(),1)

    def test_employee_cannot_forge_contact_or_private_note_changes(self):
        for changes in [{'customer_name':'must not save','phone_normalized':'01093000002','notes':'must not save'},
                        {'phone_normalized':'01093000002'},{'admin_notes':'forged'}]:
            result=update_row(self.employee,self.mutation(changes))
            self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'FORBIDDEN')
        self.customer.refresh_from_db()
        self.assertEqual((self.customer.customer_name,self.customer.phone_normalized,self.customer.version),('이전가상고객','01093000001',1))
        self.assertEqual(self.customer.notes,'이전가상고객은 다음 연락을 희망합니다.')

    def test_optional_name_and_required_valid_contact_and_type_limits(self):
        for actor in [self.admin,self.employee]:
            for changes in [{'customer_name':None},{'customer_name':42},{'customer_name':'가'*101}]:
                result=update_row(actor,self.mutation(changes))
                self.assertEqual(result['error']['code'],'VALIDATION_ERROR')
            result=update_row(actor,self.mutation({'customer_name':'  '}))
            self.assertTrue(result['ok']);self.assertEqual(result['row']['customer_name'],'')
        for changes in [{'phone_normalized':''},{'phone_normalized':1093000002},{'phone_normalized':'01193000002'}]:
            result=update_row(self.admin,self.mutation(changes))
            self.assertEqual(result['error']['code'],'VALIDATION_ERROR')

    def test_employee_name_correction_is_audited_idempotent_and_not_consultation_progress(self):
        body=self.mutation({'customer_name':' 직원 정정 '})
        response=login(self.employee).post('/api/employee/batch-update',{'rows':[body]},content_type='application/json',
                                         HTTP_X_TM_QUEUE_USER=str(self.employee.pk))
        result=response.json()['results'][0]
        self.assertTrue(result['ok']);self.assertEqual(result['row']['customer_name'],'직원 정정')
        self.assertNotIn('admin_notes',result['row'])
        revision=ConsultationRevision.objects.get(customer=self.customer)
        self.assertEqual((revision.actor_id,revision.before_values['customer_name'],revision.after_values['customer_name']),
                         (self.employee.pk,'이전가상고객','직원 정정'))
        self.assignment.refresh_from_db();self.assertIsNone(self.assignment.first_activity_at)
        self.assertEqual(update_row(self.employee,body),result)
        self.assertFalse(update_row(self.employee,self.mutation({'customer_name':' 직원 정정 '}))['changed'])
        self.assertEqual(ConsultationRevision.objects.filter(customer=self.customer).count(),1)
        saved=update_row(self.employee,self.mutation({'customer_name':'상담 동시 정정','notes':'실제 상담 변경'}))
        self.assertTrue(saved['ok']);self.assignment.refresh_from_db();self.assertIsNotNone(self.assignment.first_activity_at)

    def test_employee_name_correction_rejects_foreign_unassigned_recalled_and_stale_rows(self):
        from apps.accounts.access import AccessError
        from apps.assignments.services import change_assignee
        unassigned=self.customers(offset=60)[0]
        foreign=self.customers(offset=61)[0];self.assign(foreign,self.other)
        for target in [unassigned,foreign]:
            with self.assertRaises(AccessError) as denied:update_row(self.employee,self.mutation({'customer_name':'거절'},target))
            self.assertEqual(denied.exception.code,'FORBIDDEN')
        stale=self.mutation({'customer_name':'오래된 이름'})
        update_row(self.admin,self.mutation({'customer_name':'관리자 최신 이름'}))
        self.assertEqual(update_row(self.employee,stale)['error']['code'],'VERSION_CONFLICT')
        self.customer.refresh_from_db();late=self.mutation({'customer_name':'회수 후 저장'})
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer))
        with self.assertRaises(AccessError) as denied:update_row(self.employee,late)
        self.assertEqual(denied.exception.code,'ASSIGNMENT_CHANGED')

    def test_global_live_duplicate_rejects_entire_row_but_trash_is_allowed(self):
        other=Customer.objects.create(site=self.site,phone_normalized='01093000002')
        result=update_row(self.admin,self.mutation({'phone_normalized':'010-9300-0002','notes':'must not save'}))
        self.assertEqual(result['error']['code'],'DUPLICATE_PHONE')
        self.customer.refresh_from_db();self.assertEqual(self.customer.version,1)
        self.assertEqual(self.customer.notes,'이전가상고객은 다음 연락을 희망합니다.')
        other.deleted_at=timezone.now();other.deleted_by=self.admin;other.save()
        self.assertTrue(update_row(self.admin,self.mutation({'phone_normalized':'01093000002'}))['ok'])
        Customer.objects.create(site=self.second,phone_normalized='01093000003')
        self.assertEqual(update_row(self.admin,self.mutation({'phone_normalized':'01093000003'}))['error']['code'],'DUPLICATE_PHONE')

    def test_stale_employee_save_after_admin_correction_requires_review(self):
        stale=self.mutation({'notes':'old draft'})
        update_row(self.admin,self.mutation({'customer_name':'정정가상고객','phone_normalized':'01093000002'}))
        result=update_row(self.employee,stale)
        self.assertEqual(result['error']['code'],'VERSION_CONFLICT')
        self.assertEqual(result['server_row']['customer_name'],'정정가상고객')
        self.assertNotIn('admin_notes',result['server_row'])
        self.assertNotIn('SYNTHETIC_PRIVATE_ADMIN_NOTE',json.dumps(result))

    def test_admin_can_edit_unassigned_customer_and_employee_http_endpoint_allows_own_name(self):
        unassigned=Customer.objects.create(site=self.site,phone_normalized='01093000009')
        self.assertTrue(update_row(self.admin,self.mutation({'customer_name':'미할당 정정'},unassigned))['ok'])
        response=login(self.employee).post('/api/customers/batch-update',{'rows':[self.mutation({'customer_name':'forged'})]},content_type='application/json')
        self.assertTrue(response.json()['results'][0]['ok'])

    def test_old_names_remain_redacted_in_employee_and_manager_ai_inputs(self):
        now=timezone.now()
        ConsultationRevision.objects.create(customer=self.customer,actor=self.employee,assignment=self.assignment,
            customer_version=1,saved_at=now-timedelta(minutes=1),source='MANUAL',changed_fields=['notes'],
            notes=self.customer.notes,after_values={'notes':self.customer.notes,'call_result':None,'contract_status':'UNKNOWN'})
        update_row(self.admin,self.mutation({'customer_name':'정정가상고객','phone_normalized':'01093000002'}))
        update_row(self.employee,self.mutation({'customer_name':'직원정정가상고객'}))
        self.customer.refresh_from_db();now=timezone.now()
        for feature in [Feature.CLEANUP,Feature.SUMMARY,Feature.NEXT_QUESTIONS,Feature.WEEKLY_BRIEFING]:
            payload,_=build(feature,customer=self.customer if feature!=Feature.WEEKLY_BRIEFING else None,
                site=self.site,start=now-timedelta(days=7),end=now,korean_date=timezone.localdate())
            encoded=json.dumps(payload,ensure_ascii=False)
            for private in ['이전가상고객','정정가상고객','직원정정가상고객','01093000001','01093000002','SYNTHETIC_PRIVATE_ADMIN_NOTE']:
                self.assertNotIn(private,encoded)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerIdentityConcurrencyTests(Fixtures,TransactionTestCase):
    def test_two_admin_corrections_cannot_claim_the_same_site_contact(self):
        self.prepare();rows=self.customers(2);barrier=Barrier(2)
        def save(customer):
            close_old_connections()
            try:
                body=dict(customer_id=str(customer.pk),assignment_id=None,mutation_id=str(uuid4()),
                          expected_version=1,changes={'phone_normalized':'01095000001'})
                barrier.wait(timeout=10)
                result=update_row(self.admin,body)
                return 'ok' if result['ok'] else result['error']['code']
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,rows))
        self.assertCountEqual(results,['ok','DUPLICATE_PHONE'])
        self.assertEqual(Customer.objects.filter(site=self.site,phone_normalized='01095000001').count(),1)
        self.assertEqual(Customer.objects.filter(site=self.site).count(),2)
