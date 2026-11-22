"""Vistas para CU19: Consultar seguimiento e historial de incidencia.

Representa el ControladorIncidencia del diagrama UML, exponiendo:
- Tablero de incidencias con filtros y cálculo de SLA (pendientes/vencidas).
- Detalle completo de incidencia con seguimiento e historial.
- T034: Historial de estados y transición de estados.
- T037: Comentarios públicos e internos con control de acceso por rol.
- T038: Fechas objetivo y métricas del tablero.
"""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from incidents.models import Incident, IncidentAttachment
from .permissions import CanAccessIncidentTracking
from .serializers import (
    ChangeStatusRequestSerializer,
    CreateAttachmentRequestSerializer,
    CreateCommentRequestSerializer,
    IncidentAttachmentSerializer,
    IncidentCommentSerializer,
    IncidentDetailSerializer,
    IncidentFilterQuerySerializer,
    IncidentListSerializer,
    IncidentStatusHistorySerializer,
    SetTargetDateRequestSerializer,
)
from .services import IncidentTrackingService
from drf_spectacular.types import OpenApiTypes
from condominiums.models import Staff
from .permissions import is_admin_user
from paquetes.paquete3_incidencias_ia.cu21_ciclo_atencion.services import (
    allowed_transitions, assign_incident, attention_alerts,
)
from paquetes.paquete3_incidencias_ia.cu21_ciclo_atencion.serializers import (
    AssignmentRequestSerializer, AttentionAlertSerializer, AssigneeOptionSerializer,
    TransitionOptionSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Tablero de incidencias con filtros y SLA (Paso 1-14)",
        parameters=[IncidentFilterQuerySerializer],
    ),
    retrieve=extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Consultar detalle, seguimiento e historial completo (Paso 16-41)",
    ),
)
@method_decorator(never_cache, name="dispatch")
class IncidentTrackingViewSet(viewsets.GenericViewSet):
    """Controlador REST para consulta, seguimiento e historial de incidencias."""

    permission_classes = [IsAuthenticated, CanAccessIncidentTracking]
    lookup_field = "public_code"
    lookup_url_kwarg = "public_code"
    lookup_value_regex = r"[^/]+"

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>\d+)/download")
    def download_attachment(self, request, public_code=None, attachment_id=None):
        from django.core.files.storage import default_storage
        from django.http import FileResponse, Http404
        from pathlib import PurePosixPath
        incident = self.get_object()
        attachment = incident.attachments.filter(pk=attachment_id).first()
        if not attachment or not default_storage.exists(attachment.file_path):
            raise Http404("La evidencia no está disponible.")
        response = FileResponse(default_storage.open(attachment.file_path, "rb"), as_attachment=True,
                                filename=PurePosixPath(attachment.file_path).name)
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(responses={(200, 'image/jpeg'): OpenApiTypes.BINARY, (200, 'image/png'): OpenApiTypes.BINARY, (200, 'image/webp'): OpenApiTypes.BINARY})
    @action(detail=True, methods=['get'], url_path=r'attachments/(?P<attachment_id>\d+)/preview')
    def preview_attachment(self, request, public_code=None, attachment_id=None):
        from pathlib import PurePosixPath
        from django.core.files.storage import default_storage
        from django.http import FileResponse, Http404
        from PIL import Image
        incident = self.get_object()
        attachment = incident.attachments.filter(pk=attachment_id, file_type='IMAGE').first()
        prefix = f'incidents/{incident.condominium_id}/{incident.pk}/'
        if (not attachment or not attachment.file_path.startswith(prefix) or '..' in attachment.file_path.split('/')
                or '\\' in attachment.file_path):
            raise Http404('La imagen no está disponible.')
        try:
            with default_storage.open(attachment.file_path, 'rb') as source:
                with Image.open(source) as image:
                    mime = {'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}.get(image.format)
                    if image.width * image.height > 20000000:
                        raise Http404('La imagen supera el límite de dimensiones de vista previa.')
            if not mime:
                raise Http404('Formato de imagen no compatible.')
            response = FileResponse(default_storage.open(attachment.file_path, 'rb'), as_attachment=False,
                filename=PurePosixPath(attachment.file_path).name, content_type=mime)
        except (OSError, ValueError, Image.DecompressionBombError):
            raise Http404('La imagen no está disponible.') from None
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response

    @extend_schema(responses=AttentionAlertSerializer(many=True), filters=False)
    @action(detail=False, methods=["get"], pagination_class=None)
    def alerts(self, request):
        return Response(attention_alerts(request.user))

    @extend_schema(responses=AssigneeOptionSerializer(many=True), filters=False)
    @action(detail=False, methods=["get"], pagination_class=None)
    def assignees(self, request):
        if not is_admin_user(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        tenant_id = IncidentTrackingService.get_user_condominium_id(request.user)
        rows = Staff.objects.filter(condominium_id=tenant_id, status="ACTIVE").select_related("person") if tenant_id else Staff.objects.none()
        return Response([{"id": row.pk, "name": row.person.full_name} for row in rows])

    @extend_schema(responses=TransitionOptionSerializer(many=True), filters=False)
    @action(detail=True, methods=["get"])
    def transitions(self, request, public_code=None):
        return Response(allowed_transitions(self.get_object(), request.user))

    @extend_schema(request=AssignmentRequestSerializer, responses=IncidentDetailSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, public_code=None):
        data = AssignmentRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        incident = assign_incident(self.get_object(), request.user, request=request, **data.validated_data)
        return Response(IncidentDetailSerializer(incident, context={"request": request}).data)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return IncidentDetailSerializer
        if self.action == "change_status":
            return ChangeStatusRequestSerializer
        if self.action == "set_target_date":
            return SetTargetDateRequestSerializer
        if self.action == "comments" and self.request.method == "POST":
            return CreateCommentRequestSerializer
        if self.action == "attachments" and self.request.method == "POST":
            return CreateAttachmentRequestSerializer
        return IncidentListSerializer

    def get_object(self) -> Incident:
        lookup_val = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        return IncidentTrackingService.get_incident_detail(lookup_val, user=self.request.user)

    def list(self, request, *args, **kwargs):
        """Paso 1-14: Listar incidencias en el tablero según el rol y filtros."""
        query_serializer = IncidentFilterQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        queryset = IncidentTrackingService.list_incidents(
            user=request.user,
            filters=query_serializer.validated_data,
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = IncidentListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = IncidentListSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """Paso 16-41: Obtener detalle completo de la incidencia (DetalleIncidenciaDTO)."""
        incident = self.get_object()
        serializer = IncidentDetailSerializer(incident, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Métricas del tablero (pendientes, vencidas, a tiempo, etc. - T038 / Paso 12)",
    )
    @action(detail=False, methods=["get"], url_path="board-summary")
    def board_summary(self, request):
        """T038 / Paso 12: Métricas globales o filtradas para el tablero de incidencias."""
        query_serializer = IncidentFilterQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        queryset = IncidentTrackingService.list_incidents(
            user=request.user,
            filters=query_serializer.validated_data,
        )
        metrics = IncidentTrackingService.calculate_board_metrics(
            queryset=queryset,
            user=request.user,
        )
        return Response(metrics, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Historial completo de estados de la incidencia (T034 / Paso 23-24)",
        responses={200: IncidentStatusHistorySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, public_code=None):
        """T034: Consulta el historial de estados de la incidencia."""
        incident = self.get_object()
        history_qs = IncidentTrackingService.list_status_history(incident)
        serializer = IncidentStatusHistorySerializer(history_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Cambiar estado de incidencia con registro de historial (T034)",
        request=ChangeStatusRequestSerializer,
        responses={200: IncidentDetailSerializer},
    )
    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, public_code=None):
        """T034: Cambia el estado de una incidencia y registra el cambio en el historial."""
        incident = self.get_object()
        serializer = ChangeStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["status"]
        comment = serializer.validated_data.get("comment", "")

        incident, history_entry = IncidentTrackingService.change_status(
            incident=incident,
            new_status=new_status,
            user=request.user,
            comment=comment,
            request=request,
        )

        detail_serializer = IncidentDetailSerializer(incident, context={"request": request})
        return Response(
            {
                "message": f"Estado actualizado a {incident.get_status_display()}.",
                "incident": detail_serializer.data,
                "history_id": history_entry.id,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Consultar o agregar comentarios públicos e internos (T037 / Pasos 27-28 y 42-49)",
    )
    @action(detail=True, methods=["get", "post"], url_path="comments")
    def comments(self, request, public_code=None):
        """T037: Listar o crear comentarios públicos e internos."""
        incident = self.get_object()

        if request.method == "POST":
            serializer = CreateCommentRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            comment = IncidentTrackingService.add_comment(
                incident=incident,
                user=request.user,
                body=serializer.validated_data["body"],
                visibility=serializer.validated_data.get("visibility", "PUBLIC"),
                request=request,
            )
            return Response(
                IncidentCommentSerializer(comment).data,
                status=status.HTTP_201_CREATED,
            )

        visibility = request.query_params.get("visibility")
        comments_qs = IncidentTrackingService.list_comments(
            incident=incident,
            user=request.user,
            visibility=visibility,
        )
        serializer = IncidentCommentSerializer(comments_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Establecer o reprogramar fecha objetivo (due_at) y SLA (T038)",
        request=SetTargetDateRequestSerializer,
        responses={200: IncidentDetailSerializer},
    )
    @action(detail=True, methods=["post"], url_path="set-target-date")
    def set_target_date(self, request, public_code=None):
        """T038: Define o actualiza la fecha objetivo (due_at) o minutos objetivo."""
        incident = self.get_object()
        serializer = SetTargetDateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        due_at = serializer.validated_data.get("due_at")
        target_minutes = serializer.validated_data.get("target_minutes")

        incident = IncidentTrackingService.set_target_date(
            incident=incident,
            user=request.user,
            due_at=due_at,
            target_minutes=target_minutes,
            request=request,
        )

        detail_serializer = IncidentDetailSerializer(incident, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Incidencias - CU19 Seguimiento e Historial"],
        summary="Consultar o agregar evidencias/adjuntos de la incidencia (Paso 29-30)",
    )
    @action(detail=True, methods=["get", "post"], url_path="attachments")
    def attachments(self, request, public_code=None):
        """Listar o registrar evidencias adjuntas de la incidencia."""
        incident = self.get_object()

        if request.method == "POST":
            serializer = CreateAttachmentRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            from pathlib import PurePosixPath
            from rest_framework.exceptions import ValidationError
            file_path = serializer.validated_data["file_path"]
            prefix = f"incidents/{incident.condominium_id}/{incident.pk}/"
            if not file_path.startswith(prefix) or ".." in PurePosixPath(file_path).parts or "\\" in file_path:
                raise ValidationError({"file_path": "La evidencia debe pertenecer a esta incidencia."})

            attachment = IncidentAttachment.objects.create(
                incident=incident,
                uploaded_by_user=request.user,
                file_path=serializer.validated_data["file_path"],
                file_type=serializer.validated_data.get("file_type", IncidentAttachment.Type.IMAGE),
                caption=serializer.validated_data.get("caption", ""),
            )
            return Response(
                IncidentAttachmentSerializer(attachment).data,
                status=status.HTTP_201_CREATED,
            )

        attachments_qs = incident.attachments.select_related("uploaded_by_user__person").order_by("created_at")
        serializer = IncidentAttachmentSerializer(attachments_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

