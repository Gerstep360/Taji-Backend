from rest_framework import serializers

from condominiums.models import Sector
from maintenance.models import Asset, AssetType
from tenancy.context import TenantContext


class AssetTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetType
        fields = ("id", "code", "name", "description", "is_active")
        read_only_fields = ("id",)


class AssetSerializer(serializers.ModelSerializer):
    asset_type_id = serializers.PrimaryKeyRelatedField(
        source="asset_type", queryset=AssetType.objects.filter(is_active=True)
    )
    asset_type_name = serializers.CharField(source="asset_type.name", read_only=True)
    sector_id = serializers.PrimaryKeyRelatedField(
        source="sector", queryset=Sector.objects.filter(is_active=True)
    )
    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")
    qr_uuid = serializers.UUIDField(read_only=True)

    class Meta:
        model = Asset
        fields = (
            "id",
            "code",
            "name",
            "description",
            "asset_type_id",
            "asset_type_name",
            "sector_id",
            "sector_name",
            "brand",
            "model",
            "serial_number",
            "installation_date",
            "status",
            "qr_uuid",
            "extra_data",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "qr_uuid", "created_at", "updated_at")

    def validate_sector_id(self, sector):
        tenant_id = TenantContext.get_current_tenant_id()
        if not tenant_id or sector.condominium_id != tenant_id:
            raise serializers.ValidationError("El sector no pertenece al condominio actual.")
        return sector

    def validate_code(self, value):
        value = value.strip()
        queryset = Asset.objects.filter(code__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Ya existe un activo con ese código.")
        return value
