"""Paquete 2: Seguridad, Accesos y Auditoría (CU08–CU17)."""

from django.urls import include, path

app_name = "paquete2_seguridad_accesos"

urlpatterns = [
    path("", include("paquetes.paquete2_seguridad_accesos.cu08_visitantes.urls")),
    # CU10 se declara antes que CU09: `visit-qr/validate/` es un segmento fijo y
    # no debe competir con el patrón numérico `visit-qr/<pk>/` del router.
    path("", include("paquetes.paquete2_seguridad_accesos.cu10_validar_qr.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu09_qr_visita.urls")),
]
