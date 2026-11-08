import os
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.accounts.models import User
from tests.helpers import STRONG_PASSWORD, user


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver", "tm-http.test"])
class RequestIdBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = user(role=User.Role.ADMIN, initial=False)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        self.browser = playwright.chromium.launch(args=[
            "--host-resolver-rules=MAP tm-http.test 127.0.0.1", "--proxy-bypass-list=*",
        ])
        self.addCleanup(self.browser.close)

    def run_user_flow(self, *, insecure):
        origin = self.live_server_url.replace("localhost", "tm-http.test") if insecure else self.live_server_url
        page = self.browser.new_page()
        self.addCleanup(page.close)
        errors, external, keys = [], [], []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        def observe(request):
            path = urlsplit(request.url)
            if path.hostname not in {"localhost", "127.0.0.1", "tm-http.test"}:
                external.append(True)
            if request.method == "POST" and (path.path in {"/api/users", "/api/users/batch-update"}
                                              or path.path.endswith("/reset-password")):
                keys.append(request.post_data_json.get("idempotency_key"))
        page.on("request", observe)
        page.goto(origin + "/auth/login")
        capabilities = page.evaluate("({secure:isSecureContext,uuid:typeof crypto.randomUUID,rng:typeof crypto.getRandomValues})")
        self.assertEqual(capabilities["secure"], not insecure)
        self.assertEqual(capabilities["uuid"], "undefined" if insecure else "function")
        self.assertEqual(capabilities["rng"], "function")
        page.get_by_label("전화번호", exact=True).fill(self.admin.phone_normalized)
        page.get_by_label("비밀번호", exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button", name="로그인", exact=True).click()
        expect(page).to_have_url(origin + "/app/admin")
        page.goto(origin + "/app/admin/users")
        expect(page.locator("#user-rows tr")).to_have_count(1)
        page.get_by_role("button", name="사용자 추가", exact=True).click()
        page.locator("#new-user-name").fill("가상신규직원")
        page.locator("#new-user-phone").fill("01000000002")
        page.get_by_role("button", name="추가", exact=True).click()
        expect(page.locator("#user-message")).to_contain_text("사용자를 추가했습니다")
        expect(page.locator("#user-rows tr")).to_have_count(2)
        row = page.locator("#user-rows tr").last
        expect(row.get_by_label("전화번호", exact=True)).to_have_value("01000000002")
        row.get_by_label("이름", exact=True).fill("가상수정직원")
        page.get_by_role("button", name="저장", exact=True).click()
        page.get_by_role("button", name="저장 확인", exact=True).click()
        expect(page.locator("#user-message")).to_contain_text("1명 저장")
        row = page.locator("#user-rows tr").last
        expect(row.get_by_label("이름", exact=True)).to_have_value("가상수정직원")
        row.get_by_role("button", name="비밀번호 재설정", exact=True).click()
        page.get_by_role("button", name="재설정", exact=True).click()
        expect(page.locator("#user-message")).to_contain_text("초기 비밀번호로 재설정했습니다")
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)
        for key in keys:
            self.assertRegex(key, re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
        self.assertEqual(errors, [])
        self.assertEqual(external, [])

    def test_user_create_edit_reset_on_insecure_http(self):
        self.run_user_flow(insecure=True)

    def test_user_create_edit_reset_with_native_random_uuid(self):
        self.run_user_flow(insecure=False)
