"""Employee work cohorts and paged customer details, scoped to current ownership."""
from datetime import datetime, time, timedelta

from django.db import connection, transaction
from django.db.models import Count, Exists, OuterRef, Q
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
from apps.sites.models import GlobalSettings, Site


def current_customers(person, site_id, now):
    return Customer.objects.filter(site_id=site_id, deleted_at=None,
        current_assignment__employee=person, current_assignment__ended_at=None,
        current_assignment__assigned_at__lte=now)


def new_today(start, end):
    return Q(current_assignment__assigned_at__gte=start, current_assignment__assigned_at__lt=end)


def daily_report(person, site_id, start, end, now):
    live = current_customers(person, site_id, now)
    callbacks = Callback.objects.filter(customer_id=OuterRef('pk'), due_at__lt=end)
    completed = callbacks.filter(status='COMPLETED', completed_by=person,
        completed_at__gte=start, completed_at__lte=now)
    pending = callbacks.filter(status='PENDING')
    saves = ConsultationRevision.objects.filter(customer_id=OuterRef('pk'),
        assignment_id=OuterRef('current_assignment_id'), actor=person,
        saved_at__gte=start, saved_at__lte=now, source__in=['MANUAL', 'AI_APPLIED'])
    saves = saves.exclude(changed_fields__contained_by=['customer_name', 'phone_normalized', 'admin_notes'])
    work = live.annotate(due_callback=Exists(pending), completed_callback=Exists(completed),
        saved_consultation=Exists(saves)).filter(new_today(start, end) | Q(due_callback=True) | Q(completed_callback=True))
    total = work.count()
    done = work.filter((new_today(start, end) & Q(saved_consultation=True)) | Q(completed_callback=True)).count()
    counts = live.annotate(
        callback_today=Exists(pending.filter(due_at__gte=start)),
        callback_past=Exists(pending.filter(due_at__lt=start))).aggregate(
            held_total=Count('pk'),
            current_assignment_today_held=Count('pk', filter=new_today(start, end)),
            callbacks_today=Count('pk', filter=Q(callback_today=True)),
            callbacks_past_due=Count('pk', filter=Q(callback_past=True)),
            visits_today=Count('pk', filter=Q(visit_at__gte=start, visit_at__lt=end)),
            contracted_held=Count('pk', filter=Q(contract_status='CONTRACTED')))
    return {**counts, 'tm': {'total': total, 'completed': done,
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
    if category not in {'held', 'callbacks_today', 'new_today', 'overdue', 'visits'}:
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
        if category == 'callbacks_today': query = query.filter(callback_due_at__gte=start, callback_due_at__lt=end)
        elif category == 'overdue': query = query.filter(callback_due_at__lt=start)
        elif category == 'new_today': query = query.filter(new_today(start, end))
        elif category == 'visits': query = query.filter(visit_at__gte=start, visit_at__lt=end)
        sort = 'visit_at' if category == 'visits' else 'callback_due_at' if category in {'callbacks_today', 'overdue'} else 'customer_name'
        total = query.count()
        last_page = max(1, (total + 9) // 10)
        page = min(page, last_page)
        rows = query.order_by(sort, 'pk')[(page - 1) * 10:page * 10]
        data = {'data': [serialize(row) for row in rows], 'schema': customer_schema(),
            'category': category, 'total': total, 'page': page, 'last_page': last_page,
            'site_id': str(site_id) if site_id else None, 'business_date': start.date().isoformat()}
    return JsonResponse(data)
