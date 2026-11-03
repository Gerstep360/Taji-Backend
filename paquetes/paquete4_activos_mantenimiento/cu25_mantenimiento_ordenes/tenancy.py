from django.db.models import Q

from incidents.models import Incident
from maintenance.models import Asset, MaintenancePlan, Supplier, WorkOrder
from tenancy.context import TenantContext


def current_tenant():
    tenant = TenantContext.get_current_tenant()
    return tenant if tenant and tenant.is_active else None


def tenant_assets(tenant_id):
    return Asset.objects.filter(
        sector__condominium_id=tenant_id,
        sector__is_active=True,
    )


def tenant_plans(tenant_id):
    return MaintenancePlan.objects.filter(asset__sector__condominium_id=tenant_id)


def tenant_suppliers(tenant_id):
    return Supplier.objects.all_tenants().filter(condominium_id=tenant_id)


def tenant_incidents(tenant_id):
    return Incident.objects.filter(condominium_id=tenant_id)


def tenant_work_orders(tenant_id):
    legacy_scope = (
        Q(asset__sector__condominium_id=tenant_id)
        | Q(maintenance_plan__asset__sector__condominium_id=tenant_id)
        | Q(incident__condominium_id=tenant_id)
    )
    return (
        WorkOrder.objects.all_tenants()
        .filter(Q(condominium_id=tenant_id) | Q(condominium__isnull=True) & legacy_scope)
        .filter(Q(asset__isnull=True) | Q(asset__sector__condominium_id=tenant_id))
        .filter(Q(maintenance_plan__isnull=True) | Q(maintenance_plan__asset__sector__condominium_id=tenant_id))
        .filter(Q(incident__isnull=True) | Q(incident__condominium_id=tenant_id))
        .filter(Q(current_assignee_staff__isnull=True) | Q(current_assignee_staff__condominium_id=tenant_id))
        .filter(Q(supplier__isnull=True) | Q(supplier__condominium_id=tenant_id))
        .distinct()
    )
