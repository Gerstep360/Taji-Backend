"""Paquete 2: CU08–CU17 Seguridad y Accesos."""
from django.urls import include, path

urlpatterns = [
    path("cu17/", include("paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.urls")),
    path("facial/", include("paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.urls")),
]
