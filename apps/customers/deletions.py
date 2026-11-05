import json
from django.core import signing
from django.db import transaction,connection
from django.db.models import Q,F,Func,Value,TextField
from django.utils import timezone
from django.utils.crypto import salted_hmac
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.http import identifier
from apps.common.receipts import fingerprint,replay,remember,failure
from apps.common.transactions import business_write,retry_transient_write
from apps.consultations.models import ConsultationRevision
from apps.customers.access import current_access
from apps.customers.models import Customer,CustomerDeletionRequest,CustomerChangeEvent
from apps.customers.queries import KST
from apps.customers.services import snapshot
from apps.imports.models import ImportBatch,ImportCandidate,ImportRowResult
from apps.operations.models import IdempotencyRecord,OperationEvent
from apps.sites.models import Site
from apps.sites.services import locked_actor,locked_settings


def invalid(message='삭제 요청 형식을 확인해 주세요.'):raise AccessError('VALIDATION_ERROR',message,422)


def result_for(request):
    return {'ok':True,'request_id':str(request.pk),'customer_id':str(request.customer_id),'status':request.status,
        'approved_at':request.approved_at.isoformat() if request.approved_at else None,'approved_by':str(request.approved_by_id) if request.approved_by_id else None}


@retry_transient_write
def submit(actor,cid,body):
    if set(body)!={'assignment_id','expected_version','idempotency_key'}:invalid()
    aid,key=identifier(body['assignment_id']),identifier(body['idempotency_key'])
    if type(body['expected_version']) is not int or body['expected_version']<1:invalid('고객 버전을 확인해 주세요.')
    body_hash=fingerprint({'customer_id':str(cid),**body})
    with business_write():
        actor=locked_actor(actor)
        if actor.role!=User.Role.EMPLOYEE:raise AccessError('FORBIDDEN','직원만 삭제를 요청할 수 있습니다.')
        metadata=Customer.objects.filter(pk=cid).values('site_id').first()
        if not metadata:raise AccessError('FORBIDDEN','고객정보를 사용할 수 없습니다.')
        Site.objects.select_for_update().get(pk=metadata['site_id'])
        customer=Customer.objects.select_for_update().get(pk=cid)
        Assignment.objects.select_for_update().filter(pk=customer.current_assignment_id).first()
        current_access(actor,customer,aid)
        cached=replay(actor,'DELETION_REQUEST',key,body_hash)
        if cached:return cached
        deletion=CustomerDeletionRequest.objects.select_for_update().filter(customer=customer,status='PENDING').first()
        if not deletion:
            if customer.version!=body['expected_version']:raise AccessError('VERSION_CONFLICT','상담정보가 변경되었습니다. 다시 조회해 주세요.',409)
            deletion=CustomerDeletionRequest.objects.create(customer=customer,requested_by=actor,requested_assignment_id=aid,requested_at=timezone.now())
            OperationEvent.objects.create(actor=actor,operation='DELETION_REQUEST',occurred_at=deletion.requested_at,affected_count=1)
        return remember(actor,'DELETION_REQUEST',key,body_hash,result_for(deletion),target_ids=[cid,customer.site_id])


@retry_transient_write
def approve(actor,request_id,body):
    if set(body)!={'idempotency_key'}:invalid()
    key=identifier(body['idempotency_key']);body_hash=fingerprint({'request_id':str(request_id),**body})
    with business_write():
        metadata=CustomerDeletionRequest.objects.filter(pk=request_id).values('customer_id','customer__site_id','customer__current_assignment__employee_id').first()
        extra=[metadata['customer__current_assignment__employee_id']] if metadata and metadata['customer__current_assignment__employee_id'] else []
        actor=locked_actor(actor,admin=True,extra_ids=extra)
        if not metadata:raise AccessError('DELETION_REQUEST_CLOSED','요청이 삭제되었거나 존재하지 않습니다.',409)
        Site.objects.select_for_update().get(pk=metadata['customer__site_id'])
        customer=Customer.objects.select_for_update().get(pk=metadata['customer_id'])
        assignment=Assignment.objects.select_for_update().filter(pk=customer.current_assignment_id).first()
        callback=Callback.objects.select_for_update().filter(customer=customer,status='PENDING').first()
        deletion=CustomerDeletionRequest.objects.select_for_update().get(pk=request_id)
        cached=replay(actor,'DELETION_APPROVE',key,body_hash)
        if cached:return cached
        if deletion.status=='CLOSED':raise AccessError('DELETION_REQUEST_CLOSED','이미 일반 삭제로 처리된 요청입니다.',409)
        now=timezone.now()
        if deletion.status=='PENDING':
            if customer.deleted_at:
                deletion.status='CLOSED';deletion.closed_at=now;deletion.close_reason='ALREADY_DELETED';deletion.save()
                result,status=failure(AccessError('DELETION_REQUEST_CLOSED','이미 일반 삭제로 처리된 요청입니다.',409))
                return remember(actor,'DELETION_APPROVE',key,body_hash,result,status=status,target_ids=[customer.pk,customer.site_id])
            before=snapshot(customer,callback)
            note=f"[{timezone.localtime(now,KST):%Y-%m-%d %H:%M}] 고객요청으로 인한 삭제"
            customer.notes+=('\n' if customer.notes else '')+note
            customer.deleted_at=now;customer.deleted_by=actor;customer.current_assignment=None;customer.version+=1
            customer.save(update_fields=['notes','deleted_at','deleted_by','current_assignment','version','updated_at'])
            if assignment:
                assignment.ended_at=now;assignment.ended_by=actor;assignment.end_reason='SOFT_DELETED';assignment.save(update_fields=['ended_at','ended_by','end_reason','updated_at'])
            deletion.status='APPROVED';deletion.approved_by=actor;deletion.approved_at=now;deletion.deletion_note=note;deletion.save()
            CustomerChangeEvent.objects.create(customer=customer,assignment=assignment,changed_by=actor,changed_at=now,changed_fields=['notes'])
            ConsultationRevision.objects.create(customer=customer,assignment=assignment,actor=actor,saved_at=now,customer_version=customer.version,
                changed_fields=['notes'],before_values=before,after_values=snapshot(customer,callback),notes=customer.notes,source=ConsultationRevision.Source.SYSTEM_DELETE_NOTE)
            OperationEvent.objects.create(actor=actor,operation='DELETION_APPROVE',occurred_at=now,affected_count=1)
        return remember(actor,'DELETION_APPROVE',key,body_hash,result_for(deletion),target_ids=[customer.pk,customer.site_id])


def notifications(params):
    if set(params)-{'page'}:invalid('알림 페이지를 확인해 주세요.')
    try:page=int(params.get('page','1'))
    except (ValueError,TypeError):page=0
    if not 1<=page<=1000000000:invalid('알림 페이지를 확인해 주세요.')
    with transaction.atomic():
        with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        query=CustomerDeletionRequest.objects.filter(status='PENDING',customer__deleted_at=None).select_related('customer__site','requested_by').order_by('-requested_at','-pk')
        total=query.count();rows=list(query[(page-1)*50:page*50])
        return {'total':total,'page':page,'has_next':page*50<total,'items':[{'id':str(r.pk),'customer_id':str(r.customer_id),'site_name':r.customer.site.name,
            'customer_name':r.customer.customer_name,'phone':r.customer.phone_normalized,'requested_by':r.requested_by.name,'requested_at':r.requested_at.isoformat()} for r in rows]}


def destructive_hash(body):
    # No customer/site name or UUID is retained in a hard-delete receipt body.
    return salted_hmac('tm.p7.hard-delete',json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')),algorithm='sha256').hexdigest()


def erase_receipts(ids):
    for offset in range(0,len(ids),200):
        query=Q(pk__in=[])
        for value in ids[offset:offset+200]:
            value=str(value)
            query|=Q(target_ids__contains=[value])|Q(result__customer_id=value)|Q(result__row__id=value)|Q(result__server_row__id=value)|Q(result__payload__customer_id=value)|Q(result__payload__row__id=value)
        IdempotencyRecord.objects.filter(query).delete()


def scrub_import_sources(customer):
    """Erase matching cached input, retaining other rows and original commit counts."""
    query=ImportRowResult.objects.filter(batch__site_id=customer.site_id).annotate(clean_phone=Func(F('phone_input'),Value('[[:space:]-]'),Value(''),Value('g'),function='regexp_replace',output_field=TextField())).filter(clean_phone=customer.phone_normalized)
    candidates=ImportCandidate.objects.filter(batch__site_id=customer.site_id,normalized_values__phone_normalized=customer.phone_normalized)
    matched=set(query.values_list('batch_id','row_number'))|set(candidates.values_list('batch_id','row_number'))
    for batch_id in sorted({bid for bid,_ in matched}):
        batch=ImportBatch.objects.select_for_update().get(pk=batch_id);numbers=[number for bid,number in matched if bid==batch_id]
        ImportCandidate.objects.filter(batch=batch,row_number__in=numbers).delete()
        update={'customer_name':'','phone_input':'','error_code':'SOURCE_DELETED','reason':'영구 삭제된 고객의 입력 원문을 제거했습니다.'}
        if batch.status!='COMMITTED':update['success']=False
        ImportRowResult.objects.filter(batch=batch,row_number__in=numbers).update(**update)
        if batch.status=='VALIDATED':
            from apps.imports.services import counts_for
            batch.validation_summary=counts_for(list(batch.row_results.values('success','error_code')))
            batch.failure_count=batch.total_count-batch.validation_summary['ready'];batch.save(update_fields=['validation_summary','failure_count','updated_at'])


def erase_customers(customers,*,site_id=None):
    from apps.ai_assistant.privacy import erase_sources
    erase_sources([c.pk for c in customers],site_id=site_id)
    for customer in customers:
        if site_id is None:scrub_import_sources(customer)
    ids=[c.pk for c in customers]
    erase_receipts([*ids,*([site_id] if site_id else [])])
    Customer.objects.filter(pk__in=ids).update(current_assignment=None)
    Customer.objects.filter(pk__in=ids).delete()


@retry_transient_write
def hard_delete_customer(actor,cid,body):
    if set(body)!={'expected_version','idempotency_key','confirm'} or body.get('confirm') is not True:invalid('영구 삭제 확인이 필요합니다.')
    if type(body['expected_version']) is not int or body['expected_version']<1:invalid('고객 버전을 확인해 주세요.')
    key=identifier(body['idempotency_key']);body_hash=destructive_hash({'customer_id':str(cid),**body})
    with business_write():
        actor=locked_actor(actor,admin=True)
        cached=replay(actor,'CUSTOMER_HARD_DELETE',key,body_hash)
        if cached:return cached
        meta=Customer.objects.filter(pk=cid).values('site_id').first()
        if not meta:raise AccessError('CUSTOMER_DELETED','고객정보가 삭제되었거나 존재하지 않습니다.',409)
        Site.objects.select_for_update().get(pk=meta['site_id'])
        customer=Customer.objects.select_for_update().get(pk=cid)
        if not customer.deleted_at:raise AccessError('FORBIDDEN','휴지통의 고객만 영구 삭제할 수 있습니다.')
        if customer.version!=body['expected_version']:raise AccessError('VERSION_CONFLICT','고객정보가 변경되었습니다. 다시 확인해 주세요.',409)
        list(Assignment.objects.select_for_update().filter(customer=customer).order_by('pk'))
        erase_customers([customer])
        OperationEvent.objects.create(actor=actor,operation='CUSTOMER_HARD_DELETE',occurred_at=timezone.now(),affected_count=1)
        return remember(actor,'CUSTOMER_HARD_DELETE',key,body_hash,{'ok':True,'affected_count':1})


@retry_transient_write
def hard_delete_site(actor,sid,body):
    if set(body)!={'confirmation','idempotency_key'} or not isinstance(body['confirmation'],str):invalid('현장명 확인이 필요합니다.')
    key=identifier(body['idempotency_key']);body_hash=destructive_hash({'site_id':str(sid),**body})
    with business_write():
        actor=locked_actor(actor,admin=True,extra_ids=list(User.objects.values_list('pk',flat=True)))
        cached=replay(actor,'SITE_HARD_DELETE',key,body_hash)
        if cached:return cached
        config=locked_settings();sites=list(Site.objects.select_for_update().order_by('pk'));site=next((s for s in sites if s.pk==sid),None)
        if not site:raise AccessError('SITE_DELETED','현장이 삭제되었거나 존재하지 않습니다.',409)
        try:proof=signing.loads(body['confirmation'],salt='tm.site-delete',max_age=7*86400)
        except signing.BadSignature:invalid('현장명 확인이 만료되거나 올바르지 않습니다. 다시 확인해 주세요.')
        if proof!={'actor':str(actor.pk),'site':str(sid),'key':str(key),'stamp':site.updated_at.isoformat()}:invalid('현장 정보를 다시 확인해 주세요.')
        customers=list(Customer.objects.select_for_update().filter(site=site).order_by('pk'))
        list(Assignment.objects.select_for_update().filter(customer__site=site).order_by('pk'))
        erase_customers(customers,site_id=sid)
        from apps.sites.services import change_default
        if config.default_site_id==sid:
            replacement=Site.objects.exclude(pk=sid).order_by('created_at','pk').first()
            change_default(config,replacement,actor,timezone.now())
        site.delete()
        OperationEvent.objects.create(actor=actor,operation='SITE_HARD_DELETE',occurred_at=timezone.now(),affected_count=len(customers))
        return remember(actor,'SITE_HARD_DELETE',key,body_hash,{'ok':True,'affected_count':len(customers)})


def confirm_site(actor,sid,body):
    if actor.role!=User.Role.ADMIN:raise AccessError('FORBIDDEN','관리자 권한이 필요합니다.')
    if set(body)!={'confirm_name','idempotency_key'} or not isinstance(body['confirm_name'],str):invalid('현장명을 정확히 입력해 주세요.')
    key=identifier(body['idempotency_key'])
    site=Site.objects.filter(pk=sid).first()
    if not site:raise AccessError('SITE_DELETED','현장이 삭제되었거나 존재하지 않습니다.',409)
    if body['confirm_name']!=site.name:invalid('현장명을 정확히 입력해 주세요.')
    token=signing.dumps({'actor':str(actor.pk),'site':str(sid),'key':str(key),'stamp':site.updated_at.isoformat()},salt='tm.site-delete')
    return {'confirmation':token}
