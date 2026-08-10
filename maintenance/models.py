import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class AssetType(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "asset_type"

    def __str__(self):
        return self.name


class Asset(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        OUT_OF_SERVICE = "OUT_OF_SERVICE", "Fuera de servicio"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        RETIRED = "RETIRED", "Retirado"

    asset_type = models.ForeignKey(AssetType, on_delete=models.PROTECT, related_name="assets")
    sector = models.ForeignKey(
        "condominiums.Sector",
        on_delete=models.SET_NULL,
        related_name="assets",
        null=True,
        blank=True,
    )
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    installation_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    qr_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    extra_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asset"
        indexes = [
            models.Index(fields=("asset_type", "status"), name="idx_asset_type_status"),
            models.Index(fields=("sector",), name="idx_asset_sector"),
        ]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Supplier(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        INACTIVE = "INACTIVE", "Inactivo"

    name = models.CharField(max_length=160)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=25, blank=True)
    email = models.EmailField(blank=True)
    specialty = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "supplier"

    def __str__(self):
        return self.name


class MaintenancePlan(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="maintenance_plans")
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    frequency_days = models.IntegerField()
    last_completed_at = models.DateTimeField(null=True, blank=True)
    next_due_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "maintenance_plan"
        constraints = [
            models.CheckConstraint(
                condition=Q(frequency_days__gt=0), name="chk_maintenance_frequency"
            )
        ]
        indexes = [
            models.Index(
                fields=("next_due_at",),
                condition=Q(is_active=True),
                name="idx_maintenance_plan_due",
            )
        ]


class WorkOrder(models.Model):
    class Type(models.TextChoices):
        PREVENTIVE = "PREVENTIVE", "Preventivo"
        CORRECTIVE = "CORRECTIVE", "Correctivo"
        INSPECTION = "INSPECTION", "Inspección"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        ASSIGNED = "ASSIGNED", "Asignada"
        IN_PROGRESS = "IN_PROGRESS", "En progreso"
        PAUSED = "PAUSED", "Pausada"
        COMPLETED = "COMPLETED", "Completada"
        CANCELLED = "CANCELLED", "Cancelada"

    public_code = models.CharField(max_length=30, unique=True)
    incident = models.ForeignKey(
        "incidents.Incident",
        on_delete=models.SET_NULL,
        related_name="work_orders",
        null=True,
        blank=True,
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.SET_NULL, related_name="work_orders", null=True, blank=True
    )
    maintenance_plan = models.ForeignKey(
        MaintenancePlan,
        on_delete=models.SET_NULL,
        related_name="work_orders",
        null=True,
        blank=True,
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, related_name="work_orders", null=True, blank=True
    )
    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_work_orders",
        null=True,
        blank=True,
    )
    current_assignee_staff = models.ForeignKey(
        "condominiums.Staff",
        on_delete=models.SET_NULL,
        related_name="assigned_work_orders",
        null=True,
        blank=True,
    )
    work_type = models.CharField(max_length=20, choices=Type.choices)
    priority = models.ForeignKey(
        "incidents.PriorityLevel",
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "work_order"
        constraints = [
            models.CheckConstraint(
                condition=(Q(estimated_cost__isnull=True) | Q(estimated_cost__gte=0))
                & (Q(actual_cost__isnull=True) | Q(actual_cost__gte=0)),
                name="chk_work_order_costs",
            )
        ]
        indexes = [
            models.Index(fields=("status", "scheduled_for"), name="idx_work_status_schedule"),
            models.Index(
                fields=("current_assignee_staff", "status"), name="idx_work_assignee_status"
            ),
            models.Index(fields=("asset", "-created_at"), name="idx_work_asset_time"),
        ]


class WorkOrderAssignment(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="assignments")
    assigned_to_staff = models.ForeignKey(
        "condominiums.Staff", on_delete=models.PROTECT, related_name="work_order_assignments"
    )
    assigned_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="assigned_work_order_actions",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=240, blank=True)

    class Meta:
        db_table = "work_order_assignment"
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("assigned_at")),
                name="chk_work_assignment_dates",
            ),
            models.UniqueConstraint(
                fields=("work_order",),
                condition=Q(ended_at__isnull=True),
                name="uq_work_current_assignment",
            ),
        ]


class WorkOrderAttachment(models.Model):
    class Type(models.TextChoices):
        IMAGE = "IMAGE", "Imagen"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Documento"

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="work_order_uploads",
        null=True,
        blank=True,
    )
    file_path = models.CharField(max_length=500)
    file_type = models.CharField(max_length=20, choices=Type.choices, default=Type.IMAGE)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "work_order_attachment"


class WorkOrderCostItem(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="cost_items")
    description = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "work_order_cost_item"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="chk_work_cost_qty"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="chk_work_cost_unit"),
        ]
        indexes = [
            models.Index(fields=("work_order",), name="idx_work_cost_order")
        ]

    @property
    def total(self):
        return self.quantity * self.unit_cost