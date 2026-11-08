from django.http import JsonResponse
from django.views.decorators.http import require_GET,require_POST
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
from .services import authorize,reserve,test_mode,validate_config,reservation_cost
from .inputs import STAFF_FEATURES
from . import free_limits


@require_GET
@require_role()
@api_errors
def availability(request):
    # Explicit allowlist: never serialize the config object or environment.
    from apps.customers.employee import optional_queue_identity
    optional_queue_identity(request)
    now = timezone.now()
    day = timezone.localtime(now, KST).date()
    bucket = AIQuotaBucket.objects.filter(user=request.user, korean_date=day).first()
    staff = request.user.role == "EMPLOYEE"
    successful = bucket.successful_count if bucket else 0
    reserved = bucket.reserved_count if bucket else 0
    active=AIRequest.objects.filter(actor=request.user,status__in=['RESERVED','RUNNING','UNKNOWN']).exists()
    enabled=False
    try:
        validate_config()
        from .provider_policy import reasoning_supported
        enabled=test_mode() or reasoning_supported(settings.AI_CONFIG, staff)
    except AccessError:pass
    budget_blocked=False
    test_budget_blocked=False
    free = free_limits.is_free(settings.AI_CONFIG)
    server = free_limits.snapshot(settings.AI_CONFIG, now)
    if enabled and not free:
        budget=AIBudgetMonth.objects.filter(month=day.replace(day=1)).first()
        budget_blocked=(budget.charged_usd+budget.reserved_usd if budget else 0)+reservation_cost(staff, settings.AI_CONFIG)>settings.AI_CONFIG.monthly_budget_usd
    if enabled and settings.AI_CONFIG.test_budget_usd is not None:
        from .models import AITestBudget
        test_budget=AITestBudget.objects.filter(scope_key=settings.AI_CONFIG.test_budget_scope).first()
        test_budget_blocked=(test_budget.charged_usd+test_budget.reserved_usd if test_budget else 0)+reservation_cost(staff,settings.AI_CONFIG)>settings.AI_CONFIG.test_budget_usd
    reason=('AI_TEST_ONLY' if test_mode() else 'AI_READY') if enabled else 'AI_NOT_CONFIGURED'
    server_blocked = bool(enabled and server and (server['remaining_count'] == 0 or server['cooldown_until']))
    personal_blocked = staff and successful+reserved >= free_limits.STAFF_DAILY_LIMIT
    if server_blocked:reason='AI_SERVER_DAILY_LIMIT' if server['remaining_count'] == 0 else 'AI_SERVER_COOLDOWN'
    elif test_budget_blocked:reason='AI_TEST_BUDGET_LIMIT'
    elif enabled and personal_blocked:reason='AI_DAILY_LIMIT'
    elif enabled and active:reason='AI_BUSY'
    elif budget_blocked:reason='AI_BUDGET_LIMIT'
    if server_blocked:
        message=('공용 AI 사용 한도 소진 · 개인 잔여 횟수가 있어도 새 생성은 중단합니다. 기존 결과는 조회할 수 있습니다.'
                 if server['remaining_count'] == 0 else '공급자 분당 한도로 공용 AI가 대기 중입니다. 기존 결과와 고객관리는 계속 사용할 수 있습니다.')
    elif test_budget_blocked:
        message='테스트 누적 AI 예산이 부족합니다. 기존 결과와 고객관리는 계속 사용할 수 있습니다.'
    elif budget_blocked:
        message='조직 AI 예산이 부족합니다. 기존 결과와 고객관리는 계속 사용할 수 있습니다.'
    elif enabled:
        message='테스트 전용 AI입니다. 운영 결과가 아닙니다.' if test_mode() else '무료 AI · 서버 전체 한도를 먼저 적용하며 분당 한도에 맞춰 대기 후 처리합니다.' if free else 'AI 생성은 유료입니다. 생성 버튼을 누를 때만 요청합니다.'
    else:
        message='AI 설정 또는 공급자 연결이 없어 생성할 수 없습니다. 기존 고객관리는 정상 작동합니다.'
    return JsonResponse({"generation_available": enabled and not personal_blocked and not active and not budget_blocked and not test_budget_blocked and not server_blocked, "configured": settings.AI_CONFIG.configured,
                         "reason": reason,
                         "message": message, "server_limit": server, "usage_tier": settings.AI_CONFIG.usage_tier,
                         "daily_limit": free_limits.STAFF_DAILY_LIMIT if staff else None,
                         "successful_count": successful if staff else None, "reserved_count": reserved if staff else None,
                         "remaining_count": max(0, free_limits.STAFF_DAILY_LIMIT-successful-reserved) if staff else None,
                         "korean_date": day.isoformat(), "features": [feature for feature in Feature.values if (feature in STAFF_FEATURES) == staff], 'is_test':test_mode(), 'active':active,
                         "weekly_generation_day": day.weekday()==6,
                         "next_available_at": server['cooldown_until'] or server['reset_at'] if server_blocked else datetime.combine(day+timedelta(days=1),time.min,KST).isoformat() if personal_blocked else None})


def task_payload(task):
    result = task.result
    data = {"id": str(task.pk), "feature": task.feature, "status": task.status, "error_code": task.error_code,
            "created_at": task.created_at.isoformat(), "korean_date": task.korean_date.isoformat(),
            'customer_id':str(task.customer_id) if task.customer_id else None,'assignment_id':str(task.assignment_id) if task.assignment_id else None,
            'unknown_until':task.unknown_until.isoformat() if task.unknown_until else None,
            "is_test": task.is_test, "test_message": "테스트 전용 결과이며 운영 분석이 아닙니다." if task.is_test else "",
            "wait_until": task.dispatch_after.isoformat() if task.dispatch_after else None,
            "result_id": str(result.pk) if task.status == "SUCCEEDED" else None}
    if result.invalidation_reason in {"SOURCE_DELETED","SOURCE_CHANGED"}:
        data["message"] = "원본 삭제 또는 변경으로 결과를 더 이상 제공할 수 없습니다."
    elif task.status == "RESERVED":
        data["message"] = "분당 요청·입력 토큰 한도에 맞춰 대기 중입니다. 화면을 닫아도 서버에서 순서대로 처리합니다." if task.dispatch_after else "AI 작업을 접수했습니다. 서버 한도에 맞춰 처리합니다."
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
                 "generated_at": result.generated_at.isoformat() if result.generated_at else None, "schema_version": task.schema_version,
                 'source_ids':sorted({str(s.customer_id or s.revision_id or s.knowledge_id or s.previous_result_id) for s in result.sources.all()}),
                 'customer_name':task.customer.customer_name if task.customer_id else None})
    if task.feature not in STAFF_FEATURES and not unavailable:
        from .admin_views import guide_data
        data.update({"task_identifier":str(task.pk),"period_start":timezone.localtime(task.period_start,KST).isoformat(),"period_end":timezone.localtime(task.period_end,KST).isoformat(),"period_key":task.period_key,
                     "cutoff_message":"일요일 업무는 집계 시각까지 포함" if task.feature==Feature.WEEKLY_BRIEFING else "접수 시각 기준 최근 30일",
                     "slot_message":"이번 주 생성 1회 사용" if task.feature==Feature.WEEKLY_BRIEFING else "대상별 하루 생성 1회 사용",
                     "guide":guide_data(result) if task.feature==Feature.TEAM_GUIDE else None})
        actor_ids=[r["actor_id"] for r in result.payload.get("statistics",{}).get("employees",[])]
        actor_ids += [r["actor_id"] for r in result.payload.get("statistics",{}).get("operations",[]) if r["actor_id"]]
        data["actors"]={str(u.pk):{"name":u.name,"active":u.is_active,"role":u.role} for u in User.objects.filter(pk__in=actor_ids)}
        links=[]
        for source in result.sources.select_related("revision"):
            cid=source.customer_id or (source.revision.customer_id if source.revision_id else None)
            if cid:links.append({"source_id":str(source.customer_id or source.revision_id),"url":"/app/admin/ai/cases/"+str(cid)})
        data["case_links"]=links[:200]
    return JsonResponse(data)


@require_POST
@require_role(User.Role.EMPLOYEE)
@api_errors
def customer_task(request):
    from apps.customers.employee import queue_identity
    queue_identity(request); body=json_object(request)
    if not isinstance(body.get('feature'),str) or body.get('feature') not in STAFF_FEATURES:raise AccessError('VALIDATION_ERROR','직원 기능을 확인해 주세요.',422)
    task,new=reserve(request.user,body)
    data=task_payload(task);data['task_id']=str(task.pk);data['cached']=not new
    return JsonResponse(data,status=202 if task.status in ['RESERVED','RUNNING','UNKNOWN'] else 200)


@require_GET
@require_role(User.Role.EMPLOYEE)
@api_errors
def customer_results(request):
    from apps.customers.employee import queue_identity
    from apps.customers.access import current_access
    from apps.customers.models import Customer
    from apps.common.http import identifier
    queue_identity(request)
    if set(request.GET)!={'customer_id','assignment_id'}:raise AccessError('VALIDATION_ERROR','고객/할당을 확인해 주세요.',422)
    customer=Customer.objects.select_related('current_assignment').filter(pk=identifier(request.GET['customer_id'])).first()
    if not customer:raise AccessError('FORBIDDEN','현재 담당 고객만 조회할 수 있습니다.',403)
    current_access(request.user,customer,identifier(request.GET['assignment_id']))
    tasks=AIRequest.objects.filter(actor=request.user,actor_session_version=request.user.session_version,customer=customer,assignment_id=customer.current_assignment_id,feature__in=STAFF_FEATURES,status='SUCCEEDED').select_related('result').order_by('-created_at','-pk')[:10]
    return JsonResponse({'items':[task_payload(task) for task in tasks],'limit':10})


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
    from .models import AITestBudget
    test_budget = AITestBudget.objects.filter(scope_key=settings.AI_CONFIG.test_budget_scope).first() if settings.AI_CONFIG.test_budget_scope else None
    sent = AIUsageAttempt.objects.filter(request__budget_month__month=month,transport_started_at__isnull=False)
    return JsonResponse({"month": month.isoformat(), "currency": "USD", "features": features, "attempts": attempts,
                         "transport_started_count": sent.count(), "retry_started_count": sent.filter(sequence__gt=1).count(),
                         "reserved_usd": str(budget.reserved_usd) if budget else "0", "charged_usd": str(budget.charged_usd) if budget else "0",
                         "budget_usd": str(settings.AI_CONFIG.monthly_budget_usd), "is_absolute_billing_cap": False,
                         "test_budget": {"limit_usd": str(settings.AI_CONFIG.test_budget_usd),
                                         "reserved_usd": str(test_budget.reserved_usd) if test_budget else "0",
                                         "charged_usd": str(test_budget.charged_usd) if test_budget else "0"} if settings.AI_CONFIG.test_budget_usd is not None else None})


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
