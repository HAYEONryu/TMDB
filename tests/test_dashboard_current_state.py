"""Synthetic acceptance boundaries for current assignments and dashboard actions."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase, override_settings

from apps.accounts.models import User
from apps.accounts.management_services import transfer_list
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import trash_operation
from apps.operations.employee_dashboard import daily_report
from apps.sites.models import GlobalSettings
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DashboardCurrentStateTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,11,15,15,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare();self.start=self.now.replace(hour=0);self.versions={}

    def report(self,actor=None,site=None,period='all'):
        params={'site_id':str((site or self.site).pk)}
        if (actor or self.admin).role=='ADMIN':params['result_period']=period
        response=login(actor or self.admin).get('/api/dashboard',params)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['as_of'],self.now.isoformat())
        return response.json()

    def listing(self,category,actor=None,site=None,assignee=None):
        params={'site_id':str((site or self.site).pk),'dashboard_category':category}
        if assignee:params['assignee_id']=str(assignee.pk)
        response=login(actor or self.admin).get('/api/customers',params)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['as_of'],self.now.isoformat())
        return {row['id'] for row in response.json()['data']}

    def detail(self,category,actor=None):
        response=login(actor or self.employee).get('/api/dashboard/customers',{'category':category,'site_id':str(self.site.pk)})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['as_of'],self.now.isoformat())
        return response.json()

    def move(self,row,target):
        row.refresh_from_db();result,status=change_assignee(self.admin,row.pk,self.assignee_body(row,target));self.assertEqual(status,200);self.assertTrue(result['ok']);row.refresh_from_db()

    def saved(self,row,fields,actor=None,at=None,source='MANUAL',assignment=None,result='INTERESTED',contract='UNKNOWN'):
        version=self.versions.get(row.pk,0)+1;self.versions[row.pk]=version
        return ConsultationRevision.objects.create(customer=row,assignment=assignment or row.current_assignment,actor=actor or self.employee,
            customer_version=version,saved_at=at or self.now,source=source,changed_fields=fields,
            after_values={'call_result':result,'contract_status':contract})

    def callback(self,row,due,status='PENDING',actor=None):
        return Callback.objects.create(customer=row,due_at=due,status=status,created_by=self.employee,updated_by=self.employee,
            completed_by=(actor or self.employee) if status=='COMPLETED' else None,completed_at=self.now if status=='COMPLETED' else None)

    def assert_current(self,total,a,b):
        data=self.report();staff={row['id']:row for row in data['manager']['staff']}
        self.assertEqual(data['manager']['current_assignment_today_held'],total)
        self.assertEqual(sum(row['current_assignment_today_held'] for row in staff.values()),total)
        self.assertEqual(staff[str(self.employee.pk)]['current_assignment_today_held'],a)
        self.assertEqual(staff[str(self.other.pk)]['current_assignment_today_held'],b)
        self.assertEqual(len(self.listing('new_today')),total)
        for actor,count in [(self.employee,a),(self.other,b)]:
            self.assertEqual(self.report(actor)['employee']['current_assignment_today_held'],count)
            self.assertEqual(self.detail('new_today',actor)['total'],count)
            self.assertEqual(len(self.listing('new_today',actor)),count)

    def test_recall_reassign_same_owner_transfer_and_trash_preserve_history_and_match_all_lists(self):
        row=self.customers()[0];self.assign(row);self.assert_current(1,1,0)
        self.move(row,None);self.assert_current(0,0,0)
        self.assertEqual(self.report()['manager']['assignment_operations_today'],1)
        self.move(row,self.employee);self.assert_current(1,1,0)
        self.move(row,self.other);self.assert_current(1,0,1)
        self.assertEqual(self.report()['manager']['assignment_operations_today'],3)
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(row.pk)],'idempotency_key':str(uuid4())})
        self.assert_current(0,0,0)
        self.assertEqual((Assignment.objects.count(),self.report()['manager']['assignment_operations_today']),(3,3))
        self.assertEqual(self.report()['manager']['assigned_today_unique'],1)

    def test_kst_assignment_boundaries_and_inactive_or_promoted_holders_match_team_sum(self):
        yesterday,today,future,ended,inactive,promoted=self.customers(6)
        self.assign(yesterday,at=self.start-timedelta(microseconds=1));self.assign(today,at=self.start)
        self.assign(future,at=self.now+timedelta(microseconds=1));old=self.assign(ended)
        Assignment.objects.filter(pk=old.pk).update(ended_at=self.now,ended_by=self.admin,end_reason='MANUAL_RECALL')
        self.assign(inactive,self.employee,progress=True);self.assign(promoted,self.other,progress=True)
        User.objects.filter(pk=self.employee.pk).update(is_active=False);User.objects.filter(pk=self.other.pk).update(role='ADMIN')
        outside=self.customers(site=self.second,offset=20)[0];self.assign(outside)
        self.callback(inactive,self.now-timedelta(minutes=1))
        data=self.report();staff={row['id']:row for row in data['manager']['staff']}
        self.assertEqual(data['manager']['current_assignment_today_held'],3)
        self.assertEqual(data['manager']['held_total'],4)
        self.assertEqual(data['counts']['unassigned'],2)
        self.assertEqual(sum(r['held_total'] for r in staff.values()),4)
        self.assertEqual(sum(r['current_assignment_today_held'] for r in staff.values()),3)
        self.assertEqual(sum(r['callbacks_overdue'] for r in staff.values()),1)
        self.assertFalse(staff[str(self.employee.pk)]['is_active']);self.assertFalse(staff[str(self.other.pk)]['is_employee'])
        self.assertEqual(data['manager']['staff'][0]['id'],str(self.employee.pk))
        self.assertEqual(self.listing('new_today'),{str(row.pk) for row in [today,inactive,promoted]})
        self.assertEqual(self.listing('new_today',assignee=self.other),{str(promoted.pk)})
        expected=transfer_list({'site_id':str(self.site.pk)})
        self.assertEqual((data['transfer_needed'],expected['total']),(1,1))
        self.assertEqual({row['id'] for row in expected['items']},{str(inactive.pk)})

    def test_recall_completion_counts_schedule_ids_independent_of_due_date_or_current_holder(self):
        past,at_now,later,tomorrow,done=self.customers(5)
        for row in [past,at_now,later,tomorrow,done]:self.assign(row,at=self.start-timedelta(days=2))
        self.callback(past,self.now-timedelta(minutes=1));self.callback(at_now,self.now)
        self.callback(later,self.now+timedelta(hours=1));self.callback(tomorrow,self.start+timedelta(days=1))
        self.callback(done,self.now+timedelta(days=3),'COMPLETED')
        self.callback(done,self.start-timedelta(days=3),'COMPLETED')
        self.move(done,None)
        Customer.objects.filter(pk__in=[past.pk,later.pk]).update(visit_at=self.start+timedelta(hours=9))
        report=self.report(self.employee)['employee']
        self.assertEqual((report['callbacks_overdue'],report['callbacks_remaining'],report['callbacks_completed_today'],report['visits_today']),(1,2,2,2))
        for category,ids in [('overdue',[past]),('callbacks_remaining',[at_now,later]),('visits',[past,later])]:
            expected={str(row.pk) for row in ids}
            self.assertEqual({row['id'] for row in self.detail(category)['data']},expected)
            self.assertEqual(self.listing(category,self.employee),expected)
        self.assertFalse(self.listing('overdue',self.employee)&self.listing('callbacks_remaining',self.employee))
        # The same pending callback moves from remaining to overdue just after its due time.
        self.now+=timedelta(microseconds=1)
        self.assertEqual((self.report(self.employee)['employee']['callbacks_overdue'],self.detail('callbacks_remaining')['total']),(2,1))
        # At KST midnight, the prior day's final microsecond is overdue and the new day starts inclusively.
        edge=self.start+timedelta(days=1)
        Callback.objects.filter(customer=at_now,status='PENDING').update(due_at=edge-timedelta(microseconds=1))
        Callback.objects.filter(customer=tomorrow,status='PENDING').update(due_at=edge)
        report=daily_report(self.employee,self.site.pk,edge,edge+timedelta(days=1),edge)
        self.assertEqual((report['callbacks_overdue'],report['callbacks_remaining']),(3,1))
        self.assertEqual(report['callbacks_completed_today'],0)

    def test_consultation_progress_and_period_reports_exclude_all_identity_private_only_changes(self):
        a,b,older=self.customers(3);self.assign(a);self.assign(b);self.assign(older,at=self.start-timedelta(days=1))
        for fields in [[],['customer_name'],['phone_normalized'],['admin_notes'],['customer_name','phone_normalized','admin_notes']]:
            self.saved(a,fields,contract='CONTRACTED')
        self.saved(b,['notes'],source='IMPORT');self.saved(b,['notes'],at=self.now+timedelta(hours=1))
        self.saved(older,['notes'])
        report=self.report(self.employee)['employee'];self.assertEqual(report['consultation_progress'],{'completed':0,'total':2})
        data=self.report(period='today')['manager'];self.assertEqual(data['distribution']['total'],1)
        self.saved(a,['notes']);self.saved(a,['callback_due_at'],source='AI_APPLIED')
        self.saved(b,['customer_name','notes'],source='AI_APPLIED',contract='CONTRACTED')
        self.saved(b,['phone_normalized','admin_notes'],at=self.now+timedelta(microseconds=1),contract='UNKNOWN')
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.report(self.employee)['employee']['consultation_progress'],{'completed':2,'total':2})
        manager=self.report(period='today')['manager']
        self.assertEqual((manager['distribution']['total'],manager['distribution']['contracted_total']),(3,1))
        self.assertEqual(next(r for r in manager['staff'] if r['id']==str(self.employee.pk))['consultation_records_7d'],3)
        # A valid save on the previous assignment does not progress a replacement assignment.
        self.move(a,None);self.move(a,self.employee)
        self.assertEqual(self.report(self.employee)['employee']['consultation_progress'],{'completed':1,'total':2})

    def test_dashboard_categories_obey_scope_validation_and_do_not_change_default_site(self):
        own,foreign=self.customers(2);self.assign(own);self.assign(foreign,self.other)
        Customer.objects.filter(pk=foreign.pk).update(admin_notes='SYNTHETIC_FOREIGN_PRIVATE')
        before=GlobalSettings.objects.get(pk=1).version
        response=login(self.employee).get('/api/customers',{'site_id':str(self.site.pk),'dashboard_category':'held'})
        self.assertEqual(response.json()['total'],1);self.assertNotIn('admin_notes',response.content.decode())
        self.assertEqual(login(self.employee).get('/api/customers',{'dashboard_category':'held','assignee_id':str(self.other.pk)}).status_code,403)
        for params in [{'dashboard_category':'bad'},{'dashboard_category':'held','view':'trash'}]:
            self.assertEqual(login(self.admin).get('/api/customers',params).status_code,422)
        self.assertEqual(login(self.employee).get('/api/users/transfer-needed',{'site_id':str(self.site.pk)}).status_code,403)
        self.assertEqual(login(self.admin).get('/api/users/transfer-needed',{'site_id':str(uuid4())}).status_code,409)
        self.report(site=self.second)
        self.assertEqual(GlobalSettings.objects.get(pk=1).version,before)
