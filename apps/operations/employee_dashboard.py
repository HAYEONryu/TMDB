"""Employee work cohorts and paged customer details, scoped to current ownership."""
from datetime import datetime, time, timedelta

from django.db import connection, transaction
from django.db.models import Case, Count, DateTimeField, Exists, F, OuterRef, Q, When
from django.db.models.functions import Least
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.accounts.access import AccessError, actor_identity, require_role
from apps.accounts.models import User
from apps.callbacks.models import Callback
from apps.common.http import api_errors, identifier
from apps.consultations.models import ConsultationRevision
from apps.customers.choices import customer_schema
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.customers.queries import KST, enriched, integer, serialize
from apps.customers.cohorts import current_customers as current_cohort, category_filter, CATEGORIES
from apps.consultations.queries import consultation_saves
from apps.sites.models import GlobalSettings, Site


def current_customers(person, site_id, now):
    return current_cohort(site_id, now, person)


def new_today(start, end):
    return Q(current_assignment__assigned_at__gte=start, current_assignment__assigned_at__lt=end)


def daily_report(person, site_id, start, end, now):
    live = current_customers(person, site_id, now)
    callbacks = Callback.objects.filter(customer_id=OuterRef('pk'), due_at__lt=end)
    completed = callbacks.filter(status='COMPLETED', completed_by=person,
        completed_at__gte=start, completed_at__lte=now)
    pending = callbacks.filter(status='PENDING')
    saves = consultation_saves().filter(customer_id=OuterRef('pk'),
        assignment_id=OuterRef('current_assignment_id'), actor=person,
        saved_at__gte=start, saved_at__lte=now, source__in=['MANUAL', 'AI_APPLIED'])
    work = live.annotate(due_callback=Exists(pending), completed_callback=Exists(completed),
        saved_consultation=Exists(saves)).filter(new_today(start, end) | Q(due_callback=True) | Q(completed_callback=True))
    total = work.count()
    done = work.filter((new_today(start, end) & Q(saved_consultation=True)) | Q(completed_callback=True)).count()
    counts = live.annotate(
        callback_today=Exists(pending.filter(due_at__gte=start)),
        callback_past=Exists(pending.filter(due_at__lt=start)),
        callback_remaining=Exists(pending.filter(due_at__gte=now)),
        callback_overdue=Exists(pending.filter(due_at__lt=now)),
        saved_today=Exists(saves)).aggregate(
            held_total=Count('pk'),
            current_assignment_today_held=Count('pk', filter=new_today(start, end)),
            callbacks_today=Count('pk', filter=Q(callback_today=True)),
            callbacks_remaining=Count('pk', filter=Q(callback_remaining=True)),
            callbacks_overdue=Count('pk', filter=Q(callback_overdue=True)),
            consultations_today=Count('pk', filter=new_today(start,end)&Q(saved_today=True)),
            callbacks_past_due=Count('pk', filter=Q(callback_past=True)),
            visits_today=Count('pk', filter=Q(visit_at__gte=start, visit_at__lt=end)),
            contracted_held=Count('pk', filter=Q(contract_status='CONTRACTED')))
    completed_count=Callback.objects.filter(customer__site_id=site_id,status='COMPLETED',completed_by=person,completed_at__gte=start,completed_at__lte=now).count()
    return {**counts, 'consultation_progress': {'completed':counts['consultations_today'],'total':counts['current_assignment_today_held']},
        'callbacks_completed_today':completed_count, 'tm': {'total': total, 'completed': done,
            'percent': round(done * 100 / total, 1) if total else 0},
        'site_contracted_total': Customer.objects.filter(site_id=site_id, deleted_at=None, contract_status='CONTRACTED').count()}


@require_GET
@require_role(User.Role.EMPLOYEE)
@api_errors
def customer_details(request):
    optional_queue_identity(request)
    actor_identity(request)
    if set(request.GET) - {'site_id', 'category', 'page'} or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise AccessError('VALIDATION_ERROR', '고객 목록 조회 조건을 확인해 주세요.', 422)
    category = request.GET.get('category', 'held')
    if category not in CATEGORIES | {'scheduled'}:
        raise AccessError('VALIDATION_ERROR', '고객 목록 종류를 확인해 주세요.', 422)
    page = integer(request.GET, 'page', 1)
    if not 1 <= page <= 1000000000:
        raise AccessError('VALIDATION_ERROR', '페이지는 1 이상이어야 합니다.', 422)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        selected = request.GET.get('site_id')
        site_id = identifier(selected) if selected else GlobalSettings.objects.filter(pk=1).values_list('default_site_id', flat=True).first()
        if site_id and not Site.objects.filter(pk=site_id).exists():
            raise AccessError('SITE_DELETED', '현장이 삭제되었거나 존재하지 않습니다.', 409)
        now = timezone.now()
        start = datetime.combine(timezone.localdate(now, KST), time.min, KST)
        end = start + timedelta(days=1)
        query = enriched(current_customers(request.user, site_id, now).defer('admin_notes'))
        if category == 'scheduled':
            callback_today = Q(callback_due_at__gte=start, callback_due_at__lt=end)
            visit_today = Q(visit_at__gte=start, visit_at__lt=end)
            query = query.filter(callback_today | visit_today).annotate(scheduled_at=Least(
                Case(When(callback_today, then=F('callback_due_at')), output_field=DateTimeField()),
                Case(When(visit_today, then=F('visit_at')), output_field=DateTimeField())))
        else:
            query = category_filter(query, category, now)
        sort = 'scheduled_at' if category == 'scheduled' else 'visit_at' if category == 'visits' else 'callback_due_at' if category in {'callbacks_today', 'callbacks_remaining', 'overdue'} else 'assigned_at' if category == 'new_today' else 'customer_name'
        total = query.count()
        last_page = max(1, (total + 9) // 10)
        page = min(page, last_page)
        rows = query.order_by(sort, 'pk')[(page - 1) * 10:page * 10]
        data = {'data': [serialize(row) for row in rows], 'schema': customer_schema(),
            'category': category, 'total': total, 'page': page, 'last_page': last_page,
            'site_id': str(site_id) if site_id else None, 'business_date': start.date().isoformat(), 'as_of':now.isoformat()}
    return JsonResponse(data)
