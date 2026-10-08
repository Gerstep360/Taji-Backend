"""Permisos RBAC para CU13: Gestionar turnos del personal de seguridad."""

from rest_framework.permissions import BasePermission
from condominiums.models import Staff
from tenancy.context import TenantContext


def security_role(user):
    membership = TenantContext.get_current_membership()
    return membership.role if membership else None


def role_has_permission(role, *codes):
    return bool(role and role.permissions.filter(code__in=codes, is_active=True).exists())


def is_admin_or_management(user):
    """Retorna True si el usuario tiene rol administrativo o directiva."""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    role = security_role(user)
    if role_has_permission(role, "manage_security_shifts", "manage_staff"):
        return True
    if role and role.slug in ("admin", "administrador", "directiva", "directorio"):
        return True
    return False


def is_security_guard(user):
    """Retorna True si el usuario pertenece al personal de seguridad."""
    if not (user and user.is_authenticated):
        return False
    role = security_role(user)
    if role_has_permission(role, "operate_security_shifts", "view_security_shifts"):
        return True
    if role and role.slug in ("security", "guardia", "seguridad"):
        return True
    person = getattr(user, "person", None)
    if person and role and TenantContext.get_current_tenant_id():
        return Staff.objects.filter(person=person, staff_type=Staff.Type.SECURITY, status=Staff.Status.ACTIVE).exists()
    return False


class CanManageSecurityShifts(BasePermission):
    """
    Control de acceso RBAC para CU13:
    - Administrador / Directiva: Control total o lectura global según permisos.
    - Seguridad: Puede listar sus propios turnos, consultar turno actual/próximos e iniciar/cerrar su turno.
    - Otros roles (Residente, Limpieza, Mantenimiento): Sin acceso.
    """

    message = "No tienes permisos para acceder a la gestión de turnos de seguridad."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if is_admin_or_management(user):
            return True

        if is_security_guard(user):
            # Seguridad puede consultar sus turnos, ver actual/próximos, e iniciar/cerrar el propio
            if view.action in ("list", "retrieve", "actual", "proximos", "historial", "iniciar", "cerrar", "options"):
                return True
            return False

        return False
