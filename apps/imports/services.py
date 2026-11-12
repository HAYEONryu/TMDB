from datetime import timedelta
from django.conf import settings
from django.db import DatabaseError, OperationalError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.callbacks.models import Callback
from apps.common.http import identifier
from apps.common.transactions import business_write, retry_transient_write
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.choices import invalid_import_choice
from apps.customers.services import digest, snapshot
from apps.imports.excel import parse_upload
from apps.imports.models import ImportBatch, ImportCandidate, ImportRowResult
from apps.operations.models import IdempotencyRecord, OperationEvent
from apps.sites.models import Site
from apps.sites.services import locked_actor

OPERATION = "IMPORT_COMMIT"
TTL = timedelta(hours=settings.IMPORT_TTL_HOURS)
METADATA_RETENTION = timedelta(days=7)


def reject(code, message, status=409):
    raise AccessError(code, message, status)


def site_lock(site_id):
    site = Site.objects.select_for_update().filter(pk=site_id).first()
    if not site:
        reject("SITE_DELETED", "현장이 삭제되었거나 존재하지 않습니다.")
    return site


def counts_for(results):
    return {"total":len(results), "ready":sum(row["success"] for row in results),
        "duplicate_in_file":sum(row["error_code"] == "DUPLICATE_IN_FILE" for row in results),
        "duplicate_existing":sum(row["error_code"] == "DUPLICATE_PHONE" for row in results),
        "invalid":sum(row["error_code"] in {"INVALID_ROW","SOURCE_DELETED"} for row in results)}


def validate_upload(actor, site_id, upload):
    # Parsing is intentionally outside the global business-write lock.
    results, candidates = parse_upload(upload)
    return store_validation(actor, site_id, results, candidates)


@retry_transient_write
def store_validation(actor, site_id, results, candidates):
    with business_write():
        actor = locked_actor(actor, admin=True)
        site = site_lock(site_id)
        existing = set(Customer.objects.filter(deleted_at=None,phone_normalized__in=[values["phone_normalized"] for _,values in candidates]).values_list("phone_normalized",flat=True))
        good = []
        by_row = {row["row_number"]:row.copy() for row in results}
        for number, values in candidates:
            if values["phone_normalized"] in existing:
                by_row[number].update(success=False,error_code="DUPLICATE_PHONE",reason="전체 현장의 휴지통 제외 고객 중 같은 연락처가 있어 등록에서 제외합니다.")
            else:
                good.append((number,values))
        rows = list(by_row.values())
        summary = counts_for(rows)
        batch = ImportBatch.objects.create(site=site,created_by=actor,expires_at=timezone.now()+TTL,
            total_count=summary["total"],success_count=0,failure_count=summary["total"]-summary["ready"],validation_summary=summary)
        ImportCandidate.objects.bulk_create([ImportCandidate(batch=batch,row_number=number,normalized_values=values) for number,values in good],batch_size=500)
        ImportRowResult.objects.bulk_create([ImportRowResult(batch=batch,**row) for row in rows],batch_size=500)
    return batch


def summary(batch, now=None):
    now = now or timezone.now()
    expired = now >= batch.expires_at
    status = "EXPIRED" if expired and batch.status == "VALIDATED" else batch.status
    return {"id":str(batch.pk),"site_id":str(batch.site_id),"site_name":batch.site.name,"status":status,
        "created_at":batch.created_at.isoformat(),"expires_at":batch.expires_at.isoformat(),
        "committed_at":batch.committed_at.isoformat() if batch.committed_at else None,
        "validation_summary":batch.validation_summary,"total_count":batch.total_count,"success_count":batch.success_count,
        "failure_count":batch.failure_count,"results_expired":expired,"last_error_code":batch.last_error_code,
        "can_commit":not expired and status == "VALIDATED" and batch.validation_summary.get("ready",0)>0}


def result_page(actor, batch_id, params):
    if actor.role != User.Role.ADMIN:
        reject("FORBIDDEN","관리자 권한이 필요합니다.",403)
    if set(params)-{"page","kind"}:
        reject("VALIDATION_ERROR","결과 조회 조건을 확인해 주세요.",422)
    batch=ImportBatch.objects.select_related("site").filter(pk=batch_id).first()
    if not batch or batch.expires_at+METADATA_RETENTION<=timezone.now():
        reject("IMPORT_NOT_FOUND","업로드 결과가 삭제되었거나 존재하지 않습니다.",404)
    try:page=int(params.get("page",1))
    except (ValueError,TypeError):page=0
    kind=params.get("kind","failed")
    if not 1<=page<=1000000 or kind not in {"failed","ready","all"}:
        reject("VALIDATION_ERROR","결과 조회 조건을 확인해 주세요.",422)
    result=summary(batch)
    rows=ImportRowResult.objects.filter(batch=batch)
    if result["results_expired"]:rows=rows.none()
    if kind!="all":rows=rows.filter(success=kind=="ready")
    total=rows.count()
    result.update(rows=list(rows.order_by("row_number").values("row_number","success","customer_name","phone_input","error_code","reason")[(page-1)*100:page*100]),
        page=page,total_rows=total,last_page=max(1,(total+99)//100),kind=kind)
    return result


def completed_result(batch):
    return {"ok":True,"batch_id":str(batch.pk),"status":"COMMITTED","total_count":batch.total_count,
        "success_count":batch.success_count,"failure_count":batch.failure_count,
        "message":f"엑셀 {batch.total_count:,}개 데이터 중 {batch.success_count:,}개 업로드를 성공했습니다. {batch.failure_count:,}개는 업로드를 실패했습니다. 실패 목록을 확인해 주세요."}


def save_receipt(actor, batch, key, body_hash, result, status_code=200):
    IdempotencyRecord.objects.create(actor=actor,operation=OPERATION,key=key,body_hash=body_hash,
        result={"payload":result,"status_code":status_code}, target_ids=[str(batch.pk),str(batch.site_id)],
        # Commit may finish just after the validation deadline. Keep at least
        # seven days from acceptance without outliving batch metadata.
        expires_at=min(timezone.now(),batch.expires_at)+METADATA_RETENTION)
    return result,status_code


def cached(actor, key, body_hash):
    receipt=IdempotencyRecord.objects.filter(actor=actor,operation=OPERATION,key=key).first()
    if not receipt:return None
    if receipt.body_hash!=body_hash:reject("IDEMPOTENCY_CONFLICT","같은 작업 키의 내용이 다릅니다.")
    if receipt.expires_at<=timezone.now():reject("IDEMPOTENCY_EXPIRED","요청 보관 기간이 지났습니다. 결과를 확인해 주세요.")
    return receipt.result["payload"],receipt.result["status_code"]


def expire_batch(batch):
    if batch.status=="VALIDATED":
        batch.status="EXPIRED"
        batch.save(update_fields=["status","updated_at"])
    batch.candidates.all().delete()
    batch.row_results.all().delete()


@retry_transient_write
def commit_once(actor,batch_id,site_id,key,body_hash):
    with business_write():
        actor=locked_actor(actor,admin=True)
        site=site_lock(site_id)
        replay=cached(actor,key,body_hash)
        if replay:return replay
        batch=ImportBatch.objects.select_for_update().filter(pk=batch_id).first()
        if not batch:reject("IMPORT_NOT_FOUND","업로드 결과가 삭제되었거나 존재하지 않습니다.",404)
        if batch.site_id!=site.pk:reject("SITE_MISMATCH","검증 때 선택한 현장에서만 확정할 수 있습니다.")
        if batch.expires_at<=timezone.now() or batch.status=="EXPIRED":
            expire_batch(batch)
            return {"error":{"code":"IMPORT_EXPIRED","message":"검증 결과가 만료되었습니다. 파일을 다시 업로드해 주세요."}},409
        if batch.status=="COMMITTED":return save_receipt(actor,batch,key,body_hash,completed_result(batch))
        if batch.status=="FAILED":reject("IMPORT_FAILED","확정에 실패한 업로드입니다. 파일을 다시 업로드해 주세요.")
        candidates=list(batch.candidates.order_by("row_number"))
        existing=set(Customer.objects.filter(deleted_at=None,phone_normalized__in=[row.normalized_values["phone_normalized"] for row in candidates]).values_list("phone_normalized",flat=True))
        customers,callbacks,revisions,changed_results=[],[],[],[]
        result_rows={row.row_number:row for row in batch.row_results.filter(success=True)}
        now=timezone.now()
        for candidate in candidates:
            values=candidate.normalized_values.copy()
            row=result_rows[candidate.row_number]
            choice_error=invalid_import_choice(values)
            if choice_error:
                row.success=False;row.error_code='INVALID_ROW';row.reason=choice_error
                changed_results.append(row)
                continue
            if values["phone_normalized"] in existing:
                row.success=False;row.error_code="DUPLICATE_PHONE";row.reason="검증 후 전체 현장의 휴지통 제외 고객 중 같은 연락처가 등록·복구되었습니다. 기존 상담정보는 변경하지 않았습니다."
                changed_results.append(row)
                continue
            callback_value=values.pop("callback_due_at")
            if values["visit_at"]:values["visit_at"]=parse_datetime(values["visit_at"])
            customer=Customer(site=site,import_batch=batch,**values)
            customers.append(customer)
            callback=Callback(customer=customer,due_at=parse_datetime(callback_value),created_by=actor,updated_by=actor) if callback_value else None
            if callback:callbacks.append(callback)
            revisions.append(ConsultationRevision(customer=customer,assignment=None,actor=actor,saved_at=now,
                customer_version=1,source="IMPORT",changed_fields=list(snapshot(customer,callback)),before_values={},
                after_values=snapshot(customer,callback),notes=customer.notes))
        Customer.objects.bulk_create(customers,batch_size=500)
        Callback.objects.bulk_create(callbacks,batch_size=500)
        ConsultationRevision.objects.bulk_create(revisions,batch_size=500)
        if changed_results:ImportRowResult.objects.bulk_update(changed_results,["success","error_code","reason"],batch_size=500)
        batch.status="COMMITTED";batch.committed_at=now;batch.committed_by=actor
        batch.success_count=len(customers);batch.failure_count=batch.total_count-len(customers)
        batch.save(update_fields=["status","committed_at","committed_by","success_count","failure_count","updated_at"])
        batch.candidates.all().delete()
        OperationEvent.objects.create(actor=actor,operation="IMPORT_COMMITTED",occurred_at=now,affected_count=len(customers))
        return save_receipt(actor,batch,key,body_hash,completed_result(batch))


@retry_transient_write
def mark_fatal_failure(actor,batch_id,site_id,key,body_hash):
    # Separate transaction: the whole customer/callback/revision transaction rolled back.
    with business_write():
        actor=locked_actor(actor,admin=True)
        site_lock(site_id)
        replay=cached(actor,key,body_hash)
        if replay:return replay
        batch=ImportBatch.objects.select_for_update().filter(pk=batch_id,site_id=site_id).first()
        if not batch:reject("IMPORT_NOT_FOUND","업로드 결과가 존재하지 않습니다.",404)
        if batch.expires_at<=timezone.now():
            expire_batch(batch)
            return {"error":{"code":"IMPORT_EXPIRED","message":"검증 결과가 만료되었습니다. 다시 업로드해 주세요."}},409
        if batch.status=="COMMITTED":return save_receipt(actor,batch,key,body_hash,completed_result(batch))
        batch.status="FAILED";batch.last_error_code="COMMIT_FAILED";batch.success_count=0;batch.failure_count=batch.total_count
        batch.save(update_fields=["status","last_error_code","success_count","failure_count","updated_at"])
        batch.row_results.filter(success=True).update(success=False,error_code="COMMIT_FAILED",reason="등록을 완료하지 못해 전체 등록을 취소했습니다. 파일을 다시 업로드해 주세요.")
        batch.candidates.all().delete()
        result={"ok":False,"batch_id":str(batch.pk),"status":"FAILED","total_count":batch.total_count,"success_count":0,"failure_count":batch.total_count,
            "error":{"code":"IMPORT_FAILED","message":"등록 중 오류가 발생해 전체 등록을 취소했습니다. 파일을 다시 업로드해 주세요."}}
        return save_receipt(actor,batch,key,body_hash,result,500)


def commit_upload(actor,batch_id,body):
    if set(body)!={"site_id","idempotency_key"}:reject("VALIDATION_ERROR","현장과 작업 키를 확인해 주세요.",422)
    site_id,key=identifier(body["site_id"]),identifier(body["idempotency_key"])
    body_hash=digest({"batch_id":str(batch_id),"site_id":str(site_id)})
    try:return commit_once(actor,batch_id,site_id,key,body_hash)
    except DatabaseError as exc:
        if isinstance(exc,OperationalError):
            # Infrastructure/lock failure: no durable FAILED receipt; retry the same key.
            raise
        return mark_fatal_failure(actor,batch_id,site_id,key,body_hash)


@retry_transient_write
def cleanup_imports(*, now=None, limit=50):
    now=now or timezone.now()
    with business_write():
        # EXISTS avoids the candidate × result join (up to 100M rows per batch).
        eligible=ImportBatch.objects.filter(expires_at__lte=now).annotate(
            has_candidates=Exists(ImportCandidate.objects.filter(batch_id=OuterRef("pk"))),
            has_results=Exists(ImportRowResult.objects.filter(batch_id=OuterRef("pk")))).filter(
                Q(expires_at__lte=now-METADATA_RETENTION)|Q(status="VALIDATED")|Q(has_candidates=True)|Q(has_results=True))
        ids=list(eligible.order_by("expires_at","pk").values_list("pk",flat=True)[:limit])
        site_ids=ImportBatch.objects.filter(pk__in=ids).values_list("site_id",flat=True)
        list(Site.objects.select_for_update().filter(pk__in=site_ids).order_by("pk"))
        touched=deleted=0
        for batch_id in ids:
            batch=ImportBatch.objects.select_for_update().get(pk=batch_id)
            if batch.expires_at+METADATA_RETENTION<=now:
                IdempotencyRecord.objects.filter(operation=OPERATION,target_ids__contains=[str(batch.pk)]).delete()
                # Customer.import_batch becomes null; customers and revisions survive.
                batch.delete();deleted+=1;touched+=1
            elif batch.status=="VALIDATED" or batch.candidates.exists() or batch.row_results.exists():
                expire_batch(batch);touched+=1
            if touched>=limit:break
        # Only our own expired receipt metadata is cleaned in this stage.
        IdempotencyRecord.objects.filter(operation=OPERATION,expires_at__lte=now).delete()
        return {"batches_cleaned":touched,"metadata_deleted":deleted}
