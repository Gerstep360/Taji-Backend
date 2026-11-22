from rest_framework.permissions import BasePermission

from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember

# RN4: la Directiva es de solo lectura (track_*); solo el Administrador gestiona.
MANAGE_CODE = "manage_assemblies"
TRACK_CODE = "track_assembly_decisions"


def _role_permission_codes(user):
    """Códigos del rol del usuario en el tenant activo, o None si es superusuario."""
    if user.is_superuser:
        return None
    membership = TenantContext.get_current_membership()
    role = membership.role if membership and membership.user_id == user.pk and membership.is_active else None
    if not role or not role.is_active:
        return set()
    return set(role.permissions.filter(is_active=True).values_list("code", flat=True))


def can_manage(user):
    if not user or not user.is_authenticated:
        return False
    codes = _role_permission_codes(user)
    return codes is None or MANAGE_CODE in codes


def can_track(user):
    """Administrador y Directiva: ven actas, acuerdos y evidencias."""
    if not user or not user.is_authenticated:
        return False
    codes = _role_permission_codes(user)
    return codes is None or bool(codes & {MANAGE_CODE, TRACK_CODE})


class AssemblyTenantMember(IsTenantMember):
    message = "Necesitas una membresía activa y un condominio seleccionado para consultar asambleas."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active or not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        member = TenantContext.get_current_membership()
        return bool(member and member.user_id == request.user.pk and member.is_active
                    and member.role and member.role.is_active)


class CanTrackAgreements(BasePermission):
    message = "Solo la administración y la directiva pueden consultar los acuerdos."

    def has_permission(self, request, view):
        return can_track(request.user)
