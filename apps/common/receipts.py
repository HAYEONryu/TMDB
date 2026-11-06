"""Idempotency for P4 writes. Payloads never contain password fields."""
from datetime import timedelta
import hashlib
import json
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.operations.models import IdempotencyRecord

P4_OPERATIONS={"DISTRIBUTE","MANUAL_RECALL","ASSIGNEE_CHANGE","USER_CREATE","USER_UPDATE","PASSWORD_RESET","CALLBACK_COMPLETE","SOFT_DELETE","RESTORE","DELETION_REQUEST","DELETION_APPROVE","CUSTOMER_HARD_DELETE","SITE_HARD_DELETE","AI_GUIDE_EDIT","AI_GUIDE_PUBLISH"}


def fingerprint(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def replay(actor,operation,key,body_hash):
    receipt=IdempotencyRecord.objects.filter(actor=actor,operation=operation,key=key).first()
    if not receipt:return None
    if receipt.body_hash!=body_hash:
        raise AccessError("IDEMPOTENCY_CONFLICT","같은 요청 키의 내용이 다릅니다.",409)
    if receipt.expires_at<=timezone.now():
        raise AccessError("IDEMPOTENCY_EXPIRED","요청 보관 기간이 지났습니다. 현재 상태를 다시 확인해 주세요.",409)
    return receipt.result["payload"],receipt.result["status_code"]


def remember(actor,operation,key,body_hash,result,*,status=200,target_ids=()):
    IdempotencyRecord.objects.create(actor=actor,operation=operation,key=key,body_hash=body_hash,
        result={"payload":result,"status_code":status},target_ids=[str(value) for value in target_ids],expires_at=timezone.now()+timedelta(days=7))
    return result,status


def failure(error):
    payload={"error":{"code":error.code,"message":error.message}}
    if error.fields:payload["error"]["fields"]=error.fields
    return payload,error.status


def cleanup_p4_receipts():
    from apps.common.transactions import business_write
    with business_write():
        ids=list(IdempotencyRecord.objects.filter(operation__in=P4_OPERATIONS,expires_at__lte=timezone.now()).order_by("expires_at","pk").values_list("pk",flat=True)[:1000])
        return IdempotencyRecord.objects.filter(pk__in=ids).delete()[0]


def cleanup_mutation_receipts():
    from apps.common.transactions import business_write
    from apps.operations.models import MutationReceipt
    with business_write():
        ids=list(MutationReceipt.objects.filter(expires_at__lte=timezone.now()).order_by('expires_at','pk').values_list('pk',flat=True)[:1000])
        return MutationReceipt.objects.filter(pk__in=ids).delete()[0]
