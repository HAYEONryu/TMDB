"""Read-only current-state cohorts shared by dashboards and customer lists."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q

from apps.customers.models import Customer

KST = ZoneInfo('Asia/Seoul')
CATEGORIES = {'held', 'new_today', 'overdue', 'callbacks_remaining', 'callbacks_today', 'visits', 'unprogressed', 'contracted'}


def day_bounds(now):
    start = datetime.combine(now.astimezone(KST).date(), time.min, KST)
    return start, start + timedelta(days=1)


def valid_assignment(now):
    return Q(current_assignment__isnull=False, current_assignment__ended_at__isnull=True,
             current_assignment__assigned_at__lte=now)


def current_customers(site_id, now, person=None):
    query = Customer.objects.filter(valid_assignment(now), site_id=site_id, deleted_at__isnull=True)
    return query.filter(current_assignment__employee=person) if person is not None else query


def category_filter(query, category, now):
    """The query must already annotate callback_due_at from pending callbacks."""
    start, end = day_bounds(now)
    query = query.filter(valid_assignment(now), deleted_at__isnull=True)
    if category == 'new_today':
        return query.filter(current_assignment__assigned_at__gte=start)
    if category == 'overdue':
        return query.filter(callback_due_at__lt=now)
    if category == 'callbacks_remaining':
        return query.filter(callback_due_at__gte=now, callback_due_at__lt=end)
    if category == 'callbacks_today':
        return query.filter(callback_due_at__gte=start, callback_due_at__lt=end)
    if category == 'visits':
        return query.filter(visit_at__gte=start, visit_at__lt=end)
    if category == 'unprogressed':
        return query.filter(current_assignment__first_activity_at__isnull=True)
    if category == 'contracted':
        return query.filter(contract_status='CONTRACTED')
    return query
