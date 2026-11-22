from django.urls import include, path

urlpatterns = [
    path("cu30/", include("paquetes.paquete5_servicios_comunidad.cu30_dashboard_reportes.urls")),
]
