"""Acceso de CU13–15 limitado al condominio autenticado."""

from security.models import SecurityShift
from tenancy.context import TenantContext
from tenancy.permissions import IsTenantMember


class HasSecurityTenant(IsTenantMember):
    message = "Necesitas una membresía activa y un condominio seleccionado para acceder a seguridad."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        return bool(tenant and tenant.is_active and super().has_permission(request, view))


def tenant_shifts():
    tenant_id = TenantContext.get_current_tenant_id()
    if tenant_id is None:
        return SecurityShift.objects.none()
    return SecurityShift.objects.filter(
        condominium_id=tenant_id, guard_staff__condominium_id=tenant_id,
    )
