from dataclasses import dataclass
from collections.abc import Callable

from django.db.models import Exists, OuterRef, Q
from django.db.models.query import QuerySet

from auditlog.models import AuditEvent
from community.models import Agreement, Reservation
from incidents.models import Incident
from maintenance.models import WorkOrder
from reports.catalog import Column
from security.models import AccessEvent
from tenancy.models import TenantMembership

from .services import access_events, consistent_tenant


def incidents(tenant_id):
    return Incident.objects.filter(
        consistent_tenant(
            tenant_id,
            ("sector", "sector__condominium_id"),
            ("unit", "unit__sector__condominium_id"),
            ("asset", "asset__sector__condominium_id"),
            ("reporter_resident", "reporter_resident__condominium_id"),
            ("current_assignee_staff", "current_assignee_staff__condominium_id"),
        ),
        condominium_id=tenant_id,
    )


def work_orders(tenant_id):
    return WorkOrder.objects.filter(
        consistent_tenant(
            tenant_id,
            ("incident", "incident__condominium_id"),
            ("asset", "asset__sector__condominium_id"),
            ("maintenance_plan", "maintenance_plan__asset__sector__condominium_id"),
            ("supplier", "supplier__condominium_id"),
            ("current_assignee_staff", "current_assignee_staff__condominium_id"),
        ),
        condominium_id=tenant_id,
    )


def reservations(tenant_id):
    return Reservation.objects.filter(
        consistent_tenant(tenant_id, ("common_area__sector", "common_area__sector__condominium_id")),
        common_area__condominium_id=tenant_id,
        resident__condominium_id=tenant_id,
    )


def agreements(tenant_id):
    responsible_membership = TenantMembership.objects.filter(
        condominium_id=tenant_id, user_id=OuterRef("responsible_user_id"), is_active=True,
    )
    return Agreement.objects.filter(assembly__condominium_id=tenant_id).filter(
        Q(responsible_user__isnull=True) | Q(Exists(responsible_membership))
    )


def audit_events(tenant_id):
    return AuditEvent.objects.filter(condominium_id=tenant_id)


@dataclass(frozen=True)
class ReportSource:
    label: str
    description: str
    date_field: str
    permissions: tuple
    scoped: Callable[[int], QuerySet]
    columns: tuple

    def public(self, key, formats):
        return {
            "key": key, "label": self.label, "description": self.description,
            "date_field": self.date_field, "permissions_any": self.permissions,
            "columns": [column.public() for column in self.columns],
            "default_columns": [column.key for column in self.columns],
            "sortable": [column.key for column in self.columns],
            "default_ordering": [{"field": self.date_field, "direction": "desc"}],
            "formats": formats,
        }


def field(key, label, path=None, *, kind="text", choices=()):
    return Column(key, label, path or key, kind, tuple(choices))


def date_field(key, label):
    return field(key, label, kind="datetime")


def choice(key, label, choices):
    return field(key, label, kind="choice", choices=choices)


SOURCES = {
    "access_events": ReportSource(
        "Accesos", "Eventos según la fecha en que ocurrieron.", "occurred_at",
        ("register_entry_exit",), access_events, (
            date_field("occurred_at", "Fecha del acceso"),
            choice("event_type", "Tipo", AccessEvent.Type.choices),
            choice("validation_result", "Resultado", AccessEvent.Result.choices),
            choice("validation_method", "Método", AccessEvent.Method.choices),
        ),
    ),
    "incidents": ReportSource(
        "Incidencias", "Incidencias creadas durante el período y su estado actual.", "created_at",
        ("manage_incidents",), incidents, (
            date_field("created_at", "Fecha de creación"),
            field("public_code", "Código"), field("title", "Título"),
            choice("status", "Estado", Incident.Status.choices),
            field("priority", "Prioridad", "priority__name"),
            field("category", "Categoría", "category__name"),
        ),
    ),
    "work_orders": ReportSource(
        "Mantenimiento", "Órdenes creadas durante el período y su estado actual.", "created_at",
        ("manage_maintenance",), work_orders, (
            date_field("created_at", "Fecha de creación"),
            field("public_code", "Código"), field("title", "Título"),
            choice("status", "Estado", WorkOrder.Status.choices),
            choice("work_type", "Tipo", WorkOrder.Type.choices),
            field("asset", "Activo", "asset__name"),
            date_field("scheduled_for", "Fecha programada"),
        ),
    ),
    "reservations": ReportSource(
        "Reservas", "Reservas que comienzan durante el período.", "start_at",
        ("manage_reservations",), reservations, (
            date_field("start_at", "Inicio"), date_field("end_at", "Fin"),
            choice("status", "Estado", Reservation.Status.choices),
            field("area", "Área común", "common_area__name"),
        ),
    ),
    "agreements": ReportSource(
        "Acuerdos", "Acuerdos creados en el período. La fecha límite se filtra por separado; el estado es el registrado.",
        "created_at", ("track_assembly_decisions", "manage_settings"), agreements, (
            date_field("created_at", "Fecha de creación"), date_field("due_at", "Fecha límite"),
            field("title", "Acuerdo"), field("assembly", "Asamblea", "assembly__title"),
            choice("status", "Estado", Agreement.Status.choices),
        ),
    ),
    "audit_events": ReportSource(
        "Auditoría", "Acciones atribuibles al condominio por fecha del evento.", "occurred_at",
        ("manage_roles", "view_audit_log"), audit_events, (
            date_field("occurred_at", "Fecha del evento"),
            field("action_code", "Acción"), field("resource_type", "Tipo de recurso"),
        ),
    ),
}
