from dataclasses import dataclass

from django.db.models import Q, Value
from django.db.models.functions import Concat

from condominiums.models import Resident, Staff, Unit
from security.models import SecurityShift, ShiftHandover, ShiftLogEntry


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    path: str
    kind: str = "text"
    choices: tuple = ()

    @property
    def operators(self):
        if self.kind in ("date", "datetime", "number"):
            return ("eq", "gte", "lte", "is_empty", "not_empty")
        if self.kind == "choice":
            return ("eq", "ne")
        return ("contains", "eq", "ne", "is_empty", "not_empty")

    def public(self):
        return {"key": self.key, "label": self.label, "type": self.kind,
                "operators": self.operators,
                "choices": [{"value": value, "label": label} for value, label in self.choices]}


@dataclass(frozen=True)
class Source:
    label: str
    columns: tuple
    defaults: tuple
    ordering: str


def c(key, label, path=None, kind="text", choices=()):
    return Column(key, label, path or key, kind, tuple(choices))


IDENTITY = (
    c("name", "Nombre completo", "report_name"),
    c("document", "Documento", "person__document_number"),
    c("phone", "Teléfono", "person__phone"),
    c("email", "Correo", "person__contact_email"),
)
GUARD = c("guard", "Guardia", "report_guard")
SOURCES = {
    "staff": Source("Personal del condominio", (
        c("id", "ID", kind="number"), c("code", "Código", "employee_code"), *IDENTITY,
        c("area", "Área", "staff_type", "choice", Staff.Type.choices),
        c("status", "Estado", kind="choice", choices=Staff.Status.choices),
        c("hire_date", "Inicio de trabajo", kind="date"), c("notes", "Notas internas"),
    ), ("code", "name", "area", "status", "phone"), "name"),
    "residents": Source("Residentes y copropietarios", (
        c("id", "ID", kind="number"), *IDENTITY,
        c("status", "Estado", kind="choice", choices=Resident.Status.choices),
        c("registered_at", "Fecha de registro", kind="datetime"), c("notes", "Notas"),
    ), ("name", "document", "phone", "status"), "name"),
    "units": Source("Unidades del condominio", (
        c("id", "ID", kind="number"), c("code", "Código"), c("sector", "Sector", "sector__name"),
        c("type", "Tipo", "unit_type", "choice", Unit.Type.choices), c("floor", "Piso", "floor_label"),
        c("status", "Estado", kind="choice", choices=Unit.Status.choices), c("description", "Descripción"),
    ), ("code", "sector", "type", "status"), "code"),
    "shifts": Source("Turnos de seguridad", (
        c("id", "Turno", kind="number"), GUARD,
        c("guard_code", "Código del guardia", "guard_staff__employee_code"),
        c("scheduled_start", "Inicio planificado", kind="datetime"),
        c("scheduled_end", "Fin planificado", kind="datetime"),
        c("opened_at", "Apertura real", kind="datetime"),
        c("closed_at", "Cierre real", kind="datetime"),
        c("status", "Estado", kind="choice", choices=SecurityShift.Status.choices),
        c("observation", "Observación"), c("opening_notes", "Nota de apertura"),
        c("closing_notes", "Nota de cierre"),
    ), ("id", "guard", "scheduled_start", "scheduled_end", "status"), "-scheduled_start"),
    "logs": Source("Novedades, incidentes y alertas", (
        c("id", "ID", kind="number"), c("shift", "Turno", "shift_id", "number"), GUARD,
        c("title", "Título"), c("description", "Descripción"),
        c("type", "Tipo", "entry_type", "choice", ShiftLogEntry.Type.choices),
        c("severity", "Prioridad", kind="choice", choices=ShiftLogEntry.Severity.choices),
        c("sector", "Sector", "sector__name"), c("occurred_at", "Fecha del hecho", kind="datetime"),
    ), ("occurred_at", "guard", "type", "severity", "title", "description"), "-occurred_at"),
    "handovers": Source("Entrega y recepción de turno", (
        c("id", "ID", kind="number"), c("outgoing", "Turno saliente", "outgoing_shift_id", "number"),
        c("incoming", "Turno de relevo", "incoming_shift_id", "number"),
        c("outgoing_guard", "Guardia saliente", "report_outgoing"),
        c("incoming_guard", "Guardia entrante", "report_incoming"),
        c("summary", "Resumen y pendientes"),
        c("status", "Estado", kind="choice", choices=ShiftHandover.Status.choices),
        c("delivered_at", "Fecha de entrega", kind="datetime"),
        c("received_at", "Fecha de recepción", kind="datetime"),
    ), ("outgoing_guard", "incoming_guard", "summary", "status", "delivered_at", "received_at"), "-delivered_at"),
}


def full_name(prefix):
    return Concat(f"{prefix}__first_name", Value(" "), f"{prefix}__last_name")


def scoped_queryset(source, tenant_id):
    # Filtros explícitos incluso para modelos con TenantAwareManager: nunca modo global.
    if source == "staff":
        return Staff.objects.filter(condominium_id=tenant_id).annotate(report_name=full_name("person"))
    if source == "residents":
        return Resident.objects.filter(condominium_id=tenant_id).annotate(report_name=full_name("person"))
    if source == "units":
        return Unit.objects.filter(sector__condominium_id=tenant_id)
    shifts = SecurityShift.objects.filter(condominium_id=tenant_id, guard_staff__condominium_id=tenant_id)
    if source == "shifts":
        return shifts.annotate(report_guard=full_name("guard_staff__person"))
    if source == "logs":
        return ShiftLogEntry.objects.filter(shift__in=shifts).filter(
            Q(sector__isnull=True) | Q(sector__condominium_id=tenant_id)
        ).annotate(report_guard=full_name("shift__guard_staff__person"))
    return ShiftHandover.objects.filter(outgoing_shift__in=shifts, incoming_shift__in=shifts).annotate(
        report_outgoing=full_name("outgoing_shift__guard_staff__person"),
        report_incoming=full_name("incoming_shift__guard_staff__person"),
    )
