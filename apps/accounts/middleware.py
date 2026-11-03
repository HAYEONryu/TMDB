from django.contrib.auth import SESSION_KEY, logout
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from apps.accounts.access import api_error
from apps.accounts.models import User

SESSION_VERSION_KEY = "tm_session_version"


class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session_error = None
        user_id = request.session.get(SESSION_KEY)
        if user_id:
            try:
                current = User.objects.filter(pk=user_id).first()
            except (ValueError, TypeError, ValidationError):
                current = None
            if not current or not current.is_active:
                session_error = "ACCOUNT_DISABLED" if current else "UNAUTHENTICATED"
            elif request.session.get(SESSION_VERSION_KEY) != current.session_version:
                session_error = "UNAUTHENTICATED"
            elif not request.user.is_authenticated:
                session_error = "UNAUTHENTICATED"
            if session_error:
                logout(request)

        business_path = request.path == "/" or request.path.startswith(("/api/", "/app/"))
        if business_path and request.path != "/api/me":
            if not request.user.is_authenticated:
                response = api_error(session_error or "UNAUTHENTICATED", "다시 로그인해 주세요.", 401) if request.path.startswith("/api/") else redirect("/auth/login")
            elif request.user.must_change_password:
                response = api_error("PASSWORD_CHANGE_REQUIRED", "업무를 시작하기 전에 비밀번호를 변경해 주세요.") if request.path.startswith("/api/") else redirect("/auth/password")
            else:
                response = self.get_response(request)
        else:
            response = self.get_response(request)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "same-origin"
        return response
