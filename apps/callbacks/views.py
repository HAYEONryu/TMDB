from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.accounts.access import require_role,actor_identity
from apps.common.http import api_errors,json_object
from apps.customers.employee import optional_queue_identity
from apps.callbacks.services import complete


@require_POST
@require_role()
@api_errors
def complete_view(request,customer_id):
    optional_queue_identity(request)
    actor_identity(request)
    result,status=complete(request.user,customer_id,json_object(request),employee_only=bool(request.headers.get('X-TM-Queue-User')))
    return JsonResponse(result,status=status)
