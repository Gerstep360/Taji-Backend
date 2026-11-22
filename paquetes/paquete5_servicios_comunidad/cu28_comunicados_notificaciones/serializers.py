from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from notifications.models import Announcement, DeviceToken, Notification
from tenancy.context import TenantContext


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField(read_only=True)
    audience_display = serializers.CharField(source="get_audience_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Announcement
        fields = (
            "id",
            "title",
            "body",
            "audience",
            "audience_display",
            "priority",
            "priority_display",
            "status",
            "status_display",
            "published_at",
            "expires_at",
            "created_by_user",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by_user", "created_at", "updated_at")

    def get_created_by_name(self, obj) -> str:
        if not obj.created_by_user:
            return ""
        user = obj.created_by_user
        if hasattr(user, "person") and user.person:
            return getattr(user.person, "full_name", "") or str(user.person)
        if hasattr(user, "full_name"):
            return getattr(user, "full_name", "")
        return getattr(user, "email", "")

    def validate(self, attrs):
        title = attrs.get("title", getattr(self.instance, "title", "")).strip()
        body = attrs.get("body", getattr(self.instance, "body", "")).strip()

        if not title:
            raise ValidationError({"title": "El título del comunicado no puede estar vacío."})
        if not body:
            raise ValidationError({"body": "El contenido del comunicado no puede estar vacío."})

        published_at = attrs.get("published_at", getattr(self.instance, "published_at", None))
        expires_at = attrs.get("expires_at", getattr(self.instance, "expires_at", None))

        if published_at and expires_at and expires_at <= published_at:
            raise ValidationError(
                {"expires_at": "La fecha de vencimiento debe ser posterior a la fecha de publicación."}
            )

        return attrs


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = ("id", "token", "platform", "is_active", "last_seen_at", "created_at")
        read_only_fields = ("id", "created_at", "last_seen_at")
        extra_kwargs = {
            "token": {"validators": []},
        }

    def validate_token(self, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValidationError("El token de dispositivo no puede estar vacío.")
        return token


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField(read_only=True)
    priority = serializers.SerializerMethodField(read_only=True)
    audience = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "notification_type",
            "title",
            "message",
            "resource_type",
            "resource_id",
            "priority",
            "audience",
            "sent_at",
            "read_at",
            "is_read",
            "created_at",
        )
        read_only_fields = (
            "id",
            "notification_type",
            "title",
            "message",
            "resource_type",
            "resource_id",
            "priority",
            "audience",
            "sent_at",
            "is_read",
            "created_at",
        )

    def get_is_read(self, obj) -> bool:
        return obj.read_at is not None

    def get_priority(self, obj) -> str:
        if obj.resource_type == "announcement" and obj.resource_id:
            try:
                announcement = Announcement.objects.filter(pk=int(obj.resource_id)).only("priority").first()
                if announcement:
                    return announcement.priority
            except (ValueError, TypeError):
                pass
        return "NORMAL"

    def get_audience(self, obj) -> str:
        if obj.resource_type == "announcement" and obj.resource_id:
            try:
                announcement = Announcement.objects.filter(pk=int(obj.resource_id)).only("audience").first()
                if announcement:
                    return announcement.audience
            except (ValueError, TypeError):
                pass
        return "ALL"
