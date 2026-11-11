from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Count, Q
from apps.accounts.access import require_role, AccessError, actor_identity
from apps.accounts.models import User
from apps.common.http import api_errors, identifier, json_object
from apps.sites.models import GlobalSettings, Site
from apps.sites.services import create_site, rename_site, set_default_site
from apps.customers.models import Customer


@require_http_methods(["GET", "POST"])
@require_role()
@api_errors
def sites(request):
    if request.method == "POST":
        if request.user.role != User.Role.ADMIN:
            raise AccessError("FORBIDDEN", "관리자 권한이 필요합니다.")
        body = json_object(request)
        if set(body) != {"name"}:
            raise AccessError("VALIDATION_ERROR", "현장명만 보내 주세요.", 422)
        site, settings = create_site(request.user, body["name"])
        return JsonResponse({"id": str(site.pk), "name": site.name, "default_site_id": str(settings.default_site_id) if settings.default_site_id else None, "settings_version": settings.version}, status=201)
    settings = GlobalSettings.objects.filter(pk=1).first()
    return JsonResponse({"items": [{"id": str(s.pk), "name": s.name, "version": s.updated_at.isoformat()} for s in Site.objects.order_by("created_at", "id")],
                         "default_site_id": str(settings.default_site_id) if settings and settings.default_site_id else None,
                         "settings_version": settings.version if settings else 1})


@require_http_methods(["PATCH"])
@require_role(User.Role.ADMIN)
@api_errors
def rename(request, site_id):
    actor_identity(request)
    body = json_object(request)
    if set(body) != {"name", "expected_version"}:
        raise AccessError("VALIDATION_ERROR", "새 현장명과 현장 버전이 필요합니다.", 422)
    site, changed = rename_site(request.user, site_id, body["name"], body["expected_version"])
    return JsonResponse({"id": str(site.pk), "name": site.name, "version": site.updated_at.isoformat(), "changed": changed})


@require_http_methods(["PATCH"])
@require_role(User.Role.ADMIN)
@api_errors
def default_site(request):
    body = json_object(request)
    if set(body) != {"site_id", "expected_version"}:
        raise AccessError("VALIDATION_ERROR", "현장과 설정 버전이 필요합니다.", 422)
    settings, changed = set_default_site(request.user, identifier(body["site_id"]), body["expected_version"])
    return JsonResponse({"default_site_id": str(settings.default_site_id), "settings_version": settings.version, "changed": changed})


@require_http_methods(["GET"])
@require_role(User.Role.ADMIN)
@api_errors
def counts(request, site_id):
    if not Site.objects.filter(pk=site_id).exists():
        raise AccessError("SITE_DELETED", "현장이 삭제되었거나 존재하지 않습니다.", 409)
    return JsonResponse(Customer.objects.filter(site_id=site_id).aggregate(
        total=Count("pk", filter=Q(deleted_at__isnull=True)),
        unassigned=Count("pk", filter=Q(deleted_at__isnull=True, current_assignment__isnull=True)),
        trash=Count("pk", filter=Q(deleted_at__isnull=False))))
