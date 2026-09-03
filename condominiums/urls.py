from rest_framework.routers import SimpleRouter

from .views import StaffViewSet


router = SimpleRouter()
router.register("staff", StaffViewSet, basename="staff")

urlpatterns = router.urls
