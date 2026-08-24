from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LoginAttempt, Person, Role, SystemPermission, User


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
    list_filter = ("document_type", "is_active")
    search_fields = ("first_name", "last_name", "document_number", "phone", "contact_email")
    ordering = ("last_name", "first_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
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
                    "person",
                    "role",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "was_successful", "ip_address", "created_at")
    list_filter = ("was_successful", "created_at")
    search_fields = ("email", "ip_address")
    readonly_fields = ("user", "email", "ip_address", "was_successful", "created_at")
