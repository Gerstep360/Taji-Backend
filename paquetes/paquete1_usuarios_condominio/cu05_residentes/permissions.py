from rest_framework.permissions import BasePermission, SAFE_METHODS


class CanManageResidents(BasePermission):
    """Limita la modificación de residentes a usuarios con el permiso 'manage_residents'.

    Permite lectura (GET, HEAD, OPTIONS) a cualquier usuario autenticado del sistema para
    que los formularios de visitas y accesos puedan consultar el directorio de residentes.
    """

    message = "No tienes permiso para gestionar a los residentes del condominio."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.has_system_permission("manage_residents")

