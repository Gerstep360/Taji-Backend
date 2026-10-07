from rest_framework import permissions


class CanManageFaceVerification(permissions.BasePermission):
    """Permiso para realizar verificación facial de residentes y gestionar biometría.

    Permite acceso a Administradores, Seguridad/Guardias y usuarios con permisos de seguridad/residentes.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_staff or request.user.is_superuser:
            return True

        role_slug = request.user.role.slug if request.user.role else ""
        if role_slug in ("administrador", "seguridad", "directiva"):
            return True

        membership = getattr(request, "tenant_membership", None)
        if membership and membership.role:
            if membership.role.slug in ("administrador", "seguridad", "directiva"):
                return True

        required = {
            "validate_visits",
            "register_entry_exit",
            "capture_security_evidence",
            "manage_residents",
        }
        for code in required:
            if request.user.has_system_permission(code):
                return True
            if membership and membership.role and membership.role.permissions.filter(code=code, is_active=True).exists():
                return True

        return False
