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

        role_slugs = set(request.user.roles.values_list("slug", flat=True))
        if "administrador" in role_slugs or "seguridad" in role_slugs:
            return True

        user_permissions = set(
            request.user.roles.values_list("permissions__code", flat=True)
        )
        required = {
            "validate_visits",
            "register_entry_exit",
            "capture_security_evidence",
            "manage_residents",
        }
        return bool(user_permissions & required)
