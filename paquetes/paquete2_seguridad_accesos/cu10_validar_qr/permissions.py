"""Permisos para CU10: Validar la autorización de visitante mediante QR."""

from rest_framework.permissions import BasePermission

from condominiums.models import Staff


class CanValidateVisitQr(BasePermission):
    """
    Control de acceso para CU10 / T022 (RF-10):

    - Personal de seguridad (`validate_visits`): escanea y valida el QR en portería.
    - Administración (`manage_visits`): también puede validar, ya que por RBAC
      tiene el conjunto completo de permisos.

    Reglas adicionales:

    - Si el usuario tiene ficha de personal, esta debe estar ACTIVA: un guardia
      suspendido o con contrato terminado no puede autorizar ingresos.

    Este permiso responde a *quién* puede validar, no a *con qué método*: los
    métodos no admitidos los rechaza la propia vista con 405.
    """

    message = "No tienes permiso para validar autorizaciones de visita."
    message_inactive_staff = "Tu ficha de personal no está activa. No puedes validar ingresos."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if not (
            user.has_system_permission("validate_visits")
            or user.has_system_permission("manage_visits")
        ):
            return False

        staff = getattr(getattr(user, "person", None), "staff", None)
        if staff is not None and staff.status != Staff.Status.ACTIVE:
            return False

        return True

    def permission_denied(self, request, message=None, code=None):
        """Personal con ficha inactiva recibe un mensaje explícito, no genérico."""
        user = request.user
        staff = getattr(getattr(user, "person", None), "staff", None)
        if (
            staff is not None
            and staff.status != Staff.Status.ACTIVE
            and user.has_system_permission("validate_visits")
        ):
            message = self.message_inactive_staff
        return super().permission_denied(request, message=message, code=code)