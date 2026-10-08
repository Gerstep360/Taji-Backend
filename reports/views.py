from math import ceil

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenancy.context import TenantContext

from .catalog import SOURCES
from .exports import export_html, export_xlsx
from .serializers import ReportRequestSerializer
from .service import EXPORT_LIMIT, build_query, rows_for


class CanBuildTenantReports(BasePermission):
    message = "Solo el administrador de un condominio activo puede generar reportes."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        membership = TenantContext.get_current_membership()
        if not tenant or not tenant.is_active:
            return False
        if request.user.is_superuser:
            return True
        return bool(membership and membership.user_id == request.user.pk and membership.is_active
                    and membership.role and membership.role.is_active
                    and membership.role.slug.lower() in ("admin", "administrador", "superadmin"))


class ReportsView(APIView):
    permission_classes = [IsAuthenticated, CanBuildTenantReports]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CatalogView(ReportsView):
    @extend_schema(responses=OpenApiTypes.OBJECT, tags=["Reportes"])
    def get(self, request):
        tenant = TenantContext.get_current_tenant()
        return Response({"condominium": {"id": tenant.pk, "name": tenant.name},
                         "export_limit": EXPORT_LIMIT, "formats": ["xlsx", "html"],
                         "sources": [{"key": key, "label": source.label,
                                      "columns": [column.public() for column in source.columns],
                                      "default_columns": source.defaults,
                                      "default_ordering": [{"field": source.ordering.lstrip("-"),
                                        "direction": "desc" if source.ordering.startswith("-") else "asc"}]}
                                     for key, source in SOURCES.items()]})


class PreviewView(ReportsView):
    @extend_schema(request=ReportRequestSerializer, responses=OpenApiTypes.OBJECT, tags=["Reportes"])
    def post(self, request):
        serializer = ReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = TenantContext.get_current_tenant()
        queryset, columns = build_query(data, tenant)
        total = queryset.count()
        start = (data["page"] - 1) * data["page_size"]
        return Response({"title": data["title"] or SOURCES[data["source"]].label,
                         "columns": [column.public() for column in columns],
                         "rows": list(rows_for(queryset[start:start + data["page_size"]], columns, tenant)),
                         "pagination": {"page": data["page"], "page_size": data["page_size"],
                                        "total": total, "pages": max(1, ceil(total / data["page_size"]))},
                         "can_export": total <= EXPORT_LIMIT})


class ExportView(ReportsView):
    @extend_schema(request=ReportRequestSerializer, responses=OpenApiTypes.BINARY, tags=["Reportes"])
    def post(self, request):
        serializer = ReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "format" not in data:
            raise ValidationError("Selecciona Excel o HTML.")
        tenant = TenantContext.get_current_tenant()
        queryset, columns = build_query(data, tenant)
        # Se limita el conjunto de exportación, no solo la primera página.
        rows = list(rows_for(queryset[:EXPORT_LIMIT + 1], columns, tenant))
        if len(rows) > EXPORT_LIMIT:
            raise ValidationError(f"El reporte supera {EXPORT_LIMIT} filas. Aplica más filtros para exportarlo completo.")
        source = SOURCES[data["source"]]
        title = data["title"] or source.label
        fields = {column.key: column for column in source.columns}
        filters = [f"{fields[item['field']].label} {item['operator']} {item['value']}" for item in data["filters"]]
        ordering = data["ordering"] or [{"field": source.ordering.lstrip("-"),
                                         "direction": "desc" if source.ordering.startswith("-") else "asc"}]
        sort = ", ".join(f"{fields[item['field']].label} ({item['direction']})" for item in ordering)
        description = f"Filas: {len(rows)}. Filtros: {'; '.join(filters) or 'Sin filtros'}. Orden: {sort}."
        export = export_xlsx if data["format"] == "xlsx" else export_html
        response = export(title, columns, rows, tenant, description)
        response["Content-Disposition"] = f'attachment; filename="reporte-{data["source"]}.{data["format"]}"'
        return response
