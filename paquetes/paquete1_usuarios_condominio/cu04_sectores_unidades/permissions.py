from rest_framework.permissions import BasePermission


class CanManageUnits(BasePermission):
    """Limita CU04 a usuarios con el permiso funcional de unidades."""

    message = "No tienes permiso para gestionar sectores y unidades del condominio."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_system_permission("manage_units"))
