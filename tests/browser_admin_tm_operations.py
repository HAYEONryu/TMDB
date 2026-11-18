from datetime import datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import OperationalError
from django.utils import timezone
from playwright.sync_api import expect
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.deletions import approve, submit
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.customers.queries import KST
from apps.customers.services import update_row
from apps.operations.models import OperationEvent
from scripts.verification_evidence import artifact_path
from tests import browser_customer_metadata as metadata
from tests.test_p4 import Fixtures


class AdminTMOperationsBrowserTests(Fixtures,StaticLiveServerTestCase):
    setUp=metadata.CustomerMetadataBrowserTests.setUp
    db=metadata.CustomerMetadataBrowserTests.db
    login=metadata.CustomerMetadataBrowserTests.login

    def seed_requests(self):
        def create():
            rows=self.customers(3);rows[2].site=self.second;rows[2].save(update_fields=['site'])
            ids=[]
            for row in rows:
                self.assign(row)
                result,_=submit(self.employee,row.pk,{'assignment_id':str(row.current_assignment_id),'expected_version':row.version,'idempotency_key':str(uuid4())})
                ids.append(result['request_id'])
            return rows,ids
        self.rows,self.ids=self.db(create);self.login(self.admin)
        expect(self.page.locator('#delete-request-rows tr')).to_have_count(3)

    def select_all(self):
        self.page.locator('#delete-request-select-all').check()
        expect(self.page.locator('#approve-selected')).to_be_enabled()

    def confirm_bulk(self):
        self.page.locator('#approve-selected').click()
        expect(self.page.locator('#action-confirm-dialog')).to_contain_text('선택한 삭제 요청 3건')
        return self.page.locator('#action-confirm-dialog').get_by_role('button',name='선택 요청 일괄 승인',exact=True)

    def test_bulk_select_confirmation_multisite_exclusion_and_dashboard_refresh(self):
        self.seed_requests();page=self.page
        for width in [1440, 320]:
            page.set_viewport_size({'width': width, 'height': 960})
            bounds = page.locator('#deletion-notifications .section-heading').evaluate('''header => {
                const approve = header.querySelector("#approve-selected").getBoundingClientRect();
                const refresh = header.querySelector("#requests-refresh").getBoundingClientRect();
                return {gap: refresh.left - approve.right, centerDelta: (refresh.top + refresh.bottom - approve.top - approve.bottom) / 2,
                    scrollWidth: document.documentElement.scrollWidth};
            }''')
            self.assertGreaterEqual(bounds['gap'], 0)
            self.assertLessEqual(bounds['gap'], 12)
            self.assertAlmostEqual(bounds['centerDelta'], 0, delta=1)
            self.assertLessEqual(bounds['scrollWidth'], width)
        page.set_viewport_size({'width': 1440, 'height': 960})
        expect(page.locator('#approve-selected')).to_be_disabled()
        self.select_all();button=self.confirm_bulk()
        expect(page.locator('#action-confirm-dialog')).to_contain_text(self.site.name+': 2건')
        expect(page.locator('#action-confirm-dialog')).to_contain_text(self.second.name+': 1건')
        self.db(lambda:approve(self.admin,self.ids[0],{'idempotency_key':str(uuid4())}))
        button.click()
        expect(page.locator('#bulk-approval-results')).to_contain_text('승인 2건 · 제외 1건')
        expect(page.locator('#bulk-approval-results')).to_contain_text('이미 승인된 요청')
        expect(page.locator('#delete-request-rows tr')).to_have_count(0)
        expect(page.locator('#site-counts')).to_contain_text('현재 고객 0명')
        self.assertEqual(self.db(lambda:OperationEvent.objects.filter(operation='DELETION_APPROVE').count()),3)
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_partial_failure_shows_remaining_request_and_retry_does_not_repeat_success(self):
        self.seed_requests();self.select_all();button=self.confirm_bulk();page=self.page
        actual=approve
        def sometimes(actor,rid,payload):
            if str(rid)==self.ids[1]:raise OperationalError('synthetic')
            return actual(actor,rid,payload)
        def partial(route):
            with patch('apps.customers.bulk_deletions.approve',side_effect=sometimes):response=route.fetch()
            route.fulfill(response=response)
        page.route('**/api/deletion-requests/bulk-approve',partial);button.click()
        expect(page.locator('#bulk-approval-results')).to_contain_text('실패 1건')
        expect(page.locator('#delete-request-rows tr')).to_have_count(1)
        expect(page.locator('#approval-pending')).to_be_visible()
        page.unroute('**/api/deletion-requests/bulk-approve',partial);page.locator('#approval-retry').click()
        expect(page.locator('#bulk-approval-results')).to_contain_text('승인 3건 · 제외 0건')
        expect(page.locator('#approval-pending')).not_to_be_visible()
        self.assertEqual(self.db(lambda:OperationEvent.objects.filter(operation='DELETION_APPROVE').count()),3)
        self.assertEqual(self.errors,[])

    def test_lost_bulk_response_reload_and_same_key_retry(self):
        self.seed_requests();self.select_all();button=self.confirm_bulk();page=self.page;keys=[]
        def lose(route):
            keys.append(route.request.post_data_json['idempotency_key']);response=route.fetch()
            self.assertEqual(response.status,200);route.fulfill(status=503,json={'error':{'message':'가상 응답 유실'}})
        page.route('**/api/deletion-requests/bulk-approve',lose);button.click()
        expect(page.locator('#approval-pending')).to_be_visible()
        page.unroute('**/api/deletion-requests/bulk-approve',lose);page.reload()
        expect(page.locator('#approval-pending')).to_be_visible()
        def retry(route):
            keys.append(route.request.post_data_json['idempotency_key']);route.continue_()
        page.route('**/api/deletion-requests/bulk-approve',retry);page.locator('#approval-retry').click()
        expect(page.locator('#bulk-approval-results')).to_contain_text('승인 3건 · 제외 0건')
        expect(page.locator('#approval-pending')).not_to_be_visible()
        self.assertEqual(keys[0],keys[1]);self.assertEqual(len(keys),2)
        self.assertEqual(self.db(lambda:OperationEvent.objects.filter(operation='DELETION_APPROVE').count()),3)
        self.assertEqual(self.errors,[])

    def seed_tm(self):
        def create():
            now=timezone.now();start=datetime.combine(now.astimezone(KST).date(),time.min,KST)
            rows=self.customers(6)
            for row in rows:self.assign(row,at=start-timedelta(days=2))
            Assignment.objects.filter(pk=rows[1].current_assignment_id).update(assigned_at=now-timedelta(seconds=1))
            for row in rows[2:4]:
                Customer.objects.filter(pk=row.pk).update(call_result='NO_ANSWER')
                ConsultationRevision.objects.create(customer=row,assignment=row.current_assignment,actor=self.employee,saved_at=start-timedelta(days=1),
                    customer_version=1,source='MANUAL',changed_fields=['call_result'],after_values={'call_result':'NO_ANSWER'})
            Callback.objects.create(customer=rows[3],due_at=now,created_by=self.employee,updated_by=self.employee)
            Assignment.objects.filter(pk=rows[4].current_assignment_id).update(employee=self.other)
            rows[5].site=self.second;rows[5].save(update_fields=['site'])
            return rows
        self.rows=self.db(create);self.login(self.admin);page=self.page
        page.goto(self.live_server_url+f'/app/admin/assignments?site_id={self.site.pk}')
        page.locator('#check-availability').click();expect(page.locator('#tm-recall')).to_be_disabled()
        page.locator('#assignment-employee').select_option(str(self.employee.pk));expect(page.locator('#tm-recall')).to_be_enabled()

    def test_tm_recall_changed_target_requires_second_confirmation_and_keeps_completed(self):
        self.seed_tm();page=self.page
        page.locator('#tm-recall').click()
        expect(page.locator('#tm-recall-context')).to_contain_text('합계 3명')
        expect(page.locator('#tm-recall-preview')).to_contain_text(self.employee.name)
        def finish():
            row=Customer.objects.get(pk=self.rows[0].pk)
            return update_row(self.employee,{**self.mutation(row),'changes':{'call_result':'NO_ANSWER'}})
        self.db(finish);page.locator('#tm-recall-confirm').click()
        expect(page.locator('#tm-recall-dialog')).to_be_visible()
        expect(page.locator('#tm-recall-warning')).to_contain_text('최신 인원')
        expect(page.locator('#tm-recall-context')).to_contain_text('합계 2명')
        self.assertEqual(self.db(lambda:Customer.objects.filter(current_assignment=None).count()),0)
        page.locator('#tm-recall-confirm').click()
        expect(page.locator('#assignment-result')).to_contain_text('미완료 TM 고객 2명을 회수')
        expect(page.locator('#assignment-result')).to_contain_text('현재 담당 2명')
        self.assertEqual(self.db(lambda:Customer.objects.filter(current_assignment=None).count()),2)
        self.assertTrue(self.db(lambda:Customer.objects.get(pk=self.rows[0].pk).current_assignment_id is not None))
        self.assertTrue(self.db(lambda:Callback.objects.filter(customer=self.rows[3],status='PENDING').exists()))
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])

    def test_new_dialog_keyboard_mobile_and_existing_today_recall_remains(self):
        self.seed_tm();page=self.page
        trigger=page.locator('#tm-recall');trigger.focus();page.keyboard.press('Enter')
        expect(page.locator('#tm-recall-dialog')).to_be_visible();page.keyboard.press('Escape');expect(trigger).to_be_focused()
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':960});trigger.click()
            expect(page.locator('#tm-recall-dialog')).to_be_visible()
            box=page.locator('#tm-recall-dialog').bounding_box();self.assertGreaterEqual(box['x'],0);self.assertLessEqual(box['x']+box['width'],width+1)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            page.screenshot(path=str(artifact_path(f'tm-recall-{width}.png')))
            page.locator('#tm-recall-cancel').click()
        page.locator('#recall').click();expect(page.locator('#recall-dialog')).to_be_visible()
        page.locator('#recall-confirm').click();expect(page.locator('#assignment-result')).to_contain_text('배정 고객 1명을 회수')
        self.assertEqual(self.errors,[])

    def test_tm_recall_lost_response_retry_is_same_operation(self):
        self.seed_tm();page=self.page;page.locator('#tm-recall').click()
        expect(page.locator('#tm-recall-context')).to_contain_text('합계 3명')
        keys=[]
        def lose(route):
            keys.append(route.request.post_data_json['idempotency_key'])
            response=route.fetch();self.assertEqual(response.status,200)
            route.fulfill(status=503,json={'error':{'message':'가상 회수 응답 유실'}})
        page.route('**/api/assignments/tm-recall',lose);page.locator('#tm-recall-confirm').click()
        expect(page.locator('#assignment-pending')).to_be_visible()
        page.unroute('**/api/assignments/tm-recall',lose)
        page.once('dialog',lambda dialog:dialog.accept());page.reload()
        expect(page.locator('#assignment-pending')).to_be_visible()
        def retry(route):
            keys.append(route.request.post_data_json['idempotency_key']);route.continue_()
        page.route('**/api/assignments/tm-recall',retry);page.locator('#assignment-retry').click()
        expect(page.locator('#assignment-result')).to_contain_text('미완료 TM 고객 3명을 회수')
        expect(page.locator('#assignment-pending')).not_to_be_visible()
        self.assertEqual(keys[0],keys[1])
        self.assertEqual(self.db(lambda:OperationEvent.objects.filter(operation='TM_UNFINISHED_RECALL').count()),1)
        self.assertEqual(self.errors,[])

    def test_employee_returning_to_screen_refreshes_recalled_rows(self):
        from tests.helpers import STRONG_PASSWORD
        self.seed_tm();admin=self.page
        context=self.browser.new_context();self.addCleanup(context.close)
        staff=context.new_page();staff.on('pageerror',lambda error:self.errors.append(type(error).__name__))
        staff.goto(self.live_server_url+'/auth/login')
        staff.get_by_label('전화번호',exact=True).fill(self.employee.phone_normalized)
        staff.get_by_label('비밀번호',exact=True).fill(STRONG_PASSWORD)
        staff.get_by_role('button',name='로그인',exact=True).click()
        staff.goto(self.live_server_url+f'/app/employee/today?site_id={self.site.pk}')
        expect(staff.locator('#page-info')).to_contain_text('검색 3명')
        admin.locator('#tm-recall').click();expect(admin.locator('#tm-recall-context')).to_contain_text('합계 3명')
        admin.locator('#tm-recall-confirm').click()
        expect(admin.locator('#assignment-result')).to_contain_text('미완료 TM 고객 3명을 회수')
        staff.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(staff.locator('#page-info')).to_contain_text('검색 0명')
        self.assertEqual(self.errors,[])
