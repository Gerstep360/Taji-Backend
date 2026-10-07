"""Definición de rutas URL para CU13: Turnos de seguridad."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SecurityShiftViewSet

router = DefaultRouter()
router.register(r"turnos", SecurityShiftViewSet, basename="turnos-seguridad")
router.register(r"shifts", SecurityShiftViewSet, basename="security-shifts")

urlpatterns = [
    path("", include(router.urls)),
]
