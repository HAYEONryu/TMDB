"""Monthly evidence counts: never infer calls/actual visits from current state."""
import calendar
import re
from datetime import date, datetime, time, timedelta
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from apps.accounts.access import AccessError, actor_identity, require_role
from apps.accounts.models import User
from apps.common.http import api_errors, identifier
from apps.consultations.models import CustomerActivity, PerformanceTracking
from apps.consultations.queries import consultation_saves
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.sites.models import GlobalSettings, Site


def performance(person, site_id, month, now):
    today = now.astimezone(KST).date()
    start = datetime.combine(month, time.min, KST)
    end = start + timedelta(days=calendar.monthrange(month.year, month.month)[1])
    tracking = PerformanceTracking.objects.filter(pk=1).values_list('started_at', flat=True).first()
    # The original revision table has always audited manual/AI-applied saves.
    audit_start = MigrationRecorder.Migration.objects.filter(app='consultations', name='0001_initial').values_list('applied', flat=True).first()
    saves = consultation_saves().filter(actor=person, customer__site_id=site_id, saved_at__lte=now)
    # An isolated backdated revision does not prove coverage of earlier days.
    prospect_start = audit_start
    calls = CustomerActivity.objects.filter(actor=person, site_id=site_id, kind='CALL', occurred_at__lte=now)
    call_days = {r['day']: r for r in calls.filter(occurred_at__gte=start, occurred_at__lt=end)
        .annotate(day=TruncDate('occurred_at', tzinfo=KST)).values('day').annotate(count=Count('pk'))}
    prospects = {r['day']: r['count'] for r in saves.filter(saved_at__gte=start, saved_at__lt=end,
        after_values__call_result=Customer.CallResult.INTERESTED)
        .annotate(day=TruncDate('saved_at', tzinfo=KST)).values('day').annotate(count=Count('customer_id', distinct=True))}
    visits = {r['visited_on']: r['count'] for r in CustomerActivity.objects.filter(actor=person, site_id=site_id,
        kind='VISIT', visited_on__gte=month, visited_on__lt=end.date(), visited_on__lte=today)
        .values('visited_on').annotate(count=Count('customer_id', distinct=True))}
    # Missing result snapshots are unknown evidence, never a definite zero.
    incomplete = set(saves.filter(saved_at__gte=start, saved_at__lt=end).exclude(after_values__has_key='call_result')
        .annotate(day=TruncDate('saved_at', tzinfo=KST)).values_list('day', flat=True))
    def status(day, beginning):
        if day > today:
            return 'future'
        if beginning is None or day < beginning.astimezone(KST).date():
            return 'unavailable'
        return 'partial' if day == beginning.astimezone(KST).date() and beginning.astimezone(KST).time() != time.min else 'available'
    rows = []
    for n in range((end-start).days):
        day = month + timedelta(days=n)
        cs, ps = status(day, tracking), status(day, prospect_start)
        if day in incomplete:
            ps = 'unavailable'
        rows.append({'date': day.isoformat(), 'is_future': day > today,
            'call_count': call_days.get(day, {}).get('count', 0) if cs in {'available', 'partial'} else None,
            'prospect_count': prospects.get(day, 0) if ps in {'available', 'partial'} else None,
            'visit_count': visits.get(day, 0) if cs in {'available', 'partial'} else None,
            'call_status': cs, 'prospect_status': ps, 'visit_status': cs})
    today_start = datetime.combine(today, time.min, KST)
    counts = calls.filter(occurred_at__gte=today_start).aggregate(attempts=Count('pk'),
        connected=Count('pk', filter=Q(connection='CONNECTED')))
    available = status(today, tracking) in {'available', 'partial'}
    begins = [v.astimezone(KST).date().replace(day=1) for v in (tracking, prospect_start) if v is not None and v <= now]
    return {'month': month.strftime('%Y-%m'), 'rows': rows,
        'today': {'date': today.isoformat(), 'attempts': counts['attempts'] if available else None,
                  'connected': counts['connected'] if available else None, 'status': status(today, tracking)},
        'coverage': {'calls_from': tracking.isoformat() if tracking else None,
                     'visits_from': tracking.isoformat() if tracking else None,
                     'prospects_from': prospect_start.isoformat() if prospect_start else None},
        'earliest_month': min(begins).strftime('%Y-%m') if begins else today.strftime('%Y-%m')}


@require_GET
@require_role(User.Role.EMPLOYEE)
@api_errors
def monthly(request):
    optional_queue_identity(request)
    actor_identity(request)
    if set(request.GET) - {'site_id', 'month'} or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise AccessError('VALIDATION_ERROR', '현장과 조회 월만 선택해 주세요.', 422)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        now = timezone.now()
        value = request.GET.get('month', now.astimezone(KST).strftime('%Y-%m'))
        if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value) or int(value[:4]) < 1:
            raise AccessError('VALIDATION_ERROR', '조회 월은 YYYY-MM 형식으로 선택해 주세요.', 422)
        selected_month = date.fromisoformat(value+'-01')
        if selected_month > now.astimezone(KST).date().replace(day=1):
            raise AccessError('VALIDATION_ERROR', '이번 달 또는 이전 달을 선택해 주세요.', 422)
        selected = request.GET.get('site_id')
        site_id = identifier(selected) if selected else GlobalSettings.objects.filter(pk=1).values_list('default_site_id', flat=True).first()
        if site_id and not Site.objects.filter(pk=site_id).exists():
            raise AccessError('SITE_DELETED', '현장이 삭제되었거나 존재하지 않습니다.', 409)
        result = performance(request.user, site_id, selected_month, now)
        result.update(site_id=str(site_id) if site_id else None, as_of=now.isoformat(), business_date=now.astimezone(KST).date().isoformat())
    return JsonResponse(result)
