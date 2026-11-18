from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
import json
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase, override_settings
from apps.assignments.services import change_assignee
from apps.consultations.models import ConsultationRevision, CustomerActivity, PerformanceTracking
from apps.customers.choices import customer_schema
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import update_row
from apps.operations.employee_performance import performance
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DailyCallResultTests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,11,18,16,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare();self.client=login(self.employee)
        MigrationRecorder.Migration.objects.filter(app='consultations',name='0001_initial').update(applied=datetime(2026,11,1,9,tzinfo=KST))
        PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':datetime(2026,11,1,tzinfo=KST)})
        self.row=self.customers()[0];self.assign(self.row,at=self.now-timedelta(days=1))

    def note(self,value,*,row=None,at=None,actor=None,fields=None,source='MANUAL',snapshot=True):
        row=row or self.row
        return ConsultationRevision.objects.create(customer=row,assignment=row.current_assignment,actor=actor or self.employee,
            saved_at=at or self.now,customer_version=ConsultationRevision.objects.filter(customer=row).count()+1,
            changed_fields=['call_result'] if fields is None else fields,source=source,after_values={'call_result':value} if snapshot else {})

    def report(self,day='2026-11-18',site=None,client=None):
        response=(client or self.client).get('/api/dashboard/call-results',{'date':day,'site_id':str((site or self.site).pk)})
        self.assertEqual(response.status_code,200);return response.json()

    def counts(self,**kwargs):return {r['code']:r['count'] for r in self.report(**kwargs)['items']}

    def test_latest_explicit_result_once_per_customer_clear_and_unrelated_edits(self):
        self.note('NO_ANSWER',at=self.now-timedelta(hours=4));self.note('INTERESTED')
        self.note('NO_ANSWER',actor=self.other)  # Other staff cannot override my result.
        self.note('REJECTED',fields=['notes'])
        self.note('REJECTED',source='SYSTEM_DELETE_NOTE')
        for code in ['DELETE_REQUEST','REJECTED','NEXT_SITE','NO_ANSWER']:
            row=self.customers(offset=10+ConsultationRevision.objects.count())[0];self.assign(row);self.note(code,row=row)
        cleared=self.customers(offset=50)[0];self.assign(cleared);self.note('INTERESTED',row=cleared);self.note(None,row=cleared)
        for i,code in enumerate(['VISIT_BOOKED','VISITED','REVISITED','CALL_AGAIN']):
            row=self.customers(offset=60+i)[0];self.assign(row);self.note(code,row=row)
        outside=self.customers(site=self.second,offset=80)[0];self.assign(outside);self.note('INTERESTED',row=outside)
        self.assertEqual(self.counts(),{'NO_ANSWER':1,'DELETE_REQUEST':1,'REJECTED':1,'NEXT_SITE':1,'INTERESTED':1})
        self.assertEqual(self.counts(site=self.second)['INTERESTED'],1)
        self.assertEqual(self.counts(client=login(self.other))['NO_ANSWER'],1)
        payload=self.report();self.assertNotIn(self.row.phone_normalized,str(payload));self.assertNotIn(self.row.customer_name,str(payload))

    def test_kst_boundaries_latest_version_tie_future_exclusion_and_next_day_reassignment(self):
        self.note('REJECTED',at=datetime.fromisoformat('2026-11-17T14:59:59+00:00'))
        self.note('NO_ANSWER',at=datetime.fromisoformat('2026-11-17T15:00:00+00:00'))
        self.note('INTERESTED',at=datetime.fromisoformat('2026-11-17T15:00:00+00:00'))
        self.note('DELETE_REQUEST',at=self.now+timedelta(days=2))
        self.assertEqual(self.counts(day='2026-11-17')['REJECTED'],1)
        self.assertEqual(self.counts()['INTERESTED'],1)
        self.now+=timedelta(days=1)
        self.client=login(self.employee)
        self.row.refresh_from_db()
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.other));self.row.refresh_from_db()
        self.note('REJECTED',actor=self.other)
        Customer.objects.filter(pk=self.row.pk).update(call_result='REJECTED')
        self.assertEqual(self.counts()['INTERESTED'],1)
        self.assertEqual(self.counts(day='2026-11-19')['INTERESTED'],0)

    def test_coverage_known_zero_before_tracking_and_missing_snapshot(self):
        self.assertTrue(all(v==0 for v in self.counts().values()))
        self.assertEqual(self.report(day='2026-11-01')['status'],'partial')
        self.assertEqual(self.report(day='2026-10-31')['status'],'unavailable')
        self.assertTrue(all(v is None for v in self.counts(day='2026-10-31').values()))
        self.note('INTERESTED');self.note(None,snapshot=False)
        self.assertEqual(self.report()['status'],'unavailable')
        self.assertTrue(all(v is None for v in self.counts().values()))

    def test_last_tm_date_uses_current_assignment_result_changes_and_explicit_calls(self):
        def listing(client=None, **extra):
            response = (client or self.client).get('/api/customers', {
                'site_id': str(self.site.pk), 'view': 'today', **extra,
            })
            self.assertEqual(response.status_code, 200)
            return response.json()['data'][0]

        self.assertIsNone(listing()['last_tm_date'])
        admin = login(self.admin)
        admin_call = update_row(self.admin, {**self.mutation(self.row), 'changes': {'call_result': 'INTERESTED'}})
        self.assertIsNone(admin_call['row']['last_tm_date'])
        self.row.refresh_from_db()
        result = update_row(self.employee, {**self.mutation(self.row), 'changes': {'call_result': 'NO_ANSWER'}})
        self.assertEqual((result['row']['tm_status'], result['row']['last_tm_date']), ('COMPLETED', '2026-11-18'))
        self.assertEqual(listing()['last_tm_date'], '2026-11-18')
        self.assertEqual(listing(admin, view='all', sort='-last_tm_date')['last_tm_date'], '2026-11-18')
        self.assertFalse(CustomerActivity.objects.filter(customer=self.row).exists())

        self.now += timedelta(days=1)
        self.client = login(self.employee)
        self.row.refresh_from_db()
        saved = update_row(self.employee, {**self.mutation(self.row), 'changes': {'customer_name': '이름 정정', 'memo': '메모만 변경'}})
        self.assertEqual(saved['row']['last_tm_date'], '2026-11-18')
        self.row.refresh_from_db()
        clear = update_row(self.employee, {**self.mutation(self.row), 'changes': {'call_result': None}})
        self.assertEqual((clear['row']['tm_status'], clear['row']['last_tm_date']), ('PENDING', '2026-11-18'))
        CustomerActivity.objects.create(customer=self.row, site=self.site, actor=self.employee, assignment=self.row.current_assignment,
            kind='CALL', connection='NOT_CONNECTED', occurred_at=datetime.fromisoformat('2026-11-18T15:00:00+00:00'),
            idempotency_key=uuid4(), body_hash='synthetic')
        self.assertEqual(listing()['last_tm_date'], '2026-11-19')
        self.row.refresh_from_db()
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.other));self.row.refresh_from_db()
        change_assignee(self.admin,self.row.pk,self.assignee_body(self.row,self.employee));self.row.refresh_from_db()
        self.assertIsNone(listing()['last_tm_date']);self.assertEqual(listing()['tm_status'],'PENDING')

    def test_planned_visit_maps_existing_code_saves_filters_and_is_not_actual_visit(self):
        self.assertEqual(customer_schema()['call_result']['VISIT_BOOKED'],'방문예정')
        result=update_row(self.employee,{**self.mutation(self.row),'changes':{'call_result':'VISIT_BOOKED','visit_at':self.now.isoformat()}})
        self.assertTrue(result['ok']);self.row.refresh_from_db();self.assertEqual(self.row.call_result,'VISIT_BOOKED')
        response=self.client.get('/api/customers',{'view':'today','site_id':str(self.site.pk),'filters':json.dumps({'call_result':['VISIT_BOOKED']})})
        self.assertEqual(response.json()['total'],1)
        data=performance(self.employee,self.site.pk,self.now.date().replace(day=1),self.now)
        self.assertEqual(next(r for r in data['rows'] if r['date']=='2026-11-18')['visit_count'],0)
        self.assertTrue(all(v==0 for v in self.counts().values()))

    def test_auth_validation_and_no_foreign_employee_selection(self):
        self.assertEqual(login(self.admin).get('/api/dashboard/call-results').status_code,403)
        self.assertEqual(self.client.get('/api/dashboard/call-results',HTTP_X_TM_ACTOR=str(self.other.pk)).status_code,403)
        for params in [{'date':s} for s in ['2026-11-19','2026-02-30','bad','0000-01-01']]+[{'employee_id':str(self.other.pk)},{'date':['2026-11-17','2026-11-18']}]:
            self.assertEqual(self.client.get('/api/dashboard/call-results',params).status_code,422)
