"""Synthetic Chromium checks for blank editing and shared filter interactions."""
import re
from datetime import datetime

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect

from apps.callbacks.models import Callback
from apps.customers.models import Customer
from apps.customers.queries import KST
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class GridFilterBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self):
        def create():
            blank,filled=self.customers(2)
            blank.customer_name='';blank.save()
            filled.notes='핵심 상담';filled.memo='일반 비고';filled.residence='서울';filled.admin_notes='가상 관리자 전용'
            filled.route='티엠';filled.housing_status='무주택';filled.call_result='INTERESTED';filled.contract_status='CONTRACTED'
            filled.visit_at=datetime(2026,11,13,23,59,59,tzinfo=KST);filled.save()
            self.assign(blank);self.assign(filled)
            Callback.objects.create(customer=filled,due_at=filled.visit_at,created_by=self.employee,updated_by=self.employee)
            return blank,filled
        self.blank,self.filled=self.db(create)

    def open_grid(self,actor,total=2):
        self.login(actor)
        self.grid='customer-grid' if actor==self.admin else 'employee-grid'
        path='admin/customers' if actor==self.admin else 'employee/mine'
        self.page.goto(self.live_server_url+f'/app/{path}?site_id={self.site.pk}')
        self.count(total)

    def count(self,total):
        expect(self.page.locator('#page-info')).to_contain_text(f'검색 {total}건')

    def open_filter(self,field):
        self.page.locator(f'#{self.grid} .tabulator-header [tabulator-field="{field}"] .column-filter').click()
        expect(self.page.locator('#filter-dialog')).to_be_visible()
        expect(self.page.locator('#filter-apply')).to_be_enabled()

    def apply(self,total):
        self.page.locator('#filter-apply').click()
        expect(self.page.locator('#filter-dialog')).not_to_be_visible();self.count(total)

    def clear(self,total=2):
        self.page.locator('#clear-filters').click();self.count(total)

    def test_empty_display_and_fixed_choices_return_to_dash_for_both_roles(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor)
            row=page.locator(f'#{self.grid} .tabulator-row').filter(has=page.get_by_text('010-8000-0000',exact=True))
            fields=['customer_name','contract_status','call_result','callback_due_at','visit_at','residence','housing_status','notes','route','memo']
            for field in fields:
                expect(row.locator(f'[tabulator-field="{field}"]')).to_have_text('-')
            for empty in [False,True]:
                for field,value in {'contract_status':'CONTRACTED','call_result':'INTERESTED','housing_status':'무주택','route':'티엠'}.items():
                    cell=row.locator(f'[tabulator-field="{field}"]');cell.click()
                    value=('UNKNOWN' if field=='contract_status' else '') if empty else value
                    if actor==self.admin:
                        title='-' if empty else {'CONTRACTED':'계약','INTERESTED':'가망고객'}.get(value,value)
                        page.locator('.tabulator-edit-list-item').filter(has_text=re.compile('^'+re.escape(title)+'$')).click()
                    else:cell.locator('select').select_option(value)
                    page.locator('h1').click()
                page.locator('#save' if actor==self.admin else '#save-now').click()
                expect(page.locator('#message' if actor==self.admin else '#queue-status')).to_have_text('저장했습니다.' if actor==self.admin else '모든 변경 저장됨')
            saved=self.db(lambda:Customer.objects.get(pk=self.blank.pk))
            self.assertEqual((saved.contract_status,saved.call_result,saved.housing_status,saved.route),('UNKNOWN',None,'',''))
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_text_date_blank_filled_exclusion_and_combined_filters(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor)
            for field in ['notes','memo','residence',*(['admin_notes'] if actor==self.admin else [])]:
                self.open_filter(field);page.locator('#filter-mode').select_option('EMPTY');self.apply(1)
                self.open_filter(field);expect(page.locator('#filter-mode')).to_have_value('EMPTY')
                page.locator('#filter-mode').select_option('FILLED');self.apply(1)
                self.open_filter(field);page.locator('#filter-mode').select_option('MATCH')
                page.locator('#filter-contains').fill({'notes':'핵심','memo':'일반','residence':'서울','admin_notes':'관리자'}[field]);self.apply(1)
                expect(page.locator('#active-filters')).to_contain_text('포함:');self.clear()
            for field in ['visit_at','callback_due_at','assigned_at']:
                self.open_filter(field);page.locator('#filter-mode').select_option('EMPTY');self.apply(0 if field=='assigned_at' else 1);self.clear()
            self.open_filter('visit_at')
            page.locator('#filter-from').fill('2026-11-14');page.locator('#filter-to').fill('2026-11-13')
            page.locator('#filter-apply').click();expect(page.locator('#filter-error')).to_contain_text('종료일')
            page.locator('#filter-from').fill('2026-11-13');self.apply(1)
            self.open_filter('route');page.locator('#filter-choice').select_option('EMPTY');self.apply(0)
            expect(page.locator('#active-filters button')).to_have_count(2)
            self.open_filter('route');page.locator('#filter-choice-mode').select_option('exclude');self.apply(1)
            self.open_filter('route');page.locator('#filter-reset').click();expect(page.locator('#filter-dialog')).not_to_be_visible();self.count(1)
            expect(page.locator('#active-filters button')).to_have_count(1);self.clear()
            self.open_filter('visit_at');page.get_by_role('button',name='최근 7일',exact=True).click()
            start=page.locator('#filter-from').input_value();end=page.locator('#filter-to').input_value()
            self.assertEqual((datetime.fromisoformat(end)-datetime.fromisoformat(start)).days,6)
            page.get_by_role('button',name='이번 달',exact=True).click();self.assertTrue(page.locator('#filter-from').input_value().endswith('-01'))
            page.keyboard.press('Escape');self.count(2)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_candidate_search_paging_inclusion_exclusion_and_cancel(self):
        def create():
            rows=self.customers(105)
            for row in rows:self.assign(row)
        self.db(create);page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor,105);self.open_filter('customer_name')
            expect(page.locator('#filter-options input')).to_have_count(100)
            page.get_by_role('button',name='이 페이지 선택',exact=True).click()
            page.get_by_role('button',name='다음 후보',exact=True).click();expect(page.locator('#filter-options input')).to_have_count(5)
            expect(page.locator('#filter-summary')).to_contain_text('100개 값')
            page.get_by_role('button',name='이 페이지 선택',exact=True).click();self.apply(105)
            self.open_filter('customer_name');page.locator('#filter-list-mode').select_option('EXCLUDE');self.apply(0)
            self.clear(105);self.open_filter('customer_name')
            page.get_by_label('후보값 검색',exact=True).fill('가상고객0104');page.get_by_role('button',name='후보 검색',exact=True).click()
            expect(page.locator('#filter-options input')).to_have_count(1)
            page.locator('#filter-options input').check();self.apply(1)
            self.open_filter('customer_name');page.locator('#filter-list-mode').select_option('ALL')
            page.locator('#filter-dialog [data-close]').click();self.count(1)
            self.open_filter('customer_name');expect(page.locator('#filter-list-mode')).to_have_value('INCLUDE')
            page.locator('#filter-list-mode').select_option('ALL');self.apply(105)
            expect(page.locator('#active-filters button')).to_have_count(0)
            for field in ['phone_normalized','assignee_name']:
                self.open_filter(field);expect(page.locator('#filter-options input').first).to_be_visible()
                if field=='phone_normalized':
                    page.locator('#filter-option-search').fill('010-8000-0104');page.get_by_role('button',name='후보 검색',exact=True).click()
                    expect(page.locator('#filter-options input')).to_have_count(1)
                page.locator('#filter-options input').first.check();self.apply(1 if field=='phone_normalized' else 105);self.clear(105)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_failed_apply_reset_candidate_retry_stale_response_and_mobile(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor);self.open_filter('notes');page.locator('#filter-contains').fill('핵심')
            def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 조회 실패'}})
            page.route('**/api/customers?*',fail)
            page.locator('#filter-apply').click();expect(page.locator('#filter-error')).to_contain_text('가상 조회 실패');self.count(2)
            expect(page.locator('#active-filters button')).to_have_count(0)
            page.unroute('**/api/customers?*',fail);self.apply(1)
            self.open_filter('notes');page.route('**/api/customers?*',fail)
            page.locator('#filter-reset').click();expect(page.locator('#filter-error')).to_contain_text('가상 조회 실패');self.count(1)
            page.unroute('**/api/customers?*',fail);page.locator('#filter-reset').click();expect(page.locator('#filter-dialog')).not_to_be_visible();self.count(2)
            held=[]
            def hold(route):held.append(route)
            page.route('**/api/customers/filter-options?*',hold)
            with page.expect_request('**/api/customers/filter-options?*'):
                page.locator(f'#{self.grid} .tabulator-header [tabulator-field="customer_name"] .column-filter').click()
            expect(page.locator('#filter-apply')).to_be_disabled()
            page.locator('#filter-dialog [data-close]').click();self.open_filter('notes')
            page.wait_for_function('document.querySelector("#filter-contains")!==null')
            self.assertEqual(len(held),1)
            held[0].fulfill(json={'values':['가상 늦은 응답'],'total':1,'has_next':False})
            expect(page.locator('#filter-title')).to_have_text('상담내용 필터');expect(page.locator('#filter-contains')).to_be_visible()
            page.locator('#filter-dialog [data-close]').click();page.unroute('**/api/customers/filter-options?*',hold)
            page.route('**/api/customers/filter-options?*',fail)
            page.locator(f'#{self.grid} .tabulator-header [tabulator-field="customer_name"] .column-filter').click()
            expect(page.locator('#filter-error')).to_contain_text('가상 조회 실패');expect(page.locator('#filter-apply')).to_be_disabled()
            page.unroute('**/api/customers/filter-options?*',fail);page.get_by_role('button',name='후보 검색',exact=True).click();expect(page.locator('#filter-apply')).to_be_enabled()
            page.screenshot(path=str(artifact_path(f'filters-{actor.role.lower()}-desktop.png')),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('#filter-apply')).to_be_in_viewport();expect(page.locator('#filter-dialog')).to_be_visible()
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            page.screenshot(path=str(artifact_path(f'filters-{actor.role.lower()}-mobile.png')),full_page=True)
            page.keyboard.press('Escape');page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
