from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.common.models import TimestampedModel


class ImportBatch(TimestampedModel):
    class Status(models.TextChoices):
        VALIDATED = "VALIDATED", "검증 완료"
        COMMITTED = "COMMITTED", "확정"
        EXPIRED = "EXPIRED", "만료"
        FAILED = "FAILED", "실패"

    site = models.ForeignKey("sites.Site", on_delete=models.CASCADE, related_name="import_batches")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="import_batches")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.VALIDATED)
    expires_at = models.DateTimeField()
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    validation_summary = models.JSONField(default=dict)
    committed_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="committed_imports")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=["VALIDATED", "COMMITTED", "EXPIRED", "FAILED"]), name="import_status_valid")]


class ImportCandidate(TimestampedModel):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="candidates")
    row_number = models.PositiveIntegerField()
    normalized_values = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "row_number"], name="import_candidate_row_unique")]


class ImportRowResult(TimestampedModel):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="row_results")
    row_number = models.PositiveIntegerField()
    success = models.BooleanField(default=False)
    customer_name = models.TextField(blank=True, default="")
    phone_input = models.TextField(blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    reason = models.TextField(blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "row_number"], name="import_result_row_unique")]
