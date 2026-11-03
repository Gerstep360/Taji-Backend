from rest_framework.permissions import BasePermission

from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember


MANAGEMENT_PERMISSIONS = {"manage_maintenance"}
WORKER_PERMISSIONS = {
    "view_assigned_work_orders",
    "update_work_order_status",
    "attach_work_evidence",
    "maintain_assets",
    "access_assigned_external_orders",
}


def role_permissions(user):
    membership = TenantContext.get_current_membership()
    if user.is_superuser:
        return MANAGEMENT_PERMISSIONS | WORKER_PERMISSIONS
    role = membership.role if membership and membership.user_id == user.pk and membership.is_active else None
    if not role or not role.is_active:
        return set()
    return set(role.permissions.filter(is_active=True).values_list("code", flat=True))


def can_manage(user):
    return bool(user.is_superuser or role_permissions(user) & MANAGEMENT_PERMISSIONS)


def worker_permissions(user):
    return role_permissions(user) & WORKER_PERMISSIONS


class HasMaintenanceTenant(IsTenantMember):
    message = "Necesitas una membresía activa y un condominio seleccionado para acceder a mantenimiento."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        return bool(tenant and tenant.is_active and super().has_permission(request, view))


class CanAccessMaintenance(BasePermission):
    message = "No tienes permisos para acceder a la gestión de mantenimiento."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if can_manage(request.user):
            return True
        return bool(worker_permissions(request.user))
