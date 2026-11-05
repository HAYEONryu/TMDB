from datetime import datetime,time,timedelta
from django.db import transaction,connection
from django.db.models import Count,Q,F,Exists,OuterRef
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from apps.accounts.access import AccessError,require_role,actor_identity
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.http import api_errors,identifier
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.sites.models import Site,GlobalSettings


def employee_counts(person,site_id,start,end,now):
    history=Assignment.objects.filter(customer__site_id=site_id,employee=person,assigned_at__gte=start,assigned_at__lt=end)
    ids=history.values('customer_id').distinct()
    live=Customer.objects.filter(site_id=site_id,deleted_at=None,current_assignment__employee=person,current_assignment__ended_at=None)
    held=live.filter(pk__in=ids)
    results={value:0 for value in [None,*Customer.CallResult.values]}
    for row in held.values('call_result').annotate(count=Count('pk')):results[row['call_result']]=row['count']
    callbacks=live.filter(Exists(Callback.objects.filter(customer_id=OuterRef('pk'),status='PENDING',due_at__lt=end)))
    return {'id':str(person.pk),'name':person.name,'assigned_today_unique':history.values('customer_id').distinct().count(),'assignment_operations_today':history.count(),
        'held_total':live.count(),'assigned_today_held':held.count(),'assigned_today_removed':history.values('customer_id').distinct().count()-held.count(),
        'unprogressed_total':live.filter(current_assignment__first_activity_at=None).count(),'unprogressed_today_held':held.filter(current_assignment__first_activity_at=None).count(),
        'current_assignment_today_held':live.filter(current_assignment__assigned_at__gte=start,current_assignment__assigned_at__lt=end).count(),
        'call_results':[{'value':value,'label':'(빈 값)' if value is None else Customer.CallResult(value).label,'count':count} for value,count in results.items()],
        'callbacks_due_today_or_past':callbacks.count(),'callbacks_overdue':live.filter(Exists(Callback.objects.filter(customer_id=OuterRef('pk'),status='PENDING',due_at__lt=now))).count()}


@require_GET
@require_role()
@api_errors
def dashboard(request):
    optional_queue_identity(request)
    actor_identity(request)
    if set(request.GET)-{'site_id'}:raise AccessError('VALIDATION_ERROR','현장만 선택해 주세요.',422)
    selected=request.GET.get('site_id')
    # All metrics in one read snapshot, without the business write lock.
    with transaction.atomic():
        with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        site_id=identifier(selected) if selected else GlobalSettings.objects.filter(pk=1).values_list('default_site_id',flat=True).first()
        site=Site.objects.filter(pk=site_id).first() if site_id else None
        if site_id and not site:raise AccessError('SITE_DELETED','현장이 삭제되었거나 존재하지 않습니다.',409)
        now=timezone.now();start=datetime.combine(timezone.localdate(now,KST),time.min,KST);end=start+timedelta(days=1)
        data={'site_id':str(site.pk) if site else None,'business_date':start.date().isoformat(),'as_of':now.isoformat()}
        if request.user.role==User.Role.ADMIN:
            rows=User.objects.filter(role='EMPLOYEE',is_active=True).order_by('created_at','pk')
            data['employees']=[employee_counts(p,site_id,start,end,now) for p in rows]
            query=Customer.objects.filter(site_id=site_id)
            data['counts']=query.aggregate(total=Count('pk',filter=Q(deleted_at=None)),unassigned=Count('pk',filter=Q(deleted_at=None,current_assignment=None)),trash=Count('pk',filter=Q(deleted_at__isnull=False)))
            data['transfer_needed']=query.filter(deleted_at=None,current_assignment__employee__is_active=False,current_assignment__first_activity_at__isnull=False).count()
        else:data['employee']=employee_counts(request.user,site_id,start,end,now)
    return JsonResponse(data)
