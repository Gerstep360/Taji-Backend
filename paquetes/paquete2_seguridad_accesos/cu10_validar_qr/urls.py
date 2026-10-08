"""Rutas para CU10: Validar la autorización de visitante mediante QR."""

from django.urls import path

from .views import (
    VisitQrScanGuardsView,
    VisitQrScanHistoryView,
    VisitQrValidationReasonsView,
    VisitQrValidationView,
)

urlpatterns = [
    path("visit-qr/validate/", VisitQrValidationView.as_view(), name="visit-qr-validate"),
    path(
        "visit-qr/validate/reasons/",
        VisitQrValidationReasonsView.as_view(),
        name="visit-qr-validation-reasons",
    ),
    # El historial se declara antes que `visit-qr/` para no competir con el
    # patrón numérico del router de CU09.
    path("visit-qr/scans/", VisitQrScanHistoryView.as_view(), name="visit-qr-scan-history"),
    path("visit-qr/scans/guards/", VisitQrScanGuardsView.as_view(), name="visit-qr-scan-guards"),
]