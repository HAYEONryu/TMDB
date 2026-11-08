"""Free-tier state in a real browser; native adapter receives synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone
from playwright.sync_api import expect
from apps.accounts.models import User
from apps.ai_assistant import free_limits
from apps.ai_assistant.models import AIProviderQuota, AIProviderQuotaDay, AIProviderDispatch
from apps.ai_assistant.worker import run_once
from tests import browser_gemini as previous
from tests.test_free_ai_limits import FREE
from tests.helpers import user


class FreeAIBrowserTests(previous.GeminiBrowserKeyTests):
    def setUp(self):
        super().setUp()
        self.free=replace(FREE,api_key=self.sentinel)
        setting=override_settings(AI_CONFIG=self.free)
        setting.enable();self.addCleanup(setting.disable)

    def database(self,function):
        def execute():
            close_old_connections()
            try:return function()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(execute).result()

    def fill_global(self):
        quota,_=AIProviderQuota.objects.get_or_create(scope_key=free_limits.scope_key(self.free))
        AIProviderQuotaDay.objects.update_or_create(quota=quota,provider_date=free_limits.provider_day(timezone.now()),defaults={'sent_count':500,'reserved_count':0})

    def test_employee_generation_and_encrypted_queue_never_receive_server_key(self):
        self.login(self.employee)
        self.page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(self.page.locator('#ai-usage')).to_contain_text('/ 40회')
        expect(self.page.locator('#ai-usage')).to_contain_text('서버 공용 남은 500회 / 500회')
        def generate(route):
            response=route.fetch();self.assertEqual(response.status,202)
            self.responses.append((response.headers,response.body()))
            self.worker();route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',generate,times=1)
        self.page.get_by_role('button',name='상담 요약',exact=True).click()
        expect(self.page.locator('#ai-content')).to_contain_text('상담 핵심')
        self.inspect()
        self.database(self.fill_global)
        self.page.reload()
        expect(self.page.locator('#ai-usage')).to_contain_text('남은 39회 / 40회')
        expect(self.page.locator('#ai-usage')).to_contain_text('서버 공용 남은 0회 / 500회')
        expect(self.page.locator('#ai-availability')).to_contain_text('개인 잔여 횟수가 있어도')
        expect(self.page.get_by_role('button',name='상담 요약',exact=True)).to_be_disabled()
        self.inspect()

    def test_admin_generation_review_and_publication_never_receive_server_key(self):
        self.admin2=self.database(lambda:user('01000000004',role=User.Role.ADMIN,initial=False))
        with override_settings(AI_CONFIG=replace(self.free,free_rpd=1)):
            self.login(self.admin)
            self.page.goto(self.live_server_url+'/app/admin/ai')
            self.page.locator('#report-type').select_option('TEAM_GUIDE')
            def generate(route):
                if route.request.method!='POST':return self.capture_route(route)
                response=route.fetch();self.assertEqual(response.status,202)
                self.responses.append((response.headers,response.body()))
                self.worker();route.fulfill(response=response)
            self.page.route('**/api/ai/sites/*/guides',generate)
            self.page.locator('#report-generate').click()
            expect(self.page.locator('#guide-editor')).to_be_visible()
            expect(self.page.locator('#report-message')).to_contain_text('서버 공용 남은 0회 / 1회')
            self.inspect()
            self.context.clear_cookies();self.login(self.admin2)
            self.page.goto(self.live_server_url+'/app/admin/ai')
            self.page.locator('#report-type').select_option('TEAM_GUIDE')
            expect(self.page.locator('#report-history button')).to_have_count(1)
            self.page.locator('#report-history button').click()
            expect(self.page.locator('#guide-editor')).to_be_visible()
            expect(self.page.locator('#report-generate')).to_be_disabled()
            self.assertEqual(len([r for r in self.requests if r.method=='POST' and '/api/ai/sites/' in r.url and '/guides' in r.url]),1)
            self.inspect()

    def test_minute_wait_is_visible_after_request_and_page_reopen(self):
        def occupy_minute():
            quota,_=AIProviderQuota.objects.get_or_create(scope_key=free_limits.scope_key(self.free))
            now=timezone.now()
            for _ in range(15):AIProviderDispatch.objects.create(quota=quota,sent_at=now,window_ends_at=now+timedelta(seconds=60),input_tokens=1000)
        self.database(occupy_minute)
        self.login(self.employee)
        self.page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        def generate(route):
            response=route.fetch();self.assertEqual(response.status,202)
            self.responses.append((response.headers,response.body()))
            self.assertEqual(self.database(run_once)['processed'],0)
            route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',generate,times=1)
        self.page.get_by_role('button',name='상담 요약',exact=True).click()
        expect(self.page.locator('#ai-result-message')).to_contain_text('분당 요청·입력 토큰 한도에 맞춰 대기 중')
        self.page.reload()
        expect(self.page.locator('#ai-usage')).to_contain_text('예약 1회')
        expect(self.page.locator('#ai-usage')).to_contain_text('서버 공용 남은 499회 / 500회')
        self.page.locator('#ai-task-open').click()
        expect(self.page.locator('#ai-result-message')).to_contain_text('분당 요청·입력 토큰 한도에 맞춰 대기 중')
        self.inspect()
