"""Rutas para CU04: Gestionar sectores y unidades habitacionales."""

from rest_framework.routers import SimpleRouter

from .views import SectorViewSet, UnitViewSet

app_name = "cu04_sectores_unidades"

router = SimpleRouter()
router.register("sectors", SectorViewSet, basename="sector")
router.register("units", UnitViewSet, basename="unit")

urlpatterns = router.urls