"""Rutas para CU10: Validar la autorización de visitante mediante QR."""

from django.urls import path

from .views import VisitQrValidationReasonsView, VisitQrValidationView

urlpatterns = [
    path("visit-qr/validate/", VisitQrValidationView.as_view(), name="visit-qr-validate"),
    path(
        "visit-qr/validate/reasons/",
        VisitQrValidationReasonsView.as_view(),
        name="visit-qr-validation-reasons",
    ),
]