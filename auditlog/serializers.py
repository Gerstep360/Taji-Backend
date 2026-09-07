from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "occurred_at",
            "action_code",
            "resource_type",
            "resource_id",
            "description",
            "ip_address",
            "user_agent",
            "request_id",
            "actor_user",
            "actor_email",
            "actor_name",
            "before_data",
            "after_data",
        )
        read_only_fields = fields

    def get_actor_email(self, obj: AuditEvent) -> str:
        if obj.actor_user:
            return obj.actor_user.email
        return "Sistema / Anónimo"

    def get_actor_name(self, obj: AuditEvent) -> str:
        if obj.actor_user:
            return obj.actor_user.full_name or obj.actor_user.first_name or obj.actor_user.email
        return "Sistema"
