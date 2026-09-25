"""Permisos para CU08: Registrar y autorizar visitantes."""

from rest_framework.permissions import BasePermission


class CanRegisterOrManageVisits(BasePermission):
    """
    Control de acceso para CU08 / T020:
    - Administrador ('manage_visits'): Control total sobre todas las autorizaciones.
    - Residente ('register_visits'): Puede registrar, listar y gestionar sus propias autorizaciones.
    - Seguridad ('validate_visits'): Puede consultar autorizaciones (solo lectura).
    """

    message = "No tienes permiso para gestionar autorizaciones de visita."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if view.action in ("list", "retrieve", "options"):
            return (
                user.has_system_permission("manage_visits")
                or user.has_system_permission("register_visits")
                or user.has_system_permission("validate_visits")
            )

        return (
            user.has_system_permission("register_visits")
            or user.has_system_permission("manage_visits")
        )
