from rest_framework.routers import SimpleRouter

from .views import ResidentDirectoryViewSet, ResidentUnitViewSet, SectorViewSet, StaffViewSet, UnitViewSet


router = SimpleRouter()
router.register("staff", StaffViewSet, basename="staff")
router.register("sectors", SectorViewSet, basename="sector")
router.register("units", UnitViewSet, basename="unit")
router.register("residents", ResidentDirectoryViewSet, basename="resident")
router.register("resident-units", ResidentUnitViewSet, basename="resident-unit")

urlpatterns = router.urls
