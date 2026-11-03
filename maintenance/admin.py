from django.contrib import admin

from .models import (
    Asset,
    AssetType,
    MaintenancePlan,
    Supplier,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderAttachment,
    WorkOrderCostItem,
    WorkOrderStatusHistory,
)


@admin.register(AssetType)
class AssetTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "description")
    ordering = ("name",)


admin.site.register(
    (
        Asset,
        MaintenancePlan,
        Supplier,
        WorkOrder,
        WorkOrderAssignment,
        WorkOrderAttachment,
        WorkOrderCostItem,
        WorkOrderStatusHistory,
    )
)
