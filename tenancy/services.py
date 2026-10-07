"""Aprovisionamiento de tenants (Sección 21 de multitenant_saas_optimizado.md)."""

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from accounts.models import Role, User
from auditlog.services import record_audit_event
from condominiums.models import Condominium, Sector, Unit
from tenancy.models import TenantMembership


class TenantProvisioningService:
    """
    Aprovisiona un nuevo tenant en el modelo Pool/Shared.
    Crea el condominio, estructura base y membresía inicial de administrador
    en una única transacción atómica sin requerir migraciones ni bases de datos separadas.
    """

    @classmethod
    @transaction.atomic
    def provision_tenant(
        cls,
        name: str,
        slug: str = None,
        legal_name: str = "",
        address: str = "",
        phone: str = "",
        email: str = "",
        admin_user: User = None,
        admin_email: str = None,
        max_units: int = 500,
        max_residents: int = 1500,
        actor_user: User = None,
        request=None,
    ) -> Condominium:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError({"name": ["El nombre del condominio/tenant es requerido."]})

        resolved_slug = slugify(slug or clean_name)
        if not resolved_slug:
            resolved_slug = "condominio-nuevo"

        # Garantizar slug único
        base_slug = resolved_slug
        counter = 1
        while Condominium.objects.filter(slug=resolved_slug).exists():
            resolved_slug = f"{base_slug}-{counter}"
            counter += 1

        # 1. Crear el Condominium / Tenant
        condominium = Condominium.objects.create(
            name=clean_name,
            slug=resolved_slug,
            legal_name=legal_name.strip(),
            address=address.strip(),
            phone=phone.strip(),
            email=email.strip(),
            max_units=max_units,
            max_residents=max_residents,
            is_active=True,
            status="ACTIVE",
        )

        # 2. Crear Sector inicial por defecto
        sector = Sector.objects.create(
            condominium=condominium,
            code="SEC-01",
            name="Bloque Principal",
            sector_type=Sector.Type.BLOCK,
            description="Sector inicial aprovisionado automáticamente.",
            is_active=True,
        )

        # 3. Crear Unidad administrativa por defecto
        # Para que el code sea único globalmente según el schema actual, concatenamos el slug
        Unit.objects.create(
            sector=sector,
            code=f"ADM-{condominium.id}",
            unit_type=Unit.Type.OFFICE,
            floor_label="PB",
            description="Oficina de administración del condominio.",
            status=Unit.Status.ACTIVE,
        )

        # 4. Asignar membresía de Administrador al usuario indicado
        target_admin = admin_user
        if not target_admin and admin_email:
            target_admin = User.objects.filter(email=admin_email).first()

        admin_role = Role.objects.filter(slug="admin").first() or Role.objects.filter(name__icontains="Admin").first()

        if target_admin:
            TenantMembership.objects.create(
                user=target_admin,
                condominium=condominium,
                role=admin_role,
                is_default=True,
                is_active=True,
            )

        # 5. Auditoría
        record_audit_event(
            action_code="saas.tenant.provisioned",
            resource_type="Condominium",
            resource_id=condominium.id,
            description=f"Tenant aprovisionado: {condominium.name} (Slug: {condominium.slug}).",
            actor_user=actor_user or target_admin,
            after_data={
                "id": condominium.id,
                "name": condominium.name,
                "slug": condominium.slug,
                "max_units": condominium.max_units,
            },
            request=request,
        )

        return condominium
