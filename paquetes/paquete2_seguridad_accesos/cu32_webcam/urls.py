from django.urls import path

from .views import PlateLookupView, PlateReadView

urlpatterns = [
    path("plate/lookup/", PlateLookupView.as_view(), name="cu32-plate-lookup"),
    path("plate/read/", PlateReadView.as_view(), name="cu32-plate-read"),
]
