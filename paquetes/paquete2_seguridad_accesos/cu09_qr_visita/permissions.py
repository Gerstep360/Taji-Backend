"""Permisos para CU09: Generar y consultar el QR temporal de visita."""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class CanIssueVisitQr(BasePermission):
    """
    Control de acceso para CU09 / T021:

    - Administrador (`manage_visits`): emite y consulta el QR de cualquier autorización.
    - Residente (`register_visits`): emite y consulta únicamente el QR de las
      autorizaciones que él mismo emitió (aislamiento de información, RN4 de CU08).

    El personal de seguridad queda excluido a propósito: su rol es **validar**
    el QR en CU10, no emitirlo. `manage_visits` solo se acepta en lectura para
    que la administración pueda auditar los QR vigentes sin poder suplantar al
    residente al momento de emitirlos.
    """

    message = "No tienes permiso para gestionar el QR de esta visita."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_superuser or user.has_system_permission("manage_visits"):
            return True

        if request.method in SAFE_METHODS:
            return user.has_system_permission("manage_visits") or user.has_system_permission(
                "register_visits"
            )

        return user.has_system_permission("register_visits")

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser or user.has_system_permission("manage_visits"):
            return True

        resident = getattr(getattr(user, "person", None), "resident", None)
        return resident is not None and obj.authorized_by_resident_id == resident.id