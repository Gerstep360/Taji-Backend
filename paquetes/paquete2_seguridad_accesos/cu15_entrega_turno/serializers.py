from rest_framework import serializers
from security.models import ShiftHandover, ShiftLogEntry
from ..cu13_turnos_seguridad.serializers import SecurityShiftSerializer
from ..cu14_novedades_incidentes.serializers import ShiftLogSerializer


class HandoverSerializer(serializers.ModelSerializer):
    outgoing_detail = SecurityShiftSerializer(source="outgoing_shift", read_only=True)
    incoming_detail = SecurityShiftSerializer(source="incoming_shift", read_only=True)
    log_entries = serializers.SerializerMethodField()

    class Meta:
        model = ShiftHandover
        fields = ("id", "outgoing_shift", "incoming_shift", "outgoing_detail", "incoming_detail", "summary",
                  "delivered_by_user", "received_by_user", "delivered_at", "received_at", "status", "log_entries")
        read_only_fields = fields

    def get_log_entries(self, obj) -> list:
        if self.context.get("view") and self.context["view"].action == "list":
            return []
        # La entrega representa los registros existentes al entregar, no los añadidos después.
        entries = obj.outgoing_shift.log_entries.exclude(entry_type=ShiftLogEntry.Type.HANDOVER_NOTE).filter(
            occurred_at__lte=obj.delivered_at
        ).select_related("shift__guard_staff__person", "shift__condominium").order_by("occurred_at", "id")
        return ShiftLogSerializer(entries, many=True).data


class DeliverySerializer(serializers.Serializer):
    outgoing_shift = serializers.IntegerField(min_value=1)
    incoming_shift = serializers.IntegerField(min_value=1)
    summary = serializers.CharField(max_length=5000, allow_blank=False, trim_whitespace=True)


class CandidateQuerySerializer(serializers.Serializer):
    outgoing_shift = serializers.IntegerField(min_value=1)


class HandoverQuerySerializer(serializers.Serializer):
    outgoing_shift = serializers.IntegerField(min_value=1, required=False)
    incoming_shift = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=ShiftHandover.Status.choices, required=False)
    guard = serializers.IntegerField(min_value=1, required=False)
    condominium = serializers.IntegerField(min_value=1, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs.get("date_from") and attrs.get("date_to") and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_to": "La fecha final no puede ser anterior a la inicial."})
        return attrs
