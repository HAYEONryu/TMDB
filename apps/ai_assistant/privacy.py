from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.utils import timezone
from .models import AIRequest, AIRequestKey, AIResult, AIResultSource, AIQuotaBucket, AIBudgetMonth, AIUsageAttempt, AIReportSlot, SiteKnowledge, AIReportSnapshot, AINoteClassification, GuidePublication
from .ledger import settle
from .models import AIProviderQuota, AIProviderQuotaDay, AIProviderDispatch, AITestBudget


def invalidate_results(result_ids, *, reason="SOURCE_DELETED"):
    visited = set(); frontier = set(result_ids)
    while frontier:
        fresh = frontier-visited
        if not fresh: break
        visited |= fresh
        frontier = set(AIResultSource.objects.filter(Q(previous_result_id__in=fresh)|Q(revision__source_ai_result_id__in=fresh)).values_list("result_id",flat=True))-visited
    now = timezone.now()
    for result in AIResult.objects.select_for_update().filter(pk__in=visited).select_related("request").order_by("pk"):
        request = AIRequest.objects.select_for_update().get(pk=result.request_id)
        if not request.settled:
            if request.status in ["RUNNING","UNKNOWN"]:
                attempt = request.attempts.select_for_update().filter(sequence=request.attempt_count).first()
                if attempt:
                    attempt.status = "UNKNOWN"; attempt.accounted_cost = attempt.estimated_cost; attempt.finished_at = now; attempt.save()
            settle(request, "CANCELLED", "AI_SOURCE_DELETED", now=now)
        request.input_payload = {}; request.cache_key = ""; request.source_fingerprint = ""; request.save()
        AIReportSnapshot.objects.filter(request=request).update(data={})
        GuidePublication.objects.filter(result=result).delete()
        result.guide_body = ""
        result.payload = {}; result.valid = False; result.stale = True; result.invalidated_at = now; result.invalidation_reason = reason
        result.guide_status = "DRAFT"; result.published_at = None; result.save()
    AIResultSource.objects.filter(result_id__in=visited).delete()
    return visited


def erase_sources(customer_ids,*,site_id=None):
    # Provider ledgers contain only project hashes, counts, times and token totals.
    # Retain them so erasing customer material cannot reset shared rate limits.
    handled = {AIRequest,AIRequestKey,AIResult,AIResultSource,AIQuotaBucket,AIBudgetMonth,AIUsageAttempt,AIReportSlot,SiteKnowledge,AIReportSnapshot,AINoteClassification,GuidePublication,AIProviderQuota,AIProviderQuotaDay,AIProviderDispatch,AITestBudget}
    if set(apps.get_app_config('ai_assistant').get_models())-handled:
        raise ImproperlyConfigured('AI_PRIVACY_HANDLER_REQUIRED')
    query = Q(customer_id__in=customer_ids)|Q(revision__customer_id__in=customer_ids)
    targets = Q(request__customer_id__in=customer_ids)
    if site_id:
        query |= Q(knowledge__site_id=site_id)|Q(customer__site_id=site_id)|Q(revision__customer__site_id=site_id)
        targets |= Q(request__site_id=site_id)
    ids = set(AIResultSource.objects.filter(query).values_list("result_id",flat=True))|set(AIResult.objects.filter(targets).values_list("pk",flat=True))
    return invalidate_results(ids)
