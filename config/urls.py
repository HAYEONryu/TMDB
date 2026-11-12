from django.urls import path
from apps.accounts import views
from apps.ai_assistant.views import availability
from apps.sites import views as site_views
from apps.customers import views as customer_views
from apps.imports import views as import_views
from apps.assignments import views as assignment_views
from apps.accounts import management_views as user_views
from apps.customers import employee as employee_views
from apps.callbacks.views import complete_view
from apps.consultations.views import history
from apps.operations.dashboard import dashboard
from apps.customers import deletion_views
from apps.ai_assistant import views as ai_views

from apps.ai_assistant import admin_views as admin_ai

urlpatterns = [
    path("app/admin/ai",admin_ai.page),
    path("app/admin/ai/cases/<uuid:customer_id>",admin_ai.case_page),
    path("app/guides",admin_ai.published_page),
    path("api/ai/weekly-briefings",admin_ai.reports,{"feature":"WEEKLY_BRIEFING"}),
    path("api/ai/employees/<uuid:employee_id>/coaching",admin_ai.reports,{"feature":"EMPLOYEE_COACHING"}),
    path("api/ai/sites/<uuid:site_id>/guides",admin_ai.reports,{"feature":"TEAM_GUIDE"}),
    path("api/ai/guides/<uuid:result_id>",admin_ai.guide_write),
    path("api/ai/guides/<uuid:result_id>/publish",admin_ai.guide_write,{"publish":True}),
    path("api/sites/<uuid:site_id>/published-guide",admin_ai.published),
    path('api/ai/customer-tasks',ai_views.customer_task),
    path('api/ai/customer-readiness',ai_views.customer_readiness),
    path('api/ai/customer-results',ai_views.customer_results),
    path('api/ai/tasks/<uuid:task_id>', ai_views.task_detail),
    path('api/ai/results/<uuid:result_id>', ai_views.result_detail),
    path('api/ai/usage', ai_views.usage),
    path('api/sites/<uuid:site_id>/knowledge', ai_views.knowledge_list),
    path('api/sites/<uuid:site_id>/knowledge/<uuid:knowledge_id>', ai_views.knowledge_update),
    path('api/customers/<uuid:customer_id>/deletion-request',deletion_views.request_deletion),
    path('api/deletion-requests',deletion_views.pending),
    path('api/deletion-requests/<uuid:request_id>/approve',deletion_views.approve_request),
    path('api/customers/<uuid:customer_id>/hard-delete',deletion_views.delete_customer),
    path('api/sites/<uuid:site_id>/hard-delete',deletion_views.delete_site),
    path('api/sites/<uuid:site_id>/deletion-confirmation',deletion_views.confirm_site_view),
    path('api/dashboard',dashboard),
    path('api/customers/<uuid:customer_id>/callback-complete',complete_view),
    path('api/customers/<uuid:customer_id>/history',history),
    path("app/employee/today",employee_views.page,{"view":"today"}),
    path("app/employee/mine",employee_views.page,{"view":"mine"}),
    path("api/employee/context",employee_views.context),
    path("api/employee/queue-check",employee_views.check_queue),
    path("api/employee/batch-update",employee_views.save),
    path("app/admin/assignments",assignment_views.page),
    path("app/admin/users",user_views.page),
    path("api/assignments/availability",assignment_views.availability),
    path("api/assignments/distribute",assignment_views.distribute),
    path("api/assignments/recall-preview",assignment_views.preview),
    path("api/assignments/recall",assignment_views.recall),
    path("api/customers/<uuid:customer_id>/assignee",assignment_views.assignee),
    path("api/users",user_views.users),
    path("api/users/batch-update",user_views.update),
    path("api/users/transfer-needed",user_views.transfers),
    path("app/admin/imports", import_views.page),
    path("api/imports/template", import_views.template),
    path("api/imports/validate", import_views.validate),
    path("api/imports/<uuid:batch_id>", import_views.results),
    path("api/imports/<uuid:batch_id>/commit", import_views.commit),
    path("api/sites", site_views.sites),
    path("api/sites/<uuid:site_id>", site_views.rename),
    path("api/sites/<uuid:site_id>/counts", site_views.counts),
    path("api/settings/default-site", site_views.default_site),
    path("api/customers", customer_views.customers),
    path("api/customers/filter-options", customer_views.options),
    path("api/customers/batch-update", customer_views.batch_update),
    path("api/customers/soft-delete", customer_views.soft_delete),
    path("api/customers/restore", customer_views.restore),
    path("app/admin/customers", customer_views.management),
    path("app/admin/trash", customer_views.management, {"trash": True}),
    path("api/ai/availability", availability),
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
