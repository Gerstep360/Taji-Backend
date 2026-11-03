from rest_framework.permissions import BasePermission

from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember
from paquetes.paquete4_activos_mantenimiento.cu23_gestionar_activos.permissions import (
    can_view,
)


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
