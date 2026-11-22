from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AreaViewSet, ReservationViewSet, ResidentOptionsViewSet

router = DefaultRouter()
router.register("areas", AreaViewSet, basename="cu27-area")
router.register("reservations", ReservationViewSet, basename="cu27-reservation")
router.register("residents", ResidentOptionsViewSet, basename="cu27-resident")

urlpatterns = [path("", include(router.urls))]
