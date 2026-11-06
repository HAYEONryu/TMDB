from django.conf import settings
from django.db import models
from django.db.models import Q, F
from apps.common.models import TimestampedModel


class Feature(models.TextChoices):
    CLEANUP = "CLEANUP", "상담 정리"
    SUMMARY = "SUMMARY", "상담 요약"
    NEXT_QUESTIONS = "NEXT_QUESTIONS", "다음 질문"
    WEEKLY_BRIEFING = "WEEKLY_BRIEFING", "주간 브리핑"
    EMPLOYEE_COACHING = "EMPLOYEE_COACHING", "직원 코칭"
    TEAM_GUIDE = "TEAM_GUIDE", "팀 가이드"


class AIQuotaBucket(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    korean_date = models.DateField()
    successful_count = models.PositiveSmallIntegerField(default=0)
    reserved_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "korean_date"], name="ai_quota_user_date_unique"),
                       models.CheckConstraint(condition=Q(successful_count__lte=30-F("reserved_count")), name="ai_quota_total_max30")]


class AIBudgetMonth(TimestampedModel):
    month = models.DateField(unique=True)
    reserved_usd = models.DecimalField(max_digits=24, decimal_places=12, default=0)
    charged_usd = models.DecimalField(max_digits=24, decimal_places=12, default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(reserved_usd__gte=0, charged_usd__gte=0), name="ai_budget_nonnegative")]


class AIRequest(TimestampedModel):
    class Status(models.TextChoices):
        RESERVED = "RESERVED", "접수"
        RUNNING = "RUNNING", "처리 중"
        SUCCEEDED = "SUCCEEDED", "완료"
        FAILED = "FAILED", "실패"
        CANCELLED = "CANCELLED", "취소"
        UNKNOWN = "UNKNOWN", "결과 미확인"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ai_requests")
    actor_session_version = models.PositiveBigIntegerField()
    feature = models.CharField(max_length=24, choices=Feature.choices)
    customer = models.ForeignKey("customers.Customer", null=True, on_delete=models.SET_NULL)
    assignment = models.ForeignKey("assignments.Assignment", null=True, on_delete=models.SET_NULL)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="ai_coaching_requests")
    site = models.ForeignKey("sites.Site", null=True, on_delete=models.SET_NULL)
    customer_version = models.PositiveBigIntegerField(null=True)
    korean_date = models.DateField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    scope_key = models.CharField(max_length=64)
    period_key = models.CharField(max_length=10)
    idempotency_key = models.UUIDField()
    body_hash = models.CharField(max_length=64)
    cache_key = models.CharField(max_length=64, db_index=True)
    source_fingerprint = models.CharField(max_length=64)
    input_payload = models.JSONField(default=dict)
    prompt_version = models.CharField(max_length=32, default="foundation-v1")
    schema_version = models.CharField(max_length=32, default="foundation-v1")
    provider = models.CharField(max_length=64)
    model_version = models.CharField(max_length=128)
    reasoning_effort = models.CharField(max_length=8, blank=True, default="")
    pricing_version = models.CharField(max_length=64)
    input_price = models.DecimalField(max_digits=20, decimal_places=10)
    output_price = models.DecimalField(max_digits=20, decimal_places=10)
    input_tokens_cap = models.PositiveIntegerField()
    output_tokens_cap = models.PositiveIntegerField()
    reasoning_tokens_cap = models.PositiveIntegerField()
    budget_month = models.ForeignKey(AIBudgetMonth, on_delete=models.PROTECT)
    quota_bucket = models.ForeignKey(AIQuotaBucket, null=True, on_delete=models.PROTECT)
    reserved_cost = models.DecimalField(max_digits=24, decimal_places=12)
    charged_cost = models.DecimalField(max_digits=24, decimal_places=12, default=0)
    settled = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RESERVED, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    started_at = models.DateTimeField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    unknown_until = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    is_test = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "idempotency_key"], name="ai_request_actor_key_unique"),
                       models.CheckConstraint(condition=Q(status__in=["RESERVED","RUNNING","SUCCEEDED","FAILED","CANCELLED","UNKNOWN"]), name="ai_request_status_valid"),
                       models.CheckConstraint(condition=Q(feature__in=Feature.values), name="ai_request_feature_valid"),
                       models.CheckConstraint(condition=Q(reserved_cost__gte=0, charged_cost__gte=0, input_price__gte=0, output_price__gte=0), name="ai_request_cost_nonnegative"),
                       models.CheckConstraint(condition=Q(period_end__gte=F("period_start")), name="ai_request_period_valid"),
                       models.UniqueConstraint(fields=["actor"], condition=Q(status__in=["RESERVED","RUNNING","UNKNOWN"]), name="ai_one_pending_per_actor")]


class AIResult(TimestampedModel):
    request = models.OneToOneField(AIRequest, on_delete=models.CASCADE, related_name="result")
    payload = models.JSONField(default=dict)
    valid = models.BooleanField(default=False)
    generated_at = models.DateTimeField(null=True)
    invalidated_at = models.DateTimeField(null=True)
    invalidation_reason = models.CharField(max_length=64, default="PENDING")
    stale = models.BooleanField(default=False)
    guide_status = models.CharField(max_length=10, choices=[("DRAFT","초안"),("PUBLISHED","게시")], default="DRAFT")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="reviewed_ai_results")
    reviewed_at = models.DateTimeField(null=True)
    published_at = models.DateTimeField(null=True)
    guide_body = models.TextField(blank=True)
    guide_version = models.PositiveIntegerField(default=1)
    guide_reviewed_version = models.PositiveIntegerField(null=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(guide_version__gte=1), name="ai_guide_version_positive"),
                       models.CheckConstraint(condition=Q(guide_reviewed_version__isnull=True)|Q(guide_reviewed_version=F("guide_version"),reviewed_by__isnull=False,reviewed_at__isnull=False), name="ai_guide_review_version_matches")]


class AIRequestKey(TimestampedModel):
    """Also binds new keys that return a cached/shared task, without copying input."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.UUIDField()
    body_hash = models.CharField(max_length=64)
    request = models.ForeignKey(AIRequest, on_delete=models.PROTECT, related_name="request_keys")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor","key"], name="ai_request_alias_unique")]


class AIReportSlot(TimestampedModel):
    feature = models.CharField(max_length=24, choices=Feature.choices)
    scope_key = models.CharField(max_length=64)
    period_key = models.CharField(max_length=10)
    current_request = models.OneToOneField(AIRequest, null=True, on_delete=models.SET_NULL, related_name="reserved_slot")
    success_result = models.OneToOneField(AIResult, null=True, on_delete=models.SET_NULL, related_name="success_slot")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["feature","scope_key","period_key"], name="ai_report_slot_unique"),
                       models.CheckConstraint(condition=Q(feature__in=["WEEKLY_BRIEFING","EMPLOYEE_COACHING","TEAM_GUIDE"]), name="ai_report_feature_valid")]


class AIUsageAttempt(TimestampedModel):
    request = models.ForeignKey(AIRequest, on_delete=models.PROTECT, related_name="attempts")
    sequence = models.PositiveSmallIntegerField()
    provider_request_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=12, choices=[(v,v) for v in ["PREPARED","SUCCEEDED","FAILED","UNKNOWN","NOT_SENT"]], default="PREPARED")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)
    cached_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=24, decimal_places=12)
    actual_cost = models.DecimalField(max_digits=24, decimal_places=12, null=True)
    accounted_cost = models.DecimalField(max_digits=24, decimal_places=12, default=0)
    currency = models.CharField(max_length=3, default="USD")
    pricing_version = models.CharField(max_length=64)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["request","sequence"], name="ai_attempt_sequence_unique"),
                       models.CheckConstraint(condition=Q(estimated_cost__gte=0, accounted_cost__gte=0)&(Q(actual_cost__isnull=True)|Q(actual_cost__gte=0)), name="ai_attempt_cost_nonnegative")]


class SiteKnowledge(TimestampedModel):
    site = models.ForeignKey("sites.Site", on_delete=models.CASCADE, related_name="knowledge")
    title = models.CharField(max_length=100)
    body = models.TextField()
    version = models.PositiveIntegerField(default=1)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(null=True)
    is_valid = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(version__gte=1), name="ai_knowledge_version_positive"),
                       models.CheckConstraint(condition=Q(is_valid=False)|Q(reviewed_at__isnull=False,reviewed_by__isnull=False), name="ai_knowledge_review_required")]


class AIResultSource(TimestampedModel):
    result = models.ForeignKey(AIResult, on_delete=models.CASCADE, related_name="sources")
    customer = models.ForeignKey("customers.Customer", null=True, on_delete=models.SET_NULL)
    revision = models.ForeignKey("consultations.ConsultationRevision", null=True, on_delete=models.SET_NULL)
    knowledge = models.ForeignKey(SiteKnowledge, null=True, on_delete=models.SET_NULL)
    previous_result = models.ForeignKey(AIResult, null=True, on_delete=models.SET_NULL, related_name="derived_sources")
    source_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.CheckConstraint(condition=
            Q(customer__isnull=False,revision__isnull=True,knowledge__isnull=True,previous_result__isnull=True)|
            Q(customer__isnull=True,revision__isnull=False,knowledge__isnull=True,previous_result__isnull=True)|
            Q(customer__isnull=True,revision__isnull=True,knowledge__isnull=False,previous_result__isnull=True)|
            Q(customer__isnull=True,revision__isnull=True,knowledge__isnull=True,previous_result__isnull=False), name="ai_source_exactly_one")]


class AIReportSnapshot(TimestampedModel):
    """Server aggregates frozen at submission; never accepted from the provider."""
    request = models.OneToOneField(AIRequest, on_delete=models.CASCADE, related_name="report_snapshot")
    data = models.JSONField(default=dict)


class AINoteClassification(TimestampedModel):
    revision = models.ForeignKey("consultations.ConsultationRevision", on_delete=models.CASCADE)
    fingerprint = models.CharField(max_length=64)
    labels = models.JSONField(default=list)
    evidence = models.TextField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "fingerprint"], name="ai_note_classification_unique")]


class GuidePublication(TimestampedModel):
    site = models.OneToOneField("sites.Site", on_delete=models.CASCADE, related_name="guide_publication")
    result = models.ForeignKey(AIResult, on_delete=models.CASCADE)
    body = models.TextField()
    version = models.PositiveIntegerField()
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    published_at = models.DateTimeField()
    is_test = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(version__gte=1), name="ai_publication_version_positive")]
