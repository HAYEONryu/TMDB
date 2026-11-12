from datetime import datetime,timedelta
from uuid import uuid4
from unittest.mock import patch
from django.test import TestCase,override_settings
from django.utils import timezone
from apps.accounts.models import User
from apps.accounts.access import AccessError
from apps.accounts.services import reset_password
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerChangeEvent
from apps.customers.queries import KST
from apps.customers.services import update_row
from apps.operations.models import MutationReceipt
from tests.helpers import login,TEST_HASHERS
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class EmployeeTests(Fixtures,TestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.assignment=self.assign(self.customer)
        self.client=login(self.employee);self.headers={'HTTP_X_TM_QUEUE_USER':str(self.employee.pk)}

    def post(self,path,body,**kwargs):return self.client.post(path,body,content_type='application/json',**self.headers,**kwargs)
    def item(self,customer=None,**values):
        c=customer or self.customer
        return {'key':'fake-queue-key','site_id':str(c.site_id),'customer_id':str(c.pk),'assignment_id':str(c.current_assignment_id),'expected_version':c.version,**values}
    def check(self,item=None):return self.post('/api/employee/queue-check',{'entries':[item or self.item()]}).json()['results'][0]

    def test_page_employee_only_and_no_selection_or_export_controls(self):
        for path in ['/app/employee/today','/app/employee/mine']:
            response=self.client.get(path);self.assertContains(response,'employee-grid');self.assertNotContains(response,'선택 휴지통');self.assertNotContains(response,'다운로드')
        self.assertEqual(login(self.admin).get('/app/employee/mine').status_code,403)
        self.assertEqual(self.client.get('/app/admin/customers').status_code,403)

    def test_context_key_deterministic_per_account_never_in_html(self):
        own=self.client.get('/api/employee/context',**self.headers)
        self.assertEqual(own.status_code,200);data=own.json();self.assertEqual(data['target_ms'],90000);self.assertEqual(data['max_ms'],100000)
        self.assertEqual(data['key'],self.client.get('/api/employee/context',**self.headers).json()['key'])
        other=login(self.other).get('/api/employee/context',HTTP_X_TM_QUEUE_USER=str(self.other.pk)).json()
        self.assertNotEqual(data['key'],other['key']);self.assertNotContains(self.client.get('/app/employee/mine'),data['key'])
        self.assertEqual(own.headers['Cache-Control'],'no-store')

    def test_header_identity_missing_or_switched_user_rejects_reads_and_writes(self):
        self.assertEqual(self.client.get('/api/employee/context').status_code,403)
        for account in [self.other,self.admin]:
            client=login(account)
            for url in ['/api/employee/context','/api/customers?view=mine','/api/customers/filter-options?view=mine&field=customer_name']:
                self.assertEqual(client.get(url,**self.headers).status_code,403)
            self.assertEqual(client.post('/api/employee/batch-update',{'rows':[self.mutation(self.customer)]},content_type='application/json',**self.headers).status_code,403)
        self.customer.refresh_from_db();self.assertEqual(self.customer.notes,'')

    def test_queue_check_current_authority_only_read_and_hidden_foreign_row(self):
        before=(MutationReceipt.objects.count(),CustomerChangeEvent.objects.count())
        self.assertEqual(self.check()['code'],'READY');foreign=self.customers(offset=10)[0];self.assign(foreign,self.other)
        result=self.check(self.item(foreign));self.assertEqual(result,{'key':'fake-queue-key','code':'FORBIDDEN'})
        self.assertEqual((MutationReceipt.objects.count(),CustomerChangeEvent.objects.count()),before)

    def test_recall_same_employee_new_assignment_does_not_rebind_old_queue(self):
        old=self.item();change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer))
        self.customer.refresh_from_db();change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.employee))
        result=self.check(old);self.assertEqual(result['code'],'ASSIGNMENT_CHANGED');self.assertNotIn('server_row',result)
        row={**self.mutation(self.customer),'assignment_id':old['assignment_id']}
        result=self.post('/api/employee/batch-update',{'rows':[row]}).json()['results'][0]
        self.assertEqual(result['error']['code'],'ASSIGNMENT_CHANGED');self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_deleted_customer_queue_no_server_content(self):
        Customer.objects.filter(pk=self.customer.pk).update(deleted_at=timezone.now(),deleted_by=self.admin,current_assignment=None)
        result=self.check();self.assertEqual(result['code'],'CUSTOMER_DELETED');self.assertNotIn('server_row',result)
        response=self.post('/api/employee/batch-update',{'rows':[self.mutation(self.customer)]}).json()['results'][0]
        self.assertEqual(response['error']['code'],'CUSTOMER_DELETED')

    def test_lost_response_receipt_and_newer_server_state_both_returned(self):
        body=self.mutation(self.customer,'가상 첫 저장');saved=update_row(self.employee,body)
        self.customer.refresh_from_db();update_row(self.admin,self.mutation(self.customer,'다른 가상 변경'))
        result=self.check(self.item(expected_version=body['expected_version'],inflight=body))
        self.assertEqual(result['code'],'RECEIPT');self.assertEqual(result['receipt'],saved);self.assertEqual(result['server_row']['notes'],'다른 가상 변경')
        self.assertEqual(ConsultationRevision.objects.count(),2)
        result=self.check(self.item(inflight={**body,'changes':{'notes':'다른 내용'}}));self.assertEqual(result['code'],'IDEMPOTENCY_CONFLICT')

    def test_receipt_expiry_never_blindly_replays(self):
        body=self.mutation(self.customer);update_row(self.employee,body)
        MutationReceipt.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.check(self.item(inflight=body))['code'],'IDEMPOTENCY_EXPIRED')

    def test_partial_batch_atomic_rows_and_noop_does_not_mark_activity(self):
        second=self.customers(offset=20)[0];self.assign(second)
        noop=self.mutation(self.customer,'');result=self.post('/api/employee/batch-update',{'rows':[noop]}).json()['results'][0]
        self.assertFalse(result['changed']);self.assignment.refresh_from_db();self.assertIsNone(self.assignment.first_activity_at)
        invalid=self.mutation(second);invalid['changes']={'notes':'반영되면 안 됨','housing_status':'x'*201}
        good=self.mutation(self.customer,'가짜 상담 저장');result=self.post('/api/employee/batch-update',{'rows':[good,invalid]}).json()['results']
        self.assertEqual([row['ok'] for row in result],[True,False]);second.refresh_from_db();self.assertEqual(second.notes,'')
        self.assertEqual(ConsultationRevision.objects.count(),1);self.assignment.refresh_from_db();self.assertIsNotNone(self.assignment.first_activity_at)
        self.assertEqual(self.post('/api/employee/batch-update',{'rows':[good]}).json()['results'][0],result[0]);self.assertEqual(ConsultationRevision.objects.count(),1)

    def test_validation_limits_and_readonly_columns(self):
        for body in [{'entries':[]},{'entries':[self.item()]*101},{'entries':[self.item(key=1)]},{'entries':[self.item(expected_version=True)]}]:
            self.assertEqual(self.post('/api/employee/queue-check',body).status_code,422)
        row=self.mutation(self.customer);row['changes']={'phone_normalized':'01080009999'}
        self.assertEqual(self.post('/api/employee/batch-update',{'rows':[row]}).json()['results'][0]['error']['code'],'FORBIDDEN')
        self.assertEqual(self.post('/api/employee/batch-update',{'rows':[row]*101}).status_code,422)

    def test_password_reset_stops_queue_requests(self):
        reset_password(self.admin,self.employee.pk)
        self.assertEqual(self.client.get('/api/employee/context',**self.headers).status_code,401)
        self.assertEqual(self.post('/api/employee/batch-update',{'rows':[self.mutation(self.customer)]}).status_code,401)

    def test_role_change_between_http_check_and_locked_write_rejects_employee_queue(self):
        User.objects.filter(pk=self.employee.pk).update(role=User.Role.ADMIN)
        with self.assertRaises(AccessError) as error:update_row(self.employee,self.mutation(self.customer),employee_only=True)
        self.assertEqual(error.exception.code,'QUEUE_CONTEXT_MISMATCH');self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_today_kst_boundary_callback_union_priority_and_no_duplicates(self):
        now=datetime(2026,11,4,12,0,tzinfo=KST)
        rows=self.customers(5,offset=30)
        for c in rows:self.assign(c,at=now-timedelta(days=2))
        Assignment.objects.filter(pk=self.assignment.pk).update(assigned_at=now)
        for c,due in [(rows[0],now-timedelta(days=1)),(rows[1],now+timedelta(hours=5)),(rows[2],now.replace(hour=0)+timedelta(days=1)),(self.customer,now-timedelta(minutes=10))]:
            Callback.objects.create(customer=c,due_at=due,created_by=self.employee,updated_by=self.employee)
        with patch('apps.customers.queries.timezone.now',return_value=now):
            response=self.client.get('/api/customers',{'view':'today','site_id':self.site.pk},**self.headers).json()
        self.assertEqual([row['id'] for row in response['data']],[str(rows[0].pk),str(self.customer.pk),str(rows[1].pk)])
        self.assertEqual(response['total'],3)
