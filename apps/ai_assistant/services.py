import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.common.http import identifier
from apps.common.transactions import business_write, retry_transient_write
from apps.customers.access import current_access
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.sites.models import Site
from apps.sites.services import locked_actor
from .inputs import STAFF_FEATURES, build, digest
from .ledger import cost
from .models import AIRequest, AIRequestKey, AIResult, AIResultSource, AIQuotaBucket, AIBudgetMonth, AIReportSlot, Feature

ACTIVE = ["RESERVED", "RUNNING", "UNKNOWN"]


def failure(code, message, status=409): raise AccessError(code, message, status)


def test_mode():
    from django.db import connection
    return bool(settings.TESTING and getattr(settings, "AI_FOUNDATION_TEST_MODE", False) and connection.settings_dict["NAME"].startswith("test_tm_"))


def validate_config():
    config = settings.AI_CONFIG
    if test_mode():
        if config.input_price is None or config.output_price is None: failure("AI_NOT_CONFIGURED", "테스트 단가가 필요합니다.")
    elif not config.enabled or not config.configured:
        failure("AI_NOT_CONFIGURED", "AI 설정을 확인해 주세요.")
    else:
        # No real adapter is connected before explicit paid-call authorization.
        failure("AI_NOT_CONFIGURED", "실제 공급자 어댑터가 아직 연결되지 않았습니다.")
    for value in [config.input_price, config.output_price, config.monthly_budget_usd]:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            failure("AI_NOT_CONFIGURED", "AI 단가·예산을 확인해 주세요.")
    return config


def authorize(request, actor):
    if not actor.is_active or actor.must_change_password:
        failure("FORBIDDEN", "현재 계정으로 조회할 수 없습니다.", 403)
    if request.feature in STAFF_FEATURES:
        if actor.pk != request.actor_id or actor.role != User.Role.EMPLOYEE or not request.customer_id:
            failure("FORBIDDEN", "현재 담당 고객의 본인 결과만 조회할 수 있습니다.", 403)
        current_access(actor, request.customer, request.assignment_id)
    elif actor.role != User.Role.ADMIN:
        failure("FORBIDDEN", "관리자 결과입니다.", 403)


@retry_transient_write
def reserve(actor, body):
    """Server service only in P9. Generation buttons/routes arrive in P10/P11."""
    if not isinstance(body, dict): failure("VALIDATION_ERROR", "요청 형식을 확인해 주세요.", 422)
    feature = body.get("feature")
    if feature not in Feature.values: failure("VALIDATION_ERROR", "기능을 확인해 주세요.", 422)
    expected = {"feature", "idempotency_key"}
    if feature in STAFF_FEATURES: expected |= {"customer_id", "assignment_id", "expected_version"}
    elif feature == Feature.EMPLOYEE_COACHING: expected.add("employee_id")
    elif feature == Feature.TEAM_GUIDE: expected.add("site_id")
    if set(body) != expected: failure("VALIDATION_ERROR", "서버가 지정한 입력만 사용할 수 있습니다.", 422)
    key = identifier(body["idempotency_key"])
    body_hash = digest(body)
    now = timezone.now(); day = timezone.localtime(now, KST).date()
    with business_write():
        actor = locked_actor(actor, admin=feature not in STAFF_FEATURES)
        customer = site = employee = None
        if feature in STAFF_FEATURES:
            if actor.role != User.Role.EMPLOYEE: failure("FORBIDDEN", "직원 기능입니다.", 403)
            cid, aid = identifier(body["customer_id"]), identifier(body["assignment_id"])
            if type(body["expected_version"]) is not int or body["expected_version"] < 1: failure("VALIDATION_ERROR", "버전을 확인해 주세요.", 422)
            metadata = Customer.objects.filter(pk=cid).values("site_id").first()
            if metadata: Site.objects.select_for_update().get(pk=metadata["site_id"])
            customer = Customer.objects.select_for_update(of=("self",)).select_related("current_assignment").filter(pk=cid).first()
            if not customer: failure("FORBIDDEN", "현재 담당 고객정보만 사용할 수 있습니다.", 403)
            current_access(actor, customer, aid)
            site = customer.site
        elif feature == Feature.EMPLOYEE_COACHING:
            employee = User.objects.filter(pk=identifier(body["employee_id"]), role=User.Role.EMPLOYEE).first()
            if not employee: failure("FORBIDDEN", "직원 대상을 확인해 주세요.", 403)
        elif feature == Feature.TEAM_GUIDE:
            site = Site.objects.filter(pk=identifier(body["site_id"])).first()
            if not site: failure("SITE_DELETED", "현장이 존재하지 않습니다.")
        receipt = AIRequestKey.objects.filter(actor=actor,key=key).select_related("request").first()
        existing = receipt.request if receipt else AIRequest.objects.filter(actor=actor, idempotency_key=key).first()
        if existing:
            if (receipt.body_hash if receipt else existing.body_hash) != body_hash: failure("IDEMPOTENCY_CONFLICT", "같은 요청 키의 내용이 다릅니다.")
            authorize(existing, actor)
            return existing, False
        if feature == Feature.WEEKLY_BRIEFING and day.weekday() != 6: failure("AI_SUNDAY_ONLY", "주간 브리핑은 일요일에 접수할 수 있습니다.")
        if customer and customer.version != body["expected_version"]: failure("VERSION_CONFLICT", "상담정보를 다시 확인해 주세요.")
        start = datetime.combine(day, time.min, KST) if customer else now-timedelta(days=30)
        scope = str(customer.pk if customer else employee.pk if employee else site.pk if site else "GLOBAL")
        period = day.isoformat()
        if feature == Feature.WEEKLY_BRIEFING:
            monday = day-timedelta(days=day.weekday()); start = datetime.combine(monday, time.min, KST); period = monday.isoformat()
        slot = None
        if feature not in STAFF_FEATURES:
            slot, _ = AIReportSlot.objects.get_or_create(feature=feature, scope_key=scope, period_key=period)
            slot = AIReportSlot.objects.select_for_update().get(pk=slot.pk)
            if slot.success_result_id or slot.current_request_id:
                shared = slot.success_result.request if slot.success_result_id else slot.current_request
                AIRequestKey.objects.create(actor=actor,key=key,body_hash=body_hash,request=shared)
                return shared, False
        payload, sources = build(feature, customer=customer, site=site, employee=employee, start=start, end=now, korean_date=day)
        config = validate_config()
        input_cap, output_cap = (4000, 800) if customer else (12000, 2000)
        # UTF-8 byte count is a conservative test-stage input bound, not a provider tokenizer.
        if len(json.dumps(payload, ensure_ascii=False).encode()) > input_cap: failure("AI_INPUT_TOO_LARGE", "분석 입력 상한을 넘었습니다.", 422)
        model_version = config.model or "test-foundation-v1"
        pricing = digest([config.provider, model_version, str(config.input_price), str(config.output_price), "output-plus-reasoning-v1"])
        fingerprint = digest(payload)
        cache = digest([feature, str(actor.pk) if customer else scope, str(customer.current_assignment_id) if customer else None,
                        customer.version if customer else None, day.isoformat(), start.isoformat(), period, fingerprint, "foundation-v1", model_version, pricing])
        cached = AIRequest.objects.filter(cache_key=cache, status="SUCCEEDED", result__valid=True).first()
        if cached:
            AIRequestKey.objects.create(actor=actor,key=key,body_hash=body_hash,request=cached)
            return cached, False
        if AIRequest.objects.filter(actor=actor, status__in=ACTIVE).exists(): failure("AI_BUSY", "이미 처리 중인 AI 작업이 있습니다.")
        bucket = None
        if customer:
            bucket, _ = AIQuotaBucket.objects.get_or_create(user=actor, korean_date=day)
            bucket = AIQuotaBucket.objects.select_for_update().get(pk=bucket.pk)
            if bucket.successful_count + bucket.reserved_count >= 30: failure("AI_DAILY_LIMIT", "하루 합산 30회 한도입니다.")
        month, _ = AIBudgetMonth.objects.get_or_create(month=day.replace(day=1))
        month = AIBudgetMonth.objects.select_for_update().get(pk=month.pk)
        reserved = cost(input_cap, output_cap, output_cap, config.input_price, config.output_price)
        if month.charged_usd + month.reserved_usd + reserved > config.monthly_budget_usd: failure("AI_BUDGET_LIMIT", "조직 월 AI 예산을 사용할 수 없습니다.")
        month.reserved_usd += reserved; month.save(update_fields=["reserved_usd", "updated_at"])
        if bucket:
            bucket.reserved_count += 1; bucket.save(update_fields=["reserved_count", "updated_at"])
        task = AIRequest.objects.create(actor=actor, actor_session_version=actor.session_version, feature=feature, customer=customer, assignment=customer.current_assignment if customer else None,
            employee=employee, site=site, customer_version=customer.version if customer else None, korean_date=day, period_start=start, period_end=now,
            scope_key=scope, period_key=period, idempotency_key=key, body_hash=body_hash, cache_key=cache, source_fingerprint=fingerprint, input_payload=payload,
            provider=config.provider or "test-only", model_version=model_version, pricing_version=pricing, input_price=config.input_price, output_price=config.output_price,
            input_tokens_cap=input_cap, output_tokens_cap=output_cap, reasoning_tokens_cap=output_cap, budget_month=month, quota_bucket=bucket, reserved_cost=reserved, is_test=test_mode())
        result = AIResult.objects.create(request=task)
        AIRequestKey.objects.create(actor=actor,key=key,body_hash=body_hash,request=task)
        AIResultSource.objects.bulk_create([AIResultSource(result=result, **source) for source in sources])
        if slot:
            slot.current_request = task; slot.save(update_fields=["current_request", "updated_at"])
        return task, True
