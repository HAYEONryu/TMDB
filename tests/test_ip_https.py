"""Synthetic IP HTTPS configuration and application checks; no ACME issuance."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings

from tests.helpers import STRONG_PASSWORD, TEST_HASHERS
from tests.test_p4 import Fixtures

IP = "165.140.21.197"


class IPHttpsConfigurationTests(SimpleTestCase):
    def test_wrapper_always_uses_https_overlay_and_unsets_shell_credential_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy(settings.BASE_DIR / "scripts/compose_https.sh", root / "scripts/compose_https.sh")
            (root / "compose.server.yaml").write_text("services: {}\n")
            stub = root / "docker"
            stub.write_text(f"#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'overrides_unset':not any(k in os.environ for k in ['TM_SERVER_SECRET','TM_DB_PASSWORD'])}}))\n")
            stub.chmod(0o700)
            result = subprocess.run(["/bin/bash", str(root / "scripts/compose_https.sh"), "ps"],
                cwd=tempfile.gettempdir(), env={"PATH": directory + ":/usr/bin:/bin", "HOME": directory,
                "TM_SERVER_SECRET": "synthetic-override", "TM_DB_PASSWORD": "synthetic-override"},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            value = json.loads(result.stdout)
            self.assertEqual(value["args"], ["compose", "-f", "compose.yaml", "-f", "compose.server.yaml",
                                            "-f", "compose.https.yaml", "--profile", "proxy", "ps"])
            self.assertEqual(Path(value["cwd"]).resolve(), root.resolve())
            self.assertTrue(value["overrides_unset"])

    def test_existing_server_overlay_removes_public_backend_and_preserves_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["compose.yaml", "compose.https.yaml"]:
                shutil.copy(settings.BASE_DIR / name, root / name)
            (root / ".env").write_text("TM_SERVER_SECRET=synthetic-key\nTM_DB_PASSWORD=synthetic-password\n")
            (root / ".env.ai").write_text("AI_ENABLED=false\n")
            (root / "compose.server.yaml").write_text("""services:
  web:
    ports: ["8000:8000"]
    environment: &server
      DJANGO_SECRET_KEY: ${TM_SERVER_SECRET}
      DATABASE_URL: postgresql://tm:${TM_DB_PASSWORD}@postgres/tm_dev
  scheduler:
    environment: *server
  ai_worker:
    environment: *server
""")
            env = {"PATH": os.environ["PATH"], "HOME": directory, "TM_HTTPS_IP": IP}
            result = subprocess.run([
                str(settings.BASE_DIR / ".local/bin/docker-compose"),
                "-f", "compose.yaml", "-f", "compose.server.yaml", "-f", "compose.https.yaml",
                "--profile", "proxy", "--profile", "ai", "config", "--format", "json",
            ], cwd=root, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, "synthetic Compose merge failed")
            services = json.loads(result.stdout)["services"]
            self.assertEqual({name for name, s in services.items() if s.get("ports")}, {"proxy"})
            self.assertEqual({str(p["published"]) for p in services["proxy"]["ports"]}, {"80", "443"})
            for name in ["web", "scheduler", "ai_worker"]:
                environment = services[name]["environment"]
                self.assertEqual(environment["DJANGO_SECRET_KEY"], "synthetic-key")
                self.assertEqual(environment["DATABASE_URL"], "postgresql://tm:synthetic-password@postgres/tm_dev")
                self.assertEqual(environment["DJANGO_SETTINGS_MODULE"], "config.https_settings")
                self.assertNotIn("AI_ENABLED", environment)
            mounts = {v["target"]: v for v in services["proxy"]["volumes"]}
            self.assertTrue(mounts["/etc/caddy/Caddyfile"]["source"].endswith("deploy/Caddyfile.ip-https"))
            self.assertEqual(set(mounts), {"/etc/caddy/Caddyfile", "/data", "/config"})
            self.assertTrue(mounts["/etc/caddy/Caddyfile"]["read_only"])
            self.assertEqual(services["postgres"]["volumes"][0]["source"], "postgres_data")
            self.assertIn("X-Forwarded-Proto", services["web"]["healthcheck"]["test"][-1])

    def test_caddy_public_ip_shortlived_issuer_sni_and_private_request_logs(self):
        result = subprocess.run([
            str(settings.BASE_DIR / ".local/bin/caddy"), "adapt", "--config",
            "deploy/Caddyfile.ip-https", "--adapter", "caddyfile",
        ], cwd=settings.BASE_DIR, env={**os.environ, "TM_HTTPS_IP": IP}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        config = json.loads(result.stdout)
        self.assertTrue(config["admin"]["disabled"])
        policy = config["apps"]["tls"]["automation"]["policies"][0]
        self.assertEqual(policy["subjects"], [IP])
        self.assertEqual(policy["issuers"], [{"module": "acme", "ca": "https://acme-v02.api.letsencrypt.org/directory", "profile": "shortlived"}])
        server = next(iter(config["apps"]["http"]["servers"].values()))
        self.assertEqual(server["listen"], [":443"])
        self.assertEqual(server["tls_connection_policies"][0]["default_sni"], IP)
        self.assertIn('"{http.request.scheme}"', result.stdout)
        encoder = config["logging"]["logs"]["default"]["encoder"]
        self.assertEqual(encoder["fields"]["request"]["filter"], "delete")

    def test_https_settings_accept_public_ip_and_reject_invalid_hosts_or_debug(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AI_")}
        env.update(DJANGO_SETTINGS_MODULE="config.https_settings", TM_HTTPS_IP=IP,
                   DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DJANGO_DEBUG="false", ALLOW_DEMO_SEED="false",
                   DATABASE_URL="postgresql://tm:synthetic@127.0.0.1:55432/not_accessed")
        for change, success in [({}, True), ({"TM_HTTPS_IP": "https://" + IP}, False),
                                ({"TM_HTTPS_IP": "127.0.0.1"}, False),
                                ({"DJANGO_DEBUG": "true"}, False), ({"ALLOW_DEMO_SEED": "true"}, False)]:
            result = subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "ERROR"],
                                    cwd=settings.BASE_DIR, env={**env, **change}, capture_output=True, timeout=15)
            self.assertEqual(result.returncode == 0, success, "synthetic HTTPS settings check")


@override_settings(
    PASSWORD_HASHERS=TEST_HASHERS, ALLOWED_HOSTS=[IP], CSRF_TRUSTED_ORIGINS=["https://" + IP],
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), SECURE_HSTS_SECONDS=3600,
)
class IPHttpsApplicationTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.assign(self.customer)
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST=IP, HTTP_X_FORWARDED_PROTO="https")

    def test_https_proxy_login_secure_cookies_csrf_employee_save_and_health(self):
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        headers = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value, "HTTP_ORIGIN": "https://" + IP,
                   "HTTP_X_TM_QUEUE_USER": str(self.employee.pk)}
        response = self.client.post("/auth/login", {"phone": self.employee.phone_normalized, "password": STRONG_PASSWORD},
                                    content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["sessionid"]["secure"])
        headers["HTTP_X_CSRFTOKEN"] = self.client.cookies["csrftoken"].value
        self.assertEqual(self.client.get("/app/employee/today").status_code, 200)
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/api/employee/context", HTTP_X_TM_QUEUE_USER=str(self.employee.pk)).status_code, 200)
        response = self.client.post("/api/employee/batch-update", {"rows": [self.mutation(self.customer)]},
                                    content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.notes, "가상 저장")
        headers["HTTP_ORIGIN"] = "https://untrusted.example"
        self.assertEqual(self.client.post("/auth/logout", {}, content_type="application/json", **headers).status_code, 403)

    def test_http_redirects_without_loop_and_unknown_host_is_rejected(self):
        response = self.client.get("/auth/login", HTTP_X_FORWARDED_PROTO="http")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://" + IP + "/auth/login")
        self.assertEqual(self.client.get("/auth/login").status_code, 200)
        self.assertEqual(self.client.get("/auth/login", HTTP_HOST="untrusted.example").status_code, 400)
