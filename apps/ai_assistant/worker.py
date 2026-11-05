"""Durable DB queue; no real provider transport is installed in P9."""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import re
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import User
from apps.accounts.access import AccessError
from apps.common.transactions import business_write, retry_transient_write
from .inputs import current_fingerprint, STAFF_FEATURES, source_ids
from .ledger import cost, settle
from .models import AIRequest, AIResult, AIUsageAttempt, AIBudgetMonth
from .services import authorize, test_mode


@dataclass(frozen=True)
class ProviderResponse:
    payload: dict
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    provider_request_id: str = ""


class NotPerformed(Exception):
    """Adapter guarantees the provider did not execute/bill this attempt."""


class ProviderFailed(Exception):
    def __init__(self, response=None): self.response = response


class OutcomeUnknown(Exception): pass


def authorized_for_work(request):
    actor = User.objects.get(pk=request.actor_id)
    if actor.session_version != request.actor_session_version: return False
    try: authorize(request, actor)
    except AccessError: return False
    return True


@retry_transient_write
def reap(*, now=None):
    now = now or timezone.now(); changed = 0
    with business_write():
        for request in AIRequest.objects.select_for_update().filter(status__in=["RESERVED","RUNNING","UNKNOWN"]).order_by("created_at"):
            if request.status == "RESERVED" and request.created_at <= now-timedelta(minutes=15):
                settle(request, "FAILED", "AI_QUEUE_EXPIRED", now=now); changed += 1
            elif request.status == "RUNNING" and request.lease_expires_at <= now:
                request.status = "UNKNOWN"; request.error_code = "AI_OUTCOME_UNKNOWN"; request.save()
                request.attempts.filter(sequence=request.attempt_count).update(status="UNKNOWN")
                changed += 1
            if request.status == "UNKNOWN" and request.unknown_until <= now:
                attempt = request.attempts.select_for_update().get(sequence=request.attempt_count)
                attempt.accounted_cost = attempt.estimated_cost; attempt.finished_at = now; attempt.save()
                settle(request, "FAILED", "AI_OUTCOME_UNKNOWN", now=now); changed += 1
    return changed


@retry_transient_write
def claim(*, now=None):
    if not test_mode(): return None
    now = now or timezone.now()
    with business_write():
        if AIRequest.objects.filter(status__in=["RUNNING","UNKNOWN"]).count() >= 2: return None
        request = AIRequest.objects.select_for_update().filter(status="RESERVED", is_test=True).order_by("created_at","pk").first()
        if not request: return None
        if not authorized_for_work(request) or not request.input_payload:
            settle(request, "CANCELLED", "AI_ACCESS_REVOKED", now=now)
            return None
        request.status = "RUNNING"; request.lease_token = uuid4(); request.started_at = now
        request.lease_expires_at = now+timedelta(seconds=120); request.unknown_until = now+timedelta(minutes=10); request.attempt_count += 1; request.save()
        AIUsageAttempt.objects.create(request=request, sequence=request.attempt_count, estimated_cost=request.reserved_cost, pricing_version=request.pricing_version)
        return request


def validate_payload(request, response):
    payload = response.payload
    if not isinstance(payload, dict) or set(payload) != {"feature","text","source_ids","is_test"}: return False
    if payload["feature"] != request.feature or payload["is_test"] is not True: return False
    if not isinstance(payload["text"], str) or not 1 <= len(payload["text"].encode()) <= request.output_tokens_cap*4: return False
    ids = payload["source_ids"]
    if not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(value,str) for value in ids): return False
    if not set(ids) <= source_ids(request.result): return False
    return all(type(v) is int and 0 <= v <= cap for v,cap in [(response.input_tokens,request.input_tokens_cap),(response.output_tokens,request.output_tokens_cap),(response.reasoning_tokens,request.reasoning_tokens_cap)])


def record_usage(request, attempt, response, status, now):
    values = [response.input_tokens, response.output_tokens, response.reasoning_tokens]
    if any(type(v) is not int or not 0 <= v < 2**31 for v in values): return False
    attempt.input_tokens, attempt.output_tokens, attempt.reasoning_tokens = values
    attempt.actual_cost = cost(*values, request.input_price, request.output_price)
    attempt.accounted_cost = max(attempt.accounted_cost, attempt.actual_cost)
    provider_id = str(response.provider_request_id)
    attempt.provider_request_id = provider_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", provider_id) and not (settings.AI_CONFIG.api_key and settings.AI_CONFIG.api_key in provider_id) else ""
    attempt.status = status; attempt.finished_at = now; attempt.save()
    return True


@retry_transient_write
def finish(task_id, token, *, response=None, outcome="success", now=None):
    now = now or timezone.now()
    with business_write():
        request = AIRequest.objects.select_for_update().get(pk=task_id)
        if request.lease_token != token: return False
        attempt = request.attempts.select_for_update().get(sequence=request.attempt_count)
        if request.settled:
            if response is not None and request.status != "SUCCEEDED":
                previous = attempt.accounted_cost
                if record_usage(request, attempt, response, "FAILED", now):
                    difference = attempt.accounted_cost-previous
                    if difference:
                        budget = AIBudgetMonth.objects.select_for_update().get(pk=request.budget_month_id)
                        budget.charged_usd += difference; budget.save()
                        request.charged_cost += difference; request.save()
            return False
        if request.status not in ["RUNNING","UNKNOWN"]: return False
        if now >= request.unknown_until:
            attempt.accounted_cost = attempt.estimated_cost; attempt.status = "UNKNOWN"; attempt.finished_at = now; attempt.save()
            settle(request, "FAILED", "AI_OUTCOME_UNKNOWN", now=now)
            return False
        if outcome == "unknown":
            request.status = "UNKNOWN"; request.error_code = "AI_OUTCOME_UNKNOWN"; request.save()
            attempt.status = "UNKNOWN"; attempt.save()
            return False
        if outcome == "not_performed":
            attempt.status = "NOT_SENT"; attempt.actual_cost = 0; attempt.accounted_cost = 0; attempt.finished_at = now; attempt.save()
            if request.attempt_count < 2 and authorized_for_work(request):
                request.status = "RESERVED"; request.lease_token = None; request.lease_expires_at = None; request.save()
            else: settle(request, "FAILED", "AI_PROVIDER_FAILED", now=now)
            return False
        valid_usage = response is not None and record_usage(request, attempt, response, "SUCCEEDED" if outcome == "success" else "FAILED", now)
        if not valid_usage:
            attempt.accounted_cost = attempt.estimated_cost; attempt.status = "FAILED"; attempt.finished_at = now; attempt.save()
        if not authorized_for_work(request):
            settle(request, "CANCELLED", "AI_ACCESS_REVOKED", now=now); return False
        if outcome != "success" or not valid_usage or not validate_payload(request, response):
            settle(request, "FAILED", "AI_PROVIDER_FAILED", now=now); return False
        result = AIResult.objects.select_for_update().get(request=request)
        result.payload = response.payload; result.valid = True; result.invalidation_reason = ""; result.generated_at = now
        try: result.stale = current_fingerprint(request) != request.source_fingerprint
        except AccessError: result.stale = True
        result.save()
        settle(request, "SUCCEEDED", now=now)
        return True


def run_once(adapter=None):
    reap()
    task = claim()
    if not task: return {"processed": 0, "succeeded": 0}
    if transaction.get_connection().in_atomic_block:
        raise RuntimeError("AI I/O must run outside database transactions")
    if adapter is None:
        from .adapters import FoundationFakeAdapter
        adapter = FoundationFakeAdapter()
    try:
        response = adapter.execute_task(task, task.input_payload)
    except NotPerformed:
        succeeded = finish(task.pk, task.lease_token, outcome="not_performed")
    except ProviderFailed as error:
        succeeded = finish(task.pk, task.lease_token, response=error.response, outcome="failed")
    except Exception:
        # Transport/timeout details and potentially sensitive response text never enter logs.
        succeeded = finish(task.pk, task.lease_token, outcome="unknown")
    else:
        succeeded = finish(task.pk, task.lease_token, response=response)
    return {"processed": 1, "succeeded": int(succeeded)}
