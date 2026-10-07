"""Paquete 2: Seguridad, Accesos y Auditoría (CU08–CU17)."""

from django.urls import include, path

urlpatterns = [
    path("cu12/", include("paquetes.paquete2_seguridad_accesos.cu12_consultar_visitas_dentro.urls")),
    path("", include("security.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu08_visitantes.urls")),
    # CU10 se declara antes que CU09: `visit-qr/validate/` es un segmento fijo y
    # no debe competir con el patrón numérico `visit-qr/<pk>/` del router.
    path("", include("paquetes.paquete2_seguridad_accesos.cu10_validar_qr.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu09_qr_visita.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu13_turnos_seguridad.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu14_novedades_incidentes.urls")),
    path("", include("paquetes.paquete2_seguridad_accesos.cu15_entrega_turno.urls")),
    path("cu17/", include("paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.urls")),

    path("facial/", include("paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.urls")),
]
