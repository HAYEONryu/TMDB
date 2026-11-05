from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from apps.accounts.access import require_role, AccessError
from apps.accounts.models import User
from apps.common.http import api_errors,identifier,json_object
from apps.imports.excel import template_bytes
from apps.imports.services import validate_upload,summary,result_page,commit_upload


@require_GET
@require_role(User.Role.ADMIN)
def page(request):
    return render(request,"imports/upload.html")


@require_GET
@require_role(User.Role.ADMIN)
def template(request):
    response=HttpResponse(template_bytes(),content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"]='attachment; filename="TM_customer_template.xlsx"'
    return response


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def validate(request):
    files=request.FILES
    if getattr(request,"import_upload_too_large",False):
        raise AccessError("FILE_TOO_LARGE","파일은 10MB까지 업로드할 수 있습니다.",413)
    if set(request.POST)!={"site_id"} or set(files)!={"file"} or len(files.getlist("file"))!=1:
        raise AccessError("VALIDATION_ERROR","현장과 .xlsx 파일 하나를 선택해 주세요.",422)
    batch=validate_upload(request.user,identifier(request.POST["site_id"]),files["file"])
    return JsonResponse(summary(batch),status=201)


@require_GET
@require_role(User.Role.ADMIN)
@api_errors
def results(request,batch_id):
    return JsonResponse(result_page(request.user,batch_id,request.GET))


@require_POST
@require_role(User.Role.ADMIN)
@api_errors
def commit(request,batch_id):
    result,status=commit_upload(request.user,batch_id,json_object(request))
    return JsonResponse(result,status=status)
