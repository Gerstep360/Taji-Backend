"""URLs del Paquete 1 — Gestión de Usuarios y Condominio.

Agrupa los Casos de Uso del Paquete 1:
- CU01: Iniciar sesión y autenticar usuario (/auth/)
- CU02: Gestionar usuarios, roles y permisos (/roles/)
- CU03: Configurar datos generales del condominio (en desarrollo)
- CU04: Gestionar sectores y unidades habitacionales (/sectors/, /units/)
- CU05: Gestionar residentes y copropietarios (en desarrollo)
- CU06: Asociar residentes a unidades habitacionales (en desarrollo)
- CU07: Gestionar personal del condominio (/staff/)
"""

from django.urls import include, path

app_name = "paquete1_usuarios_condominio"

urlpatterns = [
    path("auth/", include("paquetes.paquete1_usuarios_condominio.cu01_autenticacion.urls")),
    path("roles/", include("paquetes.paquete1_usuarios_condominio.cu02_roles_permisos.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu07_personal.urls")),
    path("", include("paquetes.paquete1_usuarios_condominio.cu04_sectores_unidades.urls")),
]
