from rest_framework.permissions import BasePermission, SAFE_METHODS


class CanManageUnits(BasePermission):
    """Limita la modificación de sectores y unidades a usuarios con el permiso 'manage_units'.

    Permite lectura (GET, HEAD, OPTIONS) a cualquier usuario autenticado del sistema para
    que los formularios de visitas, residentes y accesos puedan seleccionar unidades y sectores.
    """

    message = "No tienes permiso para gestionar sectores y unidades del condominio."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.has_system_permission("manage_units")

