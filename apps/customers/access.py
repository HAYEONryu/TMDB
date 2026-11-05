from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment


def current_access(actor,customer,assignment_id,*,allow_trash=False):
    """Caller has fetched the customer; writes call this after sorted row locks."""
    if actor.role==User.Role.ADMIN:
        if customer.deleted_at and not allow_trash:raise AccessError('CUSTOMER_DELETED','휴지통의 고객정보는 수정할 수 없습니다.',409)
        return
    assignment=customer.current_assignment
    historical=assignment_id and Assignment.objects.filter(pk=assignment_id,customer=customer,employee=actor).exists()
    if customer.deleted_at or not assignment or assignment.employee_id!=actor.pk or assignment.ended_at or assignment.pk!=assignment_id:
        if historical:raise AccessError('CUSTOMER_DELETED' if customer.deleted_at else 'ASSIGNMENT_CHANGED','현재 할당이 변경되거나 삭제되었습니다.',409)
        raise AccessError('FORBIDDEN','현재 담당 고객정보만 사용할 수 있습니다.')

