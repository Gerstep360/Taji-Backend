from django.urls import path

from .views import AuditEventListView

app_name = "auditlog"

urlpatterns = [
    path("", AuditEventListView.as_view(), name="audit-list"),
]
