from rest_framework.routers import DefaultRouter
from .views import HandoverViewSet
router = DefaultRouter()
router.register("entregas-turno", HandoverViewSet, basename="shift-handover")
urlpatterns = router.urls
