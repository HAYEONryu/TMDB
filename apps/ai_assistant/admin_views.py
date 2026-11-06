"""Explicit admin generation and reviewed, versioned guide publication."""
from datetime import timedelta
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from apps.accounts.access import require_role, actor_identity, AccessError
from apps.accounts.models import User
from apps.common.http import api_errors, json_object, identifier
from apps.common.transactions import business_write
from apps.customers.models import Customer
from apps.operations.models import IdempotencyRecord, OperationEvent
from apps.sites.models import Site
from apps.sites.services import locked_actor
from .inputs import digest, sanitize
from .models import AIRequest, AIResult, AIResultSource, Feature, GuidePublication, SiteKnowledge
from .services import reserve
from .views import task_payload


@require_GET
@require_role(User.Role.ADMIN)
def page(request):return render(request,'ai/admin.html')


@require_GET
@require_role()
def published_page(request):return render(request,'ai/published.html')


@require_GET
@require_role(User.Role.ADMIN)
def case_page(request,customer_id):
    return render(request,'ai/case.html',{'customer':get_object_or_404(Customer,pk=customer_id)})


@require_http_methods(['GET','POST'])
@require_role(User.Role.ADMIN)
@api_errors
def reports(request,feature,employee_id=None,site_id=None):
    actor_identity(request)
    query=AIRequest.objects.filter(feature=feature).select_related('result')
    if employee_id:
        if not User.objects.filter(pk=employee_id,role='EMPLOYEE').exists():raise AccessError('NOT_FOUND','직원이 없습니다.',404)
        query=query.filter(employee_id=employee_id)
    if site_id:
        if not Site.objects.filter(pk=site_id).exists():raise AccessError('SITE_DELETED','현장이 없습니다.',409)
        query=query.filter(site_id=site_id)
    if request.method=='GET':
        try:page=int(request.GET.get('page','1'))
        except ValueError:page=0
        if set(request.GET)-{'page'} or not 1<=page<=1000000:raise AccessError('VALIDATION_ERROR','페이지를 확인해 주세요.',422)
        total=query.count()
        return JsonResponse({'items':[task_payload(r) for r in query.order_by('-created_at','-pk')[(page-1)*20:page*20]],'page':page,'has_next':page*20<total})
    body=json_object(request)
    if set(body)!={'idempotency_key'}:raise AccessError('VALIDATION_ERROR','요청 키만 보내 주세요.',422)
    body['feature']=feature
    if employee_id:body['employee_id']=str(employee_id)
    if site_id:body['site_id']=str(site_id)
    task,new=reserve(request.user,body)
    return JsonResponse({**task_payload(task),'task_id':str(task.pk),'cached':not new},status=202 if task.status in ['RESERVED','RUNNING','UNKNOWN'] else 200)


def guide_data(result):
    return {'result_id':str(result.pk),'body':result.guide_body,'version':result.guide_version,'status':result.guide_status,
            'reviewed':result.guide_reviewed_version==result.guide_version,'reviewed_at':result.reviewed_at.isoformat() if result.reviewed_at else None,
            'published_at':result.published_at.isoformat() if result.published_at else None,'is_test':result.request.is_test}


def validate_guide_body(body,site_id):
    from .admin_schema import BANNED
    if not isinstance(body,str) or not 1<=len(body)<=20000 or BANNED.search(body):raise AccessError('VALIDATION_ERROR','가이드는 개인정보·외부 링크 없는 일반 상담 안내로 작성해 주세요.',422)
    names=list(Customer.objects.values_list('customer_name',flat=True))+list(User.objects.values_list('name',flat=True))
    if sanitize(body,names)!=body:raise AccessError('GUIDE_PRIVATE_CONTENT','개인 식별 내용은 게시할 수 없습니다.',422)
    knowledge=list(SiteKnowledge.objects.filter(site_id=site_id,is_valid=True,reviewed_at__isnull=False))
    # Amount/date/benefit assertions must be verbatim sentences in reviewed internal material.
    import re
    facts='\n'.join(k.body for k in knowledge)
    for line in body.splitlines():
        if re.search(r'\d|확정|보장|무료|혜택|할인',line) and line.strip() not in facts:
            raise AccessError('GUIDE_FACT_UNVERIFIED','가격·일정·혜택 문구는 검토된 안내자료 원문을 사용해 주세요.',422)
    return knowledge


@require_http_methods(['PATCH','POST'])
@require_role(User.Role.ADMIN)
@api_errors
def guide_write(request,result_id,publish=False):
    actor_identity(request);body=json_object(request)
    expected={'expected_version','idempotency_key'}| (set() if publish else {'body','reviewed'})
    if set(body)!=expected or type(body['expected_version']) is not int or body['expected_version']<1 or (not publish and type(body['reviewed']) is not bool):raise AccessError('VALIDATION_ERROR','가이드 버전과 검토 여부를 확인해 주세요.',422)
    if (publish and request.method!='POST') or (not publish and request.method!='PATCH'):raise AccessError('METHOD_NOT_ALLOWED','요청 방식을 확인해 주세요.',405)
    key=identifier(body['idempotency_key']);hashed=digest(body);operation='AI_GUIDE_PUBLISH' if publish else 'AI_GUIDE_EDIT'
    with business_write():
        actor=locked_actor(request.user,admin=True)
        result=AIResult.objects.select_for_update().select_related('request').filter(pk=result_id,request__feature=Feature.TEAM_GUIDE).first()
        if not result:raise AccessError('NOT_FOUND','가이드가 없습니다.',404)
        if not result.valid or result.request.status!='SUCCEEDED' or not result.request.site_id:raise AccessError('AI_RESULT_INVALID','원본이 무효화된 가이드입니다.',409)
        receipt=IdempotencyRecord.objects.filter(actor=actor,operation=operation,key=key).first()
        if receipt:
            if receipt.expires_at<=timezone.now():raise AccessError("IDEMPOTENCY_EXPIRED","요청 보관 기간이 지났습니다. 현재 상태를 다시 확인해 주세요.",409)
            if receipt.body_hash!=hashed or str(result_id) not in receipt.target_ids:raise AccessError('IDEMPOTENCY_CONFLICT','요청 키의 내용이 다릅니다.',409)
            return JsonResponse(receipt.result)
        if result.guide_version!=body['expected_version']:raise AccessError('VERSION_CONFLICT','최신 가이드를 다시 조회해 주세요.',409)
        now=timezone.now()
        if publish:
            if result.guide_reviewed_version!=result.guide_version or not result.reviewed_by_id:raise AccessError('GUIDE_REVIEW_REQUIRED','현재 버전의 관리자 검토 후 게시할 수 있습니다.',409)
            validate_guide_body(result.guide_body,result.request.site_id)
            GuidePublication.objects.update_or_create(site_id=result.request.site_id,defaults={'result':result,'body':result.guide_body,'version':result.guide_version,'published_by':actor,'published_at':now,'is_test':result.request.is_test})
            result.guide_status='PUBLISHED';result.published_at=now
        else:
            knowledge=validate_guide_body(body['body'],result.request.site_id)
            result.guide_body=body['body'];result.guide_version+=1;result.guide_status='DRAFT'
            result.reviewed_by=actor if body['reviewed'] else None;result.reviewed_at=now if body['reviewed'] else None
            result.guide_reviewed_version=result.guide_version if body['reviewed'] else None
            existing=set(result.sources.filter(knowledge__isnull=False).values_list('knowledge_id',flat=True))
            AIResultSource.objects.bulk_create([AIResultSource(result=result,knowledge=k,source_version=k.version) for k in knowledge if k.pk not in existing])
        result.save();data=guide_data(result)
        IdempotencyRecord.objects.create(actor=actor,operation=operation,key=key,body_hash=hashed,result={k:v for k,v in data.items() if k!='body'},target_ids=[str(result.pk),str(result.request.site_id)],expires_at=now+timedelta(days=7))
        # Receipts deliberately contain no draft/customer text. Replay returns metadata; read latest result for body.
        OperationEvent.objects.create(actor=actor,operation=operation,occurred_at=now,affected_count=1)
        return JsonResponse({k:v for k,v in data.items() if k!='body'})


@require_GET
@require_role()
@api_errors
def published(request,site_id):
    actor_identity(request)
    if not Site.objects.filter(pk=site_id).exists():raise AccessError('SITE_DELETED','현장이 없습니다.',409)
    publication=GuidePublication.objects.select_related('result').filter(site_id=site_id,result__valid=True).first()
    if not publication:return JsonResponse({'available':False,'message':'관리자가 검토·게시한 가이드가 없습니다.'})
    return JsonResponse({'available':True,'body':publication.body,'version':publication.version,'site_id':str(site_id),
                         'published_at':publication.published_at.isoformat(),'is_test':publication.is_test,'test_message':'테스트 전용 가짜 결과이며 운영 안내가 아닙니다.' if publication.is_test else ''})
