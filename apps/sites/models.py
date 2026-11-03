from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.common.models import TimestampedModel
from apps.common.validation import site_name_key


class Site(TimestampedModel):
    name = models.CharField(max_length=100)
    name_key = models.CharField(max_length=100, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_sites")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(name__regex=r"\S"), name="site_name_not_empty")]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.name_key = site_name_key(self.name)
        if kwargs.get("update_fields"):
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"name_key"}
        super().save(*args, **kwargs)


class GlobalSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    default_site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_settings")
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="settings_singleton"),
            models.CheckConstraint(condition=Q(version__gte=1), name="settings_version_positive"),
        ]


class DefaultSiteHistory(TimestampedModel):
    previous_site = models.ForeignKey(Site, null=True, on_delete=models.SET_NULL, related_name="previous_default_history")
    new_site = models.ForeignKey(Site, null=True, on_delete=models.SET_NULL, related_name="new_default_history")
    previous_site_id_snapshot = models.UUIDField(null=True)
    new_site_id_snapshot = models.UUIDField(null=True)
    changed_at = models.DateTimeField(db_index=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="default_site_changes")
