"""Today's TM carryover and server-confirmed read-only state in a real browser."""
from datetime import datetime, time, timedelta
import json
from unittest.mock import patch
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.contrib.sessions.models import Session
from django.utils import timezone
from playwright.sync_api import expect
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class TodayTMBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self,called=False,callback=False,inherited=False):
        def create():
            now=timezone.now();start=datetime.combine(now.astimezone(KST).date(),time.min,KST)
            row=self.customers()[0]
            if inherited:
                old=self.assign(row,self.other,at=start-timedelta(days=3))
                old.ended_at=start-timedelta(days=1);old.end_reason='REASSIGNED';old.ended_by=self.admin;old.save()
                Customer.objects.filter(pk=row.pk).update(current_assignment=None,call_result='NO_ANSWER')
                ConsultationRevision.objects.create(customer=row,assignment=old,actor=self.other,saved_at=start-timedelta(days=2),
                    customer_version=1,source='MANUAL',changed_fields=['call_result'],after_values={'call_result':'NO_ANSWER'})
            assignment=self.assign(row,at=start-timedelta(days=1))
            if called:
                Customer.objects.filter(pk=row.pk).update(call_result='NO_ANSWER')
                ConsultationRevision.objects.create(customer=row,assignment=assignment,actor=self.employee,saved_at=start-timedelta(hours=1),
                    customer_version=1,source='MANUAL',changed_fields=['call_result'],after_values={'call_result':'NO_ANSWER'})
            if callback:Callback.objects.create(customer=row,due_at=start-timedelta(hours=2),created_by=self.employee,updated_by=self.employee)
            return row,start
        self.row,self.start=self.db(create)
        self.login(self.employee);self.page.goto(self.live_server_url+f'/app/employee/today?site_id={self.site.pk}')
        expect(self.page.locator('#page-info')).to_contain_text('검색 1명')

    def status(self):return self.page.locator('#employee-grid .tabulator-row [tabulator-field=last_tm_date]')

    def assert_state(self,label):
        response=self.context.request.get(self.live_server_url+f'/api/customers?view=today&site_id={self.site.pk}')
        self.assertEqual(response.status,200)
        row=next(r for r in response.json()['data'] if r['id']==str(self.row.pk))
        self.assertEqual(row['tm_status'],'COMPLETED' if label=='완료' else 'PENDING')

    def edit(self,field,value):
        cell=self.page.locator(f'#employee-grid .tabulator-row [tabulator-field="{field}"]')
        cell.scroll_into_view_if_needed();cell.dblclick()
        control=cell.locator('input,textarea,select')
        control.select_option(value) if field=='call_result' else control.fill(value)
        self.page.locator('h1').click();expect(self.page.locator('#queue-status')).to_contain_text('저장 대기')

    def save(self):
        self.page.locator('#save-now').click();expect(self.page.locator('#queue-status')).to_have_text('모든 변경 저장됨')

    def test_label_readonly_first_column_confirmed_save_and_responsive(self):
        self.seed();page=self.page
        expect(page.locator('h1')).to_have_text('오늘의 TM');expect(page).to_have_title('오늘의 TM · 두드림 TM')
        expect(page.locator('#employee-grid .tabulator-col-title').first).to_have_text('No.')
        expect(page.locator('#employee-grid .tabulator-col-title').nth(1)).to_contain_text('최종 TM 날짜')
        self.assert_state('-');self.status().dblclick();expect(self.status().locator('input,select,textarea')).to_have_count(0)
        self.edit('call_result','NO_ANSWER');self.assert_state('-')
        self.save();self.assert_state('완료');expect(page.locator('#page-info')).to_contain_text('검색 1명')
        page.reload();self.assert_state('완료')
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            page.locator('#employee-grid').evaluate('grid=>grid.querySelector(".tabulator-tableholder").scrollLeft=0')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            box=self.status().bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width+1)
            page.screenshot(path=str(artifact_path(f'today-tm-{width}.png')),full_page=True)
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(page.locator('#employee-grid .tabulator-col[tabulator-field=last_tm_date]')).to_have_count(1)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_notes_and_inherited_result_stay_pending_then_callback_completion_is_confirmed(self):
        self.seed(inherited=True);page=self.page
        self.edit('notes','가상 상담내용만 정정');self.save();self.assert_state('-')
        self.edit('call_result','INTERESTED');self.save();self.assert_state('완료')
        self.db(lambda:Callback.objects.create(customer=self.row,due_at=timezone.now(),created_by=self.employee,updated_by=self.employee))
        page.locator('#reload-rows').click();self.assert_state('-')
        check=page.get_by_role('checkbox',name='재콜 완료',exact=True);check.scroll_into_view_if_needed();check.click()
        expect(page.get_by_role('checkbox',name='재콜 완료',exact=True)).to_have_count(0)
        self.assert_state('완료');expect(page.locator('#page-info')).to_contain_text('검색 1명')
        self.assertEqual(self.errors,[])

    def test_auto_save_failure_never_marks_done_retry_keeps_same_row(self):
        self.page.clock.install();self.seed();page=self.page
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 저장 실패'}})
        page.route('**/api/employee/batch-update',fail)
        self.edit('call_result','NO_ANSWER');page.clock.fast_forward(91000)
        expect(page.locator('#pending-panel')).to_contain_text('결과를 확인하지 못했습니다')
        self.assert_state('-')
        expect(self.status()).to_have_text('-')
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(customer=self.row).count()),0)
        page.unroute('**/api/employee/batch-update',fail);self.save()
        self.assert_state('완료');expect(page.locator('#page-info')).to_contain_text('검색 1명')
        expect(self.status().locator('.tm-date-value')).to_have_text(timezone.localdate(timezone.now(), KST).isoformat())
        self.assertEqual(self.errors,[])

    def test_result_clear_then_reenter_and_save_buttons_keyboard_responsive(self):
        self.seed();page=self.page
        self.edit('call_result','NO_ANSWER');self.save();self.assert_state('완료')
        self.edit('call_result','');self.assert_state('완료')
        page.locator('#save-now').focus();page.keyboard.press('Enter')
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨');self.assert_state('-')
        page.reload();self.assert_state('-')
        self.assertIsNone(self.db(lambda:Customer.objects.get(pk=self.row.pk).call_result))
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            save=page.locator('.list-actions #save-now');reload=page.locator('.list-actions #reload-rows')
            self.assertEqual(page.locator('.page-heading #save-now').count(),0)
            a,b=save.bounding_box(),reload.bounding_box()
            self.assertAlmostEqual(a['height'],b['height'],delta=1)
            self.assertEqual(save.evaluate('(el)=>getComputedStyle(el).fontSize'),reload.evaluate('(el)=>getComputedStyle(el).fontSize'))
            self.assertEqual(save.evaluate('(el)=>getComputedStyle(el).padding'),reload.evaluate('(el)=>getComputedStyle(el).padding'))
            self.assertGreaterEqual(a['x'],0);self.assertLessEqual(b['x']+b['width'],width)
            grid=page.locator('#employee-grid').bounding_box()
            artifact_path(f'tm-save-button-geometry-{width}.json').write_text(json.dumps({'viewport':width,'save':a,'reload':b,'grid_top':grid['y']}))
            self.assertLessEqual(grid['y']-max(a['y']+a['height'],b['y']+b['height']),50)
            if width<=390:expect(page.locator('.table-scroll-hint')).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.screenshot(path=str(artifact_path(f'tm-cleared-save-buttons-{width}.png')),full_page=True)
        page.locator('#reload-rows').focus()
        with page.expect_response(lambda response:'/api/customers?' in response.url):page.keyboard.press('Enter')
        expect(page.locator('#employee-grid')).to_have_attribute('aria-busy','false');self.assert_state('-')
        self.edit('call_result','INTERESTED');self.save();self.assert_state('완료')
        page.reload();self.assert_state('완료')
        self.assertEqual(self.errors,[])

    def test_failed_clear_displays_confirmed_completion_and_retry_reopens(self):
        self.page.clock.install();self.seed();page=self.page
        self.edit('call_result','NO_ANSWER');self.save();self.assert_state('완료')
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 저장 실패'}})
        page.route('**/api/employee/batch-update',fail)
        self.edit('call_result','');page.clock.fast_forward(91000)
        expect(page.locator('#pending-panel')).to_contain_text('결과를 확인하지 못했습니다')
        self.assert_state('완료')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.row.pk).call_result),'NO_ANSWER')
        page.unroute('**/api/employee/batch-update',fail);self.save();self.assert_state('-')
        page.reload();self.assert_state('-')

    def test_kst_midnight_automatically_refreshes_without_discarding_work(self):
        self.page.clock.install();self.seed();page=self.page
        self.edit('call_result','NO_ANSWER');self.save();self.assert_state('완료')
        tomorrow=self.start+timedelta(days=1)
        phase={'next':False}
        def clocked(route):
            if phase['next']:
                with patch('django.utils.timezone.now',return_value=tomorrow):response=route.fetch()
                route.fulfill(response=response)
            else:
                response=route.fetch();data=response.json();data['as_of']=(tomorrow-timedelta(seconds=1)).isoformat();route.fulfill(response=response,json=data)
        self.db(lambda:Session.objects.update(expire_date=tomorrow+timedelta(days=1)))
        page.route('**/api/customers?*',clocked)
        with page.expect_response(lambda response:'/api/customers?' in response.url):page.locator('#reload-rows').click()
        expect(page.locator('#employee-grid')).to_have_attribute('aria-busy','false')
        expect(page.locator('#tm-business-date')).to_contain_text(self.start.date().isoformat())
        self.edit('notes','자정에 보존할 가상 변경')
        phase['next']=True;page.clock.fast_forward(31000)
        expect(page.locator('#employee-grid .tabulator-row')).to_have_count(1)
        expect(page.locator('#queue-status')).to_contain_text('저장 대기')
        self.save()
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.row.pk).notes),'자정에 보존할 가상 변경')
        page.clock.fast_forward(31000)
        expect(page.locator('#employee-grid .tabulator-row')).to_have_count(0)
        expect(page.locator('#list-state')).to_contain_text('오늘의 TM 고객이 없습니다.')
        expect(page.locator('#tm-business-date')).to_contain_text(tomorrow.date().isoformat())
        self.assertEqual(self.errors,[])
