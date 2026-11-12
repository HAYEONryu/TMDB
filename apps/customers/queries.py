from datetime import date, datetime, time, timedelta
import json
import re
from zoneinfo import ZoneInfo
from django.db.models import Count, F, OuterRef, Q, Subquery, Value, CharField,Case,When,IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.http import identifier
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.sites.models import GlobalSettings, Site

KST = ZoneInfo("Asia/Seoul")
CHOICE_FIELDS = {"assignee_name", "customer_name", "phone_normalized", "call_result", "contract_status", "housing_status", "route"}
DATE_FIELDS = {"visit_at", "callback_due_at", "assigned_at"}
SORT_FIELDS = CHOICE_FIELDS | DATE_FIELDS | {"created_at", "notes"}
TEXT_FIELDS = {"notes", "residence", "route", "memo"}


def visible_values(values, *, admin=False):
    """Use on stored responses too: a former administrator may now be staff."""
    if admin:
        return values
    if isinstance(values, dict):
        return {key: visible_values(value) for key, value in values.items() if key != "admin_notes"}
    if isinstance(values, list):
        return [visible_values(value) for value in values if value != "admin_notes"]
    return values


def error(message="검색·필터 조건을 확인해 주세요."):
    raise AccessError("VALIDATION_ERROR", message, 422)


def enriched(query):
    callback = Callback.objects.filter(customer_id=OuterRef("pk"), status="PENDING")
    deletion = CustomerDeletionRequest.objects.filter(customer_id=OuterRef("pk"), status="PENDING")
    return query.select_related("site", "current_assignment").annotate(
        assignee_name=Coalesce("current_assignment__employee__name", Value(""), output_field=CharField()),
        assigned_at=F("current_assignment__assigned_at"),
        callback_due_at=Subquery(callback.values("due_at")[:1]),
        callback_id=Subquery(callback.values("pk")[:1]),
        callback_version=Subquery(callback.values("version")[:1]),
        pending_deletion_request_id=Subquery(deletion.values("pk")[:1]))


def scoped(actor, params):
    view = params.get("view", "all" if actor.role == User.Role.ADMIN else "mine")
    if view not in {"all", "mine", "today", "trash"}:
        error()
    if actor.role != User.Role.ADMIN and view in {"all", "trash"}:
        raise AccessError("FORBIDDEN", "접근 권한이 없습니다.")
    selected = params.get("site_id")
    if selected == "all":
        if view != "trash" or actor.role != User.Role.ADMIN:
            error()
        site_id = "all"
    elif selected:
        site_id = identifier(selected)
        if not Site.objects.filter(pk=site_id).exists():
            raise AccessError("SITE_DELETED", "현장이 삭제되었거나 존재하지 않습니다.", 409)
    else:
        site_id = GlobalSettings.objects.filter(pk=1).values_list("default_site_id", flat=True).first()
    query = enriched(Customer.objects.all())
    if actor.role != User.Role.ADMIN:query = query.defer('admin_notes')
    if site_id != "all":
        query = query.filter(site_id=site_id) if site_id else query.none()
    query = query.filter(deleted_at__isnull=(view != "trash"))
    if params.get("assignee_id"):
        if actor.role != User.Role.ADMIN:
            raise AccessError("FORBIDDEN", "접근 권한이 없습니다.")
        query=query.filter(current_assignment__employee_id=identifier(params["assignee_id"]))
    if actor.role != User.Role.ADMIN or view in {"mine", "today"}:
        # Select the owner's current IDs once. DISTINCT ON keeps this subquery
        # independent when newly imported rows still have inaccurate statistics;
        # otherwise a nested join can scan the same owner's assignments per customer.
        current_ids = Assignment.objects.filter(employee_id=actor.pk, ended_at__isnull=True).order_by("pk").distinct("pk").values("pk")
        query = query.filter(current_assignment_id__in=current_ids)
    if view == "today":
        today = timezone.localdate()
        start = datetime.combine(today, time.min, KST)
        end = start + timedelta(days=1)
        query = query.filter(Q(assigned_at__gte=start, assigned_at__lt=end) | Q(callback_due_at__lt=end))
    return query, site_id, view


def apply_conditions(query, params, *, omit=None, admin=False):
    q = params.get("q", "")
    if len(q) > 200:
        error()
    if q.strip():
        query = query.filter(Q(customer_name__icontains=q.strip()) | Q(phone_normalized__contains=re.sub(r"[\s-]", "", q.strip())))
    try:
        filters = json.loads(params.get("filters", "{}"))
    except (ValueError, TypeError):
        error()
    if not isinstance(filters, dict) or len(filters) > 15:
        error()
    for field, condition in filters.items():
        if field not in CHOICE_FIELDS | DATE_FIELDS | TEXT_FIELDS | ({"admin_notes"} if admin else set()):
            error()
        if field == omit:
            continue
        if isinstance(condition,dict) and set(condition)=={'blank'}:
            if type(condition['blank']) is not bool:error()
            empty=Q(**{field+'__isnull':True})
            if field not in DATE_FIELDS and field!='call_result':empty|=Q(**{field:''})
            if field=='contract_status':empty|=Q(contract_status='UNKNOWN')
            query=query.filter(empty) if condition['blank'] else query.exclude(empty)
            continue
        if field in CHOICE_FIELDS and not (field=='route' and isinstance(condition,dict) and set(condition)=={'contains'}):
            exclude = False
            if isinstance(condition, dict) and set(condition) <= {"values", "exclude"}:
                exclude = condition.get("exclude", False)
                values = condition.get("values")
            else:
                values = condition
            if type(exclude) is not bool or not isinstance(values, list) or len(values) > 1000:
                error()
            match = Q(pk__in=[])
            for value in values:
                if value is not None and (not isinstance(value, str) or len(value) > 200):
                    error()
                if value in {None, ""}:
                    match |= Q(**{field + "__isnull": True}) | Q(**{field: ""}) if field not in {"call_result"} else Q(call_result__isnull=True)
                else:
                    match |= Q(**{field: value})
            query = query.exclude(match) if exclude else query.filter(match)
        elif field in TEXT_FIELDS | {"admin_notes"}:
            if not isinstance(condition, dict) or set(condition) != {"contains"} or not isinstance(condition["contains"], str) or len(condition["contains"]) > 10000:
                error()
            query = query.filter(**{field + "__icontains": condition["contains"]})
        else:
            if not isinstance(condition, dict) or not set(condition) <= {"from", "to"}:
                error()
            boundaries = {}
            for key, value in condition.items():
                try:
                    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        error()
                    boundaries[key] = date.fromisoformat(value)
                except ValueError:
                    error()
            if boundaries.get("from") and boundaries.get("to") and boundaries["from"] > boundaries["to"]:
                error()
            if "from" in boundaries:
                query = query.filter(**{field + "__gte": datetime.combine(boundaries["from"], time.min, KST)})
            if "to" in boundaries:
                if boundaries["to"] == date.max:
                    query = query.filter(**{field + "__lte": datetime.combine(date.max, time.max, KST)})
                else:
                    query = query.filter(**{field + "__lt": datetime.combine(boundaries["to"] + timedelta(days=1), time.min, KST)})
    return query


def iso(value):
    return value.isoformat() if value is not None else None


def serialize(customer, *, admin=False):
    return {**({"admin_notes": customer.admin_notes} if admin else {}),
            "residence": customer.residence, "route": customer.route, "memo": customer.memo,
            "id": str(customer.pk), "site_id": str(customer.site_id), "site_name": customer.site.name,
            "customer_name": customer.customer_name, "phone_normalized": customer.phone_normalized,
            "assignee_name": customer.assignee_name, "assignee_id":str(customer.current_assignment.employee_id) if customer.current_assignment_id else None, "assignment_id": str(customer.current_assignment_id) if customer.current_assignment_id else None,
            "assigned_at": iso(customer.assigned_at), "call_result": customer.call_result, "visit_at": iso(customer.visit_at),
            "contract_status": customer.contract_status, "notes": customer.notes, "housing_status": customer.housing_status,
            "callback_due_at": iso(customer.callback_due_at), "callback_id": str(customer.callback_id) if customer.callback_id else None,
            "callback_version": customer.callback_version, "version": customer.version, "deleted_at": iso(customer.deleted_at),
            "pending_deletion_request_id": str(customer.pending_deletion_request_id) if customer.pending_deletion_request_id else None,
            "deletion_request_status": "PENDING" if customer.pending_deletion_request_id else None}


def integer(params, name, default):
    try:
        return int(params.get(name, default))
    except (ValueError, TypeError):
        error()


def customer_list(actor, params):
    if set(params) - {"site_id", "view", "q", "page", "page_size", "sort", "filters", "assignee_id"}:
        error()
    query, site_id, view = scoped(actor, params)
    admin = actor.role == User.Role.ADMIN
    query = apply_conditions(query, params, admin=admin)
    sort = params.get("sort", "priority" if view=="today" else "-created_at")
    if sort!="priority" and (not isinstance(sort, str) or sort.lstrip("-") not in SORT_FIELDS | TEXT_FIELDS | ({"admin_notes"} if admin else set()) or sort.startswith("--")):
        error()
    if sort=="priority" and view!="today":error()
    size, page = integer(params, "page_size", 50), integer(params, "page", 1)
    if size not in {50, 100} or not 1 <= page <= 1000000000:
        error("페이지는 1 이상, 행 수는 50 또는 100이어야 합니다.")
    total = query.count()
    if sort=="priority":
        now=timezone.now()
        end=datetime.combine(timezone.localdate(now,KST)+timedelta(days=1),time.min,KST)
        query=query.annotate(priority=Case(When(callback_due_at__lt=now,then=Value(0)),When(callback_due_at__lt=end,then=Value(1)),default=Value(2),output_field=IntegerField()))
        ordered=query.order_by("priority",F("callback_due_at").asc(nulls_last=True),F("assigned_at").asc(nulls_last=True),"id")
    else:ordered=query.order_by(sort,"id")
    rows = list(ordered[(page-1)*size:page*size])
    counts = None
    if actor.role == User.Role.ADMIN:
        whole = Customer.objects.all()
        whole = whole.filter(site_id=site_id) if site_id != "all" else whole
        counts = whole.aggregate(total=Count("pk", filter=Q(deleted_at__isnull=True)),
            unassigned=Count("pk", filter=Q(deleted_at__isnull=True, current_assignment__isnull=True)),
            trash=Count("pk", filter=Q(deleted_at__isnull=False)))
    return {"data": [serialize(row, admin=admin) for row in rows], "total": total, "page": page, "page_size": size,
            "last_page": max(1, (total+size-1)//size), "site_id": str(site_id) if site_id else None, "counts": counts}


def filter_options(actor, params):
    if set(params) - {"site_id", "view", "q", "filters", "field", "option_q", "option_page", "assignee_id"}:
        error()
    field = params.get("field")
    if field not in CHOICE_FIELDS:
        error()
    query, _, _ = scoped(actor, params)
    query = apply_conditions(query, params, omit=field, admin=actor.role == User.Role.ADMIN)
    search = params.get("option_q", "")
    if len(search) > 200:
        error()
    if field=='phone_normalized':search=re.sub(r'[\s-]','',search)
    if search:
        query = query.filter(**{field + "__icontains": search})
    values = query.order_by(field).values_list(field, flat=True).distinct()
    page = integer(params, "option_page", 1)
    if not 1 <= page <= 1000000000:
        error()
    total = values.count()
    return {"values": list(values[(page-1)*100:page*100]), "total": total, "page": page, "has_next": page*100 < total}
