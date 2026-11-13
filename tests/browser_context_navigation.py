from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect
from apps.customers.models import Customer
from tests import browser_customer_metadata as metadata
from tests.test_imports import workbook, row
from tests.test_p4 import Fixtures


class ContextNavigationBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def test_import_receives_current_site_confirms_name_and_count_and_batch_site_wins(self):
        self.login(self.admin);page=self.page
        page.goto(self.live_server_url+f'/app/admin/customers?site_id={self.second.pk}')
        expect(page.locator('#site')).to_have_value(str(self.second.pk))
        page.locator('#open-imports').click();expect(page.locator('#upload-site')).to_have_value(str(self.second.pk))
        data=workbook([row('가상 현장 전달 검증','01099000099')])
        page.locator('#upload-file').set_input_files({'name':'synthetic-site.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':data})
        page.locator('#validate-file').click();expect(page.locator('#commit-upload')).to_be_enabled()
        batch=parse_qs(urlsplit(page.url).query)['batch_id'][0]
        page.locator('#commit-upload').click()
        expect(page.locator('#confirm-site')).to_have_text(self.second.name);expect(page.locator('#confirm-counts')).to_have_text('등록 예정 1건')
        page.locator('#commit-cancel').click()
        page.goto(self.live_server_url+f'/app/admin/imports?batch_id={batch}&site_id={self.site.pk}')
        expect(page.locator('#upload-site')).to_have_value(str(self.second.pk))
        page.locator('#commit-upload').click();expect(page.locator('#confirm-site')).to_have_text(self.second.name)
        page.locator('#commit-confirm').click();expect(page.locator('#batch-status')).to_have_text('등록 확정 완료')
        self.assertEqual(self.db(lambda:Customer.objects.get(phone_normalized='01099000099').site_id),self.second.pk)
        page.get_by_role('link',name='DB 관리로 돌아가기',exact=True).click()
        expect(page.locator('#site')).to_have_value(str(self.second.pk));expect(page.locator('#page-info')).to_contain_text('검색 1건')
        page.goto(self.live_server_url+f'/app/admin/imports?site_id={uuid4()}')
        expect(page.locator('#upload-site')).to_have_value('');expect(page.locator('#upload-message')).to_contain_text('현장을 다시 선택')
        page.locator('#upload-file').set_input_files({'name':'synthetic-site.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':data})
        expect(page.locator('#validate-file')).to_be_disabled()
        self.assertEqual(self.errors,[])

    def test_employee_guide_keeps_site_on_open_reload_switch_and_return(self):
        def seed():
            for site,offset in [(self.site,0),(self.second,10)]:self.assign(self.customers(site=site,offset=offset)[0])
        self.db(seed);self.login(self.employee);page=self.page
        page.goto(self.live_server_url+f'/app/employee/mine?site_id={self.second.pk}')
        expect(page.locator('#site')).to_have_value(str(self.second.pk))
        page.locator('.workspace-nav').get_by_role('link',name='팀 상담 가이드',exact=True).click()
        expect(page.locator('#published-site')).to_have_value(str(self.second.pk))
        page.reload();expect(page.locator('#published-site')).to_have_value(str(self.second.pk))
        page.get_by_role('link',name='나의 DB로 돌아가기',exact=True).click()
        expect(page.locator('#site')).to_have_value(str(self.second.pk));expect(page.locator('#page-info')).to_contain_text('검색 1건')
        page.locator('.workspace-nav').get_by_role('link',name='팀 상담 가이드',exact=True).click()
        page.locator('#published-site').select_option(str(self.site.pk))
        page.locator('.workspace-nav').get_by_role('link',name='나의 DB',exact=True).click()
        expect(page.locator('#site')).to_have_value(str(self.site.pk))
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_clear_all_removes_search_and_column_filters_for_both_roles(self):
        def seed():
            rows=self.customers(2)
            for row in rows:self.assign(row)
            Customer.objects.filter(pk=rows[0].pk).update(notes='가상 필터 대상')
        self.db(seed);page=self.page
        for actor,path,grid in [(self.admin,'admin/customers','customer-grid'),(self.employee,'employee/mine','employee-grid')]:
            self.login(actor);page.goto(self.live_server_url+f'/app/{path}?site_id={self.site.pk}')
            expect(page.locator('#page-info')).to_contain_text('검색 2건')
            page.locator('#search').fill('고객0000');page.locator('#search-form button').click();expect(page.locator('#page-info')).to_contain_text('검색 1건')
            page.get_by_role('button',name='상담내용 필터',exact=True).click();page.locator('#filter-contains').fill('대상');page.locator('#filter-apply').click()
            expect(page.locator('#active-filters button')).to_have_count(1)
            page.locator('#clear-filters').click();expect(page.locator('#search')).to_have_value('');expect(page.locator('#active-filters button')).to_have_count(0)
            expect(page.locator('#page-info')).to_contain_text('검색 2건')
            expect(page.locator(f'#{grid} [data-filter-field="notes"]')).to_have_attribute('aria-pressed','false')
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
