from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET,require_POST
from apps.accounts.access import require_role
from apps.accounts.models import User
from apps.common.http import api_errors,json_object
from apps.assignments import services


@require_GET
@require_role(User.Role.ADMIN)
def page(request):return render(request,"assignments/manage.html")


@require_GET
@require_role(User.Role.ADMIN)
@api_errors
def availability(request):return JsonResponse(services.availability(request.GET))


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def distribute(request):
    result,status=services.distribute(request.user,json_object(request));return JsonResponse(result,status=status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def preview(request):return JsonResponse(services.recall_preview(json_object(request)))


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def recall(request):
    result,status=services.recall(request.user,json_object(request));return JsonResponse(result,status=status)


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def assignee(request,customer_id):
    result,status=services.change_assignee(request.user,customer_id,json_object(request));return JsonResponse(result,status=status)
