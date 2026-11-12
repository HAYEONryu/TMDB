"""Read-only schema checks; no customer values or credentials are printed."""
import json

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.imports.models import ImportBatch, ImportCandidate, ImportRowResult
from apps.operations.models import IdempotencyRecord, OperationEvent


class Command(BaseCommand):
    help = "엑셀 등록 관련 미적용 migration과 실제 DB 스키마를 읽기 전용으로 검사합니다."

    def handle(self, *args, **options):
        executor = MigrationExecutor(connection)
        pending = [f"{migration.app_label}.{migration.name}" for migration, backwards in
            executor.migration_plan(executor.loader.graph.leaf_nodes()) if not backwards]
        issues = []
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            for model in [Customer, Callback, ConsultationRevision, ImportBatch,
                    ImportCandidate, ImportRowResult, IdempotencyRecord, OperationEvent]:
                table = model._meta.db_table
                if table not in tables:
                    issues.append({"table": table, "issue": "missing_table"})
                    continue
                columns = {column.name: column for column in connection.introspection.get_table_description(cursor, table)}
                for field in model._meta.local_fields:
                    column = columns.get(field.column)
                    if column is None:
                        issues.append({"table": table, "column": field.column, "issue": "missing_column"})
                    elif field.get_internal_type() == "CharField" and column.internal_size not in (None, -1) and column.internal_size < field.max_length:
                        issues.append({"table": table, "column": field.column, "issue": "column_too_short"})
                constraints = connection.introspection.get_constraints(cursor, table)
                for constraint in model._meta.constraints:
                    if constraint.name not in constraints:
                        issues.append({"table": table, "constraint": constraint.name, "issue": "missing_constraint"})
                if model is Customer and "customer_name_not_empty" in constraints:
                    issues.append({"table": table, "issue": "legacy_name_required_constraint"})
        self.stdout.write(json.dumps({"ok": not pending and not issues,
            "pending_migrations": pending, "schema_issues": issues}, ensure_ascii=False))
