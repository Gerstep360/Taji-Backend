from django.db import models
from django.db.models import Q
from django.utils import timezone


class CommonArea(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Disponible"
        UNAVAILABLE = "UNAVAILABLE", "No disponible"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        INACTIVE = "INACTIVE", "Inactiva"

    sector = models.ForeignKey(
        "condominiums.Sector",
        on_delete=models.SET_NULL,
        related_name="common_areas",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    capacity = models.IntegerField(null=True, blank=True)
    requires_approval = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "common_area"
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gt=0),
                name="chk_common_area_capacity",
            )
        ]

    def __str__(self):
        return self.name


class CommonAreaSchedule(models.Model):
    common_area = models.ForeignKey(CommonArea, on_delete=models.CASCADE, related_name="schedules")
    weekday = models.SmallIntegerField()
    opens_at = models.TimeField()
    closes_at = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "common_area_schedule"
        constraints = [
            models.CheckConstraint(
                condition=Q(weekday__gte=0, weekday__lte=6), name="chk_area_weekday"
            ),
            models.CheckConstraint(
                condition=Q(closes_at__gt=models.F("opens_at")), name="chk_area_schedule_time"
            ),
            models.UniqueConstraint(
                fields=("common_area", "weekday", "opens_at", "closes_at"),
                name="uq_area_schedule",
            ),
        ]


class CommonAreaBlock(models.Model):
    common_area = models.ForeignKey(CommonArea, on_delete=models.CASCADE, related_name="blocks")
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        on_delete=models.SET_NULL,
        related_name="common_area_blocks",
        null=True,
        blank=True,
    )
    blocked_from = models.DateTimeField()
    blocked_until = models.DateTimeField()
    reason = models.CharField(max_length=240)
    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_area_blocks",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "common_area_block"
        constraints = [
            models.CheckConstraint(
                condition=Q(blocked_until__gt=models.F("blocked_from")),
                name="chk_area_block_dates",
            )
        ]
        indexes = [
            models.Index(
                fields=("common_area", "blocked_from", "blocked_until"),
                name="idx_area_block_window",
            )
        ]


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        APPROVED = "APPROVED", "Aprobada"
        REJECTED = "REJECTED", "Rechazada"
        CANCELLED = "CANCELLED", "Cancelada"
        COMPLETED = "COMPLETED", "Completada"

    common_area = models.ForeignKey(
        CommonArea, on_delete=models.PROTECT, related_name="reservations"
    )
    resident = models.ForeignKey(
        "condominiums.Resident", on_delete=models.PROTECT, related_name="reservations"
    )
    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_reservations",
        null=True,
        blank=True,
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    purpose = models.CharField(max_length=240, blank=True)
    approved_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="approved_reservations",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reservation"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=models.F("start_at")), name="chk_reservation_dates"
            )
        ]
        indexes = [
            models.Index(
                fields=("resident", "-start_at"), name="idx_resident_reservation"
            ),
            models.Index(fields=("common_area", "start_at"), name="idx_area_reservation"),
        ]


class Assembly(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programada"
        IN_PROGRESS = "IN_PROGRESS", "En progreso"
        FINISHED = "FINISHED", "Finalizada"
        CANCELLED = "CANCELLED", "Cancelada"

    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_assemblies",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    scheduled_at = models.DateTimeField()
    location = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    minutes_text = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assembly"
        indexes = [
            models.Index(fields=("-scheduled_at",), name="idx_assembly_schedule")
        ]


class Agreement(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        IN_PROGRESS = "IN_PROGRESS", "En progreso"
        COMPLETED = "COMPLETED", "Completado"
        OVERDUE = "OVERDUE", "Vencido"
        CANCELLED = "CANCELLED", "Cancelado"

    assembly = models.ForeignKey(Assembly, on_delete=models.CASCADE, related_name="agreements")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    responsible_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="responsible_agreements",
        null=True,
        blank=True,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    estimated_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agreement"
        constraints = [
            models.CheckConstraint(
                condition=(Q(estimated_budget__isnull=True) | Q(estimated_budget__gte=0))
                & (Q(actual_cost__isnull=True) | Q(actual_cost__gte=0)),
                name="chk_agreement_costs",
            )
        ]
        indexes = [
            models.Index(fields=("status", "due_at"), name="idx_agreement_status_due")
        ]


class AgreementAttachment(models.Model):
    agreement = models.ForeignKey(Agreement, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="agreement_uploads",
        null=True,
        blank=True,
    )
    file_path = models.CharField(max_length=500)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "agreement_attachment"