"""CU14: registro inmutable de novedades, incidentes y alertas del turno."""

from rest_framework import serializers
from security.models import ShiftLogEntry


class ShiftLogSerializer(serializers.ModelSerializer):
    expected_shift = serializers.IntegerField(min_value=1, write_only=True, required=False)
    guard_staff = serializers.IntegerField(source="shift.guard_staff_id", read_only=True)
    guard_name = serializers.CharField(source="shift.guard_staff.person.full_name", read_only=True)
    condominium = serializers.IntegerField(source="shift.condominium_id", read_only=True, allow_null=True)
    condominium_name = serializers.CharField(source="shift.condominium.name", read_only=True, default="")
    shift_status = serializers.CharField(source="shift.status", read_only=True)
    scheduled_start = serializers.DateTimeField(source="shift.scheduled_start", read_only=True)
    scheduled_end = serializers.DateTimeField(source="shift.scheduled_end", read_only=True)
    title = serializers.CharField(max_length=120, allow_blank=False, trim_whitespace=True)
    description = serializers.CharField(max_length=5000, allow_blank=False, trim_whitespace=True)
    entry_type = serializers.ChoiceField(choices=["NOTE", "INCIDENT", "ALERT"])
    severity = serializers.ChoiceField(choices=ShiftLogEntry.Severity.choices)

    class Meta:
        model = ShiftLogEntry
        fields = ("id", "shift", "expected_shift", "guard_staff", "guard_name", "condominium", "condominium_name",
                  "shift_status", "scheduled_start", "scheduled_end", "created_by_user", "entry_type",
                  "severity", "title", "description", "occurred_at", "created_at")
        read_only_fields = ("id", "shift", "created_by_user", "occurred_at", "created_at")


class ShiftLogQuerySerializer(serializers.Serializer):
    shift = serializers.IntegerField(min_value=1, required=False)
    guard = serializers.IntegerField(min_value=1, required=False)
    condominium = serializers.IntegerField(min_value=1, required=False)
    entry_type = serializers.ChoiceField(choices=["NOTE", "INCIDENT", "ALERT"], required=False)
    severity = serializers.ChoiceField(choices=ShiftLogEntry.Severity.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs.get("date_from") and attrs.get("date_to") and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_to": "La fecha final no puede ser anterior a la inicial."})
        return attrs
