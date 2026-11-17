from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from django.db import OperationalError, close_old_connections
from django.test import TestCase, TransactionTestCase, Client, override_settings
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.services import change_assignee, recall
from apps.assignments.tm_recall import preview, recall_unfinished
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.bulk_deletions import approve_bulk
from apps.customers.deletions import approve, submit
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.customers.queries import KST, customer_list
from apps.customers.services import update_row, trash_operation
from apps.operations.models import IdempotencyRecord, OperationEvent
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class AdminTMOperationsTests(Fixtures,TestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,14,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare();self.client=login(self.admin)
        self.rows=self.customers(6)
        for row in self.rows:self.assign(row,at=self.now-timedelta(days=2))

    def request(self,row=None):
        row=row or self.rows[0]
        result,_=submit(self.employee,row.pk,{'assignment_id':str(row.current_assignment_id),'expected_version':row.version,'idempotency_key':str(uuid4())})
        return result['request_id']

    def bulk(self,ids,**extra):return {'request_ids':ids,'idempotency_key':str(uuid4()),**extra}
    def scope(self,employee=None,site=None):return {'site_id':str((site or self.site).pk),'employee_id':str((employee or self.employee).pk)}
    def confirmation(self,scope=None):
        scope=scope or self.scope();proof=preview(self.admin,scope)
        return {**scope,'confirmation':proof['confirmation'],'idempotency_key':str(uuid4())}
    def call(self,row,at=None):
        row.refresh_from_db()
        return update_row(self.employee,{**self.mutation(row),'changes':{'call_result':'NO_ANSWER'}})
    def revision(self,row):
        ConsultationRevision.objects.create(customer=row,assignment=row.current_assignment,actor=self.employee,source='MANUAL',
            saved_at=self.now-timedelta(days=1),customer_version=1,changed_fields=['call_result'],after_values={'call_result':'NO_ANSWER'})

    def test_bulk_approval_multisite_uses_individual_rules_latest_note_and_idempotency(self):
        a,b=self.rows[:2];b.site=self.second;b.save(update_fields=['site'])
        first,second=self.request(a),self.request(b)
        a.notes='가상 최신 상담';a.save(update_fields=['notes'])
        body=self.bulk([first,second]);result,status=approve_bulk(self.admin,body)
        self.assertEqual((status,result['approved_count'],result['excluded_count'],result['failed_count']),(200,2,0,0))
        a.refresh_from_db();b.refresh_from_db()
        self.assertIsNone(a.current_assignment_id);self.assertIsNotNone(a.deleted_at)
        self.assertTrue(a.notes.startswith('가상 최신 상담\n'))
        self.assertEqual(approve_bulk(self.admin,body),(result,200))
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),2)
        self.assertEqual(ConsultationRevision.objects.filter(source='SYSTEM_DELETE_NOTE').count(),2)
        self.assertEqual({r['site_name'] for r in result['items']},{self.site.name,self.second.name})

    def test_already_approved_closed_missing_requests_excluded_not_approved_again(self):
        ids=[self.request(row) for row in self.rows[:3]]
        approve(self.admin,ids[0],{'idempotency_key':str(uuid4())})
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.rows[1].pk)],'idempotency_key':str(uuid4())})
        result,_=approve_bulk(self.admin,self.bulk([*ids,str(uuid4())]))
        self.assertEqual((result['approved_count'],result['excluded_count']),(1,3))
        self.assertEqual({r.get('reason') for r in result['items'] if r['status']=='excluded'},{'ALREADY_APPROVED','REQUEST_CLOSED','REQUEST_DELETED'})
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),2)

    def test_partial_database_failure_preserves_success_and_resumes_same_batch(self):
        ids=[self.request(row) for row in self.rows[:3]];body=self.bulk(ids)
        actual=approve
        def sometimes(actor,rid,payload):
            if str(rid)==ids[1]:raise OperationalError('synthetic')
            return actual(actor,rid,payload)
        with patch('apps.customers.bulk_deletions.approve',side_effect=sometimes):
            result,_=approve_bulk(self.admin,body)
        self.assertEqual((result['approved_count'],result['failed_count']),(2,1))
        self.assertEqual(CustomerDeletionRequest.objects.get(pk=ids[1]).status,'PENDING')
        result,_=approve_bulk(self.admin,body)
        self.assertEqual((result['approved_count'],result['failed_count']),(3,0))
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),3)

    def test_crash_between_items_can_resume_without_duplicate_note(self):
        ids=[self.request(row) for row in self.rows[:2]];body=self.bulk(ids)
        from apps.customers.bulk_deletions import process_one
        calls=[]
        def crash(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('synthetic interruption')
            return process_one(*args)
        with patch('apps.customers.bulk_deletions.process_one',side_effect=crash):
            with self.assertRaises(RuntimeError):approve_bulk(self.admin,body)
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),1)
        result,_=approve_bulk(self.admin,body);self.assertEqual(result['approved_count'],2)
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),2)

    def test_bulk_rejects_changed_payload_duplicates_staff_and_csrf(self):
        rid=self.request();body=self.bulk([rid]);approve_bulk(self.admin,body)
        with self.assertRaises(AccessError):approve_bulk(self.admin,{**body,'request_ids':[rid,str(uuid4())]})
        for candidate in [self.bulk([]),self.bulk([rid,rid]),self.bulk([str(uuid4())]*101)]:
            self.assertEqual(self.client.post('/api/deletion-requests/bulk-approve',candidate,content_type='application/json').status_code,422)
        self.assertEqual(login(self.employee).post('/api/deletion-requests/bulk-approve',body,content_type='application/json').status_code,403)
        strict=Client(enforce_csrf_checks=True);strict.cookies.update(self.client.cookies)
        self.assertEqual(strict.post('/api/deletion-requests/bulk-approve',self.bulk([rid]),content_type='application/json').status_code,403)

    def test_recall_uses_shared_tm_status_all_dates_and_keeps_other_scope_and_history(self):
        old,today,done,due,other,elsewhere=self.rows
        from apps.assignments.models import Assignment
        Assignment.objects.filter(pk=today.current_assignment_id).update(assigned_at=self.now)
        self.revision(done);self.revision(due)
        callback=Callback.objects.create(customer=due,due_at=self.now,created_by=self.employee,updated_by=self.employee)
        Assignment.objects.filter(pk=other.current_assignment_id).update(employee=self.other)
        elsewhere.site=self.second;elsewhere.save(update_fields=['site'])
        listed=customer_list(self.employee,{'view':'today','site_id':str(self.site.pk),'page_size':50})
        expected={r['id'] for r in listed['data'] if r['tm_status']=='PENDING'}
        proof=preview(self.admin,self.scope());self.assertEqual(proof['target_count'],3)
        body={**self.scope(),'confirmation':proof['confirmation'],'idempotency_key':str(uuid4())}
        result,status=recall_unfinished(self.admin,body)
        self.assertEqual((status,result['recalled_count']),(200,3))
        actual={str(row.pk) for row in Customer.objects.filter(pk__in=[r.pk for r in self.rows],current_assignment=None)}
        self.assertEqual(actual,expected)
        for row in [done,other,elsewhere]:row.refresh_from_db();self.assertIsNotNone(row.current_assignment_id)
        self.assertTrue(Callback.objects.filter(pk=callback.pk,status='PENDING').exists())
        self.assertEqual(ConsultationRevision.objects.count(),2)
        self.assertEqual(recall_unfinished(self.admin,body),(result,200))
        self.assertEqual(OperationEvent.objects.filter(operation='TM_UNFINISHED_RECALL').count(),1)

    def test_completion_after_preview_aborts_every_recall_then_requires_fresh_confirmation(self):
        body=self.confirmation();self.call(self.rows[0])
        with self.assertRaises(AccessError) as error:recall_unfinished(self.admin,body)
        self.assertEqual(error.exception.code,'TM_TARGETS_CHANGED')
        fresh=error.exception.fields['preview'];self.assertEqual(fresh['target_count'],5)
        self.assertFalse(Customer.objects.filter(site=self.site,current_assignment=None).exists())
        result,_=recall_unfinished(self.admin,{**self.scope(),'confirmation':fresh['confirmation'],'idempotency_key':str(uuid4())})
        self.assertEqual(result['recalled_count'],5);self.rows[0].refresh_from_db();self.assertIsNotNone(self.rows[0].current_assignment_id)

    def test_reassignment_same_count_and_kst_date_changes_invalidate_confirmation(self):
        body=self.confirmation()
        change_assignee(self.admin,self.rows[0].pk,self.assignee_body(self.rows[0],self.other))
        self.rows[0].refresh_from_db()
        change_assignee(self.admin,self.rows[0].pk,self.assignee_body(self.rows[0],self.employee))
        with self.assertRaises(AccessError) as changed:recall_unfinished(self.admin,body)
        self.assertEqual(changed.exception.code,'TM_TARGETS_CHANGED')
        body=self.confirmation();self.now=self.now.replace(hour=0)+timedelta(days=1)
        with self.assertRaises(AccessError) as changed:recall_unfinished(self.admin,body)
        self.assertEqual(changed.exception.code,'TM_TARGETS_CHANGED')
        self.assertEqual(Customer.objects.filter(current_assignment=None).count(),0)

    def test_preview_staff_count_zero_completed_no_answer_and_strict_scope(self):
        for row in self.rows:self.revision(row)
        self.assertEqual(preview(self.admin,self.scope())['target_count'],0)
        for endpoint in ['/api/assignments/tm-recall-preview','/api/assignments/tm-recall']:
            self.assertEqual(login(self.employee).post(endpoint,self.scope(),content_type='application/json').status_code,403)
        self.assertEqual(self.client.post('/api/assignments/tm-recall-preview',{**self.scope(),'filters':{}},content_type='application/json').status_code,422)
        with self.assertRaises(AccessError):recall_unfinished(self.admin,{**self.scope(),'confirmation':'forged','idempotency_key':str(uuid4())})
        self.assertEqual(Customer.objects.filter(current_assignment=None).count(),0)

    def test_employee_deactivated_after_preview_returns_fresh_zero_and_no_recall(self):
        body=self.confirmation()
        User.objects.filter(pk=self.employee.pk).update(is_active=False)
        with self.assertRaises(AccessError) as error:recall_unfinished(self.admin,body)
        self.assertEqual(error.exception.code,'TM_TARGETS_CHANGED')
        self.assertEqual(error.exception.fields['preview']['target_count'],0)
        self.assertEqual(Customer.objects.filter(current_assignment=None).count(),0)

    def test_successful_recall_replay_never_recalls_a_later_reassignment(self):
        body=self.confirmation();result,_=recall_unfinished(self.admin,body)
        self.rows[0].refresh_from_db()
        change_assignee(self.admin,self.rows[0].pk,self.assignee_body(self.rows[0],self.employee))
        self.rows[0].refresh_from_db();new_id=self.rows[0].current_assignment_id
        replayed,_=recall_unfinished(self.admin,body)
        self.assertEqual(replayed,result)
        self.rows[0].refresh_from_db();self.assertEqual(self.rows[0].current_assignment_id,new_id)

    def test_old_today_recall_still_recalls_completed_today_only(self):
        from apps.assignments.models import Assignment
        Assignment.objects.filter(pk=self.rows[0].current_assignment_id).update(assigned_at=self.now)
        self.call(self.rows[0])
        result,_=recall(self.admin,self.recall_body(employee_id=str(self.employee.pk)))
        self.assertEqual(result['recalled_count'],1)
        self.assertEqual(Customer.objects.filter(current_assignment=None).count(),1)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class BulkApprovalConcurrencyTests(Fixtures,TransactionTestCase):
    def test_same_batch_concurrent_submissions_approve_once(self):
        self.prepare();row=self.customers()[0];self.assign(row)
        rid,_=submit(self.employee,row.pk,{'assignment_id':str(row.current_assignment_id),'expected_version':row.version,'idempotency_key':str(uuid4())})
        body={'request_ids':[rid['request_id']],'idempotency_key':str(uuid4())};barrier=Barrier(2)
        def run():
            close_old_connections()
            try:barrier.wait();return approve_bulk(User.objects.get(pk=self.admin.pk),body)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertTrue(all(r[0]['approved_count']==1 for r in results))
        self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),1)
