"""Real local Caddy TLS, desktop engines and touch-viewport queue recovery."""
from scripts.verification_evidence import artifact_path

import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
from urllib.parse import urlsplit
import urllib.request
import urllib.error

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import sync_playwright, expect
from tests.helpers import STRONG_PASSWORD
from tests.runtime_helpers import free_port, wait_http
from tests.test_p4 import Fixtures


@override_settings(SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https'), SECURE_HSTS_SECONDS=3600)
class P13HTTPSBrowserTests(Fixtures, StaticLiveServerTestCase):
    def setUp(self):
        self.prepare(); self.customer=self.customers()[0]; self.assign(self.customer)
        self.directory=tempfile.TemporaryDirectory(prefix='tm-p13-tls-',dir='/private/tmp')
        self.addCleanup(self.directory.cleanup)
        root=Path(self.directory.name); cert=root/'cert.pem'; key=root/'key.pem'
        config=root/'openssl.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(config),'-keyout',str(key),'-out',str(cert)],capture_output=True,check=True,timeout=15)
        self.port=free_port(); self.http_port=free_port(); self.origin=f'https://localhost:{self.port}'
        self.override=override_settings(CSRF_TRUSTED_ORIGINS=[self.origin]); self.override.enable(); self.addCleanup(self.override.disable)
        caddy=root/'Caddyfile'
        caddy.write_text('{\n admin off\n auto_https off\n}\n'+self.origin+' {\n tls '+str(cert)+' '+str(key)+'\n reverse_proxy '+self.live_server_url+' {\n header_up X-Forwarded-Proto {scheme}\n }\n}\nhttp://localhost:'+str(self.http_port)+' {\n redir '+self.origin+'{uri} 308\n}\n')
        self.log=(root/'caddy.log').open('w')
        env={k:v for k,v in os.environ.items() if not k.startswith('AI_')}; env.update(XDG_DATA_HOME=str(root),XDG_CONFIG_HOME=str(root))
        self.proxy=subprocess.Popen([str(settings.BASE_DIR/'.local/bin/caddy'),'run','--config',str(caddy),'--adapter','caddyfile'],env=env,stdout=self.log,stderr=self.log)
        self.addCleanup(self.stop_proxy)
        context=ssl.create_default_context(cafile=str(cert))
        wait_http(self.origin+'/healthz',self.proxy,context=context)
        with urllib.request.urlopen(self.origin+'/healthz',context=context) as response:
            self.assertEqual(response.headers['Strict-Transport-Security'],'max-age=3600')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        request=urllib.request.Request(f'http://localhost:{self.http_port}/healthz',headers={'X-Forwarded-Proto':'https'})
        try:
            urllib.request.build_opener(NoRedirect()).open(request,timeout=5)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code,308); self.assertEqual(error.headers['Location'],self.origin+'/healthz')
        else:
            self.fail('Proxy accepted spoofed HTTPS header over HTTP')
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))

    def stop_proxy(self):
        if self.proxy.poll() is None: self.proxy.terminate()
        self.proxy.wait(timeout=15); self.log.close()

    def scenario(self,engine,mobile=False):
        with sync_playwright() as pw:
            browser=getattr(pw,engine).launch()
            options={'ignore_https_errors':True,'viewport':{'width':390 if mobile else 1440,'height':844 if mobile else 960}}
            if mobile: options.update(is_mobile=True,has_touch=True)
            context=browser.new_context(**options);page=context.new_page();errors=[];external=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:external.append(request.url) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
            page.goto(self.origin+'/auth/login');page.get_by_label('전화번호',exact=True).fill(self.employee.phone_normalized);page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);page.get_by_role('button',name='로그인',exact=True).click();expect(page).to_have_url(self.origin+'/app/employee')
            cookies={cookie['name']:cookie for cookie in context.cookies()}
            self.assertTrue(cookies['sessionid']['secure']);self.assertTrue(cookies['sessionid']['httpOnly']);self.assertTrue(cookies['csrftoken']['secure'])
            page.goto(self.origin+f'/app/employee/mine?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 1건')
            row=page.locator('#employee-grid .tabulator-row').first
            cell=row.locator('[tabulator-field="notes"]');cell.dblclick();cell.locator('textarea').fill('HTTPS '+engine+' 가짜 상담');page.locator('h1').click()
            page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
            context.set_offline(True)
            cell.dblclick();cell.locator('textarea').fill('오프라인 복구 '+engine);page.locator('h1').click();page.locator('#save-now').click();expect(page.locator('#employee-message')).to_contain_text('저장하지 못한 행')
            context.set_offline(False);page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
            page.once('dialog',lambda dialog:dialog.accept());page.reload();expect(row).to_contain_text('오프라인 복구 '+engine)
            self.assertEqual(page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)
            # HTTPS-only cookies and a genuine TLS hop are exercised above; no public CA or real mobile is claimed.
            self.assertEqual(errors,[]);self.assertEqual(external,[])
            evidence={'engine':engine,'mobile_viewport':mobile,'real_device':False,'tls_verified_with_ephemeral_ca':True,
                'secure_cookies':True,'save_and_offline_recovery':True,'javascript_errors':0}
            path=artifact_path(f'p13-{engine}{"-touch" if mobile else ""}.json');path.write_text(json.dumps(evidence,indent=2))
            context.close();browser.close()

    def test_chromium_https_save_and_offline_recovery(self): self.scenario('chromium')
    def test_firefox_https_save_and_offline_recovery(self): self.scenario('firefox')
    def test_webkit_https_save_and_offline_recovery(self): self.scenario('webkit')
    def test_webkit_touch_https_save_and_offline_recovery(self): self.scenario('webkit',mobile=True)
