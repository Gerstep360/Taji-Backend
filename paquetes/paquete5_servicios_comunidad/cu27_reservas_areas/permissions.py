"""Permisos del CU27.

Se reutilizan los códigos RBAC existentes:
- ``manage_reservations``: administra (aprueba, rechaza, cancela, finaliza) reservas.
- ``reserve_areas``: solicita y cancela reservas propias.
"""
from rest_framework.permissions import BasePermission

from community.api import CommunityMember, allowed
from condominiums.models import Resident
from tenancy.context import TenantContext

MANAGE_PERMISSION = "manage_reservations"
RESERVE_PERMISSION = "reserve_areas"


def can_manage(user):
    return allowed(user, MANAGE_PERMISSION)


def can_reserve(user):
    return allowed(user, RESERVE_PERMISSION)


def current_tenant_id():
    tenant = TenantContext.get_current_tenant()
    return tenant.pk if tenant and tenant.is_active else None


def current_resident(user):
    """Perfil de residente activo del usuario en el condominio actual (o ``None``)."""
    tenant_id = current_tenant_id()
    if not tenant_id or not getattr(user, "person_id", None):
        return None
    return (
        Resident.objects.all_tenants()
        .filter(condominium_id=tenant_id, person_id=user.person_id, status=Resident.Status.ACTIVE)
        .select_related("person")
        .first()
    )


class ReservationsTenantMember(CommunityMember):
    message = "Necesitas una membresía activa en el condominio seleccionado."


class CanUseReservations(BasePermission):
    message = "No tienes permisos para consultar reservas de áreas comunes."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (can_manage(user) or can_reserve(user)))


class CanManageReservations(BasePermission):
    message = "Solo la administración puede realizar esta acción sobre las reservas."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and can_manage(request.user))
