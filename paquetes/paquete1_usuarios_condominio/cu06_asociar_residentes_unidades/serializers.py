from rest_framework import serializers
from condominiums.models import Resident
from condominiums.models import Resident, ResidentUnit


class ResidentDirectorySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="person.full_name", read_only=True)
    document_number = serializers.CharField(source="person.document_number", read_only=True)

    class Meta:
        model = Resident
        fields = ("id", "full_name", "document_number", "status", "registered_at")
        read_only_fields = fields


class ResidentUnitSerializer(serializers.ModelSerializer):
    resident_name = serializers.CharField(source="resident.person.full_name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    relation_type_display = serializers.CharField(source="get_relation_type_display", read_only=True)

    class Meta:
        model = ResidentUnit
        fields = (
            "id", "resident", "resident_name", "unit", "unit_code", "relation_type",
            "relation_type_display", "is_primary", "start_date", "end_date", "created_at",
        )
        read_only_fields = ("resident_name", "unit_code", "relation_type_display", "created_at")

    def validate(self, attrs):
        instance = self.instance
        resident = attrs.get("resident", instance.resident if instance else None)
        unit = attrs.get("unit", instance.unit if instance else None)
        start_date = attrs.get("start_date", instance.start_date if instance else None)
        end_date = attrs.get("end_date", instance.end_date if instance else None)
        is_primary = attrs.get("is_primary", instance.is_primary if instance else False)
        if end_date and start_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "La fecha final no puede ser anterior a la fecha inicial."})
        active = ResidentUnit.objects.filter(resident=resident, unit=unit, end_date__isnull=True)
        if instance:
            active = active.exclude(pk=instance.pk)
        if end_date is None and active.exists():
            raise serializers.ValidationError("El residente ya tiene una asociación activa con esta unidad.")
        primary = ResidentUnit.objects.filter(resident=resident, is_primary=True, end_date__isnull=True)
        if instance:
            primary = primary.exclude(pk=instance.pk)
        if is_primary and end_date is None and primary.exists():
            raise serializers.ValidationError({"is_primary": "El residente ya tiene otra unidad principal activa."})
        return attrs
