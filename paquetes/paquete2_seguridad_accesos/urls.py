"""Paquete 2: Seguridad, Accesos y Auditoría (CU08–CU17)."""

from django.urls import include, path

app_name = "paquete2_seguridad_accesos"

urlpatterns = [
    path("", include("paquetes.paquete2_seguridad_accesos.cu08_visitantes.urls")),
]
