from django.urls import path

from .views import CatalogView, ExportView, PreviewView

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="reports-catalog"),
    path("preview/", PreviewView.as_view(), name="reports-preview"),
    path("export/", ExportView.as_view(), name="reports-export"),
]
