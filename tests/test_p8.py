"""Basic-work integration under AI failures; all input is fictitious."""
import io
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command, CommandError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import set_user_access
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.customers.services import update_row
from apps.sites.models import Site, GlobalSettings, DefaultSiteHistory
from apps.customers.queries import KST
from config.ai import load_ai_config
from tests.helpers import login, TEST_HASHERS
from tests.test_imports import row, workbook, uploaded
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P8IntegrationTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()
        self.admin_client = login(self.admin)
        self.staff_client = login(self.employee)
        self.headers = {"HTTP_X_TM_QUEUE_USER": str(self.employee.pk)}

    def post(self, client, path, body, *, staff=False, status=200):
        response = client.post(path, body, content_type="application/json", **(self.headers if staff else {}))
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def config(self, values=None, mode=0o600):
        with tempfile.TemporaryDirectory(prefix="tm-p8-ai-", dir="/private/tmp") as directory:
            if values is not None:
                path = Path(directory) / ".env.ai"
                path.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
                path.chmod(mode)
            return load_ai_config(directory, role="web", environment={})

    def workflow(self, config):
        self.assertFalse(config.configured)
        with override_settings(AI_CONFIG=config), patch("socket.socket.connect", side_effect=AssertionError("External network forbidden")), patch("apps.ai_assistant.adapters.FakeAIAdapter.execute", side_effect=AssertionError("Fake must not serve core work")):
            for client in [self.admin_client, self.staff_client]:
                status = client.get("/api/ai/availability")
                self.assertEqual(status.status_code, 200)
                self.assertFalse(status.json()["generation_available"])
                self.assertEqual(client.get("/api/me").status_code, 200)
            self.assertEqual(self.staff_client.get("/api/imports/template").status_code, 403)
            response = self.admin_client.post("/api/imports/validate", {"site_id": str(self.site.pk), "file": uploaded(workbook([row(**{"6": "가짜 등록 상담"})]))})
            self.assertEqual(response.status_code, 201, response.content)
            batch_id = response.json()["id"]
            committed = self.post(self.admin_client, f"/api/imports/{batch_id}/commit", {"site_id": str(self.site.pk), "idempotency_key": str(uuid4())})
            self.assertEqual(committed["success_count"], 1)
            allocated = self.post(self.admin_client, "/api/assignments/distribute", self.body(employee_id=str(self.employee.pk)))
            self.assertEqual(allocated["allocated_count"], 1)
            customer = Customer.objects.get(site=self.site)
            listing = self.staff_client.get("/api/customers", {"site_id": str(self.site.pk), "view": "today"}, **self.headers)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["total"], 1)
            mutation = self.mutation(customer, "AI 없이 저장한 가상 상담")
            mutation["changes"]["callback_due_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
            saved = self.post(self.staff_client, "/api/employee/batch-update", {"rows": [mutation]}, staff=True)
            self.assertTrue(saved["results"][0]["ok"])
            customer.refresh_from_db()
            callback = Callback.objects.get(customer=customer, status="PENDING")
            self.post(self.staff_client, f"/api/customers/{customer.pk}/callback-complete", {"callback_id": str(callback.pk), "callback_version": callback.version, "assignment_id": str(customer.current_assignment_id), "expected_version": customer.version, "idempotency_key": str(uuid4())}, staff=True)
            customer.refresh_from_db()
            pending_save = self.mutation(customer, "승인 뒤 차단할 가상 대기값")
            requested = self.post(self.staff_client, f"/api/customers/{customer.pk}/deletion-request", {"assignment_id": str(customer.current_assignment_id), "expected_version": customer.version, "idempotency_key": str(uuid4())}, staff=True)
            self.assertEqual(self.admin_client.get("/api/deletion-requests").json()["total"], 1)
            self.post(self.admin_client, f"/api/deletion-requests/{requested['request_id']}/approve", {"idempotency_key": str(uuid4())})
            refused = self.post(self.staff_client, "/api/employee/batch-update", {"rows": [pending_save]}, staff=True)
            self.assertFalse(refused["results"][0]["ok"])
            customer.refresh_from_db()
            self.assertTrue(customer.notes.startswith("AI 없이 저장한 가상 상담\n"))
            self.assertEqual(customer.notes.count("고객요청으로 인한 삭제"), 1)
            self.post(self.admin_client, "/api/customers/restore", {"site_id": str(self.site.pk), "customer_ids": [str(customer.pk)], "idempotency_key": str(uuid4())})
            customer.refresh_from_db()
            self.assertIsNone(customer.current_assignment_id)
            self.assertIsNone(customer.deleted_at)
            self.assertEqual(Callback.objects.get(pk=callback.pk).status, "COMPLETED")
            self.post(self.admin_client, "/api/customers/soft-delete", {"site_id": str(self.site.pk), "customer_ids": [str(customer.pk)], "idempotency_key": str(uuid4())})
            customer.refresh_from_db()
            hard_body = {"confirm": True, "expected_version": customer.version, "idempotency_key": str(uuid4())}
            self.post(self.admin_client, f"/api/customers/{customer.pk}/hard-delete", hard_body)
            self.post(self.admin_client, f"/api/customers/{customer.pk}/hard-delete", hard_body)
            self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())
            self.assertFalse(ConsultationRevision.objects.filter(customer_id=customer.pk).exists())
            self.assertEqual(self.admin_client.get("/api/deletion-requests").json()["total"], 0)
            self.assertEqual(self.admin_client.get("/api/dashboard", {"site_id": str(self.second.pk)}).status_code, 200)
            set_user_access(self.admin, self.employee.pk, is_active=False)
            self.assertEqual(self.staff_client.get("/api/me").status_code, 401)
            self.assertEqual(self.admin_client.get("/healthz").status_code, 200)

    def test_core_workflow_without_ai_key(self):
        self.workflow(self.config())

    def test_core_workflow_with_invalid_ai_prices(self):
        config = self.config({"AI_ENABLED": "true", "AI_API_KEY": "TEST_ONLY_INVALID_PRICE", "AI_PROVIDER": "test-only", "AI_MODEL": "test-model", "AI_INPUT_USD_PER_MILLION": "NaN", "AI_OUTPUT_USD_PER_MILLION": "-1"})
        self.workflow(config)

    def test_core_workflow_with_insecure_ai_file(self):
        config = self.config({"AI_ENABLED": "true", "AI_API_KEY": "TEST_ONLY_INSECURE_FILE"}, mode=0o644)
        self.assertEqual(config.reason, "AI_CONFIG_PERMISSIONS")
        self.workflow(config)

    def test_core_workflow_with_fake_provider_rejected(self):
        config = self.config({"AI_ENABLED": "true", "AI_PROVIDER": "fake"})
        self.assertEqual(config.reason, "AI_TEST_PROVIDER_FORBIDDEN")
        self.workflow(config)

    def test_deleted_site_rejects_all_old_reads_queue_writes_and_upload_commit(self):
        customer = self.customers()[0]
        self.assign(customer)
        pending = self.mutation(customer)
        queue = {"key": "fake-p8-entry", "customer_id": str(customer.pk), "site_id": str(self.site.pk), "assignment_id": str(customer.current_assignment_id), "expected_version": customer.version}
        response = self.admin_client.post("/api/imports/validate", {"site_id": str(self.site.pk), "file": uploaded(workbook([row()]))})
        self.assertEqual(response.status_code, 201)
        batch_id = response.json()["id"]
        key = str(uuid4())
        proof = self.post(self.admin_client, f"/api/sites/{self.site.pk}/deletion-confirmation", {"confirm_name": self.site.name, "idempotency_key": key})
        self.post(self.admin_client, f"/api/sites/{self.site.pk}/hard-delete", {**proof, "idempotency_key": key})
        for client in [self.admin_client, self.staff_client]:
            response = client.get("/api/customers", {"view": "all" if client is self.admin_client else "mine", "site_id": str(self.site.pk)})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "SITE_DELETED")
        checked = self.post(self.staff_client, "/api/employee/queue-check", {"entries": [queue]}, staff=True)
        self.assertEqual(checked["results"], [{"key": "fake-p8-entry", "code": "SITE_DELETED"}])
        saved = self.post(self.staff_client, "/api/employee/batch-update", {"rows": [pending]}, staff=True)
        self.assertFalse(saved["results"][0]["ok"])
        rejected = self.post(self.admin_client, f"/api/imports/{batch_id}/commit", {"site_id": str(self.site.pk), "idempotency_key": str(uuid4())}, status=409)
        self.assertEqual(rejected["error"]["code"], "SITE_DELETED")
        self.assertFalse(Customer.objects.exists())

    @override_settings(SCHEDULER_START_DATE="")
    def test_saved_revert_and_admin_housing_edit_survive_recall_but_noop_does_not(self):
        from apps.operations.scheduler import run_jobs
        now = datetime.combine(timezone.localdate(), time(23, 5), KST)
        rows = self.customers(3)
        for customer in rows: self.assign(customer, at=now.replace(hour=10))
        DefaultSiteHistory.objects.update(changed_at=now.replace(hour=12))
        with patch("django.utils.timezone.now", return_value=now.replace(hour=22, minute=45)):
            for value in ["가상 상담 저장", ""]:
                update_row(self.employee, self.mutation(rows[0], value)); rows[0].refresh_from_db()
            changed = self.mutation(rows[1]); changed["changes"] = {"housing_status": "1주택"}
            update_row(self.admin, changed)
            unchanged = update_row(self.employee, self.mutation(rows[2], ""))
            self.assertFalse(unchanged["changed"])
        self.assertEqual(self.staff_client.get("/api/customers", {"view": "mine", "site_id": str(self.site.pk)}, **self.headers).status_code, 200)
        with patch("django.utils.timezone.now", return_value=now):
            self.assertEqual(run_jobs(now=now), {"completed": 1, "failed": 0})
        for customer in rows: customer.refresh_from_db()
        self.assertIsNotNone(rows[0].current_assignment_id)
        self.assertIsNotNone(rows[1].current_assignment_id)
        self.assertIsNone(rows[2].current_assignment_id)
        self.assertEqual(rows[0].notes, "")
        self.assertEqual(rows[1].housing_status, "1주택")
        self.assertTrue(all(customer.call_result is None for customer in rows))
        self.assertEqual(ConsultationRevision.objects.count(), 3)

    @override_settings(ALLOW_DEMO_SEED=True)
    def test_seed_repeat_preserves_live_edits_assignment_request_password_and_default(self):
        output = io.StringIO()
        call_command("seed_demo", stdout=output)
        call_command("seed_demo_customers", stdout=output)
        customer = Customer.objects.filter(phone_normalized="01090000001").get()
        self.assign(customer)
        update_row(self.employee, self.mutation(customer, "다시 seed해도 유지할 가상 상담"))
        customer.refresh_from_db()
        requested = self.post(self.staff_client, f"/api/customers/{customer.pk}/deletion-request", {"assignment_id": str(customer.current_assignment_id), "expected_version": customer.version, "idempotency_key": str(uuid4())}, staff=True)
        before = (self.employee.password, customer.version, customer.current_assignment_id, GlobalSettings.objects.get().default_site_id, ConsultationRevision.objects.count(), Site.objects.count())
        call_command("seed_demo", stdout=output)
        call_command("seed_demo_customers", stdout=output)
        customer.refresh_from_db(); self.employee.refresh_from_db()
        self.assertEqual(before, (self.employee.password, customer.version, customer.current_assignment_id, GlobalSettings.objects.get().default_site_id, ConsultationRevision.objects.count(), Site.objects.count()))
        self.assertEqual(Customer.objects.count(), 65)
        self.assertEqual(customer.notes, "다시 seed해도 유지할 가상 상담")
        self.assertEqual(CustomerDeletionRequest.objects.get(pk=requested["request_id"]).status, "PENDING")
        self.assertEqual(Assignment.objects.count(), 1)
        with override_settings(ALLOW_DEMO_SEED=False):
            for command in ["seed_demo", "seed_demo_customers"]:
                with self.assertRaises(CommandError): call_command(command, stdout=output)
