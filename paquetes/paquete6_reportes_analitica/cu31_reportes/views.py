from math import ceil

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle

from tenancy.context import TenantContext

from .catalog import SOURCES
from .exports import export_csv, export_html, export_xlsx
from .serializers import (
    ReportRequestSerializer,
    VoiceNarrateRequestSerializer,
    VoiceQueryRequestSerializer,
)
from .services import EXPORT_LIMIT, VoiceReportService, build_query, rows_for


class CanAccessReports(BasePermission):
    message = "Solo administradores u operadores autorizados del condominio pueden consultar y generar reportes."

    def has_permission(self, request, view):
        tenant = TenantContext.get_current_tenant()
        membership = TenantContext.get_current_membership()
        if not tenant or not tenant.is_active:
            return False
        if request.user.is_superuser:
            return True
        if not membership or membership.user_id != request.user.pk or not membership.is_active:
            return False
        role = getattr(membership, "role", None)
        if not role or not role.is_active:
            return False
        slug = (role.slug or "").lower()
        return slug in ("admin", "administrador", "superadmin", "seguridad", "operador")


class Cu31BaseView(APIView):
    permission_classes = [IsAuthenticated, CanAccessReports]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class TranscriptionThrottle(UserRateThrottle):
    scope = "cu31_transcription"
    rate = "6/min"


class Cu31TranscribeView(Cu31BaseView):
    parser_classes = [MultiPartParser]
    throttle_classes = [TranscriptionThrottle]

    @extend_schema(responses=OpenApiTypes.OBJECT, tags=["CU31 - Reportes"])
    def post(self, request):
        from .transcription import transcribe
        if int(request.META.get("CONTENT_LENGTH") or 0) > 1_150_000:
            raise ValidationError("El audio supera el tamaño permitido. Graba hasta 30 segundos.")
        audio = request.FILES.get("audio_file")
        if audio is None:
            raise ValidationError("Adjunta una grabación de audio.")
        return Response({"text": transcribe(audio)})


class Cu31CatalogView(Cu31BaseView):
    @extend_schema(responses=OpenApiTypes.OBJECT, tags=["CU31 - Reportes"])
    def get(self, request):
        tenant = TenantContext.get_current_tenant()
        voice_suggestions = [
            "Reporte de incidencias pendientes de esta semana",
            "Mostrar residentes activos del condominio",
            "Novedades de seguridad de alta prioridad",
            "Personal de mantenimiento y limpieza en Excel",
            "Turnos de guardia del último mes",
            "Resumen de entrega y relevo de turnos",
        ]

        return Response({
            "cu": "CU31",
            "name": "Generación de Reportes y Consultas Asistidas por Voz",
            "condominium": {"id": tenant.pk, "name": tenant.name},
            "export_limit": EXPORT_LIMIT,
            "formats": ["xlsx", "html", "csv"],
            "voice_enabled": True,
            "voice_suggestions": voice_suggestions,
            "sources": [
                {
                    "key": key,
                    "label": source.label,
                    "description": source.description,
                    "columns": [col.public() for col in source.columns],
                    "default_columns": source.defaults,
                    "default_ordering": [
                        {
                            "field": source.ordering.lstrip("-"),
                            "direction": "desc" if source.ordering.startswith("-") else "asc",
                        }
                    ],
                }
                for key, source in SOURCES.items()
            ],
        })


class Cu31PreviewView(Cu31BaseView):
    @extend_schema(request=ReportRequestSerializer, responses=OpenApiTypes.OBJECT, tags=["CU31 - Reportes"])
    def post(self, request):
        serializer = ReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = TenantContext.get_current_tenant()

        queryset, columns = build_query(data, tenant)
        total = queryset.count()
        start = (data["page"] - 1) * data["page_size"]
        end = start + data["page_size"]

        preview_rows = list(rows_for(queryset[start:end], columns, tenant))

        return Response({
            "title": data["title"] or SOURCES[data["source"]].label,
            "source": data["source"],
            "columns": [col.public() for col in columns],
            "rows": preview_rows,
            "pagination": {
                "page": data["page"],
                "page_size": data["page_size"],
                "total": total,
                "pages": max(1, ceil(total / data["page_size"])),
            },
            "can_export": total <= EXPORT_LIMIT,
        })


class Cu31ExportView(Cu31BaseView):
    @extend_schema(request=ReportRequestSerializer, responses=OpenApiTypes.BINARY, tags=["CU31 - Reportes"])
    def post(self, request):
        serializer = ReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fmt = data.get("format", "xlsx")

        tenant = TenantContext.get_current_tenant()
        queryset, columns = build_query(data, tenant)

        rows = list(rows_for(queryset[: EXPORT_LIMIT + 1], columns, tenant))
        if len(rows) > EXPORT_LIMIT:
            raise ValidationError(
                f"El reporte supera {EXPORT_LIMIT} filas. Aplica más filtros para exportarlo completo."
            )

        source = SOURCES[data["source"]]
        title = data["title"] or source.label
        fields = {col.key: col for col in source.columns}
        filters_desc = [
            f"{fields.get(item['field'], item['field'])} {item['operator']} {item['value']}"
            for item in data.get("filters", [])
        ]
        description = (
            f"Condominio: {tenant.name}. Total registros: {len(rows)}. "
            f"Filtros: {'; '.join(filters_desc) or 'Sin filtros adicionales'}."
        )

        if fmt == "xlsx":
            response = export_xlsx(title, columns, rows, tenant, description)
            extension = "xlsx"
        elif fmt == "csv":
            response = export_csv(title, columns, rows, tenant, description)
            extension = "csv"
        else:
            response = export_html(title, columns, rows, tenant, description)
            extension = "html"

        response["Content-Disposition"] = f'attachment; filename="reporte-{data["source"]}.{extension}"'
        return response


class Cu31VoiceQueryView(Cu31BaseView):
    """Endpoint principal de Voz (CU31 / Tarea 2).
    
    Recibe la transcripción o comando de voz del usuario (dictado por micrófono),
    interpreta la intención y los filtros mediante el servicio inteligente,
    ejecuta la consulta con aislamiento de inquilino y responde los datos tabulares
    junto con la narración de síntesis auditiva en español.
    """
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(request=VoiceQueryRequestSerializer, responses=OpenApiTypes.OBJECT, tags=["CU31 - Reportes"])
    def post(self, request):
        serializer = VoiceQueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        voice_text = data.get("voice_text", "")
        audio_file = data.get("audio_file")
        if audio_file and not voice_text:
            raise ValidationError("Primero transcribe el audio mediante /api/v1/cu31/transcribe/ y revisa el texto.")

        tenant = TenantContext.get_current_tenant()

        # 1. Interpretación inteligente de la consulta de voz
        parsed_query = VoiceReportService.parse_voice_query(voice_text, tenant)

        # 2. Ejecución segura del reporte con las columnas y filtros detectados
        queryset, columns = build_query(parsed_query, tenant)
        total = queryset.count()
        page_size = 25
        preview_rows = list(rows_for(queryset[:page_size], columns, tenant))

        # 3. Generación del guion hablado (síntesis de voz)
        spoken_summary = VoiceReportService.generate_spoken_narrative(
            source=parsed_query["source"],
            total_count=total,
            filters=parsed_query["filters"],
            tenant_name=tenant.name,
        )

        speech_payload = (
            VoiceReportService.synthesize_speech_payload(spoken_summary)
            if data.get("auto_narrate", True)
            else None
        )

        return Response({
            "status": "success",
            "voice_transcript": voice_text,
            "understood_intent": {
                "source": parsed_query["source"],
                "source_label": SOURCES[parsed_query["source"]].label,
                "detected_filters": parsed_query["filters"],
                "detected_format": parsed_query["format"],
                "title": parsed_query["title"],
            },
            "spoken_summary": spoken_summary,
            # Reutilizar exactamente la consulta interpretada en páginas y exportaciones.
            "report_request": {**{key: parsed_query[key] for key in ("source", "columns", "filters", "ordering", "title")}, "page": 1, "page_size": page_size},
            "speech_payload": speech_payload,
            "report_preview": {
                "title": parsed_query["title"],
                "source": parsed_query["source"],
                "columns": [col.public() for col in columns],
                "rows": preview_rows,
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total": total,
                    "pages": max(1, ceil(total / page_size)),
                },
                "can_export": total <= EXPORT_LIMIT,
            },
        })


class Cu31VoiceNarrateView(Cu31BaseView):
    """Genera la retroalimentación auditiva sintetizada para un reporte."""

    @extend_schema(request=VoiceNarrateRequestSerializer, responses=OpenApiTypes.OBJECT, tags=["CU31 - Reportes"])
    def post(self, request):
        serializer = VoiceNarrateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = TenantContext.get_current_tenant()
        custom = data.get("custom_message")
        if custom:
            narrative = custom
        else:
            narrative = VoiceReportService.generate_spoken_narrative(
                source=data["source"],
                total_count=data["total_count"],
                tenant_name=tenant.name,
            )

        return Response({
            "spoken_summary": narrative,
            "speech_payload": VoiceReportService.synthesize_speech_payload(narrative),
        })

