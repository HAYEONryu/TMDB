"""TM completion evidence for the current assignment, never inferred from state."""
from django.db.models import BooleanField, Case, CharField, Exists, OuterRef, Subquery, Value, When
from django.utils import timezone
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.consultations.models import CustomerActivity
from apps.customers.cohorts import day_bounds
from apps.customers.models import Customer

HUMAN_SOURCES = ['MANUAL', 'AI_APPLIED']


def with_tm_state(query, now=None, *, include_today=False, include_call_date=False):
    now = now or timezone.now()
    start, end = day_bounds(now)
    calls = ConsultationRevision.objects.filter(
        customer_id=OuterRef('pk'), assignment_id=OuterRef('current_assignment_id'),
        actor_id=OuterRef('current_assignment__employee_id'),
        saved_at__gte=OuterRef('current_assignment__assigned_at'), saved_at__lte=now,
        source__in=HUMAN_SOURCES, changed_fields__contains=['call_result'])
    due = Callback.objects.filter(customer_id=OuterRef('pk'), status='PENDING', due_at__lt=end)
    # An explicit clear supersedes older completion evidence. Version breaks ties
    # when multiple confirmed saves have the same timestamp; notes never override.
    latest = calls.order_by('-saved_at', '-customer_version', '-pk')
    query = query.annotate(tm_latest_call_result=Subquery(latest.values('after_values__call_result')[:1]),
                           tm_due_pending=Exists(due))
    query = query.annotate(tm_initial_done=Case(
        When(tm_latest_call_result__in=Customer.CallResult.values, then=Value(True)),
        default=Value(False), output_field=BooleanField()))
    query = query.annotate(tm_status=Case(
        When(tm_initial_done=True, tm_due_pending=False, then=Value('COMPLETED')),
        default=Value('PENDING'), output_field=CharField()))
    if include_call_date:
        attempts = CustomerActivity.objects.filter(customer_id=OuterRef('pk'),
            assignment_id=OuterRef('current_assignment_id'), actor_id=OuterRef('current_assignment__employee_id'),
            site_id=OuterRef('site_id'), kind='CALL', occurred_at__gte=OuterRef('current_assignment__assigned_at'),
            occurred_at__lte=now).order_by('-occurred_at', '-pk')
        query = query.annotate(last_tm_at=Subquery(attempts.values('occurred_at')[:1]))
    if not include_today:
        return query
    # Callback lacks an assignment FK. Its completion service writes a revision
    # at exactly completed_at, with the current assignment/actor. Require both.
    completion_revision = ConsultationRevision.objects.filter(
        customer_id=OuterRef('customer_id'), assignment_id=OuterRef(OuterRef('current_assignment_id')),
        actor_id=OuterRef('completed_by_id'), saved_at=OuterRef('completed_at'),
        source__in=HUMAN_SOURCES, changed_fields__contains=['callback_due_at'],
        after_values__callback_due_at=None)
    completed = Callback.objects.filter(customer_id=OuterRef('pk'), status='COMPLETED',
        completed_by_id=OuterRef('current_assignment__employee_id'),
        completed_at__gte=start, completed_at__lte=now, due_at__lt=end
    ).filter(completed_at__gte=OuterRef('current_assignment__assigned_at')
    ).filter(Exists(completion_revision))
    return query.annotate(tm_call_done_today=Exists(calls.filter(saved_at__gte=start,
                              after_values__call_result__in=Customer.CallResult.values)),
                          tm_callback_done_today=Exists(completed))
