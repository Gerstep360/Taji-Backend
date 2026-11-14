"""Permisos para CU19: Consultar seguimiento e historial de incidencia."""

from rest_framework.permissions import BasePermission
from condominiums.models import Staff, Resident
from incidents.models import Incident


def is_admin_user(user) -> bool:
    """Verifica si el usuario es administrador global o del condominio."""
    if not (user and user.is_authenticated):
        return False
    return bool(user.is_superuser or user.has_system_permission("manage_incidents"))


def is_directiva_user(user) -> bool:
    """Verifica si el usuario pertenece a la directiva del condominio."""
    if not (user and user.is_authenticated):
        return False
    return bool(user.has_system_permission("view_important_incidents"))


def is_staff_user(user) -> bool:
    """Verifica si el usuario es personal operativo activo (seguridad, mantenimiento, limpieza)."""
    if not (user and user.is_authenticated):
        return False
    person = getattr(user, "person", None)
    if not person:
        return False
    return Staff.objects.filter(person=person, status=Staff.Status.ACTIVE).exists()


def is_resident_user(user) -> bool:
    """Verifica si el usuario es residente o copropietario."""
    if not (user and user.is_authenticated):
        return False
    if user.has_system_permission("report_incidents"):
        return True
    person = getattr(user, "person", None)
    if not person:
        return False
    return Resident.objects.filter(person=person, status=Resident.Status.ACTIVE).exists()


def can_view_internal_comments(user) -> bool:
    """Los comentarios internos solo pueden ser consultados por staff, directiva y admin.
    
    Los residentes NO tienen acceso a comentarios internos bajo ninguna circunstancia.
    """
    return bool(is_admin_user(user) or is_directiva_user(user) or is_staff_user(user))


def can_post_internal_comments(user) -> bool:
    """Solo personal y administradores pueden publicar comentarios internos."""
    return bool(is_admin_user(user) or is_staff_user(user))


def can_change_incident_status(user, incident, new_status) -> bool:
    """Valida si el actor puede aplicar una transición de estado a la incidencia."""
    if is_admin_user(user):
        return True

    person = getattr(user, "person", None)

    # Personal responsable asignado
    if person and incident.current_assignee_staff and incident.current_assignee_staff.person_id == person.id and incident.current_assignee_staff.status == Staff.Status.ACTIVE:
        if new_status in (Incident.Status.IN_PROGRESS, Incident.Status.RESOLVED):
            return True

    # Residente que reportó la incidencia puede cancelarla si aún no se inició
    is_reporter = (
        incident.reporter_user_id == user.id
        or (person and incident.reporter_resident and incident.reporter_resident.person_id == person.id)
    )
    if is_reporter and new_status == Incident.Status.CANCELLED:
        if incident.status in (Incident.Status.REPORTED, Incident.Status.REVIEWED):
            return True

    return False


def can_modify_target_date(user) -> bool:
    """Solo el administrador puede definir o reprogramar la fecha objetivo (due_at)."""
    return is_admin_user(user)


class CanAccessIncidentTracking(BasePermission):
    """Permiso para el acceso al seguimiento e historial de incidencias (CU19)."""

    message = "No tienes permiso para acceder al seguimiento de incidencias."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if not getattr(user, "is_approved", True):
            return False
        return bool(
            is_admin_user(user)
            or is_directiva_user(user)
            or is_staff_user(user)
            or is_resident_user(user)
        )

