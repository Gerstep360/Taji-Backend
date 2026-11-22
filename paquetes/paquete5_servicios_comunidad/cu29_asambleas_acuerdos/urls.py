from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import AgreementViewSet, AssemblyViewSet

router = SimpleRouter()
router.register("assemblies", AssemblyViewSet, basename="cu29-assembly")
router.register("agreements", AgreementViewSet, basename="cu29-agreement")

urlpatterns = [path("", include(router.urls))]
