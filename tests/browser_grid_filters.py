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
from tests.browser_filter_helpers import open_detail_filter


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
        open_detail_filter(self.page,field)
        expect(self.page.locator('#filter-dialog')).to_be_visible()
        expect(self.page.locator('#filter-mode input[type=radio]')).to_have_count(4)

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
                self.open_filter(field);page.locator('#filter-mode input[value="EMPTY"]').check();self.apply(1)
                self.open_filter(field);expect(page.locator('#filter-mode input[value="EMPTY"]')).to_be_checked()
                page.locator('#filter-mode input[value="FILLED"]').check();self.apply(1)
                self.open_filter(field);page.locator('#filter-mode input[value="MATCH"]').check()
                page.locator('#filter-contains').fill({'notes':'핵심','memo':'일반','residence':'서울','admin_notes':'관리자'}[field]);self.apply(1)
                expect(page.locator('#active-filters')).to_contain_text('포함:');self.clear()
            for field in ['visit_at','callback_due_at','assigned_at']:
                self.open_filter(field);page.locator('#filter-mode input[value="EMPTY"]').check();self.apply(0 if field=='assigned_at' else 1);self.clear()
            self.open_filter('visit_at')
            expect(page.locator('#filter-from')).to_have_attribute('type','text')
            page.locator('#filter-from').press_sequentially('20261114');page.locator('#filter-to').fill('20261113')
            expect(page.locator('#filter-from')).to_have_value('2026-11-14')
            expect(page.locator('#filter-to')).to_have_value('2026-11-13')
            page.locator('#filter-apply').click();expect(page.locator('#filter-error')).to_contain_text('종료일')
            page.locator('#filter-from').fill('20260229');page.locator('#filter-apply').click()
            expect(page.locator('#filter-error')).to_contain_text('존재하는 날짜')
            page.locator('#filter-from').fill('2026111');page.locator('#filter-apply').click()
            expect(page.locator('#filter-error')).to_contain_text('숫자 8자리')
            page.locator('#filter-from').fill('2026-11-13');self.apply(1)
            self.open_filter('route');page.locator('#filter-mode input[value="EMPTY"]').check();self.apply(0)
            expect(page.locator('#active-filters button')).to_have_count(2)
            self.open_filter('route');page.locator('#filter-mode input[value="FILLED"]').check();self.apply(1)
            self.open_filter('route');page.locator('#filter-mode input[value="ALL"]').check();self.apply(1)
            expect(page.locator('#active-filters button')).to_have_count(1);self.clear()
            self.open_filter('visit_at');page.get_by_role('button',name='최근 7일',exact=True).click()
            start=page.locator('#filter-from').input_value();end=page.locator('#filter-to').input_value()
            self.assertEqual((datetime.fromisoformat(end)-datetime.fromisoformat(start)).days,6)
            page.get_by_role('button',name='이번 달',exact=True).click();self.assertTrue(page.locator('#filter-from').input_value().endswith('-01'))
            page.keyboard.press('Escape');self.count(2)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_manual_date_editors_optional_visit_time_validation_and_clearing(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor)
            row=page.locator(f'#{self.grid} .tabulator-row').filter(has=page.get_by_text('010-8000-0001',exact=True))
            def edit(field,value,formatted):
                cell=row.locator(f'[tabulator-field="{field}"]')
                (cell.locator('.callback-cell > span') if field=='callback_due_at' and actor==self.employee else cell).dblclick()
                control=cell.locator('input');expect(control).to_have_attribute('type','text')
                control.fill('');control.press_sequentially(value);expect(control).to_have_value(formatted)
                control.press('Enter')
            def save():
                page.locator('#save' if actor==self.admin else '#save-now').click()
                expect(page.locator('#message' if actor==self.admin else '#queue-status')).to_have_text('저장했습니다.' if actor==self.admin else '모든 변경 저장됨')

            # Opening an existing callback must preserve its stored legacy time.
            cell=row.locator('[tabulator-field="callback_due_at"]')
            (cell.locator('.callback-cell > span') if actor==self.employee else cell).dblclick()
            original=self.db(lambda:Callback.objects.get(customer=self.filled,status='PENDING').due_at)
            expect(cell.locator('input')).to_have_value('2026-11-13')
            page.locator('h1').click()
            expect(page.locator('#dirty-count' if actor==self.admin else '#queue-status')).to_have_text('변경사항 없음' if actor==self.admin else '모든 변경 저장됨')
            self.assertEqual(self.db(lambda:Callback.objects.get(customer=self.filled,status='PENDING').due_at),original)

            cell=row.locator('[tabulator-field="visit_at"]');cell.dblclick()
            cell.locator('input').fill('20260229');cell.locator('input').press('Enter')
            expect(page.locator('#message' if actor==self.admin else '#employee-message')).to_contain_text('존재하는 날짜')
            expect(cell.locator('input')).to_be_focused();cell.locator('input').press('Escape')
            for field,value,formatted in [('callback_due_at','20261114','2026-11-14'),('visit_at','202611141430','2026-11-14 14:30')]:
                edit(field,value,formatted)
            save()
            customer=self.db(lambda:Customer.objects.get(pk=self.filled.pk))
            self.assertEqual(customer.visit_at.astimezone(KST).isoformat(),'2026-11-14T14:30:00+09:00')
            callback=self.db(lambda:Callback.objects.get(customer=self.filled,status='PENDING'))
            self.assertEqual(callback.due_at.astimezone(KST).isoformat(),'2026-11-14T00:00:00+09:00')
            edit('visit_at','20261115','2026-11-15');save()
            self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.filled.pk)).visit_at.astimezone(KST).isoformat(),'2026-11-15T00:00:00+09:00')
            for field in ['callback_due_at','visit_at']:edit(field,'','')
            save()
            self.assertIsNone(self.db(lambda:Customer.objects.get(pk=self.filled.pk)).visit_at)
            self.assertFalse(self.db(lambda:Callback.objects.filter(customer=self.filled,completed_at__isnull=True,cancelled_at__isnull=True).exists()))
            # Restore the seed values before exercising the second role.
            def restore():
                Customer.objects.filter(pk=self.filled.pk).update(visit_at=datetime(2026,11,13,23,59,59,tzinfo=KST))
                Callback.objects.create(customer=self.filled,due_at=datetime(2026,11,13,23,59,59,tzinfo=KST),created_by=self.employee,updated_by=self.employee)
            self.db(restore)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_uniform_conditions_and_multi_selection_preserve_empty_contract_values(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor)
            for field in ['contract_status','customer_name','notes','visit_at']:
                self.open_filter(field)
                self.assertEqual(page.locator('#filter-mode label').all_text_contents(),['전체 보기','조건 지정','미입력만','입력된 항목만'])
                if field in ['contract_status','customer_name']:expect(page.locator('#filter-apply')).to_be_disabled()
                page.locator('#filter-mode input[value="EMPTY"]').check();expect(page.locator('.filter-condition')).not_to_be_visible();self.apply(1)
                self.open_filter(field);expect(page.locator('#filter-mode input[value="EMPTY"]')).to_be_checked()
                page.locator('#filter-mode input[value="FILLED"]').check();self.apply(1);self.clear()
            self.open_filter('contract_status')
            options=page.locator('#filter-options')
            options.get_by_role('checkbox',name='미입력',exact=True).check();options.get_by_role('checkbox',name='계약',exact=True).check()
            expect(page.locator('#filter-summary')).to_contain_text('미입력, 계약');self.apply(2)
            self.open_filter('contract_status')
            expect(options.get_by_role('checkbox',name='미입력',exact=True)).to_be_checked();expect(options.get_by_role('checkbox',name='계약',exact=True)).to_be_checked()
            page.locator('.filter-operator input[value="exclude"]').check();self.apply(0)
            self.open_filter('contract_status');page.locator('#filter-mode input[value="ALL"]').check();self.apply(2)
            expect(page.locator('#active-filters button')).to_have_count(0)
            for field in ['contract_status','notes','visit_at']:
                self.open_filter(field)
                for width in [1440,390,320]:
                    page.set_viewport_size({'width':width,'height':844})
                    expect(page.locator('#filter-apply')).to_be_in_viewport(ratio=1)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    page.screenshot(path=str(artifact_path(f'filter-{actor.role.lower()}-{field}-{width}.png')),full_page=False)
                page.keyboard.press('Escape');page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_candidate_search_paging_inclusion_exclusion_and_cancel(self):
        def create():
            rows=self.customers(105)
            for row in rows:self.assign(row)
        self.db(create);page=self.page
        for actor in [self.admin,self.employee]:
            self.open_grid(actor,105);self.open_filter('customer_name')
            expect(page.locator('#filter-options input')).to_have_count(100)
            page.get_by_role('button',name='보이는 값 모두 선택',exact=True).click()
            page.get_by_role('button',name='더 불러오기',exact=True).click();expect(page.locator('#filter-options input')).to_have_count(105)
            expect(page.locator('#filter-summary')).to_contain_text('100개 선택')
            page.get_by_role('button',name='보이는 값 모두 선택',exact=True).click();self.apply(105)
            self.open_filter('customer_name');page.locator('.filter-operator input[value="exclude"]').check();self.apply(0)
            self.clear(105);self.open_filter('customer_name')
            page.get_by_label('값 검색',exact=True).fill('가상고객0104');page.locator('#filter-dialog').get_by_role('button',name='검색',exact=True).click()
            expect(page.locator('#filter-options input')).to_have_count(1)
            page.locator('#filter-options input').check();self.apply(1)
            self.open_filter('customer_name');page.locator('#filter-mode input[value="ALL"]').check()
            page.locator('#filter-dialog [data-close]').click();self.count(1)
            self.open_filter('customer_name');expect(page.locator('#filter-mode input[value="MATCH"]')).to_be_checked()
            page.locator('#filter-mode input[value="ALL"]').check();self.apply(105)
            expect(page.locator('#active-filters button')).to_have_count(0)
            for field in (['phone_normalized','assignee_name'] if actor==self.admin else ['phone_normalized']):
                self.open_filter(field);expect(page.locator('#filter-options input').first).to_be_visible()
                if field=='phone_normalized':
                    page.locator('#filter-option-search').fill('010-8000-0104');page.locator('#filter-dialog').get_by_role('button',name='검색',exact=True).click()
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
            page.locator('#filter-reset').click();page.locator('#filter-apply').click();expect(page.locator('#filter-error')).to_contain_text('가상 조회 실패');self.count(1)
            page.unroute('**/api/customers?*',fail);self.apply(2)
            held=[]
            def hold(route):held.append(route)
            page.route('**/api/customers/filter-options?*',hold)
            with page.expect_request('**/api/customers/filter-options?*'):
                open_detail_filter(page,'customer_name')
            expect(page.locator('#filter-apply')).to_be_disabled()
            page.locator('#filter-dialog [data-close]').click();self.open_filter('notes')
            page.wait_for_function('document.querySelector("#filter-contains")!==null')
            self.assertEqual(len(held),1)
            held[0].fulfill(json={'values':['가상 늦은 응답'],'total':1,'has_next':False})
            expect(page.locator('#filter-title')).to_have_text('상세 필터');expect(page.locator('#filter-contains')).to_be_visible()
            page.locator('#filter-dialog [data-close]').click();page.unroute('**/api/customers/filter-options?*',hold)
            page.route('**/api/customers/filter-options?*',fail)
            open_detail_filter(page,'customer_name')
            expect(page.locator('#filter-options-error')).to_contain_text('가상 조회 실패');expect(page.locator('#filter-apply')).to_be_disabled()
            page.unroute('**/api/customers/filter-options?*',fail);page.get_by_role('button',name='다시 불러오기',exact=True).click();page.locator('#filter-options input').first.check();expect(page.locator('#filter-apply')).to_be_enabled()
            page.screenshot(path=str(artifact_path(f'filters-{actor.role.lower()}-desktop.png')),full_page=False)
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('#filter-apply')).to_be_in_viewport();expect(page.locator('#filter-dialog')).to_be_visible()
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            page.screenshot(path=str(artifact_path(f'filters-{actor.role.lower()}-mobile.png')),full_page=False)
            page.keyboard.press('Escape');page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_shared_search_draft_apply_chips_reset_and_role_permissions_on_three_views(self):
        self.seed();page=self.page
        for actor,path in [(self.admin,'admin/customers'),(self.employee,'employee/mine'),(self.employee,'employee/today')]:
            self.login(actor);page.goto(self.live_server_url+f'/app/{path}?site_id={self.site.pk}');self.count(2)
            self.grid='customer-grid' if actor==self.admin else 'employee-grid'
            self.assertEqual(page.locator('.query-controls').evaluate("el=>Array.from(el.querySelectorAll('#site,#search,#search-form button,#open-filters,#sort')).map(el=>el.id||'search-button')"),['site','search','search-button','open-filters','sort'])
            expect(page.locator(f'#{self.grid} .column-filter')).to_have_count(0)
            original_sort=page.locator('#sort').input_value()
            page.locator('#page-size').select_option('100');self.count(2)
            requests=[]
            def observe(r):
                if '/api/customers?' in r.url:requests.append(r.url)
            page.on('request',observe)
            page.locator('#open-filters').click()
            expect(page.locator('#filter-extra')).not_to_have_attribute('open','')
            expect(page.locator('#filter-field option[value="assignee_name"]')).to_have_count(1 if actor==self.admin else 0)
            expect(page.locator('#filter-field option[value="admin_notes"]')).to_have_count(1 if actor==self.admin else 0)
            page.locator('.filter-toggle[data-value="INTERESTED"]').click();page.locator('#basic-contract_status').select_option('CONTRACTED')
            self.assertEqual(requests,[])
            page.keyboard.press('Escape');expect(page.locator('#open-filters')).to_be_focused();self.count(2)
            page.locator('#open-filters').click();expect(page.locator('.filter-toggle[data-value="INTERESTED"]')).to_have_attribute('aria-pressed','false')
            page.locator('.filter-toggle[data-value="INTERESTED"]').click();page.locator('#basic-contract_status').select_option('CONTRACTED')
            self.apply(1);self.assertEqual(len(requests),1)
            page.remove_listener('request',observe)
            expect(page.locator('#open-filters')).to_have_text('상세 필터 (2)')
            page.locator('#search').fill('가상고객');page.locator('#search').press('Enter');self.count(1)
            expect(page.locator('#active-filters button')).to_have_count(3)
            page.screenshot(path=str(artifact_path('query-'+path.replace('/','-')+'.png')),full_page=True)
            page.locator('#open-filters').click();page.locator('#filter-reset').click();self.count(1)
            page.locator('#filter-dialog [data-close]').click();expect(page.locator('#open-filters')).to_be_focused();expect(page.locator('#open-filters')).to_have_text('상세 필터 (2)')
            open_detail_filter(page,'call_result')
            page.locator('.filter-operator input[value="exclude"]').check()
            expect(page.locator('section[data-field="call_result"] .filter-mode-badge')).to_have_text('선택한 값 제외')
            page.locator('.filter-toggle[data-value="NO_ANSWER"]').click()
            expect(page.locator('#filter-options input[value="NO_ANSWER"]')).to_be_checked()
            page.screenshot(path=str(artifact_path('query-panel-'+path.replace('/','-')+'.png')),full_page=False)
            page.locator('#filter-close').click();self.count(1)
            page.locator('#active-filters button').filter(has_text='검색 ·').click();self.count(1)
            expect(page.locator('#search')).to_have_value('');expect(page.locator('#active-filters button')).to_have_count(2)
            page.locator('#active-filters button').filter(has_text='계약여부').click();self.count(1);expect(page.locator('#open-filters')).to_have_text('상세 필터 (1)')
            page.locator('#clear-filters').click();self.count(2)
            expect(page.locator('#sort')).to_have_value(original_sort);expect(page.locator('#page-size')).to_have_value('100');expect(page.locator('#site')).to_have_value(str(self.site.pk))
            page.locator('#search').fill('010 - 8000 - 0001');page.locator('#search-form button').click();self.count(1)
            page.locator('#search').fill('---');page.locator('#search').press('Enter');self.count(0)
            expect(page.locator('#list-state-message')).to_have_text('조건에 맞는 고객이 없습니다.')
            page.locator('#empty-reset').click();self.count(2)
            page.locator('#search').fill('0001');page.locator('#search').press('Enter');self.count(1)
            page.locator('#search').fill('');page.locator('#search-form button').click();self.count(2)
            expect(page.locator('#active-filters button')).to_have_count(0)
            page.set_viewport_size({'width':320,'height':844});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
            page.screenshot(path=str(artifact_path('query-mobile-'+path.replace('/','-')+'.png')),full_page=True)
            page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_empty_states_and_failed_search_keep_last_successful_list_and_conditions(self):
        self.seed();page=self.page
        for actor,path,empty in [(self.admin,'admin/customers','등록된 고객이 없습니다.'),(self.employee,'employee/mine','담당 고객이 없습니다.'),(self.employee,'employee/today','오늘 할 일이 없습니다.')]:
            self.login(actor);page.goto(self.live_server_url+f'/app/{path}?site_id={self.site.pk}');self.count(2)
            page.locator('#search').fill('0001');page.locator('#search').press('Enter');self.count(1)
            def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 조회 실패'}})
            page.route('**/api/customers?*',fail)
            page.locator('#search').fill('없는 값');page.locator('#search-form button').click()
            expect(page.locator('#list-state-message')).to_contain_text('마지막으로 확인한 조건과 목록')
            expect(page.locator('#search')).to_have_value('0001');self.count(1)
            expect(page.locator('#active-filters')).to_contain_text('검색 · 0001')
            page.unroute('**/api/customers?*',fail);page.locator('#list-retry').click();self.count(1)
            expect(page.locator('#list-state')).not_to_be_visible()
            page.locator('#clear-filters').click();self.count(2)
            page.locator('#site').select_option(str(self.second.pk));self.count(0)
            expect(page.locator('#list-state-message')).to_have_text(empty);expect(page.locator('#empty-reset')).not_to_be_visible()
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_slow_initial_employee_response_cannot_replace_newer_search(self):
        self.seed();self.login(self.employee);page=self.page;held=[]
        def hold_first(route):
            if not held:
                held.append((route,None))
                held[0]=(route,route.fetch().json())
            else:route.continue_()
        page.route('**/api/customers?*',hold_first)
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.site.pk}')
        expect(page.locator('#list-state-message')).to_have_text('고객 목록을 불러오고 있습니다…')
        page.locator('#search').fill('0001');page.locator('#search').press('Enter');self.count(1)
        held[0][0].fulfill(json=held[0][1])
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        self.count(1);expect(page.locator('#search')).to_have_value('0001');expect(page.locator('#employee-grid .tabulator-row')).to_have_count(1)
        expect(page.locator('#active-filters')).to_contain_text('검색 · 0001');expect(page.locator('#result-count')).to_have_text('검색 결과 1건')
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_filter_apply_and_reset_preserve_pending_edits_and_cancel_draft_without_saving(self):
        self.seed();page=self.page
        self.open_grid(self.admin)
        row=page.locator('#customer-grid .tabulator-row').filter(has_text='010-8000-0001')
        cell=row.locator('[tabulator-field="notes"]');cell.click();cell.locator('textarea').fill('필터 변경 전 관리자 저장');page.locator('h1').click()
        page.locator('#open-filters').click();expect(page.locator('#dirty-dialog')).not_to_be_visible()
        page.locator('.filter-toggle[data-value="INTERESTED"]').click();page.locator('#filter-apply').click()
        expect(page.locator('#dirty-dialog')).to_be_visible();page.locator('#dirty-stay').click()
        expect(page.locator('#filter-dialog')).to_be_visible();self.count(2)
        page.locator('#filter-apply').click();page.locator('#dirty-save').click();expect(page.locator('#filter-dialog')).not_to_be_visible();self.count(1)
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.filled.pk).notes),'필터 변경 전 관리자 저장')
        row=page.locator('#customer-grid .tabulator-row').first;cell=row.locator('[tabulator-field="notes"]');cell.click();cell.locator('textarea').fill('폐기할 관리자 변경');page.locator('h1').click()
        page.locator('#clear-filters').click();page.locator('#dirty-stay').click();self.count(1)
        page.locator('#clear-filters').click();page.locator('#dirty-discard').click();self.count(2)
        self.open_grid(self.employee)
        row=page.locator('#employee-grid .tabulator-row').filter(has_text='010-8000-0001');cell=row.locator('[tabulator-field="notes"]');cell.dblclick();cell.locator('textarea').fill('필터 변경 전 직원 저장');page.locator('h1').click()
        expect(page.locator('#queue-status')).to_contain_text('저장 대기')
        page.locator('#open-filters').click();page.locator('.filter-toggle[data-value="INTERESTED"]').click();page.keyboard.press('Escape')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.filled.pk).notes),'필터 변경 전 관리자 저장')
        page.locator('#open-filters').click();page.locator('.filter-toggle[data-value="INTERESTED"]').click()
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 저장 실패'}})
        page.route('**/api/employee/batch-update',fail)
        page.locator('#filter-apply').click();expect(page.locator('#leave-dialog')).to_be_visible();page.locator('#leave-cancel').click()
        expect(page.locator('#filter-dialog')).to_be_visible();self.count(2)
        page.unroute('**/api/employee/batch-update',fail);self.apply(1)
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=self.filled.pk).notes),'필터 변경 전 직원 저장')
        expect(page.locator('#queue-status')).to_have_text('모든 변경 저장됨')
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_admin_reset_removes_incoming_assignee_condition_but_keeps_site_sort_and_size(self):
        self.seed()
        foreign=self.db(lambda:self.customers(offset=40)[0]);self.db(lambda:self.assign(foreign,self.other))
        self.login(self.admin);page=self.page
        page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.site.pk}&assignee_id={self.employee.pk}')
        self.count(2);expect(page.locator('#active-filters')).to_contain_text('담당직원 유입 조건')
        page.locator('#page-size').select_option('100');page.locator('#sort').select_option('customer_name');expect(page.locator('#search-form button')).to_be_enabled();self.count(2)
        page.locator('#search').fill('0001');page.locator('#search').press('Enter');self.count(1)
        page.locator('#clear-filters').click();self.count(3)
        expect(page.locator('#active-filters button')).to_have_count(0);expect(page.locator('#search')).to_have_value('')
        expect(page.locator('#site')).to_have_value(str(self.site.pk));expect(page.locator('#sort')).to_have_value('customer_name');expect(page.locator('#page-size')).to_have_value('100')
        self.assertNotIn('assignee_id=',page.url)
        page.reload();self.count(3)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_queued_reset_and_search_keep_new_input_during_slow_refresh(self):
        self.seed();self.open_grid(self.employee);page=self.page
        page.locator('#search').fill('0001');page.locator('#search').press('Enter');self.count(1)
        held=[]
        def hold_first(route):
            if not held:
                held.append((route,None));held[0]=(route,route.fetch().json())
            else:route.continue_()
        page.route('**/api/customers?*',hold_first)
        page.locator('#reload-rows').click()
        expect(page.locator('#list-state-message')).to_have_text('고객 목록을 불러오고 있습니다…')
        page.locator('#clear-filters').click()
        page.locator('#search').fill('010-8000-0000');page.locator('#search').press('Enter')
        held[0][0].fulfill(json=held[0][1])
        expect(page.locator('#active-filters')).to_contain_text('검색 · 010-8000-0000')
        self.count(1);expect(page.locator('#search')).to_have_value('010-8000-0000')
        expect(page.locator('#employee-grid .tabulator-row [tabulator-field="phone_normalized"]')).to_have_text('010-8000-0000')
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
