from django.http import JsonResponse
from django.views.decorators.http import require_GET,require_POST
from apps.accounts.access import require_role,actor_identity
from apps.accounts.models import User
from apps.common.http import api_errors,json_object
from apps.customers.employee import queue_identity
from apps.customers.deletions import submit,approve,notifications,hard_delete_customer,hard_delete_site,confirm_site


@require_POST
@require_role(User.Role.EMPLOYEE)
@api_errors
def request_deletion(request,customer_id):
    queue_identity(request);result,status=submit(request.user,customer_id,json_object(request));return JsonResponse(result,status=status)


@require_GET
@require_role(User.Role.ADMIN)
@api_errors
def pending(request):
    actor_identity(request);return JsonResponse(notifications(request.GET))


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def approve_request(request,request_id):
    actor_identity(request);result,status=approve(request.user,request_id,json_object(request));return JsonResponse(result,status=status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def delete_customer(request,customer_id):
    actor_identity(request);result,status=hard_delete_customer(request.user,customer_id,json_object(request));return JsonResponse(result,status=status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def delete_site(request,site_id):
    actor_identity(request);result,status=hard_delete_site(request.user,site_id,json_object(request));return JsonResponse(result,status=status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def confirm_site_view(request,site_id):
    actor_identity(request);return JsonResponse(confirm_site(request.user,site_id,json_object(request)))
