from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CondominiumViewSet, StaffViewSet

app_name = "condominiums"

router = DefaultRouter()
router.register(r"condominiums", CondominiumViewSet, basename="condominium")
router.register(r"staff", StaffViewSet, basename="staff")

urlpatterns = [
    path("", include(router.urls)),
]