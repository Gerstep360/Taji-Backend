from rest_framework.routers import SimpleRouter

from .views import ResidentViewSet, StaffViewSet


router = SimpleRouter()
router.register("staff", StaffViewSet, basename="staff")
router.register("residents", ResidentViewSet, basename="resident")

urlpatterns = router.urls
