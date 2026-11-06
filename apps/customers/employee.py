import base64
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_GET,require_POST
from apps.accounts.access import AccessError,require_role
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.common.http import api_errors,identifier,json_object
from apps.customers.models import Customer
from apps.customers.queries import enriched,serialize
from apps.customers.services import digest
from apps.operations.models import MutationReceipt
from apps.sites.models import Site


def queue_identity(request):
    supplied=request.headers.get("X-TM-Queue-User")
    if not supplied or supplied!=str(request.user.pk) or request.user.role!=User.Role.EMPLOYEE:
        raise AccessError("QUEUE_CONTEXT_MISMATCH","로그인 계정이 변경되었습니다. 이전 계정의 대기값은 전송하지 않습니다.",403)


def optional_queue_identity(request):
    if request.headers.get("X-TM-Queue-User") is not None:queue_identity(request)


@require_GET
@require_role(User.Role.EMPLOYEE)
def page(request,view):
    return render(request,"customers/employee.html",{"employee_view":view,"customer_schema":{
        "call_result":{"":"(빈 값)",**dict(Customer.CallResult.choices)},"contract_status":dict(Customer.ContractStatus.choices)}})


@require_GET
@require_role(User.Role.EMPLOYEE)
@api_errors
def context(request):
    queue_identity(request)
    # Separate from AI credentials; the key never lives in browser storage.
    key=salted_hmac("tm.employee.queue.v1",str(request.user.pk),algorithm="sha256").digest()
    return JsonResponse({"user_id":str(request.user.pk),"role":request.user.role,"key":base64.b64encode(key).decode(),
        "target_ms":settings.AUTOSAVE_TARGET_SECONDS*1000,"max_ms":100000,"server_time":timezone.now().isoformat()})


def check_one(actor,item):
    if not isinstance(item,dict) or set(item)-{"key","site_id","customer_id","assignment_id","expected_version","inflight"} or not {"key","site_id","customer_id","assignment_id","expected_version"}<=set(item):
        raise AccessError("VALIDATION_ERROR","대기열 확인 형식을 확인해 주세요.",422)
    cid,sid,aid=identifier(item["customer_id"]),identifier(item["site_id"]),identifier(item["assignment_id"])
    if type(item["expected_version"]) is not int or item["expected_version"]<1:
        raise AccessError("VALIDATION_ERROR","대기열 버전을 확인해 주세요.",422)
    result={"key":item["key"]}
    if not isinstance(item["key"],str) or not 1<=len(item["key"])<=500:
        raise AccessError("VALIDATION_ERROR","대기열 키를 확인해 주세요.",422)
    if not Site.objects.filter(pk=sid).exists():return {**result,"code":"SITE_DELETED"}
    customer=enriched(Customer.objects.filter(pk=cid,site_id=sid)).first()
    historical=Assignment.objects.filter(pk=aid,customer_id=cid,employee=actor).exists()
    if not customer:return {**result,"code":"CUSTOMER_DELETED" if historical else "FORBIDDEN"}
    if customer.deleted_at:return {**result,"code":"CUSTOMER_DELETED" if historical else "FORBIDDEN"}
    assignment=customer.current_assignment
    if not assignment or assignment.employee_id!=actor.pk or assignment.ended_at or assignment.pk!=aid:
        return {**result,"code":"ASSIGNMENT_CHANGED" if historical else "FORBIDDEN"}
    row=serialize(customer)
    inflight=item.get("inflight")
    if inflight:
        expected={"customer_id","assignment_id","mutation_id","expected_version","changes"}
        if not isinstance(inflight,dict) or not expected<=set(inflight) or set(inflight)-expected-{'source_ai_result_id'} or str(cid)!=inflight["customer_id"] or str(aid)!=inflight["assignment_id"]:
            raise AccessError("VALIDATION_ERROR","전송 기록의 식별자를 확인해 주세요.",422)
        if 'source_ai_result_id' in inflight:identifier(inflight['source_ai_result_id'])
        mid=identifier(inflight["mutation_id"])
        receipt=MutationReceipt.objects.filter(actor=actor,customer=customer,mutation_id=mid).first()
        if receipt:
            if receipt.body_hash!=digest(inflight):return {**result,"code":"IDEMPOTENCY_CONFLICT","server_row":row}
            if receipt.expires_at<=timezone.now():return {**result,"code":"IDEMPOTENCY_EXPIRED","server_row":row}
            return {**result,"code":"RECEIPT","server_row":row,"receipt":receipt.result}
    return {**result,"code":"READY" if customer.version==item["expected_version"] else "VERSION_CONFLICT","server_row":row}


@require_POST
@require_role(User.Role.EMPLOYEE)
@api_errors
def check_queue(request):
    queue_identity(request)
    body=json_object(request);items=body.get("entries")
    if set(body)!={"entries"} or not isinstance(items,list) or not 1<=len(items)<=100:
        raise AccessError("VALIDATION_ERROR","대기열 1~100건을 확인해 주세요.",422)
    return JsonResponse({"results":[check_one(request.user,item) for item in items]})


@require_POST
@require_role(User.Role.EMPLOYEE)
@api_errors
def save(request):
    queue_identity(request)
    from apps.customers.views import batch_update
    return batch_update(request)
