"""Resumable per-request approval, reusing individual approval atomically."""
from uuid import uuid5
from django.db import DatabaseError, transaction
from apps.accounts.access import AccessError
from apps.common.http import identifier
from apps.common.receipts import fingerprint, remember, replay
from apps.common.transactions import business_write, retry_transient_write
from apps.customers.deletions import approve
from apps.customers.models import CustomerDeletionRequest
from apps.operations.models import IdempotencyRecord
from apps.sites.services import locked_actor

OPERATION = 'DELETION_BULK_APPROVE'


def summary(items):
    return {'ok': True, 'items': items, 'approved_count': sum(r['status']=='approved' for r in items),
            'excluded_count': sum(r['status']=='excluded' for r in items),
            'failed_count': sum(r['status']=='failed' for r in items)}


@retry_transient_write
def initialize(actor, key, body_hash, ids):
    with business_write():
        actor=locked_actor(actor,admin=True)
        cached=replay(actor,OPERATION,key,body_hash)
        if cached:return cached[0]
        targets=list(CustomerDeletionRequest.objects.filter(pk__in=ids).values('pk','customer_id','customer__site_id','customer__site__name','customer__customer_name','customer__phone_normalized'))
        labels={row['pk']:row for row in targets}
        payload=summary([{'request_id':str(rid),'status':'pending','site_name':labels.get(rid,{}).get('customer__site__name','현장 확인 불가'),'customer_name':labels.get(rid,{}).get('customer__customer_name','고객 확인 불가'),'phone':labels.get(rid,{}).get('customer__phone_normalized','')} for rid in ids])
        remember(actor,OPERATION,key,body_hash,payload,target_ids=[v for row in targets for v in [row['customer_id'],row['customer__site_id']]])
        return payload


@retry_transient_write
def process_one(actor, key, body_hash, request_id):
    with business_write():
        actor=locked_actor(actor,admin=True)
        replay(actor,OPERATION,key,body_hash)  # Reject expired/mismatched batch identities.
        receipt=IdempotencyRecord.objects.select_for_update().get(actor=actor,operation=OPERATION,key=key)
        items=receipt.result['payload']['items']
        item=next(r for r in items if r['request_id']==str(request_id))
        if item['status'] in {'approved','excluded'}:return
        deletion=CustomerDeletionRequest.objects.filter(pk=request_id).values('status','customer__deleted_at').first()
        if deletion is None:item.update(status='excluded',reason='REQUEST_DELETED',message='요청이 삭제되었거나 존재하지 않습니다.')
        elif deletion['status']!='PENDING':
            item.update(status='excluded',reason='ALREADY_APPROVED' if deletion['status']=='APPROVED' else 'REQUEST_CLOSED',message='이미 승인된 요청입니다.' if deletion['status']=='APPROVED' else '이미 처리되거나 종료된 요청입니다.')
        else:
            try:
                # Approval and its progress checkpoint share one per-item transaction.
                # A failed item rolls back without undoing other committed approvals.
                with transaction.atomic():
                    result,status=approve(actor,request_id,{'idempotency_key':str(uuid5(key,str(request_id)))})
                if status==200:item.update(status='approved',reason='',message='승인했습니다.')
                else:item.update(status='failed' if status>=500 or status==429 else 'excluded',reason=result['error']['code'],message=result['error']['message'])
            except AccessError as error:
                if error.status in {401,403}:raise
                item.update(status='failed' if error.status>=500 or error.status==429 else 'excluded',reason=error.code,message=error.message)
        receipt.result={'payload':summary(items),'status_code':200};receipt.save(update_fields=['result','updated_at'])


def mark_failed(actor,key,request_id):
    with business_write():
        actor=locked_actor(actor,admin=True)
        receipt=IdempotencyRecord.objects.select_for_update().get(actor=actor,operation=OPERATION,key=key)
        items=receipt.result['payload']['items'];item=next(r for r in items if r['request_id']==str(request_id))
        if item['status'] not in {'approved','excluded'}:
            item.update(status='failed',reason='TEMPORARY_UNAVAILABLE',message='처리하지 못했습니다. 같은 일괄 요청으로 다시 확인해 주세요.')
        receipt.result={'payload':summary(items),'status_code':200};receipt.save(update_fields=['result','updated_at'])


def approve_bulk(actor,body):
    if set(body)!={'request_ids','idempotency_key'} or not isinstance(body['request_ids'],list) or not 1<=len(body['request_ids'])<=100:
        raise AccessError('VALIDATION_ERROR','삭제 요청 1~100건을 선택해 주세요.',422)
    ids=sorted(identifier(value) for value in body['request_ids'])
    if len(set(ids))!=len(ids):raise AccessError('VALIDATION_ERROR','중복 요청 ID가 있습니다.',422)
    key=identifier(body['idempotency_key']);body_hash=fingerprint({'request_ids':[str(v) for v in ids]})
    initialize(actor,key,body_hash,ids)
    for rid in ids:
        try:process_one(actor,key,body_hash,rid)
        except DatabaseError:mark_failed(actor,key,rid)
    with business_write():
        actor=locked_actor(actor,admin=True)
        return replay(actor,OPERATION,key,body_hash)[0],200
