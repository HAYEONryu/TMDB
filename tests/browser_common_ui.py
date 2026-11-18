"""Synthetic screen inventory, responsive shell and shared interaction contracts."""
from datetime import timedelta
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect
from apps.callbacks.models import Callback
from apps.customers.models import Customer
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class CommonUIBrowserTests(Fixtures, StaticLiveServerTestCase):
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def setUp(self):
        metadata.CustomerMetadataBrowserTests.setUp(self)
        def seed():
            rows=self.customers(3)
            self.assign(rows[0])
            Callback.objects.create(customer=rows[0],due_at=timezone.now()+timedelta(minutes=10),created_by=self.employee,updated_by=self.employee)
            Customer.objects.filter(pk=rows[0].pk).update(notes='로컬 가상 상담 기록',visit_at=timezone.now())
            Customer.objects.filter(pk=rows[2].pk).update(deleted_at=timezone.now(),deleted_by=self.admin)
            return rows
        self.rows=self.db(seed)

    def assert_layout(self,width):
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
        for selector in ['#search','#open-filters','#sort','#published-site','#upload-file']:
            item=self.page.locator(selector)
            if item.count() and item.is_visible():
                box=item.bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width+1)

    def test_screen_inventory_desktop_and_collapsed_mobile_navigation(self):
        paths=[(self.admin,'/app/admin','관리자 대시보드'),(self.admin,'/app/admin/customers','DB 관리'),
            (self.admin,'/app/admin/trash','휴지통'),(self.admin,'/app/admin/assignments','DB 분배·회수'),
            (self.admin,'/app/admin/users','사용자 관리'),(self.admin,'/app/admin/imports','엑셀 업로드'),
            (self.admin,'/app/admin/ai','AI 보고서'),(self.admin,f'/app/admin/ai/cases/{self.rows[0].pk}','보고서에 인용된 고객'),
            (self.employee,'/app/employee','직원 대시보드'),(self.employee,'/app/employee/today','오늘의 TM'),
            (self.employee,'/app/employee/mine','나의 DB'),(self.employee,'/app/guides','팀 상담 가이드')]
        previous=None
        for actor,path,title in paths:
            if actor!=previous:self.login(actor);previous=actor
            self.page.goto(self.live_server_url+path);self.page.wait_for_load_state('networkidle')
            expect(self.page.locator('#main-content h1')).to_have_text(title)
            expect(self.page).to_have_title(title+' · 두드림 TM')
            self.assertNotIn('고객과의 좋은 연결',self.page.locator('body').inner_text())
            self.assertEqual(self.page.locator('.header-brand').count(),1)
            for width in [1440,390,320]:
                self.page.set_viewport_size({'width':width,'height':960});self.assert_layout(width)
                menu=self.page.locator('#workspace-menu');toggle=self.page.locator('#menu-toggle')
                if width==1440:
                    expect(menu).to_be_visible();expect(toggle).to_be_hidden()
                    self.assertLess(menu.bounding_box()['y'],100)
                else:
                    expect(menu).to_be_hidden();toggle.focus();self.page.keyboard.press('Enter')
                    expect(menu).to_be_visible();expect(toggle).to_have_attribute('aria-expanded','true')
                    self.page.keyboard.press('Tab');self.page.keyboard.press('Escape')
                    expect(menu).to_be_hidden();expect(toggle).to_be_focused()
                self.page.screenshot(path=str(artifact_path(path.strip('/').replace('/','-')+f'-{width}.png')),full_page=True)
            self.page.set_viewport_size({'width':1440,'height':960})
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_account_copy_and_required_password_context(self):
        self.page.goto(self.live_server_url+'/auth/login')
        expect(self.page.locator('h1')).to_have_text('로그인')
        expect(self.page.locator('.login-intro')).to_have_count(0)
        for width in [1440,320]:
            self.page.set_viewport_size({'width':width,'height':900});self.assert_layout(width)
            self.page.screenshot(path=str(artifact_path(f'login-{width}.png')),full_page=True)
        self.login(self.employee);self.page.goto(self.live_server_url+'/auth/password?change=1')
        self.assertNotIn('비밀번호 변경을 완료한 계정입니다.',self.page.locator('body').inner_text())
        self.assertNotIn('계속하려면 비밀번호를 변경하세요.',self.page.locator('body').inner_text())
        expect(self.page.locator('h1')).to_have_text('비밀번호 변경')
        self.page.screenshot(path=str(artifact_path('password-320.png')),full_page=True)

    def test_filter_history_and_user_dialog_keyboard_focus_return(self):
        self.login(self.admin);self.page.goto(self.live_server_url+'/app/admin/customers')
        expect(self.page.locator('#page-info')).to_contain_text('검색 2명')
        for width in [1440,320]:
            self.page.set_viewport_size({'width':width,'height':900})
            opener=self.page.locator('#open-filters');opener.focus();self.page.keyboard.press('Enter')
            dialog=self.page.locator('#filter-dialog');expect(dialog).to_be_visible()
            box=dialog.bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width)
            self.page.screenshot(path=str(artifact_path(f'filter-{width}.png')),full_page=True)
            self.page.keyboard.press('Escape');expect(dialog).to_be_hidden();expect(opener).to_be_focused()
        history=self.page.locator('#customer-grid .tabulator-row').filter(has_text=self.rows[0].customer_name).get_by_role('button',name='상담·재콜 이력')
        history.click();expect(self.page.locator('#history-title')).to_contain_text('고객 이력')
        self.page.screenshot(path=str(artifact_path('customer-history-320.png')),full_page=True)
        self.page.locator('#history-dialog [data-close]').click();expect(history).to_be_focused()
        self.page.goto(self.live_server_url+'/app/admin/users')
        opener=self.page.locator('#add-user');opener.click();expect(self.page.locator('#add-user-dialog')).to_be_visible()
        self.page.keyboard.press('Escape');expect(opener).to_be_focused()
        self.assertEqual(self.errors,[])

    def test_empty_query_failure_and_unconfirmed_admin_save_are_distinct(self):
        self.login(self.admin);self.page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.second.pk}')
        expect(self.page.locator('#list-state')).to_contain_text('등록된 고객이 없습니다.')
        self.page.locator('#site').select_option(str(self.site.pk));expect(self.page.locator('#page-info')).to_contain_text('검색 2명')
        def fail(route):route.fulfill(status=503,json={'error':{'message':'가상 조회 오류'}})
        self.page.route('**/api/customers?*',fail)
        self.page.locator('#search').fill('가상');self.page.locator('#search-form button').click()
        expect(self.page.locator('#list-state')).to_contain_text('고객 목록을 불러오지 못했습니다.')
        self.page.screenshot(path=str(artifact_path('query-failed.png')),full_page=True)
        self.page.unroute('**/api/customers?*',fail);self.page.locator('#list-retry').click()
        expect(self.page.locator('#list-state')).to_be_hidden()
        cell=self.page.locator('#customer-grid .tabulator-row [tabulator-field="customer_name"]').first
        original=cell.inner_text();target=self.db(lambda:Customer.objects.get(customer_name=original).pk)
        cell.click();cell.locator('input').fill('가상 이름 변경');self.page.locator('h1').click()
        def lost(route):route.fetch();route.abort('failed')
        self.page.route('**/api/customers/batch-update',lost);self.page.locator('#save').click()
        expect(self.page.locator('#message')).to_contain_text('저장 결과를 확인하지 못했습니다.')
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=target).customer_name),'가상 이름 변경')
        self.page.screenshot(path=str(artifact_path('admin-save-unconfirmed.png')),full_page=True)
        self.page.unroute('**/api/customers/batch-update',lost);self.page.locator('#save').click()
        expect(self.page.locator('#message')).to_have_text('저장했습니다.')
        self.assertEqual(self.errors,[])

    def test_dismissing_unconfirmed_assignment_notice_keeps_server_work_and_restores_focus(self):
        from apps.assignments.models import Assignment
        self.login(self.admin);self.page.goto(self.live_server_url+'/app/admin/assignments')
        self.page.locator('#check-availability').click()
        self.page.locator('#assignment-employee').select_option(str(self.employee.pk))
        self.page.locator('#assignment-quantity').fill('1')
        def lost(route):route.fetch();route.abort('failed')
        self.page.route('**/api/assignments/distribute',lost,times=1)
        self.page.locator('#distribute').click();self.page.locator('#action-confirm-accept').click()
        expect(self.page.locator('#assignment-pending')).to_be_visible()
        self.assertEqual(self.db(Assignment.objects.count),2)
        opener=self.page.locator('#assignment-discard');opener.click()
        expect(self.page.locator('#action-confirm-dialog')).to_contain_text('서버에서 이미 처리된 작업은 그대로 유지됩니다.')
        self.page.set_viewport_size({'width':390,'height':900});self.assert_layout(390)
        self.page.screenshot(path=str(artifact_path('action-confirm-mobile.png')),full_page=True)
        self.page.keyboard.press('Tab');self.assertTrue(self.page.evaluate("!!document.activeElement.closest('#action-confirm-dialog')"))
        self.page.keyboard.press('Escape');expect(opener).to_be_focused()
        expect(self.page.locator('#assignment-pending')).to_be_visible()
        opener.click();self.page.locator('#action-confirm-dialog').get_by_role('button',name='알림 닫기',exact=True).click()
        expect(self.page.locator('#assignment-pending')).to_be_hidden()
        self.assertEqual(self.db(Assignment.objects.count),2)
        expect(self.page.locator('#assignment-message')).to_contain_text('서버에서 이미 처리된 작업은 그대로 유지됩니다.')
        self.assertEqual(self.errors,[])
