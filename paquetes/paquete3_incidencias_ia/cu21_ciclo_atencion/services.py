from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from auditlog.services import record_audit_event
from condominiums.models import Staff
from incidents.models import Incident, IncidentAssignment
from maintenance.models import MaintenancePlan
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.permissions import (
    can_change_incident_status, is_admin_user,
)
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.services import (
    IncidentTrackingService, VALID_TRANSITIONS,
)


def allowed_transitions(incident, user):
    return [
        {"value": state, "label": Incident.Status(state).label}
        for state in VALID_TRANSITIONS.get(incident.status, ())
        if can_change_incident_status(user, incident, state)
        and (state not in ("ASSIGNED", "IN_PROGRESS") or incident.current_assignee_staff_id)
    ]


@transaction.atomic
def assign_incident(incident, user, staff_id, reason="", request=None):
    if not is_admin_user(user):
        raise PermissionDenied("Solo administración puede asignar responsables.")
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if incident.status in ("RESOLVED", "CLOSED", "CANCELLED"):
        raise ValidationError({"status": "Reabre la incidencia antes de asignarla."})
    staff = Staff.objects.filter(
        pk=staff_id, condominium_id=incident.condominium_id, status=Staff.Status.ACTIVE,
    ).first()
    if not staff:
        raise ValidationError({"staff_id": "El responsable debe estar activo en este condominio."})
    if incident.current_assignee_staff_id == staff.pk:
        raise ValidationError({"staff_id": "Esta persona ya es responsable."})
    now = timezone.now()
    IncidentAssignment.objects.filter(incident=incident, ended_at__isnull=True).update(ended_at=now)
    IncidentAssignment.objects.create(
        incident=incident, assigned_to_staff=staff, assigned_by_user=user, reason=reason,
        assigned_at=now,
    )
    incident.current_assignee_staff = staff
    incident.save(update_fields=("current_assignee_staff", "updated_at"))
    if incident.status in ("REPORTED", "REVIEWED"):
        incident, _ = IncidentTrackingService.change_status(incident, "ASSIGNED", user, reason, request)
    record_audit_event(
        action_code="INCIDENT_ASSIGN", resource_type="Incident", resource_id=incident.pk,
        actor_user=user, after_data={"staff_id": staff.pk}, request=request,
    )
    return incident


def attention_alerts(user):
    """Consulta acotada al tenant; no crea notificaciones como efecto de un GET."""
    now = timezone.now()
    result = [
        {"kind": "INCIDENT_OVERDUE", "code": row.public_code, "title": row.title,
         "due_at": row.due_at, "resource_id": row.pk}
        for row in IncidentTrackingService.list_incidents(user, {"sla_status": "overdue"})[:100]
    ]
    tenant_id = IncidentTrackingService.get_user_condominium_id(user)
    if is_admin_user(user) and tenant_id:
        plans = MaintenancePlan.objects.filter(
            is_active=True, asset__sector__condominium_id=tenant_id,
            next_due_at__lte=now + timedelta(days=7),
        ).order_by("next_due_at")[:100]
        result += [
            {"kind": "MAINTENANCE_OVERDUE" if row.next_due_at < now else "MAINTENANCE_UPCOMING",
             "code": str(row.pk), "title": row.name, "due_at": row.next_due_at,
             "resource_id": row.pk}
            for row in plans
        ]
    return result
