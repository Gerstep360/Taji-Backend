"""Rutas para CU05: Gestionar residentes y copropietarios."""

from rest_framework.routers import SimpleRouter

from .views import ResidentViewSet

app_name = "cu05_residentes"

router = SimpleRouter()
router.register("residents", ResidentViewSet, basename="resident")

urlpatterns = router.urls
