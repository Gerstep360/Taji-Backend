from rest_framework.routers import SimpleRouter
from .views import DeviceTokenViewSet, NotificationViewSet

router = SimpleRouter()
router.register("devices", DeviceTokenViewSet, basename="notification-devices")
router.register("", NotificationViewSet, basename="user-notifications")

urlpatterns = router.urls
