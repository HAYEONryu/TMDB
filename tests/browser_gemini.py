"""Real browser + native Gemini adapter with synthetic wire data, no external I/O."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch
from django.db import close_old_connections
from django.test import override_settings
from playwright.sync_api import expect
from apps.ai_assistant.gemini_adapter import GeminiAdapter
from apps.ai_assistant.models import AIRequest
from apps.ai_assistant.worker import run_once
from tests.browser_p12 import P12BrowserTests
from tests.test_gemini_adapter import CONFIG, wire
from tests.test_openai_adapter import payload_for


class GeminiBrowserKeyTests(P12BrowserTests):
    def setUp(self):
        super().setUp()
        setting = override_settings(AI_FOUNDATION_TEST_MODE=False, AI_CONFIG=replace(CONFIG, api_key=self.sentinel))
        setting.enable(); self.addCleanup(setting.disable)

    def worker(self):
        def execute():
            close_old_connections()
            try:
                def transport(body, key):
                    self.assertEqual(key, self.sentinel)
                    task = AIRequest.objects.get(status='RUNNING')
                    return 200, wire(payload_for(task)), 'standard'
                with patch('http.client.HTTPSConnection', side_effect=AssertionError('NO_NETWORK')):
                    return run_once(GeminiAdapter(transport=transport))
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(execute).result()['succeeded'], 1)

    def test_employee_generation_and_encrypted_queue_never_receive_server_key(self):
        self.login(self.employee)
        self.page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(self.page.locator('#page-info')).to_contain_text('검색 1건')
        def generate(route):
            response=route.fetch();self.assertEqual(response.status,202)
            self.responses.append((response.headers,response.body()))
            self.worker();route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',generate,times=1)
        self.page.get_by_role('button',name='AI 도움',exact=True).click();self.page.get_by_role('button',name='핵심 요약',exact=True).click()
        expect(self.page.locator('#ai-content')).to_contain_text('상담 핵심')
        expect(self.page.locator('#ai-content')).not_to_contain_text('테스트 전용 가짜 응답')
        self.inspect()

    def test_admin_generation_review_and_publication_never_receive_server_key(self):
        self.login(self.admin)
        self.page.goto(self.live_server_url+'/app/admin/ai')
        expect(self.page.locator('#report-message')).to_contain_text('AI 생성은 유료')
        self.page.locator('#report-type').select_option('TEAM_GUIDE')
        def generate(route):
            if route.request.method!='POST':return self.capture_route(route)
            response=route.fetch();self.assertEqual(response.status,202)
            self.responses.append((response.headers,response.body()))
            self.worker();route.fulfill(response=response)
        self.page.route('**/api/ai/sites/*/guides',generate)
        self.page.locator('#report-generate').click()
        expect(self.page.locator('#guide-editor')).to_be_visible()
        self.inspect()
