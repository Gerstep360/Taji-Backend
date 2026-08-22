from django.contrib import admin

from .models import Person, Role, SystemPermission, User


@admin.register(SystemPermission)
class SystemPermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_public", "is_active")
    list_filter = ("is_public", "is_active")
    filter_horizontal = ("permissions",)
    search_fields = ("name", "slug")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "document_type", "document_number", "phone", "contact_email")
    search_fields = ("first_name", "last_name", "document_number", "phone", "contact_email")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("email", "person__first_name", "person__last_name", "person__phone")
    readonly_fields = ("first_name", "last_name", "phone", "date_joined", "updated_at", "last_login")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("person", "role")}),
        ("Datos Personales (Lectura)", {"fields": ("first_name", "last_name", "phone")}),
        ("Estado", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Fechas", {"fields": ("last_login", "date_joined", "updated_at")}),
    )

