"""Readable branding, role navigation and truthful overview counts."""
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright, expect

from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from django.utils import timezone
from datetime import timedelta
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures


class DoodreamUIBrowserTests(Fixtures, StaticLiveServerTestCase):
    def setUp(self):
        self.prepare()
        self.rows = self.customers(3)
        for row in self.rows[:2]: self.assign(row)
        Callback.objects.create(customer=self.rows[0], due_at=timezone.now()-timedelta(hours=1),
                                created_by=self.employee, updated_by=self.employee)
        ConsultationRevision.objects.create(customer=self.rows[0],assignment=self.rows[0].current_assignment,actor=self.employee,
            saved_at=timezone.now(),customer_version=1,changed_fields=['call_result'],after_values={'call_result':'INTERESTED'},source='MANUAL')
        for version,field in [(2,'notes'),(3,'callback_due_at')]:
            ConsultationRevision.objects.create(customer=self.rows[0],assignment=self.rows[0].current_assignment,actor=self.employee,
                saved_at=timezone.now(),customer_version=version,changed_fields=[field],after_values={'call_result':'INTERESTED'},source='MANUAL')
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch()
        self.context=self.browser.new_context(viewport={'width':1440,'height':960})
        self.page=self.context.new_page()
        self.errors=[];self.external=[];self.ai_posts=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.context.on('request',self.watch)

    def watch(self,request):
        if urlsplit(request.url).hostname not in {'localhost','127.0.0.1'}: self.external.append(request.url)
        if '/api/ai/' in request.url and request.method=='POST': self.ai_posts.append(request.url)

    def tearDown(self):
        self.context.close();self.browser.close();self.pw.stop()
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[])
        self.assertEqual(self.ai_posts,[])
        super().tearDown()

    def login(self,account):
        self.page.goto(self.live_server_url+'/auth/login')
        self.page.get_by_label('아이디 또는 전화번호',exact=True).fill(account.phone_normalized)
        self.page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD)
        self.page.get_by_role('button',name='로그인',exact=True).click()
        expect(self.page).to_have_url(self.live_server_url+'/app/'+('admin' if account.role=='ADMIN' else 'employee'))

    def test_login_brand_keyboard_access_and_mobile_readability(self):
        self.page.goto(self.live_server_url+'/auth/login')
        expect(self.page).to_have_title('로그인 · 두드림 TM')
        expect(self.page.get_by_role('link',name='두드림 TM 홈')).to_be_visible()
        self.page.keyboard.press('Tab')
        expect(self.page.get_by_role('link',name='본문으로 바로가기')).to_be_focused()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#main-content')).to_be_focused()
        for width in [320,390,768,1440]:
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)
            self.assertGreaterEqual(self.page.locator('body').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)'),16)
            self.assertGreaterEqual(self.page.get_by_label('아이디 또는 전화번호',exact=True).bounding_box()['height'],48)
            self.assertGreaterEqual(self.page.get_by_role('button',name='로그인',exact=True).bounding_box()['height'],48)

    def test_admin_overview_counts_site_change_and_empty_requests(self):
        self.login(self.admin)
        cards=self.page.locator('#dashboard-summary .overview-metric')
        expect(cards).to_have_count(4)
        for index,value in enumerate(['3건','1건','2건','2명']): expect(cards.nth(index).locator('dd')).to_have_text(value)
        expect(self.page.locator('.request-empty')).to_be_visible()
        expect(self.page.locator('.request-table')).to_be_hidden()
        self.page.locator('#default-site').select_option(str(self.second.pk))
        for index,value in enumerate(['0건','0건','0건','2명']): expect(cards.nth(index).locator('dd')).to_have_text(value)
        self.page.locator('.dashboard-detail summary').click()
        expect(self.page.locator('#dashboard-statistics')).to_be_visible()
        for path in ['customers','imports','assignments','trash','users','ai']:
            self.page.goto(self.live_server_url+'/app/admin/'+path)
            expect(self.page.locator('.workspace-nav [aria-current="page"]')).to_have_count(1)
            self.page.set_viewport_size({'width':390,'height':844})
            self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)

    def test_employee_overview_customer_first_and_password_access_on_mobile(self):
        self.login(self.employee)
        cards=self.page.locator('#dashboard-summary .overview-metric')
        expect(cards).to_have_count(4)
        expect(cards.nth(0).locator('dd')).to_have_text('2건')
        expect(cards.nth(1).locator('dd')).to_have_text('1건')
        self.page.get_by_role('link',name='나의 DB 열기',exact=True).click()
        expect(self.page.locator('#page-info')).to_contain_text('검색 2건')
        expect(self.page.locator('#employee-grid .tabulator-header .tabulator-col').first).to_have_attribute('tabulator-field','customer_name')
        expect(self.page.locator('.workspace-nav [aria-current="page"]')).to_have_text('나의 DB')
        for width in [320,390,768]:
            self.page.set_viewport_size({'width':width,'height':844})
            self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)
        self.page.get_by_role('link',name='비밀번호 변경',exact=True).click()
        expect(self.page.get_by_role('heading',name='비밀번호 변경')).to_be_visible()

    def test_manager_charts_period_switch_staff_views_and_failed_refresh_clear_old_data(self):
        self.login(self.admin)
        expect(self.page.locator('#graph-site option')).to_have_count(2)
        expect(self.page.locator('#result-period option')).to_have_text(['전체 기간','금주','오늘'])
        expect(self.page.locator('#staff-record-chart svg')).to_be_visible()
        expect(self.page.locator('#staff-record-chart')).to_contain_text(self.employee.name)
        # Identify the employee rather than relying on timestamps/UUID order.
        expect(self.page.locator('#staff-record-chart .staff-bar title',has_text=self.employee.name+': 1명')).to_have_count(1)
        expect(self.page.locator('#staff-record-range')).to_contain_text('같은 고객은 직원별 1명으로 집계')
        expect(self.page.locator('#call-result-chart .donut-total')).to_have_text('3건')
        self.page.locator('#result-period').select_option('today')
        expect(self.page.locator('#call-result-chart .donut-total')).to_have_text('1건')
        expect(self.page.locator('#call-result-legend')).to_contain_text('관심')
        self.page.locator('#result-period').select_option('week')
        expect(self.page.locator('#result-basis')).to_contain_text('금주 월요일부터 일요일')
        self.page.get_by_role('button',name='영업 진행 현황',exact=True).click()
        expect(self.page.locator('#staff-progress-panel')).to_be_visible()
        expect(self.page.locator('#staff-allocation-panel')).to_be_hidden()
        expect(self.page.locator('#staff-progress-table')).to_contain_text('미진행')
        self.page.locator('#graph-site').select_option(str(self.second.pk))
        expect(self.page.locator('#default-site')).to_have_value(str(self.second.pk))
        expect(self.page.locator('#call-result-chart .donut-total')).to_have_text('0건')
        self.page.locator('#default-site').select_option(str(self.site.pk))
        expect(self.page.locator('#graph-site')).to_have_value(str(self.site.pk))
        expect(self.page.locator('#call-result-chart .donut-total')).to_have_text('1건')
        self.page.route('**/api/dashboard*',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":{"message":"가짜 일시 오류"}}'))
        self.page.locator('#dashboard-refresh').click()
        expect(self.page.locator('#dashboard-summary')).to_contain_text('불러오지 못했습니다')
        expect(self.page.locator('#staff-record-chart svg')).to_have_count(0)
        expect(self.page.locator('#call-result-chart svg')).to_have_count(0)
