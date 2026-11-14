from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MaintenanceAssetOptionsViewSet,
    MaintenancePlanViewSet,
    MaintenancePriorityOptionsViewSet,
    MaintenanceStaffOptionsViewSet,
    MaintenanceSupplierViewSet,
    WorkOrderViewSet,
)

router = DefaultRouter()
router.register("orders", WorkOrderViewSet, basename="maintenance-work-order")
router.register("plans", MaintenancePlanViewSet, basename="maintenance-plan")
router.register("suppliers", MaintenanceSupplierViewSet, basename="maintenance-supplier")
router.register(
    "assets",
    MaintenanceAssetOptionsViewSet,
    basename="maintenance-asset-option",
)
router.register(
    "staff",
    MaintenanceStaffOptionsViewSet,
    basename="maintenance-staff-option",
)
router.register(
    "priorities",
    MaintenancePriorityOptionsViewSet,
    basename="maintenance-priority-option",
)

urlpatterns = [path("", include(router.urls))]
