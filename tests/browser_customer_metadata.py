import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from playwright.sync_api import sync_playwright, expect

from apps.customers.models import Customer
from apps.imports.excel import HEADERS
from tests.browser_observation import BrowserObservation
from tests.helpers import STRONG_PASSWORD
from tests.test_imports import workbook
from tests.test_p4 import Fixtures


class CustomerMetadataBrowserTests(Fixtures, StaticLiveServerTestCase):
    def setUp(self):
        self.prepare()
        self.errors=[];self.external=[]
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.playwright=sync_playwright().start();self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch();self.addCleanup(self.browser.close)
        self.context=self.browser.new_context(viewport={'width':1440,'height':960})
        self.addCleanup(self.context.close)
        self.observation=BrowserObservation(self.context,self.live_server_url+'/healthz',self.server_thread)
        self.addCleanup(self.observation.finish)
        self.context.on('page',lambda page:page.on('pageerror',lambda error:self.errors.append(type(error).__name__)))
        self.context.on('request',lambda request:self.external.append(urlsplit(request.url).scheme) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
        self.page=self.context.new_page()

    def db(self, action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()

    def login(self, account):
        self.context.clear_cookies()
        page=self.page
        page.goto(self.live_server_url+'/auth/login')
        page.get_by_label('전화번호',exact=True).fill(account.phone_normalized)
        page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD)
        page.get_by_role('button',name='로그인',exact=True).click()
        expect(page).to_have_url(self.live_server_url+('/app/admin' if account.role=='ADMIN' else '/app/employee'))

    def edit(self, grid, field, value):
        cell=self.page.locator(f'#{grid} .tabulator-row [tabulator-field="{field}"]').first
        cell.dblclick()
        cell.locator('input,textarea').fill(value)
        self.page.locator('h1').click()

    def test_six_column_phone_only_import_admin_and_employee_fields_save_and_private_history(self):
        self.login(self.admin)
        page=self.page
        page.goto(self.live_server_url+'/app/admin/imports')
        page.locator('#upload-site').select_option(str(self.site.pk))
        data=workbook([[None,'01090000008','서울','전세','가상 등록 비고','SYNTHETIC_PRIVATE_BROWSER']],headers=HEADERS)
        page.locator('#upload-file').set_input_files({'name':'synthetic-six.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':data})
        page.locator('#validate-file').click()
        expect(page.locator('#commit-upload')).to_be_enabled()
        page.locator('#commit-upload').click();page.locator('#commit-confirm').click()
        expect(page.locator('#commit-summary')).to_contain_text('1개 업로드를 성공')
        page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.site.pk}')
        expect(page.locator('#page-info')).to_contain_text('1건')
        for field,value in [('route','소개'),('memo','관리자가 수정한 일반 비고'),('admin_notes','SYNTHETIC_PRIVATE_BROWSER updated')]:
            self.edit('customer-grid',field,value)
        page.locator('#save').click()
        expect(page.locator('#message')).to_have_text('저장했습니다.')
        customer=self.db(lambda:Customer.objects.get(phone_normalized='01090000008'))
        self.assertEqual((customer.customer_name,customer.notes,customer.route,customer.memo,customer.admin_notes),('','','소개','관리자가 수정한 일반 비고','SYNTHETIC_PRIVATE_BROWSER updated'))
        self.db(lambda:self.assign(customer))
        self.login(self.employee)
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        self.assertEqual(page.locator('#employee-grid [tabulator-field="admin_notes"]').count(),0)
        response=self.context.request.get(self.live_server_url+f'/api/customers?site_id={self.site.pk}').text()
        self.assertNotIn('admin_notes',response)
        self.assertNotIn('SYNTHETIC_PRIVATE_BROWSER',response)
        for field,value in [('route','온라인'),('memo','직원이 수정한 일반 비고')]:
            self.edit('employee-grid',field,value)
        page.locator('#save-now').click()
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        customer=self.db(lambda:Customer.objects.get(pk=customer.pk))
        self.assertEqual((customer.route,customer.memo,customer.notes,customer.admin_notes),('온라인','직원이 수정한 일반 비고','','SYNTHETIC_PRIVATE_BROWSER updated'))
        page.get_by_role('button',name='상담·재콜 이력',exact=True).click()
        page.locator('#history-kind').select_option('consultations')
        expect(page.locator('#history-content')).to_contain_text('비고')
        self.assertNotIn('SYNTHETIC_PRIVATE_BROWSER',page.locator('#history-content').inner_text())
        self.assertNotIn('관리자 비고',page.locator('#history-content').inner_text())
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
