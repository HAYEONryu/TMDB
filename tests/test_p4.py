from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
import io

from django.core.management import call_command
from django.db import IntegrityError,close_old_connections
from django.test import TestCase,TransactionTestCase,override_settings,Client
from django.utils import timezone
from apps.accounts.models import User
from apps.accounts.access import AccessError
from apps.accounts.services import set_user_access,reset_password,change_password
from apps.accounts.management_services import update_users,create_user,user_list,transfer_list
from apps.assignments.models import Assignment
from apps.assignments.services import distribute,recall,recall_preview,change_assignee
from apps.callbacks.models import Callback
from apps.common.receipts import cleanup_p4_receipts
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerChangeEvent,CustomerDeletionRequest
from apps.customers.services import update_row
from apps.customers.queries import KST
from apps.operations.models import IdempotencyRecord,OperationEvent
from apps.common.transactions import BUSINESS_LOCK_KEY
from django.db import connection,OperationalError
from apps.sites.services import create_site
from tests.helpers import user,login,TEST_HASHERS,STRONG_PASSWORD,password_data


class Fixtures:
    def prepare(self):
        self.admin=user(role=User.Role.ADMIN,initial=False,name="가상관리자")
        self.employee=user("01000000002",initial=False,name="가상직원가")
        self.other=user("01000000003",initial=False,name="가상직원나")
        self.site,_=create_site(self.admin,"가상 분배 현장")
        self.second,_=create_site(self.admin,"다른 가상 현장")

    def customers(self,count=1,site=None,offset=0):
        return Customer.objects.bulk_create([Customer(site=site or self.site,customer_name=f"가상고객{offset+i:04}",phone_normalized=f"010800{offset+i:05}") for i in range(count)])

    def body(self,**kwargs):return {"site_id":str(self.site.pk),"employee_id":"all","quantity":1,"idempotency_key":str(uuid4()),**kwargs}
    def recall_body(self,**kwargs):return {key:value for key,value in self.body(**kwargs).items() if key!="quantity"}

    def assign(self,customer,employee=None,*,at=None,progress=False):
        assignment=Assignment.objects.create(customer=customer,employee=employee or self.employee,assigned_by=self.admin,assigned_at=at or timezone.now()-timedelta(minutes=1),first_activity_at=timezone.now() if progress else None)
        customer.current_assignment=assignment;customer.save(update_fields=["current_assignment"]);return assignment

    def assignee_body(self,customer,target=None,**kwargs):
        return {"site_id":str(customer.site_id),"employee_id":str(target.pk) if target else None,"assignment_id":str(customer.current_assignment_id) if customer.current_assignment_id else None,
            "expected_version":customer.version,"idempotency_key":str(uuid4()),**kwargs}

    def edit(self,person,**kwargs):
        return {"id":str(person.pk),"expected_version":person.updated_at.isoformat(),"name":person.name,"phone":person.phone_normalized,"role":person.role,"is_active":person.is_active,**kwargs}

    def user_body(self,*rows):return {"rows":list(rows),"idempotency_key":str(uuid4())}
    def mutation(self,customer,notes="가상 저장"):
        return {"customer_id":str(customer.pk),"assignment_id":str(customer.current_assignment_id) if customer.current_assignment_id else None,"expected_version":customer.version,"mutation_id":str(uuid4()),"changes":{"notes":notes}}


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P4Tests(Fixtures,TestCase):
    def setUp(self):self.prepare();self.client=login(self.admin)

    def post(self,path,body):return self.client.post(path,body,content_type="application/json")

    def test_four_employees_95_customers_30_each_allocates_zero_and_suggests23(self):
        user("01000000004",initial=False);user("01000000005",initial=False)
        self.customers(95)
        body=self.body(quantity=30);result,status=distribute(self.admin,body)
        self.assertEqual(status,409);self.assertEqual(result["error"]["message"],"23개씩 분배할 수 있습니다.")
        self.assertEqual(result["error"]["fields"]["allocated_count"],0)
        self.assertEqual(Assignment.objects.count(),0);self.assertFalse(Customer.objects.exclude(current_assignment=None).exists())
        self.assertEqual(distribute(self.admin,body),(result,status))
        self.assertEqual(OperationEvent.objects.filter(operation="DISTRIBUTE").count(),0)

    def test_distribution_random_nonoverlap_target_site_and_receipt_replay(self):
        self.customers(11);self.customers(2,self.second)
        deleted=self.customers(1,offset=20)[0];deleted.deleted_at=timezone.now();deleted.deleted_by=self.admin;deleted.save()
        owned=self.customers(1,offset=21)[0];self.assign(owned)
        inactive=user("01000000004",initial=False)
        inactive.is_active=False;inactive.save()
        body=self.body(quantity=4);result,status=distribute(self.admin,body)
        self.assertEqual((status,result["allocated_count"],result["available_count"]),(200,8,3))
        self.assertEqual({item["employee_id"] for item in result["employees"]},{str(self.employee.pk),str(self.other.pk)})
        self.assertEqual(distribute(self.admin,body),(result,status))
        self.assertEqual(Assignment.objects.count(),9)
        self.assertFalse(Assignment.objects.filter(employee=inactive).exists());self.assertFalse(Assignment.objects.filter(employee=self.admin).exists())
        self.assertEqual(CustomerChangeEvent.objects.count(),0);self.assertEqual(ConsultationRevision.objects.count(),0)
        self.assertTrue(all(a.first_activity_at is None for a in Assignment.objects.all()))
        self.assertFalse(Customer.objects.filter(site=self.second).exclude(current_assignment=None).exists())
        with self.assertRaises(AccessError) as conflict:distribute(self.admin,{**body,"quantity":1})
        self.assertEqual(conflict.exception.code,"IDEMPOTENCY_CONFLICT")

    def test_invalid_quantities_and_employee_zero_admin_inactive_and_unknown(self):
        for quantity in [0,-1,1.5,True,"1"]:
            self.assertEqual(self.post("/api/assignments/distribute",self.body(quantity=quantity)).status_code,422)
        for employee_id in [str(self.admin.pk),str(uuid4())]:
            self.assertEqual(distribute(self.admin,self.body(employee_id=employee_id))[0]["error"]["code"],"INVALID_EMPLOYEE")
        set_user_access(self.admin,self.employee.pk,is_active=False);set_user_access(self.admin,self.other.pk,is_active=False)
        result,status=distribute(self.admin,self.body())
        self.assertEqual((status,result["error"]["message"]),(409,"분배할 활성 직원이 없습니다."))

    def test_availability_is_advisory_and_executor_rechecks_all_team_members(self):
        self.customers(5)
        response=self.client.get("/api/assignments/availability",{"site_id":str(self.site.pk)})
        self.assertEqual(response.json()["available_count"],5)
        extra=user("01000000004",initial=False)
        result,status=distribute(self.admin,self.body(quantity=2))
        self.assertEqual(status,409);self.assertEqual(result["error"]["fields"]["employee_count"],3)
        set_user_access(self.admin,extra.pk,is_active=False)
        result,status=distribute(self.admin,self.body(quantity=2))
        self.assertEqual((status,result["allocated_count"]),(200,4))

    def test_manual_recall_today_all_includes_progress_but_not_other_site_or_past(self):
        start=datetime.combine(timezone.localdate(),datetime.min.time(),KST)
        a,b,c,d=self.customers(4)
        current=self.assign(a,at=start,progress=True);self.assign(b,at=start+timedelta(seconds=1))
        old=self.assign(c,at=start-timedelta(microseconds=1));promoted=self.assign(d,self.other)
        set_user_access(self.admin,self.other.pk,role=User.Role.ADMIN)
        elsewhere=self.customers(1,self.second)[0];other_assignment=self.assign(elsewhere)
        a.notes="가상 상담 보존";a.call_result="INTERESTED";a.save()
        Callback.objects.create(customer=a,due_at=timezone.now()+timedelta(days=1),created_by=self.admin,updated_by=self.admin)
        request=CustomerDeletionRequest.objects.create(customer=a,requested_by=self.employee,requested_assignment=current,requested_at=timezone.now())
        preview=recall_preview({"site_id":str(self.site.pk),"employee_id":"all"});self.assertEqual(preview["target_count"],2)
        key=self.recall_body();result,status=recall(self.admin,key)
        self.assertEqual((status,result["recalled_count"]),(200,2));self.assertEqual(recall(self.admin,key),(result,status))
        for assignment in [old,promoted,other_assignment]:assignment.refresh_from_db();self.assertIsNone(assignment.ended_at)
        current.refresh_from_db();self.assertEqual(current.end_reason,"MANUAL_RECALL");self.assertIsNotNone(current.first_activity_at)
        a.refresh_from_db();self.assertEqual(a.notes,"가상 상담 보존");self.assertEqual(a.call_result,"INTERESTED");self.assertIsNone(a.current_assignment_id)
        self.assertEqual(Callback.objects.get().status,"PENDING");request.refresh_from_db();self.assertEqual(request.status,"PENDING")

    def test_recall_preview_is_recomputed_and_only_selected_employee(self):
        a,b,c=self.customers(3);self.assign(a);self.assign(b,self.other)
        preview=recall_preview({"site_id":str(self.site.pk),"employee_id":str(self.employee.pk)})
        self.assertEqual(preview["target_count"],1);self.assign(c)
        result,status=recall(self.admin,self.recall_body(employee_id=str(self.employee.pk)))
        self.assertEqual(result["recalled_count"],2)
        b.refresh_from_db();self.assertIsNotNone(b.current_assignment_id)

    def test_assignee_noop_reassign_clear_and_old_buffer_rejection(self):
        customer=self.customers()[0];old=self.assign(customer,progress=True);before=self.mutation(customer)
        same=self.assignee_body(customer,self.employee)
        result,status=change_assignee(self.admin,customer.pk,same)
        self.assertFalse(result["changed"]);old.refresh_from_db();self.assertIsNotNone(old.first_activity_at)
        self.assertEqual(Assignment.objects.count(),1);customer.refresh_from_db();self.assertEqual(customer.version,1)
        body=self.assignee_body(customer,self.other);result,status=change_assignee(self.admin,customer.pk,body)
        self.assertTrue(result["changed"]);self.assertEqual(change_assignee(self.admin,customer.pk,body),(result,status))
        old.refresh_from_db();self.assertEqual(old.end_reason,"REASSIGNED")
        customer.refresh_from_db();new=customer.current_assignment;self.assertEqual(new.employee_id,self.other.pk);self.assertIsNone(new.first_activity_at)
        self.assertNotEqual(new.pk,old.pk)
        with self.assertRaises(AccessError):update_row(self.employee,before)
        change_assignee(self.admin,customer.pk,self.assignee_body(customer))
        customer.refresh_from_db();self.assertIsNone(customer.current_assignment_id)
        self.assertEqual(CustomerChangeEvent.objects.count(),0)

    def test_same_employee_after_recall_has_new_assignment_and_stale_buffer_rejected(self):
        customer=self.customers()[0];old=self.assign(customer);body=self.mutation(customer)
        change_assignee(self.admin,customer.pk,self.assignee_body(customer));customer.refresh_from_db()
        change_assignee(self.admin,customer.pk,self.assignee_body(customer,self.employee))
        customer.refresh_from_db();self.assertNotEqual(customer.current_assignment_id,old.pk)
        with self.assertRaises(AccessError) as error:update_row(self.employee,body)
        self.assertEqual(error.exception.code,"ASSIGNMENT_CHANGED")

    def test_assignee_optimistic_checks_deleted_site_and_ineligible_recipient(self):
        customer=self.customers()[0]
        body=self.assignee_body(customer,self.employee)
        update_row(self.admin,self.mutation(customer))
        self.assertEqual(change_assignee(self.admin,customer.pk,body)[0]["error"]["code"],"VERSION_CONFLICT")
        customer.refresh_from_db();set_user_access(self.admin,self.employee.pk,is_active=False)
        self.assertEqual(change_assignee(self.admin,customer.pk,self.assignee_body(customer,self.employee))[0]["error"]["code"],"INVALID_EMPLOYEE")
        customer.deleted_at=timezone.now();customer.deleted_by=self.admin;customer.save()
        self.assertEqual(change_assignee(self.admin,customer.pk,self.assignee_body(customer,self.other))[0]["error"]["code"],"CUSTOMER_DELETED")

    def test_distribution_and_recall_database_failures_are_atomic(self):
        self.customers(4)
        with patch("apps.assignments.services.Customer.objects.bulk_update",side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):distribute(self.admin,self.body())
        self.assertEqual(Assignment.objects.count(),0);self.assertEqual(IdempotencyRecord.objects.count(),0)
        distribute(self.admin,self.body())
        count=Assignment.objects.count()
        with patch("apps.assignments.services.Assignment.objects.filter",side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):recall(self.admin,self.recall_body())
        self.assertEqual(Customer.objects.exclude(current_assignment=None).count(),count)
        self.assertEqual(Assignment.objects.filter(ended_at__isnull=False).count(),0)

    def test_user_create_initial_password_unique_no_privilege_fields_or_secret_output(self):
        body={"name":" 가상신규 ","phone":"010-0000-0010","role":"EMPLOYEE","idempotency_key":str(uuid4())}
        result,status=create_user(self.admin,body);self.assertEqual(create_user(self.admin,body),(result,status))
        account=User.objects.get(pk=result["id"]);self.assertEqual(account.name,"가상신규");self.assertTrue(account.is_active)
        self.assertTrue(account.check_password("dodream"));self.assertTrue(account.must_change_password);self.assertFalse(account.is_staff);self.assertFalse(account.is_superuser)
        listing=self.client.get("/api/users").content.decode();self.assertNotIn("dodream",listing);self.assertNotIn(account.password,listing);self.assertNotIn('"password"',listing)
        self.assertEqual(self.post("/api/users",{**body,"idempotency_key":str(uuid4())}).status_code,409)
        self.assertEqual(self.post("/api/users",{**body,"is_superuser":True}).status_code,422)

    def test_user_edits_atomic_stale_duplicate_and_phone_session_invalidation(self):
        staff_client=login(self.employee)
        stale=self.user_body(self.edit(self.employee,name="오래된 값"))
        body=self.user_body(self.edit(self.employee,name=" 가상이름 ",phone="010-0000-0011"))
        result,status=update_users(self.admin,body);self.assertEqual(update_users(self.admin,body),(result,status))
        self.assertEqual(staff_client.get("/api/me").status_code,401)
        self.employee.refresh_from_db();self.assertEqual((self.employee.name,self.employee.phone_normalized),("가상이름","01000000011"))
        with self.assertRaises(AccessError) as error:update_users(self.admin,stale)
        self.assertEqual(error.exception.code,"VERSION_CONFLICT")
        body=self.user_body(self.edit(self.employee,name="반영 금지"),self.edit(self.other,phone=self.employee.phone_normalized))
        self.assertEqual(self.post("/api/users/batch-update",body).status_code,409)
        self.employee.refresh_from_db();self.assertEqual(self.employee.name,"가상이름")

    def test_deactivation_all_sites_dates_only_unprogressed_keeps_progress_and_reactivation_does_not_restore(self):
        a,b=self.customers(2);c,d=self.customers(2,self.second)
        for customer,progress in [(a,False),(b,True),(c,False),(d,True)]:
            customer.call_result="INTERESTED";customer.notes="가상 보존";customer.save();self.assign(customer,at=timezone.now()-timedelta(days=10),progress=progress)
        body=self.user_body(self.edit(self.employee,is_active=False));result,status=update_users(self.admin,body)
        self.assertEqual(result["recalled_count"],2);self.assertEqual(result["transfer_needed_count"],2)
        for customer in [a,c]:customer.refresh_from_db();self.assertIsNone(customer.current_assignment_id);self.assertEqual(customer.notes,"가상 보존")
        for customer in [b,d]:customer.refresh_from_db();self.assertIsNotNone(customer.current_assignment_id)
        self.assertEqual(transfer_list({})["total"],2)
        self.employee.refresh_from_db();update_users(self.admin,self.user_body(self.edit(self.employee,is_active=True)))
        self.assertEqual(Customer.objects.exclude(current_assignment=None).count(),2)
        self.assertEqual(transfer_list({})["total"],0)

    def test_last_admin_guard_and_atomic_handover_and_promotion_preserves_assignment(self):
        self.assertEqual(self.post("/api/users/batch-update",self.user_body(self.edit(self.admin,is_active=False))).json()["error"]["code"],"LAST_ACTIVE_ADMIN")
        customer=self.customers()[0];assignment=self.assign(customer)
        result,status=update_users(self.admin,self.user_body(self.edit(self.admin,role="EMPLOYEE"),self.edit(self.employee,role="ADMIN")))
        self.assertTrue(result["requires_relogin"])
        assignment.refresh_from_db();customer.refresh_from_db();self.assertIsNone(assignment.ended_at);self.assertEqual(customer.current_assignment_id,assignment.pk)
        self.assertEqual(self.client.get("/api/users").status_code,401)

    def test_name_only_change_keeps_session_and_noop_does_not_bump_token(self):
        client=login(self.employee);old_version=self.employee.updated_at
        result,status=update_users(self.admin,self.user_body(self.edit(self.employee)))
        self.employee.refresh_from_db();self.assertEqual(self.employee.updated_at,old_version);self.assertEqual(result["updated_count"],0)
        update_users(self.admin,self.user_body(self.edit(self.employee,name="가상변경")))
        self.assertEqual(client.get("/api/me").status_code,200)

    def test_reset_same_key_after_password_change_never_resets_twice(self):
        body={"idempotency_key":str(uuid4())};client=login(self.employee)
        self.assertEqual(self.post(f"/api/users/{self.employee.pk}/reset-password",body).status_code,200)
        self.assertEqual(client.get("/api/me").status_code,401)
        self.employee.refresh_from_db();changed=change_password(self.employee,password_data(new="Another!River2026"));version=changed.session_version
        self.assertEqual(self.post(f"/api/users/{self.employee.pk}/reset-password",body).status_code,200)
        changed.refresh_from_db();self.assertEqual(changed.session_version,version);self.assertFalse(changed.must_change_password);self.assertTrue(changed.check_password("Another!River2026"))

    def test_user_batch_failure_rolls_back_recalls_names_and_sessions(self):
        customer=self.customers()[0];assignment=self.assign(customer);version=self.employee.session_version
        with patch("apps.accounts.management_services.OperationEvent.objects.create",side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):update_users(self.admin,self.user_body(self.edit(self.employee,is_active=False)))
        customer.refresh_from_db();assignment.refresh_from_db();self.employee.refresh_from_db()
        self.assertIsNotNone(customer.current_assignment_id);self.assertIsNone(assignment.ended_at);self.assertTrue(self.employee.is_active);self.assertEqual(self.employee.session_version,version)

    def test_staff_cannot_use_assignment_user_or_transfer_apis(self):
        self.client=login(self.employee);customer=self.customers()[0]
        for path in ["/api/users","/api/users/transfer-needed","/api/assignments/availability?site_id="+str(self.site.pk),"/app/admin/users","/app/admin/assignments"]:self.assertEqual(self.client.get(path).status_code,403)
        for path,body in [("/api/assignments/distribute",self.body()),("/api/assignments/recall",self.recall_body()),("/api/assignments/recall-preview",{"site_id":str(self.site.pk),"employee_id":"all"}),(f"/api/customers/{customer.pk}/assignee",self.assignee_body(customer,self.other)),("/api/users/batch-update",self.user_body(self.edit(self.employee)))]:self.assertEqual(self.post(path,body).status_code,403)
        self.assertEqual(self.client.get("/api/customers",{"site_id":str(self.site.pk),"assignee_id":str(self.other.pk)}).status_code,403)

    def test_admin_transfer_filter_uses_id_not_duplicate_name_and_candidates_keep_scope(self):
        self.other.name=self.employee.name;self.other.save();a,b=self.customers(2);self.assign(a);self.assign(b,self.other)
        data=self.client.get("/api/customers",{"site_id":str(self.site.pk),"assignee_id":str(self.employee.pk)}).json()
        self.assertEqual(data["total"],1);self.assertEqual(data["data"][0]["assignee_id"],str(self.employee.pk))
        candidates=self.client.get("/api/customers/filter-options",{"site_id":str(self.site.pk),"assignee_id":str(self.employee.pk),"field":"customer_name"}).json()
        self.assertEqual(candidates["values"],[a.customer_name])

    def test_expired_p4_receipts_rejected_then_cleaned_without_customer_changes(self):
        self.customers(4);body=self.body();distribute(self.admin,body)
        IdempotencyRecord.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(AccessError) as expired:distribute(self.admin,body)
        self.assertEqual(expired.exception.code,"IDEMPOTENCY_EXPIRED")
        self.assertEqual(cleanup_p4_receipts(),1);self.assertEqual(Assignment.objects.count(),2)

    def test_new_write_endpoints_require_csrf_and_legacy_reset_form_still_works(self):
        strict=Client(enforce_csrf_checks=True);strict.get("/auth/login")
        strict.post("/auth/login",{"phone":self.admin.phone_normalized,"password":STRONG_PASSWORD},HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value)
        for path,body in [("/api/assignments/distribute",self.body()),("/api/users/batch-update",self.user_body(self.edit(self.employee)))]:
            self.assertEqual(strict.post(path,body,content_type="application/json").status_code,403)
        self.assertEqual(strict.post(f"/api/users/{self.employee.pk}/reset-password",{"csrfmiddlewaretoken":strict.cookies["csrftoken"].value}).status_code,200)
        self.assertEqual(self.post(f"/api/users/{self.employee.pk}/reset-password",{"idempotency_key":None}).status_code,422)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P4ConcurrencyTests(Fixtures,TransactionTestCase):
    def setUp(self):self.prepare()
    def concurrent(self,fn):
        barrier=Barrier(2)
        def run(i):
            close_old_connections()
            try:
                actor=User.objects.get(pk=self.admin.pk);barrier.wait(timeout=10);return fn(actor,i)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,range(2)))

    def test_two_admin_distributions_have_no_overlap(self):
        self.customers(12);bodies=[self.body(quantity=3),self.body(quantity=3)]
        results=self.concurrent(lambda actor,i:distribute(actor,bodies[i]))
        self.assertEqual([r[1] for r in results],[200,200]);self.assertEqual(Assignment.objects.filter(ended_at=None).count(),12)
        self.assertEqual(Customer.objects.exclude(current_assignment=None).count(),12)

    def test_same_key_distribute_once(self):
        self.customers(10);body=self.body(quantity=3)
        results=self.concurrent(lambda actor,i:distribute(actor,body))
        self.assertEqual(results[0],results[1]);self.assertEqual(Assignment.objects.count(),6)
        self.assertEqual(OperationEvent.objects.filter(operation="DISTRIBUTE").count(),1)

    def test_deactivation_racing_distribution_leaves_no_new_active_assignment_to_disabled_user(self):
        self.customers(10);body=self.body(quantity=3,employee_id=str(self.employee.pk))
        results=self.concurrent(lambda actor,i:distribute(actor,body) if i==0 else set_user_access(actor,self.employee.pk,is_active=False))
        self.employee.refresh_from_db();self.assertFalse(self.employee.is_active)
        self.assertFalse(Customer.objects.filter(current_assignment__employee=self.employee).exists())
        self.assertFalse(Assignment.objects.filter(employee=self.employee,ended_at__isnull=True).exists())

    def test_two_last_admin_deactivations_keep_one_admin(self):
        set_user_access(self.admin,self.other.pk,role="ADMIN")
        def operation(actor,i):
            target=self.admin.pk if i==0 else self.other.pk
            try:return set_user_access(User.objects.get(pk=target),target,is_active=False).is_active
            except AccessError as error:return error.code
        results=self.concurrent(operation)
        self.assertIn("LAST_ACTIVE_ADMIN",results)
        self.assertEqual(User.objects.filter(role="ADMIN",is_active=True).count(),1)

    def test_save_versus_reassign_never_saves_into_new_assignment(self):
        customer=self.customers()[0];old=self.assign(customer);mutation=self.mutation(customer);change=self.assignee_body(customer,self.other)
        def operation(actor,i):
            try:return update_row(self.employee,mutation) if i==0 else change_assignee(actor,customer.pk,change)
            except AccessError as error:return error.code
        results=self.concurrent(operation);customer.refresh_from_db()
        for revision in ConsultationRevision.objects.all():self.assertEqual(revision.assignment_id,old.pk)
        if customer.current_assignment_id!=old.pk:self.assertIsNone(customer.current_assignment.first_activity_at)

    def test_recall_same_key_once_and_failed_create_unique(self):
        customers=self.customers(4)
        for customer in customers:self.assign(customer)
        body=self.recall_body();results=self.concurrent(lambda actor,i:recall(actor,body))
        self.assertEqual(results[0],results[1]);self.assertEqual(OperationEvent.objects.filter(operation="MANUAL_RECALL").count(),1)

    @override_settings(BUSINESS_LOCK_TIMEOUT_MS=30)
    def test_compatibility_user_service_retries_actual_lock_only_once(self):
        attempts=[]
        def run():
            close_old_connections()
            def observe(execute,sql,params,many,context):
                if "pg_advisory_xact_lock" in sql:attempts.append(sql)
                return execute(sql,params,many,context)
            try:
                actor=User.objects.get(pk=self.admin.pk)
                with connection.execute_wrapper(observe):
                    try:set_user_access(actor,self.employee.pk,is_active=False)
                    except OperationalError:return "unavailable"
            finally:close_old_connections()
        with connection.cursor() as cursor:cursor.execute("SELECT pg_advisory_lock(%s)",[BUSINESS_LOCK_KEY])
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:self.assertEqual(pool.submit(run).result(),"unavailable")
        finally:
            with connection.cursor() as cursor:cursor.execute("SELECT pg_advisory_unlock(%s)",[BUSINESS_LOCK_KEY])
        self.assertEqual(len(attempts),2);self.employee.refresh_from_db();self.assertTrue(self.employee.is_active)
