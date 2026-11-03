from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.common.models import TimestampedModel


class Callback(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "미완료"
        COMPLETED = "COMPLETED", "완료"
        CANCELLED = "CANCELLED", "취소"

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="callbacks")
    due_at = models.DateTimeField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_callbacks")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="updated_callbacks")
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="completed_callbacks")
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["customer"], condition=Q(status="PENDING"), name="callback_one_pending"),
            models.CheckConstraint(condition=Q(version__gte=1), name="callback_version_positive"),
            models.CheckConstraint(condition=(
                Q(status="PENDING", completed_at__isnull=True, completed_by__isnull=True, cancelled_at__isnull=True)
                | Q(status="COMPLETED", completed_at__isnull=False, completed_by__isnull=False, cancelled_at__isnull=True)
                | Q(status="CANCELLED", completed_at__isnull=True, completed_by__isnull=True, cancelled_at__isnull=False)
            ), name="callback_state_consistent"),
        ]
        indexes = [models.Index(fields=["due_at", "customer"], condition=Q(status="PENDING"), name="callback_pending_due_idx")]
