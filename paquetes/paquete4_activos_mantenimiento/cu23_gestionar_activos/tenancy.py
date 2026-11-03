from maintenance.models import Asset


def tenant_assets(tenant_id):
    return Asset.objects.filter(
        sector__condominium_id=tenant_id,
        sector__is_active=True,
    )
