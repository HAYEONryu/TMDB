from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.common.models import TimestampedModel


class IdempotencyRecord(TimestampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="idempotency_records")
    operation = models.CharField(max_length=64)
    key = models.UUIDField()
    body_hash = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    target_ids = models.JSONField(default=list)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "operation", "key"], name="idempotency_actor_op_key_unique")]


class MutationReceipt(TimestampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="mutation_receipts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="mutation_receipts")
    mutation_id = models.UUIDField()
    body_hash = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "mutation_id"], name="mutation_actor_id_unique")]


class ScheduledJobRun(TimestampedModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "실행 중"
        FAILED = "FAILED", "실패"
        COMPLETED = "COMPLETED", "완료"

    job_type = models.CharField(max_length=64)
    business_date = models.DateField()
    cutoff = models.DateTimeField()
    target_site = models.ForeignKey("sites.Site", null=True, on_delete=models.SET_NULL, related_name="scheduled_runs")
    target_site_id_snapshot = models.UUIDField(null=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.RUNNING)
    attempt_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    affected_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job_type", "business_date"], name="scheduled_job_date_unique"),
            models.CheckConstraint(condition=Q(status__in=["RUNNING", "FAILED", "COMPLETED"]), name="scheduled_status_valid"),
        ]


class OperationEvent(TimestampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="operation_events")
    operation = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    affected_count = models.PositiveIntegerField(default=0)
