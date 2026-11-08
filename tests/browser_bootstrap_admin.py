import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from playwright.sync_api import expect, sync_playwright

from apps.accounts.bootstrap import ensure_initial_admin
from tests.helpers import STRONG_PASSWORD


class BootstrapAdminBrowserTests(StaticLiveServerTestCase):
    def test_initial_login_password_change_and_user_management(self):
        ensure_initial_admin()
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        page = browser.new_page()
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.on("request", lambda request: external.append(True)
                if urlsplit(request.url).hostname not in {"localhost", "127.0.0.1"} else None)
        page.goto(self.live_server_url + "/auth/login")
        page.get_by_label("아이디 또는 전화번호", exact=True).fill("admin")
        page.get_by_label("비밀번호", exact=True).fill("admin123")
        page.get_by_role("button", name="로그인", exact=True).click()
        expect(page).to_have_url(self.live_server_url + "/auth/password")
        page.get_by_label("현재 비밀번호", exact=True).fill("admin123")
        page.get_by_label("새 비밀번호", exact=True).fill(STRONG_PASSWORD)
        page.get_by_label("새 비밀번호 확인", exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button", name="비밀번호 변경", exact=True).click()
        expect(page).to_have_url(self.live_server_url + "/app/admin")
        page.goto(self.live_server_url + "/app/admin/users")
        row = page.locator("#user-rows tr").first
        expect(row.get_by_label("최초 관리자 아이디", exact=True)).to_have_value("admin")
        expect(row.get_by_label("최초 관리자 아이디", exact=True)).to_be_disabled()
        expect(row.get_by_label("관리자", exact=True)).to_be_disabled()
        row.get_by_label("이름", exact=True).fill("최초관리자수정")
        page.get_by_role("button", name="저장", exact=True).click()
        page.get_by_role("button", name="저장 확인", exact=True).click()
        expect(page.locator("#user-message")).to_contain_text("1명 저장")
        expect(page.locator("#user-rows tr").first.get_by_label("이름", exact=True)).to_have_value("최초관리자수정")
        def bootstrap():
            close_old_connections()
            try:
                return ensure_initial_admin()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as executor:
            self.assertFalse(executor.submit(bootstrap).result())
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
