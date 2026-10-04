"""Rutas para CU09: Generar y consultar el QR temporal de visita."""

from rest_framework.routers import SimpleRouter

from .views import VisitQrViewSet

router = SimpleRouter()
router.register("visit-qr", VisitQrViewSet, basename="visit-qr")

urlpatterns = router.urls