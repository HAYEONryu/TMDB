import io
import os
from pathlib import Path
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings

from apps.accounts.access import AccessError
from apps.accounts.bootstrap import ensure_initial_admin
from apps.accounts.management_services import create_user, update_users
from apps.accounts.models import User
from apps.accounts.services import reset_password
from apps.operations.models import OperationEvent
from tests.helpers import STRONG_PASSWORD, TEST_HASHERS, password_data, user


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class BootstrapAdminTests(TestCase):
    def test_empty_database_login_and_mandatory_password_change(self):
        self.assertTrue(ensure_initial_admin())
        account = User.objects.get(phone_normalized="admin")
        self.assertEqual(account.role, User.Role.ADMIN)
        self.assertTrue(account.check_password("admin123"))
        self.assertTrue(account.must_change_password)
        self.assertFalse(account.is_superuser or account.is_staff)
        self.assertNotEqual(account.password, "admin123")
        client = Client()
        form = client.get("/auth/login")
        self.assertContains(form, "아이디 또는 전화번호")
        self.assertContains(form, 'autocomplete="username"')
        response = client.post("/auth/login", {"phone": "admin", "password": "admin123"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], "/auth/password")
        self.assertEqual(client.get("/api/access/admin").status_code, 403)
        response = client.post("/auth/password", password_data(current="admin123"), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/access/admin").status_code, 200)
        self.assertFalse(ensure_initial_admin())
        account.refresh_from_db()
        self.assertTrue(account.check_password(STRONG_PASSWORD))
        self.assertFalse(account.check_password("admin123"))
        self.assertFalse(account.must_change_password)
        self.assertEqual(OperationEvent.objects.filter(operation="INITIAL_ADMIN_CREATED").count(), 1)

    def test_existing_accounts_are_never_given_a_default_login(self):
        user(initial=False)
        self.assertFalse(ensure_initial_admin())
        self.assertFalse(User.objects.filter(phone_normalized="admin").exists())

    def test_disabled_bootstrap_account_is_not_reactivated(self):
        ensure_initial_admin()
        User.objects.filter(phone_normalized="admin").update(is_active=False)
        self.assertFalse(ensure_initial_admin())
        self.assertFalse(User.objects.get(phone_normalized="admin").is_active)

    def test_both_management_commands_preserve_existing_passwords(self):
        call_command("create_initial_admin", stdout=io.StringIO())
        account = User.objects.get(phone_normalized="admin")
        account.set_password(STRONG_PASSWORD)
        account.save()
        call_command("ensure_initial_admin", stdout=io.StringIO())
        call_command("create_initial_admin", stdout=io.StringIO())
        account.refresh_from_db()
        self.assertTrue(account.check_password(STRONG_PASSWORD))
        self.assertEqual(User.objects.count(), 1)

    def test_reserved_login_and_employee_phone_constraints(self):
        ensure_initial_admin()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(phone_normalized="admin").update(role=User.Role.EMPLOYEE)
        for identifier in ["admin2", "010123", "admin"]:
            with self.assertRaises(ValidationError):
                User.objects.create_user(identifier, "가상직원", STRONG_PASSWORD, role=User.Role.EMPLOYEE)
        account = user("01000000002", initial=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=account.pk).update(phone_normalized="not-a-phone")

    def test_reserved_identifier_cannot_be_renamed_demoted_or_claimed(self):
        ensure_initial_admin()
        account = User.objects.get(phone_normalized="admin")
        account.must_change_password = False
        account.save()
        other = user("01000000002", initial=False, role=User.Role.ADMIN)
        body = {"id": str(account.pk), "name": account.name, "phone": "admin", "role": "ADMIN",
                "is_active": True, "expected_version": account.updated_at.isoformat()}
        for changes in [{"phone": "01000000003"}, {"role": "EMPLOYEE"}]:
            with self.assertRaises(AccessError) as raised:
                update_users(other, {"rows": [{**body, **changes}], "idempotency_key": str(uuid4())})
            self.assertEqual(raised.exception.code, "BOOTSTRAP_ADMIN_PROTECTED")
        with self.assertRaises(AccessError):
            create_user(other, {"name": "가상", "phone": "admin", "role": "ADMIN", "idempotency_key": str(uuid4())})
        result, status = update_users(other, {"rows": [{**body, "name": "변경관리자"}], "idempotency_key": str(uuid4())})
        self.assertEqual(status, 200)
        self.assertEqual(result["updated_count"], 1)

    def test_reset_uses_bootstrap_password_and_invalidates_sessions(self):
        ensure_initial_admin()
        account = User.objects.get(phone_normalized="admin")
        account.set_password(STRONG_PASSWORD)
        account.must_change_password = False
        account.save()
        client = Client()
        self.assertEqual(client.post("/auth/login", {"phone": "admin", "password": STRONG_PASSWORD}, content_type="application/json").status_code, 200)
        other = user("01000000002", initial=False, role=User.Role.ADMIN)
        reset_password(other, account.pk)
        account.refresh_from_db()
        self.assertTrue(account.check_password("admin123"))
        self.assertTrue(account.must_change_password)
        self.assertEqual(client.get("/api/me").status_code, 401)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ConcurrentBootstrapTests(TransactionTestCase):
    def test_parallel_startup_creates_exactly_one_account(self):
        def bootstrap(_):
            close_old_connections()
            try:
                return ensure_initial_admin()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=5) as executor:
            created = list(executor.map(bootstrap, range(5)))
        self.assertEqual(sum(created), 1)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.filter(operation="INITIAL_ADMIN_CREATED").count(), 1)


class BootstrapMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_accounts_without_a_default_password_login(self):
        before = [("accounts", "0001_initial")]
        after = [("accounts", "0002_bootstrap_admin_identifier")]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            old_user = executor.loader.project_state(before).apps.get_model("accounts", "User")
            row = old_user.objects.create(phone_normalized="01000000099", name="가상기존관리자",
                                          role="ADMIN", password="!unusable", must_change_password=False,
                                          session_version=7)
            MigrationExecutor(connection).migrate(after)
            account = User.objects.get(pk=row.pk)
            self.assertEqual(account.password, "!unusable")
            self.assertEqual(account.session_version, 7)
            self.assertFalse(account.must_change_password)
            self.assertFalse(ensure_initial_admin())
            self.assertFalse(User.objects.filter(phone_normalized="admin").exists())
        finally:
            MigrationExecutor(connection).migrate(after)


class ContainerEntrypointTests(SimpleTestCase):
    def test_only_web_bootstraps_and_bootstrap_failure_prevents_startup(self):
        script = Path(__file__).resolve().parents[1] / "deploy/entrypoint.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {
                "python": '#!/bin/sh\nprintf "python:%s\\n" "$*"\nexit "${BOOTSTRAP_EXIT:-0}"\n',
                "gunicorn": '#!/bin/sh\nprintf "web:%s\\n" "$*"\n',
            }.items():
                path = root / name
                path.write_text(content)
                path.chmod(0o700)
            env = {**os.environ, "PATH": directory}
            result = subprocess.run(["/bin/sh", str(script), "gunicorn", "config.wsgi:application"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.splitlines(), ["python:manage.py ensure_initial_admin", "web:config.wsgi:application"])
            worker = subprocess.run(["/bin/sh", str(script), "python", "manage.py", "run_ai_worker"], env=env, capture_output=True, text=True)
            self.assertEqual(worker.stdout.strip(), "python:manage.py run_ai_worker")
            failed = subprocess.run(["/bin/sh", str(script), "gunicorn"], env={**env, "BOOTSTRAP_EXIT": "7"}, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 7)
            self.assertNotIn("web:", failed.stdout)
