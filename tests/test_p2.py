from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import json
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer, CustomerChangeEvent, CustomerDeletionRequest
from apps.customers.queries import KST
from apps.customers.services import update_row, trash_operation
from apps.operations.models import MutationReceipt, IdempotencyRecord, OperationEvent
from apps.sites.models import Site, GlobalSettings, DefaultSiteHistory
from apps.sites.services import create_site
from tests.helpers import user, login, TEST_HASHERS


class Fixtures:
    def prepare(self):
        self.admin = user(role=User.Role.ADMIN, initial=False, name="가상관리자")
        self.employee = user("01000000002", initial=False, name="가상직원가")
        self.other = user("01000000003", initial=False, name="가상직원나")
        self.site, _ = create_site(self.admin, "가상현장 A")
        self.second, _ = create_site(self.admin, "가상현장 B")
        self.customer = Customer.objects.create(site=self.site, customer_name="가상고객", phone_normalized="01090000001")
        self.assignment = self.assign(self.customer, self.employee)

    def assign(self, customer, employee):
        assignment = Assignment.objects.create(customer=customer, employee=employee, assigned_by=self.admin, assigned_at=timezone.now()-timedelta(minutes=1))
        customer.current_assignment = assignment
        customer.save(update_fields=["current_assignment"])
        return assignment

    def body(self, changes=None, customer=None, **kwargs):
        customer = customer or self.customer
        return {"customer_id": str(customer.pk), "assignment_id": str(customer.current_assignment_id) if customer.current_assignment_id else None,
            "mutation_id": str(uuid4()), "expected_version": customer.version, "changes": changes or {"notes":"가짜 상담 메모"}, **kwargs}

    def bulk(self, **kwargs):
        return {"customer_ids":[str(self.customer.pk)], "site_id":str(self.site.pk), "idempotency_key":str(uuid4()), **kwargs}


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P2ApiTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.client = login(self.admin)

    def post(self, url, data):
        return self.client.post(url, data, content_type="application/json")

    def get(self, **params):
        return self.client.get("/api/customers", {"site_id":str(self.site.pk), **params})

    def test_sites_first_default_normalized_duplicate_and_explicit_default(self):
        settings = GlobalSettings.objects.get()
        self.assertEqual(settings.default_site_id, self.site.pk)
        self.assertEqual(DefaultSiteHistory.objects.count(), 1)
        response = self.post("/api/sites", {"name":" 가 상 현 장 A "})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "DUPLICATE_SITE")
        response = self.client.patch("/api/settings/default-site", {"site_id":str(self.second.pk), "expected_version":settings.version}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        stale = self.client.patch("/api/settings/default-site", {"site_id":str(self.site.pk), "expected_version":settings.version}, content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        settings.refresh_from_db()
        self.assertEqual(settings.default_site_id, self.second.pk)
        self.assertEqual(DefaultSiteHistory.objects.count(), 2)
        noop = self.client.patch("/api/settings/default-site", {"site_id":str(self.second.pk), "expected_version":settings.version}, content_type="application/json")
        self.assertFalse(noop.json()["changed"])
        self.assertEqual(DefaultSiteHistory.objects.count(), 2)

    def test_site_validation_and_role(self):
        for name in [None, "  ", "가"*101, [], 2]:
            self.assertEqual(self.post("/api/sites", {"name":name}).status_code, 422)
        self.client = login(self.employee)
        for url, body in [("/api/sites",{"name":"X"}),("/api/customers/soft-delete",self.bulk()),("/api/customers/restore",self.bulk())]:
            self.assertEqual(self.post(url,body).status_code,403)
        self.assertEqual(self.client.get("/app/admin/customers").status_code,403)
        self.assertEqual(self.client.get("/app/admin/trash").status_code,403)
        self.assertEqual(self.client.get(f"/api/sites/{self.site.pk}/counts").status_code,403)

    def test_dashboard_counts_and_selection_do_not_change_default(self):
        self.assertEqual(self.client.get(f"/api/sites/{self.site.pk}/counts").json(),{"total":1,"unassigned":0,"trash":0})
        self.assertEqual(self.client.get(f"/api/sites/{self.second.pk}/counts").json(),{"total":0,"unassigned":0,"trash":0})
        self.assertEqual(GlobalSettings.objects.get().default_site_id,self.site.pk)
        self.assertEqual(self.client.get(f"/api/sites/{uuid4()}/counts").status_code,409)

    def test_empty_sites_and_bad_request_shapes(self):
        self.customer.current_assignment=None;self.customer.save()
        Site.objects.all().delete()
        self.assertEqual(self.get(site_id="").json()["total"],0)
        self.assertEqual(self.client.get("/api/sites").json()["items"],[])
        for body in [[],{}, {"rows":[]},{"rows":[self.body()]*101}]:
            self.assertEqual(self.post("/api/customers/batch-update",body).status_code,422)

    def test_server_paging_sort_search_and_site_scope(self):
        Customer.objects.bulk_create([Customer(site=self.site,customer_name=f"가상{i:03}",phone_normalized=f"0108000{i:04}") for i in range(64)])
        Customer.objects.create(site=self.second,customer_name="다른 현장",phone_normalized="01099999999")
        first = self.get().json()
        second = self.get(page=2).json()
        self.assertEqual((len(first["data"]),len(second["data"]),first["total"]),(50,15,65))
        self.assertFalse({r["id"] for r in first["data"]}&{r["id"] for r in second["data"]})
        self.assertEqual(first["data"],self.get().json()["data"])
        self.assertEqual(len(self.get(page_size=100).json()["data"]),65)
        self.assertEqual(self.get(q="010-9000-0001").json()["total"],1)
        self.assertEqual(self.get(q="다른 현장").json()["total"],0)
        self.assertEqual(self.get(site_id=str(uuid4())).json()["error"]["code"],"SITE_DELETED")

    def test_scoped_filters_candidates_and_errors_never_disclose_other_employee(self):
        hidden = Customer.objects.create(site=self.site,customer_name="비공개가상고객",phone_normalized="01088888888",notes="비공개상담")
        self.assign(hidden,self.other)
        self.client=login(self.employee)
        self.assertEqual(self.get().json()["total"],1)
        self.assertEqual(self.get(view="all").status_code,403)
        self.assertEqual(self.get(view="trash").status_code,403)
        response=self.client.get("/api/customers/filter-options",{"site_id":str(self.site.pk),"field":"customer_name"})
        self.assertEqual(response.json()["values"],["가상고객"])
        response=self.post("/api/customers/batch-update",{"rows":[self.body(customer=hidden,expected_version=0),self.body(customer=hidden)]})
        # Duplicate batch is rejected before rows; retry one foreign row separately.
        self.assertEqual(response.status_code,422)
        foreign=self.post("/api/customers/batch-update",{"rows":[self.body(customer=hidden)]})
        self.assertEqual(foreign.json()["results"][0]["error"]["code"],"FORBIDDEN")
        self.assertNotIn("server_row",foreign.json()["results"][0])
        self.assertNotIn("비공개",foreign.content.decode())
        self.assertEqual(MutationReceipt.objects.count(),0)

    def test_filters_or_within_and_across_blank_exclude_notes_and_kst_dates(self):
        update_row(self.admin,self.body({"call_result":"INTERESTED","housing_status":"1주택","notes":"가짜 메모 알파","visit_at":"2026-11-04T00:00:00+09:00"}))
        Customer.objects.create(site=self.site,customer_name="빈값",phone_normalized="01090000002",call_result=None,housing_status="1주택",visit_at=datetime(2026,11,3,23,59,tzinfo=KST))
        Customer.objects.create(site=self.site,customer_name="다른값",phone_normalized="01090000003",call_result="REJECTED",housing_status="다주택",visit_at=datetime(2026,11,5,0,0,tzinfo=KST))
        def total(filters):return self.get(filters=json.dumps(filters)).json()["total"]
        self.assertEqual(total({"call_result":["INTERESTED",None],"housing_status":["1주택"]}),2)
        self.assertEqual(total({"call_result":{"values":["REJECTED"],"exclude":True}}),2)
        self.assertEqual(total({"call_result":[]}),0)
        self.assertEqual(total({"notes":{"contains":"알파"}}),1)
        self.assertEqual(total({"visit_at":{"from":"2026-11-04","to":"2026-11-04"}}),1)
        candidates=self.client.get("/api/customers/filter-options",{"site_id":str(self.site.pk),"field":"call_result","filters":json.dumps({"call_result":["REJECTED"],"housing_status":["1주택"]})}).json()
        self.assertCountEqual(candidates["values"],[None,"INTERESTED"])

    def test_filter_candidates_paged_at_100(self):
        Customer.objects.bulk_create([Customer(site=self.site,customer_name=f"후보{i:03}",phone_normalized=f"0107000{i:04}") for i in range(105)])
        first=self.client.get("/api/customers/filter-options",{"field":"customer_name","site_id":str(self.site.pk)}).json()
        second=self.client.get("/api/customers/filter-options",{"field":"customer_name","site_id":str(self.site.pk),"option_page":2}).json()
        self.assertEqual((len(first["values"]),len(second["values"]),first["total"]),(100,6,106))
        self.assertTrue(first["has_next"])
        self.assertFalse(second["has_next"])

    def test_reject_arbitrary_orm_queries_and_malformed_conditions(self):
        for params in [{"employee_id":str(self.other.pk)},{"sort":"site__created_by__password"},{"sort":"--notes"},{"page_size":1000},{"page":0},{"page":"NaN"},{"filters":"[]"},{"filters":"broken"},{"filters":json.dumps({"site__name":["X"]})},{"filters":json.dumps({"visit_at":{"from":"2026-12-01","to":"2026-01-01"}})},{"filters":json.dumps({"housing_status":{"values":[{}]}})}]:
            with self.subTest(params=params):self.assertEqual(self.get(**params).status_code,422)

    def test_save_batch_partial_success_and_whole_row_validation(self):
        other=Customer.objects.create(site=self.site,customer_name="가상다른고객",phone_normalized="01090000002")
        result=self.post("/api/customers/batch-update",{"rows":[self.body({"notes":"적용되면 안 됨","customer_name":42}),self.body({"notes":"성공"},customer=other)]}).json()["results"]
        self.assertEqual([r["ok"] for r in result],[False,True])
        self.customer.refresh_from_db();other.refresh_from_db()
        self.assertEqual(self.customer.notes,"");self.assertEqual(other.notes,"성공")
        self.assertEqual(ConsultationRevision.objects.count(),1)
        for field,value in [("phone_normalized",42),("current_assignment",None),("deleted_at",None),("first_activity_at",None),("version",99)]:
            response=self.post("/api/customers/batch-update",{"rows":[self.body({field:value})]})
            self.assertFalse(response.json()["results"][0]["ok"])

    def test_full_100_row_batch_of_10000_character_notes_fits_request_limit(self):
        customers=Customer.objects.bulk_create([Customer(site=self.site,customer_name=f"긴메모가상{i}",phone_normalized=f"0106000{i:04}") for i in range(100)])
        body={"rows":[self.body({"notes":"가"*10000},customer=customer) for customer in customers]}
        response=self.post("/api/customers/batch-update",body)
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()["results"]),100)
        self.assertTrue(all(row["ok"] for row in response.json()["results"]))
        self.assertEqual(ConsultationRevision.objects.count(),100)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=128)
    def test_oversized_request_is_json_413_without_applying_rows(self):
        response=self.post("/api/customers/batch-update",{"rows":[self.body({"notes":"가"*100})]})
        self.assertEqual(response.status_code,413)
        self.assertEqual(response.json()["error"]["code"],"PAYLOAD_TOO_LARGE")
        self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_admin_and_employee_save_actual_revision_progress_and_idempotent_replay(self):
        body=self.body({"notes":"새 상담\r\n메모","housing_status":" 1주택 ","contract_status":"CONTRACTED","call_result":"INTERESTED"})
        result=update_row(self.admin,body)
        again=update_row(self.admin,body)
        self.assertEqual(result,again)
        self.customer.refresh_from_db();self.assignment.refresh_from_db()
        self.assertEqual(self.customer.version,2);self.assertEqual(self.customer.notes,"새 상담\n메모");self.assertEqual(self.customer.housing_status,"1주택")
        self.assertIsNotNone(self.assignment.first_activity_at)
        revision=ConsultationRevision.objects.get()
        self.assertEqual(revision.actor,self.admin);self.assertEqual(revision.assignment,self.assignment)
        self.assertEqual(revision.before_values["notes"],"");self.assertEqual(revision.after_values["notes"],self.customer.notes)
        self.assertEqual(revision.customer_version,2);self.assertEqual(revision.notes,self.customer.notes)
        self.assertEqual(CustomerChangeEvent.objects.count(),1);self.assertEqual(MutationReceipt.objects.count(),1)
        with self.assertRaises(AccessError) as caught:update_row(self.admin,{**body,"changes":{"notes":"다른내용"}})
        self.assertEqual(caught.exception.code,"IDEMPOTENCY_CONFLICT")
        first_activity=self.assignment.first_activity_at
        update_row(self.employee,self.body({"notes":""}))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.first_activity_at,first_activity)
        self.assertEqual(ConsultationRevision.objects.count(),2)

    def test_noop_normalization_never_progresses(self):
        result=update_row(self.admin,self.body({"notes":"","housing_status":"   ","contract_status":"","call_result":"","visit_at":"","callback_due_at":None}))
        self.assertFalse(result["changed"])
        self.customer.refresh_from_db();self.assignment.refresh_from_db()
        self.assertEqual(self.customer.version,1);self.assertIsNone(self.assignment.first_activity_at)
        self.assertEqual(CustomerChangeEvent.objects.count(),0);self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_callback_create_update_cancel_atomic_consultation_changes(self):
        update_row(self.admin,self.body({"callback_due_at":"2026-11-04T14:30"}))
        callback=Callback.objects.get();self.assertEqual(timezone.localtime(callback.due_at,KST).hour,14)
        self.customer.refresh_from_db()
        update_row(self.admin,self.body({"callback_due_at":"2026-11-05T10:00+09:00"}))
        callback.refresh_from_db();self.assertEqual(callback.version,2)
        self.customer.refresh_from_db()
        update_row(self.admin,self.body({"callback_due_at":None}))
        callback.refresh_from_db();self.assertEqual(callback.status,"CANCELLED");self.assertEqual(callback.version,3)
        self.assertEqual(ConsultationRevision.objects.order_by("customer_version").last().after_values["callback_due_at"],None)
        self.assertEqual(ConsultationRevision.objects.count(),3)

    def test_failed_revision_rolls_back_every_side_effect(self):
        with patch("apps.customers.services.ConsultationRevision.objects.create",side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):update_row(self.admin,self.body({"notes":"중간실패","callback_due_at":"2026-11-04T12:00"}))
        self.customer.refresh_from_db();self.assignment.refresh_from_db()
        self.assertEqual((self.customer.version,self.customer.notes),(1,""));self.assertIsNone(self.assignment.first_activity_at)
        for model in [ConsultationRevision,CustomerChangeEvent,Callback,MutationReceipt]:self.assertEqual(model.objects.count(),0)

    def test_version_conflict_requires_fresh_mutation_and_keeps_failed_receipt(self):
        stale=self.body({"notes":"내 변경"})
        update_row(self.admin,self.body({"notes":"서버 변경"}))
        result=update_row(self.admin,stale)
        self.assertFalse(result["ok"]);self.assertEqual(result["error"]["code"],"VERSION_CONFLICT")
        self.assertEqual(result["server_row"]["notes"],"서버 변경")
        self.assertEqual(update_row(self.admin,stale),result)
        self.assertEqual(ConsultationRevision.objects.count(),1)
        reapplied={**stale,"expected_version":2,"mutation_id":str(uuid4())}
        self.assertTrue(update_row(self.admin,reapplied)["ok"])

    def test_same_employee_new_assignment_cannot_accept_old_buffer(self):
        body=self.body()
        self.assignment.ended_at=timezone.now();self.assignment.end_reason="REASSIGNED";self.assignment.save()
        self.assign(self.customer,self.employee)
        with self.assertRaises(AccessError) as caught:update_row(self.employee,body)
        self.assertEqual(caught.exception.code,"ASSIGNMENT_CHANGED")
        self.assertEqual(MutationReceipt.objects.count(),0)

    def test_unassigned_admin_save_never_progresses_future_assignment(self):
        customer=Customer.objects.create(site=self.site,customer_name="미할당가상",phone_normalized="01090000002")
        update_row(self.admin,self.body(customer=customer))
        new=self.assign(customer,self.employee)
        self.assertIsNone(new.first_activity_at)
        self.assertIsNone(ConsultationRevision.objects.get().assignment_id)

    def test_validation_datetime_text_limit_and_preserved_system_append_allowance(self):
        for changes in [{"visit_at":"2026-11-04"},{"visit_at":"2026-99-01T12:00"},{"notes":"가"*10001},{"housing_status":"가"*201},{"call_result":"OTHER"},{"contract_status":"OTHER"}]:
            with self.subTest(changes=str(changes)[:60]):self.assertFalse(update_row(self.admin,self.body(changes))["ok"])
        self.customer.notes="가"*10020;self.customer.save()
        self.assertTrue(update_row(self.admin,self.body({"notes":"나"*10020}))["ok"])

    def test_soft_delete_close_request_restore_preserves_business_history(self):
        update_row(self.admin,self.body({"notes":"보존","call_result":"INTERESTED","callback_due_at":"2026-11-05T10:00"}))
        request=CustomerDeletionRequest.objects.create(customer=self.customer,requested_by=self.employee,requested_assignment=self.assignment,requested_at=timezone.now())
        body=self.bulk();result=trash_operation(self.admin,body)
        self.assertEqual(trash_operation(self.admin,body),result)
        self.customer.refresh_from_db();self.assignment.refresh_from_db();request.refresh_from_db()
        self.assertIsNotNone(self.customer.deleted_at);self.assertIsNone(self.customer.current_assignment_id)
        self.assertEqual(self.assignment.end_reason,"SOFT_DELETED")
        self.assertEqual((request.status,request.close_reason,request.deletion_note),("CLOSED","ALREADY_DELETED",""))
        self.assertEqual(self.customer.notes,"보존")
        self.assertEqual(self.get().json()["total"],0)
        self.assertEqual(self.get(view="trash",site_id="all").json()["total"],1)
        restore=self.bulk(site_id="all");self.assertEqual(trash_operation(self.admin,restore,restore=True)["affected_count"],1)
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.deleted_at);self.assertIsNone(self.customer.current_assignment_id)
        self.assertEqual(self.customer.call_result,"INTERESTED");self.assertEqual(self.customer.notes,"보존")
        self.assertEqual(Callback.objects.get().status,"PENDING");self.assertEqual(ConsultationRevision.objects.count(),1)
        new=self.assign(self.customer,self.employee)
        self.assertEqual(trash_operation(self.admin,restore,restore=True)["affected_count"],1) # cached previous receipt
        self.customer.refresh_from_db();self.assertEqual(self.customer.current_assignment_id,new.pk)
        self.assertEqual(trash_operation(self.admin,self.bulk(),restore=True)["affected_count"],0)
        self.customer.refresh_from_db();self.assertEqual(self.customer.current_assignment_id,new.pk)
        self.assertEqual(OperationEvent.objects.filter(operation="SOFT_DELETE").count(),1)

    def test_bulk_missing_or_wrong_site_is_all_or_nothing(self):
        for body in [self.bulk(customer_ids=[str(self.customer.pk),str(uuid4())]),self.bulk(site_id=str(self.second.pk))]:
            with self.assertRaises(AccessError):trash_operation(self.admin,body)
            self.customer.refresh_from_db();self.assertIsNone(self.customer.deleted_at)
        self.assertEqual(IdempotencyRecord.objects.count(),0)

    def test_actor_revocation_rechecked_under_write_lock_even_before_cached_response(self):
        body=self.body();update_row(self.admin,body)
        User.objects.filter(pk=self.admin.pk).update(session_version=self.admin.session_version+1)
        with self.assertRaises(AccessError) as caught:update_row(self.admin,body)
        self.assertEqual(caught.exception.code,"UNAUTHENTICATED")

    def test_receipt_expiry_and_staff_permission_precede_replay(self):
        body=self.body()
        update_row(self.employee,body)
        MutationReceipt.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(AccessError) as expired:update_row(self.employee,body)
        self.assertEqual(expired.exception.code,"IDEMPOTENCY_EXPIRED")
        self.assignment.ended_at=timezone.now();self.assignment.end_reason="REASSIGNED";self.assignment.save()
        self.assign(self.customer,self.other)
        with self.assertRaises(AccessError) as forbidden:update_row(self.employee,body)
        # P5 distinguishes this user's old assignment from an unrelated customer's ID.
        self.assertEqual(forbidden.exception.code,"ASSIGNMENT_CHANGED")
        self.assertEqual(forbidden.exception.status,409)
        self.assertIsNone(forbidden.exception.fields)

    @override_settings(ALLOW_DEMO_SEED=True)
    def test_fake_seed_idempotent_preserves_edits_and_password(self):
        password=self.admin.password
        call_command("seed_demo_customers",stdout=io.StringIO())
        sample=Customer.objects.get(phone_normalized="01090000065")
        sample.notes="사용자 수정";sample.save()
        call_command("seed_demo_customers",stdout=io.StringIO())
        sample.refresh_from_db();self.admin.refresh_from_db()
        self.assertEqual(sample.notes,"사용자 수정");self.assertEqual(self.admin.password,password)
        self.assertEqual(ConsultationRevision.objects.filter(source="BASELINE").count(),65)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P2ConcurrencyTests(Fixtures, TransactionTestCase):
    def setUp(self):self.prepare()

    def concurrent(self, fn):
        barrier=Barrier(2)
        def run(index):
            close_old_connections()
            try:
                actor=User.objects.get(pk=self.admin.pk)
                barrier.wait(timeout=10)
                return fn(actor,index)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,range(2)))

    def test_two_updates_same_version_exactly_one_revision(self):
        bodies=[self.body({"notes":f"동시 변경{i}"}) for i in range(2)]
        results=self.concurrent(lambda actor,index:update_row(actor,bodies[index]))
        self.assertEqual(sum(r["ok"] for r in results),1)
        self.assertEqual([r["error"]["code"] for r in results if not r["ok"]],["VERSION_CONFLICT"])
        self.assertEqual(ConsultationRevision.objects.count(),1);self.assertEqual(CustomerChangeEvent.objects.count(),1)

    def test_replayed_mutation_concurrent_once(self):
        body=self.body()
        results=self.concurrent(lambda actor,_:update_row(actor,body))
        self.assertEqual(results[0],results[1]);self.assertEqual(ConsultationRevision.objects.count(),1);self.assertEqual(MutationReceipt.objects.count(),1)

    def test_soft_delete_same_key_concurrent_once(self):
        body=self.bulk()
        results=self.concurrent(lambda actor,_:trash_operation(actor,body))
        self.assertEqual(results[0],results[1]);self.assertEqual(IdempotencyRecord.objects.count(),1)
        self.assertEqual(OperationEvent.objects.filter(operation="SOFT_DELETE").count(),1)

    def test_site_normalization_concurrent_one_success(self):
        def operation(actor,index):
            try:return str(create_site(actor,["동시 현장","동 시 현 장"][index])[0].pk)
            except AccessError as exc:return exc.code
        results=self.concurrent(operation)
        self.assertEqual(results.count("DUPLICATE_SITE"),1);self.assertEqual(Site.objects.filter(name_key="동시현장").count(),1)

    def test_save_versus_delete_never_partial_journal(self):
        body=self.body()
        def operation(actor,index):
            try:return update_row(actor,body) if index==0 else trash_operation(actor,self.bulk())
            except AccessError as exc:return exc.code
        results=self.concurrent(operation)
        self.customer.refresh_from_db();self.assignment.refresh_from_db()
        self.assertIsNotNone(self.customer.deleted_at);self.assertIsNone(self.customer.current_assignment_id)
        self.assertIsNotNone(self.assignment.ended_at)
        revisions=ConsultationRevision.objects.count()
        self.assertIn(revisions,[0,1]);self.assertEqual(CustomerChangeEvent.objects.count(),revisions)
        self.assertEqual(self.customer.notes,"가짜 상담 메모" if revisions else "")
