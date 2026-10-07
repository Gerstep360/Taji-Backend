from django.urls import path

from paquetes.paquete2_seguridad_accesos.cu16_auditoria_bitacora.views import Cu16AuditEventListView

app_name = "auditlog"

urlpatterns = [
    path("", Cu16AuditEventListView.as_view(), name="audit-list"),
]
