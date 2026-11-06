"""Real-provider queue policy with synthetic responses; never sends paid calls."""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase, override_settings
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.ai_assistant.adapters import FoundationFakeAdapter
from apps.ai_assistant.models import AIRequest, AIBudgetMonth, AIQuotaBucket
from apps.ai_assistant.openai_adapter import OpenAIAdapter
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import run_once, reap
from apps.customers.models import Customer
from apps.customers.queries import KST
from tests.helpers import TEST_HASHERS, user
from tests.test_p4 import Fixtures
from tests.test_openai_adapter import CONFIG, payload_for, wire


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_CONFIG=CONFIG, AI_FOUNDATION_TEST_MODE=False)
class AIOperatingLimitTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.assign(self.customer)
        self.customer.notes = "가짜 상담 관심"
        self.customer.save()
        guard = patch("http.client.HTTPSConnection", side_effect=AssertionError("NO_NETWORK"))
        guard.start()
        self.addCleanup(guard.stop)

    def body(self, feature="SUMMARY", customer=None):
        customer = customer or self.customer
        customer.refresh_from_db()
        return {"feature":feature, "customer_id":str(customer.pk),
                "assignment_id":str(customer.current_assignment_id), "expected_version":customer.version,
                "idempotency_key":str(uuid4())}

    def success(self, task):
        return run_once(OpenAIAdapter(transport=lambda *args: (200, wire(payload_for(task)), "req_operating_mock")))

    def test_real_model_three_features_share_thirty_and_duplicate_reserves_once(self):
        for feature in ["CLEANUP", "SUMMARY", "NEXT_QUESTIONS"]:
            body = self.body(feature)
            task, created = reserve(self.employee, body)
            self.assertTrue(created)
            same, created = reserve(self.employee, body)
            self.assertFalse(created)
            self.assertEqual(task.pk, same.pk)
            self.assertEqual(AIQuotaBucket.objects.get().reserved_count, 1)
            self.assertEqual(AIBudgetMonth.objects.get().reserved_usd, Decimal(".0024"))
            self.assertEqual(self.success(task)["succeeded"], 1)
            cached, created = reserve(self.employee, self.body(feature))
            self.assertFalse(created)
            self.assertEqual(cached.pk, task.pk)
        self.assertEqual(AIRequest.objects.count(), 3)
        bucket = AIQuotaBucket.objects.get()
        self.assertEqual(bucket.successful_count, 3)
        bucket.successful_count = 29
        bucket.save()
        Customer.objects.filter(pk=self.customer.pk).update(version=2)
        task, _ = reserve(self.employee, self.body("CLEANUP"))
        self.assertEqual(self.success(task)["succeeded"], 1)
        for feature in ["SUMMARY", "NEXT_QUESTIONS"]:
            with self.assertRaises(AccessError) as error:
                reserve(self.employee, self.body(feature))
            self.assertEqual(error.exception.code, "AI_DAILY_LIMIT")
        bucket.refresh_from_db()
        self.assertEqual((bucket.successful_count, bucket.reserved_count), (30, 0))

    def test_usd5_global_budget_counts_pending_reservations_and_releases_rejection(self):
        self.assertEqual(CONFIG.monthly_budget_usd, Decimal("5"))
        today = datetime.now(KST).date()
        month = AIBudgetMonth.objects.create(month=today.replace(day=1), charged_usd=Decimal("4.9976"))
        task, _ = reserve(self.employee, self.body())
        second = self.customers(offset=20)[0]
        self.assign(second, self.other)
        with self.assertRaises(AccessError) as error:
            reserve(self.other, self.body(customer=second))
        self.assertEqual(error.exception.code, "AI_BUDGET_LIMIT")
        month.refresh_from_db()
        self.assertEqual(month.charged_usd + month.reserved_usd, Decimal("5"))
        run_once(OpenAIAdapter(transport=lambda *args: (400, {}, "")))
        month.refresh_from_db()
        self.assertEqual(month.reserved_usd, 0)
        self.assertEqual(month.charged_usd, Decimal("4.9976"))
        other_task, _ = reserve(self.other, self.body(customer=second))
        self.assertNotEqual(task.pk, other_task.pk)
        self.assertEqual(AIRequest.objects.count(), 2)

    def test_manager_shared_weekly_and_per_employee_per_site_daily_periods(self):
        sunday = datetime(2026, 11, 8, 15, tzinfo=KST)
        second_admin = user("01000000004", role=User.Role.ADMIN, initial=False)
        def body(feature):
            extra = {"employee_id":str(self.employee.pk)} if feature == "EMPLOYEE_COACHING" else {"site_id":str(self.site.pk)} if feature == "TEAM_GUIDE" else {}
            return {"feature":feature, "idempotency_key":str(uuid4()), **extra}
        with patch("django.utils.timezone.now", return_value=sunday):
            for feature in ["WEEKLY_BRIEFING", "EMPLOYEE_COACHING", "TEAM_GUIDE"]:
                task, created = reserve(self.admin, body(feature))
                shared, created = reserve(second_admin, body(feature))
                self.assertFalse(created)
                self.assertEqual(shared.pk, task.pk)
                self.assertEqual(task.reserved_cost, Decimal(".005"))
                self.assertEqual(self.success(task)["succeeded"], 1)
                repeated, created = reserve(second_admin, body(feature))
                self.assertFalse(created)
                self.assertEqual(repeated.pk, task.pk)
        self.assertEqual(AIRequest.objects.count(), 3)
        with patch("django.utils.timezone.now", return_value=sunday + timedelta(days=1)):
            with self.assertRaises(AccessError) as error:
                reserve(self.admin, body("WEEKLY_BRIEFING"))
            self.assertEqual(error.exception.code, "AI_SUNDAY_ONLY")
            for feature in ["EMPLOYEE_COACHING", "TEAM_GUIDE"]:
                task, created = reserve(self.admin, body(feature))
                self.assertTrue(created)
                self.assertEqual(self.success(task)["succeeded"], 1)
        with patch("django.utils.timezone.now", return_value=sunday + timedelta(days=7)):
            task, created = reserve(self.admin, body("WEEKLY_BRIEFING"))
            self.assertTrue(created)
            self.assertEqual(self.success(task)["succeeded"], 1)
        self.assertEqual(AIRequest.objects.count(), 6)

    @override_settings(TESTING=False)
    def test_production_failures_cannot_be_replaced_by_fake_success(self):
        for failure in [400, 503, TimeoutError()]:
            task, _ = reserve(self.employee, self.body())
            def transport(*args):
                if isinstance(failure, Exception): raise failure
                return failure, {}, ""
            with patch.object(FoundationFakeAdapter, "execute_task", side_effect=AssertionError("FAKE_FALLBACK_FORBIDDEN")) as fake:
                adapter = OpenAIAdapter(transport=transport)
                with patch("apps.ai_assistant.openai_adapter.OpenAIAdapter", return_value=adapter):
                    self.assertEqual(run_once()["succeeded"], 0)
                fake.assert_not_called()
            task.refresh_from_db()
            self.assertIn(task.status, ["FAILED", "UNKNOWN"])
            self.assertFalse(task.result.valid)
            self.assertEqual(task.attempt_count, 1)
            self.assertEqual(run_once()["processed"], 0)
            if task.status == "UNKNOWN": reap(now=task.unknown_until)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count, 0)

    @override_settings(TESTING=False, AI_FOUNDATION_TEST_MODE=True)
    def test_production_cannot_force_fake_adapter_even_with_test_flag(self):
        task, _ = reserve(self.employee, self.body())
        with self.assertRaises(RuntimeError):
            FoundationFakeAdapter().execute_task(task, task.input_payload)

