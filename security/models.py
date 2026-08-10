import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class VisitAuthorization(models.Model):
    class Status(models.TextChoices):
        AUTHORIZED = "AUTHORIZED", "Autorizada"
        ACTIVE = "ACTIVE", "Activa"
        FINISHED = "FINISHED", "Finalizada"
        CANCELLED = "CANCELLED", "Cancelada"
        EXPIRED = "EXPIRED", "Expirada"

    visitor_person = models.ForeignKey(
        "accounts.Person", on_delete=models.PROTECT, related_name="visit_authorizations"
    )
    authorized_by_resident = models.ForeignKey(
        "condominiums.Resident", on_delete=models.PROTECT, related_name="authorized_visits"
    )
    unit = models.ForeignKey(
        "condominiums.Unit", on_delete=models.PROTECT, related_name="visit_authorizations"
    )
    created_by_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, related_name="created_visits", null=True, blank=True
    )
    purpose = models.CharField(max_length=200, blank=True)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AUTHORIZED)
    qr_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    qr_expires_at = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "visit_authorization"
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_until__gt=models.F("valid_from")), name="chk_visit_dates"
            ),
            models.CheckConstraint(
                condition=Q(qr_expires_at__lte=models.F("valid_until")), name="chk_visit_qr_expiry"
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "valid_from", "valid_until"), name="idx_visit_status_window"
            ),
            models.Index(
                fields=("authorized_by_resident", "-valid_from"), name="idx_visit_resident_time"
            ),
            models.Index(fields=("unit", "-valid_from"), name="idx_visit_unit_time"),
        ]


class AccessEvent(models.Model):
    class Type(models.TextChoices):
        ENTRY = "ENTRY", "Entrada"
        EXIT = "EXIT", "Salida"
        DENIED = "DENIED", "Denegado"

    class Method(models.TextChoices):
        QR = "QR", "QR"
        FACE = "FACE", "Facial"
        MANUAL = "MANUAL", "Manual"

    class Result(models.TextChoices):
        APPROVED = "APPROVED", "Aprobado"
        REJECTED = "REJECTED", "Rechazado"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Revisión manual"

    authorization = models.ForeignKey(
        VisitAuthorization, on_delete=models.PROTECT, related_name="access_events", null=True, blank=True
    )
    person = models.ForeignKey(
        "accounts.Person", on_delete=models.PROTECT, related_name="access_events", null=True, blank=True
    )
    guard_staff = models.ForeignKey(
        "condominiums.Staff",
        on_delete=models.SET_NULL,
        related_name="guarded_access_events",
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=20, choices=Type.choices)
    validation_method = models.CharField(max_length=20, choices=Method.choices, default=Method.MANUAL)
    validation_result = models.CharField(
        max_length=20, choices=Result.choices, default=Result.APPROVED
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "access_event"
        indexes = [
            models.Index(fields=("authorization", "-occurred_at"), name="idx_access_auth_time"),
            models.Index(fields=("person", "-occurred_at"), name="idx_access_person_time"),
            models.Index(fields=("guard_staff", "-occurred_at"), name="idx_access_guard_time"),
        ]


class SecurityShift(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programado"
        OPEN = "OPEN", "Abierto"
        CLOSED = "CLOSED", "Cerrado"
        CANCELLED = "CANCELLED", "Cancelado"

    guard_staff = models.ForeignKey(
        "condominiums.Staff", on_delete=models.PROTECT, related_name="security_shifts"
    )
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    opening_notes = models.TextField(blank=True)
    closing_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "security_shift"
        constraints = [
            models.CheckConstraint(
                condition=Q(scheduled_end__gt=models.F("scheduled_start")),
                name="chk_shift_schedule",
            ),
            models.UniqueConstraint(
                fields=("guard_staff",),
                condition=Q(status="OPEN"),
                name="uq_guard_open_shift",
            ),
        ]
        indexes = [
            models.Index(fields=("guard_staff", "-scheduled_start"), name="idx_shift_guard_start")
        ]


class ShiftLogEntry(models.Model):
    class Type(models.TextChoices):
        NOTE = "NOTE", "Nota"
        INCIDENT = "INCIDENT", "Incidente"
        ALERT = "ALERT", "Alerta"
        HANDOVER_NOTE = "HANDOVER_NOTE", "Entrega de turno"

    class Severity(models.TextChoices):
        INFO = "INFO", "Información"
        LOW = "LOW", "Baja"
        MEDIUM = "MEDIUM", "Media"
        HIGH = "HIGH", "Alta"
        CRITICAL = "CRITICAL", "Crítica"

    shift = models.ForeignKey(SecurityShift, on_delete=models.CASCADE, related_name="log_entries")
    created_by_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, related_name="shift_logs", null=True, blank=True
    )
    sector = models.ForeignKey(
        "condominiums.Sector",
        on_delete=models.SET_NULL,
        related_name="shift_logs",
        null=True,
        blank=True,
    )
    entry_type = models.CharField(max_length=20, choices=Type.choices, default=Type.NOTE)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=120, blank=True)
    description = models.TextField()
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "shift_log_entry"
        indexes = [
            models.Index(fields=("shift", "-occurred_at"), name="idx_shift_log_time")
        ]


class ShiftHandover(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        RECEIVED = "RECEIVED", "Recibida"
        REJECTED = "REJECTED", "Rechazada"

    outgoing_shift = models.OneToOneField(
        SecurityShift, on_delete=models.PROTECT, related_name="outgoing_handover"
    )
    incoming_shift = models.ForeignKey(
        SecurityShift,
        on_delete=models.PROTECT,
        related_name="incoming_handovers",
        null=True,
        blank=True,
    )
    delivered_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="delivered_handovers",
        null=True,
        blank=True,
    )
    received_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="received_handovers",
        null=True,
        blank=True,
    )
    summary = models.TextField()
    delivered_at = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = "shift_handover"
        constraints = [
            models.CheckConstraint(
                condition=Q(received_at__isnull=True)
                | Q(received_at__gte=models.F("delivered_at")),
                name="chk_handover_receive_time",
            )
        ]


class BiometricReference(models.Model):
    resident = models.ForeignKey(
        "condominiums.Resident", on_delete=models.CASCADE, related_name="biometric_references"
    )
    reference_image = models.CharField(max_length=500, blank=True)
    embedding = models.BinaryField()
    embedding_dim = models.SmallIntegerField()
    model_name = models.CharField(max_length=80)
    model_version = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    enrolled_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="biometric_enrollments",
        null=True,
        blank=True,
    )
    enrolled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "biometric_reference"
        constraints = [
            models.UniqueConstraint(
                fields=("resident",),
                condition=Q(is_active=True),
                name="uq_active_biometric_ref",
            )
        ]


class FaceVerification(models.Model):
    class Result(models.TextChoices):
        MATCH = "MATCH", "Coincidencia"
        NO_MATCH = "NO_MATCH", "Sin coincidencia"
        REVIEW = "REVIEW", "Revisión"

    captured_image = models.CharField(max_length=500, blank=True)
    matched_resident = models.ForeignKey(
        "condominiums.Resident",
        on_delete=models.SET_NULL,
        related_name="face_verifications",
        null=True,
        blank=True,
    )
    biometric_reference = models.ForeignKey(
        BiometricReference,
        on_delete=models.SET_NULL,
        related_name="verifications",
        null=True,
        blank=True,
    )
    guard_staff = models.ForeignKey(
        "condominiums.Staff",
        on_delete=models.SET_NULL,
        related_name="face_verifications",
        null=True,
        blank=True,
    )
    access_event = models.ForeignKey(
        AccessEvent,
        on_delete=models.SET_NULL,
        related_name="face_verifications",
        null=True,
        blank=True,
    )
    similarity_score = models.DecimalField(max_digits=6, decimal_places=5, null=True, blank=True)
    threshold = models.DecimalField(max_digits=6, decimal_places=5, null=True, blank=True)
    model_name = models.CharField(max_length=80)
    model_version = models.CharField(max_length=40)
    result = models.CharField(max_length=20, choices=Result.choices)
    human_confirmed = models.BooleanField(null=True, blank=True)
    confirmed_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="confirmed_faces",
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "face_verification"
        constraints = [
            models.CheckConstraint(
                condition=Q(similarity_score__isnull=True)
                | Q(similarity_score__gte=0, similarity_score__lte=1),
                name="chk_face_score",
            ),
            models.CheckConstraint(
                condition=Q(threshold__isnull=True) | Q(threshold__gte=0, threshold__lte=1),
                name="chk_face_threshold",
            ),
        ]
        indexes = [
            models.Index(fields=("-verified_at",), name="idx_face_verify_time"),
            models.Index(
                fields=("matched_resident", "-verified_at"), name="idx_face_resident_time"
            ),
        ]