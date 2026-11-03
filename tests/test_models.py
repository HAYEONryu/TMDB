from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.access import AccessError
from apps.accounts.services import set_user_access
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.transactions import BUSINESS_LOCK_KEY, business_write
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.operations.models import IdempotencyRecord, MutationReceipt, ScheduledJobRun
from apps.sites.models import GlobalSettings, Site
from tests.helpers import TEST_HASHERS, user


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DatabaseConstraintTests(TestCase):
    def setUp(self):
        self.admin = user(role=User.Role.ADMIN, initial=False)
        self.employee = user("01000000002")
        self.site = Site.objects.create(name="가상 A 현장", created_by=self.admin)
        self.customer = Customer.objects.create(site=self.site, customer_name="가상고객", phone_normalized="01000000003")
        self.assignment = Assignment.objects.create(customer=self.customer, employee=self.employee, assigned_by=self.admin, assigned_at=timezone.now())

    def assert_database_rejects(self, action):
        with self.assertRaises(IntegrityError), transaction.atomic():
            action()

    def test_database_is_postgresql_17(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.pg_version // 10000, 17)

    def test_site_normalized_unique_and_nonempty(self):
        self.assert_database_rejects(lambda: Site.objects.create(name="가상a현장", created_by=self.admin))
        self.assert_database_rejects(lambda: Site.objects.create(name="  ", created_by=self.admin))

    def test_phone_unique_including_trash_but_not_across_sites(self):
        self.customer.deleted_at = timezone.now()
        self.customer.save()
        self.assert_database_rejects(lambda: Customer.objects.create(site=self.site, customer_name="다른가상고객", phone_normalized=self.customer.phone_normalized))
        other_site = Site.objects.create(name="가상B현장", created_by=self.admin)
        Customer.objects.create(site=other_site, customer_name="가상고객", phone_normalized=self.customer.phone_normalized)

    def test_invalid_phone_enum_and_version_rejected_in_database(self):
        for values in [{"phone_normalized": "1012345678"}, {"call_result": "INVALID"}, {"contract_status": "INVALID"}, {"version": 0}]:
            self.assert_database_rejects(lambda values=values: Customer.objects.filter(pk=self.customer.pk).update(**values))
        self.assert_database_rejects(lambda: User.objects.filter(pk=self.employee.pk).update(role="INVALID"))

    def test_only_one_current_assignment_and_ended_assignment_allows_next(self):
        self.assert_database_rejects(lambda: Assignment.objects.create(customer=self.customer, employee=self.employee, assigned_by=self.admin, assigned_at=timezone.now()))
        self.assignment.ended_at = timezone.now()
        self.assignment.end_reason = Assignment.EndReason.MANUAL_RECALL
        self.assignment.save()
        Assignment.objects.create(customer=self.customer, employee=self.employee, assigned_by=self.admin, assigned_at=timezone.now())

    def test_assignment_end_requires_reason(self):
        self.assert_database_rejects(lambda: Assignment.objects.filter(pk=self.assignment.pk).update(ended_at=timezone.now()))

    def test_current_assignment_customer_and_open_state_validation(self):
        other = Customer.objects.create(site=self.site, customer_name="가상다른고객", phone_normalized="01000000004")
        other.current_assignment = self.assignment
        with self.assertRaises(ValidationError):
            other.full_clean()
        self.assignment.ended_at = timezone.now()
        self.assignment.end_reason = Assignment.EndReason.MANUAL_RECALL
        self.assignment.save()
        self.customer.current_assignment = self.assignment
        with self.assertRaises(ValidationError):
            self.customer.full_clean()

    def test_deleted_customer_cannot_have_current_assignment(self):
        self.assert_database_rejects(lambda: Customer.objects.filter(pk=self.customer.pk).update(deleted_at=timezone.now(), current_assignment=self.assignment))

    def test_callback_pending_unique_and_state_constraints(self):
        callback = Callback.objects.create(customer=self.customer, due_at=timezone.now(), created_by=self.admin, updated_by=self.admin)
        self.assert_database_rejects(lambda: Callback.objects.create(customer=self.customer, due_at=timezone.now(), created_by=self.admin, updated_by=self.admin))
        self.assert_database_rejects(lambda: Callback.objects.filter(pk=callback.pk).update(status="COMPLETED"))
        Callback.objects.filter(pk=callback.pk).update(status="COMPLETED", completed_at=timezone.now(), completed_by=self.admin)
        Callback.objects.create(customer=self.customer, due_at=timezone.now(), created_by=self.admin, updated_by=self.admin)

    def request(self):
        return CustomerDeletionRequest.objects.create(customer=self.customer, requested_assignment=self.assignment, requested_by=self.employee, requested_at=timezone.now())

    def test_deletion_request_pending_unique_and_states(self):
        request = self.request()
        self.assert_database_rejects(self.request)
        self.assert_database_rejects(lambda: CustomerDeletionRequest.objects.filter(pk=request.pk).update(status="APPROVED"))
        CustomerDeletionRequest.objects.filter(pk=request.pk).update(status="APPROVED", approved_by=self.admin, approved_at=timezone.now(), deletion_note="[2026-11-03 12:00] 고객요청으로 인한 삭제")
        self.request()

    def test_deletion_request_customer_matches_historical_assignment(self):
        other = Customer.objects.create(site=self.site, customer_name="가상다른고객", phone_normalized="01000000004")
        request = CustomerDeletionRequest(customer=other, requested_assignment=self.assignment, requested_by=self.employee, requested_at=timezone.now())
        with self.assertRaises(ValidationError):
            request.full_clean()

    def test_notes_can_hold_system_append_without_truncation(self):
        content = "가" * 10000 + "\n[2026-11-03 12:00] 고객요청으로 인한 삭제"
        Customer.objects.filter(pk=self.customer.pk).update(notes=content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.notes, content)

    def test_singleton_and_job_idempotency_constraints(self):
        GlobalSettings.objects.get_or_create(pk=1)
        self.assert_database_rejects(lambda: GlobalSettings.objects.create(pk=2))
        job = {"job_type": "AUTO_RECALL", "business_date": timezone.localdate(), "cutoff": timezone.now()}
        ScheduledJobRun.objects.create(**job)
        self.assert_database_rejects(lambda: ScheduledJobRun.objects.create(**job))

    def test_receipt_keys_are_scoped_and_unique(self):
        values = {"actor": self.admin, "operation": "DISTRIBUTE", "key": uuid.uuid4(), "body_hash": "a" * 64, "expires_at": timezone.now() + timedelta(days=7)}
        IdempotencyRecord.objects.create(**values)
        self.assert_database_rejects(lambda: IdempotencyRecord.objects.create(**values))
        receipt = {"actor": self.employee, "customer": self.customer, "mutation_id": uuid.uuid4(), "body_hash": "b" * 64, "expires_at": timezone.now() + timedelta(days=7)}
        MutationReceipt.objects.create(**receipt)
        self.assert_database_rejects(lambda: MutationReceipt.objects.create(**receipt))

    def test_cascade_customer_removes_assignment_and_deletion_request(self):
        self.request()
        self.customer.current_assignment = self.assignment
        self.customer.save()
        cid = self.customer.pk
        self.customer.delete()
        self.assertFalse(Assignment.objects.filter(customer_id=cid).exists())
        self.assertFalse(CustomerDeletionRequest.objects.filter(customer_id=cid).exists())

    def test_deactivation_recalls_unprogressed_all_dates_and_preserves_progress(self):
        Customer.objects.filter(pk=self.customer.pk).update(current_assignment=self.assignment, notes="가상 상담 기록")
        old = timezone.now() - timedelta(days=3)
        Assignment.objects.filter(pk=self.assignment.pk).update(assigned_at=old)
        progressed = Customer.objects.create(site=self.site, customer_name="진행가상고객", phone_normalized="01000000004")
        assignment = Assignment.objects.create(customer=progressed, employee=self.employee, assigned_by=self.admin, assigned_at=old, first_activity_at=old + timedelta(hours=1))
        progressed.current_assignment = assignment
        progressed.save()
        set_user_access(self.admin, self.employee.pk, is_active=False)
        self.customer.refresh_from_db()
        self.assignment.refresh_from_db()
        progressed.refresh_from_db()
        self.assertIsNone(self.customer.current_assignment_id)
        self.assertEqual(self.customer.notes, "가상 상담 기록")
        self.assertEqual(self.assignment.end_reason, "USER_DISABLED")
        self.assertEqual(progressed.current_assignment_id, assignment.pk)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def test_concurrent_self_deactivation_keeps_one_active_admin(self):
        accounts = [user(role=User.Role.ADMIN, initial=False), user("01000000002", role=User.Role.ADMIN, initial=False)]
        barrier = Barrier(2)

        def deactivate(account):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                set_user_access(account, account.pk, is_active=False)
                return "changed"
            except AccessError as exc:
                return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(deactivate, accounts))
        self.assertCountEqual(results, ["changed", "LAST_ACTIVE_ADMIN"])
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN, is_active=True).count(), 1)

    @override_settings(BUSINESS_LOCK_TIMEOUT_MS=50)
    def test_busy_write_returns_retryable_503_then_can_login(self):
        account = user()
        acquired, release = Event(), Event()

        def hold_lock():
            close_old_connections()
            try:
                with business_write():
                    acquired.set()
                    release.wait(timeout=10)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(hold_lock)
            self.assertTrue(acquired.wait(timeout=10))
            try:
                response = self.client.post("/auth/login", {"phone": account.phone_normalized, "password": "dodream"}, content_type="application/json")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "TEMPORARY_UNAVAILABLE")
            finally:
                release.set()
                future.result(timeout=10)
        self.assertEqual(self.client.post("/auth/login", {"phone": account.phone_normalized, "password": "dodream"}, content_type="application/json").status_code, 200)

    def test_concurrent_site_insert_only_one_succeeds(self):
        admin = user(role=User.Role.ADMIN)
        barrier = Barrier(2)

        def insert(name):
            close_old_connections()
            try:
                with transaction.atomic():
                    barrier.wait(timeout=10)
                    Site.objects.create(name=name, created_by_id=admin.pk)
                return "created"
            except IntegrityError:
                return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(insert, ["가상 A현장", "가상a 현장"]))
        self.assertCountEqual(results, ["created", "duplicate"])
        self.assertEqual(Site.objects.count(), 1)

    def test_global_transaction_lock_blocks_other_connection(self):
        def try_lock():
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [BUSINESS_LOCK_KEY])
                    return cursor.fetchone()[0]
            finally:
                close_old_connections()

        with business_write():
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertFalse(pool.submit(try_lock).result(timeout=10))
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertTrue(pool.submit(try_lock).result(timeout=10))
