"""Free-tier reservations and dispatch pacing. Mutations require business_write."""
from datetime import datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db.models import Q
from .models import AIProviderQuota, AIProviderQuotaDay, AIProviderDispatch

PACIFIC = ZoneInfo("America/Los_Angeles")
STAFF_DAILY_LIMIT = 40


def is_free(config):
    return config.provider == "gemini" and config.usage_tier == "free"


def scope_key(config):
    return sha256(("gemini\0"+config.model+"\0"+config.free_project_id.strip()).encode()).hexdigest()


def provider_day(now):
    return now.astimezone(PACIFIC).date()


def reset_at(day):
    return datetime.combine(day+timedelta(days=1), time.min, PACIFIC)


def reserve_day(config, now, input_cap):
    from .services import failure
    quota, _ = AIProviderQuota.objects.get_or_create(scope_key=scope_key(config))
    quota = AIProviderQuota.objects.select_for_update().get(pk=quota.pk)
    day, _ = AIProviderQuotaDay.objects.get_or_create(quota=quota, provider_date=provider_day(now))
    day = AIProviderQuotaDay.objects.select_for_update().get(pk=day.pk)
    if day.sent_count+day.reserved_count >= config.free_rpd:
        failure("AI_SERVER_DAILY_LIMIT", "공용 AI 사용 한도 소진 · 개인 잔여 횟수와 관계없이 새 생성을 중단합니다.")
    if quota.cooldown_until and quota.cooldown_until > now:
        failure("AI_SERVER_COOLDOWN", "공급자 한도 안내에 따라 서버 전체 AI가 대기 중입니다.")
    if input_cap > config.free_tpm:
        failure("AI_SERVER_INPUT_LIMIT", "이 요청은 서버 분당 입력 토큰 한도를 넘습니다. 입력 범위를 줄여 주세요.", 422)
    day.reserved_count += 1
    day.save(update_fields=["reserved_count", "updated_at"])
    return day


def dispatch(request, now):
    """Reserve RPM/TPM before I/O; return ready, wait, expired or config_changed."""
    config = settings.AI_CONFIG
    day = AIProviderQuotaDay.objects.select_for_update().select_related("quota").get(pk=request.provider_day_id)
    quota = AIProviderQuota.objects.select_for_update().get(pk=day.quota_id)
    if (not is_free(config) or quota.scope_key != scope_key(config)
            or request.usage_tier != "free" or request.input_tokens_cap > config.free_tpm):
        return "config_changed"
    if day.provider_date != provider_day(now):
        return "expired"
    if day.sent_count >= config.free_rpd:
        return "exhausted"
    rows = list(AIProviderDispatch.objects.filter(quota=quota).filter(
        Q(window_ends_at__isnull=True)|Q(window_ends_at__gt=now)))
    until = now
    if quota.cooldown_until and quota.cooldown_until > until:
        until = quota.cooldown_until
    if len(rows) >= config.free_rpm or sum(r.input_tokens for r in rows)+request.input_tokens_cap > config.free_tpm:
        # Pending I/O keeps its entire reservation, even beyond sixty seconds.
        until = max(until, min((r.window_ends_at or now+timedelta(seconds=2) for r in rows), default=now+timedelta(seconds=2)))
    if until > now:
        request.dispatch_after = until; request.error_code = "AI_RATE_WAIT"
        request.save(update_fields=["dispatch_after", "error_code", "updated_at"])
        return "wait"
    day.reserved_count -= 1; day.sent_count += 1
    day.save(update_fields=["reserved_count", "sent_count", "updated_at"])
    request.provider_sent_at = now; request.dispatch_after = None; request.error_code = ""
    AIProviderDispatch.objects.create(quota=quota, request=request, sent_at=now, input_tokens=request.input_tokens_cap)
    return "ready"


def settle_quota(request, now):
    if not request.provider_day_id:
        return
    if request.provider_sent_at is None:
        day = AIProviderQuotaDay.objects.select_for_update().get(pk=request.provider_day_id)
        day.reserved_count -= 1
        day.save(update_fields=["reserved_count", "updated_at"])
    else:
        # Sent failures/unknowns still consume RPD; never refund an uncertain call.
        AIProviderDispatch.objects.filter(request=request).update(window_ends_at=max(now, request.provider_sent_at+timedelta(seconds=60)))


def reconcile_tokens(request, input_tokens):
    if request.provider_day_id:
        AIProviderDispatch.objects.filter(request=request).update(input_tokens=input_tokens)


def cooldown(request, now, seconds=60, daily=False):
    quota = AIProviderQuota.objects.select_for_update().get(pk=request.provider_day.quota_id)
    until = reset_at(provider_day(now)) if daily else now+timedelta(seconds=max(1, min(seconds, 86400)))
    quota.cooldown_until = max(quota.cooldown_until or until, until)
    quota.save(update_fields=["cooldown_until", "updated_at"])


def snapshot(config, now):
    if not is_free(config):
        return None
    day = AIProviderQuotaDay.objects.filter(quota__scope_key=scope_key(config), provider_date=provider_day(now)).select_related("quota").first()
    quota = day.quota if day else AIProviderQuota.objects.filter(scope_key=scope_key(config)).first()
    used, reserved = (day.sent_count, day.reserved_count) if day else (0, 0)
    until = quota.cooldown_until if quota and quota.cooldown_until and quota.cooldown_until > now else None
    return {"daily_limit": config.free_rpd, "sent_count": used, "reserved_count": reserved,
            "remaining_count": max(0, config.free_rpd-used-reserved),
            "reset_at": reset_at(provider_day(now)).isoformat(),
            "cooldown_until": until.isoformat() if until else None,
            "rpm": config.free_rpm, "tpm": config.free_tpm}
