from rest_framework.routers import SimpleRouter
from .views import CondominiumViewSet

router = SimpleRouter()
router.register("condominiums", CondominiumViewSet, basename="condominium")
urlpatterns = router.urls
