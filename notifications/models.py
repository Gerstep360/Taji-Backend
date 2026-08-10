from django.db import models
from django.db.models import Q
from django.utils import timezone


class Announcement(models.Model):
    class Audience(models.TextChoices):
        ALL = "ALL", "Todos"
        RESIDENTS = "RESIDENTS", "Residentes"
        STAFF = "STAFF", "Personal"
        SECURITY = "SECURITY", "Seguridad"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        DIRECTIVE = "DIRECTIVE", "Directiva"

    class Priority(models.TextChoices):
        LOW = "LOW", "Baja"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "Alta"
        URGENT = "URGENT", "Urgente"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        PUBLISHED = "PUBLISHED", "Publicado"
        ARCHIVED = "ARCHIVED", "Archivado"

    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="created_announcements",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=160)
    body = models.TextField()
    audience = models.CharField(max_length=30, choices=Audience.choices, default=Audience.ALL)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcement"
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__isnull=True)
                | Q(published_at__isnull=True)
                | Q(expires_at__gt=models.F("published_at")),
                name="chk_announcement_expiry",
            )
        ]
        indexes = [
            models.Index(fields=("status", "-published_at"), name="idx_announcement_publish")
        ]


class DeviceToken(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "ANDROID", "Android"
        IOS = "IOS", "iOS"
        WEB = "WEB", "Web"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=500, unique=True)
    platform = models.CharField(max_length=20, choices=Platform.choices)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "device_token"
        indexes = [
            models.Index(fields=("user", "is_active"), name="idx_device_user_active")
        ]


class Notification(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=40)
    title = models.CharField(max_length=160)
    message = models.TextField()
    resource_type = models.CharField(max_length=60, null=True, blank=True)
    resource_id = models.CharField(max_length=80, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notification"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "-created_at"),
                condition=Q(read_at__isnull=True),
                name="idx_notification_unread",
            )
        ]