from rest_framework.permissions import BasePermission


class CanManageStaff(BasePermission):
    """Limita CU07 a usuarios con el permiso funcional de personal."""

    message = "No tienes permiso para gestionar al personal del condominio."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_system_permission("manage_staff"))


class CanManageResidents(BasePermission):
    """Limita CU05 a usuarios con el permiso funcional de residentes."""

    message = "No tienes permiso para gestionar a los residentes del condominio."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_system_permission("manage_residents"))
