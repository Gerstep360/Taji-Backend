"""Paquete 1: CU01–CU07."""
from django.urls import include, path

app_name = "paquete1_usuarios_condominio"
urlpatterns = [
    path("auth/", include("paquetes.paquete1_usuarios_condominio.cu01_autenticacion.urls")),
    path("roles/", include("paquetes.paquete1_usuarios_condominio.cu02_roles_permisos.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu03_datos_condominio.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu04_sectores_unidades.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu05_residentes.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu06_asociar_residentes_unidades.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu07_personal.urls")),
]
