from django.db import IntegrityError, transaction
from django.utils import timezone
from apps.accounts.access import AccessError, verify_actor
from apps.accounts.models import User
from apps.common.transactions import business_write, retry_transient_write
from apps.common.validation import site_name_key
from apps.operations.models import OperationEvent
from apps.sites.models import DefaultSiteHistory, GlobalSettings, Site


def locked_actor(actor, *, admin=False, extra_ids=()):
    users = {u.pk: u for u in User.objects.select_for_update().filter(pk__in=[actor.pk, *extra_ids]).order_by("pk")}
    current = users.get(actor.pk)
    if current is None:
        raise AccessError("UNAUTHENTICATED", "다시 로그인해 주세요.", 401)
    verify_actor(actor, current, admin=admin)
    return current


def locked_settings():
    GlobalSettings.objects.get_or_create(pk=1)
    return GlobalSettings.objects.select_for_update().get(pk=1)


def change_default(settings, site, actor, now):
    previous = settings.default_site_id
    new_id=site.pk if site else None
    if previous == new_id:
        return False
    settings.default_site = site
    settings.version += 1
    settings.save(update_fields=["default_site", "version", "updated_at"])
    DefaultSiteHistory.objects.create(previous_site_id=previous, new_site=site,
        previous_site_id_snapshot=previous, new_site_id_snapshot=new_id, changed_at=now, changed_by=actor,settings_version=settings.version)
    OperationEvent.objects.create(actor=actor, operation="DEFAULT_SITE_CHANGED", occurred_at=now, affected_count=1)
    return True


@retry_transient_write
def create_site(actor, name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise AccessError("VALIDATION_ERROR", "현장명은 1~100자로 입력해 주세요.", 422, {"name": ["현장명을 확인해 주세요."]})
    name = name.strip()
    if len(site_name_key(name)) > 100:
        raise AccessError("VALIDATION_ERROR", "현장명 정규화 결과가 너무 깁니다.", 422)
    with business_write():
        actor = locked_actor(actor, admin=True)
        settings = locked_settings()
        first = not Site.objects.exists()
        try:
            with transaction.atomic():
                site = Site.objects.create(name=name, name_key=site_name_key(name), created_by=actor)
        except IntegrityError:
            raise AccessError("DUPLICATE_SITE", "이미 존재하는 현장명입니다.", 409)
        now = timezone.now()
        if first:
            change_default(settings, site, actor, now)
        OperationEvent.objects.create(actor=actor, operation="SITE_CREATED", occurred_at=now, affected_count=1)
        return site, settings


@retry_transient_write
def set_default_site(actor, site_id, expected_version):
    if type(expected_version) is not int or expected_version < 1:
        raise AccessError("VALIDATION_ERROR", "설정 버전을 확인해 주세요.", 422)
    with business_write():
        actor = locked_actor(actor, admin=True)
        settings = locked_settings()
        if settings.version != expected_version:
            raise AccessError("VERSION_CONFLICT", "다른 관리자가 설정을 변경했습니다. 새로고침해 주세요.", 409)
        site = Site.objects.select_for_update().filter(pk=site_id).first()
        if not site:
            raise AccessError("SITE_DELETED", "현장이 삭제되었거나 존재하지 않습니다.", 409)
        changed = change_default(settings, site, actor, timezone.now())
        return settings, changed
