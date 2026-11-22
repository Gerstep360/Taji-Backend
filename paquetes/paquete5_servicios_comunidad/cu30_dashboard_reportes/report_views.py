from math import ceil
import re
from types import SimpleNamespace

from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from auditlog.views import CanViewAuditLog
from paquetes.paquete6_reportes_analitica.cu31_reportes.exports import export_csv, export_pdf
from reports.exports import export_html, export_xlsx
from reports.service import rows_for
from tenancy.context import TenantContext

from .report_catalog import SOURCES
from .report_queries import EXPORT_LIMITS, FORMATS, ReportExportQuery, ReportQuery, prepare_report, tenant_zone
from .views import CanConsultDashboard


EXPORTERS = {"csv": export_csv, "xlsx": export_xlsx, "html": export_html, "pdf": export_pdf}
FORMULA_PREFIX = re.compile(r"^[\s\x00-\x1f\x7f\ufeff]*[=+\-@＝＋－＠]")


def csv_text(value):
    if isinstance(value, str) and value:
        if value.startswith(("\t", "\r", "\n", "\ufeff")) or FORMULA_PREFIX.match(value):
            return "'" + value
    return value


class ReportPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    timezone = serializers.CharField()


class ReportPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    pages = serializers.IntegerField()


class ReportChoiceSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class ReportColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    type = serializers.CharField()
    operators = serializers.ListField(child=serializers.CharField())
    choices = ReportChoiceSerializer(many=True)


class ReportSourceSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    date_field = serializers.CharField()
    permissions_any = serializers.ListField(child=serializers.CharField())
    columns = ReportColumnSerializer(many=True)
    default_columns = serializers.ListField(child=serializers.CharField())
    sortable = serializers.ListField(child=serializers.CharField())
    default_ordering = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    formats = serializers.ListField(child=serializers.ChoiceField(choices=FORMATS))


class ReportContextSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["condominium"])
    id = serializers.IntegerField()
    name = serializers.CharField()
    timezone = serializers.CharField()


class ReportCatalogSerializer(serializers.Serializer):
    context = ReportContextSerializer()
    formats = serializers.ListField(child=serializers.ChoiceField(choices=FORMATS))
    export_limits = serializers.DictField(child=serializers.IntegerField())
    sources = ReportSourceSerializer(many=True)


class ReportPreviewSerializer(serializers.Serializer):
    source = serializers.CharField()
    title = serializers.CharField()
    columns = ReportColumnSerializer(many=True)
    period = ReportPeriodSerializer()
    rows = serializers.ListField(child=serializers.ListField(child=serializers.JSONField()))
    pagination = ReportPaginationSerializer()
    can_export = serializers.DictField(child=serializers.BooleanField())


class TenantReportView(APIView):
    permission_classes = [IsAuthenticated, CanConsultDashboard]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def authorized_sources(self):
        if self.request.user.is_superuser:
            return SOURCES
        role = TenantContext.get_current_membership().role
        granted = set(role.permissions.filter(is_active=True).values_list("code", flat=True))
        if "view_reports" not in granted:
            raise PermissionDenied("No tienes acceso a reportes operativos en este contexto.")
        return {
            key: source for key, source in SOURCES.items()
            if granted.intersection(source.permissions)
            and (key != "audit_events" or CanViewAuditLog().has_permission(self.request, self))
        }

    def query(self, serializer_class):
        authorized = self.authorized_sources()
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = authorized.get(data["source"])
        if source is None:
            raise PermissionDenied("No tienes acceso a esa fuente en este contexto.")
        tenant = TenantContext.get_current_tenant()
        queryset, columns, period = prepare_report(data, source, tenant)
        return data, queryset, columns, period, tenant, data["title"] or source.label


class ReportCatalogView(TenantReportView):
    @extend_schema(responses=ReportCatalogSerializer, tags=["CU30 - Reportes"])
    def get(self, request):
        tenant = TenantContext.get_current_tenant()
        payload = {
            "context": {"mode": "condominium", "id": tenant.pk, "name": tenant.name, "timezone": str(tenant_zone(tenant))},
            "formats": FORMATS, "export_limits": EXPORT_LIMITS,
            "sources": [source.public(key, FORMATS) for key, source in self.authorized_sources().items()],
        }
        return Response(ReportCatalogSerializer(payload).data)


class ReportPreviewView(TenantReportView):
    @extend_schema(request=ReportQuery, responses=ReportPreviewSerializer, tags=["CU30 - Reportes"])
    def post(self, request):
        data, queryset, columns, period, _, title = self.query(ReportQuery)
        total = queryset.count()
        page, size = data["page"], data["page_size"]
        start = (page - 1) * size
        rows = rows_for(queryset[start:start + size], columns, SimpleNamespace(timezone=period["timezone"]))
        payload = {
            "source": data["source"], "title": title, "period": period,
            "columns": [column.public() for column in columns], "rows": list(rows),
            "pagination": {"page": page, "page_size": size, "total": total, "pages": max(1, ceil(total / size))},
            "can_export": {fmt: total <= limit for fmt, limit in EXPORT_LIMITS.items()},
        }
        return Response(ReportPreviewSerializer(payload).data)


class ReportExportView(TenantReportView):
    @extend_schema(request=ReportExportQuery, responses={
        (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
        (200, "text/csv"): OpenApiTypes.BINARY,
        (200, "text/html"): OpenApiTypes.BINARY,
        (200, "application/pdf"): OpenApiTypes.BINARY,
    }, tags=["CU30 - Reportes"])
    def post(self, request):
        data, queryset, columns, period, tenant, title = self.query(ReportExportQuery)
        fmt = data["format"]
        limit = EXPORT_LIMITS[fmt]
        rows = list(rows_for(queryset[:limit + 1], columns, SimpleNamespace(timezone=period["timezone"])))
        if len(rows) > limit:
            raise ValidationError({"format": f"La exportación admite hasta {limit} filas. Reduce el período o aplica filtros."})
        if fmt == "csv":
            rows = ([csv_text(value) for value in row] for row in rows)
        description = f'Período: {period["date_from"]} al {period["date_to"]} ({period["timezone"]}).'
        with timezone.override(tenant_zone(tenant)):
            response = EXPORTERS[fmt](title, columns, rows, tenant, description)
        if fmt == "html":
            response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        response["Content-Disposition"] = f'attachment; filename="cu30-{data["source"]}.{fmt}"'
        return response
