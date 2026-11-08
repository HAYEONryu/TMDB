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
from apps.ai_assistant.models import AIRequest,AIUsageAttempt,GuidePublication
from apps.ai_assistant.worker import run_once
from apps.ai_assistant.privacy import invalidate_results
from apps.common.transactions import business_write
from apps.consultations.models import ConsultationRevision
from django.utils import timezone
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(AI_FOUNDATION_TEST_MODE=True,AI_CONFIG=TEST_AI)
class P11BrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0]
        ConsultationRevision.objects.create(customer=self.customer,actor=self.employee,saved_at=timezone.now(),customer_version=1,changed_fields=['notes'],notes='가격 비교 후 다시 확인 요청',source='MANUAL')
        self.errors=[];self.external=[];self.posts=[];self.polls=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.pw=sync_playwright().start();self.browser=self.pw.chromium.launch();self.context=self.browser.new_context(viewport={'width':1440,'height':960});self.watch(self.context);self.page=self.context.new_page();self.login(self.page,self.admin);self.page.goto(self.live_server_url+'/app/admin/ai');expect(self.page.locator('#report-message')).to_contain_text('테스트 전용')
    def watch(self,context):
        context.on('page',lambda p:p.on('pageerror',lambda e:self.errors.append(str(e))))
        context.on('request',lambda r:self.external.append(r.url) if urlsplit(r.url).hostname not in ['localhost','127.0.0.1'] else None)
        context.on('request',lambda r:self.posts.append(r.post_data_json) if '/api/ai/' in r.url and r.method=='POST' else None)
        context.on('request',lambda r:self.polls.append(r.url) if '/api/ai/tasks/' in r.url else None)
    def tearDown(self):
        try:self.browser.close()
        finally:self.pw.stop()
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()
    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def login(self,page,user):
        page.goto(self.live_server_url+'/auth/login');page.get_by_label('전화번호',exact=True).fill(user.phone_normalized);page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);page.get_by_role('button',name='로그인',exact=True).click();expect(page).to_have_url(self.live_server_url+('/app/admin' if user.role=='ADMIN' else '/app/employee'))
    def guide(self,lose=False):
        self.page.locator('#report-type').select_option('TEAM_GUIDE');expect(self.page.locator('#report-site')).to_have_value(str(self.site.pk));self.page.locator('#knowledge-panel').wait_for(state='visible');expect(self.page.locator('#knowledge-save')).to_be_enabled()
        used=False
        def execute(route):
            nonlocal used
            if used or route.request.method!='POST':return route.continue_()
            used=True
            response=route.fetch();self.assertEqual(response.status,202);self.assertEqual(self.db(run_once)['succeeded'],1)
            if lose:route.abort('failed')
            else:route.fulfill(response=response)
        self.page.route('**/api/ai/sites/*/guides',execute)
        self.page.locator('#report-generate').click()
        if not lose:expect(self.page.locator('#guide-editor')).to_be_visible()
    def save(self,reviewed=True):
        self.page.locator('#guide-reviewed').set_checked(reviewed);self.page.locator('#guide-save').click();expect(self.page.locator('#guide-status')).to_contain_text('초안 저장 완료')
    def staff(self):
        context=self.browser.new_context(viewport={'width':390,'height':844});self.watch(context);page=context.new_page();self.login(page,self.employee);page.goto(self.live_server_url+'/app/guides');return context,page
    def test_no_auto_generation_weekday_disabled_and_existing_lists(self):
        # Verify the weekday UI on every calendar day, including a real Sunday.
        def weekday(route):
            response=route.fetch();data=response.json();data['weekly_generation_day']=False
            route.fulfill(response=response,json=data)
        self.page.route('**/api/ai/availability',weekday)
        self.page.reload()
        expect(self.page.locator('#report-generate')).to_be_disabled();expect(self.page.locator('#report-rule')).to_contain_text('일요일')
        self.page.locator('#report-refresh').click();self.page.locator('#report-type').select_option('EMPLOYEE_COACHING');expect(self.page.locator('#report-generate')).to_be_enabled()
        self.assertEqual(self.db(lambda:AIRequest.objects.count()),0);self.assertEqual(self.posts,[])
    def test_guide_review_publish_employee_read_only_and_mobile(self):
        self.guide();expect(self.page.locator('#guide-publish')).to_be_disabled();self.assertFalse(self.db(lambda:GuidePublication.objects.exists()))
        self.page.screenshot(path=str(self.evidence/'p11-guide-desktop.png'),full_page=True)
        context,page=self.staff();expect(page.locator('#published-message')).to_contain_text('없습니다')
        self.save();self.page.locator('#guide-publish').click();expect(self.page.locator('#guide-status')).to_contain_text('게시 완료');page.locator('#published-refresh').click();expect(page.locator('#published-message')).to_contain_text('테스트 전용');expect(page.locator('#published-body')).to_contain_text('현장 담당자 확인 필요')
        page.screenshot(path=str(self.evidence/'p11-published-mobile.png'),full_page=True);self.assertEqual(page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0);self.assertEqual(page.locator('textarea').count(),0);self.assertEqual(self.db(lambda:AIUsageAttempt.objects.count()),1);context.close()
    def test_coaching_attribution_insufficient_evidence_and_source_link(self):
        self.page.locator('#report-type').select_option('EMPLOYEE_COACHING');self.page.locator('#report-employee').select_option(str(self.employee.pk))
        def execute(route):
            response=route.fetch();self.assertEqual(self.db(run_once)['succeeded'],1);route.fulfill(response=response)
        self.page.route('**/api/ai/employees/*/coaching',lambda route:execute(route) if route.request.method=='POST' else route.continue_());self.page.locator('#report-generate').click();expect(self.page.locator('#report-content')).to_contain_text('판단 불가');expect(self.page.locator('#report-content')).to_contain_text(self.employee.name);expect(self.page.locator('#report-content a').first).to_have_attribute('href',f'/app/admin/ai/cases/{self.customer.pk}')
        self.page.set_viewport_size({'width':390,'height':844});self.page.screenshot(path=str(self.evidence/'p11-coaching-mobile.png'),full_page=True);self.assertEqual(self.page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)'),0)
    def test_new_draft_edit_keeps_old_publication_and_review_resets(self):
        self.guide();self.save();self.page.locator('#guide-publish').click();expect(self.page.locator('#guide-status')).to_contain_text('게시 완료');old=self.db(lambda:GuidePublication.objects.get().body)
        self.page.locator('#guide-body').fill('고객에게 다시 확인할 질문을 준비하세요.');expect(self.page.locator('#guide-publish')).to_be_disabled();self.save(False);self.assertEqual(self.db(lambda:GuidePublication.objects.get().body),old);expect(self.page.locator('#guide-publish')).to_be_disabled()
    def test_lost_submission_response_retries_same_key_after_reload(self):
        self.guide(lose=True);expect(self.page.locator('#report-retry')).to_be_visible();self.page.reload();expect(self.page.locator('#report-retry')).to_be_visible();self.page.locator('#report-retry').click();expect(self.page.locator('#guide-editor')).to_be_visible();self.assertEqual(self.posts[0],self.posts[1]);self.assertEqual(self.db(lambda:AIUsageAttempt.objects.count()),1)
        self.assertNotIn('가격 비교',self.page.evaluate('Object.values(sessionStorage).join(" ")'))
    def test_knowledge_review_and_change_invalidates_published_guide(self):
        self.page.locator('#report-type').select_option('TEAM_GUIDE');self.page.locator('#knowledge-title').fill('가짜 공식 안내');self.page.locator('#knowledge-body').fill('예약 전 담당자에게 확인하세요.');self.page.locator('#knowledge-reviewed').check();self.page.locator('#knowledge-valid').check();self.page.locator('#knowledge-save').click();expect(self.page.locator('#knowledge-message')).to_contain_text('저장 완료')
        self.guide();self.save();self.page.locator('#guide-publish').click();expect(self.page.locator('#guide-status')).to_contain_text('게시 완료')
        self.page.locator('#knowledge-select').select_option(label='가짜 공식 안내 · v1 · 유효');self.page.locator('#knowledge-body').fill('변경된 담당자 확인 자료');self.page.locator('#knowledge-save').click();expect(self.page.locator('#report-content')).to_contain_text('원본 삭제·변경');expect(self.page.locator('#guide-editor')).to_be_hidden();self.assertFalse(self.db(lambda:GuidePublication.objects.exists()))
    def test_dirty_guide_navigation_requires_explicit_discard(self):
        self.guide();self.page.locator('#guide-body').fill('아직 저장하지 않은 가짜 초안');self.page.once('dialog',lambda dialog:dialog.dismiss());self.page.locator('#report-close').click();expect(self.page.locator('#guide-editor')).to_be_visible();expect(self.page.locator('#guide-body')).to_have_value('아직 저장하지 않은 가짜 초안')
        self.page.once('dialog',lambda dialog:dialog.accept());self.page.locator('#report-close').click();expect(self.page.locator('#report-detail')).to_be_hidden()
    def test_polling_only_while_open_and_stops_on_completion_or_close(self):
        self.page.clock.install();self.page.locator('#report-type').select_option('TEAM_GUIDE');self.page.locator('#report-generate').click();expect(self.page.locator('#report-content')).to_contain_text('접수');count=len(self.polls);self.page.clock.fast_forward(3100);self.page.wait_for_timeout(100);self.assertGreater(len(self.polls),count)
        self.page.evaluate("window.aiHidden=true;Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.aiHidden?'hidden':'visible'});document.dispatchEvent(new Event('visibilitychange'))");count=len(self.polls);self.page.clock.fast_forward(10000);self.assertEqual(len(self.polls),count)
        self.page.evaluate("window.aiHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
        self.page.locator('#report-close').click();count=len(self.polls);self.page.clock.fast_forward(10000);self.assertEqual(len(self.polls),count)
        self.assertEqual(self.db(run_once)['succeeded'],1);self.page.locator('#report-refresh').click();self.page.locator('#report-history button').first.click();expect(self.page.locator('#guide-editor')).to_be_visible();count=len(self.polls);self.page.clock.fast_forward(10000);self.assertEqual(len(self.polls),count);self.assertEqual(self.db(lambda:AIRequest.objects.count()),1)

    def test_sunday_explicit_weekly_generation_and_cutoff_display(self):
        from datetime import timedelta
        from unittest.mock import patch
        from apps.customers.queries import KST
        now=timezone.now();sunday=now+timedelta(days=(6-now.astimezone(KST).weekday())%7)
        with patch('django.utils.timezone.now',return_value=sunday):
            self.page.goto(self.live_server_url+'/auth/login')
            # Refresh the login/session under the Sunday clock, preserving the normal UI login path.
            self.page.locator('form[action="/auth/logout"] button').click() if self.page.locator('form[action="/auth/logout"] button').count() else None
            self.login(self.page,self.admin);self.page.goto(self.live_server_url+'/app/admin/ai');expect(self.page.locator('#report-generate')).to_be_enabled()
            def execute(route):
                response=route.fetch();self.assertEqual(self.db(run_once)['succeeded'],1);route.fulfill(response=response)
            self.page.route('**/api/ai/weekly-briefings',lambda route:execute(route) if route.request.method=='POST' else route.continue_())
            self.page.locator('#report-generate').click();expect(self.page.locator('#report-content')).to_contain_text('일요일 업무는 집계 시각까지 포함');expect(self.page.locator('#report-content')).to_contain_text('이번 주 생성 1회 사용');expect(self.page.locator('#report-content')).to_contain_text('한국 시각');self.assertEqual(self.db(lambda:AIRequest.objects.count()),1)
