"""Permisos para CU18: Registrar incidencia."""

from rest_framework.permissions import BasePermission

from paquetes.paquete2_seguridad_accesos.cu13_turnos_seguridad.permissions import is_security_guard
from tenancy.context import TenantContext

# Permisos existentes del catálogo RBAC (accounts/rbac.py) que habilitan el registro.
REPORT_PERMISSION_CODES = ("report_incidents", "manage_incidents")
MANAGE_PERMISSION_CODE = "manage_incidents"


def tenant_role(request):
    """Rol del usuario dentro del condominio activo (membresía del tenant)."""
    membership = getattr(request, "tenant_membership", None) or TenantContext.get_current_membership()
    if not membership or not membership.is_active:
        return None
    return membership.role


def role_grants(role, *codes):
    return bool(
        role
        and role.is_active
        and role.permissions.filter(code__in=codes, is_active=True).exists()
    )


def has_full_unit_scope(request):
    """
    Administración y seguridad pueden vincular cualquier unidad del condominio;
    el resto (residentes) solo las unidades a las que está asociado vigentemente.
    """
    user = request.user
    if user.is_superuser:
        return True
    return role_grants(tenant_role(request), MANAGE_PERMISSION_CODE) or is_security_guard(user)


class CanReportIncidents(BasePermission):
    """
    Control de acceso para CU18:
    - Requiere usuario autenticado, activo y aprobado.
    - Requiere un condominio activo resuelto por el TenantContext.
    - El rol de la membresía en ese condominio debe tener 'report_incidents'
      (residente) o 'manage_incidents' (administrador). Seguridad accede solo
      si su rol recibió alguno de esos permisos mediante CU02.
    """

    message = "No tienes permiso para registrar incidencias en este condominio."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active:
            return False
        if user.is_superuser:
            return True
        if not user.is_approved:
            return False
        return role_grants(tenant_role(request), *REPORT_PERMISSION_CODES)
