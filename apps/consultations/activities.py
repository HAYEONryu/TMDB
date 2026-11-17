"""Explicit employee call/actual-visit evidence, independent of customer state saves."""
from datetime import datetime, time
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods
from apps.accounts.access import AccessError, actor_identity, require_role
from apps.accounts.models import User
from apps.common.http import api_errors, identifier, json_object
from apps.common.transactions import business_write, retry_transient_write
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.customers.services import datetime_value, digest
from apps.sites.services import locked_actor
from .models import CustomerActivity, PerformanceTracking


def serialize(record):
    return {'id': str(record.pk), 'kind': record.kind,
            'occurred_at': record.occurred_at.astimezone(KST).isoformat() if record.occurred_at else None,
            'connection': record.connection, 'visited_on': record.visited_on.isoformat() if record.visited_on else None}


def owned_customer(actor, customer_id, site_id=None, assignment_id=None):
    customer = Customer.objects.select_related('current_assignment').filter(pk=customer_id).first()
    assignment = customer.current_assignment if customer else None
    if (not customer or customer.deleted_at or not assignment or assignment.ended_at or
            assignment.assigned_at > timezone.now() or assignment.employee_id != actor.pk or
            site_id is not None and customer.site_id != site_id or
            assignment_id is not None and assignment.pk != assignment_id):
        raise AccessError('ASSIGNMENT_CHANGED', '현재 본인 담당 고객만 기록할 수 있습니다. 담당 상태를 다시 확인해 주세요.', 403)
    return customer


@retry_transient_write
def record_activity(actor, customer_id, body):
    common = {'site_id', 'assignment_id', 'kind', 'idempotency_key'}
    kind = body.get('kind')
    fields = {'occurred_at', 'connection'} if kind == 'CALL' else {'visited_on'} if kind == 'VISIT' else None
    if fields is None or set(body) != common | fields:
        raise AccessError('VALIDATION_ERROR', '통화 또는 실제 방문 기록 형식을 확인해 주세요.', 422)
    key, site_id, assignment_id = (identifier(body[field]) for field in ('idempotency_key', 'site_id', 'assignment_id'))
    body_hash = digest({'customer_id': str(customer_id), **body})
    with business_write():
        actor = locked_actor(actor)
        if actor.role != User.Role.EMPLOYEE:
            raise AccessError('FORBIDDEN', '직원 본인의 실적만 기록할 수 있습니다.', 403)
        previous = CustomerActivity.objects.filter(actor=actor, idempotency_key=key).first()
        if previous:
            if previous.body_hash != body_hash:
                raise AccessError('IDEMPOTENCY_CONFLICT', '같은 기록 요청의 내용이 다릅니다.', 409)
            # Own immutable receipt remains available after recall/reassignment.
            return {'ok': True, 'record': serialize(previous)}, 200
        customer = owned_customer(actor, customer_id, site_id, assignment_id)
        start = PerformanceTracking.objects.filter(pk=1).values_list('started_at', flat=True).first()
        if start is None:
            raise AccessError('TRACKING_UNAVAILABLE', '실적 기록 시작일을 확인하지 못했습니다. 관리자에게 문의해 주세요.', 409)
        now = timezone.now()
        first_day = start.astimezone(KST).date()
        values = {}
        if kind == 'CALL':
            occurred_at = datetime_value(body['occurred_at'])
            if (occurred_at is None or occurred_at > now or
                    occurred_at < datetime.combine(first_day, time.min, KST)):
                raise AccessError('VALIDATION_ERROR', '통화 시각은 기록 도입일부터 현재 시각 사이로 입력해 주세요.', 422)
            if body['connection'] not in CustomerActivity.Connection.values:
                raise AccessError('VALIDATION_ERROR', '연결·미연결·확인 불가 중 하나를 선택해 주세요.', 422)
            values = {'occurred_at': occurred_at, 'connection': body['connection']}
        else:
            try:
                visited_on = parse_date(body['visited_on']) if isinstance(body['visited_on'], str) else None
            except ValueError:
                visited_on = None
            if visited_on is None or not first_day <= visited_on <= now.astimezone(KST).date():
                raise AccessError('VALIDATION_ERROR', '실제 방문일은 기록 도입일부터 오늘 사이로 입력해 주세요. 예약일은 사용하지 마세요.', 422)
            values = {'visited_on': visited_on}
        record = CustomerActivity.objects.create(customer=customer, site_id=site_id, actor=actor,
            assignment=customer.current_assignment, kind=kind, idempotency_key=key, body_hash=body_hash, **values)
        return {'ok': True, 'record': serialize(record)}, 201


@require_http_methods(['GET', 'POST'])
@require_role(User.Role.EMPLOYEE)
@api_errors
def activities(request, customer_id):
    optional_queue_identity(request)
    actor_identity(request)
    if request.method == 'POST':
        result, status = record_activity(request.user, customer_id, json_object(request))
        return JsonResponse(result, status=status)
    if request.GET:
        raise AccessError('VALIDATION_ERROR', '기록 조회 조건을 확인해 주세요.', 422)
    owned_customer(request.user, customer_id)
    return JsonResponse({'items': [serialize(row) for row in CustomerActivity.objects.filter(
        customer_id=customer_id, actor=request.user).order_by('-created_at', '-pk')[:20]]})
