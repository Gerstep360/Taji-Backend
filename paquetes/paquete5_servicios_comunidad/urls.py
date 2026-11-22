from django.urls import include, path

urlpatterns = [
    path("cu28/", include("paquetes.paquete5_servicios_comunidad.cu28_comunicados_notificaciones.urls")),
    path("cu30/", include("paquetes.paquete5_servicios_comunidad.cu30_dashboard_reportes.urls")),
]
