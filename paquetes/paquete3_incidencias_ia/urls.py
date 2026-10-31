"""Paquete 3: Incidencias e IA (CU18–CU22)."""

from django.urls import include, path

urlpatterns = [
    path("", include("paquetes.paquete3_incidencias_ia.cu18_registrar_incidencia.urls")),
]
