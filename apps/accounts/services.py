from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.core.exceptions import ValidationError

from apps.accounts.access import AccessError, verify_actor
from apps.accounts.forms import PasswordChangeForm
from apps.accounts.models import LoginFailure, User
from apps.accounts.bootstrap import BOOTSTRAP_ADMIN_ID, BOOTSTRAP_ADMIN_PASSWORD
from apps.common.transactions import business_write, retry_transient_write
from apps.common.validation import normalize_phone
from apps.operations.models import OperationEvent

INITIAL_PASSWORD = "dodream"


@retry_transient_write
def attempt_login(request, phone, password):
    try:
        phone = normalize_phone(phone)
    except ValidationError:
        phone = phone.strip()[:32]
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
            return None, AccessError("INVALID_CREDENTIALS", "아이디 또는 전화번호와 비밀번호를 확인해 주세요.", 401)
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
def reset_password(actor, target_id, *, idempotency_key=None):
    from apps.common.receipts import fingerprint,replay,remember
    from apps.common.http import identifier
    key=identifier(idempotency_key) if idempotency_key is not None else None
    body_hash=fingerprint({"target_id":str(target_id)})
    with business_write():
        users = {u.pk: u for u in User.objects.select_for_update().filter(pk__in=[actor.pk, target_id]).order_by("pk")}
        verify_actor(actor, users[actor.pk], admin=True)
        if key:
            cached=replay(users[actor.pk],"PASSWORD_RESET",key,body_hash)
            if cached:return users.get(target_id)
        target = users.get(target_id)
        if target is None:
            raise AccessError("NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)
        target.set_password(BOOTSTRAP_ADMIN_PASSWORD if target.phone_normalized == BOOTSTRAP_ADMIN_ID else INITIAL_PASSWORD)
        target.must_change_password = True
        target.session_version += 1
        target.save(update_fields=["password", "must_change_password", "session_version", "updated_at"])
        OperationEvent.objects.create(actor=users[actor.pk], operation="PASSWORD_RESET", occurred_at=timezone.now(), affected_count=1)
        if key:remember(users[actor.pk],"PASSWORD_RESET",key,body_hash,{"ok":True,"id":str(target.pk)},target_ids=[target.pk])
        return target


def set_user_access(actor, target_id, *, is_active=None, role=None):
    """Compatibility entry point, sharing P4's atomic user/deactivation rules."""
    from apps.accounts.management_services import update_access
    return update_access(actor,target_id,is_active=is_active,role=role)
