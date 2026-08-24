from django.contrib import admin

from .models import Condominium, Resident, Sector, Staff, Unit


@admin.register(Condominium)
class CondominiumAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "email", "phone", "is_active")
    list_filter = ("is_active", "timezone")
    search_fields = ("name", "legal_name", "address", "email")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "condominium", "sector_type", "is_active")
    list_filter = ("condominium", "sector_type", "is_active")
    search_fields = ("code", "name", "condominium__name")
    ordering = ("condominium", "code")
    readonly_fields = ("created_at",)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("code", "sector", "unit_type", "floor_label", "status")
    list_filter = ("unit_type", "status", "sector__condominium")
    search_fields = ("code", "description", "sector__name")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = ("person", "status", "registered_at", "deactivated_at")
    list_filter = ("status",)
    search_fields = ("person__first_name", "person__last_name", "person__document_number")
    ordering = ("person__last_name", "person__first_name")
    readonly_fields = ("registered_at",)


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("person", "employee_code", "staff_type", "status", "hire_date")
    list_filter = ("staff_type", "status")
    search_fields = ("employee_code", "person__first_name", "person__last_name")
    ordering = ("person__last_name", "person__first_name")
