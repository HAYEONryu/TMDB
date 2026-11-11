import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.db import close_old_connections
from django.utils.functional import classproperty
from playwright.sync_api import sync_playwright, expect

from scripts.verification_evidence import artifact_path
from tests import browser_request_id as previous
from tests import browser_p4 as p4
from tests.test_p4 import Fixtures
from tests.test_imports import workbook, row
from tests.helpers import STRONG_PASSWORD

HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "testserver", "tm-http.test"]
ARGS = ["--host-resolver-rules=MAP tm-http.test 127.0.0.1", "--proxy-bypass-list=*"]


@override_settings(ALLOWED_HOSTS=HOSTS)
class EmployeeEnvironmentBrowserTests(Fixtures, StaticLiveServerTestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.assign(self.customer)
        self.errors, self.requests = [], []
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(args=ARGS)
        self.addCleanup(self.browser.close)

    def open(self, *, insecure=False, script=None, admin=False):
        origin = self.live_server_url.replace("localhost", "tm-http.test") if insecure else self.live_server_url
        page = self.browser.new_page()
        self.addCleanup(page.close)
        if script:
            page.add_init_script(script)
        page.on("pageerror", lambda error: self.errors.append(type(error).__name__))
        page.on("request", lambda request: self.requests.append((request.method, urlsplit(request.url).path)))
        page.goto(origin + "/auth/login")
        account = self.admin if admin else self.employee
        page.get_by_label("전화번호", exact=True).fill(account.phone_normalized)
        page.get_by_label("비밀번호", exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button", name="로그인", exact=True).click()
        expect(page).to_have_url(origin + ("/app/admin" if admin else "/app/employee"))
        return page, origin

    def db(self, action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()

    def assert_blocked(self, page, message, *, context_requested=False, browse=True):
        expect(page.locator("#employee-message")).to_contain_text(message)
        expect(page.locator("#save-now")).to_be_disabled()
        if browse:
            expect(page.locator('#employee-private')).to_be_visible()
            expect(page.locator('#site')).to_be_enabled()
            expect(page.locator('#queue-status')).to_have_text('조회 전용')
            expect(page.locator('#page-info')).to_contain_text('검색 1건')
            cell=page.locator('.tabulator-row [tabulator-field="notes"]').first
            cell.dblclick();expect(cell.locator('input,textarea')).to_have_count(0)
            expect(page.get_by_role('button',name='삭제 요청',exact=True)).to_be_disabled()
        else:
            expect(page.locator('#employee-private')).not_to_be_visible()
        expect(page.locator("#ai-toolbar")).not_to_be_visible()
        self.assertEqual(("GET", "/api/employee/context") in self.requests, context_requested)
        self.assertNotIn(("POST", "/api/employee/batch-update"), self.requests)
        self.assertEqual(self.errors, [])

    def test_http_employee_can_browse_without_encryption_key_or_editing(self):
        page, origin = self.open(insecure=True)
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        self.assertFalse(page.evaluate("isSecureContext"))
        self.assertEqual(page.evaluate("typeof crypto.subtle"), "undefined")
        self.assertEqual(page.evaluate("typeof navigator.locks"), "undefined")
        expect(page.locator("#connection-warning")).to_contain_text("HTTP 연결")
        self.assert_blocked(page, "HTTPS 접속이 필요")
        page.get_by_role("button", name="로그아웃", exact=True).click()
        expect(page).to_have_url(origin + "/auth/login")

    def test_http_today_site_selection_filters_and_session_end(self):
        def more_rows():
            row=self.customers(site=self.second,offset=31)[0];self.assign(row)
            foreign=self.customers(site=self.second,offset=41)[0];self.assign(foreign,self.other)
        self.db(more_rows)
        page,origin=self.open(insecure=True)
        page.goto(origin+'/app/employee/today')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        expect(page.locator('#site')).to_be_enabled()
        page.locator('#site').select_option(str(self.second.pk))
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        expect(page.locator('.tabulator-row [tabulator-field="customer_name"]').first).to_have_text('가상고객0031')
        page.locator('#search').fill('없는가상고객');page.locator('#search-form').get_by_role('button',name='검색',exact=True).click()
        expect(page.locator('#page-info')).to_contain_text('검색 0건')
        page.locator('#search').fill('');page.locator('#search-form').get_by_role('button',name='검색',exact=True).click()
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        page.get_by_role('button',name='상담·재콜 이력',exact=True).click()
        expect(page.locator('#history-dialog')).to_be_visible()
        page.locator('#history-dialog').get_by_role('button',name='닫기',exact=True).click()
        self.assertNotIn(('GET','/api/employee/context'),self.requests)
        self.assertFalse(any(method=='POST' and path.startswith('/api/') for method,path in self.requests))
        self.db(lambda:type(self.employee).objects.filter(pk=self.employee.pk).update(is_active=False))
        page.locator('#reload-rows').click()
        expect(page.locator('#employee-private')).not_to_be_visible()
        expect(page.locator('#employee-message')).to_contain_text('다시 로그인')

    def test_missing_locks_has_clear_message_before_editing(self):
        page, origin = self.open(script="Object.defineProperty(navigator,'locks',{value:undefined,configurable:true});")
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        self.assert_blocked(page, "다중 탭 저장")

    def test_http_old_identity_response_cannot_reopen_hidden_customer_grid(self):
        page,origin=self.open(insecure=True)
        page.goto(origin+'/app/employee/today')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        def stale_me(route):
            page.evaluate("window.dispatchEvent(new CustomEvent('tm-auth-context',{detail:{user:'other-synthetic-user',role:'EMPLOYEE',initial:false}}))")
            route.fulfill(status=200,json={'id':str(self.employee.pk),'role':'EMPLOYEE','must_change_password':False})
        page.route('**/api/me',stale_me)
        with page.expect_response('**/api/me'):
            page.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(page.locator('#employee-private')).not_to_be_visible()
        expect(page.locator('#employee-message')).to_contain_text('다른 탭에서 로그인 정보가 변경')
        self.assertNotIn(('GET','/api/employee/context'),self.requests)
        self.assertEqual(self.errors,[])

    def test_missing_crypto_subtle_has_clear_message_before_editing(self):
        page, origin = self.open(script="Object.defineProperty(crypto,'subtle',{value:undefined,configurable:true});")
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        self.assert_blocked(page, "최신 브라우저")

    def test_storage_access_denied_has_clear_message_before_editing(self):
        page, origin = self.open(script="Object.defineProperty(window,'indexedDB',{get(){throw new DOMException('blocked','SecurityError');},configurable:true});")
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        self.assert_blocked(page, "저장소 접근이 차단")

    def test_employee_saves_without_abortsignal_timeout(self):
        page, origin = self.open(script="Object.defineProperty(AbortSignal,'timeout',{value:undefined,configurable:true});")
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        expect(page.locator("#page-info")).to_contain_text("검색 1건")
        cell = page.locator('.tabulator-row [tabulator-field="notes"]').first
        cell.dblclick()
        cell.locator("textarea").fill("가상 시간 제한 호환 저장")
        page.locator("h1").click()
        expect(page.locator("#save-now")).to_be_enabled()
        page.locator("#save-now").click()
        expect(page.locator("#queue-status")).to_have_text("모든 변경 저장됨")
        page.reload()
        expect(page.locator('.tabulator-row [tabulator-field="notes"]').first).to_have_text("가상 시간 제한 호환 저장")
        self.assertEqual(self.errors, [])

    def test_storage_opening_denied_prevents_editing(self):
        page, origin = self.open(script="Object.defineProperty(indexedDB,'open',{value(){throw new DOMException('blocked','SecurityError');},configurable:true});")
        page.goto(origin + f"/app/employee/mine?site_id={self.site.pk}")
        self.assert_blocked(page, "보관소를 열 수 없습니다", context_requested=True, browse=False)

    def test_http_excel_validation_and_commit(self):
        page, origin = self.open(insecure=True, admin=True)
        page.goto(origin + "/app/admin/imports")
        page.locator("#upload-site").select_option(str(self.site.pk))
        page.locator("#upload-file").set_input_files({"name": "synthetic.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                   "buffer": workbook([row("가상업로드고객", "01090000099")])})
        page.locator("#validate-file").click()
        expect(page.locator("#batch-status")).to_contain_text("검증 완료")
        page.locator("#commit-upload").click()
        page.locator("#commit-confirm").click()
        expect(page.locator("#batch-status")).to_contain_text("등록 확정 완료")
        self.assertEqual(self.errors, [])


@override_settings(ALLOWED_HOSTS=HOSTS)
class OptionalApisBrowserTests(previous.RequestIdBrowserTests):
    def test_http_account_actions_when_channel_and_session_storage_are_denied(self):
        original = self.browser.new_page
        from unittest.mock import patch
        def make_page(*args, **kwargs):
            page = original(*args, **kwargs)
            page.add_init_script("""window.BroadcastChannel=class {constructor(){throw new DOMException('blocked','SecurityError');}};
                Object.defineProperty(window,'sessionStorage',{get(){throw new DOMException('blocked','SecurityError');},configurable:true});""")
            return page
        with patch.object(self.browser, "new_page", side_effect=make_page):
            self.run_user_flow(insecure=True)


@override_settings(ALLOWED_HOSTS=HOSTS)
class HttpAdminP4BrowserTests(Fixtures, StaticLiveServerTestCase):
    db = p4.P4BrowserTests.db
    login = p4.P4BrowserTests.login
    save_users = p4.P4BrowserTests.save_users
    csrf = p4.P4BrowserTests.csrf
    test_assignee_and_user_save_lost_response_replay_and_noop = p4.P4BrowserTests.test_assignee_and_user_save_lost_response_replay_and_noop
    test_distribution_shortage_lost_response_reload_replay_and_today_recall = p4.P4BrowserTests.test_distribution_shortage_lost_response_reload_replay_and_today_recall
    @classproperty
    def live_server_url(cls):
        # Both browser traffic and route.fetch/APIRequestContext can resolve
        # this numeric local destination. The server still binds to localhost.
        return super().live_server_url.replace("localhost", "0.0.0.0")

    def setUp(self):
        self.prepare()
        self.rows = self.customers(95)
        self.errors, self.external = [], []
        self.evidence = artifact_path("qa")
        self.evidence.mkdir(exist_ok=True, parents=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(args=ARGS)
        self.addCleanup(lambda: self.browser.close() if self.browser.is_connected() else None)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 960})
        self.context.on("page", lambda page: page.on("pageerror", lambda error: self.errors.append(type(error).__name__)))
        self.context.on("request", lambda request: self.external.append(True) if urlsplit(request.url).hostname not in HOSTS else None)
        self.page = self.context.new_page()
        self.login(self.page, self.admin)
        self.assertFalse(self.page.evaluate("isSecureContext"))

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])

    def test_http_deactivation_invalidates_existing_employee_session(self):
        staff = self.browser.new_context()
        self.addCleanup(staff.close)
        staff_page = staff.new_page()
        self.login(staff_page, self.employee)
        self.page.goto(self.live_server_url + "/app/admin/users")
        record = self.page.locator(f'#user-rows tr[data-id="{self.employee.pk}"]')
        record.get_by_label("비활성화", exact=True).check()
        self.save_users()
        expect(self.page.locator("#user-message")).to_contain_text("1명 저장")
        # Browser traffic uses the configured HTTP hostname mapping, unlike
        # Playwright's separate APIRequestContext DNS resolver.
        response = staff_page.goto(self.live_server_url + "/api/me")
        self.assertEqual(response.status, 401)
        self.assertFalse(self.db(lambda: self.employee.__class__.objects.get(pk=self.employee.pk).is_active))
