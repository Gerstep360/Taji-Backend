from rest_framework.routers import DefaultRouter
from .views import ShiftLogViewSet

router = DefaultRouter()
router.register("novedades-turno", ShiftLogViewSet, basename="shift-log")
urlpatterns = router.urls
