import io
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import LoginFailure, User
from apps.accounts.services import set_user_access
from apps.accounts.access import AccessError
from apps.operations.models import OperationEvent
from tests.helpers import TEST_HASHERS, STRONG_PASSWORD, login, password_data, user


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class AuthenticationTests(TestCase):
    def setUp(self):
        self.admin = user(role=User.Role.ADMIN, name="가상관리자")
        self.employee = user("01000000002", name="가상직원")

    def test_anonymous_business_access_requires_login(self):
        self.assertEqual(self.client.get("/api/access/admin").status_code, 401)
        self.assertRedirects(self.client.get("/app/employee"), "/auth/login", fetch_redirect_response=False)

    def test_admin_and_employee_login_initial_password_gate(self):
        for account, path in [(self.admin, "/api/access/admin"), (self.employee, "/api/access/employee")]:
            client = login(account)
            self.assertEqual(client.get(path).json()["error"]["code"], "PASSWORD_CHANGE_REQUIRED")
            self.assertEqual(client.get("/api/me").json()["must_change_password"], True)
            self.assertRedirects(client.get("/"), "/auth/password", fetch_redirect_response=False)
            self.assertNotIn("password", client.get("/api/me").json())

    def test_initial_password_gate_also_blocks_reset_endpoint(self):
        client = login(self.admin)
        response = client.post(f"/api/users/{self.employee.pk}/reset-password")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_phone_normalization_and_generic_bad_login(self):
        good = self.client.post("/auth/login", {"phone": "010-0000-0002", "password": "dodream"}, content_type="application/json")
        self.assertEqual(good.status_code, 200)
        self.client.post("/auth/logout")
        for phone in ["+82 10 0000 0002", "01000009999"]:
            response = self.client.post("/auth/login", {"phone": phone, "password": "wrong"}, content_type="application/json")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_initial_change_unlocks_correct_role_only(self):
        for account, allowed, denied in [(self.admin, "admin", "employee"), (self.employee, "employee", "admin")]:
            client = login(account)
            response = client.post("/auth/password", password_data(), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get(f"/api/access/{allowed}").status_code, 200)
            self.assertEqual(client.get(f"/api/access/{denied}").status_code, 403)
            account.refresh_from_db()
            self.assertFalse(account.must_change_password)
            self.assertEqual(account.session_version, 2)
            self.assertTrue(account.check_password(STRONG_PASSWORD))
            self.assertNotEqual(account.password, STRONG_PASSWORD)

    def test_password_validation_and_current_password_required(self):
        client = login(self.employee)
        cases = [password_data(current="wrong"), password_data(new="dodream"),
                 password_data(new="123456789"), password_data(new="a" * 129),
                 {**password_data(), "new_password_confirm": "not-matching"}]
        for data in cases:
            self.assertEqual(client.post("/auth/password", data, content_type="application/json").status_code, 422)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.must_change_password)
        self.assertEqual(self.employee.session_version, 1)

    def test_password_change_preserves_current_session_and_invalidates_other_browser(self):
        current, other = login(self.employee), login(self.employee)
        self.assertEqual(current.post("/auth/password", password_data(), content_type="application/json").status_code, 200)
        self.assertEqual(current.get("/api/me").status_code, 200)
        self.assertEqual(other.get("/api/me").status_code, 401)
        self.assertEqual(Client().post("/auth/login", {"phone": self.employee.phone_normalized, "password": "dodream"}, content_type="application/json").status_code, 401)
        self.employee.refresh_from_db()
        self.assertEqual(login(self.employee).get("/api/access/employee").status_code, 200)

    def test_reset_invalidates_all_sessions_and_requires_initial_change_again(self):
        self.admin.must_change_password = False
        self.admin.set_password(STRONG_PASSWORD)
        self.admin.save()
        admin_client = login(self.admin)
        a, b = login(self.employee), login(self.employee)
        a.post("/auth/password", password_data(), content_type="application/json")
        self.employee.refresh_from_db()
        b = login(self.employee)
        response = admin_client.post(f"/api/users/{self.employee.pk}/reset-password")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password", response.json())
        self.assertEqual(a.get("/api/me").status_code, 401)
        self.assertEqual(b.get("/api/me").status_code, 401)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password("dodream"))
        self.assertTrue(self.employee.must_change_password)
        new_client = login(self.employee)
        self.assertEqual(new_client.get("/api/access/employee").json()["error"]["code"], "PASSWORD_CHANGE_REQUIRED")
        self.assertEqual(new_client.post("/auth/password", password_data(new="Autumn!Cloud2026"), content_type="application/json").status_code, 200)
        self.assertEqual(new_client.get("/api/access/employee").status_code, 200)

    def test_employee_cannot_reset_any_password(self):
        client = login(self.employee)
        client.post("/auth/password", password_data(), content_type="application/json")
        self.assertEqual(client.post(f"/api/users/{self.admin.pk}/reset-password").status_code, 403)

    def test_admin_reset_unknown_id_is_404(self):
        client = login(self.admin)
        client.post("/auth/password", password_data(), content_type="application/json")
        self.assertEqual(client.post(f"/api/users/{uuid.uuid4()}/reset-password").status_code, 404)

    def test_deactivation_invalidates_session_and_reactivation_does_not_restore_it(self):
        self.admin.must_change_password = False
        self.admin.save()
        old = login(self.employee)
        unobserved = login(self.employee)
        set_user_access(self.admin, self.employee.pk, is_active=False)
        self.assertEqual(old.get("/api/access/employee").status_code, 401)
        set_user_access(self.admin, self.employee.pk, is_active=True)
        self.assertEqual(old.get("/api/me").status_code, 401)
        self.assertEqual(unobserved.get("/api/me").status_code, 401)

    def test_superuser_flag_cannot_bypass_business_role(self):
        client = login(self.employee)
        client.post("/auth/password", password_data(), content_type="application/json")
        User.objects.filter(pk=self.employee.pk).update(is_superuser=True, is_staff=True)
        self.assertEqual(client.get("/api/access/admin").status_code, 403)

    def test_self_reset_invalidates_current_session_too(self):
        client = login(self.admin)
        client.post("/auth/password", password_data(), content_type="application/json")
        self.assertEqual(client.post(f"/api/users/{self.admin.pk}/reset-password").status_code, 200)
        self.assertEqual(client.get("/api/me").status_code, 401)

    def test_role_change_invalidates_session(self):
        self.admin.must_change_password = False
        self.admin.save()
        old = login(self.employee)
        set_user_access(self.admin, self.employee.pk, role=User.Role.ADMIN)
        self.assertEqual(old.get("/api/me").status_code, 401)

    def test_last_admin_guard(self):
        self.admin.must_change_password = False
        self.admin.save()
        for change in [{"is_active": False}, {"role": User.Role.EMPLOYEE}]:
            with self.assertRaises(AccessError) as caught:
                set_user_access(self.admin, self.admin.pk, **change)
            self.assertEqual(caught.exception.code, "LAST_ACTIVE_ADMIN")

    def test_csrf_on_login_change_reset_logout(self):
        client = Client(enforce_csrf_checks=True)
        data = {"phone": self.admin.phone_normalized, "password": "dodream"}
        self.assertEqual(client.post("/auth/login", data).status_code, 403)
        client.get("/auth/login")
        response = client.post("/auth/login", data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.post("/auth/password", password_data()).status_code, 403)
        self.assertEqual(client.post("/auth/logout").status_code, 403)
        self.assertEqual(client.get("/auth/logout").status_code, 405)
        self.assertEqual(client.post("/auth/password", password_data(), HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value).status_code, 302)
        self.assertEqual(client.post(f"/api/users/{self.employee.pk}/reset-password").status_code, 403)

    @override_settings(LOGIN_ACCOUNT_FAILURE_LIMIT=2)
    def test_login_failures_persist_and_expire_without_raw_credentials(self):
        data = {"phone": self.employee.phone_normalized, "password": "secret-incorrect"}
        for _ in range(2):
            self.assertEqual(self.client.post("/auth/login", data, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post("/auth/login", data, content_type="application/json").status_code, 429)
        record = LoginFailure.objects.first()
        self.assertNotIn(self.employee.phone_normalized, str(record.__dict__))
        self.assertNotIn("secret-incorrect", str(record.__dict__))
        LoginFailure.objects.update(created_at=timezone.now() - timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS + 1))
        self.assertEqual(login(self.employee, self.client).get("/api/me").status_code, 200)

    @override_settings(LOGIN_REQUEST_FAILURE_LIMIT=2)
    def test_request_limit_applies_across_different_accounts(self):
        for phone in ["01000000099", "01000000098"]:
            self.client.post("/auth/login", {"phone": phone, "password": "wrong"}, content_type="application/json")
        self.assertEqual(self.client.post("/auth/login", {"phone": self.employee.phone_normalized, "password": "dodream"}, content_type="application/json").status_code, 429)

    def test_api_rejects_malformed_json_and_non_string_credentials(self):
        for body in ["[1]", "{", '{"phone":123,"password":true}']:
            self.assertEqual(self.client.post("/auth/login", body, content_type="application/json").status_code, 422)

    def test_no_password_or_customer_content_in_operation_event(self):
        client = login(self.employee)
        client.post("/auth/password", password_data(), content_type="application/json")
        event = OperationEvent.objects.get(operation="PASSWORD_CHANGED")
        self.assertNotIn(STRONG_PASSWORD, str(event.__dict__))
        self.assertNotIn("dodream", str(event.__dict__))

    def test_logout_flushes_session(self):
        client = login(self.employee)
        self.assertEqual(client.post("/auth/logout", {}, content_type="application/json").status_code, 200)
        self.assertEqual(client.get("/api/me").status_code, 401)


class RealPasswordHashTests(TestCase):
    def test_runtime_password_hasher_is_pbkdf2(self):
        account = user()
        self.assertEqual(identify_hasher(account.password).algorithm, "pbkdf2_sha256")
        self.assertFalse(account.is_superuser)
        self.assertFalse(account.is_staff)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ManagementCommandTests(TestCase):
    def test_initial_admin_and_existing_admin_guard(self):
        out = io.StringIO()
        call_command("create_initial_admin", phone="010-0000-0010", name="가상최초관리자", stdout=out)
        account = User.objects.get(phone_normalized="01000000010")
        self.assertEqual(account.role, User.Role.ADMIN)
        self.assertTrue(account.check_password("dodream"))
        self.assertTrue(account.must_change_password)
        self.assertFalse(account.is_superuser)
        with self.assertRaises(CommandError):
            call_command("create_initial_admin", phone="01000000011", name="가상추가관리자", stdout=out)

    @override_settings(ALLOW_DEMO_SEED=True)
    def test_seed_is_repeatable_and_preserves_changed_password(self):
        call_command("seed_demo", stdout=io.StringIO())
        account = User.objects.get(phone_normalized="01000000002")
        account.set_password(STRONG_PASSWORD)
        account.must_change_password = False
        account.save()
        call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(User.objects.count(), 3)
        account.refresh_from_db()
        self.assertFalse(account.must_change_password)
        self.assertTrue(account.check_password(STRONG_PASSWORD))

    @override_settings(ALLOW_DEMO_SEED=False)
    def test_seed_requires_explicit_environment_flag(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())
