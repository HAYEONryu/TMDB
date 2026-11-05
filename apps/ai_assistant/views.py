from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.conf import settings
from apps.accounts.access import require_role
from django.utils import timezone
from datetime import timedelta, datetime, time, date
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Sum, Q
from apps.accounts.access import AccessError, actor_identity
from apps.accounts.models import User
from apps.common.http import api_errors, json_object
from apps.common.transactions import business_write
from apps.customers.queries import KST
from apps.sites.models import Site
from apps.sites.services import locked_actor
from .models import AIRequest, AIResult, AIQuotaBucket, AIUsageAttempt, AIBudgetMonth, SiteKnowledge, AIResultSource, Feature
from .services import authorize
from .inputs import STAFF_FEATURES


@require_GET
@require_role()
def availability(request):
    # Explicit allowlist: never serialize the config object or environment.
    day = timezone.localdate()
    bucket = AIQuotaBucket.objects.filter(user=request.user, korean_date=day).first()
    staff = request.user.role == "EMPLOYEE"
    successful = bucket.successful_count if bucket else 0
    reserved = bucket.reserved_count if bucket else 0
    return JsonResponse({"generation_available": False, "configured": settings.AI_CONFIG.configured,
                         "reason": settings.AI_CONFIG.reason,
                         "message": "AI 상담 도구를 아직 사용할 수 없습니다.",
                         "daily_limit": 30 if request.user.role == "EMPLOYEE" else None,
                         "successful_count": successful if staff else None, "reserved_count": reserved if staff else None,
                         "remaining_count": max(0, 30-successful-reserved) if staff else None,
                         "korean_date": day.isoformat(), "features": [feature for feature in Feature.values if (feature in STAFF_FEATURES) == staff],
                         "next_available_at": datetime.combine(day+timedelta(days=1),time.min,KST).isoformat() if staff and successful+reserved >= 30 else None})


def task_payload(task):
    result = task.result
    data = {"id": str(task.pk), "feature": task.feature, "status": task.status, "error_code": task.error_code,
            "created_at": task.created_at.isoformat(), "korean_date": task.korean_date.isoformat(),
            "is_test": task.is_test, "test_message": "테스트 전용 결과이며 운영 분석이 아닙니다." if task.is_test else "",
            "result_id": str(result.pk) if task.status == "SUCCEEDED" else None}
    if result.invalidation_reason in {"SOURCE_DELETED","SOURCE_CHANGED"}:
        data["message"] = "원본 삭제 또는 변경으로 결과를 더 이상 제공할 수 없습니다."
    return data


@require_GET
@require_role()
@api_errors
def task_detail(request, task_id):
    actor_identity(request)
    task = AIRequest.objects.select_related("customer__current_assignment", "result").filter(pk=task_id).first()
    if not task: raise AccessError("NOT_FOUND", "작업이 없습니다.", 404)
    authorize(task, request.user)
    return JsonResponse(task_payload(task))


@require_GET
@require_role()
@api_errors
def result_detail(request, result_id):
    actor_identity(request)
    result = AIResult.objects.select_related("request__customer__current_assignment").filter(pk=result_id).first()
    if not result: raise AccessError("NOT_FOUND", "결과가 없습니다.", 404)
    task = result.request; authorize(task, request.user)
    data = task_payload(task)
    unavailable = not result.valid or task.status != "SUCCEEDED"
    stale = result.stale or bool(task.customer_id and task.customer.version != task.customer_version)
    data.update({"id": str(result.pk), "available": not unavailable, "stale": stale,
                 "payload": result.payload if not unavailable else {}, "source_customer_version": task.customer_version,
                 "generated_at": result.generated_at.isoformat() if result.generated_at else None, "schema_version": task.schema_version})
    return JsonResponse(data)


@require_GET
@require_role(User.Role.ADMIN)
@api_errors
def usage(request):
    actor_identity(request)
    if set(request.GET)-{"month"}: raise AccessError("VALIDATION_ERROR", "월을 확인해 주세요.", 422)
    try: month = date.fromisoformat(request.GET["month"]) if "month" in request.GET else timezone.localdate().replace(day=1)
    except ValueError: raise AccessError("VALIDATION_ERROR", "월을 확인해 주세요.", 422)
    if month.day != 1: raise AccessError("VALIDATION_ERROR", "월의 첫 날짜를 보내 주세요.", 422)
    tasks = AIRequest.objects.filter(budget_month__month=month)
    features = list(tasks.values("feature").annotate(request_count=Count("id"), successful_count=Count("id",filter=Q(status="SUCCEEDED")),
                    pending_count=Count("id",filter=Q(status__in=["RESERVED","RUNNING","UNKNOWN"])), failed_count=Count("id",filter=Q(status="FAILED")),
                    cancelled_count=Count("id",filter=Q(status="CANCELLED")), unknown_count=Count("id",filter=Q(status="UNKNOWN")), charged_usd=Sum("charged_cost")).order_by("feature"))
    attempts = AIUsageAttempt.objects.filter(request__in=tasks).aggregate(attempts=Count("id"), input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"), reasoning_tokens=Sum("reasoning_tokens"), actual_cost=Sum("actual_cost"), accounted_cost=Sum("accounted_cost"))
    budget = AIBudgetMonth.objects.filter(month=month).first()
    return JsonResponse({"month": month.isoformat(), "currency": "USD", "features": features, "attempts": attempts,
                         "reserved_usd": str(budget.reserved_usd) if budget else "0", "charged_usd": str(budget.charged_usd) if budget else "0",
                         "budget_usd": str(settings.AI_CONFIG.monthly_budget_usd), "is_absolute_billing_cap": False})


def knowledge_payload(row):
    return {"id": str(row.pk), "site_id": str(row.site_id), "title": row.title, "body": row.body, "version": row.version,
            "is_valid": row.is_valid, "reviewed_by": str(row.reviewed_by_id) if row.reviewed_by_id else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None}


def knowledge_values(body, update=False):
    expected = {"title","body","reviewed","is_valid"}|({"expected_version"} if update else set())
    if set(body) != expected or not isinstance(body["title"],str) or not 1 <= len(body["title"].strip()) <= 100 or not isinstance(body["body"],str) or not 1 <= len(body["body"]) <= 20000 or type(body["reviewed"]) is not bool or type(body["is_valid"]) is not bool:
        raise AccessError("VALIDATION_ERROR", "안내자료 형식을 확인해 주세요.", 422)
    if body["is_valid"] and not body["reviewed"]: raise AccessError("VALIDATION_ERROR", "유효 자료는 관리자 검토가 필요합니다.", 422)
    if update and (type(body["expected_version"]) is not int or body["expected_version"] < 1): raise AccessError("VALIDATION_ERROR", "버전을 확인해 주세요.", 422)


@require_http_methods(["GET","POST"])
@require_role(User.Role.ADMIN)
@api_errors
def knowledge_list(request, site_id):
    actor_identity(request)
    if request.method == "GET":
        try: page = int(request.GET.get("page", "1"))
        except ValueError: page = 0
        if set(request.GET)-{"page"} or not 1 <= page <= 1000000: raise AccessError("VALIDATION_ERROR", "페이지를 확인해 주세요.", 422)
        if not Site.objects.filter(pk=site_id).exists(): raise AccessError("SITE_DELETED", "현장이 없습니다.", 409)
        query = SiteKnowledge.objects.filter(site_id=site_id).order_by("-created_at","-pk")
        total = query.count()
        return JsonResponse({"items": [knowledge_payload(row) for row in query[(page-1)*100:page*100]], "limit": 100, "page": page, "total": total, "has_next": page*100 < total})
    body = json_object(request); knowledge_values(body)
    with business_write():
        actor = locked_actor(request.user, admin=True)
        site = Site.objects.select_for_update().filter(pk=site_id).first()
        if not site: raise AccessError("SITE_DELETED", "현장이 없습니다.", 409)
        row = SiteKnowledge.objects.create(site=site, title=body["title"].strip(), body=body["body"], is_valid=body["is_valid"],
                 reviewed_by=actor if body["reviewed"] else None, reviewed_at=timezone.now() if body["reviewed"] else None)
        return JsonResponse(knowledge_payload(row), status=201)


@require_http_methods(["PATCH"])
@require_role(User.Role.ADMIN)
@api_errors
def knowledge_update(request, site_id, knowledge_id):
    actor_identity(request); body = json_object(request); knowledge_values(body, update=True)
    with business_write():
        actor = locked_actor(request.user, admin=True)
        if not Site.objects.select_for_update().filter(pk=site_id).exists(): raise AccessError("SITE_DELETED", "현장이 없습니다.", 409)
        row = SiteKnowledge.objects.select_for_update().filter(site_id=site_id, pk=knowledge_id).first()
        if not row: raise AccessError("NOT_FOUND", "안내자료가 없습니다.", 404)
        if row.version != body["expected_version"]: raise AccessError("VERSION_CONFLICT", "최신 자료를 확인해 주세요.", 409)
        from .privacy import invalidate_results
        invalidate_results(AIResultSource.objects.filter(knowledge=row).values_list("result_id",flat=True), reason="SOURCE_CHANGED")
        row.title = body["title"].strip(); row.body = body["body"]; row.version += 1; row.is_valid = body["is_valid"]
        row.reviewed_by = actor if body["reviewed"] else None; row.reviewed_at = timezone.now() if body["reviewed"] else None; row.save()
        return JsonResponse(knowledge_payload(row))
