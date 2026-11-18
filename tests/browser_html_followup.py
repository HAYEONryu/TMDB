"""Local synthetic browser acceptance for the supplied employee/admin HTML."""
from datetime import datetime,time,timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect
from apps.callbacks.models import Callback
from apps.consultations.models import PerformanceTracking
from apps.customers.models import Customer
from apps.customers.services import update_row
from apps.sites.models import GlobalSettings
from apps.sites.services import create_site
from apps.customers.queries import KST
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures
from tests.browser_filter_helpers import open_detail_filter


class HTMLFollowupBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self,count=1):
        def create():
            start=datetime.combine(timezone.localdate(timezone.now(),KST),time.min,KST)
            PerformanceTracking.objects.update_or_create(pk=1,defaults={'started_at':start-timedelta(days=40)})
            rows=self.customers(count)
            for row in rows:self.assign(row,at=start-timedelta(days=1))
            return rows
        self.rows=self.db(create)

    def visit(self,path):self.page.goto(self.live_server_url+path);self.page.wait_for_load_state('networkidle')

    def test_employee_full_result_order_scroll_search_filter_and_matching_grids(self):
        self.seed(125);self.login(self.employee);page=self.page
        self.visit('/app/employee/today')
        expect(page.locator('#page-info')).to_contain_text('50 / 125명')
        expected=['_number','last_tm_date','customer_name','phone_normalized','call_result','_deletion','residence','notes','callback_due_at','memo','visit_at']
        self.assertEqual(page.locator('#employee-grid .tabulator-col').evaluate_all('(els)=>els.slice(0,11).map(e=>e.getAttribute("tabulator-field"))'),expected)
        first=page.locator('#employee-grid .tabulator-row .missing-tm-date').first
        expect(first).to_have_text('-');self.assertEqual(first.evaluate('(e)=>getComputedStyle(e).backgroundColor'),'rgb(255, 240, 223)')
        for target in [100,125]:
            page.locator('#employee-grid .tabulator-tableholder').evaluate('(e)=>e.scrollTop=e.scrollHeight')
            try:expect(page.locator('#page-info')).to_contain_text(f'{target} / 125명')
            except AssertionError:
                import json
                artifact_path('scroll-diagnostic.json').write_text(json.dumps({'info':page.locator('#page-info').inner_text(),'notice':page.locator('#employee-message').inner_text(),'state':page.locator('#list-state').inner_text(),'errors':self.errors,'geometry':page.locator('#employee-grid .tabulator-tableholder').evaluate('(e)=>({top:e.scrollTop,height:e.clientHeight,scroll:e.scrollHeight})')}))
                page.screenshot(path=str(artifact_path('scroll-failure.png')),full_page=True)
                raise
        self.assertEqual(page.evaluate("new Set(Tabulator.findTable('#employee-grid')[0].getData().map(r=>r.id)).size"),125)
        self.assertEqual(page.evaluate("Tabulator.findTable('#employee-grid')[0].getData().map(row => row._number)"),list(range(1,126)))
        page.locator('[data-sort-field=customer_name]').focus();page.keyboard.press('Enter');expect(page.locator('#page-info')).to_contain_text('50 / 125명')
        expect(page.locator('.tabulator-col[tabulator-field=customer_name]')).to_have_attribute('aria-sort','ascending')
        page.locator('[data-sort-field=customer_name]').click();expect(page.locator('.tabulator-col[tabulator-field=customer_name]')).to_have_attribute('aria-sort','descending')
        expect(page.locator('#employee-grid .tabulator-row [tabulator-field=customer_name]').first).to_have_text('가상고객0124')
        page.locator('#search').fill('0124');page.locator('#search-form button').click();expect(page.locator('#result-count')).to_have_text('검색 결과 1명')
        expect(page.locator('#employee-grid .tabulator-row [tabulator-field=_number]')).to_have_text('1')
        page.locator('#clear-filters').click();expect(page.locator('#result-count')).to_have_text('검색 결과 125명')
        open_detail_filter(page,'callback_due_at',match=False)
        page.locator('#filter-dialog').press('Escape')
        self.visit('/app/employee/mine')
        self.assertEqual(page.locator('#employee-grid .tabulator-col').evaluate_all('(els)=>els.slice(0,11).map(e=>e.getAttribute("tabulator-field"))'),expected)
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960});page.locator('#employee-grid .tabulator-tableholder').evaluate('(e)=>e.scrollLeft=0')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            a=page.locator('#save-now').bounding_box();b=page.locator('#reload-rows').bounding_box();self.assertAlmostEqual(a['height'],b['height'],delta=1)
            page.screenshot(path=str(artifact_path(f'followup-employee-grid-{width}.png')),full_page=True)
        self.assertEqual(self.errors,[])

    def test_schedule_inline_full_details_close_focus_and_month_at_bottom(self):
        self.seed();row=self.rows[0]
        self.db(lambda:Customer.objects.filter(pk=row.pk).update(notes='전체 상담내용 '+('긴 대화 기록. '*80),residence='가상 거주지',visit_at=timezone.now()))
        self.login(self.employee);page=self.page
        expect(page.locator('#today-call-attempts')).to_have_text('0콜')
        expect(page.locator('#today-call-connected')).to_have_text('0콜')
        control=page.locator('#employee-today-schedule .text-control').first;control.click()
        expect(page.locator('#schedule-customer-detail')).to_be_visible();expect(page.locator('#schedule-customer-content')).to_contain_text('가상 거주지')
        expect(page.locator('#schedule-customer-content')).to_contain_text('긴 대화 기록. '*80)
        self.assertEqual(page.url,self.live_server_url+'/app/employee')
        page.locator('#close-schedule-customer').focus();page.keyboard.press('Enter');expect(control).to_be_focused()
        expect(page.locator('#schedule-customer-detail')).to_be_hidden()
        expect(page.locator('#month-call-total')).to_have_text('0콜')
        self.assertEqual(page.locator('.dashboard-home>section').last.get_attribute('id'),'monthly-performance')
        page.locator('#performance-day').select_option(str(timezone.localdate(timezone.now(),KST)));expect(page.locator('#performance-day-values')).to_contain_text('콜 수 0콜')
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.screenshot(path=str(artifact_path(f'followup-employee-dashboard-{width}.png')),full_page=True)
        self.assertEqual(self.errors,[])

    def test_lookup_and_default_independent_and_staff_monthly_details(self):
        self.seed();self.login(self.admin);page=self.page
        new_default, _ = self.db(lambda: create_site(self.admin, '새 기본 가상 현장'))
        page.locator('#default-site').select_option(str(self.second.pk));expect(page.locator('#dashboard-updated')).to_contain_text(self.second.name)
        page.locator('#set-default').click();expect(page.locator('#service-default-site')).to_have_value(str(self.site.pk))
        page.locator('#service-default-site').select_option(str(new_default.pk));page.locator('#default-site-save').click()
        expect(page.locator('#default-site-dialog')).to_be_hidden();expect(page.locator('#default-site')).to_have_value(str(self.second.pk))
        self.assertEqual(self.db(lambda:GlobalSettings.objects.get(pk=1).default_site_id),new_default.pk)
        expect(page.locator('#staff-record-preview meter')).to_have_count(2)
        expect(page.locator('.legacy-chart').first).not_to_have_attribute('open','')
        page.locator('[data-staff-detail]').first.click();expect(page.locator('#staff-day-detail')).to_be_visible()
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.screenshot(path=str(artifact_path(f'followup-admin-dashboard-{width}.png')),full_page=True)
        page.set_viewport_size({'width':1440,'height':960})
        page.get_by_role('link',name='DB 관리',exact=True).click();expect(page.locator('#site')).to_have_value(str(new_default.pk))
        self.login(self.employee)
        expect(page.locator('#employee-dashboard-site')).to_have_value(str(new_default.pk))
        self.assertEqual(self.errors,[])

    def test_assignment_select_all_subset_distribution_confirm_and_recall(self):
        self.seed(2);self.db(lambda:self.customers(6,offset=20));self.login(self.admin);self.visit('/app/admin/assignments');page=self.page
        page.locator('#assignment-select-all').check();expect(page.locator('#assignment-selection-count')).to_have_text('2명 선택')
        page.locator(f'[data-assign-staff="{self.other.pk}"]').uncheck();expect(page.locator('#assignment-select-all')).not_to_be_checked()
        page.locator('#assignment-quantity').fill('1');page.locator('#distribute').click()
        expect(page.locator('#action-confirm-dialog h2')).to_have_text('고객 분배 확인')
        page.locator('#action-confirm-accept').click();expect(page.locator('#assignment-result')).to_contain_text('1명을 배정')
        page.locator('#tm-recall').click();expect(page.locator('#tm-recall-context')).to_contain_text('합계 3명')
        page.locator('#tm-recall-confirm').click();expect(page.locator('#assignment-result')).to_contain_text('3명을 회수')
        self.assertEqual(self.db(lambda:Customer.objects.filter(current_assignment__employee=self.employee).count()),0)
        self.assertEqual(self.errors,[])

    def test_manual_assignees_remain_after_distributing_ten_more(self):
        rows = self.db(lambda: self.customers(12))
        self.login(self.admin)
        page = self.page
        self.visit('/app/admin/customers')
        for customer in rows[:2]:
            row = page.locator('#customer-grid .tabulator-row').filter(has_text=customer.customer_name)
            row.get_by_role('button', name='담당 변경').click()
            page.locator('#assignee-target').select_option(str(self.employee.pk))
            page.locator('#assignee-confirm').click()
            expect(row.locator('[tabulator-field=assignee_name]')).to_contain_text(self.employee.name)
        def manual_assignments():
            return dict(Customer.objects.filter(pk__in=[row.pk for row in rows[:2]])
                        .values_list('pk', 'current_assignment_id'))
        before = self.db(manual_assignments)
        self.assertTrue(all(before.values()))

        self.visit('/app/admin/assignments')
        expect(page.locator('#availability-count')).to_contain_text('10명')
        page.locator(f'[data-assign-staff="{self.employee.pk}"]').check()
        page.locator('#assignment-quantity').fill('10')
        page.locator('#distribute').click()
        page.locator('#action-confirm-accept').click()
        expect(page.locator('#assignment-result')).to_contain_text('10명을 배정')
        staff = page.locator('#assignment-staff-rows tr').filter(has=page.locator(f'[data-assign-staff="{self.employee.pk}"]'))
        expect(staff.locator('td').nth(3)).to_have_text('12명')
        self.assertEqual(self.db(manual_assignments), before)

        self.login(self.employee)
        today = page.get_by_role('button', name='오늘 받은 고객 12명 목록 열기')
        expect(today).to_contain_text('12명')
        self.visit('/app/employee/today')
        expect(page.locator('#result-count')).to_have_text('검색 결과 12명')
        self.assertEqual(self.errors, [])

    def test_protected_pages_keep_original_css_and_routes(self):
        self.seed();self.login(self.admin);page=self.page
        for path in ['/app/admin/trash','/app/admin/users']:
            self.visit(path);self.assertNotIn('tm-refresh',page.locator('body').get_attribute('class'))
            properties=['fontSize','fontFamily','lineHeight','padding','margin','backgroundColor','color','borderRadius','minHeight','display','gap','gridTemplateColumns']
            def styles():return page.locator('body,header,main,h1,.btn,.card,.table,.form-control').evaluate_all('(els,props)=>els.map(e=>Object.fromEntries(props.map(p=>[p,getComputedStyle(e)[p]])))',properties)
            before=styles();page.screenshot(path=str(artifact_path(path.split('/')[-1]+'-protected.png')),full_page=True)
            # All new rules are opt-in; computed styles must be identical without it.
            page.locator('link[href$="followup.css"]').evaluate('(e)=>e.remove()')
            self.assertEqual(before,styles())
        for path in ['/app/admin/customers','/app/admin/ai','/app/admin/imports','/app/admin/assignments']:
            self.visit(path)
            for width in [1440,390,320]:
                page.set_viewport_size({'width':width,'height':960});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                page.screenshot(path=str(artifact_path(path.split('/')[-1]+f'-followup-{width}.png')),full_page=True)
            page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[])

    def test_capture_exact_html_references(self):
        directory=Path('/Users/hayeon/.codex/.chatgpt-projects/g-p-6aa239c70f6c8191986ac2a70c8e49cf/output/tmdb-figma-followup')
        if not directory.exists():self.skipTest('Reference files are local user attachments')
        context=self.browser.new_context(viewport={'width':1440,'height':960});self.addCleanup(context.close)
        page=context.new_page()
        for name,fragments in [('employee',['dashboard','today','mine']),('admin',['dashboard','db','assignments','ai'])]:
            for fragment in fragments:
                page.goto((directory/(name+'.html')).as_uri()+'#'+fragment)
                page.screenshot(path=str(artifact_path(f'reference-{name}-{fragment}-1440.png')),full_page=True)
