"""Latest explicit result change per employee/customer/Korean day; no state inference."""
import re
from datetime import date, datetime, time, timedelta
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from apps.accounts.access import AccessError, actor_identity, require_role
from apps.accounts.models import User
from apps.common.http import api_errors, identifier
from apps.consultations.models import ConsultationRevision
from apps.consultations.queries import audit_started_at
from apps.customers.cohorts import KST
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.sites.models import GlobalSettings, Site

RESULTS = [('NO_ANSWER','부재'),('DELETE_REQUEST','삭제요망'),('REJECTED','거절'),
           ('NEXT_SITE','다음현장 연락'),('INTERESTED','가망고객')]


def daily_results(actor, site_id, day, now):
    start=datetime.combine(day,time.min,KST);end=start+timedelta(days=1)
    beginning=audit_started_at()
    available=beginning is not None and day>=beginning.astimezone(KST).date()
    status='partial' if available and day==beginning.astimezone(KST).date() and beginning.astimezone(KST).time()!=time.min else 'available' if available else 'unavailable'
    counts={code:0 for code,_ in RESULTS}
    if available:
        latest=ConsultationRevision.objects.filter(actor=actor,customer__site_id=site_id,
            source__in=['MANUAL','AI_APPLIED'],changed_fields__contains=['call_result'],
            saved_at__gte=start,saved_at__lt=end,saved_at__lte=now
        ).order_by('customer_id','-saved_at','-customer_version','-pk').distinct('customer_id').values_list('after_values',flat=True)
        for snapshot in latest.iterator(chunk_size=2000):
            if not isinstance(snapshot,dict) or 'call_result' not in snapshot or snapshot['call_result'] not in [None,'',*Customer.CallResult.values]:
                status='unavailable'
            elif snapshot['call_result'] in counts:
                counts[snapshot['call_result']]+=1
    return {'date':day.isoformat(),'status':status,'coverage_from':beginning.isoformat() if beginning else None,
        'earliest_date':beginning.astimezone(KST).date().isoformat() if beginning else None,
        'items':[{'code':code,'label':label,'count':None if status=='unavailable' else counts[code]} for code,label in RESULTS]}


@require_GET
@require_role(User.Role.EMPLOYEE)
@api_errors
def daily(request):
    optional_queue_identity(request);actor_identity(request)
    if set(request.GET)-{'site_id','date'} or any(len(request.GET.getlist(k))!=1 for k in request.GET):
        raise AccessError('VALIDATION_ERROR','현장과 조회 날짜만 선택해 주세요.',422)
    with transaction.atomic():
        with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        now=timezone.now();today=now.astimezone(KST).date();value=request.GET.get('date',today.isoformat())
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):raise ValueError()
            day=date.fromisoformat(value)
        except ValueError:raise AccessError('VALIDATION_ERROR','조회 날짜는 YYYY-MM-DD 형식으로 선택해 주세요.',422)
        if day>today:raise AccessError('VALIDATION_ERROR','오늘 또는 이전 날짜를 선택해 주세요.',422)
        selected=request.GET.get('site_id')
        site_id=identifier(selected) if selected else GlobalSettings.objects.filter(pk=1).values_list('default_site_id',flat=True).first()
        if site_id and not Site.objects.filter(pk=site_id).exists():raise AccessError('SITE_DELETED','현장이 삭제되었거나 존재하지 않습니다.',409)
        data=daily_results(request.user,site_id,day,now)
        data.update(site_id=str(site_id) if site_id else None,business_date=today.isoformat(),as_of=now.isoformat())
    return JsonResponse(data)
