from scripts.verification_evidence import artifact_path
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from playwright.sync_api import sync_playwright,expect
from apps.accounts.services import reset_password
from apps.assignments.services import change_assignee
from apps.assignments.models import Assignment
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.services import update_row
from tests.helpers import STRONG_PASSWORD
from tests.test_p4 import Fixtures
from tests.browser_observation import BrowserObservation


class EmployeeBrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.rows=self.customers(3)
        for row in self.rows:self.assign(row)
        self.foreign=self.customers(offset=20)[0];self.assign(self.foreign,self.other)
        self.errors=[];self.external=[];self.sent=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(settings.BASE_DIR/'.cache/ms-playwright'))
        self.playwright=sync_playwright().start()
        # Cleanup must also run when setup/navigation fails. Otherwise the sync
        # Playwright event loop leaks into Django's DB teardown and masks every
        # subsequent test with SynchronousOnlyOperation.
        self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch();self.addCleanup(self.browser.close)
        self.context=self.browser.new_context(viewport={'width':1440,'height':960})
        self.observation=BrowserObservation(self.context,self.live_server_url+'/healthz',self.server_thread)
        self.addCleanup(self.observation.finish)
        self.watch(self.context);self.page=self.context.new_page();self.login(self.page,self.employee);self.open(self.page)

    def watch(self,context):
        context.on('page',lambda page:page.on('pageerror',lambda error:self.errors.append(str(error))))
        context.on('request',lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ['localhost','127.0.0.1'] else None)
        context.on('request',lambda request:self.sent.append(request.post_data_json) if request.url.endswith('/api/employee/batch-update') else None)

    def tearDown(self):
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()
    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()
    def login(self,page,person):
        page.context.clear_cookies()
        page.goto(self.live_server_url+'/auth/login');page.get_by_label('전화번호',exact=True).fill(person.phone_normalized);page.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD);page.get_by_role('button',name='로그인',exact=True).click();expect(page).to_have_url(self.live_server_url+('/app/admin' if person.role=='ADMIN' else '/app/employee'))
    def open(self,page):
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 3건');expect(page.locator('#employee-message')).to_be_empty()
    def cell(self,page=None,field='notes',index=0):return (page or self.page).locator(f'#employee-grid .tabulator-row [tabulator-field="{field}"]').nth(index)
    def edit(self,value,page=None,field='notes',index=0,blur=True,pending=True):
        page=page or self.page;cell=self.cell(page,field,index);cell.dblclick();control=cell.locator('textarea,input,select');control.fill(value) if field not in ['call_result','contract_status','route','housing_status'] else control.select_option(value)
        if blur:page.locator('h1').click()
        if pending:expect(page.locator('#queue-status')).to_contain_text('저장 대기')
        return cell
    def records(self,page=None):
        return (page or self.page).evaluate("""async()=>{const db=await new Promise((ok,no)=>{const r=indexedDB.open('tm-employee-queue-v1',1);r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error);});return await new Promise(ok=>{const t=db.transaction('entries');const r=t.objectStore('entries').getAll();r.onsuccess=()=>ok(r.result);});}""")
    def saved(self,page=None):expect((page or self.page).locator('#queue-status')).to_have_text('모든 변경 저장됨')
    def save(self,page=None):
        page=page or self.page;page.locator('#save-now').click();self.saved(page)
    def row_id(self,index=0,page=None):return (page or self.page).locator('#employee-grid .tabulator-row').nth(index).get_attribute('tabulator-row-index')

    def test_injected_network_failure_preserves_only_sanitized_observation(self):
        from playwright.sync_api import Error
        marker='SYNTHETIC_PRIVATE_QUERY_AND_BODY'
        self.page.route('**/healthz?*',lambda route:route.abort('connectionreset'))
        with self.assertRaises(Error):self.page.goto(self.live_server_url+'/healthz?token='+marker)
        self.observation.finish()
        content=''.join(p.read_text() for p in self.observation.target.glob('*.json'))
        for private in [marker,STRONG_PASSWORD,self.employee.phone_normalized]:self.assertNotIn(private,content)
        failed=json.loads((self.observation.target/'failed-requests.json').read_text())
        self.assertTrue(any(row['failure']=='net::ERR_CONNECTION_RESET' for row in failed))
        state=json.loads((self.observation.target/'observation.json').read_text())
        self.assertEqual(state['root_cause'],'UNCONFIRMED')
        self.assertEqual(state['trace_status'],'sanitized_projection_saved')

    def test_first_dirty_deadline_continuous_typing_noop_and_copy_restrictions(self):
        page=self.page
        self.cell().dblclick();page.locator('h1').click();page.clock.install();page.clock.run_for(95000);self.assertEqual(self.sent,[])
        self.edit('가상 첫 입력',blur=False);first=page.evaluate('Date.now()');page.clock.run_for(60000)
        self.cell().locator('textarea').fill('가상 최신 입력');page.clock.run_for(29999);self.assertEqual(self.sent,[])
        with page.expect_request('**/api/employee/batch-update') as event:page.clock.run_for(1500)
        self.saved();elapsed=page.evaluate('Date.now()')-first;self.assertLessEqual(elapsed,100000);body=event.value.post_data_json;self.assertEqual(body['rows'][0]['changes'],{'notes':'가상 최신 입력'})
        (artifact_path('p5-timing.json')).write_text(json.dumps({'target_ms':90000,'typing_again_ms':60000,'clock_elapsed_when_confirmed_ms':elapsed,'within_100000ms':True}),encoding='utf-8')
        cid=body['rows'][0]['customer_id'];self.assertEqual(self.db(lambda:Customer.objects.get(pk=cid).notes),'가상 최신 입력');self.assertIsNotNone(self.db(lambda:Assignment.objects.get(pk=body['rows'][0]['assignment_id']).first_activity_at))
        page.locator('h1').click();page.clock.run_for(100000);self.assertEqual(len(self.sent),1)
        self.assertEqual(page.locator('#employee-grid input[type=checkbox]').count(),0)
        for name in ['copy','cut','contextmenu']:
            self.assertFalse(page.locator('#employee-grid').evaluate('(element,name)=>element.dispatchEvent(new Event(name,{bubbles:true,cancelable:true}))',name))
        self.assertTrue(page.locator('#employee-grid').evaluate("element=>element.dispatchEvent(new Event('paste',{bubbles:true,cancelable:true}))"))
        self.assertFalse(page.locator('#employee-grid').evaluate("element=>element.dispatchEvent(new KeyboardEvent('keydown',{key:'c',ctrlKey:true,bubbles:true,cancelable:true}))"))
        self.assertTrue(page.locator('#employee-grid').evaluate("element=>element.dispatchEvent(new KeyboardEvent('keydown',{key:'v',metaKey:true,bubbles:true,cancelable:true}))"))

    def test_offline_encrypted_persistent_browser_restart_user_isolation(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR/'.local',prefix='p5-browser-') as profile:
            context=self.playwright.chromium.launch_persistent_context(profile);self.watch(context);page=context.pages[0];self.login(page,self.employee);self.open(page)
            key=context.request.get(self.live_server_url+'/api/employee/context',headers={'X-TM-Queue-User':str(self.employee.pk)}).json()['key']
            context.set_offline(True);self.edit('가짜 오프라인 상담 고유문장',page);expect(page.locator('#pending-rows')).to_contain_text('오프라인 대기')
            page.wait_for_function("async()=>{const d=await new Promise(ok=>{const r=indexedDB.open('tm-employee-queue-v1');r.onsuccess=()=>ok(r.result)});return await new Promise(ok=>{const r=d.transaction('entries').objectStore('entries').count();r.onsuccess=()=>ok(r.result===1)})}")
            records=self.records(page);encoded=json.dumps(records,ensure_ascii=False);self.assertNotIn('가짜 오프라인 상담 고유문장',encoded);self.assertNotIn('notes',encoded);self.assertNotIn(key,encoded)
            self.assertEqual(set(records[0]),{'key','user_id','site_id','customer_id','assignment_id','cipher','iv'})
            proof=page.evaluate("""async ({user,key,record})=>{const {QueueStore}=await import('/static/employee-store.js');const s=await new QueueStore(user,key).open();const e=await s.read(record);let tamper=false,exportBlocked=false;try{await s.read({...record,customer_id:crypto.randomUUID()});}catch{tamper=true;}try{await crypto.subtle.exportKey('raw',s.cryptoKey);}catch{exportBlocked=true;}s.close();return {tamper,exportBlocked,storedFields:Object.keys(e.pending)};}""",{'user':str(self.employee.pk),'key':key,'record':records[0]})
            self.assertEqual(proof,{'tamper':True,'exportBlocked':True,'storedFields':['notes']});context.close()
            context=self.playwright.chromium.launch_persistent_context(profile);self.watch(context);page=context.pages[0];self.login(page,self.other);page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}');expect(page.locator('#page-info')).to_contain_text('검색 1건');self.saved(page);self.assertNotIn('가짜 오프라인',page.locator('body').inner_text());self.assertEqual(len(self.records(page)),1)
            self.login(page,self.employee);self.open(page);expect(page.locator('#queue-status')).to_contain_text('저장 대기 1행');expect(page.locator('#employee-grid')).to_contain_text('가짜 오프라인 상담 고유문장');self.save(page);self.assertEqual(self.records(page),[]);context.close()
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),1)

    def test_native_datetime_arrows_edit_value_instead_of_navigating_grid(self):
        cell = self.cell(field='callback_due_at')
        customer_name = self.cell(field='customer_name').inner_text()
        customer_id = self.db(lambda: str(Customer.objects.get(customer_name=customer_name).pk))
        cell.dblclick()
        control = cell.locator('input')
        control.fill('2026-11-08T15:00')
        control.press('ArrowLeft')
        before = control.input_value()
        control.press('ArrowUp')
        after = control.input_value()
        self.assertNotEqual(after, before)
        self.page.locator('h1').click()
        self.save()
        self.assertEqual(self.sent[-1]['rows'][0]['customer_id'], customer_id)
        self.page.reload()
        self.saved()
        cell = self.cell(field='callback_due_at')
        cell.dblclick()
        self.assertEqual(cell.locator('input').input_value(), after)
        cell.locator('input').press('Escape')

    def test_inflight_later_edit_and_lost_response_recovery(self):
        page=self.page;self.edit('가상 전송 스냅샷');held=[]
        def hold(route):held.append(route)
        page.route('**/api/employee/batch-update',hold,times=1);page.locator('#save-now').click();page.wait_for_function("document.querySelector('#pending-rows').textContent.includes('저장 중')")
        self.edit('가상 전송 중 다음 입력');self.assertEqual(held[0].request.post_data_json['rows'][0]['changes'],{'notes':'가상 전송 스냅샷'})
        held[0].fulfill(response=held[0].fetch());self.saved();expect(self.cell()).to_have_text('가상 전송 중 다음 입력');self.assertEqual(len(self.sent),2)
        captured=[]
        def lose(route):captured.append(route.request.post_data_json);response=route.fetch();self.assertEqual(response.status,200);route.abort('failed')
        page.route('**/api/employee/batch-update',lose,times=1);self.edit('가상 응답 유실');page.locator('#save-now').click();expect(page.locator('#pending-rows')).to_contain_text('재시도 대기')
        page.once('dialog',lambda dialog:dialog.accept());page.reload();self.saved();self.assertEqual(self.records(),[]);self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),3)
        self.assertEqual(len(self.sent),3) # Recovery reads receipt rather than submitting a new mutation.

    def test_multitab_explicit_conflict_and_reassignment_blocks_old_queue(self):
        page=self.page;second=self.context.new_page();self.open(second)
        self.edit('가상 첫 탭');self.edit('가상 두 번째 탭',second);self.save();second.locator('#save-now').click();expect(second.locator('#pending-rows')).to_contain_text('충돌')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),1)
        second.get_by_role('button',name='비교·확인',exact=True).click();expect(second.locator('#employee-compare')).to_contain_text('가상 첫 탭');expect(second.locator('#employee-compare')).to_contain_text('가상 두 번째 탭')
        second.locator('#employee-reapply').click();self.saved(second);self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),2)
        self.edit('재분배 전 가상 대기',second);cid=self.sent[-1]['rows'][0]['customer_id'];customer=self.db(lambda:Customer.objects.get(pk=cid))
        self.db(lambda:change_assignee(self.admin,customer.pk,self.assignee_body(customer)))
        self.db(customer.refresh_from_db);self.db(lambda:change_assignee(self.admin,customer.pk,self.assignee_body(customer,self.employee)))
        second.locator('#save-now').click();expect(second.locator('#pending-rows')).to_contain_text('전송 불가');second.get_by_role('button',name='대기 정보 확인',exact=True).click();expect(second.locator('#employee-reapply')).to_be_disabled();expect(second.locator('#employee-compare')).to_be_empty()
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=cid).notes),'가상 두 번째 탭');self.assertEqual(len(self.sent),2)
        second.close()

    def test_navigation_logout_failure_cancel_retry_and_confirmed_discard(self):
        page=self.page;self.context.set_offline(True);self.edit('가상 이동 실패 대기');page.get_by_role('link',name='오늘 할 일',exact=True).click();expect(page.locator('#leave-dialog')).to_be_visible();page.locator('#leave-cancel').click();expect(page).to_have_url(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        page.get_by_role('button',name='로그아웃',exact=True).click();expect(page.locator('#leave-cancel')).to_have_text('로그아웃 취소');page.locator('#leave-cancel').click()
        self.context.set_offline(False);page.get_by_role('link',name='오늘 할 일',exact=True).click();expect(page).to_have_url(self.live_server_url+'/app/employee/today');self.saved();self.assertEqual(len(self.sent),1)
        expect(page.locator('#page-info')).to_contain_text('검색 3건');self.context.set_offline(True);self.edit('가상 버릴 대기');page.get_by_role('button',name='로그아웃',exact=True).click();page.once('dialog',lambda dialog:dialog.dismiss());page.locator('#leave-discard').click();expect(page.locator('#leave-dialog')).to_be_visible();self.assertEqual(len(self.records()),1)
        self.context.set_offline(False);page.once('dialog',lambda dialog:dialog.accept());page.locator('#leave-discard').click();expect(page).to_have_url(self.live_server_url+'/auth/login');self.assertEqual(self.records(),[])

    def test_quota_failure_attempts_server_and_blocks_navigation_when_both_fail(self):
        page=self.page;page.evaluate("()=>{window.originalPut=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(){throw new DOMException('test quota','QuotaExceededError')};}")
        self.edit('가상 로컬 실패 서버 성공');self.saved();self.assertEqual(len(self.sent),1)
        self.context.set_offline(True);self.edit('가상 양쪽 실패');expect(page.locator('#storage-warning')).to_contain_text('로컬 임시 보관 실패');page.get_by_role('link',name='대시보드',exact=True).click();expect(page.locator('#leave-dialog')).to_be_visible();page.locator('#leave-cancel').click()
        page.evaluate('()=>{IDBObjectStore.prototype.put=window.originalPut;}');self.context.set_offline(False);self.save();self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),2)

    def test_session_invalid_stops_retries_and_account_switch_hides_values(self):
        page=self.page;self.edit('가상 비밀번호 재설정 전 대기');self.db(lambda:reset_password(self.admin,self.employee.pk));page.locator('#save-now').click();expect(page.locator('#queue-status')).to_have_text('저장 중단');expect(page.locator('#employee-private')).to_be_hidden();self.assertEqual(self.sent,[])
        second=self.context.new_page();self.login(second,self.other);second.goto(self.live_server_url+'/app/employee/mine');expect(page.locator('#employee-private')).to_be_hidden();self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),0);second.close()

    def test_filters_mobile_dates_and_visual_evidence(self):
        page=self.page;self.edit('가상 필터용 상담');self.save();page.get_by_role('button',name='상담내용 필터',exact=True).click();page.locator('#filter-contains').fill('필터용');page.locator('#filter-apply').click();expect(page.locator('#page-info')).to_contain_text('검색 1건')
        page.locator('#clear-filters').click();expect(page.locator('#page-info')).to_contain_text('검색 3건')
        page.get_by_role('button',name='통화결과 필터',exact=True).click();expect(page.locator('#filter-options')).to_contain_text('(빈 값)');page.get_by_role('button',name='전체 해제',exact=True).click();page.locator('#filter-apply').click();expect(page.locator('#page-info')).to_contain_text('검색 0건');page.locator('#clear-filters').click();expect(page.locator('#page-info')).to_contain_text('검색 3건')
        page.screenshot(path=str(self.evidence/'p5-employee-desktop.png'),full_page=True);page.set_viewport_size({'width':390,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390);page.screenshot(path=str(self.evidence/'p5-employee-mobile.png'),full_page=True)

    def test_expired_queue_manual_review_and_foreground_online_deadline(self):
        page=self.page;self.edit('7일 지난 가상 대기')
        page.wait_for_function("async()=>{const d=await new Promise(ok=>{const r=indexedDB.open('tm-employee-queue-v1');r.onsuccess=()=>ok(r.result)});return await new Promise(ok=>{const r=d.transaction('entries').objectStore('entries').count();r.onsuccess=()=>ok(r.result===1)})}")
        page.evaluate("""async user=>{const {QueueStore}=await import('/static/employee-store.js');const c=await (await fetch('/api/employee/context',{headers:{'X-TM-Queue-User':user}})).json();const s=await new QueueStore(user,c.key).open();for(const record of await s.list()){const e=await s.read(record);e.created_at=Date.now()-8*86400000;await s.put(e);}s.close();}""",str(self.employee.pk))
        page.once('dialog',lambda dialog:dialog.accept());page.reload();expect(page.locator('#pending-rows')).to_contain_text('수동 확인 필요');self.assertEqual(self.sent,[])
        page.get_by_role('button',name='비교·확인',exact=True).click();expect(page.locator('#employee-compare')).to_contain_text('7일 지난 가상 대기');page.locator('#employee-reapply').click();self.saved();self.assertEqual(len(self.sent),1)
        page.clock.install();self.context.set_offline(True);self.edit('온라인 복구 가상 대기');page.clock.run_for(100000)
        with page.expect_request('**/api/employee/batch-update'):self.context.set_offline(False)
        self.saved();self.assertEqual(len(self.sent),2)

    def test_reverted_unsent_values_do_not_create_activity_and_datetime_fields(self):
        page=self.page;self.edit('저장 전 원복할 가상 내용');self.edit('',pending=False);self.saved();self.assertEqual(self.sent,[]);self.assertFalse(self.db(lambda:Assignment.objects.filter(first_activity_at__isnull=False).exists()))
        self.edit('INTERESTED',field='call_result');self.edit('2026-11-05T13:30',field='visit_at');self.edit('2026-11-06T10:15',field='callback_due_at');self.edit('다주택',field='housing_status');self.save()
        body=self.sent[0]['rows'][0];self.assertEqual(body['changes']['visit_at'],'2026-11-05T04:30:00.000Z');self.assertEqual(body['changes']['housing_status'],'다주택');self.assertEqual(body['changes']['callback_due_at'],'2026-11-06T01:15:00.000Z')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),1)
        self.cell(field='visit_at').dblclick();page.locator('h1').click();self.saved();self.assertEqual(len(self.sent),1)

    def test_transient_retry_same_mutation_and_no_write_when_recovery_check_fails(self):
        page=self.page;page.clock.install();failures=[]
        def unavailable(route):failures.append(route.request.post_data_json);route.abort('failed')
        page.route('**/api/employee/batch-update',unavailable,times=1);self.edit('가상 네트워크 재시도');page.locator('#save-now').click();expect(page.locator('#pending-rows')).to_contain_text('재시도 대기')
        with page.expect_request('**/api/employee/batch-update') as retry:page.clock.run_for(3500)
        self.saved();self.assertEqual(retry.value.post_data_json,failures[0]);self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),1)
        self.edit('가상 확인 서버 장애');count=len(self.sent)
        page.route('**/api/employee/queue-check',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":{"code":"TEMPORARY_UNAVAILABLE","message":"가상 점검 장애"}}'),times=1)
        page.locator('#save-now').click();expect(page.locator('#pending-rows')).to_contain_text('재시도 대기');self.assertEqual(len(self.sent),count)

    def test_invalid_first_input_is_not_reported_saved_and_navigation_requires_choice(self):
        page=self.page;cell=self.cell(field='residence');cell.dblclick();control=cell.locator('input');control.fill('x'*201)
        expect(page.locator('#queue-status')).to_have_text('입력 오류 · 미저장');expect(page.locator('#employee-message')).to_contain_text('200자');self.assertEqual(self.sent,[])
        page.get_by_role('link',name='대시보드',exact=True).click();expect(page.locator('#leave-dialog')).to_be_visible();page.locator('#leave-cancel').click();control.press('Escape');self.saved();self.assertEqual(self.sent,[])
