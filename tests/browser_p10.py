from scripts.verification_evidence import artifact_path
import json,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from django.test import override_settings
from playwright.sync_api import sync_playwright,expect
from apps.ai_assistant.models import AIRequest,AIQuotaBucket,AIUsageAttempt
from apps.ai_assistant.worker import run_once
from apps.assignments.services import change_assignee
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.services import update_row
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(AI_FOUNDATION_TEST_MODE=True,AI_CONFIG=TEST_AI)
class P10BrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.rows=self.customers(3)
        for row in self.rows:row.notes='가짜 최초 상담';row.save();self.assign(row)
        self.errors=[];self.external=[];self.posts=[];self.gets=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.playwright=sync_playwright().start();self.browser=self.playwright.chromium.launch();self.context=self.browser.new_context(viewport={'width':1440,'height':960});self.watch(self.context);self.page=self.context.new_page();self.login();self.open()
    def watch(self,context):
        context.on('page',lambda page:page.on('pageerror',lambda error:self.errors.append(str(error))))
        context.on('request',lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
        context.on('request',lambda request:self.posts.append(request.post_data_json) if request.url.endswith('/api/ai/customer-tasks') and request.method=='POST' else None)
        context.on('request',lambda request:self.gets.append(request.url) if '/api/ai/tasks/' in request.url and request.method=='GET' else None)
    def tearDown(self):
        self.browser.close();self.playwright.stop();self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()
    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def login(self):
        self.page.goto(self.live_server_url+'/auth/login');self.page.get_by_label('아이디 또는 전화번호',exact=True).fill(self.employee.phone_normalized);self.page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);self.page.get_by_role('button',name='로그인',exact=True).click();expect(self.page).to_have_url(self.live_server_url+'/app/employee')
    def open(self,view='mine'):
        self.page.goto(self.live_server_url+f'/app/employee/{view}?site_id={self.site.pk}');expect(self.page.locator('#page-info')).to_contain_text('검색 3건');expect(self.page.locator('#ai-availability')).to_contain_text('테스트 전용')
    def row(self,index=0):return self.page.locator('#employee-grid .tabulator-row').filter(has_text=self.rows[index].customer_name)
    def edit(self,value,index=0):
        cell=self.row(index).locator('[tabulator-field="notes"]');cell.dblclick();cell.locator('textarea').fill(value);self.page.locator('h1').click();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기')
    def worker_route(self,lose=False):
        def run(route):
            response=route.fetch();self.assertEqual(response.status,202);self.assertEqual(self.db(run_once)['succeeded'],1)
            if lose:route.abort('failed')
            else:route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',run,times=1)
    def generate(self,label='AI 상담 정리'):
        self.worker_route();self.row().get_by_role('button',name=label,exact=True).click();expect(self.page.locator('#ai-content')).to_contain_text('테스트 전용 가짜 응답')
    def choose_notes(self):
        self.page.get_by_label('상담기타내용(비고) 제안 선택',exact=True).check();self.page.once('dialog',lambda dialog:dialog.accept());self.page.locator('#ai-apply').click();expect(self.page.locator('#ai-result-message')).to_contain_text('저장 대기열에 반영')
    def close(self):self.page.locator('#ai-dialog [data-close]').click()

    def test_cleanup_saves_target_only_default_unselected_compare_select_and_real_save(self):
        self.open('today');self.edit('다른 행 미저장',1);self.edit('AI 요청 직전 가짜 상담');self.generate()
        expect(self.page.locator('#queue-status')).to_contain_text('저장 대기 1행');self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[1].pk).notes),'가짜 최초 상담')
        self.assertEqual(self.page.locator('#ai-content input:checked').count(),0);expect(self.page.locator('#ai-apply')).to_be_disabled();expect(self.page.locator('.ai-compare')).to_contain_text('AI 요청 직전 가짜 상담')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED').count()),0)
        self.page.screenshot(path=str(self.evidence/'p10-cleanup-desktop.png'),full_page=True)
        self.choose_notes();self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).notes),'AI 요청 직전 가짜 상담');self.close();self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED',source_ai_result__isnull=False).count()),1);self.assertEqual(self.db(lambda:AIQuotaBucket.objects.get().successful_count),1)

    def test_summary_questions_read_only_and_mobile_no_automatic_generation(self):
        self.generate('상담 요약');expect(self.page.locator('#ai-content')).to_contain_text('상담 핵심');expect(self.page.locator('#ai-apply')).to_be_hidden();self.close()
        self.generate('다음 질문 제안');expect(self.page.locator('#ai-content')).to_contain_text('목적:');expect(self.page.locator('#ai-apply')).to_be_hidden();self.page.set_viewport_size({'width':390,'height':844});self.page.screenshot(path=str(self.evidence/'p10-questions-mobile.png'),full_page=True)
        self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0);self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),0);self.assertEqual(len(self.posts),2)
        self.close();self.page.locator('#reload-rows').click();expect(self.page.locator('#page-info')).to_contain_text('검색 3건');self.assertEqual(len(self.posts),2)

    def test_offline_save_failure_no_ai_request_or_quota(self):
        self.context.set_offline(True);self.edit('오프라인 가짜 입력');self.row().get_by_role('button',name='AI 상담 정리',exact=True).click();expect(self.page.locator('#employee-message')).to_contain_text('AI 요청은 접수하지 않았습니다')
        self.assertEqual(self.posts,[]);self.assertEqual(self.db(lambda:AIRequest.objects.count()),0);self.assertEqual(self.db(lambda:AIQuotaBucket.objects.count()),0)

    def test_lost_submission_response_reload_retries_same_key_and_charges_once(self):
        self.worker_route(lose=True);self.row().get_by_role('button',name='AI 상담 정리',exact=True).click();expect(self.page.locator('#ai-pending')).to_be_visible();self.page.once('dialog',lambda dialog:dialog.accept());self.page.reload();expect(self.page.locator('#ai-pending')).to_be_visible();self.page.locator('#ai-retry').click();expect(self.page.locator('#ai-content')).to_contain_text('테스트 전용 가짜 응답')
        self.assertEqual(self.posts[0],self.posts[1]);self.assertEqual(self.db(lambda:AIUsageAttempt.objects.count()),1);self.assertEqual(self.db(lambda:AIQuotaBucket.objects.get().successful_count),1)
        metadata=self.page.evaluate('Object.values(sessionStorage).join(" ")');self.assertNotIn('가짜 최초 상담',metadata);self.assertNotIn('테스트 정리:',metadata)

    def test_stale_result_after_other_save_read_only_no_selected_apply(self):
        self.generate();self.close()
        def edit():
            customer=Customer.objects.get(pk=self.rows[0].pk);update_row(self.employee,self.mutation(customer,'다른 탭의 새 가짜 값'))
        self.db(edit);self.row().get_by_role('button',name='AI 결과',exact=True).click();self.page.locator('#ai-history button').first.click();expect(self.page.locator('#ai-result-message')).to_contain_text('오래된 결과');expect(self.page.locator('#ai-apply')).to_be_disabled();self.assertEqual(self.page.locator('#ai-content input:checked').count(),0)
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED').count()),0)

    def test_selected_ai_queue_survives_offline_reload_and_preserves_provenance(self):
        self.generate();self.choose_notes();self.close();self.context.set_offline(True)
        self.page.locator('#save-now').click();expect(self.page.locator('#employee-message')).to_contain_text('저장하지 못한 행')
        # Page loading requires connectivity; the offline queue is not discarded.
        self.context.set_offline(False);self.page.once('dialog',lambda dialog:dialog.accept());self.page.reload();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기');self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED',source_ai_result__isnull=False).count()),1)

    def test_polling_only_visible_open_dialog_and_stops_when_closed(self):
        self.page.clock.install();self.page.once('dialog',lambda dialog:dialog.accept());self.page.reload();expect(self.page.locator('#ai-availability')).to_contain_text('테스트 전용')
        self.row().get_by_role('button',name='상담 요약',exact=True).click();expect(self.page.locator('#ai-result-message')).to_contain_text('접수했습니다');count=len(self.gets);self.page.clock.run_for(3100);expect(self.page.locator('#ai-result-message')).to_contain_text('접수했습니다');self.assertGreaterEqual(len(self.gets),count+1)
        self.close();self.page.clock.run_for(10000);closed=len(self.gets);self.page.clock.run_for(10000);self.assertEqual(len(self.gets),closed);self.assertEqual(len(self.posts),1)

    def test_no_key_disables_buttons_and_existing_result_still_readable(self):
        self.generate();self.close()
        with override_settings(AI_FOUNDATION_TEST_MODE=False):
            self.page.reload();expect(self.page.locator('#ai-availability')).to_contain_text('공급자 연결');expect(self.row().get_by_role('button',name='AI 상담 정리',exact=True)).to_be_disabled()
            self.row().get_by_role('button',name='AI 결과',exact=True).click();self.page.locator('#ai-history button').first.click();expect(self.page.locator('#ai-content')).to_contain_text('테스트 전용 가짜 응답');self.assertEqual(len(self.posts),1)

    def test_lost_ai_applied_save_recovers_receipt_without_duplicate_revision(self):
        self.generate();self.choose_notes();self.close()
        def lose(route):self.assertEqual(route.fetch().status,200);route.abort('failed')
        self.page.route('**/api/employee/batch-update',lose,times=1);self.page.locator('#save-now').click();expect(self.page.locator('#employee-message')).to_contain_text('저장하지 못한 행')
        self.page.once('dialog',lambda dialog:dialog.accept());self.page.reload();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED',source_ai_result__isnull=False).count()),1);self.assertEqual(self.db(lambda:AIQuotaBucket.objects.get().successful_count),1)

    def test_hidden_dialog_does_not_poll_and_return_only_reads_existing_task(self):
        self.page.clock.install();self.page.reload();expect(self.page.locator('#ai-availability')).to_contain_text('테스트 전용');self.row().get_by_role('button',name='상담 요약',exact=True).click();expect(self.page.locator('#ai-result-message')).to_contain_text('접수했습니다')
        self.page.evaluate("window.aiHidden=true;Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.aiHidden?'hidden':'visible'});document.dispatchEvent(new Event('visibilitychange'))")
        count=len(self.gets);self.page.clock.run_for(10000);self.assertEqual(len(self.gets),count)
        with self.page.expect_response('**/api/ai/tasks/*'):self.page.evaluate("window.aiHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
        self.assertEqual(len(self.posts),1);self.assertEqual(self.db(lambda:AIUsageAttempt.objects.count()),0)

    def test_result_renders_html_as_text_and_never_executes_or_links_it(self):
        from apps.ai_assistant.adapters import FoundationFakeAdapter
        from dataclasses import replace
        class Adapter:
            def execute_task(self,task,payload):
                response=FoundationFakeAdapter().execute_task(task,payload);response.payload['key_points'][0]['text']='<img src=x onerror="window.p10Executed=true"> https://invalid.example/test';return response
        def execute(route):
            response=route.fetch();self.assertEqual(self.db(lambda:run_once(Adapter()))['succeeded'],1);route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',execute,times=1);self.row().get_by_role('button',name='상담 요약',exact=True).click();expect(self.page.locator('#ai-content')).to_contain_text('<img');self.assertEqual(self.page.locator('#ai-content img,#ai-content a').count(),0);self.assertFalse(self.page.evaluate('!!window.p10Executed'))

    def test_selecting_notes_only_keeps_unchecked_call_recommendation_unchanged(self):
        from apps.ai_assistant.adapters import FoundationFakeAdapter
        self.edit('관심이 있어 추가 설명 요청')
        class Adapter:
            def execute_task(self,task,payload):
                response=FoundationFakeAdapter().execute_task(task,payload);response.payload['suggestions']['call_result']={'status':'SUGGESTION','value':'INTERESTED','source_ids':[str(task.customer_id)],'evidence':'관심','reason':'관심 언급 근거'};return response
        def execute(route):
            response=route.fetch();self.assertEqual(self.db(lambda:run_once(Adapter()))['succeeded'],1);route.fulfill(response=response)
        self.page.route('**/api/ai/customer-tasks',execute,times=1);self.row().get_by_role('button',name='AI 상담 정리',exact=True).click();expect(self.page.get_by_label('통화결과 제안 선택',exact=True)).to_be_enabled();self.assertFalse(self.page.get_by_label('통화결과 제안 선택',exact=True).is_checked())
        self.page.set_viewport_size({'width':390,'height':844});self.page.screenshot(path=str(self.evidence/'p10-cleanup-mobile.png'),full_page=True);self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)
        self.choose_notes();self.close();self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨');self.assertIsNone(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).call_result))

    def test_recall_between_view_and_apply_clears_private_result_and_never_saves(self):
        self.generate();self.page.get_by_label('상담기타내용(비고) 제안 선택',exact=True).check()
        def reassign():
            customer=Customer.objects.get(pk=self.rows[0].pk);change_assignee(self.admin,customer.pk,self.assignee_body(customer,self.other))
        self.db(reassign);self.page.locator('#ai-apply').click();expect(self.page.locator('#ai-dialog')).not_to_be_visible();expect(self.page.locator('#ai-content')).to_be_empty();self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(source='AI_APPLIED').count()),0)
