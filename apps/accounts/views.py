import json

from django.contrib.auth import login, logout, update_session_auth_hash
from django.db import OperationalError, connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.accounts.access import AccessError, api_error, database_write_errors, require_role
from apps.accounts.forms import LoginForm, PasswordChangeForm
from apps.accounts.middleware import SESSION_VERSION_KEY
from apps.accounts.models import User
from apps.accounts.services import attempt_login, change_password, reset_password
from apps.sites.models import GlobalSettings


def is_json(request):
    return request.content_type == "application/json"


def input_data(request):
    if not is_json(request):
        return request.POST
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise AccessError("VALIDATION_ERROR", "JSON 형식이 올바르지 않습니다.", 422)
    if not isinstance(data, dict) or any(not isinstance(value, str) for value in data.values()):
        raise AccessError("VALIDATION_ERROR", "문자열 항목으로 입력해 주세요.", 422)
    return data


def destination(user):
    if user.must_change_password:
        return "/auth/password"
    return "/app/admin" if user.role == User.Role.ADMIN else "/app/employee"


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


@require_GET
@require_role()
def home(request):
    return redirect(destination(request.user))


@sensitive_post_parameters("password")
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
@database_write_errors
def login_view(request):
    if request.method == "GET":
        if request.user.is_authenticated:
            return redirect(destination(request.user))
        return render(request, "accounts/login.html", {"form": LoginForm()})
    try:
        form = LoginForm(input_data(request))
        if not form.is_valid():
            if is_json(request):
                return api_error("VALIDATION_ERROR", "입력한 항목을 확인해 주세요.", 422, dict(form.errors))
            return render(request, "accounts/login.html", {"form": form}, status=422)
        user, error = attempt_login(request, form.cleaned_data["phone"], form.cleaned_data["password"])
        if error:
            if is_json(request):
                return api_error(error.code, error.message, error.status)
            form.add_error(None, error.message)
            return render(request, "accounts/login.html", {"form": form}, status=error.status)
        login(request, user)
        request.session[SESSION_VERSION_KEY] = user.session_version
        if is_json(request):
            return JsonResponse({"role": user.role, "must_change_password": user.must_change_password, "redirect": destination(user)})
        return redirect(destination(user))
    except AccessError as exc:
        return api_error(exc.code, exc.message, exc.status, exc.fields)


@require_POST
@require_role()
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True}) if is_json(request) else redirect("/auth/login")


@sensitive_post_parameters("current_password", "new_password", "new_password_confirm")
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
@require_role()
@database_write_errors
def password_view(request):
    if request.method == "GET":
        return render(request, "accounts/password.html", {"form": PasswordChangeForm(request.user)})
    try:
        data = input_data(request)
        user = change_password(request.user, data)
    except AccessError as exc:
        if is_json(request) or exc.code != "VALIDATION_ERROR":
            return api_error(exc.code, exc.message, exc.status, exc.fields)
        form = PasswordChangeForm(request.user, request.POST)
        form.is_valid()
        return render(request, "accounts/password.html", {"form": form}, status=422)
    update_session_auth_hash(request, user)
    request.user = user
    request.session[SESSION_VERSION_KEY] = user.session_version
    return JsonResponse({"ok": True, "redirect": destination(user)}) if is_json(request) else redirect(destination(user))


@require_GET
@require_role()
def me(request):
    # The only business-prefix endpoint available before initial password change.
    settings = GlobalSettings.objects.filter(pk=1).values("version").first()
    return JsonResponse({"id": str(request.user.pk), "name": request.user.name,
                         "role": request.user.role, "must_change_password": request.user.must_change_password,
                         "settings_version": settings["version"] if settings else None})


@require_GET
@require_role(User.Role.ADMIN)
def admin_access(request):
    return JsonResponse({"ok": True, "role": User.Role.ADMIN})


@require_GET
@require_role(User.Role.EMPLOYEE)
def employee_access(request):
    return JsonResponse({"ok": True, "role": User.Role.EMPLOYEE})


@require_POST
@require_role(User.Role.ADMIN)
@database_write_errors
def reset_password_view(request, user_id):
    try:
        key=None
        if is_json(request) and request.body:
            from apps.common.http import json_object,identifier
            body=json_object(request)
            if set(body) not in (set(),{"idempotency_key"}):raise AccessError("VALIDATION_ERROR","비밀번호 재설정 요청 키를 확인해 주세요.",422)
            key=identifier(body["idempotency_key"]) if "idempotency_key" in body else None
        user = reset_password(request.user, user_id, idempotency_key=key)
    except AccessError as exc:
        return api_error(exc.code, exc.message, exc.status, exc.fields)
    return JsonResponse({"id": str(user.pk), "must_change_password": True})


@require_GET
@require_role(User.Role.ADMIN)
def admin_home(request):
    return render(request, "accounts/home.html", {"role_title": "관리자", "access_path": "/api/access/admin"})


@require_GET
@require_role(User.Role.EMPLOYEE)
def employee_home(request):
    return render(request, "accounts/home.html", {"role_title": "직원", "access_path": "/api/access/employee"})
