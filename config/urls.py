from django.urls import path
from apps.accounts import views

urlpatterns = [
    path("healthz", views.health),
    path("", views.home),
    path("auth/login", views.login_view),
    path("auth/logout", views.logout_view),
    path("auth/password", views.password_view),
    path("api/me", views.me),
    path("api/access/admin", views.admin_access),
    path("api/access/employee", views.employee_access),
    path("api/users/<uuid:user_id>/reset-password", views.reset_password_view),
    path("app/admin", views.admin_home),
    path("app/employee", views.employee_home),
]
