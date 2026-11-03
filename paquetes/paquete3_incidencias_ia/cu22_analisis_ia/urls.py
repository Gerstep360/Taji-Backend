from django.urls import path
from .views import (IncidentAIView, IncidentAIReviewView, IncidentAICatalogView,
                    IncidentAICatalogWriteView, IncidentAICatalogUpdateView, IncidentAIMetricsView)

urlpatterns = [
    path('incident-ai/catalogs/', IncidentAICatalogView.as_view(), name='incident-ai-catalogs'),
    path('incident-ai/catalogs/<str:kind>/', IncidentAICatalogWriteView.as_view()),
    path('incident-ai/catalogs/<str:kind>/<int:pk>/', IncidentAICatalogUpdateView.as_view()),
    path('incident-ai/metrics/', IncidentAIMetricsView.as_view()),
    path('incidents/<str:public_code>/ai/', IncidentAIView.as_view(), name='incident-ai'),
    path('incidents/<str:public_code>/ai/<int:analysis_id>/review/', IncidentAIReviewView.as_view(), name='incident-ai-review'),
]
