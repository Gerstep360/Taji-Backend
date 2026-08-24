from django.contrib import admin

from .models import AssetType


@admin.register(AssetType)
class AssetTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("name",)
