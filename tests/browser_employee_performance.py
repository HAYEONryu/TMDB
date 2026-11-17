"""Employee call evidence and month navigation, using only local synthetic records."""
from datetime import datetime, time, timedelta
from uuid import uuid4
from unittest.mock import patch
import json
from django.db import connection, DatabaseError
from django.db.backends.utils import CursorWrapper
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect
from apps.consultations.activities import record_activity
from apps.consultations.models import ConsultationRevision, CustomerActivity, PerformanceTracking
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.assignments.services import change_assignee
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class EmployeePerformanceBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self):
        def create():
            now=timezone.now();today=now.astimezone(KST).date();start=datetime.combine(today,time.min,KST)
            PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':start-timedelta(days=45)})
            a,b,foreign=self.customers(3)
            self.assign(a);self.assign(b);self.assign(foreign,self.other)
            outside=self.customers(site=self.second,offset=50)[0];self.assign(outside)
            Customer.objects.filter(pk=b.pk).update(visit_at=now,call_result='INTERESTED')
            def record(row,actor,**fields):
                return record_activity(actor,row.pk,{'site_id':str(row.site_id),'assignment_id':str(row.current_assignment_id),
                    'idempotency_key':str(uuid4()),**fields})
            record(a,self.employee,kind='CALL',connection='CONNECTED',occurred_at=now.isoformat())
            record(a,self.employee,kind='CALL',connection='NOT_CONNECTED',occurred_at=now.isoformat())
            record(foreign,self.other,kind='CALL',connection='CONNECTED',occurred_at=now.isoformat())
            record(a,self.employee,kind='VISIT',visited_on=(today-timedelta(days=1)).isoformat())
            for version in [1,2]:ConsultationRevision.objects.create(customer=a,assignment=a.current_assignment,actor=self.employee,
                customer_version=version,source='MANUAL',saved_at=now,changed_fields=['notes'],after_values={'call_result':'INTERESTED'})
            return a,b,foreign,outside,today
        self.a,self.b,self.foreign,self.outside,self.today=self.db(create)

    def today_row(self):return self.page.locator(f'#performance-rows tr[data-date="{self.today.isoformat()}"]')

    def test_monthly_prospect_removed_after_recall_without_changing_calls_visits_or_daily_results(self):
        self.seed();self.login(self.employee);page=self.page
        expect(self.today_row().locator('td')).to_have_text(['2','1','0'])
        expect(page.locator('[data-call-result="INTERESTED"]')).to_have_text('0명')  # Seed has notes-only snapshots.
        def recall_customer():
            self.a.refresh_from_db();change_assignee(self.admin,self.a.pk,self.assignee_body(self.a,None))
        self.db(recall_customer);page.locator('#dashboard-refresh').click()
        expect(self.today_row().locator('td')).to_have_text(['2','0','0'])
        expect(page.locator('#today-call-attempts')).to_have_text('2콜');expect(page.locator('#today-call-connected')).to_have_text('1콜')
        yesterday=self.today-timedelta(days=1)
        expect(page.locator(f'#performance-rows tr[data-date="{yesterday}"] td').last).to_have_text('1')
        page.reload();expect(self.today_row().locator('td')).to_have_text(['2','0','0'])
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_missing_performance_relation_error_and_restored_schema_retry(self):
        self.seed();self.login(self.employee);page=self.page
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        sqlstates=[];execute=CursorWrapper.execute
        def observed(cursor,sql,params=None):
            try:return execute(cursor,sql,params)
            except DatabaseError as error:
                sqlstates.append(getattr(error.__cause__,'sqlstate',None));raise
        def rename(missing):
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE consultations_customeractivity RENAME TO consultations_customeractivity_local_missing' if missing else
                    'ALTER TABLE consultations_customeractivity_local_missing RENAME TO consultations_customeractivity')
        self.db(lambda:rename(True))
        try:
            with patch.object(CursorWrapper,'execute',new=observed),self.assertLogs('django.request',level='ERROR') as logs:
                with page.expect_response('**/api/dashboard/performance*') as response:page.reload()
                expect(page.locator('#today-call-attempts')).to_have_text('조회 실패')
            wire=response.value.json()
            self.assertEqual(response.value.status,503);self.assertIn('42P01',sqlstates)
            self.assertIn('불러오지 못했습니다',wire['error']['message'])
            self.assertNotIn('저장',wire['error']['message'])
            expect(page.locator('#performance-status')).to_have_text('실적을 불러오지 못했습니다. 다시 조회해 주세요.')
            self.assertTrue(any(getattr(row,'status_code',None)==503 for row in logs.records))
            artifact_path('performance-read-reproduction.json').write_text(json.dumps({'route':'/api/dashboard/performance',
                'status':response.value.status,'error':wire['error'],'sqlstates':sqlstates,'server_503_logged':any(getattr(row,'status_code',None)==503 for row in logs.records)},ensure_ascii=False))
        finally:self.db(lambda:rename(False))
        page.locator('#performance-retry').click();expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        expect(self.today_row().locator('td').first).to_have_text('2')

    def test_monthly_evidence_today_match_previous_month_missing_data_and_responsive(self):
        self.seed();self.login(self.employee);page=self.page
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        expect(page.locator('#today-call-connected')).to_have_text('1콜')
        expect(self.today_row().locator('td')).to_have_text(['2','1','0'])
        expect(page.locator('#performance-month')).to_have_value(self.today.strftime('%Y-%m'))
        expect(page.locator('.monthly-performance-table thead th')).to_have_text(['날짜','콜 수','가망고객 수','방문고객 수'])
        tomorrow=self.today+timedelta(days=1)
        if tomorrow.month==self.today.month:expect(page.locator(f'#performance-rows tr[data-date="{tomorrow}"] td')).to_have_text(['—','—','—'])
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            first=page.locator('#today-call-attempts').bounding_box();second=page.locator('#today-call-connected').bounding_box()
            self.assertLess(first['x'],second['x']);self.assertAlmostEqual(first['y'],second['y'],delta=3)
            page.screenshot(path=str(artifact_path(f'employee-performance-{width}.png')),full_page=True)
        previous=(self.today.replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
        page.locator('#performance-month').fill(previous);page.locator('#performance-month').dispatch_event('change')
        expect(page.locator('#performance-status')).to_contain_text(previous)
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        page.locator('#performance-month').fill('2000-01');page.locator('#performance-month').dispatch_event('change')
        expect(page.locator('#performance-status')).to_contain_text('2000-01')
        expect(page.locator('#performance-rows tr').first.locator('td')).to_have_text(['집계 자료 없음']*3)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_explicit_call_and_actual_visit_record_dialog_keyboard_and_counts(self):
        self.seed();self.login(self.employee);page=self.page
        page.locator('[data-customer-category=held]').click()
        trigger=page.locator(f'.employee-customer[data-customer-id="{self.a.pk}"]').get_by_role('button',name='통화·방문 기록')
        trigger.focus();page.keyboard.press('Enter')
        expect(page.locator('#activity-dialog')).to_be_visible();page.keyboard.press('Escape')
        expect(trigger).to_be_focused()
        trigger.click();page.locator('#activity-connection').select_option('UNKNOWN');page.locator('#activity-submit').click()
        expect(page.locator('#activity-dialog')).not_to_be_visible();expect(page.locator('#today-call-attempts')).to_have_text('3콜')
        expect(page.locator('#today-call-connected')).to_have_text('1콜')
        trigger.click();page.locator('#activity-kind').select_option('VISIT');page.locator('#activity-visit-date').fill(self.today.isoformat());page.locator('#activity-submit').click()
        expect(page.locator('#activity-dialog')).not_to_be_visible();expect(self.today_row().locator('td')).to_have_text(['3','1','1'])
        self.assertEqual(self.db(lambda:CustomerActivity.objects.filter(actor=self.employee,kind='CALL').count()),3)
        self.assertEqual(self.errors,[])

    def test_lost_record_response_reload_same_key_is_not_another_call(self):
        self.seed();self.login(self.employee);page=self.page
        page.locator('[data-customer-category=held]').click()
        page.locator(f'.employee-customer[data-customer-id="{self.a.pk}"]').get_by_role('button',name='통화·방문 기록').click()
        keys=[]
        def lose(route):
            if route.request.method!='POST':route.continue_();return
            keys.append(route.request.post_data_json['idempotency_key']);response=route.fetch()
            self.assertEqual(response.status,201);route.fulfill(status=503,json={'error':{'message':'가상 응답 유실'}})
        page.route('**/api/customers/*/activities',lose)
        page.locator('#activity-connection').select_option('CONNECTED');page.locator('#activity-submit').click()
        expect(page.locator('#activity-error')).to_contain_text('결과를 확인하지 못했습니다')
        page.locator('#activity-close').click();page.unroute('**/api/customers/*/activities',lose)
        page.once('dialog',lambda dialog:dialog.accept());page.reload()
        expect(page.locator('#activity-pending')).to_be_visible();expect(page.locator('#today-call-attempts')).to_have_text('3콜')
        def retry(route):
            if route.request.method=='POST':keys.append(route.request.post_data_json['idempotency_key'])
            route.continue_()
        page.route('**/api/customers/*/activities',retry)
        page.locator('#activity-retry').click();expect(page.locator('#activity-pending')).not_to_be_visible()
        expect(page.locator('#today-call-attempts')).to_have_text('3콜');expect(page.locator('#today-call-connected')).to_have_text('2콜')
        self.assertEqual(len(keys),2);self.assertEqual(keys[0],keys[1])
        self.assertEqual(self.errors,[])

    def test_site_month_races_failure_retry_and_grid_entry(self):
        self.seed();self.login(self.employee);page=self.page
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 실적 조회 실패'}})
        page.route('**/api/dashboard/performance*',fail);page.locator('#dashboard-refresh').click()
        expect(page.locator('#performance-status')).to_contain_text('마지막 성공 결과')
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        page.unroute('**/api/dashboard/performance*',fail);page.locator('#performance-retry').click()
        expect(page.locator('#performance-retry')).not_to_be_visible()
        held=[]
        def delay(route):
            if 'site_id='+str(self.site.pk) in route.request.url:held.append((route,route.fetch()))
            else:route.continue_()
        page.route('**/api/dashboard/performance*',delay);page.locator('#dashboard-refresh').click()
        expect(page.locator('#monthly-performance')).to_have_attribute('aria-busy','true')
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#today-call-attempts')).to_have_text('0콜')
        for route,response in held:route.fulfill(response=response)
        expect(page.locator('#today-call-attempts')).to_have_text('0콜')
        page.unroute('**/api/dashboard/performance*',delay)
        page.locator('#performance-open-mine').click();expect(page.locator('#page-info')).to_contain_text('검색 1명')
        cell=page.locator('#employee-grid .tabulator-row [tabulator-field="_actions"]').first
        cell.scroll_into_view_if_needed();cell.get_by_role('button',name='통화·방문 기록').click()
        expect(page.locator('#activity-dialog')).to_be_visible();page.locator('#activity-close').click()
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_first_load_failure_has_retry_without_zero_or_endless_loading(self):
        self.seed();page=self.page
        # Even an older server's misleading write error must read as a query failure.
        def fail(route):route.fulfill(status=503,json={'error':{'message':'저장을 완료하지 못했습니다. 같은 요청으로 다시 확인해 주세요.'}})
        page.route('**/api/dashboard/performance*',fail)
        self.login(self.employee)
        expect(page.locator('#today-call-attempts')).to_have_text('조회 실패')
        expect(page.locator('#performance-status')).to_have_text('실적을 불러오지 못했습니다. 다시 조회해 주세요.')
        expect(page.locator('#performance-rows tr')).to_have_count(0)
        page.unroute('**/api/dashboard/performance*',fail)
        page.locator('#performance-retry').click()
        expect(page.locator('#today-call-attempts')).to_have_text('2콜')
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#today-call-attempts')).to_have_text('0콜')
        self.db(lambda:PerformanceTracking.objects.all().delete())
        page.locator('#dashboard-refresh').click()
        expect(page.locator('#today-call-attempts')).to_have_text('집계 자료 없음')
        expect(self.today_row().locator('td').first).to_have_text('집계 자료 없음')
        self.assertEqual(self.errors,[])
