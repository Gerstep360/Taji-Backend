from django.urls import path
from .views import VisitConsultationView

urlpatterns = [path("visits/", VisitConsultationView.as_view(), name="cu12-visits")]
