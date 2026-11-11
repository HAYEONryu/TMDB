from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.common.models import TimestampedModel


class Customer(TimestampedModel):
    class CallResult(models.TextChoices):
        NO_ANSWER = "NO_ANSWER", "부재"
        REJECTED = "REJECTED", "거절"
        INTERESTED = "INTERESTED", "관심"
        CALL_AGAIN = "CALL_AGAIN", "재통화"
        VISIT_BOOKED = "VISIT_BOOKED", "방문예약"
        VISITED = "VISITED", "방문"
        REVISITED = "REVISITED", "재방"

    class ContractStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN", "미확인"
        NO_CONTRACT = "NO_CONTRACT", "미계약"
        CONTRACTED = "CONTRACTED", "계약"

    site = models.ForeignKey("sites.Site", on_delete=models.CASCADE, related_name="customers")
    customer_name = models.CharField(max_length=100, blank=True, default="")
    phone_normalized = models.CharField(max_length=11)
    call_result = models.CharField(max_length=12, choices=CallResult.choices, null=True, blank=True)
    visit_at = models.DateTimeField(null=True, blank=True)
    contract_status = models.CharField(max_length=12, choices=ContractStatus.choices, default=ContractStatus.UNKNOWN)
    # TextField deliberately has no 10,000-char DB cap: system approval notes must fit.
    notes = models.TextField(blank=True, default="")
    housing_status = models.CharField(max_length=200, blank=True, default="")
    residence = models.CharField(max_length=200, blank=True, default="")
    route = models.CharField(max_length=200, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    admin_notes = models.TextField(blank=True, default="")
    current_assignment = models.OneToOneField("assignments.Assignment", null=True, blank=True, on_delete=models.SET_NULL, related_name="current_for_customer")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="deleted_customers")
    version = models.PositiveBigIntegerField(default=1)
    import_batch = models.ForeignKey("imports.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="customers")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "phone_normalized"], condition=Q(deleted_at__isnull=True), name="customer_site_live_phone_unique"),
            models.CheckConstraint(condition=Q(phone_normalized__regex=r"^010[0-9]{8}$"), name="customer_phone_format"),
            models.CheckConstraint(condition=Q(customer_name="") | Q(customer_name__regex=r"\S"), name="customer_name_valid"),
            models.CheckConstraint(condition=Q(version__gte=1), name="customer_version_positive"),
            models.CheckConstraint(condition=Q(call_result__isnull=True) | Q(call_result__in=["NO_ANSWER", "REJECTED", "INTERESTED", "CALL_AGAIN", "VISIT_BOOKED", "VISITED", "REVISITED"]), name="customer_call_result_valid"),
            models.CheckConstraint(condition=Q(contract_status__in=["UNKNOWN", "NO_CONTRACT", "CONTRACTED"]), name="customer_contract_valid"),
            models.CheckConstraint(condition=Q(deleted_at__isnull=True) | Q(current_assignment__isnull=True), name="deleted_customer_unassigned"),
        ]
        indexes = [models.Index(fields=["site", "deleted_at", "created_at", "id"], name="customer_site_list_idx"),
            models.Index(fields=["phone_normalized"], condition=Q(deleted_at__isnull=True), name="customer_live_phone_idx")]

    def clean(self):
        super().clean()
        if self.current_assignment_id:
            assignment = self.current_assignment
            if assignment.customer_id != self.id or assignment.ended_at is not None:
                raise ValidationError({"current_assignment": "현재 할당은 이 고객의 종료되지 않은 할당이어야 합니다."})


class CustomerChangeEvent(TimestampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="change_events")
    assignment = models.ForeignKey("assignments.Assignment", null=True, on_delete=models.CASCADE, related_name="change_events")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_change_events")
    changed_at = models.DateTimeField()
    changed_fields = models.JSONField(default=list)


class CustomerDeletionRequest(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "요청완료"
        APPROVED = "APPROVED", "승인"
        CLOSED = "CLOSED", "종료"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="deletion_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deletion_requests")
    requested_assignment = models.ForeignKey("assignments.Assignment", on_delete=models.CASCADE, related_name="deletion_requests")
    requested_at = models.DateTimeField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_deletion_requests")
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=32, blank=True, default="")
    deletion_note = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["customer"], condition=Q(status="PENDING"), name="deletion_one_pending"),
            models.CheckConstraint(condition=(
                Q(status="PENDING", approved_by__isnull=True, approved_at__isnull=True, closed_at__isnull=True, close_reason="", deletion_note="")
                | (Q(status="APPROVED", approved_by__isnull=False, approved_at__isnull=False, closed_at__isnull=True, close_reason="") & ~Q(deletion_note=""))
                | Q(status="CLOSED", approved_by__isnull=True, approved_at__isnull=True, closed_at__isnull=False, close_reason="ALREADY_DELETED", deletion_note="")
            ), name="deletion_state_consistent"),
        ]
        indexes = [models.Index(fields=["status", "requested_at", "id"], name="deletion_pending_list_idx")]

    def clean(self):
        super().clean()
        if self.requested_assignment_id and self.requested_assignment.customer_id != self.customer_id:
            raise ValidationError({"requested_assignment": "요청 당시 할당의 고객이 일치해야 합니다."})
