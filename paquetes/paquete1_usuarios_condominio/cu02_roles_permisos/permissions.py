"""Permisos para CU02: Gestionar usuarios, roles y permisos."""

from rest_framework.permissions import BasePermission


class CanManageRoles(BasePermission):
    """Restringe la gestión de roles y permisos al rol Administrador. (CU02 - RN1)"""

    message = "No tienes permiso para gestionar roles y permisos del sistema."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_system_permission("manage_roles"))
