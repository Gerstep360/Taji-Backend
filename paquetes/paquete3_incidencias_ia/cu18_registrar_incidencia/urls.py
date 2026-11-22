"""Rutas para CU18: Registrar incidencia."""

from rest_framework.routers import SimpleRouter

from .views import IncidentReportViewSet

router = SimpleRouter()
router.register("incidents", IncidentReportViewSet, basename="incident-report")

urlpatterns = router.urls
