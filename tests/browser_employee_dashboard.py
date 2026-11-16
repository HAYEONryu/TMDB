from datetime import datetime, timedelta, time
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect

from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class EmployeeDashboardBrowserTests(Fixtures, StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed(self):
        def create():
            now=timezone.now();start=datetime.combine(now.astimezone(KST).date(),time.min,KST)
            a,b,c,d=self.customers(4)
            for row in [a,b]:self.assign(row,at=start)
            for row in [c,d]:self.assign(row,at=start-timedelta(days=1))
            foreign=self.customers(offset=20)[0];self.assign(foreign,self.other)
            outside=self.customers(site=self.second,offset=30)[0];self.assign(outside,at=start)
            for row,day in [(a,0),(c,-1),(d,1)]:
                Callback.objects.create(customer=row,due_at=now+(start+timedelta(days=1)-now)/2 if day==0 else start+timedelta(days=day),created_by=self.employee,updated_by=self.employee)
            Customer.objects.filter(pk=a.pk).update(visit_at=start+timedelta(hours=9),contract_status='CONTRACTED',notes='대시보드 가상 상담',admin_notes='SYNTHETIC_PRIVATE_ADMIN')
            Customer.objects.filter(pk=d.pk).update(visit_at=start+timedelta(hours=15))
            Customer.objects.filter(pk=foreign.pk).update(contract_status='CONTRACTED',notes='SYNTHETIC_FOREIGN_OWNER')
            ConsultationRevision.objects.create(customer=a,assignment=a.current_assignment,actor=self.employee,
                saved_at=now,customer_version=1,changed_fields=['notes'],source='MANUAL')
            return a,b,c,d,foreign,outside
        self.a,self.b,self.c,self.d,self.foreign,self.outside=self.db(create)

    def test_requested_employee_layout_clickable_metrics_visits_contracts_and_mobile(self):
        self.seed();self.login(self.employee);page=self.page
        expect(page.locator('.quick-work')).to_have_count(0);expect(page.locator('.dashboard-detail')).to_have_count(0)
        expect(page.locator('#employee-consultation-value')).to_have_text('1 / 2명')
        expect(page.locator('#employee-callback-completed')).to_have_text('0건')
        expect(page.locator('[data-customer-category=contracted]')).to_have_text('1명')
        expect(page.locator('#employee-today-schedule tbody tr')).to_have_count(2)
        expect(page.locator('#employee-today-schedule')).to_contain_text('상담 예정 고객 2명')
        expect(page.locator(f'#employee-today-schedule tr[data-customer-id="{self.a.pk}"] .schedule-event')).to_have_count(2)
        expect(page.locator('#employee-today-schedule')).to_contain_text('방문예약')
        expect(page.locator('#employee-today-schedule')).to_contain_text('재콜')
        for category,ids in [('held',[self.a,self.b,self.c,self.d]),('callbacks_remaining',[self.a]),('new_today',[self.a,self.b]),('overdue',[self.c]),('visits',[self.a,self.d]),('contracted',[self.a])]:
            button=page.locator(f'[data-customer-category="{category}"]');button.click()
            expect(button).to_have_attribute('aria-expanded','true')
            expect(page.locator('#employee-customer-panel')).to_be_visible()
            expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(len(ids))
            actual=page.locator('#employee-customer-list .employee-customer').evaluate_all('rows=>rows.map(r=>r.dataset.customerId)')
            self.assertCountEqual(actual,[str(row.pk) for row in ids])
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list')).to_contain_text('대시보드 가상 상담')
        self.assertNotIn('SYNTHETIC_PRIVATE_ADMIN',page.locator('body').inner_text())
        self.assertNotIn('SYNTHETIC_FOREIGN_OWNER',page.locator('body').inner_text())
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            schedule=page.locator('#employee-today-schedule')
            schedule.scroll_into_view_if_needed()
            expect(schedule.locator('tbody tr').first).to_be_visible()
            schedule.screenshot(path=str(artifact_path(f'employee-today-schedule-{width}.png')))
            page.screenshot(path=str(artifact_path(f'employee-dashboard-{width}.png')),full_page=True)
        page.locator('#employee-customer-close').click();expect(page.locator('#employee-customer-panel')).not_to_be_visible()
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#employee-consultation-value')).to_have_text('0 / 1명')
        expect(page.locator('[data-customer-category=contracted]')).to_have_text('0명')
        expect(page.locator('#employee-today-schedule')).to_contain_text('오늘 예정된 재콜·방문예약 고객이 없습니다.')
        page.locator('[data-customer-category=visits]').click();expect(page.locator('#employee-customer-list')).to_contain_text('오늘 방문예약이 없습니다.')
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer h4')).to_have_text([self.outside.customer_name])
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_customer_pagination_and_stale_responses_do_not_cross_selected_sites(self):
        self.seed()
        def extra():
            for row in self.customers(8,offset=50):self.assign(row)
        self.db(extra);self.login(self.employee);page=self.page
        expect(page.locator('#employee-consultation-value')).to_be_visible()
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(10)
        page.get_by_role('button',name='고객 목록 다음 페이지').click()
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(2)
        held=[]
        def delay(route):held.append((route,route.fetch()))
        page.route('**/api/dashboard/customers?category=callbacks_remaining*',delay)
        page.locator('[data-customer-category="callbacks_remaining"]').click()
        page.wait_for_function("document.querySelector('#employee-customer-list').getAttribute('aria-busy')==='true'")
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#employee-consultation-value')).to_have_text('0 / 1명')
        for route,response in held:route.fulfill(response=response)
        expect(page.locator('#employee-customer-panel')).not_to_be_visible()
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer h4')).to_have_text([self.outside.customer_name])
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_today_schedule_pagination_retry_stale_site_response_and_customer_link(self):
        self.seed()
        def extra():
            for row in self.customers(10,offset=50):
                self.assign(row);Customer.objects.filter(pk=row.pk).update(visit_at=timezone.now())
        self.db(extra);self.login(self.employee);page=self.page
        schedule=page.locator('#employee-today-schedule')
        expect(schedule.locator('tbody tr')).to_have_count(10)
        page.get_by_role('button',name='오늘 상담 일정 다음 페이지').click()
        expect(schedule.locator('tbody tr')).to_have_count(2)
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 일정 실패'}})
        page.route('**/api/dashboard/customers?category=scheduled*',fail)
        page.locator('#dashboard-refresh').click()
        expect(schedule).to_contain_text('마지막 성공 목록을 표시합니다.')
        expect(schedule.locator('tbody tr')).to_have_count(2)
        page.unroute('**/api/dashboard/customers?category=scheduled*',fail)
        page.get_by_role('button',name='일정 다시 조회').click()
        expect(schedule).not_to_contain_text('가상 일정 실패')
        held=[]
        def delay(route):
            if 'site_id='+str(self.site.pk) in route.request.url:held.append((route,route.fetch()))
            else:route.continue_()
        page.route('**/api/dashboard/customers?category=scheduled*',delay)
        page.locator('#dashboard-refresh').click()
        expect(schedule).to_have_attribute('aria-busy','true')
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(schedule).to_contain_text('오늘 예정된 재콜·방문예약 고객이 없습니다.')
        for route,response in held:route.fulfill(response=response)
        expect(schedule.locator('tbody tr')).to_have_count(0)
        page.unroute('**/api/dashboard/customers?category=scheduled*',delay)
        page.locator('#employee-dashboard-site').select_option(str(self.site.pk))
        expect(schedule.locator('tbody tr')).to_have_count(10)
        phone= schedule.locator('tbody tr').first.locator('td').nth(2).inner_text().replace('-','')
        schedule.locator('tbody tr').first.locator('a').click()
        expect(page.locator('#page-info')).to_contain_text('검색 1명')
        expect(page.locator('#search')).to_have_value(phone)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
