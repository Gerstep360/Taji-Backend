from django.contrib import admin
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "action_code",
        "actor_user",
        "resource_type",
        "resource_id",
        "ip_address",
    )
    list_filter = ("action_code", "resource_type", "occurred_at")
    search_fields = (
        "action_code",
        "resource_type",
        "resource_id",
        "actor_user__email",
        "description",
    )
    ordering = ("-occurred_at",)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
