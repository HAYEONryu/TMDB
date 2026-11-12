from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.operations.dashboard_reports import manager_report
from apps.sites.models import GlobalSettings
from tests.helpers import TEST_HASHERS, login, user
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DashboardReportTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,11,9,10,tzinfo=KST)
        clock=patch('django.utils.timezone.now',side_effect=lambda:self.now);clock.start();self.addCleanup(clock.stop)
        self.prepare();self.client=login(self.admin);self.versions={}

    def revision(self,customer,actor=None,at=None,result='INTERESTED',source='MANUAL',assignment=None,contract='UNKNOWN'):
        version=self.versions.get(customer.pk,0)+1;self.versions[customer.pk]=version
        return ConsultationRevision.objects.create(customer=customer,actor=actor or self.employee,
            assignment=assignment or customer.current_assignment, saved_at=at or self.now,
            customer_version=version,source=source,changed_fields=['notes','call_result'],
            after_values={'call_result':result,'contract_status':contract},notes='가짜 내부 상담 기록')

    def report(self,period='all',site=None):
        response=self.client.get('/api/dashboard',{'site_id':str((site or self.site).pk),'result_period':period})
        self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def test_today_assignment_is_unique_across_reassignments_and_sites(self):
        customer=self.customers()[0];old=self.assign(customer)
        Assignment.objects.filter(pk=old.pk).update(ended_at=self.now,end_reason='REASSIGNED')
        self.assign(customer,self.other)
        other=self.customers(offset=1)[0];self.assign(other)
        outside=self.customers(site=self.second,offset=2)[0];self.assign(outside)
        future=self.customers(offset=3)[0];self.assign(future,at=self.now+timedelta(hours=1))
        data=self.report()['manager']
        self.assertEqual((data['assigned_today_unique'],data['assignment_operations_today']),(2,3))
        staff={r['id']:r for r in data['staff']}
        self.assertEqual(staff[str(self.employee.pk)]['assigned_today_unique'],2)
        self.assertEqual(staff[str(self.other.pk)]['assigned_today_unique'],1)

    def test_name_only_correction_does_not_inflate_consultation_records_or_period_results(self):
        from apps.customers.services import update_row
        customer=self.customers()[0];self.assign(customer)
        self.assertTrue(update_row(self.employee,self.mutation(customer,notes='가상 변경')|{'changes':{'customer_name':'가상 정정'}})['ok'])
        data=self.report('today')['manager']
        employee=next(row for row in data['staff'] if row['id']==str(self.employee.pk))
        self.assertEqual(employee['consultation_records_7d'],0)
        self.assertEqual(data['distribution']['total'],0)
        customer.refresh_from_db()
        self.assertTrue(update_row(self.employee,self.mutation(customer)|{'changes':{'customer_name':'가상 재정정','notes':'상담 기록'}})['ok'])
        data=self.report('today')['manager']
        employee=next(row for row in data['staff'] if row['id']==str(self.employee.pk))
        self.assertEqual(employee['consultation_records_7d'],1)
        self.assertEqual(data['distribution']['total'],1)

    def test_seven_day_records_use_author_include_applied_save_exclude_system_import_and_future(self):
        customer=self.customers()[0];self.assign(customer,self.other)
        self.revision(customer,self.employee)
        self.revision(customer,self.employee,source='AI_APPLIED')
        self.revision(customer,self.other,at=self.now.replace(hour=0)-timedelta(days=6))
        for source in ['IMPORT','BASELINE','SYSTEM_DELETE_NOTE']:self.revision(customer,self.employee,source=source)
        self.revision(customer,self.admin)
        self.revision(customer,self.employee,at=self.now.replace(hour=0)-timedelta(days=6,microseconds=1))
        self.revision(customer,self.employee,at=self.now+timedelta(seconds=1))
        outside=self.customers(site=self.second,offset=8)[0];self.revision(outside,self.employee)
        staff={r['id']:r for r in self.report()['manager']['staff']}
        self.assertEqual(staff[str(self.employee.pk)]['consultation_records_7d'],1)
        self.assertEqual(staff[str(self.other.pk)]['consultation_records_7d'],1)

    def test_repeated_notes_and_callback_saves_across_days_count_one_customer(self):
        customer=self.customers()[0];self.assign(customer)
        # Reproduce two note edits and one callback edit on the same customer.
        for days,fields in [(2,['notes']),(1,['callback_due_at']),(0,['notes'])]:
            revision=self.revision(customer,at=self.now-timedelta(days=days))
            revision.changed_fields=fields;revision.save(update_fields=['changed_fields'])
        Customer.objects.filter(pk=customer.pk).update(call_result=None)
        staff=next(row for row in self.report()['manager']['staff'] if row['id']==str(self.employee.pk))
        self.assertEqual(staff['consultation_records_7d'],1)
        self.assertEqual(ConsultationRevision.objects.filter(actor=self.employee).count(),3)
        self.assertEqual(next(row['count'] for row in staff['call_results'] if row['value'] is None),1)
        other_customer=self.customers(offset=10)[0]
        self.revision(other_customer)
        staff=next(row for row in self.report()['manager']['staff'] if row['id']==str(self.employee.pk))
        self.assertEqual(staff['consultation_records_7d'],2)

    def test_period_results_deduplicate_customer_and_use_last_saved_result_in_period(self):
        self.now=datetime(2026,11,11,10,tzinfo=KST)
        self.client=login(self.admin)
        a,b,c,d=self.customers(4)
        self.revision(a,at=datetime(2026,11,9,8,tzinfo=KST),result='INTERESTED')
        self.revision(a,result='CALL_AGAIN')
        self.revision(a,at=self.now+timedelta(minutes=1),result='VISITED')
        self.revision(a,source='SYSTEM_DELETE_NOTE',result='VISIT_BOOKED')
        self.revision(b,at=datetime(2026,11,10,8,tzinfo=KST),result='REJECTED')
        self.revision(c,at=datetime(2026,11,8,23,59,tzinfo=KST),result='VISITED')
        Customer.objects.filter(pk=a.pk).update(call_result='CALL_AGAIN')
        Customer.objects.filter(pk=b.pk).update(call_result='REJECTED')
        Customer.objects.filter(pk=c.pk).update(call_result='VISITED')
        all_data=self.report('all')['manager']['distribution']
        week=self.report('week')['manager']['distribution'];today=self.report('today')['manager']['distribution']
        self.assertEqual((all_data['total'],week['total'],today['total']),(4,2,1))
        self.assertEqual({r['value']:r['count'] for r in week['results'] if r['count']},{'CALL_AGAIN':1,'REJECTED':1})
        self.assertEqual({r['value']:r['count'] for r in today['results'] if r['count']},{'CALL_AGAIN':1})
        self.assertEqual(week['start'],'2026-11-09T00:00:00+09:00')
        self.assertEqual(week['end_exclusive'],'2026-11-16T00:00:00+09:00')
        self.assertNotIn('가짜 내부 상담 기록',str(week))

    def test_sunday_week_boundary_and_kst_day_exclude_next_monday(self):
        self.now=datetime(2027,1,3,23,59,59,tzinfo=KST)
        self.client=login(self.admin)
        a,b,c=self.customers(3)
        self.revision(a,at=datetime(2026,12,28,0,0,tzinfo=KST))
        self.revision(b,at=datetime(2027,1,3,0,0,tzinfo=KST),result='CALL_AGAIN')
        self.revision(c,at=datetime(2027,1,4,0,0,tzinfo=KST),result='VISITED')
        week=self.report('week')['manager']['distribution'];today=self.report('today')['manager']['distribution']
        self.assertEqual((week['total'],today['total']),(2,1))
        self.assertEqual(week['start'],'2026-12-28T00:00:00+09:00')
        self.assertEqual(week['end_exclusive'],'2027-01-04T00:00:00+09:00')

    def test_contract_counts_share_result_cohort_and_period_latest_snapshot(self):
        self.now=datetime(2026,11,11,10,tzinfo=KST);self.client=login(self.admin)
        a,b,c,d,trash=self.customers(5)
        Customer.objects.filter(pk__in=[a.pk,d.pk,trash.pk]).update(contract_status='CONTRACTED')
        Customer.objects.filter(pk=trash.pk).update(deleted_at=self.now,deleted_by=self.admin)
        outside=self.customers(site=self.second,offset=20)[0]
        Customer.objects.filter(pk=outside.pk).update(contract_status='CONTRACTED')
        self.revision(a,contract='CONTRACTED',at=self.now-timedelta(minutes=3))
        self.revision(a,contract='NO_CONTRACT',at=self.now-timedelta(minutes=2))
        self.revision(b,contract='CONTRACTED',at=self.now-timedelta(minutes=2))
        self.revision(b,contract='CONTRACTED',source='AI_APPLIED')
        self.revision(b,contract='NO_CONTRACT',at=self.now+timedelta(minutes=1))
        self.revision(c,contract='CONTRACTED',at=datetime(2026,11,10,8,tzinfo=KST))
        self.revision(d,contract='CONTRACTED',source='IMPORT')
        self.revision(d,contract='CONTRACTED',source='SYSTEM_DELETE_NOTE')
        self.revision(trash,contract='CONTRACTED')
        self.revision(outside,contract='CONTRACTED')
        for period,total,contracts in [('all',4,2),('week',3,2),('today',2,1)]:
            with self.subTest(period=period):
                result=self.report(period)['manager']['distribution']
                self.assertEqual((result['total'],result['contracted_total']),(total,contracts))
                self.assertEqual(sum(row['count'] for row in result['results']),total)
        self.assertEqual(self.report('today',self.second)['manager']['distribution']['contracted_total'],1)

    def test_missing_historical_contract_field_is_not_inferred_from_current_state(self):
        customer=self.customers()[0]
        Customer.objects.filter(pk=customer.pk).update(contract_status='CONTRACTED')
        ConsultationRevision.objects.create(customer=customer,actor=self.employee,saved_at=self.now,
            customer_version=1,source='MANUAL',changed_fields=['call_result'],after_values={'call_result':'INTERESTED'})
        self.assertEqual(self.report()['manager']['distribution']['contracted_total'],1)
        for period in ['today','week']:
            result=self.report(period)['manager']['distribution']
            self.assertEqual((result['total'],result['contracted_total']),(1,0))

    def test_progress_uses_current_assignment_not_old_owner_and_excludes_trash(self):
        a,b,c=self.customers(3)
        self.assign(a,progress=True);self.assign(b);old=self.assign(c,progress=True)
        Assignment.objects.filter(pk=old.pk).update(ended_at=self.now,end_reason='REASSIGNED')
        self.assign(c,self.other)
        Customer.objects.filter(pk=a.pk).update(call_result='INTERESTED',contract_status='CONTRACTED')
        staff={r['id']:r for r in self.report()['manager']['staff']}
        e=staff[str(self.employee.pk)];other=staff[str(self.other.pk)]
        self.assertEqual((e['held_total'],e['progressed_total'],e['unprogressed_total'],e['contracted_total']),(2,1,1,1))
        self.assertEqual((other['held_total'],other['progressed_total'],other['unprogressed_total']),(1,0,1))
        self.assertEqual(sum(r['count'] for r in e['call_results']),2)

    def test_inactive_or_promoted_former_employee_work_is_not_lost(self):
        a,b=self.customers(2);self.assign(a);self.assign(b,self.other)
        self.revision(a,self.employee);self.revision(b,self.other)
        User.objects.filter(pk=self.employee.pk).update(is_active=False)
        User.objects.filter(pk=self.other.pk).update(role='ADMIN')
        rows={r['id']:r for r in self.report()['manager']['staff']}
        self.assertFalse(rows[str(self.employee.pk)]['is_active'])
        self.assertFalse(rows[str(self.other.pk)]['is_employee'])
        self.assertEqual(rows[str(self.other.pk)]['consultation_records_7d'],1)

    def test_employee_has_no_team_data_and_cannot_request_period_or_spoof_actor(self):
        client=login(self.employee)
        data=client.get('/api/dashboard',{'site_id':self.site.pk}).json()
        self.assertNotIn('manager',data);self.assertNotIn('employees',data)
        self.assertEqual(client.get('/api/dashboard',{'result_period':'all'}).status_code,403)
        self.assertEqual(client.get('/api/dashboard',HTTP_X_TM_ACTOR=str(self.admin.pk)).status_code,403)
        self.assertEqual(client.get('/api/dashboard',{'employee_id':self.other.pk}).status_code,422)

    def test_invalid_period_duplicate_parameters_site_change_and_empty_results(self):
        before=GlobalSettings.objects.get(pk=1).version
        for query in ['result_period=bad','result_period=all&result_period=today','site_id=bad','site_id='+str(uuid4()),'unknown=true']:
            self.assertIn(self.client.get('/api/dashboard?'+query).status_code,[409,422])
        data=self.report('week',self.second)['manager']
        self.assertEqual(data['distribution']['total'],0)
        self.assertEqual(data['distribution']['contracted_total'],0)
        self.assertEqual(data['assigned_today_unique'],0)
        self.assertEqual(GlobalSettings.objects.get(pk=1).version,before)

    def test_manager_aggregates_have_constant_query_count_and_no_raw_customer_fields(self):
        rows=self.customers(25)
        for i,row in enumerate(rows):self.assign(row,self.employee if i%2 else self.other);self.revision(row)
        for i in range(10):user(f'0109100{i:04d}',initial=False)
        with CaptureQueriesContext(connection) as capture:data=manager_report(self.site.pk,self.now,'week')
        self.assertLessEqual(len(capture),8)
        self.assertEqual(len(data['staff']),12)
        self.assertEqual(data['distribution']['total'],25)
        encoded=str(data)
        for row in rows:self.assertNotIn(row.customer_name,encoded);self.assertNotIn(row.phone_normalized,encoded)

    def test_trashed_customer_is_excluded_from_current_results_but_saved_work_remains(self):
        customer=self.customers()[0];self.revision(customer)
        Customer.objects.filter(pk=customer.pk).update(deleted_at=self.now,deleted_by=self.admin)
        for period in ['all','week','today']:
            data=self.report(period)['manager']
            self.assertEqual(data['distribution']['total'],0)
            self.assertEqual(data['distribution']['contracted_total'],0)
            staff=next(r for r in data['staff'] if r['id']==str(self.employee.pk))
            self.assertEqual(staff['consultation_records_7d'],1)
