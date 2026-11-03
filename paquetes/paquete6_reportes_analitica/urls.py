"""Rutas del Paquete 6: Reportes y Analítica Inteligente."""
from django.urls import include, path

urlpatterns = [
    path("cu31/", include("paquetes.paquete6_reportes_analitica.cu31_reportes.urls")),
    path("", include("paquetes.paquete6_reportes_analitica.cu31_reportes.urls")),
]

