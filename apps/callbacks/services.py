from django.db.models import F
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.http import identifier
from apps.common.receipts import fingerprint,replay,remember
from apps.common.transactions import business_write,retry_transient_write
from apps.consultations.models import ConsultationRevision
from apps.consultations.snapshots import audit_snapshot
from apps.customers.access import current_access
from apps.customers.models import Customer,CustomerChangeEvent
from apps.customers.services import snapshot,safe_row
from apps.sites.models import Site
from apps.sites.services import locked_actor


@retry_transient_write
def complete(actor,cid,body,*,employee_only=False):
    if set(body)!={'callback_id','callback_version','assignment_id','expected_version','idempotency_key'}:
        raise AccessError('VALIDATION_ERROR','재콜 완료 요청 형식을 확인해 주세요.',422)
    callback_id,aid,key=identifier(body['callback_id']),identifier(body['assignment_id'],nullable=True),identifier(body['idempotency_key'])
    if any(type(body[name]) is not int or body[name]<1 for name in ['callback_version','expected_version']):raise AccessError('VALIDATION_ERROR','재콜·고객 버전을 확인해 주세요.',422)
    body_hash=fingerprint({'customer_id':str(cid),**body})
    with business_write():
        metadata=Customer.objects.filter(pk=cid).values('site_id','current_assignment__employee_id').first()
        actor=locked_actor(actor,extra_ids=[metadata['current_assignment__employee_id']] if metadata and metadata['current_assignment__employee_id'] else [])
        if employee_only and actor.role!=User.Role.EMPLOYEE:raise AccessError('QUEUE_CONTEXT_MISMATCH','로그인 권한이 변경되었습니다.',403)
        if not metadata:raise AccessError('CUSTOMER_DELETED' if actor.role==User.Role.ADMIN else 'FORBIDDEN','고객정보를 사용할 수 없습니다.',409 if actor.role==User.Role.ADMIN else 403)
        Site.objects.select_for_update().get(pk=metadata['site_id'])
        customer=Customer.objects.select_for_update().get(pk=cid)
        assignment=Assignment.objects.select_for_update().filter(pk=customer.current_assignment_id).first()
        current_access(actor,customer,aid)
        if customer.current_assignment_id!=aid:raise AccessError('ASSIGNMENT_CHANGED','담당자가 변경되었습니다. 다시 확인해 주세요.',409)
        cached=replay(actor,'CALLBACK_COMPLETE',key,body_hash)
        if cached:return {**cached[0],'row':safe_row(cid,actor)},cached[1]
        callback=Callback.objects.select_for_update().filter(pk=callback_id,customer=customer).first()
        if not callback:raise AccessError('CALLBACK_CHANGED','해당 재콜 일정을 사용할 수 없습니다.',409)
        changed=callback.status!=Callback.Status.COMPLETED
        if changed:
            if callback.status!=Callback.Status.PENDING:raise AccessError('CALLBACK_CHANGED','취소되거나 변경된 일정입니다.',409)
            if callback.version!=body['callback_version'] or customer.version!=body['expected_version']:raise AccessError('VERSION_CONFLICT','재콜 또는 상담정보가 변경되었습니다. 새로 확인해 주세요.',409)
            before=snapshot(customer,callback);now=timezone.now()
            callback.status=Callback.Status.COMPLETED;callback.completed_at=now;callback.completed_by=actor;callback.updated_by=actor;callback.version+=1;callback.save()
            customer.version+=1;customer.save(update_fields=['version','updated_at'])
            if assignment and assignment.first_activity_at is None:
                assignment.first_activity_at=now;assignment.save(update_fields=['first_activity_at','updated_at'])
            after=snapshot(customer,None)
            CustomerChangeEvent.objects.create(customer=customer,assignment=assignment,changed_by=actor,changed_at=now,changed_fields=['callback_due_at'])
            ConsultationRevision.objects.create(customer=customer,assignment=assignment,actor=actor,saved_at=now,customer_version=customer.version,
                changed_fields=['callback_due_at'],before_values=audit_snapshot(before, {'callback_due_at'}),after_values=audit_snapshot(after, {'callback_due_at'}),notes=customer.notes,source=ConsultationRevision.Source.MANUAL)
        result={'ok':True,'changed':changed,'customer_id':str(cid),'callback_id':str(callback.pk),'completed_at':callback.completed_at.isoformat(),'completed_by':str(callback.completed_by_id),'version':customer.version}
        remember(actor,'CALLBACK_COMPLETE',key,body_hash,result,target_ids=[cid,customer.site_id])
        return {**result,'row':safe_row(cid,actor)},200
