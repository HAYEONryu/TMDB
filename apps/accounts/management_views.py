from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET,require_http_methods,require_POST
from apps.accounts.access import require_role
from apps.accounts.models import User
from apps.accounts import management_services as services
from apps.common.http import api_errors,json_object


@require_GET
@require_role(User.Role.ADMIN)
def page(request):return render(request,"accounts/manage.html")


@require_http_methods(["GET","POST"])
@require_role(User.Role.ADMIN)
@api_errors
def users(request):
    if request.method=="GET":return JsonResponse(services.user_list(request.GET))
    result,status=services.create_user(request.user,json_object(request));return JsonResponse(result,status=201 if status==200 else status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def update(request):
    result,status=services.update_users(request.user,json_object(request));return JsonResponse(result,status=status)


@require_GET
@require_role(User.Role.ADMIN)
@api_errors
def transfers(request):return JsonResponse(services.transfer_list(request.GET))
