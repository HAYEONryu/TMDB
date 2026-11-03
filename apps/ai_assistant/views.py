from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.conf import settings
from apps.accounts.access import require_role


@require_GET
@require_role()
def availability(request):
    # Explicit allowlist: never serialize the config object or environment.
    return JsonResponse({"generation_available": False, "configured": settings.AI_CONFIG.configured,
                         "reason": settings.AI_CONFIG.reason,
                         "message": "AI 생성 기능은 후속 단계에서 제공됩니다.",
                         "daily_limit": 30 if request.user.role == "EMPLOYEE" else None,
                         "successful_count": None, "reserved_count": None, "remaining_count": None})
