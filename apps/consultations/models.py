from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from apps.common.models import TimestampedModel


class ConsultationRevision(TimestampedModel):
    class Source(models.TextChoices):
        MANUAL = "MANUAL", "직접 수정"
        AI_APPLIED = "AI_APPLIED", "AI 추천 적용"
        IMPORT = "IMPORT", "업로드"
        BASELINE = "BASELINE", "도입 시점 기록"
        SYSTEM_DELETE_NOTE = "SYSTEM_DELETE_NOTE", "삭제 승인 문구"

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="consultation_revisions")
    assignment = models.ForeignKey("assignments.Assignment", null=True, blank=True, on_delete=models.CASCADE, related_name="consultation_revisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="consultation_revisions")
    saved_at = models.DateTimeField(default=timezone.now)
    customer_version = models.PositiveBigIntegerField()
    changed_fields = models.JSONField(default=list)
    before_values = models.JSONField(default=dict)
    after_values = models.JSONField(default=dict)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=18, choices=Source.choices)
    # Original AI result FK is added alongside the AI models in P9, before AI_APPLIED is exposed.

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["customer", "customer_version"], name="revision_customer_version_unique"),
            models.CheckConstraint(condition=Q(customer_version__gte=1), name="revision_version_positive"),
            models.CheckConstraint(condition=Q(source__in=["MANUAL", "AI_APPLIED", "IMPORT", "BASELINE", "SYSTEM_DELETE_NOTE"]), name="revision_source_valid"),
            models.CheckConstraint(condition=Q(actor__isnull=False) | Q(source="BASELINE"), name="revision_actor_required"),
        ]
        indexes = [models.Index(fields=["actor", "saved_at"], name="revision_actor_time_idx"),
                   models.Index(fields=["customer", "saved_at"], name="revision_customer_time_idx")]

    def clean(self):
        super().clean()
        if self.assignment_id and self.assignment.customer_id != self.customer_id:
            raise ValidationError({"assignment": "상담 이력과 할당의 고객이 일치해야 합니다."})
