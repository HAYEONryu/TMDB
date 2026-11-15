"""Inline creation and the existing manual-save/leave guards."""
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect

from apps.customers.models import Customer
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class CustomerCreateBrowserTests(Fixtures, StaticLiveServerTestCase):
    setUp = metadata.CustomerMetadataBrowserTests.setUp
    db = metadata.CustomerMetadataBrowserTests.db
    login = metadata.CustomerMetadataBrowserTests.login

    def open_grid(self, site=None):
        self.login(self.admin)
        self.page.goto(self.live_server_url+f'/app/admin/customers?site_id={(site or self.site).pk}')
        expect(self.page.locator('#add-row')).to_be_enabled()

    def edit(self, field, value, selector='.new-customer-row'):
        cell = self.page.locator(f'{selector} [tabulator-field="{field}"]').first
        cell.scroll_into_view_if_needed()
        cell.click()
        cell.locator('input,textarea').fill(value)
        self.page.locator('h1').click()

    def test_empty_site_validation_selected_site_inline_save_and_permissions(self):
        self.open_grid(self.second);page = self.page
        expect(page.locator('#list-state')).to_contain_text('등록된 고객이 없습니다.')
        page.locator('#add-row').click()
        expect(page.locator('.new-customer-row')).to_have_count(1)
        expect(page.locator('#list-state')).not_to_be_visible()
        page.locator('#save').click()
        expect(page.locator('#new-row-error')).to_contain_text('010으로 시작하는 11자리')
        self.assertEqual(self.db(Customer.objects.count), 0)
        self.edit('customer_name', '가상 직접 추가')
        self.edit('phone_normalized', '010-9400-0001')
        self.edit('notes', '가상 신규 상담')
        page.screenshot(path=str(artifact_path('inline-new-customer.png')), full_page=True)
        page.locator('#save').click()
        expect(page.locator('#message')).to_contain_text('고객을 추가했습니다.')
        expect(page.locator('#page-info')).to_contain_text('검색 1건')
        expect(page.locator('#dirty-count')).to_have_text('변경사항 없음')
        customer = self.db(lambda:Customer.objects.get())
        self.assertEqual((customer.site_id, customer.customer_name, customer.phone_normalized, customer.notes, customer.current_assignment_id),
                         (self.second.pk, '가상 직접 추가', '01094000001', '가상 신규 상담', None))
        page.goto(self.live_server_url+'/app/admin/trash')
        expect(page.locator('#add-row')).to_have_count(0)
        self.login(self.employee)
        for view in ['mine','today']:
            page.goto(self.live_server_url+'/app/employee/'+view)
            expect(page.locator('#add-row')).to_have_count(0)
        self.assertEqual(self.errors, []);self.assertEqual(self.external, [])

    def test_new_and_existing_edits_search_guard_stay_discard_cancel_and_save(self):
        original = self.db(lambda:self.customers()[0])
        self.open_grid();page = self.page
        self.edit('customer_name', '가상 수정 이름', '.tabulator-row')
        page.locator('#add-row').click()
        self.edit('phone_normalized', '01094000001')
        expect(page.locator('#dirty-count')).to_have_text('미저장 2행')
        page.locator('#search').fill('없는 가상 조건');page.locator('#search-form').get_by_role('button', name='검색', exact=True).click()
        expect(page.locator('#dirty-dialog')).to_be_visible()
        page.locator('#dirty-stay').click()
        expect(page.locator('.new-customer-row')).to_have_count(1)
        page.locator('#save').click()
        expect(page.locator('#message')).to_have_text('저장했습니다.')
        self.assertEqual(self.db(Customer.objects.count), 2)
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=original.pk).customer_name), '가상 수정 이름')
        page.locator('#add-row').click()
        page.locator('#cancel-new-row').click()
        expect(page.locator('.new-customer-row')).to_have_count(0)
        page.locator('#add-row').click()
        page.locator('#search').fill('없는 가상 조건')
        page.locator('#search-form').get_by_role('button', name='검색', exact=True).click()
        expect(page.locator('#dirty-dialog')).to_be_visible();page.locator('#dirty-discard').click()
        expect(page.locator('#page-info')).to_contain_text('검색 0건')
        expect(page.locator('.new-customer-row')).to_have_count(0)
        self.assertEqual(self.db(Customer.objects.count), 2)
        # An active search stays applied after creating a customer outside it.
        page.locator('#add-row').click();self.edit('phone_normalized', '01094000002')
        page.locator('#save').click();expect(page.locator('#message')).to_contain_text('고객을 추가했습니다.')
        expect(page.locator('#page-info')).to_contain_text('검색 0건')
        expect(page.locator('#search')).to_have_value('없는 가상 조건')
        self.assertEqual(self.db(Customer.objects.count), 3)
        self.assertEqual(self.errors, []);self.assertEqual(self.external, [])

    def test_lost_response_retries_identical_payload_without_duplicate(self):
        self.open_grid();page = self.page
        page.locator('#add-row').click();self.edit('phone_normalized', '01094000001')
        captured=[]
        def lose(route):
            captured.append(route.request.post_data_json)
            self.assertEqual(route.fetch().status, 201)
            route.abort('failed')
        page.route('**/api/customers/create', lose, times=1)
        page.locator('#save').click()
        expect(page.locator('#new-row-error')).to_contain_text('같은 요청으로 결과를 확인')
        self.assertEqual(self.db(Customer.objects.count), 1)
        phone = page.locator('.new-customer-row [tabulator-field="phone_normalized"]')
        phone.click();expect(phone.locator('input')).to_have_count(0)
        def retry(route):
            captured.append(route.request.post_data_json);route.continue_()
        page.route('**/api/customers/create', retry, times=1)
        page.locator('#save').click()
        expect(page.locator('#message')).to_contain_text('고객을 추가했습니다.')
        self.assertEqual(captured[0], captured[1])
        self.assertEqual(self.db(Customer.objects.count), 1)
        self.assertEqual(self.errors, []);self.assertEqual(self.external, [])

    def test_save_and_move_keeps_original_site_and_new_row_is_not_bulk_selectable(self):
        self.open_grid();page = self.page
        page.locator('#add-row').click();self.edit('phone_normalized', '01094000001')
        expect(page.locator('.new-customer-row input[type=checkbox]')).to_be_disabled()
        page.locator('#site').select_option(str(self.second.pk))
        expect(page.locator('#dirty-dialog')).to_be_visible()
        page.locator('#dirty-save').click()
        expect(page.locator('#site')).to_have_value(str(self.second.pk))
        expect(page.locator('#page-info')).to_contain_text('검색 0건')
        expect(page.locator('.new-customer-row')).to_have_count(0)
        self.assertEqual(self.db(lambda:Customer.objects.get().site_id), self.site.pk)
        self.assertEqual(self.errors, []);self.assertEqual(self.external, [])
