from django.urls import re_path

from .views import Records

kind = r"(?P<kind>warranties|quotes|inspections)"
urlpatterns = [
    re_path(rf"^{kind}/$", Records.as_view({"get": "list", "post": "create"}), name="operations-records"),
    re_path(rf"^{kind}/(?P<pk>[0-9]+)/$", Records.as_view({
        "get": "retrieve", "put": "update", "delete": "destroy",
    }), name="operations-record"),
    re_path(rf"^{kind}/analyze/$", Records.as_view({"post": "analyze"}), name="operations-analysis"),
]
