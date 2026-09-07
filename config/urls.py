from pathlib import Path
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health_check(_request):
    return JsonResponse({"status": "ok", "service": "taji-api"})


def download_mobile_apk(_request):
    apk_path = Path(__file__).resolve().parent.parent / "downloads" / "taji-1.0.apk"
    if not apk_path.exists():
        raise Http404("El archivo APK no está disponible para descarga.")
    return FileResponse(open(apk_path, "rb"), as_attachment=True, filename="taji-v1.0.apk")


def api_not_found(_request, _path):
    return JsonResponse(
        {
            "error": {
                "code": "not_found",
                "message": "No se encontró el recurso solicitado.",
            }
        },
        status=404,
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", health_check, name="health"),
    path("api/v1/download/apk/", download_mobile_apk, name="download-apk"),
    path("downloads/taji.apk", download_mobile_apk, name="download-apk-direct"),
    path("api/v1/paquete1/", include("paquetes.paquete1_usuarios_condominio.urls")),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/roles/", include("paquetes.paquete1_usuarios_condominio.cu02_roles_permisos.urls")),
    path("api/v1/", include("condominiums.urls")),
    path("api/v1/openapi/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="openapi-schema"),
        name="swagger-ui",
    ),
    # Alias conservados para no romper enlaces creados durante el MVP.
    path("api/schema/", SpectacularAPIView.as_view(), name="legacy-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="legacy-schema"),
        name="legacy-swagger-ui",
    ),
    path("api/<path:_path>", api_not_found, name="api-not-found"),
]