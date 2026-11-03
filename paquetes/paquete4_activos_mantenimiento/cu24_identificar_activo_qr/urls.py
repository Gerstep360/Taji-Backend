from django.urls import path
from .views import QRScanView

urlpatterns = [
    path("", QRScanView.as_view(), name="qr-scan"),
]
