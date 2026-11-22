from django.urls import path

from .report_views import ReportCatalogView, ReportExportView, ReportPreviewView
from .views import DashboardView

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="cu30-dashboard"),
    path("reports/catalog/", ReportCatalogView.as_view(), name="cu30-reports-catalog"),
    path("reports/preview/", ReportPreviewView.as_view(), name="cu30-reports-preview"),
    path("reports/export/", ReportExportView.as_view(), name="cu30-reports-export"),
]
