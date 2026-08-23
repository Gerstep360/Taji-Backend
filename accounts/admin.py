from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Person, Role, SystemPermission, User


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "document_type", "document_number", "phone", "is_active")
    list_filter = ("document_type", "is_active")
    search_fields = ("first_name", "last_name", "document_number", "contact_email", "phone")
    ordering = ("last_name", "first_name")
    readonly_fields = ("created_at", "updated_at")


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


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "phone")
    readonly_fields = ("date_joined", "updated_at", "last_login")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("first_name", "last_name", "phone", "role")}),
        ("Estado", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Permisos Django", {"fields": ("groups", "user_permissions"), "classes": ("collapse",)}),
        ("Fechas", {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )
