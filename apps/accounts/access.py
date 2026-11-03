from functools import wraps
from django.http import JsonResponse
from django.shortcuts import redirect
from django.db import OperationalError


class AccessError(Exception):
    def __init__(self, code, message, status=403, fields=None):
        self.code, self.message, self.status, self.fields = code, message, status, fields
        super().__init__(code)


def api_error(code, message, status=403, fields=None):
    payload = {"error": {"code": code, "message": message}}
    if fields:
        payload["error"]["fields"] = fields
    return JsonResponse(payload, status=status)


def database_write_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except OperationalError:
            return api_error("TEMPORARY_UNAVAILABLE", "일시적으로 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.", 503)
    return wrapped


def require_role(role=None):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return api_error("UNAUTHENTICATED", "로그인이 필요합니다.", 401) if request.path.startswith("/api/") else redirect("/auth/login")
            if role and request.user.role != role:
                return api_error("FORBIDDEN", "접근 권한이 없습니다.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def verify_actor(actor, locked_actor, *, admin=False, allow_initial=False):
    if not locked_actor.is_active:
        raise AccessError("ACCOUNT_DISABLED", "비활성화된 계정입니다.", 401)
    if locked_actor.session_version != actor.session_version:
        raise AccessError("UNAUTHENTICATED", "다시 로그인해 주세요.", 401)
    if not allow_initial and locked_actor.must_change_password:
        raise AccessError("PASSWORD_CHANGE_REQUIRED", "비밀번호를 먼저 변경해 주세요.")
    if admin and locked_actor.role != "ADMIN":
        raise AccessError("FORBIDDEN", "관리자 권한이 필요합니다.")
