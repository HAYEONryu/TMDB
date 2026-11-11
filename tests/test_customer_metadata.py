"""Synthetic import, field permissions, stored-response and migration coverage."""
from datetime import timedelta
from io import StringIO
import json
from uuid import uuid4

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.ai_assistant.inputs import build
from apps.ai_assistant.models import Feature
from apps.customers.employee import check_one
from apps.customers.models import Customer
from apps.customers.queries import customer_list
from apps.customers.services import update_row
from apps.imports.excel import HEADERS
from apps.imports.services import validate_upload, commit_upload
from tests.helpers import TEST_HASHERS, login
from tests.test_imports import workbook, uploaded
from tests.test_p4 import Fixtures

PRIVATE = "SYNTHETIC_ADMIN_ONLY_METADATA"


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerMetadataTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.customer = Customer.objects.create(site=self.site, phone_normalized="01090000001", notes="기존 상담 보존", admin_notes=PRIVATE)
        self.assignment = self.assign(self.customer)

    def body(self, changes, **overrides):
        self.customer.refresh_from_db()
        return dict(customer_id=str(self.customer.pk), assignment_id=str(self.assignment.pk), mutation_id=str(uuid4()), expected_version=self.customer.version, changes=changes, **overrides)

    def listing(self, actor, **params):
        return customer_list(actor, {"site_id":str(self.site.pk), **params})

    def assert_private_absent(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertNotIn(PRIVATE, encoded)
        self.assertNotIn('admin_notes', encoded)

    def test_phone_only_customer_and_admin_staff_list_boundary(self):
        self.customer.full_clean()
        admin = self.listing(self.admin)["data"][0]
        staff = self.listing(self.employee)["data"][0]
        self.assertEqual(admin["customer_name"], "")
        self.assertEqual(admin["admin_notes"], PRIVATE)
        self.assert_private_absent(staff)
        for field in ["route", "memo", "residence"]:
            self.assertIn(field, staff)

    def test_admin_and_staff_edit_new_public_text_separate_from_consultation_notes(self):
        result = update_row(self.admin, self.body({"route":" 소개 ","residence":" 서울 ","memo":"새 비고\r\n다음 줄","admin_notes":PRIVATE+" updated"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["row"]["admin_notes"], PRIVATE+" updated")
        result = update_row(self.employee, self.body({"route":"온라인", "memo":"직원 비고", "residence":"부산"}))
        self.assertTrue(result["ok"])
        self.assert_private_absent(result)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.notes,"기존 상담 보존")
        self.assertEqual(self.customer.memo,"직원 비고")
        self.assertEqual(self.customer.admin_notes, PRIVATE+" updated")

    def test_employee_forged_admin_notes_update_and_wrong_owner_rejected(self):
        result = update_row(self.employee, self.body({"admin_notes":"forged", "memo":"must roll back"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"],"FORBIDDEN")
        self.assert_private_absent(result)
        self.customer.refresh_from_db()
        self.assertEqual((self.customer.admin_notes,self.customer.memo,self.customer.version),(PRIVATE,"",1))
        from apps.accounts.access import AccessError
        with self.assertRaises(AccessError):
            update_row(self.other, self.body({"memo":"wrong owner"}))

    def test_new_text_validation_and_stale_save(self):
        for changes in [{"memo":42},{"admin_notes":42},{"route":"가"*201},{"residence":"가"*201},{"memo":"가"*10001},{"admin_notes":"가"*10001}]:
            self.assertEqual(update_row(self.admin,self.body(changes))["error"]["code"],"VALIDATION_ERROR")
        stale = self.body({"memo":"late"})
        self.assertTrue(update_row(self.admin,self.body({"memo":"first"}))["ok"])
        result = update_row(self.employee,stale)
        self.assertEqual(result["error"]["code"],"VERSION_CONFLICT")
        self.assert_private_absent(result)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.memo,"first")

    def test_employee_history_and_ai_payload_never_include_private_snapshots(self):
        update_row(self.admin,self.body({"memo":"public edit","admin_notes":PRIVATE+" changed"}))
        update_row(self.admin,self.body({"admin_notes":PRIVATE+" private only"}))
        client=login(self.employee)
        path=f"/api/customers/{self.customer.pk}/history"
        response=client.get(path,{"kind":"consultations","assignment_id":str(self.assignment.pk)})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["total"],1)
        self.assert_private_absent(response.json())
        self.assertIn(PRIVATE, json.dumps(login(self.admin).get(path,{"kind":"consultations"}).json()))
        self.customer.refresh_from_db()
        now=timezone.now()
        for feature in [Feature.CLEANUP,Feature.SUMMARY,Feature.NEXT_QUESTIONS]:
            payload,_=build(feature,customer=self.customer,start=now-timedelta(days=7),end=now,korean_date=timezone.localdate())
            self.assert_private_absent(payload)
            self.assertEqual(len(payload["records"]),1)

    def test_private_only_edit_does_not_mark_assignment_consulted(self):
        update_row(self.admin,self.body({"admin_notes":PRIVATE+" edited"}))
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.first_activity_at)

    def test_admin_filter_works_staff_cannot_infer_private_values_by_filter_sort_options(self):
        self.assertEqual(self.listing(self.admin,filters=json.dumps({"admin_notes":{"contains":PRIVATE}}))["total"],1)
        client=login(self.employee)
        for query in [{"sort":"admin_notes"},{"filters":json.dumps({"admin_notes":{"contains":PRIVATE}})}]:
            response=client.get("/api/customers",{"site_id":str(self.site.pk),**query})
            self.assertEqual(response.status_code,422)
            self.assert_private_absent(response.json())
        response=client.get("/api/customers/filter-options",{"field":"admin_notes","site_id":str(self.site.pk)})
        self.assertEqual(response.status_code,422)

    def test_old_admin_receipt_is_redacted_after_role_change_in_save_and_queue_recovery(self):
        body=self.body({"memo":"admin public edit"})
        self.assertEqual(update_row(self.admin,body)["row"]["admin_notes"],PRIVATE)
        # Same account now owns the assignment as an employee. Replaying an
        # earlier authorized receipt must use current disclosure permissions.
        self.assignment.employee=self.admin;self.assignment.save(update_fields=["employee"])
        User.objects.filter(pk=self.admin.pk).update(role=User.Role.EMPLOYEE)
        self.admin.refresh_from_db()
        self.assert_private_absent(update_row(self.admin,body))
        recovered=check_one(self.admin,{"key":"synthetic-entry","site_id":str(self.site.pk),"customer_id":str(self.customer.pk),"assignment_id":str(self.assignment.pk),"expected_version":1,"inflight":body})
        self.assertEqual(recovered["code"],"RECEIPT")
        self.assert_private_absent(recovered)

    def test_six_column_import_phone_only_and_metadata_mapping(self):
        rows=[[None,"01090000002"," 서울 "," 전세 ","새 비고\r\n줄바꿈",PRIVATE],
              [" ","01090000003",None,None,None,None]]
        batch=validate_upload(self.admin,self.site.pk,uploaded(workbook(rows,headers=HEADERS)))
        self.assertEqual(batch.validation_summary["ready"],2)
        result,status=commit_upload(self.admin,batch.pk,{"site_id":str(self.site.pk),"idempotency_key":str(uuid4())})
        self.assertEqual((status,result["success_count"]),(200,2))
        customer=Customer.objects.get(phone_normalized="01090000002")
        self.assertEqual((customer.customer_name,customer.residence,customer.housing_status,customer.memo,customer.notes,customer.route,customer.admin_notes),("","서울","전세","새 비고\n줄바꿈","","",PRIVATE))
        self.assertIsNone(customer.current_assignment_id)
        self.assertEqual(customer.call_result,None)

    def test_six_column_import_rejects_missing_numeric_phone_formula_extra_values_and_duplicate(self):
        rows=[[None,None,None,None,None,"private without phone"],
              [None,1090000002,None,None,None,None],
              [None,"01090000002",None,None,"=1+1",None],
              [None,"01090000002",None,None,None,None,"extra"],
              [None,"01090000002",None,None,None,PRIVATE],
              [None,"010-9000-0002",None,None,None,None],
              [None,self.customer.phone_normalized,None,None,None,None]]
        batch=validate_upload(self.admin,self.site.pk,uploaded(workbook(rows,headers=HEADERS)))
        self.assertEqual(batch.validation_summary,dict(total=7,ready=1,invalid=4,duplicate_in_file=1,duplicate_existing=1))
        from apps.imports.services import result_page
        self.assert_private_absent(result_page(self.admin,batch.pk,{"kind":"all"}))

    def test_no_uncommitted_model_changes(self):
        call_command("makemigrations", "customers", dry_run=True, check=True, stdout=StringIO())


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerMetadataMigrationTests(Fixtures,TransactionTestCase):
    def test_previous_schema_synthetic_upgrade_preserves_existing_data(self):
        self.prepare()
        executor=MigrationExecutor(connection)
        target=[("customers","0003_live_phone_unique")]
        try:
            executor.migrate([("customers","0001_initial")])
            old=executor.loader.project_state([("customers","0001_initial")]).apps.get_model("customers","Customer")
            row=old.objects.create(site_id=self.site.pk,customer_name="가상 기존 고객",phone_normalized="01090000004",notes="기존 상담",housing_status="전세",version=7)
            executor=MigrationExecutor(connection);executor.migrate(target)
            current=Customer.objects.get(pk=row.pk)
            self.assertEqual((current.customer_name,current.notes,current.housing_status,current.version,current.site_id),("가상 기존 고객","기존 상담","전세",7,self.site.pk))
            self.assertEqual((current.route,current.residence,current.memo,current.admin_notes),("","","",""))
            blank=Customer.objects.create(site=self.site,phone_normalized="01090000005")
            blank.full_clean()
        finally:
            MigrationExecutor(connection).migrate(target)
