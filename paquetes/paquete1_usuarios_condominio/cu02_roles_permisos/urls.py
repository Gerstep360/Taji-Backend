"""Rutas para CU02: Gestionar usuarios, roles y permisos."""

from django.urls import path

from .views import (
    AllPermissionsView,
    InternalUserCreateView,
    PendingResidentsView,
    ResidentReviewView,
    RoleListView,
    RolePermissionsView,
)

app_name = "cu02_roles_permisos"

urlpatterns = [
    # Roles y permisos
    path("", RoleListView.as_view(), name="role-list"),
    path("permissions/", AllPermissionsView.as_view(), name="permission-list"),
    path("<slug:slug>/permissions/", RolePermissionsView.as_view(), name="role-permissions"),
    # Usuarios internos
    path("users/", InternalUserCreateView.as_view(), name="user-create"),
    # Residentes pendientes
    path("residents/pending/", PendingResidentsView.as_view(), name="pending-residents"),
    path("residents/<int:pk>/review/", ResidentReviewView.as_view(), name="resident-review"),
]
