"""Confirmed exact-set recall using the same TM state as the employee grid."""
from django.core import signing
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.assignments.models import Assignment
from apps.assignments.services import end_locked, eligible, employee_rows, selected_employee, selected_rows, site_for
from apps.accounts.models import User
from apps.common.http import identifier
from apps.common.receipts import fingerprint, remember, replay
from apps.common.transactions import business_write, retry_transient_write
from apps.customers.cohorts import current_customers
from apps.customers.tm import with_tm_state
from apps.operations.models import OperationEvent
from apps.sites.services import locked_actor
from apps.customers.queries import KST

OPERATION='TM_UNFINISHED_RECALL'
SALT='tm.unfinished-recall.v1'


def selection(body,fields):
    if set(body)!=fields:raise AccessError('VALIDATION_ERROR','현장·직원과 확인 내용을 확인해 주세요.',422)
    return identifier(body['site_id']),selected_employee(body['employee_id'])


def current_selection(value):
    if value=='all':return list(employee_rows())
    if isinstance(value,tuple):
        if User.objects.filter(pk__in=value).count()!=len(value):raise AccessError('INVALID_EMPLOYEE','직원 목록을 다시 확인해 주세요.',409)
        return list(selected_rows(employee_rows(),value))
    if not User.objects.filter(pk=value).exists():
        raise AccessError('INVALID_EMPLOYEE','직원이 존재하지 않습니다. 직원 목록을 다시 확인해 주세요.',409)
    return list(employee_rows().filter(pk=value))


def targets(site_id,people,now):
    return with_tm_state(current_customers(site_id,now).filter(current_assignment__employee_id__in=[p.pk for p in people]),now).filter(tm_status='PENDING')


def snapshot(actor,site,people,value,now):
    rows=list(targets(site.pk,people,now).order_by('pk').values_list('pk','current_assignment_id','current_assignment__employee_id'))
    counts={p.pk:0 for p in people}
    for _,_,employee_id in rows:counts[employee_id]+=1
    day=timezone.localdate(now,KST).isoformat()
    digest=fingerprint({'rows':[[str(v) for v in row] for row in rows], 'date':day,
        'people':[[str(p.pk),p.name] for p in people],'site_name':site.name})
    proof={'actor':str(actor.pk),'site':str(site.pk),'employee':str(value),'digest':digest}
    return {'site_id':str(site.pk),'site_name':site.name,'business_date':day,'target_count':len(rows),
        'employees':[{'id':str(p.pk),'name':p.name,'count':counts[p.pk]} for p in people],
        'confirmation':signing.dumps(proof,salt=SALT)},proof


@retry_transient_write
def preview(actor,body):
    site_id,value=selection(body,{'site_id','employee_id'})
    with business_write():
        actor=locked_actor(actor,admin=True);site=site_for(site_id,lock=True);people=current_selection(value)
        return snapshot(actor,site,people,value,timezone.now())[0]


@retry_transient_write
def recall_unfinished(actor,body):
    site_id,value=selection(body,{'site_id','employee_id','confirmation','idempotency_key'})
    key=identifier(body['idempotency_key'])
    if not isinstance(body['confirmation'],str):raise AccessError('VALIDATION_ERROR','회수 대상 확인이 필요합니다.',422)
    body_hash=fingerprint({'site_id':str(site_id),'employee_id':str(value),'confirmation':body['confirmation']})
    with business_write():
        actor=locked_actor(actor,admin=True)
        cached=replay(actor,OPERATION,key,body_hash)
        if cached:return cached
        site=site_for(site_id,lock=True);people=current_selection(value);now=timezone.now()
        fresh,proof=snapshot(actor,site,people,value,now)
        try:previous=signing.loads(body['confirmation'],salt=SALT,max_age=600)
        except signing.BadSignature:previous=None
        if previous!=proof:
            raise AccessError('TM_TARGETS_CHANGED','대상 또는 확인 유효기간이 변경되었습니다. 최신 인원을 확인하고 다시 확정해 주세요.',409,{'preview':fresh})
        customers=list(targets(site_id,people,now).select_for_update(of=('self',)).order_by('pk'))
        assignments=list(Assignment.objects.select_for_update().filter(pk__in=[c.current_assignment_id for c in customers]).order_by('pk'))
        end_locked(customers,assignments,actor,Assignment.EndReason.MANUAL_RECALL,now)
        OperationEvent.objects.create(actor=actor,operation=OPERATION,occurred_at=now,affected_count=len(customers))
        for person in fresh['employees']:
            person['remaining_held']=current_customers(site_id,now).filter(current_assignment__employee_id=person['id']).count()
        result={'ok':True,'recall_kind':'unfinished_tm','site_id':str(site_id),'business_date':fresh['business_date'],
            'recalled_count':len(customers),'employees':fresh['employees'],'available_count':eligible(site_id).count()}
        return remember(actor,OPERATION,key,body_hash,result,target_ids=[site_id])
