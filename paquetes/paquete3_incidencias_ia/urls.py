"""Paquete 3: Incidencias e Inteligencia Artificial (CU18-CU22)."""

from rest_framework.routers import DefaultRouter
from .cu18_registrar_incidencia.views import IncidentReportViewSet
from .cu19_seguimiento_historial.views import IncidentTrackingViewSet

class IncidentViewSet(IncidentTrackingViewSet, IncidentReportViewSet):
    """Un router conserva el registro, los catálogos y el seguimiento."""
    def get_serializer_class(self):
        if self.action in ("create", "categories", "priorities", "options"):
            return IncidentReportViewSet.serializer_class
        return IncidentTrackingViewSet.get_serializer_class(self)

    def get_permissions(self):
        report_actions = ("create", "categories", "priorities", "options")
        classes = IncidentReportViewSet.permission_classes if self.action in report_actions else IncidentTrackingViewSet.permission_classes
        return [permission() for permission in classes]

    def get_serializer_context(self):
        return IncidentReportViewSet.get_serializer_context(self)


router = DefaultRouter()
router.register("incidents", IncidentViewSet, basename="incident-tracking")
urlpatterns = router.urls
