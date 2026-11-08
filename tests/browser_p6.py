from scripts.verification_evidence import artifact_path
import os
from datetime import datetime,time,timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from django.utils import timezone
from playwright.sync_api import sync_playwright,expect
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import update_row,trash_operation
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures


class P6BrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.rows=self.customers(3)
        for row in self.rows:self.assign(row)
        Assignment.objects.filter(pk=self.rows[0].current_assignment_id).update(assigned_at=timezone.now()-timedelta(days=1))
        self.callback=Callback.objects.create(customer=self.rows[0],due_at=timezone.now()-timedelta(hours=1),created_by=self.employee,updated_by=self.employee)
        self.errors=[];self.external=[];self.sent=[];self.completions=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.playwright=sync_playwright().start();self.browser=self.playwright.chromium.launch();self.context=self.browser.new_context(viewport={'width':1440,'height':960})
        self.context.on('page',lambda page:page.on('pageerror',lambda error:self.errors.append(str(error))))
        self.context.on('request',lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
        self.context.on('request',lambda request:self.sent.append(request.post_data_json) if request.url.endswith('/api/employee/batch-update') else None)
        self.context.on('request',lambda request:self.completions.append(request.post_data_json) if request.url.endswith('/callback-complete') else None)
        self.page=self.context.new_page();self.login(self.employee)
    def tearDown(self):
        self.browser.close();self.playwright.stop();self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()
    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def login(self,account):
        self.context.clear_cookies();page=self.page;page.goto(self.live_server_url+'/auth/login');page.get_by_label('아이디 또는 전화번호',exact=True).fill(account.phone_normalized);page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);page.get_by_role('button',name='로그인',exact=True).click();expect(page).to_have_url(self.live_server_url+('/app/admin' if account.role=='ADMIN' else '/app/employee'))
    def open(self,view='mine'):
        self.page.goto(self.live_server_url+f'/app/employee/{view}?site_id={self.site.pk}');expect(self.page.locator('#page-info')).to_contain_text('검색 3건')
    def row(self,customer=None):return self.page.locator('#employee-grid .tabulator-row').filter(has_text=(customer or self.rows[0]).customer_name)
    def edit(self,value,customer=None):
        cell=self.row(customer).locator('[tabulator-field="notes"]');cell.dblclick();cell.locator('textarea').fill(value);self.page.locator('h1').click();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기')
    def completed(self):expect(self.page.locator('#employee-message')).to_have_text('재콜을 완료했습니다.')

    def test_complete_saves_row_first_leaves_today_and_preserves_history(self):
        page=self.page;self.open('today');self.edit('완료 전 가상 상담 저장');self.row().get_by_role('button',name='재콜 완료',exact=True).click();self.completed();expect(page.locator('#page-info')).to_contain_text('검색 2건')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).notes),'완료 전 가상 상담 저장');self.assertEqual(self.db(lambda:Callback.objects.get(pk=self.callback.pk).status),'COMPLETED');self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),2)
        self.open();self.row().get_by_role('button',name='상담·재콜 이력',exact=True).click();expect(page.locator('#history-content')).to_contain_text('완료');expect(page.locator('#history-content')).to_contain_text(self.employee.name)
        page.locator('#history-kind').select_option('consultations');expect(page.locator('#history-page')).to_contain_text('전체 2건');expect(page.locator('#history-content')).to_contain_text('완료 전 가상 상담 저장');expect(page.locator('#history-content')).to_contain_text('재콜일정');page.screenshot(path=str(self.evidence/'p6-history-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390);box=page.locator('#history-dialog').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],390);page.screenshot(path=str(self.evidence/'p6-history-mobile.png'),full_page=True)

    def test_completion_flushes_only_target_and_other_row_remains_pending(self):
        self.open();self.edit('다른 행 가상 대기',self.rows[1]);self.edit('대상 행 가상 저장');self.row().get_by_role('button',name='재콜 완료',exact=True).click();self.completed();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기 1행')
        self.assertEqual(self.sent[0]['rows'][0]['customer_id'],str(self.rows[0].pk));self.assertEqual(len(self.sent[0]['rows']),1);self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[1].pk).notes),'')
        self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨');self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[1].pk).notes),'다른 행 가상 대기')

    def test_lost_completion_response_reload_retry_preserves_new_callback(self):
        self.open();page=self.page
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        page.route('**/callback-complete',lose,times=1);self.row().get_by_role('button',name='재콜 완료',exact=True).click();expect(page.locator('#callback-pending')).to_be_visible()
        customer=self.db(lambda:Customer.objects.get(pk=self.rows[0].pk));body=self.mutation(customer);body['changes']={'callback_due_at':(timezone.now()+timedelta(days=1)).isoformat()};self.db(lambda:update_row(self.employee,body))
        new=self.db(lambda:Callback.objects.get(customer=customer,status='PENDING'));page.once('dialog',lambda dialog:dialog.accept());page.reload();expect(page.locator('#callback-pending')).to_be_visible();page.locator('#callback-retry').click();self.completed()
        self.assertEqual(self.completions[0],self.completions[1]);self.assertEqual(self.db(lambda:Callback.objects.get(pk=new.pk).status),'PENDING');self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),2);expect(self.row().get_by_role('button',name='재콜 완료',exact=True)).to_be_enabled()

    def test_save_failure_blocks_completion_and_recall_rejects_old_assignment(self):
        self.open();self.context.set_offline(True);self.edit('오프라인 가상 상담');self.row().get_by_role('button',name='재콜 완료',exact=True).click();expect(self.page.locator('#employee-message')).to_contain_text('재콜은 완료하지 않았습니다');self.assertEqual(self.completions,[])
        self.context.set_offline(False);self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        customer=self.db(lambda:Customer.objects.get(pk=self.rows[0].pk));self.db(lambda:change_assignee(self.admin,customer.pk,self.assignee_body(customer)))
        self.row().get_by_role('button',name='재콜 완료',exact=True).click();expect(self.page.locator('#employee-message')).to_contain_text('할당이 변경');self.assertEqual(self.db(lambda:Callback.objects.get(pk=self.callback.pk).status),'PENDING')

    def test_dashboards_selected_site_manual_refresh_and_mobile(self):
        page=self.page;expect(page.locator('#dashboard-statistics')).to_contain_text('오늘 할당받은 고유 DB');expect(page.locator('#dashboard-statistics')).to_contain_text('오늘 재콜할 DB')
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk));expect(page.locator('#dashboard-statistics dd').first).to_have_text('0')
        page.locator('#employee-dashboard-site').select_option(str(self.site.pk));expect(page.locator('#dashboard-statistics dd').first).to_have_text('2');page.screenshot(path=str(self.evidence/'p6-employee-dashboard.png'),full_page=True)
        self.login(self.admin);expect(page.locator('#dashboard-statistics')).to_contain_text('오늘 할당 고유 DB');expect(page.locator('#dashboard-statistics')).to_contain_text('현재 보유 전체');before=self.db(lambda:__import__('apps.sites.models',fromlist=['GlobalSettings']).GlobalSettings.objects.get(pk=1).version)
        page.locator('#default-site').select_option(str(self.second.pk));page.locator('#dashboard-refresh').click();expect(page.locator('#site-counts')).to_contain_text('전체 DB 0');self.assertEqual(self.db(lambda:__import__('apps.sites.models',fromlist=['GlobalSettings']).GlobalSettings.objects.get(pk=1).version),before)
        page.locator('#default-site').select_option(str(self.site.pk));expect(page.locator(f'#dashboard-statistics tr[data-employee-id="{self.employee.pk}"] td').nth(1)).to_have_text('2');page.screenshot(path=str(self.evidence/'p6-admin-dashboard.png'),full_page=True);page.set_viewport_size({'width':390,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390);page.screenshot(path=str(self.evidence/'p6-admin-mobile.png'),full_page=True)

    def test_admin_completion_and_trash_history(self):
        self.login(self.admin);page=self.page;page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 3건')
        row=page.locator('#customer-grid .tabulator-row').filter(has_text=self.rows[0].customer_name);row.get_by_role('button',name='재콜 완료',exact=True).click();expect(page.locator('#message')).to_have_text('재콜을 완료했습니다.');self.assertEqual(self.db(lambda:Callback.objects.get(pk=self.callback.pk).completed_by_id),self.admin.pk)
        row.get_by_role('button',name='상담·재콜 이력',exact=True).click();expect(page.locator('#history-content')).to_contain_text(self.admin.name)
        page.locator('#history-dialog [data-close]').click();self.db(lambda:trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.rows[0].pk)],'idempotency_key':str(uuid4())}))
        page.goto(self.live_server_url+f'/app/admin/trash?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 1건');page.get_by_role('button',name='상담·재콜 이력',exact=True).click();expect(page.locator('#history-content')).to_contain_text(self.admin.name)

    def test_pre_recall_225930_flushes_visible_editor_before_normal_deadline(self):
        self.open();page=self.page;page.clock.install();self.edit('23시 전 가상 전송');future=datetime.combine(timezone.localdate(),time(22,59,29),KST);page.clock.set_system_time(future)
        with page.expect_request('**/api/employee/batch-update'):page.clock.run_for(2500)
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨');self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).notes),'23시 전 가상 전송')
