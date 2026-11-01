"""Paquete 3: Incidencias e Inteligencia Artificial (CU18–CU22)."""

from django.urls import include, path

urlpatterns = [
    path("", include("paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.urls")),
]

