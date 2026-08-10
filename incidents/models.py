from django.db import models
from django.db.models import Q
from django.utils import timezone


STAFF_TYPE_CHOICES = (
    ("ADMINISTRATION", "Administración"),
    ("SECURITY", "Seguridad"),
    ("MAINTENANCE", "Mantenimiento"),
    ("CLEANING", "Limpieza"),
    ("OTHER", "Otro"),
)


class IncidentCategory(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=240, blank=True)
    default_staff_type = models.CharField(
        max_length=20, choices=STAFF_TYPE_CHOICES, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "incident_category"

    def __str__(self):
        return self.name


class PriorityLevel(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=40, unique=True)
    rank = models.SmallIntegerField(unique=True)
    min_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    target_minutes = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "priority_level"
        ordering = ("rank",)
        constraints = [
            models.CheckConstraint(condition=Q(rank__gt=0), name="chk_priority_rank"),
            models.CheckConstraint(
                condition=Q(min_score__isnull=True)
                | Q(max_score__isnull=True)
                | Q(max_score__gte=models.F("min_score")),
                name="chk_priority_score_range",
            ),
            models.CheckConstraint(
                condition=Q(target_minutes__isnull=True) | Q(target_minutes__gt=0),
                name="chk_priority_target",
            ),
        ]

    def __str__(self):
        return self.name


class Incident(models.Model):
    class Status(models.TextChoices):
        REPORTED = "REPORTED", "Reportada"
        REVIEWED = "REVIEWED", "Revisada"
        ASSIGNED = "ASSIGNED", "Asignada"
        IN_PROGRESS = "IN_PROGRESS", "En progreso"
        RESOLVED = "RESOLVED", "Resuelta"
        CLOSED = "CLOSED", "Cerrada"
        CANCELLED = "CANCELLED", "Cancelada"

    public_code = models.CharField(max_length=30, unique=True)
    reporter_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="reported_incidents",
        null=True,
        blank=True,
    )
    reporter_resident = models.ForeignKey(
        "condominiums.Resident",
        on_delete=models.SET_NULL,
        related_name="reported_incidents",
        null=True,
        blank=True,
    )
    sector = models.ForeignKey(
        "condominiums.Sector",
        on_delete=models.SET_NULL,
        related_name="incidents",
        null=True,
        blank=True,
    )
    unit = models.ForeignKey(
        "condominiums.Unit",
        on_delete=models.SET_NULL,
        related_name="incidents",
        null=True,
        blank=True,
    )
    asset = models.ForeignKey(
        "maintenance.Asset",
        on_delete=models.SET_NULL,
        related_name="incidents",
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        IncidentCategory, on_delete=models.PROTECT, related_name="incidents", null=True, blank=True
    )
    priority = models.ForeignKey(
        PriorityLevel, on_delete=models.PROTECT, related_name="incidents", null=True, blank=True
    )
    current_assignee_staff = models.ForeignKey(
        "condominiums.Staff",
        on_delete=models.SET_NULL,
        related_name="assigned_incidents",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=160, blank=True)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REPORTED)
    due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "incident"
        indexes = [
            models.Index(
                fields=("status", "priority", "-created_at"),
                name="idx_inc_status_priority",
            ),
            models.Index(
                fields=("current_assignee_staff", "status"),
                name="idx_inc_assignee_status",
            ),
            models.Index(fields=("category", "-created_at"), name="idx_inc_category_time"),
            models.Index(
                fields=("due_at",),
                condition=Q(status__in=("REPORTED", "REVIEWED", "ASSIGNED", "IN_PROGRESS")),
                name="idx_incident_due_open",
            ),
        ]


class IncidentAttachment(models.Model):
    class Type(models.TextChoices):
        IMAGE = "IMAGE", "Imagen"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Documento"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="incident_uploads",
        null=True,
        blank=True,
    )
    file_path = models.CharField(max_length=500)
    file_type = models.CharField(max_length=20, choices=Type.choices, default=Type.IMAGE)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "incident_attachment"
        indexes = [
            models.Index(fields=("incident",), name="idx_inc_attachment_inc")
        ]


class IncidentAssignment(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="assignments")
    assigned_to_staff = models.ForeignKey(
        "condominiums.Staff", on_delete=models.PROTECT, related_name="incident_assignments"
    )
    assigned_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="assigned_incident_actions",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=240, blank=True)

    class Meta:
        db_table = "incident_assignment"
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("assigned_at")),
                name="chk_inc_assignment_dates",
            ),
            models.UniqueConstraint(
                fields=("incident",),
                condition=Q(ended_at__isnull=True),
                name="uq_inc_current_assignment",
            ),
        ]
        indexes = [
            models.Index(
                fields=("assigned_to_staff", "-assigned_at"), name="idx_inc_assignment_staff"
            )
        ]


class IncidentStatusHistory(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="status_history")
    changed_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="incident_status_changes",
        null=True,
        blank=True,
    )
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20, choices=Incident.Status.choices)
    comment = models.CharField(max_length=300, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "incident_status_history"
        indexes = [
            models.Index(fields=("incident", "changed_at"), name="idx_incident_history")
        ]


class IncidentComment(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Público"
        INTERNAL = "INTERNAL", "Interno"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="comments")
    author_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="incident_comments",
        null=True,
        blank=True,
    )
    body = models.TextField()
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "incident_comment"
        indexes = [
            models.Index(fields=("incident", "created_at"), name="idx_inc_comment_time")
        ]


class RiskRule(models.Model):
    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=40)
    conditions = models.JSONField(default=dict, blank=True)
    weight = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "risk_rule"
        indexes = [
            models.Index(fields=("is_active", "entity_type"), name="idx_risk_active_type")
        ]


class IncidentAIAnalysis(models.Model):
    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        ACCEPTED = "ACCEPTED", "Aceptado"
        CORRECTED = "CORRECTED", "Corregido"
        REJECTED = "REJECTED", "Rechazado"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="ai_analyses")
    model_name = models.CharField(max_length=100)
    model_version = models.CharField(max_length=60)
    text_hash = models.CharField(max_length=64)
    suggested_category = models.ForeignKey(
        IncidentCategory,
        on_delete=models.SET_NULL,
        related_name="ai_suggestions",
        null=True,
        blank=True,
    )
    suggested_priority = models.ForeignKey(
        PriorityLevel,
        on_delete=models.SET_NULL,
        related_name="ai_suggestions",
        null=True,
        blank=True,
    )
    risk_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    confidence = models.DecimalField(max_digits=6, decimal_places=5, null=True, blank=True)
    suggested_staff_type = models.CharField(
        max_length=20, choices=STAFF_TYPE_CHOICES, null=True, blank=True
    )
    suggested_action = models.TextField(blank=True)
    raw_output = models.JSONField(default=dict, blank=True)
    reviewed_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="reviewed_ai_analyses",
        null=True,
        blank=True,
    )
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "incident_ai_analysis"
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__isnull=True)
                | Q(confidence__gte=0, confidence__lte=1),
                name="chk_ai_confidence",
            )
        ]
        indexes = [
            models.Index(fields=("incident", "-created_at"), name="idx_ai_incident_time")
        ]


class IncidentAIEntity(models.Model):
    analysis = models.ForeignKey(
        IncidentAIAnalysis, on_delete=models.CASCADE, related_name="entities"
    )
    entity_type = models.CharField(max_length=40)
    text_value = models.CharField(max_length=240)
    normalized_value = models.CharField(max_length=240, blank=True)
    confidence = models.DecimalField(max_digits=6, decimal_places=5, null=True, blank=True)
    applied_weight = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    risk_rule = models.ForeignKey(
        RiskRule, on_delete=models.SET_NULL, related_name="applied_entities", null=True, blank=True
    )

    class Meta:
        db_table = "incident_ai_entity"
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__isnull=True)
                | Q(confidence__gte=0, confidence__lte=1),
                name="chk_ai_entity_confidence",
            )
        ]
        indexes = [
            models.Index(fields=("analysis",), name="idx_ai_entity_analysis")
        ]