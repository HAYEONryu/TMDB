from django.conf import settings
from django.db import models
from django.db.models import F, Q
from apps.common.models import TimestampedModel


class Assignment(TimestampedModel):
    class EndReason(models.TextChoices):
        MANUAL_RECALL = "MANUAL_RECALL", "수동 회수"
        AUTO_RECALL = "AUTO_RECALL", "자동 회수"
        REASSIGNED = "REASSIGNED", "재분배"
        USER_DISABLED = "USER_DISABLED", "사용자 비활성화"
        SOFT_DELETED = "SOFT_DELETED", "휴지통 이동"

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments")
    assigned_at = models.DateTimeField()
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_records")
    first_activity_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=16, choices=EndReason.choices, null=True, blank=True)
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="ended_assignments")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["customer"], condition=Q(ended_at__isnull=True), name="assignment_one_current"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True, end_reason__isnull=True) | Q(ended_at__isnull=False, end_reason__isnull=False, end_reason__in=["MANUAL_RECALL", "AUTO_RECALL", "REASSIGNED", "USER_DISABLED", "SOFT_DELETED"]), name="assignment_end_consistent"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("assigned_at")), name="assignment_end_after_start"),
            models.CheckConstraint(condition=Q(first_activity_at__isnull=True) | Q(first_activity_at__gte=F("assigned_at")), name="assignment_activity_after_start"),
        ]
        indexes = [
            models.Index(fields=["employee", "ended_at", "assigned_at"], name="assignment_employee_idx"),
            models.Index(fields=["assigned_at", "employee"], name="assignment_date_idx"),
        ]
