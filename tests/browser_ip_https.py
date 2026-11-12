"""Local Caddy TLS transport only: no public certificate or external API request."""
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class IPHttpsBrowserTests(Fixtures, StaticLiveServerTestCase):
    def test_local_tls_proxy_enables_secure_browser_employee_save(self):
        self.prepare()
        self.assign(self.customers(site=self.second)[0])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        port = available_port()
        origin = f"https://127.0.0.1:{port}"
        override = override_settings(
            ALLOWED_HOSTS=["127.0.0.1", "localhost"], CSRF_TRUSTED_ORIGINS=[origin],
            SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
            SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
        )
        override.enable()
        self.addCleanup(override.disable)
        path = Path(directory.name) / "Caddyfile"
        # Internal CA and high loopback port are deliberately test-only. Never
        # trust this CA globally and never contact ACME during verification.
        source = (settings.BASE_DIR / "deploy/Caddyfile.ip-https").read_text()
        source = source.replace("admin off", "admin off\n\tskip_install_trust\n\tauto_https disable_redirects")
        source = source.replace("https://{$TM_HTTPS_IP}", origin)
        source = source.replace("issuer acme https://acme-v02.api.letsencrypt.org/directory {\n\t\t\tprofile shortlived\n\t\t}", "issuer internal")
        source = source.replace("web:8000", self.live_server_url.removeprefix("http://"))
        path.write_text(source)
        process = subprocess.Popen([
            str(settings.BASE_DIR / ".local/bin/caddy"), "run", "--config", str(path), "--adapter", "caddyfile",
        ], env={**os.environ, "TM_HTTPS_IP": "127.0.0.1", "XDG_DATA_HOME": directory.name + "/data",
                "XDG_CONFIG_HOME": directory.name + "/config"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def stop():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.addCleanup(stop)
        ready = False
        for _ in range(60):
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(origin + "/healthz", context=ssl._create_unverified_context(), timeout=1) as response:
                    ready = response.status == 200
                if ready:
                    break
            except (OSError, ValueError):
                time.sleep(0.1)
        self.assertTrue(ready, "local TLS proxy failed to become ready")
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.BASE_DIR / ".cache/ms-playwright"))
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        # This bypass is exclusively for our synthetic local CA. The server's
        # final public certificate must pass verification WITHOUT a bypass.
        context = browser.new_context(ignore_https_errors=True)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.goto(origin + "/auth/login")
        page.get_by_label("전화번호", exact=True).fill(self.employee.phone_normalized)
        page.get_by_label("비밀번호", exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button", name="로그인", exact=True).click()
        expect(page).to_have_url(origin + "/app/employee")
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#dashboard-summary .overview-metric').nth(2).locator('dd')).to_have_text('1건')
        page.locator('.workspace-nav').get_by_role('link',name='오늘 할 일',exact=True).click()
        expect(page.locator('#site')).to_have_value(str(self.second.pk))
        expect(page.locator("#page-info")).to_contain_text("검색 1건")
        expect(page.locator("#employee-message")).to_be_empty()
        self.assertTrue(page.evaluate("isSecureContext && !!crypto.subtle && !!navigator.locks"))
        name=page.locator('.tabulator-row [tabulator-field="customer_name"]').first
        name.click();name.locator('input').fill('가상 HTTPS 이름 정정');page.locator('h1').click()
        cell = page.locator('.tabulator-row [tabulator-field="notes"]').first
        cell.dblclick()
        cell.locator("textarea").fill("가상 HTTPS 저장")
        page.locator("h1").click()
        expect(page.locator("#queue-status")).to_contain_text("저장 대기")
        with page.expect_response("**/api/employee/batch-update") as response:
            page.locator("#save-now").click()
        self.assertEqual(response.value.status, 200)
        self.assertEqual(response.value.request.post_data_json['rows'][0]['changes']['customer_name'],'가상 HTTPS 이름 정정')
        expect(page.locator("#queue-status")).to_have_text("모든 변경 저장됨")
        self.assertEqual(errors, [])
