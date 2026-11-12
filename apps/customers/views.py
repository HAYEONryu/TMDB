from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from apps.accounts.access import AccessError, require_role
from apps.accounts.models import User
from apps.common.http import api_errors, identifier, json_object
from apps.customers.models import Customer
from apps.customers.choices import customer_schema
from apps.customers.queries import customer_list, filter_options
from apps.customers.services import update_row, trash_operation


@require_GET
@require_role()
@api_errors
def customers(request):
    from apps.customers.employee import optional_queue_identity
    optional_queue_identity(request)
    return JsonResponse(customer_list(request.user, request.GET))


@require_GET
@require_role()
@api_errors
def options(request):
    from apps.customers.employee import optional_queue_identity
    optional_queue_identity(request)
    return JsonResponse(filter_options(request.user, request.GET))


@require_POST
@require_role()
@api_errors
def batch_update(request):
    from apps.customers.employee import optional_queue_identity
    optional_queue_identity(request)
    body = json_object(request)
    rows = body.get("rows")
    if set(body) != {"rows"} or not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise AccessError("VALIDATION_ERROR", "행 1~100개를 보내 주세요.", 422)
    ids = [str(row.get("customer_id")) for row in rows if isinstance(row, dict)]
    if len(set(ids)) != len(ids):
        raise AccessError("VALIDATION_ERROR", "한 배치에 같은 고객을 반복할 수 없습니다.", 422)
    results = []
    for row in rows:
        try:
            results.append(update_row(request.user, row,employee_only=bool(request.headers.get("X-TM-Queue-User"))))
        except AccessError as exc:
            results.append({"ok": False, "customer_id": row.get("customer_id") if isinstance(row, dict) else None,
                "mutation_id": row.get("mutation_id") if isinstance(row, dict) else None,
                "error": {"code": exc.code, "message": exc.message}})
    return JsonResponse({"results": results})


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def soft_delete(request):
    return JsonResponse(trash_operation(request.user, json_object(request)))


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def restore(request):
    return JsonResponse(trash_operation(request.user, json_object(request), restore=True))


@require_GET
@require_role(User.Role.ADMIN)
def management(request, trash=False):
    return render(request, "customers/manage.html", {"trash": trash, "customer_schema": customer_schema()})
