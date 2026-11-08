from scripts.verification_evidence import artifact_path
import os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import close_old_connections,IntegrityError,OperationalError
from django.utils import timezone
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright,expect
from apps.customers.models import Customer
from apps.consultations.models import ConsultationRevision
from apps.imports.models import ImportBatch
from tests.helpers import STRONG_PASSWORD
from tests.test_imports import Fixtures,workbook,row,HEADERS
from apps.imports.excel import TEMPLATE_HEADERS


class ImportBrowserTests(Fixtures,StaticLiveServerTestCase):
    def setUp(self):
        self.prepare();self.errors=[];self.external=[]
        self.evidence=artifact_path('qa');self.evidence.mkdir(parents=True,exist_ok=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(settings.BASE_DIR/".cache/ms-playwright"))
        self.playwright=sync_playwright().start();self.browser=self.playwright.chromium.launch()
        self.context=self.browser.new_context(viewport={"width":1440,"height":960},accept_downloads=True)
        self.context.on("page",lambda page:page.on("pageerror",lambda error:self.errors.append(str(error))))
        self.context.on("request",lambda request:self.external.append(request.url) if urlsplit(request.url).hostname not in ["localhost","127.0.0.1"] else None)
        self.page=self.context.new_page();self.login(self.page,self.admin)

    def tearDown(self):
        self.browser.close();self.playwright.stop()
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
        super().tearDown()

    def login(self,page,account):
        page.goto(self.live_server_url+"/auth/login")
        page.get_by_label("전화번호",exact=True).fill(account.phone_normalized)
        page.get_by_label("비밀번호",exact=True).fill(STRONG_PASSWORD)
        page.get_by_role("button",name="로그인",exact=True).click()
        expect(page).to_have_url(self.live_server_url+("/app/admin" if account.role=="ADMIN" else "/app/employee"))

    def db(self,action):
        def run():
            close_old_connections()
            try:return action()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(run).result()

    def csrf(self):return next(item["value"] for item in self.context.cookies() if item["name"]=="csrftoken")
    def batch_id(self):return parse_qs(urlsplit(self.page.url).query)["batch_id"][0]

    def upload(self,data):
        self.page.locator("#upload-file").set_input_files({"name":"fake_customers.xlsx","mimeType":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","buffer":data})
        self.page.get_by_role("button",name="파일 검증",exact=True).click()
        expect(self.page.locator("#batch-status")).to_contain_text("검증 완료")

    def confirm(self):
        self.page.get_by_role("button",name="업로드 확정",exact=True).click()
        self.page.get_by_role("button",name="등록 확정",exact=True).click()

    def test_template_validate_recheck_results_without_file_mobile_and_employee_denial(self):
        page=self.page
        existing=self.db(lambda:Customer.objects.create(site=self.site,customer_name="보존가상",phone_normalized="01090000001",notes="휴지통 상담 보존",deleted_at=timezone.now(),deleted_by=self.admin))
        page.get_by_role("link",name="DB 관리",exact=True).click()
        page.get_by_role("link",name="엑셀 업로드",exact=True).click()
        expect(page.get_by_role("heading",name="엑셀 업로드",exact=True)).to_be_visible()
        with page.expect_download() as event:page.get_by_role("link",name="빈 입력 양식 다운로드",exact=True).click()
        download=event.value;target=self.evidence/"TM_customer_template.xlsx";download.save_as(target)
        book=load_workbook(target);self.assertEqual([cell.value for cell in book.worksheets[0][1]],TEMPLATE_HEADERS);self.assertEqual(book.worksheets[0]["B2"].number_format,"@");book.close()
        data=workbook([row(name=42),row("기존 중복"),row("파일 중복"),row("가상신규2","01090000002",**{"6":"가상 상담"}),row(phone=1090000001),[],row("<img src=x onerror=window.p3Injected=1>","01090000003",**{"7":"2026-11-05 (월) 10:00"})])
        self.upload(data)
        expect(page.locator("#validation-counts")).to_have_text("검증 시 총 6건 · 등록 가능 2 · 파일 내 중복 1 · 기존 중복 1 · 형식 오류 2")
        expect(page.locator("#import-rows tr")).to_have_count(4)
        self.assertEqual(self.db(lambda:Customer.objects.count()),1)
        batch_id=self.batch_id();page.reload()
        expect(page.locator("#batch-status")).to_contain_text("검증 완료")
        self.assertEqual(page.locator("#upload-file").input_value(),"")
        expect(page.locator("#import-rows")).to_contain_text("1090000001")
        page.screenshot(path=str(self.evidence/"p3-preview-desktop.png"),full_page=True)
        later=self.context.request.post(self.live_server_url+"/api/imports/validate",headers={"X-CSRFToken":self.csrf()},multipart={"site_id":str(self.site.pk),"file":{"name":"later.xlsx","mimeType":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","buffer":workbook([row("다른 등록","01090000002",**{"6":"새로 등록된 상담 보존"})])}})
        self.assertEqual(later.status,201)
        committed=self.context.request.post(self.live_server_url+f"/api/imports/{later.json()['id']}/commit",headers={"X-CSRFToken":self.csrf()},data={"site_id":str(self.site.pk),"idempotency_key":str(uuid4())})
        self.assertEqual(committed.status,200)
        self.confirm()
        expect(page.locator("#batch-status")).to_have_text("등록 확정 완료")
        expect(page.locator("#commit-summary")).to_contain_text("1개 업로드를 성공했습니다. 5개는")
        self.assertEqual(self.db(lambda:Customer.objects.get(pk=existing.pk).notes),"휴지통 상담 보존")
        self.assertEqual(self.db(lambda:Customer.objects.get(site=self.site,phone_normalized="01090000002").notes),"새로 등록된 상담 보존")
        page.locator("#result-kind").select_option("all")
        expect(page.locator("#import-rows tr")).to_have_count(6)
        expect(page.locator("#import-rows")).to_contain_text("<img src=x")
        self.assertIsNone(page.evaluate("window.p3Injected"));expect(page.locator("#import-rows img")).to_have_count(0)
        page.screenshot(path=str(self.evidence/"p3-result-desktop.png"),full_page=True)
        page.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),390)
        page.screenshot(path=str(self.evidence/"p3-result-mobile.png"),full_page=True)
        page.get_by_role("link",name="DB 관리로 돌아가기",exact=True).click()
        expect(page.locator("#page-info")).to_contain_text("검색 2건")
        staff=self.browser.new_context();staff_page=staff.new_page();self.login(staff_page,self.employee)
        self.assertEqual(staff_page.goto(self.live_server_url+"/app/admin/imports").status,403)
        self.assertEqual(staff.request.get(self.live_server_url+"/api/imports/template").status,403)
        self.assertEqual(staff.request.get(self.live_server_url+f"/api/imports/{batch_id}").status,403)
        staff.close()

    def test_lost_response_expiry_fatal_rollback_and_transient_retry(self):
        page=self.page;page.goto(self.live_server_url+"/app/admin/imports")
        page.locator("#upload-file").set_input_files({"name":"wrong.xlsx","mimeType":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","buffer":workbook([row()],headers=HEADERS[::-1])})
        page.get_by_role("button",name="파일 검증",exact=True).click()
        expect(page.locator("#upload-message")).to_contain_text("고객명·연락처·고객 거주지·주택상황·비고·관리자 비고 순서")
        self.upload(workbook([row()]));batch_id=self.batch_id();captured=[]
        def lose(route):
            captured.append(route.request.post_data_json);self.assertEqual(route.fetch().status,200);route.abort("failed")
        page.route("**/commit",lose,times=1);self.confirm()
        expect(page.locator("#batch-status")).to_have_text("등록 확정 완료")
        expect(page.locator("#upload-message")).to_contain_text("서버에서 등록 완료를 확인")
        replay=self.context.request.post(self.live_server_url+f"/api/imports/{batch_id}/commit",headers={"X-CSRFToken":self.csrf()},data=captured[0])
        self.assertEqual(replay.status,200);self.assertEqual(replay.json()["success_count"],1)
        self.assertEqual(self.db(lambda:ConsultationRevision.objects.count()),1)
        page.get_by_role("button",name="다른 파일 검증",exact=True).click()
        self.upload(workbook([row("만료가상","01090000002")]))
        expired=self.batch_id();self.db(lambda:ImportBatch.objects.filter(pk=expired).update(expires_at=timezone.now()-timedelta(seconds=1)))
        self.confirm();expect(page.locator("#batch-status")).to_have_text("검증 결과 만료")
        expect(page.locator("#upload-message")).to_contain_text("만료")
        self.assertEqual(self.db(lambda:Customer.objects.count()),1)
        page.get_by_role("button",name="다른 파일 검증",exact=True).click()
        self.upload(workbook([row("롤백가상","01090000003")]))
        with patch("apps.imports.services.ConsultationRevision.objects.bulk_create",side_effect=IntegrityError("가짜 원문은 응답에 없어야 함")):
            self.confirm();expect(page.locator("#batch-status")).to_have_text("등록 실패 · 재업로드 필요")
        expect(page.locator("#upload-message")).to_contain_text("전체 등록을 취소")
        expect(page.locator("#upload-message")).not_to_contain_text("가짜 원문")
        page.reload();expect(page.locator("#batch-status")).to_have_text("등록 실패 · 재업로드 필요")
        self.assertEqual(self.db(lambda:Customer.objects.count()),1)
        page.get_by_role("button",name="다른 파일 검증",exact=True).click()
        self.upload(workbook([row("재시도가상","01090000004")]))
        requests=[]
        page.on("request",lambda request:requests.append(request.post_data_json) if request.url.endswith("/commit") else None)
        with patch("apps.imports.services.Customer.objects.bulk_create",side_effect=OperationalError("temporary")):
            self.confirm();expect(page.locator("#upload-message")).to_contain_text("같은 요청으로 다시 시도")
        expect(page.locator("#batch-status")).to_contain_text("검증 완료")
        self.confirm();expect(page.locator("#batch-status")).to_have_text("등록 확정 완료")
        self.assertEqual(requests[0],requests[1]);self.assertEqual(self.db(lambda:Customer.objects.count()),2)
