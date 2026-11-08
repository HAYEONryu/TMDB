from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta
from io import BytesIO,StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED
import logging
from contextlib import redirect_stderr

from django.core.files.uploadedfile import SimpleUploadedFile,TemporaryUploadedFile
from django.core.management import call_command
from django.db import IntegrityError,OperationalError,close_old_connections
from django.test import TestCase,TransactionTestCase,override_settings,Client
from django.utils import timezone
from openpyxl import Workbook,load_workbook

from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerChangeEvent
from apps.imports.excel import HEADERS,TEMPLATE_HEADERS,HEADER_INSTRUCTIONS,parse_upload,template_bytes
from apps.imports.models import ImportBatch,ImportCandidate,ImportRowResult
from apps.imports.services import validate_upload,commit_upload,cleanup_imports,result_page
from apps.operations.models import IdempotencyRecord,OperationEvent
from apps.sites.services import create_site
from tests.helpers import user,login,TEST_HASHERS


def row(name="가상고객",phone="010-9000-0001",**kwargs):
    values=[None,name,phone,None,None,None,None,None,None]
    for index,value in kwargs.items():values[int(index)]=value
    return values


def workbook(rows,*,headers=None,second=None):
    book=Workbook();sheet=book.active;sheet.append(HEADERS if headers is None else headers)
    for values in rows:sheet.append(values)
    if second:
        hidden=book.create_sheet("무시할 시트");hidden.sheet_state="hidden"
        for values in second:hidden.append(values)
    stream=BytesIO();book.save(stream);book.close();return stream.getvalue()


def uploaded(data,name="fake.xlsx"):
    return SimpleUploadedFile(name,data,content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def alter_zip(data,replace=None,add=None):
    output=BytesIO()
    with ZipFile(BytesIO(data)) as source,ZipFile(output,"w",ZIP_DEFLATED) as target:
        for item in source.infolist():
            value=source.read(item.filename)
            if replace:value=replace(item.filename,value)
            target.writestr(item.filename,value)
        for name,value in (add or {}).items():target.writestr(name,value)
    return output.getvalue()


class Fixtures:
    def prepare(self):
        self.admin=user(role=User.Role.ADMIN,initial=False,name="가상관리자")
        self.employee=user("01000000002",initial=False)
        self.other_admin=user("01000000003",role=User.Role.ADMIN,initial=False)
        self.site,_=create_site(self.admin,"가상업로드 현장")
        self.other_site,_=create_site(self.admin,"다른 가상 현장")

    def validate(self,rows=None,**kwargs):
        return validate_upload(self.admin,self.site.pk,uploaded(workbook(rows if rows is not None else [row()],**kwargs)))

    def body(self,**kwargs):
        return {"site_id":str(self.site.pk),"idempotency_key":str(uuid4()),**kwargs}


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ImportTests(Fixtures,TestCase):
    def setUp(self):self.prepare();self.client=login(self.admin)

    def test_template_is_empty_nine_headers_text_phone_and_no_personal_data(self):
        response=self.client.get("/api/imports/template")
        self.assertEqual(response.status_code,200)
        self.assertIn("attachment",response["Content-Disposition"])
        book=load_workbook(BytesIO(response.content));sheet=book.worksheets[0]
        self.assertEqual([cell.value for cell in sheet[1]],TEMPLATE_HEADERS)
        self.assertEqual(sheet["C2"].number_format,"@")
        self.assertTrue(all(cell.value is None for cells in sheet.iter_rows(min_row=2) for cell in cells))
        self.assertEqual(len(book.worksheets),1);book.close()
        self.assertEqual(Customer.objects.count(),0)

    def test_template_has_visible_formats_notes_and_input_prompts_for_every_column(self):
        book=load_workbook(BytesIO(template_bytes()));sheet=book.worksheets[0]
        self.assertEqual([cell.value.split("\n",1)[0] for cell in sheet[1]],HEADERS)
        self.assertEqual(sheet.freeze_panes,"A2")
        self.assertEqual(sheet.auto_filter.ref,"A1:I1")
        validations=list(sheet.data_validations.dataValidation)
        self.assertEqual(len(validations),9)
        for cell,instruction,validation in zip(sheet[1],HEADER_INSTRUCTIONS,validations):
            self.assertTrue(cell.alignment.wrap_text)
            self.assertEqual(cell.comment.text,instruction)
            self.assertTrue(validation.showInputMessage)
            self.assertLessEqual(len(validation.prompt),255)
            self.assertEqual(validation.prompt,instruction)
            self.assertIn(f"{cell.column_letter}2",validation.sqref)
        self.assertEqual(validations[3].type,"list")
        self.assertEqual(validations[5].type,"list")
        self.assertIn("YYYY-MM-DD HH:mm",sheet["E1"].value)
        self.assertIn("YYYY-MM-DD HH:mm",sheet["H1"].value)
        book.close()

    def test_explanatory_headers_accept_valid_row_and_never_import_the_guidance(self):
        book=load_workbook(BytesIO(template_bytes()));sheet=book.worksheets[0]
        values=row(**{"3":"관심","4":"2026-11-09 14:30","5":"미계약","6":"가상 상담","7":"2026-11-10 10:00","8":"전세"})
        for column,value in enumerate(values,1):sheet.cell(2,column,value)
        output=BytesIO();book.save(output);book.close()
        batch=validate_upload(self.admin,self.site.pk,uploaded(output.getvalue()))
        self.assertEqual(batch.validation_summary["total"],1)
        self.assertEqual(batch.validation_summary["ready"],1)
        self.assertEqual(batch.candidates.get().row_number,2)
        self.assertEqual(Customer.objects.count(),0)
        with self.assertRaises(AccessError) as caught:parse_upload(uploaded(template_bytes()))
        self.assertEqual(caught.exception.code,"EMPTY_FILE")

    def test_explanatory_headers_still_reject_reordering_and_unknown_titles(self):
        for headers in [TEMPLATE_HEADERS[::-1],["다른 고객명\n설명",*TEMPLATE_HEADERS[1:]]]:
            with self.assertRaises(AccessError) as caught:self.validate(headers=headers)
            self.assertEqual(caught.exception.code,"INVALID_HEADER")

    def test_header_guidance_can_change_without_changing_column_meanings(self):
        headers=[f"{title}\n예전 안내 또는 새 안내" if index%2 else title for index,title in enumerate(HEADERS)]
        batch=self.validate(headers=headers)
        self.assertEqual(batch.validation_summary["ready"],1)

    def test_staff_and_initial_login_cannot_read_validate_commit_or_results(self):
        batch=self.validate()
        self.client=login(self.employee)
        for path in ["/api/imports/template",f"/api/imports/{batch.pk}","/app/admin/imports"]:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post("/api/imports/validate",{"site_id":self.site.pk,"file":uploaded(workbook([row()]))}).status_code,403)
        self.assertEqual(self.client.post(f"/api/imports/{batch.pk}/commit",self.body(),content_type="application/json").status_code,403)
        self.employee.must_change_password=True;self.employee.save()
        self.assertEqual(self.client.get("/api/imports/template").json()["error"]["code"],"PASSWORD_CHANGE_REQUIRED")

    def test_csrf_required_and_multipart_validate_creates_candidates_only(self):
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.admin)
        from apps.accounts.middleware import SESSION_VERSION_KEY
        session=strict.session;session[SESSION_VERSION_KEY]=self.admin.session_version;session.save()
        self.assertEqual(strict.post("/api/imports/validate",{"site_id":self.site.pk,"file":uploaded(workbook([row()]))}).status_code,403)
        response=self.client.post("/api/imports/validate",{"site_id":self.site.pk,"file":uploaded(workbook([row()]))})
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.json()["validation_summary"],{"total":1,"ready":1,"duplicate_in_file":0,"duplicate_existing":0,"invalid":0})
        self.assertEqual(Customer.objects.count(),0);self.assertEqual(ImportCandidate.objects.count(),1)

    def test_exact_headers_order_type_only_first_sheet_and_blank_rows(self):
        for headers in [HEADERS[::-1],HEADERS[:-1],HEADERS+["할당일"],[*HEADERS[:2],"연락처",*HEADERS[3:]]]:
            with self.assertRaises(AccessError) as caught:self.validate(headers=headers)
            self.assertEqual(caught.exception.code,"INVALID_HEADER")
        batch=self.validate(rows=[[],row(),[None]*9,row("가상2","01090000002")],second=[["다른 헤더"],["=NOW()"]])
        self.assertEqual(batch.total_count,2)
        self.assertEqual(list(batch.candidates.order_by("row_number").values_list("row_number",flat=True)),[3,5])

    def test_formula_staff_and_extra_columns_fail_rows_not_entire_valid_file(self):
        batch=self.validate([row(**{"0":"가상직원"}),row(**{"6":"=1+1"}),row()+["추가값"],row("가상정상","01090000004")])
        self.assertEqual(batch.validation_summary["invalid"],3)
        self.assertEqual(batch.validation_summary["ready"],1)
        self.assertTrue(all(not item.success for item in batch.row_results.filter(row_number__lt=5)))

    def test_first_valid_phone_wins_invalid_earlier_does_not_reserve_phone(self):
        batch=self.validate([row(name=""),row("유효 첫 행"),row("유효 둘째 중복")])
        self.assertEqual(batch.validation_summary,{"total":3,"ready":1,"duplicate_in_file":1,"duplicate_existing":0,"invalid":1})
        self.assertEqual(batch.candidates.get().row_number,3)
        self.assertEqual(batch.row_results.get(row_number=4).error_code,"DUPLICATE_IN_FILE")

    def test_numeric_phone_is_never_repaired_and_invalid_types_enums_lengths(self):
        invalid=[row(phone=1090000001),row(phone="+82 1090000001"),row(phone="01190000001"),row(name=42),row(name="가"*101),
            row(**{"3":"OTHER"}),row(**{"5":"UNKNOWN"}),row(**{"6":"가"*10001}),row(**{"8":"가"*201}),row(**{"6":12})]
        batch=self.validate(invalid+[row("가상 정상","01090000002")])
        self.assertEqual(batch.validation_summary["invalid"],len(invalid))
        self.assertEqual(batch.candidates.count(),1)
        self.assertEqual(batch.row_results.get(row_number=2).phone_input,"1090000001")

    def test_dates_excel_datetime_strings_weekday_ignored_and_date_only_rejected(self):
        values=[row("날짜1","01090000001",**{"4":datetime(2026,11,4,14,30),"7":"2026-11-04 (월) 16:20"}),
            row("날짜2","01090000002",**{"4":"2026-11-04 00:00 (목요일)"}),
            row("날짜3","01090000003",**{"4":"2026-11-04"}),row("날짜4","01090000004",**{"7":date(2026,11,4)}),
            row("날짜5","01090000005",**{"4":44444}),row("날짜6","01090000006",**{"4":"2026-02-30 12:00"}),row("날짜7","01090000007",**{"4":"0001-01-01 00:00"})]
        batch=self.validate(values)
        self.assertEqual(batch.validation_summary["ready"],2);self.assertEqual(batch.validation_summary["invalid"],5)
        candidate=batch.candidates.get(row_number=2).normalized_values
        self.assertEqual(candidate["visit_at"],"2026-11-04T14:30:00+09:00")
        self.assertEqual(candidate["callback_due_at"],"2026-11-04T16:20:00+09:00")

    def test_existing_duplicates_include_trash_but_different_site_allowed(self):
        existing=Customer.objects.create(site=self.site,customer_name="보존가상",phone_normalized="01090000001",notes="기존 상담 보존",deleted_at=timezone.now(),deleted_by=self.admin)
        Customer.objects.create(site=self.other_site,customer_name="타현장",phone_normalized="01090000002")
        batch=self.validate([row(),row("신규","01090000002")])
        self.assertEqual(batch.validation_summary["duplicate_existing"],1)
        self.assertEqual(batch.candidates.count(),1)
        result,status=commit_upload(self.admin,batch.pk,self.body())
        self.assertEqual((status,result["success_count"]),(200,1))
        existing.refresh_from_db();self.assertEqual(existing.notes,"기존 상담 보존");self.assertIsNotNone(existing.deleted_at)

    def test_commit_creates_import_revision_callback_unassigned_and_atomic_idempotency(self):
        batch=self.validate([row(**{"3":"관심","4":"2026-11-04 14:30","5":"계약","6":"가짜 상담","7":"2026-11-05 16:00","8":" 자가 "})])
        key=self.body();result,status=commit_upload(self.other_admin,batch.pk,key)
        self.assertEqual((status,result["success_count"],result["failure_count"]),(200,1,0))
        self.assertEqual(commit_upload(self.other_admin,batch.pk,key),(result,status))
        customer=Customer.objects.get();revision=ConsultationRevision.objects.get();callback=Callback.objects.get()
        self.assertEqual(customer.phone_normalized,"01090000001");self.assertEqual(customer.call_result,"INTERESTED")
        self.assertEqual(customer.contract_status,"CONTRACTED");self.assertEqual(customer.housing_status,"자가")
        self.assertIsNone(customer.current_assignment_id)
        self.assertEqual((revision.source,revision.actor_id,revision.assignment_id,revision.customer_version),("IMPORT",self.other_admin.pk,None,1))
        self.assertEqual(revision.after_values["notes"],"가짜 상담")
        self.assertEqual(callback.created_by_id,self.other_admin.pk)
        self.assertEqual((Assignment.objects.count(),CustomerChangeEvent.objects.count()),(0,0))
        batch.refresh_from_db();self.assertEqual(batch.committed_by_id,self.other_admin.pk);self.assertIsNotNone(batch.committed_at)
        self.assertEqual(batch.candidates.count(),0)
        self.assertEqual(OperationEvent.objects.filter(operation="IMPORT_COMMITTED").count(),1)
        self.assertLessEqual(IdempotencyRecord.objects.get(operation="IMPORT_COMMIT").expires_at,batch.expires_at+timedelta(days=7))
        self.assertEqual(commit_upload(self.admin,batch.pk,self.body())[0]["success_count"],1)
        self.assertEqual(Customer.objects.count(),1)

    def test_commit_revalidates_new_duplicates_and_replay_counts_do_not_change(self):
        batch=self.validate([row(),row("가상신규","01090000002")])
        old=Customer.objects.create(site=self.site,customer_name="나중 등록",phone_normalized="01090000001",notes="덮어쓰지 않음")
        key=self.body();result,status=commit_upload(self.admin,batch.pk,key)
        self.assertEqual((result["success_count"],result["failure_count"]),(1,1))
        old.refresh_from_db();self.assertEqual(old.notes,"덮어쓰지 않음")
        self.assertEqual(batch.row_results.get(row_number=2).error_code,"DUPLICATE_PHONE")
        self.assertEqual(commit_upload(self.admin,batch.pk,key),(result,status))

    def test_wrong_site_key_conflict_missing_batch_and_deleted_site_are_rejected(self):
        batch=self.validate();key=self.body()
        with self.assertRaises(AccessError) as mismatch:commit_upload(self.admin,batch.pk,self.body(site_id=str(self.other_site.pk)))
        self.assertEqual(mismatch.exception.code,"SITE_MISMATCH")
        commit_upload(self.admin,batch.pk,key)
        other=self.validate([row("다른고객","01090000002")])
        with self.assertRaises(AccessError) as conflict:commit_upload(self.admin,other.pk,key)
        self.assertEqual(conflict.exception.code,"IDEMPOTENCY_CONFLICT")
        with self.assertRaises(AccessError):commit_upload(self.admin,uuid4(),self.body())
        site_id=self.site.pk;self.site.delete()
        with self.assertRaises(AccessError) as deleted:commit_upload(self.admin,batch.pk,{**key,"site_id":str(site_id)})
        self.assertEqual(deleted.exception.code,"SITE_DELETED")

    def test_fatal_database_failure_rolls_back_everything_then_records_terminal_failed(self):
        batch=self.validate([row(**{"7":"2026-11-05 12:00","6":"가짜 원문"}),row("가상2","01090000002")])
        key=self.body()
        with patch("apps.imports.services.ConsultationRevision.objects.bulk_create",side_effect=IntegrityError("가짜 오류에 포함된 가짜 원문")):
            result,status=commit_upload(self.admin,batch.pk,key)
        self.assertEqual((status,result["status"]),(500,"FAILED"))
        for model in [Customer,Callback,ConsultationRevision]:self.assertEqual(model.objects.count(),0)
        self.assertEqual(batch.candidates.count(),0);batch.refresh_from_db()
        self.assertEqual((batch.status,batch.success_count,batch.failure_count),("FAILED",0,2))
        self.assertNotIn("가짜 원문",str(result))
        self.assertEqual(commit_upload(self.admin,batch.pk,key),(result,status))
        with self.assertRaises(AccessError) as terminal:commit_upload(self.admin,batch.pk,self.body())
        self.assertEqual(terminal.exception.code,"IMPORT_FAILED")

    def test_transient_database_failure_does_not_mark_failed_or_cache_error(self):
        batch=self.validate();key=self.body()
        with patch("apps.imports.services.Customer.objects.bulk_create",side_effect=OperationalError("temporary")):
            with self.assertRaises(OperationalError):commit_upload(self.admin,batch.pk,key)
        batch.refresh_from_db();self.assertEqual(batch.status,"VALIDATED")
        self.assertEqual(batch.candidates.count(),1);self.assertEqual(IdempotencyRecord.objects.count(),0)
        self.assertTrue(commit_upload(self.admin,batch.pk,key)[0]["ok"])

    def test_expiration_boundary_rejects_commit_hides_rows_and_cleanup_purges(self):
        batch=self.validate()
        ImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now())
        result,status=commit_upload(self.admin,batch.pk,self.body())
        self.assertEqual((status,result["error"]["code"]),(409,"IMPORT_EXPIRED"))
        batch.refresh_from_db();self.assertEqual(batch.status,"EXPIRED")
        self.assertEqual(batch.candidates.count(),0);self.assertEqual(batch.row_results.count(),0)
        self.assertEqual(Customer.objects.count(),0)
        second=self.validate([row("가상2","01090000002")])
        now=second.expires_at
        with patch("apps.imports.services.timezone.now",return_value=now):
            response=result_page(self.admin,second.pk,{})
            self.assertEqual(response["rows"],[]);self.assertFalse(response["can_commit"])
        self.assertEqual(cleanup_imports(now=now)["batches_cleaned"],1)
        self.assertEqual(second.candidates.count(),0)

    def test_committed_result_survives_candidate_cleanup_and_metadata_expiry_keeps_customer(self):
        batch=self.validate();key=self.body();result,status=commit_upload(self.admin,batch.pk,key)
        cleanup_imports(now=batch.expires_at)
        self.assertEqual(ImportRowResult.objects.count(),0);self.assertEqual(ImportCandidate.objects.count(),0)
        self.assertEqual(commit_upload(self.admin,batch.pk,key),(result,status))
        with patch("apps.imports.services.timezone.now",return_value=batch.expires_at):
            expired,status_code=commit_upload(self.admin,batch.pk,self.body())
            self.assertEqual((status_code,expired["error"]["code"]),(409,"IMPORT_EXPIRED"))
        self.assertEqual(cleanup_imports(now=batch.expires_at+timedelta(days=7))["metadata_deleted"],1)
        self.assertFalse(ImportBatch.objects.exists());self.assertFalse(IdempotencyRecord.objects.filter(operation="IMPORT_COMMIT").exists())
        customer=Customer.objects.get();self.assertIsNone(customer.import_batch_id);self.assertEqual(ConsultationRevision.objects.count(),1)

    def test_results_are_paginated_full_phone_no_file_and_no_internal_failure_leak(self):
        batch=self.validate([row("가상오류",f"잘못된연락처{i:03}") for i in range(105)])
        first=self.client.get(f"/api/imports/{batch.pk}").json()
        second=self.client.get(f"/api/imports/{batch.pk}",{"page":2}).json()
        self.assertEqual((len(first["rows"]),len(second["rows"]),first["total_rows"]),(100,5,105))
        self.assertEqual(first["rows"][0]["phone_input"],"잘못된연락처000")
        self.assertEqual(first["rows"][0]["row_number"],2)
        for params in [{"page":0},{"kind":"secret"},{"employee__password":"x"}]:
            self.assertEqual(self.client.get(f"/api/imports/{batch.pk}",params).status_code,422)

    def test_empty_corrupt_macro_file_size_and_row_limit(self):
        for data,name,code in [(b"notzip","fake.xlsx","INVALID_XLSX"),(workbook([row()]),"fake.xlsm","INVALID_FILE_TYPE"),(workbook([]),"empty.xlsx","EMPTY_FILE"),
            (alter_zip(workbook([row()]),add={"xl/vbaProject.bin":b"fake macro"}),"macro.xlsx","MACRO_NOT_ALLOWED"),
            (alter_zip(workbook([row()]),add={"../unsafe.xml":b"x"}),"unsafe.xlsx","UNSAFE_XLSX")]:
            with self.subTest(code=code),self.assertRaises(AccessError) as caught:parse_upload(uploaded(data,name))
            self.assertEqual(caught.exception.code,code)
        with override_settings(IMPORT_MAX_BYTES=100):
            response=self.client.post("/api/imports/validate",{"site_id":self.site.pk,"file":uploaded(workbook([row()]))})
            self.assertEqual(response.status_code,413)
        with override_settings(IMPORT_MAX_ROWS=2):
            with self.assertRaises(AccessError) as caught:self.validate([row(),[],row("가상2","01090000002"),row("가상3","01090000003")])
            self.assertEqual(caught.exception.code,"TOO_MANY_ROWS")

    def test_xml_entities_sparse_bounds_and_far_extra_column_cannot_bypass_checks(self):
        data=workbook([row()])
        def entity(name,value):
            if name=="xl/worksheets/sheet1.xml":
                return b'<!DOCTYPE worksheet [<!ENTITY x "unsafe">]>'+value.replace(b"</worksheet>",b"&x;</worksheet>")
            return value
        with self.assertRaises(AccessError) as caught:parse_upload(uploaded(alter_zip(data,replace=entity)))
        self.assertEqual(caught.exception.code,"INVALID_XLSX")
        def huge_row(name,value):return value.replace(b'<row r="2">',b'<row r="999999999">') if name=="xl/worksheets/sheet1.xml" else value
        with self.assertRaises(AccessError):parse_upload(uploaded(alter_zip(data,replace=huge_row)))
        book=Workbook();sheet=book.active;sheet.append(HEADERS);sheet.append(row());sheet["XFD2"]="숨긴 추가 값"
        output=BytesIO();book.save(output);book.close()
        batch=validate_upload(self.admin,self.site.pk,uploaded(output.getvalue()))
        self.assertEqual(batch.validation_summary["invalid"],1)

    def test_original_temporary_file_is_deleted_on_success_and_failure(self):
        for data in [workbook([row()]),b"bad"]:
            file=TemporaryUploadedFile("fake.xlsx","application/octet-stream",len(data),None)
            path=Path(file.temporary_file_path());file.write(data);file.seek(0)
            try:parse_upload(file)
            except AccessError:pass
            self.assertFalse(path.exists());self.assertTrue(file.closed)

    def test_parser_warnings_and_fatal_http_logs_never_echo_raw_cell_or_database_error(self):
        book=Workbook();sheet=book.active;sheet.append(HEADERS);sheet.append(row(phone=1090000001));sheet["C2"].number_format="yyyy-mm-dd h:mm:ss"
        output=BytesIO();book.save(output);book.close();stderr=StringIO()
        with redirect_stderr(stderr):
            batch=validate_upload(self.admin,self.site.pk,uploaded(output.getvalue()))
        self.assertEqual(batch.validation_summary["invalid"],1);self.assertNotIn("1090000001",stderr.getvalue())
        batch=self.validate();logs=StringIO();handler=logging.StreamHandler(logs);logger=logging.getLogger("django.request");logger.addHandler(handler)
        sentinel="가상상담원문_01099999999"
        try:
            with patch("apps.imports.services.Customer.objects.bulk_create",side_effect=IntegrityError(sentinel)):
                response=self.client.post(f"/api/imports/{batch.pk}/commit",self.body(),content_type="application/json")
            self.assertEqual(response.status_code,500)
            self.assertNotIn(sentinel,response.content.decode()+logs.getvalue())
        finally:logger.removeHandler(handler)

    def test_zip_expansion_limit_and_forged_dimensions(self):
        data=workbook([row()])
        with patch("apps.imports.excel.MAX_EXPANDED_BYTES",100),self.assertRaises(AccessError) as caught:
            parse_upload(uploaded(data))
        self.assertEqual(caught.exception.code,"UNSAFE_XLSX")
        def dimension(name,value):return value.replace(b'ref="A1:I2"',b'ref="A1:A1"') if name=="xl/worksheets/sheet1.xml" else value
        batch=validate_upload(self.admin,self.site.pk,uploaded(alter_zip(data,replace=dimension)))
        self.assertEqual(batch.validation_summary["ready"],1)

    def test_role_session_revocation_rechecked_after_parse(self):
        User.objects.filter(pk=self.admin.pk).update(session_version=self.admin.session_version+1)
        with self.assertRaises(AccessError):self.validate()
        self.assertEqual(ImportBatch.objects.count(),0)

@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ImportConcurrencyTests(Fixtures,TransactionTestCase):
    def setUp(self):self.prepare()

    def test_cleanup_command_and_scheduler_once_are_idempotent(self):
        batch=self.validate();ImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        call_command("cleanup_imports",stdout=StringIO())
        call_command("run_scheduler",once=True,stdout=StringIO())
        batch.refresh_from_db();self.assertEqual(batch.status,"EXPIRED")
        self.assertFalse(ImportCandidate.objects.exists());self.assertFalse(ImportRowResult.objects.exists())

    def concurrent(self,fn):
        barrier=Barrier(2)
        def run(index):
            close_old_connections()
            try:
                actor=User.objects.get(pk=self.admin.pk);barrier.wait(timeout=10);return fn(actor,index)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,range(2)))

    def test_same_batch_same_key_exactly_once(self):
        batch=self.validate();key=self.body()
        results=self.concurrent(lambda actor,index:commit_upload(actor,batch.pk,key))
        self.assertEqual(results[0],results[1]);self.assertEqual(Customer.objects.count(),1)
        self.assertEqual(ConsultationRevision.objects.count(),1);self.assertEqual(IdempotencyRecord.objects.count(),1)

    def test_two_batches_same_phone_revalidate_under_lock(self):
        batches=[self.validate(),self.validate()];keys=[self.body(),self.body()]
        results=self.concurrent(lambda actor,index:commit_upload(actor,batches[index].pk,keys[index]))
        self.assertCountEqual([result[0]["success_count"] for result in results],[0,1])
        self.assertEqual(Customer.objects.count(),1);self.assertEqual(ConsultationRevision.objects.count(),1)

    def test_cleanup_commit_expired_boundary_no_customers(self):
        batch=self.validate();ImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now())
        results=self.concurrent(lambda actor,index:commit_upload(actor,batch.pk,self.body()) if index==0 else cleanup_imports())
        self.assertEqual(results[0][1],409);self.assertEqual(Customer.objects.count(),0)
