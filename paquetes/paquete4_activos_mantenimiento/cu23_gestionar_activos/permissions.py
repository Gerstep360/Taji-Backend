from rest_framework.permissions import BasePermission

from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember

# RN4 (CU4): la Directiva es de solo lectura. "manage_assets" gestiona el
# catálogo (alta/edición/baja); "view_general_status" es el permiso de
# solo-lectura que ya tiene asignado el rol Directiva.
MANAGEMENT_PERMISSIONS = {"manage_assets"}
VIEW_ONLY_PERMISSIONS = {"view_general_status", "maintain_assets", "manage_maintenance"}


def _role_permission_codes(user):
    """Códigos de permiso del rol del usuario en el tenant activo, o None si es superusuario."""
    if user.is_superuser:
        return None
    membership = TenantContext.get_current_membership()
    role = membership.role if membership and membership.user_id == user.pk and membership.is_active else None
    if not role or not role.is_active:
        return set()
    return set(role.permissions.filter(is_active=True).values_list("code", flat=True))


def can_manage(user):
    if not user or not user.is_authenticated:
        return False
    codes = _role_permission_codes(user)
    return codes is None or bool(codes & MANAGEMENT_PERMISSIONS)


def can_view(user):
    if not user or not user.is_authenticated:
        return False
    if can_manage(user):
        return True
    codes = _role_permission_codes(user)
    return codes is None or bool(codes & VIEW_ONLY_PERMISSIONS)


class HasAssetsTenant(IsTenantMember):
    message = "Necesitas una membresía activa y un condominio seleccionado para acceder a activos."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        return bool(tenant and tenant.is_active and super().has_permission(request, view))


class CanAccessAssets(BasePermission):
    message = "No tienes permisos para acceder al inventario de activos."

    def has_permission(self, request, view):
        return can_view(request.user)
