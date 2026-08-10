from datetime import date

from django.db import models
from django.db.models import Q
from django.utils import timezone as dj_timezone


class Condominium(models.Model):
    name = models.CharField(max_length=150)
    legal_name = models.CharField(max_length=180, blank=True)
    address = models.CharField(max_length=250, blank=True)
    phone = models.CharField(max_length=25, blank=True)
    email = models.EmailField(blank=True)
    timezone = models.CharField(max_length=50, default="America/La_Paz")
    logo = models.CharField(max_length=500, blank=True)
    rules_summary = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "condominium"

    def __str__(self):
        return self.name


class Sector(models.Model):
    class Type(models.TextChoices):
        SECTOR = "SECTOR", "Sector"
        BLOCK = "BLOCK", "Bloque"
        TOWER = "TOWER", "Torre"
        FLOOR = "FLOOR", "Piso"
        ZONE = "ZONE", "Zona"
        OTHER = "OTHER", "Otro"

    condominium = models.ForeignKey(Condominium, on_delete=models.CASCADE, related_name="sectors")
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="children", null=True, blank=True
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    sector_type = models.CharField(max_length=20, choices=Type.choices, default=Type.SECTOR)
    description = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        db_table = "sector"
        constraints = [
            models.UniqueConstraint(fields=("condominium", "code"), name="uq_sector_code")
        ]
        indexes = [models.Index(fields=("parent",), name="idx_sector_parent")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Unit(models.Model):
    class Type(models.TextChoices):
        HOUSE = "HOUSE", "Casa"
        APARTMENT = "APARTMENT", "Departamento"
        OFFICE = "OFFICE", "Oficina"
        STORE = "STORE", "Local"
        OTHER = "OTHER", "Otro"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activa"
        INACTIVE = "INACTIVE", "Inactiva"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"

    sector = models.ForeignKey(
        Sector, on_delete=models.PROTECT, related_name="units", null=True, blank=True
    )
    code = models.CharField(max_length=40, unique=True)
    unit_type = models.CharField(max_length=20, choices=Type.choices, default=Type.APARTMENT)
    floor_label = models.CharField(max_length=20, blank=True)
    description = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "unit"
        indexes = [
            models.Index(fields=("sector",), name="idx_unit_sector"),
            models.Index(fields=("status",), name="idx_unit_status"),
        ]

    def __str__(self):
        return self.code


class Resident(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        INACTIVE = "INACTIVE", "Inactivo"
        BLOCKED = "BLOCKED", "Bloqueado"

    person = models.OneToOneField("accounts.Person", on_delete=models.PROTECT, related_name="resident")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    registered_at = models.DateTimeField(default=dj_timezone.now)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "resident"

    def __str__(self):
        return str(self.person)


class ResidentUnit(models.Model):
    class Relation(models.TextChoices):
        OWNER = "OWNER", "Propietario"
        TENANT = "TENANT", "Inquilino"
        FAMILY = "FAMILY", "Familiar"
        AUTHORIZED = "AUTHORIZED", "Autorizado"
        OTHER = "OTHER", "Otro"

    resident = models.ForeignKey(Resident, on_delete=models.CASCADE, related_name="unit_links")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="resident_links")
    relation_type = models.CharField(max_length=20, choices=Relation.choices)
    is_primary = models.BooleanField(default=False)
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        db_table = "resident_unit"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                name="chk_resident_unit_dates",
            ),
            models.UniqueConstraint(
                fields=("resident", "unit"),
                condition=Q(end_date__isnull=True),
                name="uq_resident_unit_active",
            ),
            models.UniqueConstraint(
                fields=("resident",),
                condition=Q(is_primary=True, end_date__isnull=True),
                name="uq_resident_primary_active",
            ),
        ]
        indexes = [models.Index(fields=("unit",), name="idx_resident_unit_unit")]


class Staff(models.Model):
    class Type(models.TextChoices):
        ADMINISTRATION = "ADMINISTRATION", "Administración"
        SECURITY = "SECURITY", "Seguridad"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        CLEANING = "CLEANING", "Limpieza"
        OTHER = "OTHER", "Otro"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        INACTIVE = "INACTIVE", "Inactivo"
        SUSPENDED = "SUSPENDED", "Suspendido"

    person = models.OneToOneField("accounts.Person", on_delete=models.PROTECT, related_name="staff")
    employee_code = models.CharField(max_length=40, unique=True, null=True, blank=True)
    staff_type = models.CharField(max_length=20, choices=Type.choices)
    hire_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "staff"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True)
                | Q(hire_date__isnull=True)
                | Q(end_date__gte=models.F("hire_date")),
                name="chk_staff_dates",
            )
        ]
        indexes = [
            models.Index(fields=("staff_type", "status"), name="idx_staff_type_status")
        ]

    def __str__(self):
        return str(self.person)