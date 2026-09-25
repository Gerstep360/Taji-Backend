"""Rutas para CU08: Registrar y autorizar visitantes."""

from rest_framework.routers import SimpleRouter

from .views import VisitAuthorizationViewSet

router = SimpleRouter()
router.register("visit-authorizations", VisitAuthorizationViewSet, basename="visit-authorization")

urlpatterns = router.urls
