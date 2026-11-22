from rest_framework import serializers

from .models import OperationsRecord


class Warranty(serializers.Serializer):
    provider = serializers.CharField(max_length=100)
    reference = serializers.CharField(max_length=80)
    coverage = serializers.CharField(max_length=400)


class Quote(serializers.Serializer):
    provider = serializers.CharField(max_length=100)
    request_code = serializers.RegexField(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$", max_length=40)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    currency = serializers.ChoiceField(choices=("BOB", "USD"))
    delivery_days = serializers.IntegerField(min_value=0, max_value=3650)
    warranty_months = serializers.IntegerField(min_value=0, max_value=1200)
    scope = serializers.CharField(max_length=400)

    def validate_request_code(self, value):
        return value.upper()


CHECKS = {
    "lighting": "Iluminación",
    "signage": "Señalización",
    "surfaces": "Pisos y superficies",
    "drainage": "Drenaje visible",
    "order": "Orden y limpieza",
}
CONDITIONS = ("ok", "attention", "not_checked")


class Inspection(serializers.Serializer):
    location = serializers.CharField(max_length=100)
    checks = serializers.DictField(child=serializers.ChoiceField(choices=CONDITIONS))
    notes = serializers.CharField(max_length=400, allow_blank=True)

    def validate_checks(self, value):
        if set(value) != set(CHECKS):
            raise serializers.ValidationError("Registra los cinco puntos de inspección.")
        return value


DETAILS = {"warranties": Warranty, "quotes": Quote, "inspections": Inspection}
STATUSES = {
    "warranties": ("active", "claimed", "closed"),
    "quotes": ("received", "shortlisted", "discarded"),
    "inspections": ("draft", "reviewed", "closed"),
}


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationsRecord
        fields = ("id", "kind", "title", "date", "status", "details", "created_at", "updated_at")
        read_only_fields = ("id", "kind", "created_at", "updated_at")

    def validate(self, attrs):
        kind = self.context["view"].kwargs["kind"]
        if attrs["status"] not in STATUSES[kind]:
            raise serializers.ValidationError({"status": "Selecciona un estado válido."})
        detail = DETAILS[kind](data=attrs["details"])
        detail.is_valid(raise_exception=False)
        if detail.errors:
            raise serializers.ValidationError({"details": detail.errors})
        # Usamos el contrato del serializer también para valores JSON, p. ej. Decimal a texto.
        attrs["details"] = dict(detail.data)
        return attrs


class AnalysisInput(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=5)

    def validate_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("No repitas registros.")
        return value
