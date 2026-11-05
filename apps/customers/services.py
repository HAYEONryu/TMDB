from datetime import timedelta, timezone as datetime_timezone
import hashlib
import json
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.http import identifier
from apps.common.transactions import business_write, retry_transient_write
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer, CustomerChangeEvent, CustomerDeletionRequest
from apps.customers.queries import KST, enriched, iso, serialize
from apps.operations.models import IdempotencyRecord, MutationReceipt, OperationEvent
from apps.sites.models import Site
from apps.sites.services import locked_actor

EDITABLE_FIELDS = {"call_result", "visit_at", "contract_status", "notes", "callback_due_at", "housing_status"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def invalid(message):
    raise AccessError("VALIDATION_ERROR", message, 422)


def datetime_value(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 40 or len(value) < 16 or value[10] not in {"T", " "}:
        invalid("날짜와 시각을 함께 입력해 주세요.")
    try:
        result = parse_datetime(value)
    except ValueError:
        result = None
    if result is None:
        invalid("날짜·시각 형식이 올바르지 않습니다.")
    result = timezone.make_aware(result, KST) if timezone.is_naive(result) else result
    try:
        result.astimezone(datetime_timezone.utc)
    except (ValueError, OverflowError):
        invalid("날짜·시각 범위를 확인해 주세요.")
    return result


def normalized_changes(customer, changes):
    if not isinstance(changes, dict) or not changes or set(changes) - EDITABLE_FIELDS:
        invalid("수정할 수 없는 필드가 포함되었거나 변경값이 없습니다.")
    result = {}
    for field, value in changes.items():
        if field in {"visit_at", "callback_due_at"}:
            result[field] = datetime_value(value)
        elif field == "call_result":
            if value not in [None, "", *Customer.CallResult.values]:
                invalid("통화결과를 확인해 주세요.")
            result[field] = value or None
        elif field == "contract_status":
            if value not in [None, "", *Customer.ContractStatus.values]:
                invalid("계약여부를 확인해 주세요.")
            result[field] = value or Customer.ContractStatus.UNKNOWN
        else:
            limit = max(10000, len(customer.notes)) if field == "notes" else 200
            if not isinstance(value, str):
                invalid("상담내용·주택상황은 문자열로 입력해 주세요.")
            value = value.replace("\r\n", "\n").replace("\r", "\n") if field == "notes" else value.strip()
            if len(value) > limit:
                label = "상담기타내용" if field == "notes" else "주택상황"
                invalid(f"{label} 입력은 {limit:,}자까지 가능합니다.")
            result[field] = value
    return result


def snapshot(customer, callback):
    return {"call_result": customer.call_result, "visit_at": iso(customer.visit_at),
            "contract_status": customer.contract_status, "notes": customer.notes,
            "housing_status": customer.housing_status, "callback_due_at": iso(callback.due_at) if callback else None}


def safe_row(customer_id):
    return serialize(enriched(Customer.objects.filter(pk=customer_id)).get())


@retry_transient_write
def update_row(actor, body, *, employee_only=False):
    if not isinstance(body, dict) or set(body) != {"customer_id", "assignment_id", "mutation_id", "expected_version", "changes"}:
        invalid("행 저장 형식을 확인해 주세요.")
    cid = identifier(body["customer_id"])
    assignment_id = identifier(body["assignment_id"], nullable=True)
    mutation_id = identifier(body["mutation_id"])
    if type(body["expected_version"]) is not int or body["expected_version"] < 1:
        invalid("행 버전을 확인해 주세요.")
    body_hash = digest(body)
    with business_write():
        metadata = Customer.objects.filter(pk=cid).values("site_id", "current_assignment__employee_id").first()
        extra = [metadata["current_assignment__employee_id"]] if metadata and metadata["current_assignment__employee_id"] else []
        actor = locked_actor(actor, extra_ids=extra)
        if employee_only and actor.role!=User.Role.EMPLOYEE:
            raise AccessError("QUEUE_CONTEXT_MISMATCH","로그인 권한이 변경되었습니다. 대기값을 다시 확인해 주세요.",403)
        if not metadata:
            raise AccessError("FORBIDDEN" if actor.role != User.Role.ADMIN else "CUSTOMER_DELETED", "고객정보를 사용할 수 없습니다.", 403 if actor.role != User.Role.ADMIN else 409)
        site = Site.objects.select_for_update().filter(pk=metadata["site_id"]).first()
        if not site:
            raise AccessError("SITE_DELETED", "현장이 삭제되었습니다.", 409)
        customer = Customer.objects.select_for_update(of=("self",)).get(pk=cid)
        assignment = Assignment.objects.select_for_update().filter(pk=customer.current_assignment_id).first()
        if assignment and (assignment.customer_id != customer.pk or assignment.ended_at is not None):
            raise AccessError("ASSIGNMENT_CHANGED", "현재 할당 상태를 다시 확인해 주세요.", 409)
        if actor.role != User.Role.ADMIN and (not assignment or assignment.employee_id != actor.pk or assignment.ended_at is not None or customer.deleted_at):
            historical=assignment_id and Assignment.objects.filter(pk=assignment_id,customer=customer,employee=actor).exists()
            if historical:
                raise AccessError("CUSTOMER_DELETED" if customer.deleted_at else "ASSIGNMENT_CHANGED","회수·재분배·삭제되어 이전 변경값을 저장할 수 없습니다.",409)
            raise AccessError("FORBIDDEN", "현재 담당 고객정보만 수정할 수 있습니다.")
        if customer.deleted_at:
            raise AccessError("CUSTOMER_DELETED", "휴지통의 고객정보는 수정할 수 없습니다.", 409)
        if actor.role != User.Role.ADMIN and assignment_id is None:
            invalid("현재 할당 ID가 필요합니다.")
        if assignment_id != customer.current_assignment_id:
            raise AccessError("ASSIGNMENT_CHANGED", "담당자가 변경되었습니다. 이전 변경값을 자동 저장하지 않습니다.", 409)
        receipt = MutationReceipt.objects.filter(actor=actor, mutation_id=mutation_id).first()
        if receipt:
            if receipt.body_hash != body_hash:
                raise AccessError("IDEMPOTENCY_CONFLICT", "같은 요청 ID의 내용이 다릅니다.", 409)
            if receipt.expires_at <= timezone.now():
                raise AccessError("IDEMPOTENCY_EXPIRED", "요청 보관 기간이 지났습니다. 서버 상태를 확인해 주세요.", 409)
            return receipt.result
        try:
            if customer.version != body["expected_version"]:
                raise AccessError("VERSION_CONFLICT", "다른 변경이 저장되었습니다. 서버값과 비교해 주세요.", 409)
            values = normalized_changes(customer, body["changes"])
        except AccessError as exc:
            result = {"customer_id": str(cid), "mutation_id": str(mutation_id), "ok": False,
                      "error": {"code": exc.code, "message": exc.message}}
            if exc.code == "VERSION_CONFLICT":
                result["server_row"] = safe_row(cid)
            MutationReceipt.objects.create(actor=actor, customer=customer, mutation_id=mutation_id, body_hash=body_hash,
                result=result, expires_at=timezone.now()+timedelta(days=7))
            return result
        callback = Callback.objects.select_for_update().filter(customer=customer, status="PENDING").first()
        before = snapshot(customer, callback)
        actual = {}
        for field, value in values.items():
            current = callback.due_at if field == "callback_due_at" and callback else (None if field == "callback_due_at" else getattr(customer, field))
            if current != value:
                actual[field] = value
        now = timezone.now()
        if actual:
            for field, value in actual.items():
                if field != "callback_due_at":
                    setattr(customer, field, value)
            if "callback_due_at" in actual:
                due = actual["callback_due_at"]
                if callback:
                    callback.version += 1
                    callback.updated_by = actor
                    if due is None:
                        callback.status = Callback.Status.CANCELLED
                        callback.cancelled_at = now
                    else:
                        callback.due_at = due
                    callback.save()
                elif due is not None:
                    callback = Callback.objects.create(customer=customer, due_at=due, created_by=actor, updated_by=actor)
            customer.version += 1
            customer.save(update_fields=[*[f for f in actual if f != "callback_due_at"], "version", "updated_at"])
            if assignment and assignment.first_activity_at is None:
                assignment.first_activity_at = now
                assignment.save(update_fields=["first_activity_at", "updated_at"])
            after = snapshot(customer, callback if callback and callback.status == "PENDING" else None)
            CustomerChangeEvent.objects.create(customer=customer, assignment=assignment, changed_by=actor, changed_at=now, changed_fields=sorted(actual))
            ConsultationRevision.objects.create(customer=customer, assignment=assignment, actor=actor, saved_at=now,
                customer_version=customer.version, changed_fields=sorted(actual), before_values=before, after_values=after,
                notes=customer.notes, source=ConsultationRevision.Source.MANUAL)
        result = {"ok": True, "customer_id": str(cid), "mutation_id": str(mutation_id), "changed": bool(actual),
                  "version": customer.version, "row": safe_row(cid)}
        MutationReceipt.objects.create(actor=actor, customer=customer, mutation_id=mutation_id, body_hash=body_hash,
            result=result, expires_at=now+timedelta(days=7))
        return result


@retry_transient_write
def trash_operation(actor, body, *, restore=False):
    if set(body) != {"customer_ids", "site_id", "idempotency_key"} or not isinstance(body["customer_ids"], list) or not 1 <= len(body["customer_ids"]) <= 100:
        invalid("선택한 현재 페이지의 고객 1~100건을 보내 주세요.")
    ids = sorted({identifier(v) for v in body["customer_ids"]})
    if len(ids) != len(body["customer_ids"]):
        invalid("중복 고객 ID가 있습니다.")
    selected_site = "all" if body["site_id"] == "all" and restore else identifier(body["site_id"])
    key = identifier(body["idempotency_key"])
    operation = "RESTORE" if restore else "SOFT_DELETE"
    canonical = {"ids": [str(v) for v in ids], "site_id": str(selected_site)}
    body_hash = digest(canonical)
    with business_write():
        extra = list(Customer.objects.filter(pk__in=ids).exclude(current_assignment=None).values_list("current_assignment__employee_id", flat=True))
        actor = locked_actor(actor, admin=True, extra_ids=extra)
        receipt = IdempotencyRecord.objects.filter(actor=actor, operation=operation, key=key).first()
        if receipt:
            if receipt.body_hash != body_hash:
                raise AccessError("IDEMPOTENCY_CONFLICT", "같은 작업 키의 내용이 다릅니다.", 409)
            if receipt.expires_at <= timezone.now():
                raise AccessError("IDEMPOTENCY_EXPIRED", "오래된 작업입니다. 현재 상태를 다시 확인해 주세요.", 409)
            return receipt.result
        site_ids = sorted(set(Customer.objects.filter(pk__in=ids).values_list("site_id", flat=True)))
        if selected_site != "all" and (not site_ids or site_ids != [selected_site]):
            raise AccessError("SITE_DELETED", "선택 현장과 고객정보를 다시 확인해 주세요.", 409)
        list(Site.objects.select_for_update().filter(pk__in=site_ids).order_by("pk"))
        customers = list(Customer.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
        if len(customers) != len(ids):
            raise AccessError("CUSTOMER_DELETED", "일부 고객정보가 없어 작업하지 않았습니다.", 409)
        assignment_ids = [c.current_assignment_id for c in customers if c.current_assignment_id]
        assignments = {a.pk: a for a in Assignment.objects.select_for_update().filter(pk__in=assignment_ids).order_by("pk")}
        now, affected = timezone.now(), 0
        for customer in customers:
            if restore:
                if customer.deleted_at is None:
                    continue  # A late retry must never clear a newer assignment.
                customer.deleted_at = None
                customer.deleted_by = None
                customer.current_assignment = None
            else:
                if customer.deleted_at is not None:
                    continue
                assignment = assignments.get(customer.current_assignment_id)
                customer.current_assignment = None
                if assignment:
                    assignment.ended_at, assignment.end_reason, assignment.ended_by = now, "SOFT_DELETED", actor
                    assignment.save(update_fields=["ended_at", "end_reason", "ended_by", "updated_at"])
                customer.deleted_at, customer.deleted_by = now, actor
                requests = CustomerDeletionRequest.objects.select_for_update().filter(customer=customer, status="PENDING").order_by("pk")
                for deletion in requests:
                    deletion.status, deletion.closed_at, deletion.close_reason = "CLOSED", now, "ALREADY_DELETED"
                    deletion.save(update_fields=["status", "closed_at", "close_reason", "updated_at"])
            customer.version += 1
            customer.save(update_fields=["current_assignment", "deleted_at", "deleted_by", "version", "updated_at"])
            affected += 1
        OperationEvent.objects.create(actor=actor, operation=operation, occurred_at=now, affected_count=affected)
        result = {"ok": True, "affected_count": affected, "requested_count": len(ids)}
        IdempotencyRecord.objects.create(actor=actor, operation=operation, key=key, body_hash=body_hash,
            result=result, target_ids=[str(v) for v in ids], expires_at=now+timedelta(days=7))
        return result
