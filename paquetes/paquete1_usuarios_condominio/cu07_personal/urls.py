"""Rutas para CU07: Gestionar personal del condominio."""

from rest_framework.routers import SimpleRouter

from .views import StaffViewSet

app_name = "cu07_personal"

router = SimpleRouter()
router.register("staff", StaffViewSet, basename="staff")

urlpatterns = router.urls
