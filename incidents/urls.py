"""Compatibilidad de rutas para la aplicación incidents."""

from django.urls import include, path

urlpatterns = [
    path("", include("paquetes.paquete3_incidencias_ia.urls")),
]

