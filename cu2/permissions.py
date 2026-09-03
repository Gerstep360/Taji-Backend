from rest_framework.permissions import BasePermission


class CanManageRoles(BasePermission):
    """Restringe el CU2 (Gestionar Roles y Permisos) al rol Administrador. (RN1)"""

    message = "No tienes permiso para gestionar roles y permisos del sistema."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_system_permission("manage_roles"))
