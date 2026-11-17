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
    source_ai_result = models.ForeignKey("ai_assistant.AIResult", null=True, blank=True, on_delete=models.SET_NULL, related_name="applied_revisions")

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


class PerformanceTracking(models.Model):
    """Deployment boundary; never backfill missing telephone/visit evidence."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    started_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name='performance_tracking_singleton')]


class CustomerActivity(TimestampedModel):
    class Kind(models.TextChoices):
        CALL = 'CALL', '통화 시도'
        VISIT = 'VISIT', '실제 방문'

    class Connection(models.TextChoices):
        CONNECTED = 'CONNECTED', '연결'
        NOT_CONNECTED = 'NOT_CONNECTED', '미연결·부재·미응답'
        UNKNOWN = 'UNKNOWN', '확인 불가'

    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='activities')
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='customer_activities')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='customer_activities')
    assignment = models.ForeignKey('assignments.Assignment', null=True, on_delete=models.SET_NULL, related_name='activities')
    kind = models.CharField(max_length=5, choices=Kind.choices)
    occurred_at = models.DateTimeField(null=True, blank=True)
    connection = models.CharField(max_length=13, choices=Connection.choices, blank=True, default='')
    visited_on = models.DateField(null=True, blank=True)
    idempotency_key = models.UUIDField()
    body_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['actor', 'idempotency_key'], name='activity_actor_request_unique'),
            models.CheckConstraint(condition=(
                Q(kind='CALL', occurred_at__isnull=False, visited_on__isnull=True,
                  connection__in=['CONNECTED', 'NOT_CONNECTED', 'UNKNOWN']) |
                Q(kind='VISIT', occurred_at__isnull=True, visited_on__isnull=False, connection='')
            ), name='activity_evidence_consistent'),
        ]
        indexes = [models.Index(fields=['actor', 'site', 'occurred_at'], name='activity_actor_site_call_idx'),
                   models.Index(fields=['actor', 'site', 'visited_on'], name='activity_actor_site_visit_idx')]
