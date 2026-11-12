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
            outside=self.customers(site=self.second,offset=30)[0];self.assign(outside)
            for row,day in [(a,0),(c,-1),(d,1)]:
                Callback.objects.create(customer=row,due_at=start+timedelta(days=day),created_by=self.employee,updated_by=self.employee)
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
        expect(page.locator('#employee-tm-value')).to_have_text('33.3%(1/3)')
        expect(page.get_by_role('progressbar',name='TM 달성률')).to_have_attribute('aria-valuenow','33.3')
        expect(page.locator('#employee-site-contract-count')).to_have_text('2건')
        expect(page.locator('#employee-contracts')).to_contain_text('내 담당 고객의 계약 1건')
        expect(page.locator('#employee-visits-count')).to_have_text('2건')
        expect(page.locator('#employee-visits-list .employee-customer h4')).to_have_text([self.a.customer_name,self.d.customer_name])
        expect(page.locator('#employee-visits-list')).to_contain_text('09:00')
        for category,ids in [('held',[self.a,self.b,self.c,self.d]),('callbacks_today',[self.a]),('new_today',[self.a,self.b]),('overdue',[self.c])]:
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
            page.screenshot(path=str(artifact_path(f'employee-dashboard-{width}.png')),full_page=True)
        page.locator('#employee-customer-close').click();expect(page.locator('#employee-customer-panel')).not_to_be_visible()
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#employee-tm-value')).to_have_text('0%(0/1)')
        expect(page.locator('#employee-visits-list')).to_contain_text('오늘 방문예약이 없습니다.')
        expect(page.locator('#employee-site-contract-count')).to_have_text('0건')
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer h4')).to_have_text([self.outside.customer_name])
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_customer_pagination_and_stale_responses_do_not_cross_selected_sites(self):
        self.seed()
        def extra():
            for row in self.customers(8,offset=50):self.assign(row)
        self.db(extra);self.login(self.employee);page=self.page
        expect(page.locator('#employee-tm-value')).to_be_visible()
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(10)
        page.get_by_role('button',name='고객 목록 다음 페이지').click()
        expect(page.locator('#employee-customer-list .employee-customer')).to_have_count(2)
        held=[]
        def delay(route):held.append((route,route.fetch()))
        page.route('**/api/dashboard/customers?category=callbacks_today*',delay)
        page.locator('[data-customer-category="callbacks_today"]').click()
        page.wait_for_function("document.querySelector('#employee-customer-list').getAttribute('aria-busy')==='true'")
        page.locator('#employee-dashboard-site').select_option(str(self.second.pk))
        expect(page.locator('#employee-tm-value')).to_have_text('0%(0/1)')
        for route,response in held:route.fulfill(response=response)
        expect(page.locator('#employee-customer-panel')).not_to_be_visible()
        page.locator('[data-customer-category="held"]').click()
        expect(page.locator('#employee-customer-list .employee-customer h4')).to_have_text([self.outside.customer_name])
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
