import uuid
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.common.validation import normalize_phone
from apps.accounts.bootstrap import BOOTSTRAP_ADMIN_ID


class UserManager(BaseUserManager):
    def create_user(self, phone_normalized, name, password=None, **extra_fields):
        identifier = (BOOTSTRAP_ADMIN_ID if phone_normalized == BOOTSTRAP_ADMIN_ID
                      and extra_fields.get("role") == "ADMIN" else normalize_phone(phone_normalized))
        user = self.model(phone_normalized=identifier, name=name.strip(), **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, *args, **kwargs):
        raise ValueError("업무 관리자는 create_initial_admin 명령으로 생성해 주세요.")


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "관리자"
        EMPLOYEE = "EMPLOYEE", "직원"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    phone_normalized = models.CharField(max_length=11, unique=True)
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.EMPLOYEE)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=True)
    session_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = UserManager()
    USERNAME_FIELD = "phone_normalized"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(phone_normalized__regex=r"^010[0-9]{8}$")
                | Q(phone_normalized=BOOTSTRAP_ADMIN_ID, role="ADMIN"),
                name="user_login_identifier_format"),
            models.CheckConstraint(condition=Q(role__in=["ADMIN", "EMPLOYEE"]), name="user_role_valid"),
            models.CheckConstraint(condition=Q(name__regex=r"\S"), name="user_name_not_empty"),
            models.CheckConstraint(condition=Q(session_version__gte=1), name="user_session_version_positive"),
        ]

    def __str__(self):
        return self.name


class LoginFailure(models.Model):
    """HMAC keys only: no raw phone, IP, password or session token."""
    account_key = models.CharField(max_length=64, db_index=True)
    request_key = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
