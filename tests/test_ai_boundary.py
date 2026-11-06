import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from apps.ai_assistant.adapters import FakeAIAdapter
from config.ai import AIConfig, load_ai_config
from config.process import load_app_environment, prepare_process
from config.security import RedactingFormatter
from tests.helpers import TEST_HASHERS, login, user


class AIConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="tm-ai-config-", dir="/private/tmp")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sentinel = "TEST_ONLY_SENTINEL_" + uuid.uuid4().hex
        self.complete = {"AI_ENABLED": "true", "AI_API_KEY": self.sentinel,
                         "AI_PROVIDER": "test-vendor", "AI_MODEL": "test-model",
                         "AI_INPUT_USD_PER_MILLION": "0.1", "AI_OUTPUT_USD_PER_MILLION": "0.3"}

    def write_file(self, values=None):
        path = self.root / ".env.ai"
        path.write_text("\n".join(f"{k}={v}" for k, v in (values or self.complete).items()))
        path.chmod(0o600)
        return path

    def test_missing_file_and_settings_do_not_break_configuration(self):
        config = load_ai_config(self.root, role="web", environment={})
        self.assertFalse(config.configured)
        self.assertEqual(config.reason, "AI_NOT_CONFIGURED")

    def test_file_loaded_only_in_web_and_worker(self):
        self.write_file()
        for role in ["web", "ai_worker"]:
            config = load_ai_config(self.root, role=role, environment={})
            self.assertTrue(config.configured)
            self.assertEqual(config.api_key, self.sentinel)
        for role in ["scheduler", "management", "test"]:
            with patch("config.ai.dotenv_values") as reader:
                config = load_ai_config(self.root, role=role, environment=self.complete)
                reader.assert_not_called()
                self.assertEqual(config.api_key, "")
                self.assertFalse(config.configured)

    def test_environment_wins_and_explicit_empty_is_not_filled(self):
        self.write_file()
        config = load_ai_config(self.root, role="web", environment={"AI_MODEL": "process-model", "AI_API_KEY": ""})
        self.assertEqual(config.model, "process-model")
        self.assertEqual(config.api_key, "")
        self.assertFalse(config.configured)

    def test_external_file_path_supported(self):
        path = self.write_file()
        config = load_ai_config(self.root / "other", role="web", environment={"AI_ENV_FILE": str(path)})
        self.assertTrue(config.configured)

    def test_insecure_file_disables_ai_without_raising(self):
        self.write_file().chmod(0o644)
        config = load_ai_config(self.root, role="web", environment={})
        self.assertFalse(config.configured)
        self.assertEqual(config.reason, "AI_CONFIG_PERMISSIONS")

    def test_missing_invalid_and_negative_prices_disable_generation(self):
        for values in [{**self.complete, "AI_INPUT_USD_PER_MILLION": ""},
                       {**self.complete, "AI_OUTPUT_USD_PER_MILLION": "-1"},
                       {**self.complete, "AI_MONTHLY_BUDGET_USD": "Infinity"},
                       {**self.complete, "AI_MONTHLY_BUDGET_USD": "invalid"}]:
            config = load_ai_config(self.root, role="web", environment=values)
            self.assertFalse(config.configured)

    def test_fake_provider_rejected_by_normal_loader(self):
        config = load_ai_config(self.root, role="web", environment={**self.complete, "AI_PROVIDER": "fake"})
        self.assertEqual(config.reason, "AI_TEST_PROVIDER_FORBIDDEN")
        self.assertFalse(config.configured)

    def test_no_interpolation_of_other_environment_secrets(self):
        self.write_file({**self.complete, "AI_MODEL": "${PRIVATE_REFERENCE}"})
        with patch.dict(os.environ, {"PRIVATE_REFERENCE": self.sentinel}):
            config = load_ai_config(self.root, role="web", environment={})
        self.assertEqual(config.model, "${PRIVATE_REFERENCE}")

    def test_repr_and_logs_with_exception_do_not_expose_key(self):
        config = load_ai_config(self.root, role="web", environment=self.complete)
        self.assertNotIn(self.sentinel, repr(config))
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(message)s"))
        logger = logging.Logger("isolated-ai-boundary-test")
        logger.addHandler(handler)
        try:
            raise ValueError("test-only exception " + self.sentinel)
        except ValueError:
            logger.exception("test-only message %s", self.sentinel)
        self.assertNotIn(self.sentinel, stream.getvalue())
        self.assertIn("[REDACTED]", stream.getvalue())

    def test_loader_never_uses_network(self):
        self.write_file()
        with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            self.assertTrue(load_ai_config(self.root, role="web", environment={}).configured)

    def test_configured_application_and_django_log_handlers_redact(self):
        load_ai_config(self.root, role="web", environment=self.complete)
        for logger_name, owner in [("apps.ai_assistant", logging.getLogger()),
                                   ("django.ai_boundary", logging.getLogger("django"))]:
            stream = io.StringIO()
            console = owner.handlers[0]
            with patch.object(console, "stream", stream):
                logging.getLogger(logger_name).warning("test-only %s", self.sentinel)
            self.assertNotIn(self.sentinel, stream.getvalue())
            self.assertIn("[REDACTED]", stream.getvalue())

    def test_non_ai_process_drops_inherited_ai_environment(self):
        for role in ["management", "scheduler", "test"]:
            with patch.dict(os.environ, {"AI_API_KEY": self.sentinel, "AI_ENV_FILE": "ignored", "AI_ENABLED": "true"}):
                prepare_process(role)
                self.assertFalse(any(k.startswith("AI_") for k in os.environ))
                self.assertEqual(os.environ["TM_PROCESS_ROLE"], role)

    def test_web_role_preserves_runtime_environment(self):
        with patch.dict(os.environ, {"AI_API_KEY": self.sentinel}):
            prepare_process("web")
            self.assertEqual(os.environ["AI_API_KEY"], self.sentinel)

    def test_general_env_does_not_load_ai_values_into_management_process(self):
        # Uses the real management entrypoint; only prints booleans, never key values.
        env = {**os.environ, "AI_API_KEY": self.sentinel, "AI_ENABLED": "true"}
        result = subprocess.run([sys.executable, "manage.py", "shell", "-c",
                                 "import os; from django.conf import settings; print('AI_KEY_PRESENT', 'AI_API_KEY' in os.environ); print('CONFIG_HAS_KEY', bool(settings.AI_CONFIG.api_key))"],
                                cwd=settings.BASE_DIR, env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertIn("AI_KEY_PRESENT False", result.stdout)
        self.assertIn("CONFIG_HAS_KEY False", result.stdout)
        self.assertNotIn(self.sentinel, result.stdout + result.stderr)

    def test_general_env_cannot_supply_ai_secrets_or_override_process_role(self):
        path = self.root / ".env"
        path.write_text(f"AI_API_KEY={self.sentinel}\nAI_ENABLED=true\nTM_PROCESS_ROLE=web\nDJANGO_SECRET_KEY=fake-file-value\nDATABASE_URL=fake-database-value\n")
        environment = {"DJANGO_SECRET_KEY": "process-value"}
        load_app_environment(path, environment)
        self.assertNotIn("AI_API_KEY", environment)
        self.assertNotIn("AI_ENABLED", environment)
        self.assertNotIn("TM_PROCESS_ROLE", environment)
        self.assertEqual(environment["DJANGO_SECRET_KEY"], "process-value")
        self.assertEqual(environment["DATABASE_URL"], "fake-database-value")


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class AIApplicationBoundaryTests(TestCase):
    def setUp(self):
        self.account = user(initial=False)
        self.client = login(self.account)

    def test_availability_is_disabled_and_does_not_fabricate_usage(self):
        response = self.client.get("/api/ai/availability")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["generation_available"])
        self.assertEqual(data["daily_limit"], 30)
        self.assertEqual(data["successful_count"], 0)
        self.assertEqual(data["remaining_count"], 30)

    def test_unconfigured_ai_does_not_block_core_account_functions(self):
        with override_settings(AI_CONFIG=AIConfig()):
            self.assertEqual(self.client.get("/api/me").status_code, 200)
            self.assertEqual(self.client.get("/api/access/employee").status_code, 200)
            self.assertEqual(self.client.get("/healthz").status_code, 200)
            self.assertFalse(self.client.get("/api/ai/availability").json()["generation_available"])

    def test_key_not_in_api_html_or_static_source(self):
        sentinel = "TEST_ONLY_SENTINEL_" + uuid.uuid4().hex
        with override_settings(AI_CONFIG=AIConfig(enabled=True, configured=True, api_key=sentinel)):
            for path in ["/api/ai/availability", "/api/me", "/app/employee", "/auth/password"]:
                self.assertNotIn(sentinel, self.client.get(path).content.decode())
        for path in (settings.BASE_DIR / "static").rglob("*"):
            if path.is_file():
                self.assertNotIn(sentinel.encode(), path.read_bytes())

    def test_availability_requires_login_and_initial_change(self):
        self.client.post("/auth/logout")
        self.assertEqual(self.client.get("/api/ai/availability").status_code, 401)
        initial = user("01000000002")
        client = login(initial)
        self.assertEqual(client.get("/api/ai/availability").json()["error"]["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_fake_adapter_only_runs_in_test_database_without_network(self):
        with patch("socket.socket.connect", side_effect=AssertionError("No external calls")):
            for feature in ["CLEANUP", "SUMMARY", "NEXT_QUESTIONS"]:
                result = FakeAIAdapter().execute(feature)
                self.assertTrue(result["is_test"])
                self.assertEqual(result["provider_calls"], 0)

    @override_settings(TESTING=False)
    def test_fake_adapter_rejected_outside_test_settings(self):
        with self.assertRaises(RuntimeError):
            FakeAIAdapter().execute("SUMMARY")

    def test_fake_adapter_rejected_for_non_test_database(self):
        with patch.dict(connection.settings_dict, {"NAME": "tm_dev"}):
            with self.assertRaises(RuntimeError):
                FakeAIAdapter().execute("SUMMARY")

    def test_generation_api_requires_employee_queue_identity(self):
        self.assertEqual(self.client.post("/api/ai/customer-tasks", {}, content_type="application/json").status_code, 403)
