"""Actual dump/restore of fictitious test data into a separate disposable DB."""
from scripts.verification_evidence import artifact_path

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import timedelta
from uuid import uuid4

import psycopg
from psycopg import sql
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.callbacks.models import Callback
from apps.customers.deletions import submit, approve
from apps.customers.services import update_row
from tests.helpers import login, STRONG_PASSWORD
from tests.test_p4 import Fixtures
from tests.restored_login import verify_restored_login


def table_snapshot(db):
    db.execute("SET TIME ZONE 'UTC'")
    names = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    result = {}
    for (name,) in names:
        rows = db.execute(sql.SQL("SELECT row_to_json(t) FROM {} t").format(sql.Identifier(name))).fetchall()
        encoded = sorted(json.dumps(row[0], sort_keys=True, ensure_ascii=False, separators=(",", ":")) for row in rows)
        result[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest()}
    return result


class BasicBackupRestoreTests(Fixtures, TransactionTestCase):
    def test_actual_dump_restore_separate_database_accounts_assignments_notes_callbacks_requests(self):
        source = connection.settings_dict
        self.assertTrue(settings.TESTING and source["NAME"].startswith("test_"), "가짜 테스트 DB만 백업합니다.")
        self.prepare()
        first, second = self.customers(2)
        for customer in [first, second]:
            self.assign(customer)
            mutation = self.mutation(customer, "별도 복원 검증용 가짜 상담")
            mutation["changes"]["callback_due_at"] = (timezone.now() + timedelta(days=1)).isoformat()
            update_row(self.employee, mutation)
            customer.refresh_from_db()
        first_request, _ = submit(self.employee, first.pk, {"assignment_id": str(first.current_assignment_id), "expected_version": first.version, "idempotency_key": str(uuid4())})
        submit(self.employee, second.pk, {"assignment_id": str(second.current_assignment_id), "expected_version": second.version, "idempotency_key": str(uuid4())})
        approve(self.admin, first_request["request_id"], {"idempotency_key": str(uuid4())})
        callback = Callback.objects.get(customer=second)
        from apps.callbacks.services import complete
        complete(self.employee, second.pk, {"callback_id": str(callback.pk), "callback_version": callback.version, "assignment_id": str(second.current_assignment_id), "expected_version": second.version, "idempotency_key": str(uuid4())})
        login(self.admin); login(self.employee)
        params = {"host": source["HOST"], "port": source["PORT"], "user": source["USER"], "password": source["PASSWORD"]}
        target = "test_tm_p8_restore_" + uuid4().hex
        binary = Path(os.environ.get("TM_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
        common = ["--host", str(source["HOST"]), "--port", str(source["PORT"]), "--username", source["USER"]]
        environment = {**os.environ, "PGPASSWORD": source["PASSWORD"]}
        for key in list(environment):
            if key.startswith("AI_"): environment.pop(key)
        started = time.monotonic()
        created = False
        with psycopg.connect(dbname="postgres", autocommit=True, **params) as maintenance:
            try:
                maintenance.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
                created = True
                with tempfile.TemporaryDirectory(prefix="tm-p8-restore-", dir="/private/tmp") as directory:
                    backup = Path(directory) / "fake-test.dump"
                    backup.touch(mode=0o600)
                    dump = subprocess.run([str(binary / "pg_dump"), *common, "--format=custom", "--no-owner", "--no-acl", "--file", str(backup), source["NAME"]], env=environment, capture_output=True, timeout=60)
                    self.assertEqual(dump.returncode, 0, "pg_dump 실패(원문 로그를 표시하지 않음)")
                    size = backup.stat().st_size
                    restored = subprocess.run([str(binary / "pg_restore"), *common, "--exit-on-error", "--no-owner", "--no-acl", "--dbname", target, str(backup)], env=environment, capture_output=True, timeout=60)
                    self.assertEqual(restored.returncode, 0, "pg_restore 실패(원문 로그를 표시하지 않음)")
                    with psycopg.connect(dbname=source["NAME"], autocommit=True, **params) as original, psycopg.connect(dbname=target, autocommit=True, **params) as replica:
                        expected = table_snapshot(original)
                        self.assertEqual(table_snapshot(replica), expected)
                        account = replica.execute("SELECT password, must_change_password, is_active, role FROM accounts_user WHERE id=%s", (self.employee.pk,)).fetchone()
                        self.assertTrue(check_password(STRONG_PASSWORD, account[0]))
                        self.assertEqual(account[1:], (False, True, User.Role.EMPLOYEE))
                        self.assertEqual(replica.execute("SELECT count(*) FROM customers_customer c JOIN assignments_assignment a ON c.current_assignment_id=a.id WHERE c.id=a.customer_id AND a.ended_at IS NULL").fetchone()[0], 1)
                        restored_login=verify_restored_login(target,self.employee,self.admin)
                        replica.execute("UPDATE customers_customer SET notes=%s WHERE id=%s", ("별도 DB만 변경한 가짜 값", second.pk))
                        self.assertEqual(table_snapshot(original), expected)
                    report = {"separate_database": True, "backup_bytes": size, "backup_mode_0600": backup.stat().st_mode & 0o777 == 0o600,
                              "restore_seconds": round(time.monotonic() - started, 3), "all_tables_match": True, "restored_password_valid": True,
                              "restored_login_and_role_routes": restored_login,
                              "restored_assignment_relation_valid": True, "replica_write_did_not_change_source": True, "tables": expected}
            finally:
                if created:
                    maintenance.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
            self.assertIsNone(maintenance.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone())
        self.assertFalse(Path(directory).exists())
        report["temporary_database_and_dump_removed"] = True
        path = artifact_path('p8-restore.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
