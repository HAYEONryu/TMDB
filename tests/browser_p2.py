from scripts.verification_evidence import artifact_path
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright, expect

from apps.accounts.models import User
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.sites.services import create_site
from tests.helpers import user, STRONG_PASSWORD


class AdminGridBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin=user(role=User.Role.ADMIN,initial=False,name="가상관리자")
        self.employee=user("01000000002",initial=False)
        self.site,_=create_site(self.admin,"가상 연습 A")
        self.second,_=create_site(self.admin,"가상 연습 B")
        Customer.objects.bulk_create([Customer(site=self.site,customer_name=f"가상고객{i:03}",phone_normalized=f"0108000{i:04}",housing_status="자가" if i%2 else "전세") for i in range(1,66)])
        self.target=Customer.objects.get(customer_name="가상고객001")
        self.errors=[];self.external=[]
        self.evidence=artifact_path('qa')
        self.evidence.mkdir(parents=True,exist_ok=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(settings.BASE_DIR/".cache/ms-playwright"))
        self.playwright=sync_playwright().start()
        self.browser=self.playwright.chromium.launch()
        self.context=self.browser.new_context(viewport={"width":1440,"height":960})
        self.context.on("page",lambda page:page.on("pageerror",lambda error:self.errors.append(str(error))))
        self.context.on("request",lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ["localhost","127.0.0.1"] else None)
        self.page=self.context.new_page()
        self.login(self.page,self.admin)

    def tearDown(self):
        self.browser.close();self.playwright.stop()
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[])
        super().tearDown()

    def login(self,page,account):
        page.goto(self.live_server_url+"/auth/login")
        page.get_by_label("아이디 또는 전화번호",exact=True).fill(account.phone_normalized)
        page.get_by_label("비밀번호",exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button",name="로그인",exact=True).click()
        expect(page).to_have_url(self.live_server_url+("/app/admin" if account.role=="ADMIN" else "/app/employee"))

    def grid(self):
        self.page.goto(self.live_server_url+"/app/admin/customers")
        expect(self.page.locator("#page-info")).to_contain_text("검색 65건")
        self.page.locator("#sort").select_option("customer_name")
        expect(self.page.locator('.tabulator-row [tabulator-field="customer_name"]').first).to_have_text("가상고객001")

    def edit(self,field,value):
        cell=self.page.locator(f'.tabulator-row [tabulator-field="{field}"]').first
        cell.dblclick()
        editor=cell.locator("textarea, input").first
        expect(editor).to_be_visible()
        editor.fill(value)
        self.page.locator("h1").click()
        expect(self.page.locator("#dirty-count")).to_contain_text("미저장 1행")

    def csrf(self):return next(c["value"] for c in self.context.cookies() if c["name"]=="csrftoken")

    def aligned_grid(self):
        self.page.wait_for_function("Math.abs(document.querySelector('.tabulator-col[tabulator-field=notes]').getBoundingClientRect().left-document.querySelector('.tabulator-row [tabulator-field=notes]').getBoundingClientRect().left)<2")

    def api(self,path,body):return self.context.request.post(self.live_server_url+path,data=body,headers={"X-CSRFToken":self.csrf()})

    def db(self, action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()

    def test_grid_paging_filters_manual_save_trash_restore_site_default_and_mobile(self):
        page=self.page;self.grid()
        with page.expect_response(lambda response:"/api/customers?" in response.url) as response:
            page.locator("#page-size").select_option("100")
        self.assertEqual(len(response.value.json()["data"]),65)
        expect(page.locator("#page-info")).to_contain_text("1 / 1페이지")
        name=page.locator('.tabulator-row [tabulator-field="customer_name"]').first
        name.dblclick();expect(name.locator("input")).to_have_count(0)
        self.edit("notes","<img src=x onerror=window.p2Injected=1> 가상 상담")
        self.db(self.target.refresh_from_db);self.assertEqual(self.target.notes,"")
        page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#message")).to_have_text("저장했습니다.")
        self.db(self.target.refresh_from_db);self.assertIn("가상 상담",self.target.notes)
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.get(customer=self.target).actor_id),self.admin.pk)
        self.assertIsNone(page.evaluate("window.p2Injected"))
        self.edit("visit_at","2026-11-04T14:30")
        page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#message")).to_have_text("저장했습니다.")
        expect(page.locator('.tabulator-row [tabulator-field="visit_at"]').first).to_have_text("2026-11-04 14:30")
        page.get_by_role("button",name="방문예약 날짜 필터",exact=True).click()
        page.get_by_label("시작일",exact=True).fill("2026-11-04")
        page.get_by_label("종료일",exact=True).fill("2026-11-04")
        page.get_by_role("button",name="적용",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 1건")
        page.get_by_role("button",name="필터 초기화",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 65건")
        page.get_by_role("button",name="주택상황 필터",exact=True).click()
        expect(page.locator("#filter-dialog")).to_be_visible()
        page.get_by_role("button",name="전체 해제",exact=True).click()
        page.locator("#filter-options").get_by_label("자가",exact=True).check()
        page.get_by_role("button",name="적용",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 33건")
        page.get_by_role("button",name="필터 초기화",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 65건")
        page.locator('.tabulator-row [tabulator-field="notes"]').first.scroll_into_view_if_needed()
        self.aligned_grid()
        page.screenshot(path=str(self.evidence/"p2-grid-desktop.png"),full_page=True)
        page.locator(".tabulator-row input[type=checkbox]").first.check()
        page.get_by_role("button",name="선택 휴지통 이동",exact=True).click()
        expect(page.locator("#bulk-summary")).to_contain_text("1개의 정보를 삭제하시겠습니까?")
        page.locator("#bulk-confirm").click()
        expect(page.locator("#message")).to_have_text("1건 처리했습니다.")
        page.get_by_role("link",name="휴지통",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 1건")
        expect(page.locator('.tabulator-row [tabulator-field="notes"]').first).to_contain_text("가상 상담")
        page.locator(".tabulator-row input[type=checkbox]").first.check()
        page.get_by_role("button",name="선택 복구",exact=True).click()
        page.locator("#bulk-confirm").click()
        expect(page.locator("#message")).to_have_text("1건 처리했습니다.")
        self.db(self.target.refresh_from_db);self.assertIsNone(self.target.deleted_at);self.assertIsNone(self.target.current_assignment_id)
        page.get_by_role("link",name="DB 관리",exact=True).click()
        expect(page.locator("#site")).to_have_value(str(self.site.pk))
        page.get_by_role("button",name="현장 생성",exact=True).click()
        page.get_by_label("현장명",exact=True).fill("가상 새 현장")
        page.get_by_role("button",name="생성",exact=True).click()
        expect(page.locator("#site-dialog")).not_to_be_visible()
        expect(page.locator("#page-info")).to_contain_text("검색 0건")
        selected=page.locator("#site").input_value()
        working=self.context.new_page()
        working.goto(self.live_server_url+"/app/admin/customers")
        expect(working.locator("#site")).to_have_value(str(self.site.pk))
        page.get_by_role("link",name="대시보드",exact=True).click()
        expect(page.locator("#default-site")).to_have_value(str(self.site.pk))
        expect(page.locator("#site-counts")).to_contain_text("전체 DB 65")
        page.locator("#default-site").select_option(selected)
        page.get_by_role("button",name="기본 현장 설정",exact=True).click()
        expect(page.locator("#site-message")).to_contain_text("다음 화면부터 적용")
        expect(working.locator("#site")).to_have_value(str(self.site.pk))
        working.reload()
        expect(working.locator("#site")).to_have_value(selected)
        working.close()
        page.get_by_role("link",name="DB 관리",exact=True).click()
        expect(page.locator("#site")).to_have_value(selected)
        page.locator("#site").select_option(str(self.site.pk))
        expect(page.locator("#page-info")).to_contain_text("검색 65건")
        page.set_viewport_size({"width":390,"height":844})
        expect(page.locator("h1")).to_have_text("DB 관리")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),390)
        self.aligned_grid()
        page.screenshot(path=str(self.evidence/"p2-grid-mobile.png"),full_page=True)

    def test_dirty_navigation_conflict_validation_and_lost_response_retry(self):
        page=self.page;self.grid()
        self.edit("notes","미저장 버릴 값")
        page.get_by_role("button",name="다음",exact=True).click()
        expect(page.locator("#dirty-dialog")).to_be_visible()
        page.get_by_role("button",name="머무르기",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("1 / 2페이지")
        self.db(self.target.refresh_from_db);self.assertEqual(self.target.notes,"")
        page.get_by_role("button",name="다음",exact=True).click()
        page.get_by_role("button",name="변경 폐기",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("2 / 2페이지")
        page.get_by_role("button",name="이전",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("1 / 2페이지")
        self.edit("notes","내 충돌 값")
        response=self.api("/api/customers/batch-update",{"rows":[{"customer_id":str(self.target.pk),"assignment_id":None,"mutation_id":str(uuid4()),"expected_version":1,"changes":{"notes":"다른 관리자 저장"}}]})
        self.assertTrue(response.json()["results"][0]["ok"])
        page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#message")).to_contain_text("저장하지 못했습니다")
        page.locator('.tabulator-row [tabulator-field="_status"]').first.get_by_role("button",name="확인").click()
        expect(page.locator("#conflict-values")).to_contain_text("다른 관리자 저장")
        expect(page.locator("#conflict-values")).to_contain_text("내 충돌 값")
        page.screenshot(path=str(self.evidence/"p2-conflict.png"),full_page=True)
        page.get_by_role("button",name="내 변경 다시 적용",exact=True).click()
        page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#message")).to_have_text("저장했습니다.")
        self.db(self.target.refresh_from_db);self.assertEqual(self.target.notes,"내 충돌 값")
        self.edit("housing_status","가"*201)
        page.get_by_role("button",name="다음",exact=True).click()
        page.get_by_role("button",name="저장하고 이동",exact=True).click()
        expect(page.locator("#message")).to_contain_text("저장하지 못했습니다")
        expect(page.locator("#page-info")).to_contain_text("1 / 2페이지")
        page.locator('.tabulator-row [tabulator-field="_status"]').first.get_by_role("button",name="확인").click()
        page.get_by_role("button",name="내 변경 폐기",exact=True).click()
        expect(page.locator("#dirty-count")).to_have_text("변경사항 없음")
        self.edit("notes","응답 유실 재시도")
        captured=[]
        def lose_response(route):
            captured.append(route.request.post_data_json)
            result=route.fetch()
            self.assertEqual(result.status,200)
            route.abort("failed")
        page.route("**/api/customers/batch-update",lose_response,times=1)
        page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#dirty-count")).to_contain_text("미저장 1행")
        expect(page.locator('.tabulator-row [tabulator-field="_status"]').first).to_contain_text("결과 확인 필요")
        self.db(self.target.refresh_from_db);version=self.target.version
        count=self.db(lambda:ConsultationRevision.objects.filter(customer=self.target).count())
        with page.expect_request("**/api/customers/batch-update") as retried:
            page.get_by_role("button",name="저장",exact=True).click()
        expect(page.locator("#message")).to_have_text("저장했습니다.")
        self.assertEqual(retried.value.post_data_json,captured[0])
        self.db(self.target.refresh_from_db);self.assertEqual(self.target.version,version)
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.filter(customer=self.target).count()),count)
        self.edit("notes","이동 전 저장")
        page.get_by_role("link",name="휴지통",exact=True).click()
        page.get_by_role("button",name="저장하고 이동",exact=True).click()
        expect(page).to_have_url(self.live_server_url+"/app/admin/trash")
        self.db(self.target.refresh_from_db);self.assertEqual(self.target.notes,"이동 전 저장")
