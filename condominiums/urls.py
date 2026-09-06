from rest_framework.routers import SimpleRouter
from .views import ResidentDirectoryViewSet, CondominiumViewSet, ResidentViewSet, ResidentUnitViewSet, SectorViewSet, StaffViewSet, UnitViewSet

router = SimpleRouter()
router.register("condominiums", CondominiumViewSet, basename="condominium")
router.register("staff", StaffViewSet, basename="staff")
router.register("residents", ResidentViewSet, basename="resident")
router.register("sectors", SectorViewSet, basename="sector")
router.register("units", UnitViewSet, basename="unit")
router.register("resident-units", ResidentUnitViewSet, basename="resident-unit")
router.register("resident-directory", ResidentDirectoryViewSet, basename="resident-directory")
urlpatterns = router.urls
