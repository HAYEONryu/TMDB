"""Cards, workload rows and destination lists use the same current-state cohorts."""
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.sites.models import GlobalSettings
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.helpers import user
from tests.test_p4 import Fixtures


class DashboardActionsBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self):
        def create():
            now=timezone.now();start=datetime.combine(now.astimezone(KST).date(),time.min,KST)
            a,recalled,b,inactive,future,free,trash=self.customers(7)
            self.assign(a,at=start);self.assign(recalled,at=start);self.assign(b,self.other,at=start)
            result,status=change_assignee(self.admin,recalled.pk,self.assignee_body(recalled));self.assertEqual(status,200)
            person=user('01000000004',initial=False,name='가상 비활성 직원');self.assign(inactive,person,at=start,progress=True)
            User.objects.filter(pk=person.pk).update(is_active=False)
            self.assign(future,at=now+timedelta(days=1))
            Customer.objects.filter(pk=trash.pk).update(deleted_at=now,deleted_by=self.admin)
            Customer.objects.filter(pk=a.pk).update(contract_status='CONTRACTED',admin_notes='SYNTHETIC_PRIVATE_DASHBOARD')
            for row in [a,inactive]:Callback.objects.create(customer=row,due_at=now-timedelta(minutes=1),created_by=self.admin,updated_by=self.admin)
            outside=self.customers(site=self.second,offset=20)[0];self.assign(outside,at=start)
            outside_inactive=self.customers(site=self.second,offset=21)[0];self.assign(outside_inactive,person,at=start,progress=True)
            return a,recalled,b,inactive,future,free,trash,outside,person
        self.a,self.recalled,self.b,self.inactive,self.future,self.free,self.trash,self.outside,self.inactive_person=self.db(create)

    def metric(self,category):return self.page.locator(f'#dashboard-summary [data-metric="{category}"] dd')
    def ready(self):expect(self.page.locator('#dashboard-message')).to_have_attribute('data-state','success')

    def test_admin_cards_staff_sums_keyboard_links_selected_site_and_history(self):
        self.seed();self.login(self.admin);page=self.page;self.ready()
        before=self.db(lambda:GlobalSettings.objects.get(pk=1).version)
        expect(page.locator('.quick-work')).to_have_count(0)
        expect(page.locator('#daily-consultation-chart svg rect')).to_have_count(7)
        expect(page.locator('#contract-status-chart [data-contract-status=CONTRACTED]')).to_contain_text('1명')
        expect(page.locator('#staff-performance-table tbody tr')).to_have_count(3)
        expect(page.locator('#staff-performance-table')).to_contain_text('비활성 직원')
        for category,count in [('unassigned',3),('new_today',3),('overdue',2),('transfer',1)]:expect(self.metric(category)).to_have_text(f'{count}명')
        self.assertEqual(page.locator('#graph-site').count(),0)
        expect(page.locator('#result-period option')).to_have_text(['현재 고객 상태','금주','오늘'])
        expect(page.locator('#staff-progress-table')).to_contain_text('비활성 직원')
        expect(page.locator('#staff-progress-table')).to_contain_text('재콜 우선')
        rows=page.locator('#staff-progress-table tbody tr').evaluate_all('rows=>rows.map(row=>Array.from(row.cells).slice(2).map(c=>Number(c.textContent)))')
        self.assertEqual([sum(row[i] for row in rows) for i in range(4)],[3,3,2,2])
        page.locator('.dashboard-detail summary').click();expect(page.locator('#staff-allocation-table')).to_contain_text('오늘 배정 작업')
        expect(page.locator('#daily-work')).to_contain_text('배정 이력은 회수·재배정·휴지통 이동 후에도 남습니다.')
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.evaluate('scrollTo(0,0)');page.screenshot(path=str(artifact_path(f'admin-actions-{width}.png')),full_page=True)
        page.set_viewport_size({'width':1440,'height':960})
        link=page.locator('#dashboard-summary [data-metric="new_today"] a');link.focus();page.keyboard.press('Enter')
        expect(page.locator('#page-info')).to_contain_text('검색 3건')
        expect(page.locator('#active-filters')).to_contain_text('대시보드 · 오늘 배정 유지')
        names=page.locator('#customer-grid .tabulator-row [tabulator-field="customer_name"]').all_text_contents()
        self.assertCountEqual(names,[self.a.customer_name,self.b.customer_name,self.inactive.customer_name])
        expect(page.locator('#result-count')).to_contain_text('조회')
        page.locator('#clear-filters').click();expect(page.locator('#page-info')).to_contain_text('검색 6건')
        page.goto(self.live_server_url+'/app/admin?site_id='+str(self.site.pk));self.ready()
        staff_link=page.locator(f'#staff-progress-table tr[data-employee-id="{self.inactive_person.pk}"] td').nth(3).locator('a')
        staff_link.click();expect(page.locator('#page-info')).to_contain_text('검색 1건');expect(page.locator('#customer-grid .tabulator-row [tabulator-field="customer_name"]')).to_have_text(self.inactive.customer_name)
        page.goto(self.live_server_url+'/app/admin?site_id='+str(self.site.pk));self.ready()
        page.locator('#dashboard-summary [data-metric="transfer"] a').click()
        expect(page.locator('#transfer-page')).to_contain_text('이관 필요 1건')
        expect(page.locator('#transfer-page')).to_contain_text('조회')
        expect(page.locator('#transfer-rows tr')).to_have_count(1);expect(page.locator('#transfer-rows')).to_contain_text(self.inactive.customer_name)
        self.assertEqual(self.db(lambda:GlobalSettings.objects.get(pk=1).version),before)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_both_roles_keep_last_success_on_failure_clear_new_site_and_ignore_late_response(self):
        self.seed();page=self.page
        for actor in [self.admin,self.employee]:
            self.login(actor);self.ready();select=page.locator('#default-site' if actor==self.admin else '#employee-dashboard-site')
            baseline=page.locator('#dashboard-summary').inner_text();updated=page.locator('#dashboard-updated').inner_text()
            def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 갱신 실패'}})
            page.route('**/api/dashboard?*',fail)
            page.locator('#dashboard-refresh').click();expect(page.locator('#dashboard-message')).to_contain_text('갱신 실패 · 마지막 성공 결과')
            self.assertEqual(page.locator('#dashboard-summary').inner_text(),baseline);expect(page.locator('#dashboard-updated')).to_have_text(updated)
            select.select_option(str(self.second.pk));expect(page.locator('#dashboard-message')).to_contain_text('조회 실패')
            expect(page.locator('#dashboard-summary .overview-metric')).to_have_count(0)
            expect(page.locator('#dashboard-updated')).to_have_text('이 현장의 조회 성공 기록이 없습니다.')
            if actor==self.admin:expect(page.locator('#staff-progress-table tr[data-employee-id]')).to_have_count(0)
            else:expect(page.locator('#employee-contracts')).to_be_empty()
            page.unroute('**/api/dashboard?*',fail);select.select_option(str(self.site.pk));self.ready()
            held=[]
            def delay(route):
                if not held:
                    held.append((route,None));held[0]=(route,route.fetch())
                else:route.continue_()
            page.route('**/api/dashboard?*',delay)
            select.select_option(str(self.second.pk));expect(page.locator('#dashboard-message')).to_have_text('최초 조회 중…')
            expect(page.locator('#dashboard-summary .overview-metric')).to_have_count(0)
            select.select_option(str(self.site.pk));self.ready()
            held[0][0].fulfill(response=held[0][1]);page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            expect(select).to_have_value(str(self.site.pk));self.assertEqual(page.locator('#dashboard-summary').inner_text(),baseline)
            page.unroute('**/api/dashboard?*',delay)
            if actor==self.admin:
                page.route('**/api/dashboard?*',fail);page.locator('#result-period').select_option('today')
                expect(page.locator('#dashboard-message')).to_have_attribute('data-state','error');expect(page.locator('#result-period')).to_have_value('all')
                expect(page.locator('#call-result-chart svg')).to_have_count(1);page.unroute('**/api/dashboard?*',fail)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_employee_card_customer_open_uses_own_scope_and_list_failure_keeps_results(self):
        self.seed();self.login(self.employee);self.ready();page=self.page
        button=page.locator('[data-customer-category=new_today]');button.focus();page.keyboard.press('Enter')
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(1)
        expect(page.locator('#employee-customer-list .customer-list-summary')).to_contain_text('목록 조회')
        self.assertNotIn('SYNTHETIC_PRIVATE_DASHBOARD',page.locator('body').inner_text())
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 목록 실패'}})
        page.route('**/api/dashboard/customers?*',fail);page.locator('#dashboard-refresh').click()
        expect(page.locator('#employee-customer-list')).to_contain_text('마지막 성공 목록')
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(1)
        page.unroute('**/api/dashboard/customers?*',fail);page.get_by_role('button',name='목록 다시 조회').click()
        expect(page.locator('#employee-customer-list')).not_to_contain_text('가상 목록 실패')
        page.locator('#employee-customer-list a').click()
        expect(page.locator('#page-info')).to_contain_text('검색 1건');expect(page.locator('#search')).to_have_value(self.a.phone_normalized)
        expect(page.locator('#employee-grid [tabulator-field="admin_notes"]')).to_have_count(0)
        expect(page.locator('#employee-grid .tabulator-row [tabulator-field="customer_name"]')).to_have_text(self.a.customer_name)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_site_list_initial_failure_is_not_zero_or_loading_and_refresh_recovers(self):
        self.seed();page=self.page;writes=[]
        page.on('request',lambda r:writes.append(r.method) if '/api/' in r.url and r.method not in ['GET','HEAD'] else None)
        for actor in [self.admin,self.employee]:
            def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 현장 조회 실패'}})
            page.route('**/api/sites',fail);self.login(actor)
            expect(page.locator('#dashboard-message')).to_have_attribute('data-state','error')
            expect(page.locator('#dashboard-message')).to_contain_text('현장 목록 조회 실패')
            expect(page.locator('#dashboard-summary .overview-metric')).to_have_count(0)
            expect(page.locator('#dashboard-summary')).to_have_attribute('aria-busy','false')
            expect(page.locator('#dashboard-updated')).to_have_text('조회 성공 기록이 없습니다.')
            page.unroute('**/api/sites',fail);page.locator('#dashboard-refresh').click();self.ready()
            expect(page.locator('#dashboard-summary .overview-metric')).to_have_count(4)
        self.assertEqual(writes,[]);self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
