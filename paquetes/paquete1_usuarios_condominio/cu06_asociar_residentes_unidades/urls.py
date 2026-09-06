from rest_framework.routers import SimpleRouter
from .views import ResidentUnitViewSet, ResidentDirectoryViewSet

router = SimpleRouter()
router.register("resident-units", ResidentUnitViewSet, basename="resident-unit")
router.register("resident-directory", ResidentDirectoryViewSet, basename="resident-directory")
urlpatterns = router.urls
