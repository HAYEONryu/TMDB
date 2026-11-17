"""Today's TM: assignment-bound evidence, carryover, callback work and confirmed saves."""
from datetime import datetime, timedelta
import json
from unittest.mock import patch
from uuid import uuid4
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee, recall
from apps.callbacks.models import Callback
from apps.callbacks.services import complete
from apps.consultations.models import ConsultationRevision, CustomerActivity, PerformanceTracking
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import update_row, trash_operation
from apps.operations.employee_performance import performance
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class TodayTMTests(Fixtures, TestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,14,30,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare();self.client=login(self.employee)
        self.row=self.customers()[0];self.assign(self.row,at=self.now-timedelta(days=1))

    def listing(self,**params):
        response=self.client.get('/api/customers',{'view':'today','site_id':str(self.site.pk),**params})
        self.assertEqual(response.status_code,200);return response.json()

    def statuses(self,**params):return {row['id']:row['tm_status'] for row in self.listing(**params)['data']}

    def save(self,**changes):
        self.row.refresh_from_db()
        result=update_row(self.employee,{**self.mutation(self.row),'changes':changes})
        self.row.refresh_from_db();return result

    def revision(self,customer=None,*,actor=None,assignment=None,at=None,source='MANUAL',fields=None,result='NO_ANSWER'):
        row=customer or self.row
        return ConsultationRevision.objects.create(customer=row,assignment=assignment or row.current_assignment,
            actor=actor or self.employee,saved_at=at or self.now,source=source,
            customer_version=ConsultationRevision.objects.filter(customer=row).count()+1,
            changed_fields=['call_result'] if fields is None else fields,after_values={'call_result':result})

    def callback(self,*,due=None):
        return Callback.objects.create(customer=self.row,due_at=due or self.now,created_by=self.employee,updated_by=self.employee)

    def finish(self,callback):
        self.row.refresh_from_db();callback.refresh_from_db()
        return complete(self.employee,self.row.pk,{'callback_id':str(callback.pk),'callback_version':callback.version,
            'assignment_id':str(self.row.current_assignment_id),'expected_version':self.row.version,'idempotency_key':str(uuid4())})

    def test_old_unfinished_without_callback_carries_and_confirmed_call_stays_until_midnight(self):
        self.assertEqual(self.statuses(),{str(self.row.pk):'PENDING'})
        result=self.save(call_result='NO_ANSWER')
        self.assertTrue(result['ok']);self.assertEqual(result['row']['tm_status'],'COMPLETED')
        self.assertEqual(self.statuses(),{str(self.row.pk):'COMPLETED'})
        self.now=self.now.replace(hour=23,minute=59,second=59,microsecond=999999)
        self.assertEqual(self.statuses(),{str(self.row.pk):'COMPLETED'})
        self.now+=timedelta(microseconds=1)
        self.assertEqual(self.statuses(),{})

    def test_new_assignments_remain_today_regardless_of_completion(self):
        Assignment.objects.filter(pk=self.row.current_assignment_id).update(assigned_at=self.now)
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        self.save(call_result='INTERESTED')
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')

    def test_name_notes_memo_booking_and_first_activity_do_not_count_as_call_result(self):
        for changes in [{'customer_name':'가상 정정'},{'notes':'가상 비고'},{'memo':'일반 비고'},
                        {'visit_at':self.now.isoformat()},{'contract_status':'CONTRACTED'}]:
            self.assertTrue(self.save(**changes)['ok'])
            self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        self.row.current_assignment.refresh_from_db()
        self.assertIsNotNone(self.row.current_assignment.first_activity_at)
        self.assertFalse(self.save(phone_normalized='01011112222')['ok'])
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')

    def test_previous_actor_assignment_and_unchanged_inherited_result_are_not_proof(self):
        self.save(call_result='NO_ANSWER')
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.other))
        self.row.refresh_from_db()
        other=login(self.other).get('/api/customers',{'view':'today','site_id':str(self.site.pk)}).json()
        self.assertEqual(other['data'][0]['tm_status'],'PENDING')
        body={**self.mutation(self.row),'changes':{'call_result':'NO_ANSWER'}}
        unchanged=update_row(self.other,body)
        self.assertFalse(unchanged['changed']);self.assertEqual(unchanged['row']['tm_status'],'PENDING')
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.employee));self.row.refresh_from_db()
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')

    def test_only_human_current_employee_result_changes_with_complete_snapshots_count(self):
        for args in [{'actor':self.admin},{'source':'IMPORT'},{'source':'BASELINE'},{'source':'SYSTEM_DELETE_NOTE'},
                     {'fields':['notes']},{'fields':[]},{'result':None},{'result':''},
                     {'at':self.now+timedelta(seconds=1)},{'at':self.now-timedelta(days=2)}]:
            self.revision(**args);self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        self.revision(source='AI_APPLIED')
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')

    def test_due_callback_overrides_old_call_and_completion_stays_today_then_reappears_when_due(self):
        self.revision(at=self.now-timedelta(hours=20))
        self.assertEqual(self.statuses(),{})
        cb=self.callback(due=self.now.replace(hour=23))
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        result,status=self.finish(cb)
        self.assertEqual(status,200);self.assertEqual(result['row']['tm_status'],'COMPLETED')
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')
        self.now+=timedelta(days=1);self.client=login(self.employee)
        self.assertEqual(self.statuses(),{})
        self.callback(due=self.now)
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')

    def test_callback_completion_without_initial_result_remains_pending(self):
        cb=self.callback(due=self.now-timedelta(days=1))
        self.finish(cb)
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')

    def test_future_callback_does_not_block_but_cancel_is_not_a_completion(self):
        self.revision(at=self.now-timedelta(hours=20))
        cb=self.callback(due=self.now.replace(hour=0,minute=0)+timedelta(days=1))
        self.assertEqual(self.statuses(),{})
        self.assertEqual(self.save(call_result='INTERESTED')['row']['tm_status'],'COMPLETED')
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')
        self.now+=timedelta(days=1);self.client=login(self.employee);self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        self.save(callback_due_at=None)
        self.assertEqual(self.statuses(),{})
        cb.refresh_from_db();self.assertEqual(cb.status,'CANCELLED')

    def test_completed_callback_requires_matching_assignment_revision_not_just_actor_time(self):
        self.revision(at=self.now-timedelta(hours=20))
        cb=self.callback();cb.status='COMPLETED';cb.completed_at=self.now;cb.completed_by=self.employee;cb.save()
        self.assertEqual(self.statuses(),{})
        self.revision(fields=['callback_due_at'])
        self.assertEqual(self.statuses(),{})  # Missing explicit completion snapshot.
        ConsultationRevision.objects.filter(customer=self.row,changed_fields=['callback_due_at']).update(after_values={'callback_due_at':None})
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')

    def test_recall_reassignment_trash_other_site_other_employee_and_future_assignment_excluded(self):
        own,foreign,outside,future=self.customers(4,offset=10)
        self.assign(own);self.assign(foreign,self.other)
        self.assign(future,at=self.now+timedelta(seconds=1))
        outside.site=self.second;outside.save();self.assign(outside)
        self.assertEqual(set(self.statuses()),{str(self.row.pk),str(own.pk)})
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.other))
        self.assertEqual(set(self.statuses()),{str(own.pk)})
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(own.pk)],'idempotency_key':str(uuid4())})
        self.assertEqual(self.statuses(),{})
        self.now+=timedelta(seconds=1);recall(self.admin,self.recall_body(employee_id=str(self.employee.pk)))
        self.assertEqual(self.statuses(),{})

    def test_kst_callback_midnight_and_utc_result_boundaries(self):
        self.now=datetime(2026,11,18,0,0,tzinfo=KST)
        self.revision(at=datetime.fromisoformat('2026-11-17T14:59:59.999999+00:00'))
        self.assertEqual(self.statuses(),{})
        self.callback(due=datetime.fromisoformat('2026-11-17T15:00:00+00:00'))
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')

    def test_failed_save_and_unknown_response_do_not_invent_done_and_receipt_rechecks_current_day(self):
        invalid=self.save(call_result='INVALID')
        self.assertFalse(invalid['ok']);self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        body={**self.mutation(self.row),'changes':{'call_result':'NO_ANSWER'}}
        with patch('apps.customers.services.ConsultationRevision.objects.create',side_effect=IntegrityError('synthetic')):
            response=self.client.post('/api/employee/batch-update',{'rows':[body]},content_type='application/json',HTTP_X_TM_QUEUE_USER=str(self.employee.pk))
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.statuses()[str(self.row.pk)],'PENDING')
        saved=update_row(self.employee,body)
        self.assertEqual(saved['row']['tm_status'],'COMPLETED')
        self.callback(due=self.now.replace(hour=0,minute=0)+timedelta(days=1))
        self.now+=timedelta(days=1)
        self.assertEqual(update_row(self.employee,body)['row']['tm_status'],'PENDING')

    def test_union_deduplicates_and_retains_search_filter_pagination_and_readonly_permissions(self):
        rows=self.customers(53,offset=100)
        for row in rows:self.assign(row,at=self.now-timedelta(days=1))
        self.callback()
        data=self.listing();self.assertEqual(data['total'],54);self.assertEqual(len(data['data']),50)
        self.assertEqual(len(set(row['id'] for row in data['data'])),50)
        self.assertEqual(len(self.listing(page=2)['data']),4)
        self.assertEqual(self.listing(q=self.row.phone_normalized)['total'],1)
        self.save(call_result='NO_ANSWER')
        self.assertEqual(self.listing(filters=json.dumps({'call_result':['NO_ANSWER']}))['total'],1)
        self.assertFalse(self.save(tm_status='COMPLETED')['ok'])
        self.assertEqual(login(self.admin).get('/app/employee/today').status_code,403)
        with CaptureQueriesContext(connection) as queries:self.listing()
        self.assertLess(len(queries),14)

    def test_no_answer_completes_tm_without_creating_connected_calls(self):
        PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':self.now-timedelta(days=1)})
        self.save(call_result='NO_ANSWER')
        self.assertEqual(self.statuses()[str(self.row.pk)],'COMPLETED')
        report=performance(self.employee,self.site.pk,self.now.date().replace(day=1),self.now)
        self.assertEqual((report['today']['attempts'],report['today']['connected']),(0,0))
        self.assertFalse(CustomerActivity.objects.exists())
