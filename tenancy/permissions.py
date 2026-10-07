"""Permisos y autorización por tenant (Sección 9, 10 y 24 de multitenant_saas_optimizado.md)."""

from rest_framework.permissions import BasePermission
from tenancy.context import TenantContext


class IsTenantMember(BasePermission):
    """
    Exige que el actor autenticado sea miembro activo del tenant en el que opera.
    Los superusuarios de plataforma están exentos.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        if getattr(request, "tenant_membership", None):
            return request.tenant_membership.is_active

        # Si el contexto tiene un tenant activo, comprobar membresía
        current_membership = TenantContext.get_current_membership()
        if current_membership and current_membership.is_active:
            return True

        return False


class IsTenantAdmin(BasePermission):
    """
    Exige que el actor tenga rol de Administrador dentro del tenant activo,
    o sea superusuario de la plataforma.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        membership = getattr(request, "tenant_membership", None) or TenantContext.get_current_membership()
        if not membership or not membership.is_active:
            return False

        if not membership.role:
            return False

        role_slug = (membership.role.slug or "").lower()
        return "admin" in role_slug or role_slug in ("administrador", "manager", "superadmin")


class IsPlatformAdmin(BasePermission):
    """
    Exige que el usuario sea administrador global de la plataforma SaaS (Superuser o Staff).
    Sección 35: Plataform Admin vs Tenant Admin.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff))
