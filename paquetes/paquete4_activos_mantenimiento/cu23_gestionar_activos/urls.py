from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AssetTypeViewSet, AssetViewSet

router = DefaultRouter()
router.register("types", AssetTypeViewSet, basename="asset-type")
router.register("", AssetViewSet, basename="asset")

urlpatterns = [path("", include(router.urls))]
