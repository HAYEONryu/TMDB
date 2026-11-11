import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from playwright.sync_api import sync_playwright, expect

from apps.customers.models import Customer
from apps.customers.services import update_row
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
        cell.click()
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

    def test_requested_column_order_admin_identity_edit_and_staff_readonly_identity(self):
        customer=self.db(lambda:Customer.objects.create(site=self.site,customer_name='가상 원본',
            phone_normalized='01094000001',admin_notes='SYNTHETIC_PRIVATE_GRID'))
        self.db(lambda:self.assign(customer))
        page=self.page;self.login(self.admin)
        page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.site.pk}')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        fields=['customer_name','phone_normalized','contract_status','admin_notes','assignee_name',
                'call_result','notes','callback_due_at','visit_at','residence','housing_status','route','memo','assigned_at','_actions','_status']
        labels=['고객명','연락처','계약여부','관리자 비고','담당직원명','통화결과','상담내용','재콜일정',
                '방문예약 날짜','고객 거주지','주택상황','루트','비고','할당일','작업','저장상태']
        def header(grid):
            return page.locator(f'#{grid} .tabulator-header .tabulator-col[tabulator-field]').evaluate_all(
                "cells=>cells.filter(c=>c.getAttribute('tabulator-field')).map(c=>[c.getAttribute('tabulator-field'),c.querySelector('.tabulator-col-title').textContent.replace('▾','').trim()])")
        self.assertEqual(header('customer-grid'),list(map(list,zip(fields,labels))))
        self.edit('customer-grid','customer_name','가상 정정')
        self.edit('customer-grid','phone_normalized','010-9400-0002')
        self.edit('customer-grid','notes','관리자 상담 입력')
        self.edit('customer-grid','admin_notes','SYNTHETIC_PRIVATE_GRID updated')
        page.locator('#customer-grid .tabulator-row [tabulator-field="contract_status"]').first.click()
        page.get_by_text('계약',exact=True).click()
        page.locator('#save').click();expect(page.locator('#message')).to_have_text('저장했습니다.')
        current=self.db(lambda:Customer.objects.get(pk=customer.pk))
        self.assertEqual((current.customer_name,current.phone_normalized,current.contract_status,current.notes),
                         ('가상 정정','01094000002','CONTRACTED','관리자 상담 입력'))
        self.login(self.employee)
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        self.assertEqual(header('employee-grid'),[[field,label] for field,label in zip(fields,labels) if field!='admin_notes'])
        for field in ['customer_name','phone_normalized','assignee_name','assigned_at']:
            cell=page.locator(f'#employee-grid .tabulator-row [tabulator-field="{field}"]').first
            cell.click();expect(cell.locator('input,textarea,select')).to_have_count(0)
        self.assertEqual(page.locator('#employee-grid [tabulator-field="admin_notes"]').count(),0)
        response=self.context.request.get(self.live_server_url+f'/api/customers?site_id={self.site.pk}').text()
        self.assertNotIn('admin_notes',response);self.assertNotIn('SYNTHETIC_PRIVATE_GRID',response)
        self.edit('employee-grid','notes','직원 상담 입력')
        page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=customer.pk).notes),'직원 상담 입력')
        self.edit('employee-grid','notes','정정 전 직원 대기')
        def correct_again():
            row=Customer.objects.get(pk=customer.pk)
            return update_row(self.admin,dict(customer_id=str(row.pk),assignment_id=str(row.current_assignment_id),
                mutation_id=str(uuid4()),expected_version=row.version,
                changes={'customer_name':'가상 재정정','phone_normalized':'01094000003'}))
        self.assertTrue(self.db(correct_again)['ok'])
        page.locator('#save-now').click();expect(page.locator('#pending-rows')).to_contain_text('충돌')
        page.get_by_role('button',name='비교·확인',exact=True).click()
        expect(page.locator('#conflict-message')).to_contain_text('가상 재정정')
        expect(page.locator('#conflict-message')).to_contain_text('010-9400-0003')
        self.assertNotIn('SYNTHETIC_PRIVATE_GRID',page.locator('#conflict-message').inner_text())
        page.once('dialog',lambda dialog:dialog.accept());page.locator('#employee-discard').click()
        expect(page.locator('#employee-grid .tabulator-row [tabulator-field="customer_name"]').first).to_have_text('가상 재정정')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=customer.pk).notes),'직원 상담 입력')
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
