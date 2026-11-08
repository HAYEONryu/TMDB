from scripts.verification_evidence import artifact_path
import json,os
from datetime import timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from django.utils import timezone
from playwright.sync_api import sync_playwright,expect
from apps.accounts.models import User
from apps.assignments.services import change_assignee
from apps.customers.models import Customer,CustomerDeletionRequest
from apps.customers.deletions import submit,approve
from apps.customers.services import update_row,trash_operation
from apps.operations.models import OperationEvent
from apps.sites.models import Site,GlobalSettings
from tests.helpers import STRONG_PASSWORD,user
from tests.test_p4 import Fixtures


class P7BrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.rows=self.customers(3)
        for row in self.rows:self.assign(row)
        self.admin2=user('01000000004',role='ADMIN',initial=False,name='가상관리자나');self.errors=[];self.external=[];self.requests=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.playwright=sync_playwright().start();self.browser=self.playwright.chromium.launch();self.context=self.browser.new_context(viewport={'width':1440,'height':960});self.watch(self.context);self.page=self.context.new_page();self.login(self.page,self.employee)
    def watch(self,context):
        context.on('page',lambda page:page.on('pageerror',lambda error:self.errors.append(str(error))))
        context.on('request',lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
        context.on('request',lambda request:self.requests.append((request.url,request.post_data_json)) if request.method=='POST' and any(part in request.url for part in ['deletion-request','/approve','hard-delete']) else None)
    def tearDown(self):
        self.browser.close();self.playwright.stop();self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()
    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def login(self,page,account):
        page.context.clear_cookies();page.goto(self.live_server_url+'/auth/login');page.get_by_label('전화번호',exact=True).fill(account.phone_normalized);page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);page.get_by_role('button',name='로그인',exact=True).click();expect(page).to_have_url(self.live_server_url+('/app/admin' if account.role=='ADMIN' else '/app/employee'))
    def open(self,page=None,view='mine'):
        page=page or self.page;page.goto(self.live_server_url+f'/app/employee/{view}?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 3건')
    def row(self,customer=None,page=None):return (page or self.page).locator('#employee-grid .tabulator-row').filter(has_text=(customer or self.rows[0]).customer_name)
    def edit(self,value,customer=None,page=None):
        page=page or self.page;cell=self.row(customer,page).locator('[tabulator-field="notes"]');cell.dblclick();cell.locator('textarea').fill(value);page.locator('h1').click();expect(page.locator('#queue-status')).to_contain_text('저장 대기')
    def request_body(self,customer=None):
        c=customer or self.rows[0];return {'assignment_id':str(c.current_assignment_id),'expected_version':c.version,'idempotency_key':str(uuid4())}
    def submit_server(self,customer=None):
        c=customer or self.rows[0];return self.db(lambda:submit(self.employee,c.pk,self.request_body(c))[0])
    def admin_page(self,account=None):
        context=self.browser.new_context(viewport={'width':1440,'height':960});self.watch(context);page=context.new_page();self.login(page,account or self.admin);return context,page
    def submit_ui(self,page=None,customer=None):
        page=page or self.page;page.once('dialog',lambda dialog:dialog.accept());self.row(customer,page).get_by_role('button',name='삭제 요청',exact=True).click();expect(self.row(customer,page).get_by_role('button',name='요청완료',exact=True)).to_be_disabled()

    def test_row_request_saves_only_target_and_keeps_editing_until_approval(self):
        self.open(view='today');self.edit('다른 행 대기',self.rows[1]);self.edit('삭제 요청 전 가상 상담');self.submit_ui();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기 1행')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[1].pk).notes),'');self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).notes),'삭제 요청 전 가상 상담');self.assertIsNone(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).deleted_at))
        self.edit('승인 전 추가 가상 상담');self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨');self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).notes),'승인 전 추가 가상 상담');self.assertEqual(self.page.locator('#employee-grid input[type=checkbox]').count(),0)

    def test_cancel_confirmation_and_offline_save_do_not_submit(self):
        self.open();self.page.once('dialog',lambda dialog:dialog.dismiss());self.row().get_by_role('button',name='삭제 요청',exact=True).click();self.assertEqual(self.requests,[])
        self.context.set_offline(True);self.edit('오프라인 가상 변경');self.row().get_by_role('button',name='삭제 요청',exact=True).click();expect(self.page.locator('#employee-message')).to_contain_text('삭제 요청을 제출하지 않았습니다');self.assertEqual(self.db(lambda:CustomerDeletionRequest.objects.count()),0)

    def test_lost_request_response_same_key_reload_and_other_tab_pending(self):
        self.open();page=self.page
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        page.route('**/deletion-request',lose,times=1);page.once('dialog',lambda dialog:dialog.accept());self.row().get_by_role('button',name='삭제 요청',exact=True).click();expect(page.locator('#deletion-pending')).to_be_visible();self.assertEqual(self.row().get_by_role('button',name='요청완료',exact=True).count(),0)
        page.once('dialog',lambda dialog:dialog.accept());page.reload();expect(page.locator('#deletion-pending')).to_be_visible();page.locator('#deletion-retry').click();expect(page.locator('#deletion-pending')).not_to_be_visible();expect(self.row().get_by_role('button',name='요청완료',exact=True)).to_be_disabled();self.assertEqual(self.requests[0][1],self.requests[1][1]);self.assertEqual(self.db(lambda:CustomerDeletionRequest.objects.count()),1)
        second=self.context.new_page();self.open(second);expect(self.row(page=second).get_by_role('button',name='요청완료',exact=True)).to_be_disabled();second.close()

    def test_approval_global_list_lost_response_latest_notes_and_blocked_employee_queue(self):
        self.open();self.submit_ui();admin_context,admin=self.admin_page();expect(admin.locator('#delete-request-count')).to_have_text('고객정보 삭제 요청 1건');admin.locator('#default-site').select_option(str(self.second.pk));expect(admin.locator('#delete-request-rows')).to_contain_text(self.site.name)
        customer=self.db(lambda:Customer.objects.get(pk=self.rows[0].pk));self.db(lambda:update_row(self.employee,self.mutation(customer,'승인 직전 최신 가상 상담')))
        self.edit('승인 후 거부할 미전송 변경')
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        admin.route('**/approve',lose,times=1);admin.once('dialog',lambda dialog:dialog.accept());admin.get_by_role('button',name='승인',exact=True).click();expect(admin.locator('#approval-pending')).to_be_visible();admin.reload();expect(admin.locator('#approval-pending')).to_be_visible();admin.locator('#approval-retry').click();expect(admin.locator('#approval-pending')).not_to_be_visible();expect(admin.locator('#delete-request-count')).to_have_text('고객정보 삭제 요청 0건')
        saved=self.db(lambda:Customer.objects.get(pk=customer.pk));self.assertTrue(saved.notes.startswith('승인 직전 최신 가상 상담\n['));self.assertEqual(saved.notes.count('고객요청으로 인한 삭제'),1)
        self.page.locator('#save-now').click();expect(self.page.locator('#pending-rows')).to_contain_text('전송 불가');expect(self.row()).to_have_count(0);self.assertEqual(self.db(lambda:Customer.objects.get(pk=customer.pk).notes),saved.notes)
        admin.screenshot(path=str(self.evidence/'p7-approval-desktop.png'),full_page=True);admin_context.close()

    def test_notifications_poll_once_per_visible_minute_and_on_return(self):
        self.submit_server();context,page=self.admin_page();expect(page.locator('#delete-request-count')).to_contain_text('1건');calls=[];page.on('request',lambda request:calls.append(request.url) if '/api/deletion-requests?' in request.url else None);page.clock.install();page.reload();expect(page.locator('#delete-request-count')).to_contain_text('1건');calls.clear()
        with page.expect_request(lambda request:'/api/deletion-requests?' in request.url):page.clock.run_for(61000)
        expect(page.locator('#deletion-notifications')).to_have_attribute('aria-busy','false');self.assertEqual(len(calls),1);page.evaluate("()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));}");page.clock.run_for(65000);self.assertEqual(len(calls),1)
        with page.expect_request(lambda request:'/api/deletion-requests?' in request.url):page.evaluate("()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'));}")
        expect(page.locator('#delete-request-count')).to_contain_text('1건');page.set_viewport_size({'width':390,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390);page.screenshot(path=str(self.evidence/'p7-notifications-mobile.png'),full_page=True);context.close()

    def test_trash_single_hard_delete_lost_response_replay(self):
        self.db(lambda:trash_operation(self.admin,{'customer_ids':[str(self.rows[0].pk)],'site_id':str(self.site.pk),'idempotency_key':str(uuid4())}));context,page=self.admin_page();page.goto(self.live_server_url+f'/app/admin/trash?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 1건');page.get_by_role('button',name='영구 삭제',exact=True).click();expect(page.locator('#hard-message')).to_contain_text('되돌릴 수 없습니다')
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        page.route('**/hard-delete',lose,times=1);page.locator('#hard-confirm').click();expect(page.locator('#hard-pending')).to_be_visible();self.assertFalse(self.db(lambda:Customer.objects.filter(pk=self.rows[0].pk).exists()))
        page.once('dialog',lambda dialog:dialog.accept());page.reload();expect(page.locator('#hard-pending')).to_be_visible();page.locator('#hard-retry').click();expect(page.locator('#hard-pending')).not_to_be_visible();expect(page.locator('#page-info')).to_contain_text('검색 0건');hard=[body for url,body in self.requests if '/hard-delete' in url];self.assertEqual(hard[0],hard[1]);context.close()

    def test_site_exact_name_confirmation_and_private_retry_payload(self):
        context,page=self.admin_page();page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 3건');page.locator('#delete-site').click();page.locator('#hard-name').fill(self.site.name+' ');page.locator('#hard-confirm').click();expect(page.locator('#hard-error')).to_contain_text('정확히');self.assertTrue(self.db(lambda:Site.objects.filter(pk=self.site.pk).exists()))
        page.locator('#hard-name').fill(self.site.name)
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        page.route('**/hard-delete',lose,times=1);page.locator('#hard-confirm').click();expect(page.locator('#hard-pending')).to_be_visible();metadata=page.evaluate('JSON.stringify(sessionStorage)');self.assertNotIn(self.site.name,metadata);self.assertIn('confirmation',metadata);self.assertFalse(self.db(lambda:Site.objects.filter(pk=self.site.pk).exists()))
        page.locator('#hard-retry').click();expect(page.locator('#hard-pending')).not_to_be_visible();expect(page.locator('#site')).to_have_value(str(self.second.pk));self.assertEqual(self.db(lambda:GlobalSettings.objects.get().default_site_id),self.second.pk);page.reload();expect(page.locator('#site')).to_have_value(str(self.second.pk));expect(page.locator('#page-info')).to_contain_text('검색 0건');page.set_viewport_size({'width':390,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390);page.screenshot(path=str(self.evidence/'p7-site-deleted-mobile.png'),full_page=True);context.close()
