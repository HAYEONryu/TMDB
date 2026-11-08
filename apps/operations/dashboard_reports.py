"""Read-only manager aggregates. No customer text or generated AI is returned."""
from datetime import datetime, time, timedelta
from django.db.models import Count, Q, F, Exists, OuterRef, Subquery, JSONField
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.queries import KST

HUMAN_SAVES = [ConsultationRevision.Source.MANUAL, ConsultationRevision.Source.AI_APPLIED]


def periods(now):
    day = now.astimezone(KST).date()
    today = datetime.combine(day, time.min, KST)
    monday = today-timedelta(days=day.weekday())
    return today, today+timedelta(days=1), monday, monday+timedelta(days=7), today-timedelta(days=6)


def result_rows(counts):
    return [{"value": value, "label": "미입력" if value is None else Customer.CallResult(value).label,
             "count": counts.get(value, 0)} for value in [None, *Customer.CallResult.values]]


def distribution(customers, now, period):
    today, tomorrow, monday, next_monday, _ = periods(now)
    start, end = (today, tomorrow) if period == "today" else (monday, next_monday) if period == "week" else (None, None)
    if period == "all":
        grouped = customers.values("call_result").annotate(count=Count("pk"))
        counts = {row["call_result"]: row["count"] for row in grouped}
    else:
        latest = ConsultationRevision.objects.filter(customer_id=OuterRef("pk"), source__in=HUMAN_SAVES,
            saved_at__gte=start, saved_at__lt=end, saved_at__lte=now).order_by("-saved_at", "-customer_version", "-pk")
        grouped = (customers.annotate(period_saved=Exists(latest),
            result=Subquery(latest.values("after_values__call_result")[:1], output_field=JSONField()))
            .filter(period_saved=True).values("result").annotate(count=Count("pk")))
        counts = {}
        for row in grouped:
            value = row["result"] if row["result"] in Customer.CallResult.values else None
            counts[value] = counts.get(value, 0)+row["count"]
    rows = result_rows(counts)
    return {"period": period, "start": start.isoformat() if start else None,
            "end_exclusive": end.isoformat() if end else None, "as_of": now.isoformat(),
            "total": sum(row["count"] for row in rows), "results": rows,
            "basis": "선택 현장의 현재 상태" if period == "all" else "기간 내 저장 고객별 마지막 상담결과"}


def manager_report(site_id, now, result_period):
    today, tomorrow, _, _, seven_start = periods(now)
    customers = Customer.objects.filter(site_id=site_id, deleted_at=None)
    history = Assignment.objects.filter(customer__site_id=site_id, assigned_at__gte=seven_start, assigned_at__lte=now)
    allocations = {row["employee_id"]: row for row in history.values("employee_id").annotate(
        today_unique=Count("customer_id", distinct=True, filter=Q(assigned_at__gte=today, assigned_at__lt=tomorrow)),
        today_operations=Count("pk", filter=Q(assigned_at__gte=today, assigned_at__lt=tomorrow)),
        seven_unique=Count("customer_id", distinct=True), seven_operations=Count("pk"))}
    # Actual author, including former/inactive employees with attributable work.
    saves = (ConsultationRevision.objects.filter(customer__site_id=site_id, source__in=HUMAN_SAVES,
             saved_at__gte=seven_start, saved_at__lte=now)
             .filter(Q(actor__role=User.Role.EMPLOYEE)|Q(assignment__employee_id=F("actor_id"))))
    # One customer per actual employee author across the entire seven-day span,
    # even when notes/callbacks were saved repeatedly or on different days.
    records = {row["actor_id"]: row["count"] for row in saves.values("actor_id").annotate(count=Count("customer_id", distinct=True))}
    live = customers.filter(current_assignment__ended_at=None, current_assignment__isnull=False)
    holdings = {row["current_assignment__employee_id"]: row for row in
        live.values("current_assignment__employee_id").annotate(held=Count("pk"),
            progressed=Count("pk", filter=Q(current_assignment__first_activity_at__isnull=False)),
            contracted=Count("pk", filter=Q(contract_status=Customer.ContractStatus.CONTRACTED)))}
    states = {}
    for row in live.values("current_assignment__employee_id", "call_result").annotate(count=Count("pk")):
        states.setdefault(row["current_assignment__employee_id"], {})[row["call_result"]] = row["count"]
    ids = (set(allocations)|set(records)|set(holdings))-{None}
    people = User.objects.filter(Q(role=User.Role.EMPLOYEE, is_active=True)|Q(pk__in=ids)).order_by("created_at", "pk")
    staff = []
    for person in people:
        allocation, held = allocations.get(person.pk, {}), holdings.get(person.pk, {})
        staff.append({"id": str(person.pk), "name": person.name, "is_active": person.is_active,
            "is_employee": person.role == User.Role.EMPLOYEE,
            "assigned_today_unique": allocation.get("today_unique", 0),
            "assignment_operations_today": allocation.get("today_operations", 0),
            "assigned_7d_unique": allocation.get("seven_unique", 0),
            "assignment_operations_7d": allocation.get("seven_operations", 0),
            "consultation_records_7d": records.get(person.pk, 0),
            "held_total": held.get("held", 0), "progressed_total": held.get("progressed", 0),
            "unprogressed_total": held.get("held", 0)-held.get("progressed", 0),
            "contracted_total": held.get("contracted", 0), "call_results": result_rows(states.get(person.pk, {}))})
    return {"assigned_today_unique": history.filter(assigned_at__gte=today, assigned_at__lt=tomorrow).values("customer_id").distinct().count(),
            "assignment_operations_today": sum(row["today_operations"] for row in allocations.values()),
            "records_start": seven_start.isoformat(), "records_end_exclusive": tomorrow.isoformat(),
            "staff": staff, "distribution": distribution(customers, now, result_period)}
