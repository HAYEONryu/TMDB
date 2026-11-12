from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase, override_settings
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import trash_operation
from apps.sites.models import GlobalSettings
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class EmployeeDashboardTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 14, tzinfo=KST)
        timer = patch('django.utils.timezone.now', side_effect=lambda: self.now)
        timer.start(); self.addCleanup(timer.stop)
        self.prepare(); self.client = login(self.employee); self.versions = {}

    def report(self, site=None):
        response = self.client.get('/api/dashboard', {'site_id': str((site or self.site).pk)})
        self.assertEqual(response.status_code, 200)
        return response.json()['employee']

    def listing(self, category='held', site=None, page=1):
        response = self.client.get('/api/dashboard/customers', {'site_id': str((site or self.site).pk), 'category': category, 'page': page})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def callback(self, customer, *, days=0, status='PENDING', actor=None, completed_at=None):
        return Callback.objects.create(customer=customer, due_at=self.now.replace(hour=0)+timedelta(days=days),
            created_by=self.employee, updated_by=self.employee, status=status,
            completed_by=(actor or self.employee) if status=='COMPLETED' else None,
            completed_at=(completed_at or self.now) if status=='COMPLETED' else None,
            cancelled_at=self.now if status=='CANCELLED' else None)

    def save(self, customer, *, fields=None, source='MANUAL', actor=None, at=None):
        version=self.versions.get(customer.pk, 0)+1;self.versions[customer.pk]=version
        return ConsultationRevision.objects.create(customer=customer, assignment=customer.current_assignment,
            actor=actor or self.employee, saved_at=at or self.now, customer_version=version,
            changed_fields=fields or ['notes'], source=source)

    def test_tm_deduplicates_assigned_and_callbacks_and_retains_completed_callbacks(self):
        a,b,c,d,e,f=self.customers(6)
        for row in [a,b]: self.assign(row)
        for row in [c,d,e,f]: self.assign(row, at=self.now-timedelta(days=2))
        self.callback(a);self.callback(a, status='COMPLETED');self.callback(c, days=-1)
        self.callback(d, status='COMPLETED');self.callback(d, days=1)
        self.callback(e);self.callback(f, days=1)
        self.save(a);self.save(a, source='AI_APPLIED')
        for fields in [['customer_name'], ['customer_name','phone_normalized'], ['admin_notes']]: self.save(b, fields=fields)
        self.save(b, actor=self.admin);self.save(b, source='IMPORT');self.save(b, at=self.now+timedelta(seconds=1))
        self.assertEqual(self.report()['tm'], {'total':5,'completed':2,'percent':40.0})
        self.save(b, source='AI_APPLIED')
        self.assertEqual(self.report()['tm'], {'total':5,'completed':3,'percent':60.0})

    def test_lists_match_day_counts_and_do_not_expose_other_owners_or_private_notes(self):
        today,past,future,other,trashed=self.customers(5)
        for row in [today,past,future,trashed]:self.assign(row, at=self.now-timedelta(days=2))
        self.assign(other,self.other)
        for row in [today,other,trashed]:self.callback(row)
        self.callback(past, days=-1);self.callback(future, days=1)
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(trashed.pk)],'idempotency_key':str(uuid4())})
        Customer.objects.filter(pk=today.pk).update(admin_notes='SYNTHETIC_PRIVATE_ADMIN',notes='가상 공개 상담',visit_at=self.now)
        Customer.objects.filter(pk=other.pk).update(notes='SYNTHETIC_OTHER_OWNER',visit_at=self.now)
        report=self.report()
        self.assertEqual((report['held_total'],report['callbacks_today'],report['callbacks_past_due'],report['visits_today']),(3,1,1,1))
        for category,ids in [('held',[today.pk,past.pk,future.pk]),('callbacks_today',[today.pk]),('overdue',[past.pk]),('visits',[today.pk]),('new_today',[])]:
            result=self.listing(category)
            self.assertCountEqual([r['id'] for r in result['data']],map(str,ids))
            self.assertNotIn('SYNTHETIC_PRIVATE_ADMIN',str(result));self.assertNotIn('admin_notes',str(result));self.assertNotIn('SYNTHETIC_OTHER_OWNER',str(result))
        self.assertEqual(self.listing('visits')['data'][0]['notes'],'가상 공개 상담')

    def test_contracts_count_selected_site_and_own_holdings_excluding_trash(self):
        own,other,free,trash=self.customers(4)
        self.assign(own);self.assign(other,self.other)
        Customer.objects.filter(site=self.site).update(contract_status='CONTRACTED')
        Customer.objects.filter(pk=trash.pk).update(deleted_at=self.now,deleted_by=self.admin)
        outside=self.customers(site=self.second,offset=20)[0]
        Customer.objects.filter(pk=outside.pk).update(contract_status='CONTRACTED')
        report=self.report()
        self.assertEqual((report['site_contracted_total'],report['contracted_held']),(3,1))
        self.assertEqual(self.report(self.second)['site_contracted_total'],1)
        self.assertEqual(self.report(self.second)['tm'],{'total':0,'completed':0,'percent':0})

    def test_completed_yesterday_cancelled_or_future_callbacks_do_not_inflate_today(self):
        old,cancelled,future,admin_done=self.customers(4)
        for row in [old,cancelled,future,admin_done]: self.assign(row, at=self.now-timedelta(days=3))
        self.callback(old, days=-1,status='COMPLETED',completed_at=self.now-timedelta(days=1))
        self.callback(cancelled,status='CANCELLED');self.callback(future,days=1,status='COMPLETED')
        self.callback(admin_done,status='COMPLETED',actor=self.admin)
        self.assertEqual(self.report()['tm'],{'total':0,'completed':0,'percent':0})

    def test_kst_midnight_boundaries_future_assignments_and_pagination(self):
        rows=self.customers(12)
        for row in rows[:11]:self.assign(row)
        self.assign(rows[11],at=self.now+timedelta(hours=1))
        start=self.now.replace(hour=0)
        for row,at in [(rows[0],start),(rows[1],start+timedelta(days=1)),(rows[2],start-timedelta(microseconds=1))]:
            Customer.objects.filter(pk=row.pk).update(visit_at=at)
        self.assertEqual((self.listing()['total'],len(self.listing()['data']),len(self.listing(page=2)['data'])),(11,10,1))
        self.assertEqual(self.listing(page=999)['page'],2)
        self.assertEqual(self.report()['held_total'],11)
        self.assertEqual(self.report()['current_assignment_today_held'],11)
        self.assertEqual([r['id'] for r in self.listing('visits')['data']],[str(rows[0].pk)])

    def test_request_validation_identity_and_selected_site_do_not_change_defaults(self):
        before=GlobalSettings.objects.get(pk=1).version
        for query in ['category=bad','page=0','page=x','site_id=bad','category=held&category=visits','employee_id='+str(self.other.pk)]:
            self.assertEqual(self.client.get('/api/dashboard/customers?'+query).status_code,422)
        self.assertEqual(self.client.get('/api/dashboard/customers',{'site_id':str(uuid4())}).status_code,409)
        self.assertEqual(self.client.get('/api/dashboard/customers',HTTP_X_TM_ACTOR=str(self.other.pk)).status_code,403)
        self.assertEqual(login(self.admin).get('/api/dashboard/customers').status_code,403)
        self.listing(site=self.second)
        self.assertEqual(GlobalSettings.objects.get(pk=1).version,before)
