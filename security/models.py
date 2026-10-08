import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from tenancy.managers import TenantAwareManager


class VisitAuthorization(models.Model):
    objects = TenantAwareManager()

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
    # RF-09 / T021: identidad pública del QR actual y su expiración.
    # `qr_token_hash` es el SHA-256 hexadecimal del token opaco contenido en el QR;
    # nunca se persiste el token en claro, de modo que una filtración de la base de
    # datos no permite clonar accesos. Es NULL mientras no se ha emitido un QR.
    qr_token_hash = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    qr_issued_at = models.DateTimeField(null=True, blank=True)
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

    def is_qr_issued(self):
        """True cuando ya se emitió un QR con token vigente para esta autorización."""
        return bool(self.qr_token_hash and self.qr_issued_at)

    def is_qr_active(self, at=None):
        """
        RF-09: el QR solo es utilizable si fue emitido, no expiró,
        la autorización no está en estado terminal y la visita está dentro de su ventana.
        """
        moment = at or timezone.now()
        if not self.is_qr_issued():
            return False
        if self.status in (
            self.Status.CANCELLED,
            self.Status.FINISHED,
            self.Status.EXPIRED,
        ):
            return False
        if self.qr_expires_at <= moment or self.valid_until <= moment:
            return False
        if self.valid_from > moment:
            return False
        return True

    def qr_seconds_remaining(self, at=None):
        """Segundos restantes de vigencia del QR; 0 si ya no es utilizable."""
        if not self.is_qr_issued():
            return 0
        remaining = int((self.qr_expires_at - (at or timezone.now())).total_seconds())
        return max(remaining, 0)


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
    unit = models.ForeignKey(
        "condominiums.Unit",
        on_delete=models.PROTECT,
        related_name="access_events",
        null=True,
        blank=True,
    )
    person = models.ForeignKey(
        "accounts.Person", on_delete=models.PROTECT, related_name="access_events", null=True, blank=True
    )
    visitor_name = models.CharField(max_length=220, blank=True)
    visitor_document_number = models.CharField(max_length=30, blank=True)
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


class VisitQrScan(models.Model):
    """
    Bitácora de **todo** escaneo realizado por el personal de seguridad (RF-10).

    `AccessEvent` responde a "¿quién entró y a qué hora?", por lo que solo
    registra los escaneos que resuelven a una autorización real. Esta tabla
    responde a la otra pregunta de la portería: "¿cuántos escaneos se hicieron,
    cuántos fueron exitosos, cuántos fallidos y por qué?".

    A diferencia de `AccessEvent`, aquí también se persisten los códigos QR
    desconocidos (`NOT_FOUND`), porque son precisamente los intentos
    sospechosos que la seguridad necesita ver. El texto escaneado nunca se
    guarda en claro: solo su SHA-256, igual que el token de la autorización.
    """

    class Result(models.TextChoices):
        VALID = "VALID", "Válido"
        REJECTED = "REJECTED", "Denegado"
        NOT_FOUND = "NOT_FOUND", "Código desconocido"

    authorization = models.ForeignKey(
        VisitAuthorization,
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    access_event = models.ForeignKey(
        AccessEvent,
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    guard_staff = models.ForeignKey(
        "condominiums.Staff",
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    scanned_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    # Código de motivo (`VALID` o un valor de `QrRejection`), consultable y no truncado.
    reason = models.CharField(max_length=40)
    message = models.CharField(max_length=300, blank=True)
    # SHA-256 del texto escaneado. Permite correlacionar intentos del mismo
    # código sin almacenar un token reutilizable.
    scanned_token_hash = models.CharField(max_length=64, blank=True, editable=False)
    visitor_name = models.CharField(max_length=220, blank=True)
    visitor_document_number = models.CharField(max_length=30, blank=True)
    device_id = models.CharField(max_length=120, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "visit_qr_scan"
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=("-occurred_at",), name="idx_qr_scan_time"),
            models.Index(fields=("result", "-occurred_at"), name="idx_qr_scan_result"),
            models.Index(fields=("guard_staff", "-occurred_at"), name="idx_qr_scan_guard"),
            models.Index(fields=("scanned_token_hash",), name="idx_qr_scan_token"),
        ]

    def __str__(self) -> str:
        return f"{self.get_result_display()} ({self.reason}) @ {self.occurred_at:%Y-%m-%d %H:%M}"


class SecurityShift(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programado"
        OPEN = "OPEN", "Abierto"
        CLOSED = "CLOSED", "Cerrado"
        CANCELLED = "CANCELLED", "Cancelado"

    condominium = models.ForeignKey(
        "condominiums.Condominium",
        on_delete=models.SET_NULL,
        related_name="security_shifts",
        null=True,
        blank=True,
    )
    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_security_shifts",
        null=True,
        blank=True,
    )
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
    observation = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


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
    # Data URL base64 de la foto de referencia. TextField y no CharField: una
    # captura real de cámara supera con creces los 500 caracteres y PostgreSQL
    # rechazaba el INSERT con DataError (HTTP 503 en la API).
    reference_image = models.TextField(blank=True)
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

    # Data URL base64 de la captura del guardia. TextField y no CharField: una
    # foto real de 640x480 en JPEG ocupa cientos de KB y PostgreSQL recortaba
    # el INSERT a varchar(500) lanzando DataError (HTTP 503 en la API).
    captured_image = models.TextField(blank=True)
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