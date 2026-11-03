from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.core.exceptions import ValidationError

from apps.accounts.access import AccessError, verify_actor
from apps.accounts.forms import PasswordChangeForm
from apps.accounts.models import LoginFailure, User
from apps.common.transactions import business_write, retry_transient_write
from apps.common.validation import normalize_phone
from apps.operations.models import OperationEvent

INITIAL_PASSWORD = "dodream"


@retry_transient_write
def attempt_login(request, phone, password):
    try:
        phone = normalize_phone(phone)
    except ValidationError:
        phone = phone[:32]
    account_key = salted_hmac("tm.login.account", phone, algorithm="sha256").hexdigest()
    request_key = salted_hmac("tm.login.request", request.META.get("REMOTE_ADDR", "unknown"), algorithm="sha256").hexdigest()
    since = timezone.now() - timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS)
    # The global transaction lock also prevents concurrent attempts bypassing limits.
    with business_write():
        LoginFailure.objects.filter(created_at__lt=since).delete()
        failures = LoginFailure.objects.filter(created_at__gte=since)
        if (failures.filter(account_key=account_key).count() >= settings.LOGIN_ACCOUNT_FAILURE_LIMIT
                or failures.filter(request_key=request_key).count() >= settings.LOGIN_REQUEST_FAILURE_LIMIT):
            return None, AccessError("LOGIN_RATE_LIMITED", "로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.", 429)
        user = authenticate(request, phone_normalized=phone, password=password)
        if user is None:
            LoginFailure.objects.create(account_key=account_key, request_key=request_key)
            return None, AccessError("INVALID_CREDENTIALS", "전화번호와 비밀번호를 확인해 주세요.", 401)
        LoginFailure.objects.filter(account_key=account_key).delete()
        return user, None


@retry_transient_write
def change_password(actor, data):
    with business_write():
        user = User.objects.select_for_update().get(pk=actor.pk)
        verify_actor(actor, user, allow_initial=True)
        form = PasswordChangeForm(user, data)
        if not form.is_valid():
            raise AccessError("VALIDATION_ERROR", "입력한 항목을 확인해 주세요.", 422, dict(form.errors))
        user.set_password(form.cleaned_data["new_password"])
        user.must_change_password = False
        user.session_version += 1
        user.save(update_fields=["password", "must_change_password", "session_version", "updated_at"])
        OperationEvent.objects.create(actor=user, operation="PASSWORD_CHANGED", occurred_at=timezone.now(), affected_count=1)
        return user


@retry_transient_write
def reset_password(actor, target_id):
    with business_write():
        users = {u.pk: u for u in User.objects.select_for_update().filter(pk__in=[actor.pk, target_id]).order_by("pk")}
        verify_actor(actor, users[actor.pk], admin=True)
        target = users.get(target_id)
        if target is None:
            raise AccessError("NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)
        target.set_password(INITIAL_PASSWORD)
        target.must_change_password = True
        target.session_version += 1
        target.save(update_fields=["password", "must_change_password", "session_version", "updated_at"])
        OperationEvent.objects.create(actor=users[actor.pk], operation="PASSWORD_RESET", occurred_at=timezone.now(), affected_count=1)
        return target


@retry_transient_write
def set_user_access(actor, target_id, *, is_active=None, role=None):
    """Foundation service for later user management. No partial deactivation writes."""
    from apps.assignments.models import Assignment
    from apps.customers.models import Customer

    with business_write():
        users = {u.pk: u for u in User.objects.select_for_update().filter(pk__in=[actor.pk, target_id]).order_by("pk")}
        verify_actor(actor, users[actor.pk], admin=True)
        target = users.get(target_id)
        if not target:
            raise AccessError("NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)
        new_active = target.is_active if is_active is None else is_active
        new_role = target.role if role is None else role
        if type(new_active) is not bool or new_role not in User.Role.values:
            raise AccessError("VALIDATION_ERROR", "활성 상태 또는 역할이 올바르지 않습니다.", 422)
        if target.role == User.Role.ADMIN and target.is_active and (not new_active or new_role != User.Role.ADMIN):
            if not User.objects.filter(is_active=True, role=User.Role.ADMIN).exclude(pk=target.pk).exists():
                raise AccessError("LAST_ACTIVE_ADMIN", "마지막 활성 관리자는 비활성화하거나 직원으로 변경할 수 없습니다.", 409)
        if (new_active, new_role) == (target.is_active, target.role):
            return target
        if target.is_active and not new_active:
            # Lock order: sorted users -> sorted customers -> assignments.
            customers = list(Customer.objects.select_for_update(of=("self",)).filter(
                current_assignment__employee=target,
                current_assignment__first_activity_at__isnull=True,
                current_assignment__ended_at__isnull=True,
            ).exclude(current_assignment=None).order_by("pk"))
            assignment_ids = [c.current_assignment_id for c in customers]
            assignments = list(Assignment.objects.select_for_update().filter(pk__in=assignment_ids).order_by("pk"))
            now = timezone.now()
            for customer in customers:
                customer.current_assignment = None
                customer.version += 1
                customer.save(update_fields=["current_assignment", "version", "updated_at"])
            for assignment in assignments:
                assignment.ended_at = now
                assignment.end_reason = Assignment.EndReason.USER_DISABLED
                assignment.ended_by = users[actor.pk]
                assignment.save(update_fields=["ended_at", "end_reason", "ended_by", "updated_at"])
        target.is_active, target.role = new_active, new_role
        target.session_version += 1
        target.save(update_fields=["is_active", "role", "session_version", "updated_at"])
        OperationEvent.objects.create(actor=users[actor.pk], operation="USER_ACCESS_CHANGED", occurred_at=timezone.now(), affected_count=1)
        return target
