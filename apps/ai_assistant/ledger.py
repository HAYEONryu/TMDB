"""All functions run inside the caller's short business_write transaction."""
from decimal import Decimal, ROUND_UP
from django.utils import timezone
from .models import AIQuotaBucket, AIBudgetMonth, AIReportSlot, AIRequest

UNIT = Decimal("0.000000000001")


def cost(input_tokens, output_tokens, reasoning_tokens, input_price, output_price):
    return ((Decimal(input_tokens)*input_price + Decimal(output_tokens+reasoning_tokens)*output_price)/Decimal(1000000)).quantize(UNIT, rounding=ROUND_UP)


def settle(request, status, code="", *, now=None):
    if request.settled: return False
    now = now or timezone.now()
    attempts = list(request.attempts.order_by("sequence"))
    charged = sum((attempt.accounted_cost for attempt in attempts), Decimal(0))
    budget = AIBudgetMonth.objects.select_for_update().get(pk=request.budget_month_id)
    budget.reserved_usd -= request.reserved_cost
    budget.charged_usd += charged
    budget.save(update_fields=["reserved_usd", "charged_usd", "updated_at"])
    if request.quota_bucket_id:
        bucket = AIQuotaBucket.objects.select_for_update().get(pk=request.quota_bucket_id)
        bucket.reserved_count -= 1
        if status == AIRequest.Status.SUCCEEDED: bucket.successful_count += 1
        bucket.save(update_fields=["reserved_count", "successful_count", "updated_at"])
    slot = AIReportSlot.objects.select_for_update().filter(current_request=request).first()
    if slot:
        slot.current_request = None
        if status == AIRequest.Status.SUCCEEDED: slot.success_result = request.result
        slot.save(update_fields=["current_request", "success_result", "updated_at"])
    request.charged_cost = charged
    request.settled = True
    request.status = status
    request.error_code = code
    request.completed_at = now
    request.input_payload = {}
    request.lease_expires_at = None
    request.save()
    return True
