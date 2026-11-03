from rest_framework.routers import SimpleRouter
from django.urls import path
from .api import MobileAuditView, CondominiumViewSet
from .api import CommonAreaViewSet, ReservationViewSet, AnnouncementViewSet, AssemblyViewSet, AgreementViewSet
router = SimpleRouter()
router.register('condominium', CondominiumViewSet, basename='community-condominium')
router.register('areas', CommonAreaViewSet, basename='community-area')
router.register('reservations', ReservationViewSet, basename='community-reservation')
router.register('announcements', AnnouncementViewSet, basename='community-announcement')
router.register('assemblies', AssemblyViewSet, basename='community-assembly')
router.register('agreements', AgreementViewSet, basename='community-agreement')
urlpatterns = [path('audit/', MobileAuditView.as_view(), name='community-audit')] + router.urls
