"""Inspect real browser traffic, DOM, console and browser storage for a synthetic key."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from django.test import override_settings
from playwright.sync_api import sync_playwright, expect

from apps.ai_assistant.worker import run_once
from config.ai import load_ai_config
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures


@override_settings(AI_FOUNDATION_TEST_MODE=True)
class P12BrowserTests(Fixtures, StaticLiveServerTestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.customer.notes = '가짜 상담 후 추가 확인'
        self.customer.save()
        self.assign(self.customer)
        self.sentinel = 'TEST_ONLY_SENTINEL_' + uuid4().hex
        directory = TemporaryDirectory(prefix='tm-p12-key-', dir='/private/tmp')
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / '.env.ai'
        path.write_text('AI_ENABLED=true\nAI_API_KEY=' + self.sentinel +
                        '\nAI_PROVIDER=test-only\nAI_MODEL=test-model\n'
                        'AI_INPUT_USD_PER_MILLION=.1\nAI_OUTPUT_USD_PER_MILLION=.3\n')
        path.chmod(0o600)
        override = override_settings(AI_CONFIG=load_ai_config(Path(directory.name), role='web', environment={}))
        override.enable()
        self.addCleanup(override.disable)
        self.responses = []
        self.requests = []
        self.console = []
        self.errors = []
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(settings.BASE_DIR / '.cache/ms-playwright'))
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.context = self.browser.new_context()
        self.context.route('**/*', self.capture_route)
        self.context.on('request', lambda request: self.requests.append(request))
        self.context.on('page', self.watch_page)
        self.page = self.context.new_page()

    def watch_page(self, page):
        page.on('console', lambda message: self.console.append(message.text))
        page.on('pageerror', lambda error: self.errors.append(str(error)))

    def capture_route(self, route):
        # Capture before navigation can discard Chromium's response body handle.
        response = route.fetch(max_redirects=0)
        self.responses.append((response.headers, response.body()))
        route.fulfill(response=response)

    def tearDown(self):
        try:
            self.browser.close()
        finally:
            self.pw.stop()
        super().tearDown()

    def login(self, account):
        self.page.goto(self.live_server_url + '/auth/login')
        self.page.get_by_label('전화번호', exact=True).fill(account.phone_normalized)
        self.page.get_by_label('비밀번호', exact=True).fill(STRONG_PASSWORD)
        self.page.get_by_role('button', name='로그인', exact=True).click()
        expect(self.page).to_have_url(self.live_server_url + ('/app/admin' if account.role == 'ADMIN' else '/app/employee'))

    def worker(self):
        def execute():
            close_old_connections()
            try:
                return run_once()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(execute).result()['succeeded'], 1)

    def inspect(self):
        self.page.wait_for_load_state('networkidle')
        expect(self.page.locator('body')).to_be_visible()
        self.assertNotIn(self.sentinel, self.page.content())
        self.assertNotIn(self.sentinel, json.dumps(self.context.storage_state(indexed_db=True)))
        self.assertNotIn(self.sentinel, self.page.evaluate('JSON.stringify({...sessionStorage})'))
        for request in self.requests:
            self.assertIn(urlsplit(request.url).hostname, ['localhost', '127.0.0.1'])
            self.assertNotIn(self.sentinel, request.url + json.dumps(request.headers) + (request.post_data or ''))
        self.assertTrue(self.responses)
        for headers, body in self.responses:
            self.assertNotIn(self.sentinel, json.dumps(headers))
            self.assertNotIn(self.sentinel.encode(), body)
        self.assertEqual(self.errors, [])
        self.assertNotIn(self.sentinel, json.dumps(self.console))

    def test_employee_generation_and_encrypted_queue_never_receive_server_key(self):
        self.login(self.employee)
        self.page.goto(self.live_server_url + f'/app/employee/mine?site_id={self.site.pk}')
        expect(self.page.locator('#page-info')).to_contain_text('검색 1건')

        def generate(route):
            response = route.fetch()
            self.assertEqual(response.status, 202)
            self.responses.append((response.headers, response.body()))
            self.worker()
            route.fulfill(response=response)

        self.page.route('**/api/ai/customer-tasks', generate, times=1)
        self.page.get_by_role('button', name='AI 상담 정리', exact=True).click()
        expect(self.page.locator('#ai-content')).to_contain_text('테스트 전용 가짜 응답')
        self.page.get_by_label('상담기타내용(비고) 제안 선택', exact=True).check()
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('#ai-apply').click()
        expect(self.page.locator('#ai-result-message')).to_contain_text('저장 대기열에 반영')
        self.inspect()
        self.page.locator('#ai-dialog [data-close]').click()
        self.page.locator('#save-now').click()
        expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.inspect()

    def test_admin_generation_review_and_publication_never_receive_server_key(self):
        self.login(self.admin)
        self.page.goto(self.live_server_url + '/app/admin/ai')
        expect(self.page.locator('#report-message')).to_contain_text('테스트 전용')
        self.page.locator('#report-type').select_option('TEAM_GUIDE')
        expect(self.page.locator('#report-site')).to_have_value(str(self.site.pk))

        def generate(route):
            if route.request.method != 'POST':
                return self.capture_route(route)
            response = route.fetch()
            self.assertEqual(response.status, 202)
            self.responses.append((response.headers, response.body()))
            self.worker()
            route.fulfill(response=response)

        self.page.route('**/api/ai/sites/*/guides', generate)
        self.page.locator('#report-generate').click()
        expect(self.page.locator('#guide-editor')).to_be_visible()
        self.inspect()
        self.page.locator('#guide-reviewed').check()
        self.page.locator('#guide-save').click()
        expect(self.page.locator('#guide-publish')).to_be_enabled()
        self.page.locator('#guide-publish').click()
        expect(self.page.locator('#guide-status')).to_contain_text('게시 완료')
        self.inspect()
        self.page.goto(self.live_server_url + '/app/guides')
        expect(self.page.locator('#published-message')).to_contain_text('테스트')
        expect(self.page.locator('#published-body')).not_to_be_empty()
        self.inspect()
