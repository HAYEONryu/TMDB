"""Full-set ordering/continuations and shared employee/admin performance contracts."""
from datetime import datetime,timedelta
from unittest.mock import patch
from uuid import uuid4
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments import services
from apps.assignments.tm_recall import preview,recall_unfinished
from apps.consultations.models import PerformanceTracking
from apps.consultations.activities import record_activity
from apps.customers.models import Customer
from apps.customers.queries import KST,customer_list
from apps.customers.services import update_row
from apps.operations.employee_performance import performance
from tests.test_p4 import Fixtures
from tests.helpers import login,TEST_HASHERS


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class HTMLFollowupTests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,11,18,15,tzinfo=KST)
        timer=patch('django.utils.timezone.now',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.prepare()
        PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':self.now.replace(day=1,hour=0)})

    def query(self,actor=None,**extra):
        return customer_list(actor or self.employee,{'site_id':str(self.site.pk),'view':'mine','pagination':'infinite','sort':'customer_name',**extra})

    def test_infinite_all_pages_ties_both_orders_and_full_set_search_filter(self):
        customers=self.customers(125)
        for c in customers:self.assign(c)
        Customer.objects.filter(pk__in=[c.pk for c in customers[:60]]).update(customer_name='같은 이름')
        for sort in ['customer_name','-customer_name','call_result','-call_result','last_tm_date','-last_tm_date','deletion_request_status','-deletion_request_status','housing_status','-notes']:
            first=self.query(sort=sort);found=[r['id'] for r in first['data']];next_=first['next_cursor']
            while next_:
                page=self.query(sort=sort,cursor=next_);found += [r['id'] for r in page['data']];next_=page['next_cursor']
            self.assertEqual(len(found),125);self.assertEqual(len(set(found)),125)
        result=self.query(q='0124');self.assertEqual(result['total'],1)
        Customer.objects.filter(pk=customers[-1].pk).update(call_result='VISIT_BOOKED')
        result=self.query(filters='{"call_result":["VISIT_BOOKED"]}');self.assertEqual(result['total'],1)
        self.assertEqual(result['data'][0]['id'],str(customers[-1].pk))

    def test_changed_membership_order_actor_condition_and_kst_midnight_reject_stale_cursor(self):
        customers=self.customers(55)
        for c in customers:self.assign(c)
        cursor=self.query()['next_cursor']
        for actor,extra in [(self.other,{}),(self.employee,{'q':'가상'}),(self.employee,{'sort':'-customer_name'})]:
            with self.assertRaises(AccessError) as failure:self.query(actor,cursor=cursor,**extra)
            self.assertEqual(failure.exception.code,'LIST_CHANGED')
        Customer.objects.filter(pk=customers[-1].pk).update(customer_name='000 우선')
        with self.assertRaises(AccessError):self.query(cursor=cursor)
        cursor=self.query()['next_cursor'];self.now+=timedelta(days=1)
        with self.assertRaises(AccessError):self.query(cursor=cursor)

    def test_last_tm_sort_missing_date_belongs_only_to_current_assignment(self):
        a,b=self.customers(2);self.assign(a);self.assign(b)
        record_activity(self.employee,a.pk,{'site_id':str(self.site.pk),'assignment_id':str(a.current_assignment_id),'kind':'CALL','connection':'NOT_CONNECTED','occurred_at':self.now.isoformat(),'idempotency_key':str(uuid4())})
        for view in ['today','mine']:
            rows=self.query(view=view,sort='-last_tm_date')['data'];self.assertEqual(rows[0]['last_tm_date'],'2026-11-18');self.assertIsNone(rows[1]['last_tm_date'])
        services.change_assignee(self.admin,a.pk,self.assignee_body(a,self.other))
        rows=self.query(self.other)['data'];self.assertIsNone(rows[0]['last_tm_date'])

    def test_selected_staff_array_reuses_atomic_distribution_and_recall_proof(self):
        self.customers(6)
        selected=[str(self.employee.pk),str(self.other.pk)]
        body=self.body(employee_id=selected,quantity=2)
        result,status=services.distribute(self.admin,body);self.assertEqual((status,result['allocated_count']),(200,4))
        self.assertEqual(services.distribute(self.admin,body),(result,status))
        selection={'site_id':str(self.site.pk),'employee_id':[str(self.employee.pk)]}
        proof=preview(self.admin,selection);self.assertEqual(proof['target_count'],2)
        c=Customer.objects.filter(current_assignment__employee=self.employee).first()
        update_row(self.employee,{**self.mutation(c),'changes':{'call_result':'NO_ANSWER'}})
        with self.assertRaises(AccessError) as changed:recall_unfinished(self.admin,{**selection,'confirmation':proof['confirmation'],'idempotency_key':str(uuid4())})
        self.assertEqual(changed.exception.code,'TM_TARGETS_CHANGED')
        fresh=preview(self.admin,selection);self.assertEqual(fresh['target_count'],1)
        result,_=recall_unfinished(self.admin,{**selection,'confirmation':fresh['confirmation'],'idempotency_key':str(uuid4())})
        self.assertEqual(result['recalled_count'],1)
        self.assertEqual(Customer.objects.filter(current_assignment__employee=self.other).count(),2)
        recall_preview=services.recall_preview(selection);self.assertEqual(recall_preview['employees'][0]['count'],1)
        result,_=services.recall(self.admin,self.recall_body(employee_id=selection['employee_id']));self.assertEqual(result['recalled_count'],1)

    def test_invalid_staff_array_does_not_partially_distribute(self):
        self.customers(5)
        for ids in [[],[str(self.employee.pk)]*2,[str(self.employee.pk),str(self.admin.pk)]]:
            try:
                result,status=services.distribute(self.admin,self.body(employee_id=ids))
                self.assertEqual(status,409)
            except AccessError as error:self.assertEqual(error.code,'VALIDATION_ERROR')
        self.assertFalse(Customer.objects.exclude(current_assignment=None).exists())

    def test_distribution_applies_only_to_customers_still_eligible_when_locked(self):
        existing, first, changed = self.customers(3)
        current = self.assign(existing)
        pool = services.eligible(self.site.pk)
        locked_pool = pool.exclude(pk=changed.pk).select_for_update()
        with patch.object(services, 'eligible', return_value=pool), patch.object(pool, 'select_for_update', return_value=locked_pool):
            result, status = services.distribute(self.admin, self.body(employee_id=[str(self.employee.pk)], quantity=2))
        self.assertEqual(status, 409)
        self.assertEqual(result['error']['code'], 'DISTRIBUTION_TARGETS_CHANGED')
        existing.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(existing.current_assignment_id, current.pk)
        self.assertIsNone(first.current_assignment_id)

    def test_explicit_staff_selection_keeps_every_selected_id(self):
        ids = [uuid4() for _ in range(201)]
        self.assertEqual(services.selected_employee([str(pk) for pk in ids]), tuple(sorted(ids)))

    def test_admin_monthly_matches_employee_after_later_recall_keeps_call_and_visit(self):
        started_at = self.now.replace(day=1, hour=0)
        audit = patch('apps.operations.employee_performance.audit_started_at', return_value=started_at)
        audit.start()
        self.addCleanup(audit.stop)
        a,b,c=self.customers(3);self.assign(a);self.assign(b);self.assign(c)
        update_row(self.admin, {**self.mutation(c), 'changes': {'call_result': 'INTERESTED'}})
        for row in [a,b]:update_row(self.employee,{**self.mutation(row),'changes':{'call_result':'INTERESTED'}})
        for kind,values in [('CALL',{'occurred_at':self.now.isoformat(),'connection':'CONNECTED'}),('CALL',{'occurred_at':self.now.isoformat(),'connection':'NOT_CONNECTED'}),('VISIT',{'visited_on':'2026-11-18'})]:
            record_activity(self.employee,a.pk,{'site_id':str(self.site.pk),'assignment_id':str(a.current_assignment_id),'kind':kind,'idempotency_key':str(uuid4()),**values})
        self.now+=timedelta(days=1);a.refresh_from_db();services.change_assignee(self.admin,a.pk,self.assignee_body(a,None))
        employee=performance(self.employee,self.site.pk,self.now.date().replace(day=1),self.now)
        response=login(self.admin).get('/api/dashboard/staff-performance',{'site_id':str(self.site.pk),'month':'2026-11'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn(str(self.admin.pk), [r['id'] for r in response.json()['employees']])
        manager=next(r for r in response.json()['employees'] if r['id']==str(self.employee.pk))
        self.assertEqual(manager['rows'],employee['rows']);self.assertEqual(manager['totals'],employee['totals'])
        day=next(r for r in manager['rows'] if r['date']=='2026-11-18')
        self.assertEqual((day['call_count'],day['connected_count'],day['prospect_count'],day['visit_count']),(2,1,1,1))
        self.assertEqual(login(self.employee).get('/api/dashboard/staff-performance').status_code,403)
        self.assertEqual(login(self.admin).get('/api/dashboard/staff-performance',{'month':'2026-12'}).status_code,422)
        User.objects.filter(pk=self.employee.pk).update(role=User.Role.ADMIN)
        after_role_change = login(self.admin).get('/api/dashboard/staff-performance', {
            'site_id': str(self.site.pk), 'month': '2026-11',
        }).json()['employees']
        former_employee = next(row for row in after_role_change if row['id'] == str(self.employee.pk))
        self.assertEqual(former_employee['rows'], employee['rows'])
