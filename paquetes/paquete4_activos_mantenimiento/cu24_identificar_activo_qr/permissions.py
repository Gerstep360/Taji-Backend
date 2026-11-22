from rest_framework.permissions import BasePermission

from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember

def can_view(user):
    """Lectura CU24 con el rol activo, sin importar el CRUD CU23."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = TenantContext.get_current_membership()
    if not membership or membership.user_id != user.pk or not membership.is_active:
        return False
    role = membership.role
    return bool(role and role.is_active and role.permissions.filter(
        is_active=True,
        code__in=("manage_maintenance", "manage_assets", "maintain_assets", "view_general_status"),
    ).exists())


class HasAssetsTenant(IsTenantMember):
    """Valida que el usuario tenga un condominio activo seleccionado."""

    message = "Necesitas una membresía activa y un condominio seleccionado para escanear activos."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        return bool(tenant and tenant.is_active and super().has_permission(request, view))


class CanScanAssets(BasePermission):
    """Valida que el usuario tenga permiso para consultar activos."""

    message = "No tienes permisos para escanear activos."

    def has_permission(self, request, view):
        return can_view(request.user)
