from django.urls import path

from .views import PlateLookupView, PlateReadView
from .visual_views import (VisionSettingsView, VisualDetailView, VisualEvidenceView, VisualHistoryView,
                           VisualReviewView, VisualSessionStartView, VisualSessionStopView, VisualWindowView)

urlpatterns = [
    path("plate/lookup/", PlateLookupView.as_view(), name="cu32-plate-lookup"),
    path("plate/read/", PlateReadView.as_view(), name="cu32-plate-read"),
    path('vision/settings/', VisionSettingsView.as_view(), name='cu32-vision-settings'),
    path('vision/sessions/', VisualSessionStartView.as_view(), name='cu32-vision-start'),
    path('vision/sessions/<uuid:pk>/stop/', VisualSessionStopView.as_view(), name='cu32-vision-stop'),
    path('vision/sessions/<uuid:pk>/windows/', VisualWindowView.as_view(), name='cu32-vision-window'),
    path('vision/observations/', VisualHistoryView.as_view(), name='cu32-vision-history'),
    path('vision/observations/<uuid:pk>/', VisualDetailView.as_view(), name='cu32-vision-detail'),
    path('vision/observations/<uuid:pk>/evidence/', VisualEvidenceView.as_view(), name='cu32-vision-evidence'),
    path('vision/observations/<uuid:pk>/review/', VisualReviewView.as_view(), name='cu32-vision-review'),
]
