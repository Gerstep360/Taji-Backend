from rest_framework import serializers
from condominiums.models import Condominium


class CondominiumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condominium
        fields = (
            "id",
            "name",
            "legal_name",
            "address",
            "phone",
            "email",
            "timezone",
            "logo",
            "rules_summary",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
