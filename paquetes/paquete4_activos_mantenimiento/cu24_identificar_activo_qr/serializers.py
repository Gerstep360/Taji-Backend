from rest_framework import serializers
import uuid as uuid_module

from maintenance.models import Asset


class QRScanRequestSerializer(serializers.Serializer):
    """Valida y deserializa el payload del código QR escaneado."""

    qr_payload = serializers.CharField(required=True, allow_blank=False)

    def validate_qr_payload(self, value):
        value = value.strip()
        if not value.startswith("TAJI-ASSET."):
            raise serializers.ValidationError("Formato de QR inválido: prefijo incorrecto.")

        try:
            uuid_hex = value.split(".", 1)[1]
            uuid_module.UUID(hex=uuid_hex)
        except (IndexError, ValueError) as e:
            raise serializers.ValidationError(f"Formato de QR inválido: UUID mal formado. {str(e)}")

        return value


class AssetQRScanResponseSerializer(serializers.ModelSerializer):
    """Serializa un asset encontrado mediante escaneo de QR."""

    asset_type_name = serializers.CharField(source="asset_type.name", read_only=True)
    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")

    class Meta:
        model = Asset
        fields = (
            "id",
            "code",
            "name",
            "description",
            "asset_type_name",
            "sector_name",
            "brand",
            "model",
            "serial_number",
            "status",
            "qr_uuid",
            "created_at",
        )
        read_only_fields = fields
