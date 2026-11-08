"""Server-selected, bounded employee and report evidence."""
import hashlib
import json
import re
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from apps.accounts.models import User
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.callbacks.models import Callback
from .models import Feature, SiteKnowledge

STAFF_FEATURES = {Feature.CLEANUP, Feature.SUMMARY, Feature.NEXT_QUESTIONS}


def note_date_anchors(saved_at):
    """Calendar facts from the source timestamp, never inferred from query time."""
    if saved_at is None:return {}
    from apps.customers.queries import KST
    day=timezone.localtime(saved_at,KST).date()
    return {word:(day+timedelta(days=offset)).isoformat() for word,offset in [('어제',-1),('오늘',0),('내일',1),('모레',2)]}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def sanitize(value, names):
    if isinstance(value, dict): return {k: sanitize(v, names) for k, v in value.items()}
    if isinstance(value, list): return [sanitize(v, names) for v in value]
    if not isinstance(value, str): return value
    key = settings.AI_CONFIG.api_key
    if key: value = value.replace(key, "[보호값]")
    for name in sorted(set(names), key=len, reverse=True):
        if name: value = value.replace(name, "[이름]")
    value = re.sub(r"\b01[016789][\s-]?\d{3,4}[\s-]?\d{4}\b", "[연락처]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일]", value)
    return value


def build(feature, *, customer=None, site=None, employee=None, start, end, korean_date):
    if feature not in STAFF_FEATURES:
        from .reports import build_report
        return build_report(feature, site=site, employee=employee, start=start, end=end, korean_date=korean_date)
    query = ConsultationRevision.objects.filter(saved_at__lte=end).exclude(changed_fields=["admin_notes"]).select_related("customer")
    sources = []
    payload = {"reference_date": korean_date.isoformat(), "period_start": start.isoformat(), "period_end": end.isoformat(), "records": []}
    names = list(User.objects.values_list("name", flat=True))
    if feature in STAFF_FEATURES:
        payload.pop("period_start")
        payload.pop("period_end")
        query = query.filter(customer=customer)
        names.append(customer.customer_name)
        callback = Callback.objects.filter(customer=customer, status="PENDING").first()
        payload["current"] = {"notes": customer.notes, "call_result": customer.call_result, "contract_status": customer.contract_status,
                              "housing_status": customer.housing_status, "visit_at": customer.visit_at.isoformat() if customer.visit_at else None,
                              "callback_due_at": callback.due_at.isoformat() if callback else None, "version": customer.version}
        note_revision=ConsultationRevision.objects.filter(customer=customer,changed_fields__contains=["notes"],source__in=["MANUAL","AI_APPLIED"]).order_by("-saved_at","-pk").first()
        payload["current"]["source_id"]=str(customer.pk)
        payload["current"]["notes_saved_at"]=note_revision.saved_at.isoformat() if note_revision and note_revision.notes==customer.notes else None
        payload["current"]["notes_date_anchors"]=note_date_anchors(note_revision.saved_at if note_revision and note_revision.notes==customer.notes else None)
        payload["current"]["information_state"]="저장된 상담내용 있음" if customer.notes else "저장된 상담내용 없음"
        from .employee_schema import INSTRUCTIONS
        payload["instructions"]=INSTRUCTIONS
        sources.append({"customer_id": customer.pk, "source_version": customer.version})
    rows = list(query.order_by("-saved_at", "-pk")[:101])
    if len(rows) > 100:
        from apps.accounts.access import AccessError
        raise AccessError("AI_INPUT_TOO_LARGE", "분석 입력 상한을 넘었습니다.", 422)
    for revision in rows:
        names.append(revision.customer.customer_name)
        payload["records"].append({"source_id": str(revision.pk), "saved_at": revision.saved_at.isoformat(), "source": revision.source,
                                   "version": revision.customer_version, "notes": revision.notes,
                                   "fields": {key: value for key, value in revision.after_values.items() if key in {"notes", "call_result", "contract_status", "housing_status", "visit_at", "callback_due_at"}},
                                   "notes_date_anchors":note_date_anchors(revision.saved_at if revision.source in {'MANUAL','AI_APPLIED'} else None)})
        sources.append({"revision_id": revision.pk, "source_version": revision.customer_version})
    payload = sanitize(payload, names)
    return payload, sources


def source_ids(result):
    return {str(s.customer_id or s.revision_id or s.knowledge_id or s.previous_result_id) for s in result.sources.all()}


def current_fingerprint(request):
    payload, _ = build(request.feature, customer=request.customer, site=request.site, employee=request.employee,
                       start=request.period_start, end=request.period_end, korean_date=request.korean_date)
    return digest(payload)
