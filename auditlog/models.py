from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuditEventQuerySet(models.QuerySet):
    """Protege los registros contra operaciones masivas de modificación y eliminación."""

    def update(self, **kwargs):
        raise ValidationError("AuditEvent es append-only y no permite modificaciones masivas.")

    def delete(self):
        raise ValidationError("AuditEvent es append-only y no permite eliminaciones masivas.")


class AuditEventManager(models.Manager.from_queryset(AuditEventQuerySet)):
    pass


class AuditEvent(models.Model):
    objects = AuditEventManager()

    actor_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, related_name="audit_events", null=True, blank=True
    )
    action_code = models.CharField(max_length=80)
    resource_type = models.CharField(max_length=80)
    resource_id = models.CharField(max_length=80, null=True, blank=True)
    description = models.CharField(max_length=240, blank=True)
    before_data = models.JSONField(null=True, blank=True)
    after_data = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "audit_event"
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=("-occurred_at",), name="idx_audit_occurred_at"),
            models.Index(fields=("actor_user", "-occurred_at"), name="idx_audit_actor_time"),
            models.Index(fields=("action_code", "-occurred_at"), name="idx_audit_action_time"),
            models.Index(fields=("resource_type", "resource_id"), name="idx_audit_resource"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("AuditEvent es append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent es append-only.")

    def __str__(self):
        return f"{self.action_code} · {self.occurred_at:%Y-%m-%d %H:%M:%S}"