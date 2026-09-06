from rest_framework import serializers
from condominiums.models import Condominium
from condominiums.models import Condominium, Sector, Unit


class SectorSerializer(serializers.ModelSerializer):
    """CU04: sectores/bloques/torres/pisos/zonas, con jerarquía padre-hijo."""

    parent_name = serializers.SerializerMethodField()

    def get_parent_name(self, obj) -> str | None:
        return obj.parent.name if obj.parent else None
    sector_type_display = serializers.CharField(source="get_sector_type_display", read_only=True)

    class Meta:
        model = Sector
        fields = (
            "id", "code", "name", "sector_type", "sector_type_display",
            "description", "parent", "parent_name", "is_active",
        )
        extra_kwargs = {
            "parent": {"required": False, "allow_null": True},
            "description": {"required": False, "allow_blank": True},
        }

    def validate_parent(self, value):
        if value and self.instance and value.pk == self.instance.pk:
            raise serializers.ValidationError("Un sector no puede ser su propio padre.")
        return value

    def create(self, validated_data):
        validated_data["condominium"] = Condominium.objects.first()
        return super().create(validated_data)


class UnitSerializer(serializers.ModelSerializer):
    """CU04: unidades habitacionales, vinculadas a un sector."""

    sector_name = serializers.SerializerMethodField()

    def get_sector_name(self, obj) -> str | None:
        return obj.sector.name if obj.sector else None
    unit_type_display = serializers.CharField(source="get_unit_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Unit
        fields = (
            "id", "code", "unit_type", "unit_type_display", "floor_label",
            "description", "status", "status_display", "sector", "sector_name",
        )
        extra_kwargs = {
            "sector": {"required": False, "allow_null": True},
            "floor_label": {"required": False, "allow_blank": True},
            "description": {"required": False, "allow_blank": True},
        }
