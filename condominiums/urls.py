from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import CondominiumViewSet, ResidentViewSet, StaffViewSet

app_name = "condominiums"
router = DefaultRouter()
router.register("condominiums", CondominiumViewSet, basename="condominium")
router.register("staff", StaffViewSet, basename="staff")
router.register("residents", ResidentViewSet, basename="resident")
urlpatterns = [path("", include(router.urls))]
