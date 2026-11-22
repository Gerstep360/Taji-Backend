"""Rutas URL para CU19: Consultar seguimiento e historial de incidencia."""

from rest_framework.routers import DefaultRouter
from .views import IncidentTrackingViewSet

router = DefaultRouter()
router.register(r"incidents", IncidentTrackingViewSet, basename="incident-tracking")

urlpatterns = router.urls

