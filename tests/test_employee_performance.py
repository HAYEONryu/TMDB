"""Real event counts, ownership-independent attribution and KST calendar boundaries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from django.db import IntegrityError, close_old_connections, transaction, connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client, TransactionTestCase, override_settings
from apps.accounts.models import User
from apps.assignments.services import change_assignee, recall
from apps.consultations.activities import record_activity
from apps.consultations.models import CustomerActivity, ConsultationRevision, PerformanceTracking
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import update_row, trash_operation
from apps.operations.employee_performance import performance
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class EmployeePerformanceTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,14,30,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare();self.client=login(self.employee)
        PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':datetime(2026,10,10,9,tzinfo=KST)})
        MigrationRecorder.Migration.objects.filter(app='consultations',name='0001_initial').update(applied=datetime(2026,9,1,tzinfo=KST))
        self.a,self.b,self.foreign=self.customers(3)
        self.assign(self.a);self.assign(self.b);self.assign(self.foreign,self.other)
        self.outside=self.customers(site=self.second,offset=20)[0];self.assign(self.outside)

    def body_for(self,customer=None,kind='CALL',**extra):
        customer=customer or self.a
        return {'site_id':str(customer.site_id),'assignment_id':str(customer.current_assignment_id),
                'kind':kind,'idempotency_key':str(uuid4()),**({'occurred_at':self.now.isoformat(),'connection':'UNKNOWN'} if kind=='CALL' else {'visited_on':self.now.date().isoformat()}),**extra}

    def record(self,customer=None,actor=None,**extra):
        customer=customer or self.a
        result,status=record_activity(actor or self.employee,customer.pk,self.body_for(customer,**extra))
        self.assertEqual(status,201);return result

    def report(self,month=None,site=None,client=None,**extra):
        response=(client or self.client).get('/api/dashboard/performance',{'site_id':str((site or self.site).pk),**({'month':month} if month else {}),**extra})
        self.assertEqual(response.status_code,200);return response.json()

    def day(self,data,value):
        return next(row for row in data['rows'] if row['date']==value)

    def revision(self,customer=None,actor=None,at=None,fields=None,result='INTERESTED',source='MANUAL',snapshot=True):
        customer=customer or self.a
        return ConsultationRevision.objects.create(customer=customer,assignment=customer.current_assignment,actor=actor or self.employee,
            saved_at=at or self.now,customer_version=ConsultationRevision.objects.filter(customer=customer).count()+1,
            changed_fields=fields or ['notes'],after_values={'call_result':result} if snapshot else {},source=source)

    def test_two_calls_one_connected_retry_unknown_and_today_row_match(self):
        body=self.body_for(connection='CONNECTED');result,status=record_activity(self.employee,self.a.pk,body)
        self.assertEqual(status,201)
        self.assertEqual(record_activity(self.employee,self.a.pk,body),(result,200))
        self.record(connection='NOT_CONNECTED')
        data=self.report()
        self.assertEqual((data['today']['attempts'],data['today']['connected']),(2,1))
        self.assertEqual(self.day(data,'2026-11-17')['call_count'],2)
        self.record(connection='UNKNOWN')
        self.assertEqual((self.report()['today']['attempts'],self.report()['today']['connected']),(3,1))
        self.assertEqual(CustomerActivity.objects.count(),3)
        self.assertFalse(ConsultationRevision.objects.exists())

    def test_saves_current_states_completed_callback_and_booked_visit_are_not_calls_or_actual_visits(self):
        Customer.objects.filter(pk=self.a.pk).update(call_result='VISITED',visit_at=self.now)
        self.revision(result='VISITED');self.revision(result='VISIT_BOOKED')
        booked=self.customers(offset=60)[0];self.assign(booked)
        Customer.objects.filter(pk=booked.pk).update(visit_at=self.now,call_result='VISIT_BOOKED')
        self.record(kind='VISIT')
        self.record(kind='VISIT')
        self.record(self.b,kind='VISIT')
        data=self.report();day=self.day(data,'2026-11-17')
        self.assertEqual((data['today']['attempts'],data['today']['connected'],day['visit_count']),(0,0,2))
        self.assertEqual(Customer.objects.get(pk=self.a.pk).call_result,'VISITED')
        self.assertEqual(self.day(self.report('2026-11'),'2026-11-16')['visit_count'],0)

    def test_prospects_use_actual_human_authors_snapshots_and_unique_customer_per_day(self):
        self.revision();self.revision(source='AI_APPLIED');self.revision(self.b)
        self.revision(self.foreign,actor=self.other);self.revision(self.a,actor=self.admin)
        for fields in [['customer_name'],['admin_notes'],['customer_name','phone_normalized']]:self.revision(fields=fields)
        for source in ['IMPORT','BASELINE','SYSTEM_DELETE_NOTE']:self.revision(source=source)
        self.revision(self.b,result='NO_ANSWER')
        Customer.objects.filter(pk=self.a.pk).update(call_result='REJECTED')
        self.assertEqual(self.day(self.report(),'2026-11-17')['prospect_count'],2)
        self.assertEqual(self.day(self.report(client=login(self.other)),'2026-11-17')['prospect_count'],1)

    def test_recall_reassignment_and_trash_preserve_attribution_and_own_receipt(self):
        body=self.body_for(connection='CONNECTED');record_activity(self.employee,self.a.pk,body)
        self.record(kind='VISIT');self.revision()
        change_assignee(self.admin,self.a.pk,self.assignee_body(self.a,self.other))
        self.a.refresh_from_db()
        self.assertEqual(record_activity(self.employee,self.a.pk,body)[1],200)
        self.assertEqual(self.report()['today']['attempts'],1)
        other_client=login(self.other)
        other_data=self.report(client=other_client)
        self.assertEqual(other_data['today']['attempts'],0)
        self.assertEqual((self.day(other_data,'2026-11-17')['prospect_count'],self.day(other_data,'2026-11-17')['visit_count']),(0,0))
        self.assertEqual(other_client.get(f'/api/customers/{self.a.pk}/activities').json()['items'],[])
        day=self.day(self.report(),'2026-11-17');self.assertEqual((day['prospect_count'],day['visit_count']),(1,1))
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.a.pk)],'idempotency_key':str(uuid4())})
        self.assertEqual(self.report()['today']['attempts'],1)
        self.assertEqual(self.day(self.report(),'2026-11-17')['visit_count'],1)
        self.record(self.b,connection='CONNECTED')
        recall(self.admin,self.recall_body(employee_id=str(self.employee.pk)))
        self.assertEqual(self.report()['today']['attempts'],2)

    def test_kst_midnight_month_end_leap_year_actual_visit_day_and_future_dates(self):
        self.now=datetime(2028,3,1,0,0,tzinfo=KST)
        self.client=login(self.employee)
        for at in ['2028-02-29T14:59:59.999999Z','2028-02-29T15:00:00Z']:
            self.record(occurred_at=at,connection='CONNECTED')
        self.record(kind='VISIT',visited_on='2028-02-29');self.revision(at=datetime(2028,2,29,23,59,59,tzinfo=KST))
        feb=self.report('2028-02');march=self.report()
        self.assertEqual(len(feb['rows']),29);self.assertEqual(feb['rows'][-1]['date'],'2028-02-29')
        self.assertEqual((feb['rows'][-1]['call_count'],feb['rows'][-1]['prospect_count'],feb['rows'][-1]['visit_count']),(1,1,1))
        self.assertEqual((march['today']['attempts'],march['today']['connected'],march['rows'][0]['call_count']),(1,1,1))
        self.assertTrue(all(row['is_future'] and row['call_count'] is None for row in march['rows'][1:]))
        self.assertEqual(len(self.report('2027-02')['rows']),28)

    def test_coverage_missing_snapshots_known_zero_and_before_tracking_are_distinct(self):
        data=self.report('2026-10')
        self.assertIsNone(self.day(data,'2026-10-09')['call_count'])
        self.assertEqual(self.day(data,'2026-10-09')['call_status'],'unavailable')
        self.assertEqual(self.day(data,'2026-10-10')['call_status'],'partial')
        self.assertEqual(self.day(data,'2026-10-11')['call_count'],0)
        self.assertEqual(self.day(data,'2026-10-11')['prospect_count'],0)
        self.revision(at=datetime(2026,8,15,tzinfo=KST))
        august=self.report('2026-08')
        self.assertIsNone(august['rows'][0]['prospect_count'])
        self.assertIsNone(self.day(august,'2026-08-15')['prospect_count'])
        self.assertIsNone(self.day(august,'2026-08-16')['prospect_count'])
        self.revision(snapshot=False)
        self.assertIsNone(self.day(self.report(),'2026-11-17')['prospect_count'])
        PerformanceTracking.objects.all().delete()
        self.assertIsNone(self.report()['today']['attempts'])

    def test_employee_site_scope_strict_month_validation_and_no_pii(self):
        self.record(connection='CONNECTED');self.record(self.outside,connection='CONNECTED')
        self.record(self.foreign,actor=self.other,connection='CONNECTED')
        data=self.report();self.assertEqual(data['today']['attempts'],1)
        self.assertEqual(self.report(site=self.second)['today']['attempts'],1)
        self.assertNotIn(self.a.customer_name,str(data));self.assertNotIn(self.a.phone_normalized,str(data))
        for params in [{'month':x} for x in ['2026-00','2026-13','2026-1','0000-01','2026-12','invalid']]+[{'employee_id':str(self.other.pk)},{'month':['2026-10','2026-11']},{'site_id':str(uuid4())}]:
            self.assertIn(self.client.get('/api/dashboard/performance',params).status_code,[409,422])
        self.assertEqual(login(self.admin).get('/api/dashboard/performance').status_code,403)
        self.assertEqual(self.client.get('/api/dashboard/performance',HTTP_X_TM_ACTOR=str(self.other.pk)).status_code,403)

    def test_write_validation_authorization_csrf_and_unique_database_constraint(self):
        endpoint=f'/api/customers/{self.a.pk}/activities'
        csrf=Client(enforce_csrf_checks=True);csrf.cookies.update(self.client.cookies)
        self.assertEqual(csrf.post(endpoint,self.body_for(),content_type='application/json').status_code,403)
        for extra in [{'connection':'NO_ANSWER'},{'occurred_at':(self.now+timedelta(seconds=1)).isoformat()},
                      {'occurred_at':'2026-10-09T23:59:59+09:00'},{'actor_id':str(self.other.pk)}, {'assignment_id':str(uuid4())}]:
            self.assertIn(self.client.post(endpoint,self.body_for(**extra),content_type='application/json').status_code,[403,422])
        for value in ['2026-11-18','2026-10-09','2026-02-30','not-a-date']:
            self.assertEqual(self.client.post(endpoint,self.body_for(kind='VISIT',visited_on=value),content_type='application/json').status_code,422)
        self.assertEqual(login(self.admin).post(endpoint,self.body_for(),content_type='application/json').status_code,403)
        self.assertEqual(self.client.post(f'/api/customers/{self.foreign.pk}/activities',self.body_for(self.foreign),content_type='application/json').status_code,403)
        body=self.body_for();result=record_activity(self.employee,self.a.pk,body)
        changed={**body,'connection':'CONNECTED'}
        self.assertEqual(self.client.post(endpoint,changed,content_type='application/json').status_code,409)
        row=CustomerActivity.objects.get()
        with self.assertRaises(IntegrityError),transaction.atomic():
            CustomerActivity.objects.create(customer=self.a,site=self.site,actor=self.employee,kind='VISIT',visited_on=self.now.date(),idempotency_key=row.idempotency_key,body_hash='test')

    def test_same_request_concurrency_records_only_once(self):
        body=self.body_for(connection='CONNECTED');barrier=Barrier(2)
        def save():
            close_old_connections()
            try:
                barrier.wait();return record_activity(User.objects.get(pk=self.employee.pk),self.a.pk,body)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:save(),range(2)))
        self.assertEqual(sorted(row[1] for row in results),[200,201]);self.assertEqual(CustomerActivity.objects.count(),1)

    def test_upgrade_preserves_existing_customer_and_revision_without_inventing_events(self):
        self.revision()
        target=('consultations','0003_performancetracking_customeractivity')
        executor=MigrationExecutor(connection)
        try:
            executor.migrate([('consultations','0002_consultationrevision_source_ai_result')])
            self.assertEqual(ConsultationRevision.objects.filter(customer=self.a).count(),1)
            MigrationExecutor(connection).migrate([target])
            self.assertEqual(Customer.objects.get(pk=self.a.pk).phone_normalized,self.a.phone_normalized)
            self.assertEqual(ConsultationRevision.objects.filter(customer=self.a).count(),1)
            self.assertFalse(CustomerActivity.objects.exists())
            self.assertEqual(PerformanceTracking.objects.get(pk=1).started_at,self.now)
        finally:
            MigrationExecutor(connection).migrate([target])
