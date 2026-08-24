from django.contrib import admin

from .models import IncidentCategory, PriorityLevel, RiskRule


@admin.register(IncidentCategory)
class IncidentCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_staff_type", "is_active")
    list_filter = ("default_staff_type", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("name",)


@admin.register(PriorityLevel)
class PriorityLevelAdmin(admin.ModelAdmin):
    list_display = ("rank", "code", "name", "target_minutes", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("rank",)


@admin.register(RiskRule)
class RiskRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "entity_type", "weight", "is_active")
    list_filter = ("entity_type", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")
