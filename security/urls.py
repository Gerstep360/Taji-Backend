from rest_framework.routers import SimpleRouter

from security.views import AccessEventViewSet

app_name = "security"

router = SimpleRouter()
router.register("access-events", AccessEventViewSet, basename="access-event")

urlpatterns = router.urls
