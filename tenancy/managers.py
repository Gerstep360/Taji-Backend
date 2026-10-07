"""Data Access Layer Multi-Tenant (Sección 6, 7 y 31 de multitenant_saas_optimizado.md)."""

from django.db import models
from tenancy.context import TenantContext


class TenantAwareQuerySet(models.QuerySet):
    """
    QuerySet que aplica automáticamente el aislamiento de tenant cuando existe un
    TenantContext activo, sin necesidad de que cada desarrollador o endpoint escriba
    manualmente 'WHERE tenant_id = ...'.
    """

    def filter_by_current_tenant(self):
        """Aplica el filtro del tenant activo si corresponde."""
        if TenantContext.is_global():
            return self

        tenant_id = TenantContext.get_current_tenant_id()
        if not tenant_id:
            return self

        explicit_lookup = getattr(self.model, "TENANT_LOOKUP_FIELD", None)
        if explicit_lookup:
            return self.filter(**{explicit_lookup: tenant_id})

        field_names = {f.name for f in self.model._meta.get_fields()}
        if "condominium" in field_names:
            return self.filter(condominium_id=tenant_id)
        if "sector" in field_names:
            return self.filter(models.Q(sector__condominium_id=tenant_id) | models.Q(sector__isnull=True))
        if "unit" in field_names:
            return self.filter(models.Q(unit__sector__condominium_id=tenant_id) | models.Q(unit__sector__isnull=True))

        return self

    def all_tenants(self):
        """
        Permite el acceso global sin filtrar por tenant
        (para superusuarios de plataforma o procesos del sistema).
        """
        return self._clone()

    def unscoped(self):
        """Alias para all_tenants."""
        return self.all_tenants()


class TenantAwareManager(models.Manager.from_queryset(TenantAwareQuerySet)):
    """
    Manager que inyecta automáticamente el filtro de tenant a nivel ORM.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = TenantContext.get_current_tenant_id()
        if tenant_id and not TenantContext.is_global():
            return qs.filter_by_current_tenant()
        return qs

    def all_tenants(self):
        """Devuelve un queryset sin la restricción de tenant."""
        return super().get_queryset()

    def unscoped(self):
        """Alias para all_tenants."""
        return self.all_tenants()
