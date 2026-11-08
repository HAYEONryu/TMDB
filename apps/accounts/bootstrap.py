"""Public, one-time bootstrap credentials; never overwrite an existing account."""
from django.utils import timezone

from apps.common.transactions import business_write, retry_transient_write

BOOTSTRAP_ADMIN_ID = "admin"
BOOTSTRAP_ADMIN_PASSWORD = "admin123"


@retry_transient_write
def ensure_initial_admin():
    from apps.accounts.models import User
    from apps.operations.models import OperationEvent

    with business_write():
        # An existing installation must never gain a new default-password login.
        # This also preserves changed passwords, disabled accounts and role limits.
        if User.objects.exists():
            return False
        account = User.objects.create_user(
            BOOTSTRAP_ADMIN_ID, "최초관리자", BOOTSTRAP_ADMIN_PASSWORD,
            role=User.Role.ADMIN, must_change_password=True,
        )
        OperationEvent.objects.create(
            actor=account, operation="INITIAL_ADMIN_CREATED",
            occurred_at=timezone.now(), affected_count=1,
        )
        return True
