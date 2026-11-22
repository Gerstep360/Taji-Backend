from rest_framework.routers import SimpleRouter
from .views import AnnouncementViewSet, DeviceTokenViewSet, NotificationViewSet

router = SimpleRouter()
router.register("announcements", AnnouncementViewSet, basename="cu28-announcement")
router.register("devices", DeviceTokenViewSet, basename="cu28-device")
router.register("notifications", NotificationViewSet, basename="cu28-notification")

urlpatterns = router.urls
