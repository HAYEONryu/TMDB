from datetime import datetime, time, timedelta
from unittest.mock import patch
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db.migrations.recorder import MigrationRecorder
from django.contrib.sessions.models import Session
from django.utils import timezone
from playwright.sync_api import expect
from apps.consultations.models import ConsultationRevision, CustomerActivity, PerformanceTracking
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.customers.queries import KST
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures
from tests.browser_dialog_helpers import confirm_action


class DailyCallResultBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self):
        def create():
            now=timezone.now();today=now.astimezone(KST).date();start=datetime.combine(today,time.min,KST)
            MigrationRecorder.Migration.objects.filter(app='consultations',name='0001_initial').update(applied=start-timedelta(days=30))
            PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':start-timedelta(days=30)})
            row=self.customers()[0];self.assign(row,at=start-timedelta(days=2))
            ConsultationRevision.objects.create(customer=row,assignment=row.current_assignment,actor=self.employee,saved_at=now-timedelta(seconds=1),
                customer_version=1,source='MANUAL',changed_fields=['call_result'],after_values={'call_result':'INTERESTED'})
            Customer.objects.filter(pk=row.pk).update(version=2,call_result='INTERESTED',housing_status='무주택',route='티엠')
            return row,today
        self.row,self.today=self.db(create)

    def metric(self,code):return self.page.locator(f'[data-call-result="{code}"]')

    def test_daily_defaults_scope_date_missing_zero_error_retry_and_responsive(self):
        self.seed();self.login(self.employee);page=self.page
        expect(page.locator('#call-results-date')).to_have_value(self.today.isoformat())
        expect(self.metric('INTERESTED')).to_have_text('1명');expect(self.metric('NO_ANSWER')).to_have_text('0명')
        yesterday=(self.today-timedelta(days=1)).isoformat()
        page.locator('#call-results-date').fill(yesterday);page.locator('#call-results-date').dispatch_event('change')
        expect(self.metric('INTERESTED')).to_have_text('0명')
        page.locator('#call-results-date').fill('2000-01-01');page.locator('#call-results-date').dispatch_event('change')
        expect(self.metric('INTERESTED')).to_have_text('집계 자료 없음')
        def fail(route):route.fulfill(status=503,json={'error':{'message':'저장 실패'}})
        page.route('**/api/dashboard/call-results*',fail)
        page.locator('#call-results-date').fill(self.today.isoformat());page.locator('#call-results-date').dispatch_event('change')
        expect(self.metric('INTERESTED')).to_have_text('조회 실패')
        expect(page.locator('#call-results-status')).to_contain_text('불러오지 못했습니다')
        expect(page.locator('#call-results-status')).not_to_contain_text('저장 실패')
        page.unroute('**/api/dashboard/call-results*',fail);page.locator('#call-results-retry').click()
        expect(self.metric('INTERESTED')).to_have_text('1명')
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk));expect(self.metric('INTERESTED')).to_have_text('0명')
        page.locator('#employee-dashboard-site').select_option(str(self.site.pk));expect(self.metric('INTERESTED')).to_have_text('1명')
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.screenshot(path=str(artifact_path(f'daily-call-results-{width}.png')),full_page=True)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_today_grid_order_planned_visit_autosave_filter_deletion_and_explicit_call_date(self):
        self.seed();self.login(self.employee);page=self.page
        page.goto(self.live_server_url+f'/app/employee/today?site_id={self.site.pk}&q={self.row.phone_normalized}')
        try:expect(page.locator('#page-info')).to_contain_text('검색 1명')
        except AssertionError:
            page.screenshot(path=str(artifact_path('grid-load-diagnostic.png')),full_page=True)
            raise
        headers=page.locator('#employee-grid .tabulator-col-title')
        self.assertEqual([v.rstrip(' ↕↑↓') for v in headers.all_text_contents()[:11]],['최종 TM 날짜','고객명','연락처','통화결과','삭제요청','고객 거주지','재콜일정','주택보유상황','상담내용','방문예약 날짜','계약여부'])
        for field in ['tm_status','memo','route','assigned_at']:
            expect(page.locator(f'#employee-grid .tabulator-col[tabulator-field="{field}"]')).to_have_count(0)
        for field,width in [('phone_normalized',154),('call_result',166),('notes',340),('housing_status',168)]:
            self.assertAlmostEqual(page.locator(f'#employee-grid .tabulator-col[tabulator-field="{field}"]').evaluate('e=>e.getBoundingClientRect().width'),width,delta=1)
        def cell(field):return page.locator(f'#employee-grid .tabulator-row [tabulator-field="{field}"]')
        expect(cell('last_tm_date')).to_have_text('-');cell('last_tm_date').dblclick();expect(cell('last_tm_date').locator('input')).to_have_count(0)
        def edit(field,value):
            c=cell(field);c.scroll_into_view_if_needed();c.dblclick()
            control=c.locator('select,input,textarea')
            control.select_option(value) if field in {'call_result','contract_status'} else control.fill(value)
            page.locator('h1').click()
        page.clock.install()
        edit('call_result','VISIT_BOOKED');page.clock.fast_forward(91000)
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨');expect(cell('call_result')).to_have_text('방문예정')
        self.assertFalse(self.db(lambda:CustomerDeletionRequest.objects.exists()))
        long_notes='상담 전체 내용 '*30+chr(10)+'두 번째 줄과 확인할 질문'
        edit('notes',long_notes);page.locator('#save-now').click()
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        expect(cell('last_tm_date')).to_have_text('-')
        cell('notes').dblclick();expect(cell('notes').locator('textarea')).to_have_value(long_notes);page.locator('h1').click()
        page.reload();expect(cell('call_result')).to_have_text('방문예정')
        page.locator('#open-filters').click();page.locator('section[data-field="call_result"] details summary').click()
        page.locator('.filter-toggle[data-value="VISIT_BOOKED"]').click();page.locator('#filter-apply').click()
        expect(page.locator('#page-info')).to_contain_text('검색 1명');expect(page.locator('#active-filters')).to_contain_text('방문예정')
        action=page.get_by_role('button',name='통화·방문 기록',exact=True);action.scroll_into_view_if_needed();action.click()
        page.locator('#activity-connection').select_option('NOT_CONNECTED')
        page.locator('#activity-at').fill(self.db(timezone.now).astimezone(KST).strftime('%Y-%m-%dT%H:%M:%S'))
        page.locator('#activity-submit').click()
        expect(page.locator('#activity-dialog')).not_to_be_visible();expect(cell('last_tm_date')).to_have_text(self.today.isoformat())
        self.assertEqual(self.db(lambda:CustomerActivity.objects.filter(customer=self.row,kind='CALL').count()),1)
        edit('notes','상담내용만 정정');page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        edit('contract_status','CONTRACT_CANCELLED');page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        expect(cell('last_tm_date')).to_have_text(self.today.isoformat())
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            page.locator('#employee-grid .tabulator-tableholder').evaluate('e=>e.scrollLeft=0')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            holder=page.locator('#employee-grid .tabulator-tableholder');self.assertGreater(holder.evaluate('e=>e.scrollWidth'),holder.evaluate('e=>e.clientWidth'))
            page.screenshot(path=str(artifact_path(f'today-tm-layout-{width}.png')),full_page=True)
        row=self.db(lambda:Customer.objects.get(pk=self.row.pk));self.assertEqual((row.housing_status,row.route),('무주택','티엠'))
        page.set_viewport_size({'width':1440,'height':960})
        with page.expect_response(lambda response:'/api/customers?' in response.url):page.locator('#clear-filters').click()
        expect(page.locator('#employee-grid')).to_have_attribute('aria-busy','false')
        edit('call_result','DELETE_REQUEST');page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertFalse(self.db(lambda:CustomerDeletionRequest.objects.exists()))
        request=page.get_by_role('button',name='삭제 요청',exact=True);request.scroll_into_view_if_needed();request.click()
        confirm_action(page)
        expect(page.get_by_role('button',name='요청완료',exact=True)).to_be_visible()
        self.assertTrue(self.db(lambda:CustomerDeletionRequest.objects.exists()))
        self.assertEqual(self.errors,[])

    def test_default_date_rolls_at_kst_midnight_without_closing_day(self):
        self.seed();self.page.clock.install();self.login(self.employee);page=self.page
        tomorrow=datetime.combine(self.today+timedelta(days=1),time.min,KST)
        self.db(lambda:Session.objects.update(expire_date=tomorrow+timedelta(days=2)))
        phase={'next':False}
        def clocked(route):
            if phase['next']:
                with patch('django.utils.timezone.now',return_value=tomorrow):response=route.fetch()
                route.fulfill(response=response)
            else:
                response=route.fetch();data=response.json();data['as_of']=(tomorrow-timedelta(seconds=1)).isoformat();route.fulfill(response=response,json=data)
        page.route('**/api/dashboard/call-results*',clocked)
        with page.expect_response('**/api/dashboard/call-results*'):page.locator('#dashboard-refresh').click()
        expect(self.metric('INTERESTED')).to_have_text('1명')
        phase['next']=True;page.clock.fast_forward(31000)
        expect(page.locator('#call-results-date')).to_have_value(tomorrow.date().isoformat())
        expect(self.metric('INTERESTED')).to_have_text('0명')
