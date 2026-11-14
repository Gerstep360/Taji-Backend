from django.contrib import admin

from .models import CommonArea, CommonAreaBlock, CommonAreaSchedule


@admin.register(CommonArea)
class CommonAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "condominium", "sector", "capacity", "status", "requires_approval")
    list_filter = ("condominium", "status", "requires_approval")
    search_fields = ("name", "condominium__name", "sector__name")
    ordering = ("condominium", "name")


@admin.register(CommonAreaSchedule)
class CommonAreaScheduleAdmin(admin.ModelAdmin):
    list_display = ("common_area", "weekday", "opens_at", "closes_at", "is_active")
    list_filter = ("common_area__condominium", "weekday", "is_active")
    search_fields = ("common_area__name",)
    ordering = ("common_area", "weekday", "opens_at")


@admin.register(CommonAreaBlock)
class CommonAreaBlockAdmin(admin.ModelAdmin):
    list_display = ("common_area", "reason", "blocked_from", "blocked_until", "work_order", "created_by_user")
    list_filter = ("common_area__condominium",)
    search_fields = ("common_area__name", "reason")
    ordering = ("common_area", "blocked_from")
    readonly_fields = ("created_at",)
