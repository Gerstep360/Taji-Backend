"""Persistencia de CU32, independiente de Incident y AccessEvent."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class VisualSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    condominium = models.ForeignKey('condominiums.Condominium', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sector = models.ForeignKey('condominiums.Sector', null=True, on_delete=models.SET_NULL)
    keep_evidence = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('condominium', 'owner'),
                                               condition=Q(ended_at__isnull=True), name='cu32_one_active_session')]


class VisualObservation(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued'
        RUNNING = 'running'
        SUCCEEDED = 'succeeded'
        FAILED = 'failed'
        CANCELLED = 'cancelled'
        SKIPPED = 'skipped'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(VisualSession, on_delete=models.CASCADE, related_name='observations')
    window = models.UUIDField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    mode = models.CharField(max_length=5)
    observed_from = models.DateTimeField()
    observed_until = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    payload = models.BinaryField(null=True, editable=False)
    payload_bytes = models.PositiveIntegerField(default=0)
    evidence = models.BinaryField(null=True, editable=False)
    has_evidence = models.BooleanField(default=False)
    model_id = models.CharField(max_length=120, blank=True)
    provider_ms = models.PositiveIntegerField(null=True)
    provider_error = models.CharField(max_length=48, blank=True)
    description = models.CharField(max_length=320, blank=True)
    prediction = models.JSONField(default=dict, blank=True)
    matches = models.JSONField(default=list, blank=True)
    review_status = models.CharField(max_length=16, default='pending')
    review_text = models.CharField(max_length=320, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('session', 'window'), name='cu32_unique_visual_window')]
        indexes = [models.Index(fields=('status', 'received_at'), name='cu32_visual_queue_idx'),
                   models.Index(fields=('session', '-observed_until'), name='cu32_visual_history_idx'),
                   models.Index(fields=('received_at',), name='cu32_visual_budget_idx')]


class VisualQuota(models.Model):
    """Una fila usada como mutex transaccional para las cuotas compartidas."""

    worker_seen_at = models.DateTimeField(null=True)
