"""Validate provenance at the ordinary customer write transaction boundary."""
from apps.accounts.access import AccessError
from apps.accounts.models import User
from .models import AIResult
from .services import authorize


def validate_application(actor, customer, result_id, values, actual):
    from apps.customers.services import normalized_changes
    result=AIResult.objects.select_for_update(of=('self',)).select_related('request__customer__current_assignment').filter(pk=result_id).first()
    if not result or actor.role!=User.Role.EMPLOYEE or result.request.actor_id!=actor.pk or result.request.customer_id!=customer.pk:
        raise AccessError('FORBIDDEN','현재 담당 고객의 본인 AI 결과만 적용할 수 있습니다.',403)
    authorize(result.request,actor)
    if not result.valid or result.request.status!='SUCCEEDED' or result.request.feature!='CLEANUP' or result.request.schema_version!='employee-v1':
        raise AccessError('AI_RESULT_STALE','적용할 수 없는 AI 결과입니다. 기존 값을 확인해 주세요.',409)
    if result.stale or result.request.customer_version!=customer.version or result.request.assignment_id!=customer.current_assignment_id:
        raise AccessError('AI_RESULT_STALE','오래된 AI 결과입니다. 최신 값과 비교해 일반 편집으로 반영해 주세요.',409)
    matching=[]
    for field,item in result.payload['suggestions'].items():
        if field in actual and item['status']=='SUGGESTION' and item['value'] is not None:
            proposed=normalized_changes(customer,{field:item['value']})[field]
            if proposed==values[field]:matching.append(field)
    if actual and not matching:raise AccessError('AI_SOURCE_MISMATCH','선택한 AI 제안과 저장값이 일치하지 않습니다.',422)
    return result
