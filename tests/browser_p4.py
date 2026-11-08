from scripts.verification_evidence import artifact_path
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections
from playwright.sync_api import sync_playwright,expect
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.customers.models import Customer
from apps.operations.models import OperationEvent,IdempotencyRecord
from apps.common.receipts import cleanup_p4_receipts
from django.utils import timezone
from datetime import timedelta
from tests.test_p4 import Fixtures
from tests.helpers import user,STRONG_PASSWORD


class P4BrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.rows=self.customers(95)
        self.errors=[];self.external=[];self.evidence=artifact_path('qa');self.evidence.mkdir(exist_ok=True,parents=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(settings.BASE_DIR/".cache/ms-playwright"))
        self.playwright=sync_playwright().start();self.browser=self.playwright.chromium.launch()
        self.context=self.browser.new_context(viewport={"width":1440,"height":960})
        self.context.on("page",lambda page:page.on("pageerror",lambda error:self.errors.append(str(error))))
        self.context.on("request",lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ["localhost","127.0.0.1"] else None)
        self.page=self.context.new_page();self.login(self.page,self.admin)

    def tearDown(self):
        self.browser.close();self.playwright.stop();self.assertEqual(self.errors,[]);self.assertEqual(self.external,[]);super().tearDown()

    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()

    def login(self,page,person,password=STRONG_PASSWORD):
        page.goto(self.live_server_url+"/auth/login");page.get_by_label("전화번호",exact=True).fill(person.phone_normalized);page.get_by_label("비밀번호",exact=True).fill(password);page.get_by_role("button",name="로그인",exact=True).click()
        expect(page).to_have_url(self.live_server_url+("/auth/password" if password=="dodream" else "/app/admin" if person.role=="ADMIN" else "/app/employee"))

    def csrf(self):return next(item["value"] for item in self.context.cookies() if item["name"]=="csrftoken")
    def save_users(self):
        self.page.get_by_role("button",name="저장",exact=True).click();self.page.get_by_role("button",name="저장 확인",exact=True).click()

    def test_distribution_shortage_lost_response_reload_replay_and_today_recall(self):
        self.db(lambda:user("01000000004",initial=False,name="가상직원다"));self.db(lambda:user("01000000005",initial=False,name="가상직원라"))
        page=self.page;page.get_by_role("link",name="DB 분배·회수",exact=True).click()
        expect(page.locator("#assignment-quantity")).to_be_disabled()
        page.get_by_role("button",name="확인",exact=True).click();expect(page.locator("#availability-count")).to_contain_text("분배 가능 95건 · 활성 직원 4명")
        page.locator("#assignment-quantity").fill("30");page.get_by_role("button",name="분배",exact=True).click()
        expect(page.locator("#assignment-message")).to_have_text("23개씩 분배할 수 있습니다.")
        self.assertEqual(self.db(lambda:Assignment.objects.count()),0)
        page.locator("#assignment-quantity").fill("23");page.get_by_role("button",name="분배",exact=True).click()
        expect(page.locator("#assignment-result")).to_contain_text("총 92건 분배했습니다.")
        expect(page.locator("#availability-count")).to_contain_text("분배 가능 3건")
        page.screenshot(path=str(self.evidence/"p4-allocation-desktop.png"),full_page=True)
        page.locator("#assignment-employee").select_option(str(self.employee.pk));page.locator("#assignment-quantity").fill("1")
        captured=[]
        def lose(route):captured.append(route.request.post_data_json);self.assertEqual(route.fetch().status,200);route.abort("failed")
        page.route("**/api/assignments/distribute",lose,times=1);page.get_by_role("button",name="분배",exact=True).click()
        expect(page.locator("#assignment-pending")).to_be_visible();self.assertEqual(self.db(lambda:Assignment.objects.count()),93)
        page.once("dialog",lambda dialog:dialog.accept());page.reload()
        expect(page.locator("#assignment-pending")).to_be_visible();expect(page.locator("#distribute")).to_be_disabled()
        with page.expect_request("**/api/assignments/distribute") as replay:
            page.get_by_role("button",name="동일 요청 다시 확인",exact=True).click()
        expect(page.locator("#assignment-pending")).not_to_be_visible();self.assertEqual(replay.value.post_data_json,captured[0]);self.assertEqual(self.db(lambda:Assignment.objects.count()),93)
        page.locator("#assignment-employee").select_option(str(self.employee.pk))
        owned=self.context.request.get(self.live_server_url+f"/api/customers?site_id={self.site.pk}&assignee_id={self.employee.pk}").json()["data"][0]
        response=self.context.request.post(self.live_server_url+"/api/customers/batch-update",headers={"X-CSRFToken":self.csrf()},data={"rows":[{"customer_id":owned["id"],"assignment_id":owned["assignment_id"],"expected_version":owned["version"],"mutation_id":str(uuid4()),"changes":{"notes":"가상 진행 상담 보존"}}]})
        self.assertTrue(response.json()["results"][0]["ok"])
        page.get_by_role("button",name="오늘 할당 회수",exact=True).click();expect(page.locator("#recall-preview")).to_contain_text("24건")
        page.locator("#recall-confirm").click();expect(page.locator("#assignment-result")).to_contain_text("24건을 회수했습니다.")
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=owned["id"]).notes),"가상 진행 상담 보존")
        self.assertEqual(self.db(lambda:Customer.objects.filter(pk=owned["id"],current_assignment=None).count()),1)
        page.locator("#assignment-site").select_option(str(self.second.pk));expect(page.locator("#assignment-quantity")).to_be_disabled();expect(page.locator("#availability-count")).to_have_text("현장을 확인해 주세요.")
        page.get_by_role("button",name="확인",exact=True).click();expect(page.locator("#availability-count")).to_contain_text("분배 가능 0건")
        page.set_viewport_size({"width":390,"height":844});self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),390);page.screenshot(path=str(self.evidence/"p4-allocation-mobile.png"),full_page=True)
        self.db(lambda:IdempotencyRecord.objects.filter(operation="DISTRIBUTE",key=captured[0]["idempotency_key"]).update(expires_at=timezone.now()-timedelta(seconds=1)))
        self.db(cleanup_p4_receipts)
        page.evaluate("data=>sessionStorage.setItem(data.key,JSON.stringify({endpoint:'/api/assignments/distribute',body:data.body,created_at:Date.now()-8*24*60*60*1000}))",{"key":f"tm:p4:allocation:{self.admin.pk}","body":captured[0]})
        page.reload();expect(page.locator("#assignment-pending")).to_be_visible();requests=[]
        page.on("request",lambda request:requests.append(request.url) if request.url.endswith("/api/assignments/distribute") else None)
        page.get_by_role("button",name="동일 요청 다시 확인",exact=True).click();expect(page.locator("#assignment-message")).to_contain_text("요청 보관 기간")
        self.assertEqual(requests,[]);self.assertEqual(self.db(lambda:Assignment.objects.count()),93)

    def test_user_deactivation_transfer_dirty_guard_reset_and_new_user_first_login(self):
        a,b=self.rows[:2]
        self.db(lambda:self.assign(a));self.db(lambda:self.assign(b,progress=True))
        staff=self.browser.new_context();staff_page=staff.new_page();self.login(staff_page,self.employee)
        page=self.page;page.get_by_role("link",name="사용자 관리",exact=True).click()
        record=page.locator(f'#user-rows tr[data-id="{self.employee.pk}"]')
        record.get_by_label("비활성화",exact=True).check();page.get_by_role("button",name="저장",exact=True).click()
        expect(page.get_by_role("heading",name="수정을 반영하시겠습니까?",exact=True)).to_be_visible();page.locator("#user-save-cancel").click()
        self.assertTrue(self.db(lambda:User.objects.get(pk=self.employee.pk).is_active))
        self.save_users();expect(page.locator("#user-message")).to_contain_text("미진행 1건 회수")
        self.assertEqual(staff.request.get(self.live_server_url+"/api/me").status,401)
        expect(page.locator("#transfer-page")).to_contain_text("이관 필요 1건")
        page.screenshot(path=str(self.evidence/"p4-users-desktop.png"),full_page=True)
        page.get_by_role("link",name="DB 관리에서 이관",exact=True).click()
        expect(page.locator("#site")).to_have_value(str(self.site.pk));expect(page.locator("#page-info")).to_contain_text("검색 1건")
        notes=page.locator('.tabulator-row [tabulator-field="notes"]').first;notes.dblclick();notes.locator("textarea").fill("이관 전 가상 상담 저장");page.locator("h1").click()
        page.get_by_role("button",name="담당 변경",exact=True).click();expect(page.locator("#dirty-dialog")).to_be_visible();page.get_by_role("button",name="머무르기",exact=True).click()
        page.get_by_role("button",name="담당 변경",exact=True).click();page.get_by_role("button",name="저장하고 이동",exact=True).click()
        expect(page.locator("#assignee-dialog")).to_be_visible();page.locator("#assignee-target").select_option(str(self.other.pk));page.get_by_role("button",name="담당자 변경 확인",exact=True).click()
        expect(page.locator("#message")).to_contain_text("담당자를 변경했습니다")
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=b.pk).notes),"이관 전 가상 상담 저장")
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=b.pk).current_assignment.employee_id),self.other.pk)
        self.assertEqual(self.db(lambda:Customer.objects.filter(pk=a.pk,current_assignment=None).count()),1)
        page.get_by_role("link",name="사용자 관리",exact=True).click();record=page.locator(f'#user-rows tr[data-id="{self.employee.pk}"]')
        record.get_by_label("비활성화",exact=True).uncheck();record.get_by_label("이름",exact=True).fill("가상새이름");record.get_by_label("전화번호",exact=True).fill("010-0000-0012");self.save_users()
        expect(page.locator("#user-message")).to_contain_text("1명 저장")
        self.db(self.employee.refresh_from_db);self.login(staff_page,self.employee)
        record.get_by_role("button",name="비밀번호 재설정",exact=True).click();page.locator("#reset-confirm").click();expect(page.locator("#user-message")).to_contain_text("초기 비밀번호로 재설정")
        self.assertEqual(staff.request.get(self.live_server_url+"/api/me").status,401)
        page.get_by_role("button",name="사용자 추가",exact=True).click()
        page.locator("#new-user-name").fill("가상추가계정");page.locator("#new-user-phone").fill("01000000010");page.locator("#add-user-submit").click()
        expect(page.locator("#user-message")).to_contain_text("사용자를 추가했습니다")
        account=self.db(lambda:User.objects.get(phone_normalized="01000000010"));self.login(staff_page,account,"dodream")
        expect(staff_page.get_by_role("heading",name="비밀번호 변경",exact=True)).to_be_visible()
        own=page.locator(f'#user-rows tr[data-id="{self.admin.pk}"]');own.get_by_label("관리자",exact=True).uncheck();self.save_users();expect(page.locator("#user-message")).to_contain_text("마지막 활성 관리자")
        self.assertEqual(self.db(lambda:User.objects.get(pk=self.admin.pk).role),"ADMIN")
        page.get_by_role("button",name="다시 조회",exact=True).click();page.locator("#user-discard").click();expect(own.get_by_label("관리자",exact=True)).to_be_checked()
        page.set_viewport_size({"width":390,"height":844});self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),390);page.screenshot(path=str(self.evidence/"p4-users-mobile.png"),full_page=True);staff.close()

    def test_assignee_and_user_save_lost_response_replay_and_noop(self):
        customer=self.rows[0];self.db(lambda:self.assign(customer))
        page=self.page;page.goto(self.live_server_url+f"/app/admin/customers?site_id={self.site.pk}&assignee_id={self.employee.pk}")
        expect(page.locator("#page-info")).to_contain_text("검색 1건")
        assigned=page.locator('.tabulator-row [tabulator-field="assigned_at"] span').first
        self.assertEqual(len(assigned.inner_text()),5);self.assertIn("시",assigned.get_attribute("title"))
        page.get_by_role("button",name="담당 변경",exact=True).click();page.locator("#assignee-target").select_option(str(self.other.pk))
        requests=[]
        def lose(route):requests.append(route.request.post_data_json);self.assertEqual(route.fetch().status,200);route.abort("failed")
        page.route("**/assignee",lose,times=1);page.locator("#assignee-confirm").click()
        expect(page.locator("#assignee-pending")).to_be_visible();self.assertEqual(self.db(lambda:Assignment.objects.count()),2)
        page.reload();expect(page.locator("#assignee-pending")).to_be_visible()
        with page.expect_request("**/assignee") as replay:page.locator("#assignee-retry").click()
        expect(page.locator("#assignee-pending")).not_to_be_visible();self.assertEqual(replay.value.post_data_json,requests[0]);self.assertEqual(self.db(lambda:Assignment.objects.count()),2)
        page.get_by_role("button",name="담당직원 조건 해제 ×",exact=True).click();page.locator("#sort").select_option("customer_name")
        expect(page.locator('.tabulator-row [tabulator-field="customer_name"]').first).to_have_text(customer.customer_name)
        page.get_by_role("button",name="담당 변경",exact=True).first.click();page.locator("#assignee-confirm").click();expect(page.locator("#message")).to_contain_text("같은 담당자")
        self.assertEqual(self.db(lambda:Assignment.objects.count()),2)
        page.get_by_role("link",name="사용자 관리",exact=True).click();record=page.locator(f'#user-rows tr[data-id="{self.other.pk}"]');record.get_by_label("이름",exact=True).fill("재시도 가상 이름")
        saved=[]
        def lose_user(route):saved.append(route.request.post_data_json);self.assertEqual(route.fetch().status,200);route.abort("failed")
        page.route("**/api/users/batch-update",lose_user,times=1);self.save_users();expect(page.locator("#user-dirty")).to_contain_text("응답 미확인")
        expect(record.get_by_label("이름",exact=True)).to_be_disabled()
        with page.expect_request("**/api/users/batch-update") as replay:self.save_users()
        expect(page.locator("#user-message")).to_contain_text("1명 저장");self.assertEqual(replay.value.post_data_json,saved[0])
