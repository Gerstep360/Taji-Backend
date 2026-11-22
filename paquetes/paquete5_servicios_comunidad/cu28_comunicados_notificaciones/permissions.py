from rest_framework.permissions import BasePermission
from tenancy.context import TenantContext


def has_announcement_permission(user, permission_code="manage_announcements"):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    member = TenantContext.get_current_membership()
    if not member or member.user_id != user.pk or not member.is_active:
        return False
    if not member.role or not member.role.is_active:
        return False
    return member.role.permissions.filter(code=permission_code, is_active=True).exists()


class CanManageAnnouncements(BasePermission):
    """Permite el acceso a administradores o miembros con el permiso manage_announcements."""

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active:
            return False
        return has_announcement_permission(request.user, "manage_announcements")


class CanViewCommunityAnnouncements(BasePermission):
    """Permite el acceso a miembros activos del condominio autenticado."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        tenant = TenantContext.get_current_tenant()
        member = TenantContext.get_current_membership()
        if not tenant or not tenant.is_active or not member:
            return False
        return bool(member.user_id == request.user.pk and member.is_active)
