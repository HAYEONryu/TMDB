import os
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright, expect

from apps.accounts.models import User
from tests.helpers import STRONG_PASSWORD, user


class LoginBrowserTests(StaticLiveServerTestCase):
    """Explicit browser entry point; uses Django's separate PostgreSQL test DB."""

    def test_admin_employee_first_change_reset_and_mobile_login(self):
        admin = user(role=User.Role.ADMIN, name="가상관리자")
        employee = user("01000000002", name="가상직원")
        evidence = Path(settings.BASE_DIR) / ".local/qa"
        evidence.mkdir(parents=True, exist_ok=True)
        errors, external_requests = [], []
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))

        def login_page(page, account, password="dodream"):
            page.goto(self.live_server_url + "/auth/login")
            page.get_by_label("전화번호", exact=True).fill(account.phone_normalized)
            page.get_by_label("비밀번호", exact=True).fill(password)
            page.get_by_role("button", name="로그인", exact=True).click()

        def change(page, password=STRONG_PASSWORD):
            expect(page.get_by_role("heading", name="비밀번호 변경", exact=True)).to_be_visible()
            page.get_by_label("현재 비밀번호", exact=True).fill("dodream")
            page.get_by_label("새 비밀번호", exact=True).fill(password)
            page.get_by_label("새 비밀번호 확인", exact=True).fill(password)
            page.get_by_role("button", name="비밀번호 변경", exact=True).click()

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                admin_context = browser.new_context(viewport={"width": 1440, "height": 960})
                employee_context = browser.new_context(viewport={"width": 1440, "height": 960})
                other_context = browser.new_context()
                for context in [admin_context, employee_context, other_context]:
                    context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
                    context.on("request", lambda request: external_requests.append(request.url) if urlsplit(request.url).hostname not in ["localhost", "127.0.0.1"] else None)
                admin_page, employee_page = admin_context.new_page(), employee_context.new_page()
                admin_page.goto(self.live_server_url + "/auth/login")
                expect(admin_page.get_by_role("heading", name="로그인", exact=True)).to_be_visible()
                self.assertEqual(admin_context.request.get(self.live_server_url + "/static/vendor/bootstrap.min.css").status, 200)
                admin_page.screenshot(path=str(evidence / "login-desktop.png"), full_page=True)
                login_page(admin_page, admin)
                expect(admin_page).to_have_url(self.live_server_url + "/auth/password")
                self.assertEqual(admin_context.request.get(self.live_server_url + "/api/access/admin").status, 403)
                admin_page.screenshot(path=str(evidence / "first-password.png"), full_page=True)
                change(admin_page)
                expect(admin_page).to_have_url(self.live_server_url + "/app/admin")
                self.assertEqual(admin_context.request.get(self.live_server_url + "/api/access/admin").status, 200)
                admin_page.screenshot(path=str(evidence / "admin-home.png"), full_page=True)

                login_page(employee_page, employee)
                self.assertEqual(employee_context.request.get(self.live_server_url + "/api/access/employee").status, 403)
                change(employee_page)
                expect(employee_page).to_have_url(self.live_server_url + "/app/employee")
                self.assertEqual(employee_context.request.get(self.live_server_url + "/api/access/employee").status, 200)
                self.assertEqual(employee_context.request.get(self.live_server_url + "/api/access/admin").status, 403)
                employee_page.screenshot(path=str(evidence / "employee-home.png"), full_page=True)
                other_page = other_context.new_page()
                login_page(other_page, employee, STRONG_PASSWORD)
                expect(other_page).to_have_url(self.live_server_url + "/app/employee")
                csrf = next(c["value"] for c in admin_context.cookies() if c["name"] == "csrftoken")
                response = admin_context.request.post(self.live_server_url + f"/api/users/{employee.pk}/reset-password", headers={"X-CSRFToken": csrf})
                self.assertEqual(response.status, 200)
                self.assertEqual(employee_context.request.get(self.live_server_url + "/api/me").status, 401)
                self.assertEqual(other_context.request.get(self.live_server_url + "/api/me").status, 401)
                login_page(employee_page, employee)
                expect(employee_page).to_have_url(self.live_server_url + "/auth/password")
                change(employee_page, "Autumn!Cloud2026")
                expect(employee_page).to_have_url(self.live_server_url + "/app/employee")

                mobile = browser.new_context(viewport={"width": 390, "height": 844})
                page = mobile.new_page()
                page.goto(self.live_server_url + "/auth/login")
                expect(page.get_by_role("heading", name="로그인", exact=True)).to_be_visible()
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
                page.screenshot(path=str(evidence / "login-mobile.png"), full_page=True)
                self.assertEqual(errors, [])
                self.assertEqual(external_requests, [])
            finally:
                browser.close()
