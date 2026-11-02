"""Vistas para CU18: Registrar incidencia."""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.services import record_audit_event
from incidents.models import Incident, IncidentCategory, PriorityLevel
from tenancy.context import TenantContext

from . import services
from .permissions import CanReportIncidents, has_full_unit_scope
from .serializers import (
    AssetOptionSerializer,
    IncidentCategorySerializer,
    IncidentCreateSerializer,
    IncidentSerializer,
    PriorityLevelSerializer,
    SectorOptionSerializer,
    UnitOptionSerializer,
)

TAG = "Incidencias - Registro"


@extend_schema_view(
    create=extend_schema(
        tags=[TAG],
        summary="Registrar incidencia",
        description=(
            "Registra una incidencia en el condominio activo con estado REPORTED (Reportada). "
            "Acepta multipart/form-data con evidencias repetidas en el campo `evidences` "
            "(jpg, jpeg, png, webp o pdf). El servidor fija condominio, reportante, código, "
            "estado y prioridad inicial; la operación es atómica."
        ),
        request={"multipart/form-data": IncidentCreateSerializer, "application/json": IncidentCreateSerializer},
        responses={status.HTTP_201_CREATED: IncidentSerializer},
    ),
)
@method_decorator(never_cache, name="dispatch")
class IncidentReportViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    Controlador para CU18 / T031-T033:
    - Catálogos de categorías y prioridades servidos por el backend.
    - Opciones del formulario limitadas al condominio y al usuario.
    - Registro atómico de la incidencia con sus evidencias.
    """

    serializer_class = IncidentCreateSerializer
    permission_classes = [IsAuthenticated, CanReportIncidents]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Incident.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["condominium"] = TenantContext.get_current_tenant()
        context["full_unit_scope"] = has_full_unit_scope(self.request)
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        condominium = serializer.context["condominium"]
        data = dict(serializer.validated_data)
        evidences = data.pop("evidences", [])
        incident = services.create_incident(
            condominium=condominium,
            reporter=request.user,
            reporter_resident=services.reporter_resident_for(condominium, request.user),
            validated_data=data,
            evidences=evidences,
        )
        incident = (
            Incident.objects.select_related("category", "priority", "sector", "unit", "asset", "reporter_user__person")
            .prefetch_related("attachments")
            .get(pk=incident.pk)
        )
        record_audit_event(
            action_code="INCIDENT_REPORTED",
            resource_type="Incident",
            resource_id=incident.pk,
            description=f"Incidencia {incident.public_code} registrada.",
            actor_user=request.user,
            after_data={
                "incident_id": incident.pk,
                "public_code": incident.public_code,
                "condominium_id": incident.condominium_id,
                "category": incident.category.code,
                "priority": incident.priority.code if incident.priority else None,
                "sector_id": incident.sector_id,
                "unit_id": incident.unit_id,
                "asset_id": incident.asset_id,
                "evidences": len(evidences),
                "status": incident.status,
            },
            request=request,
        )
        return Response(IncidentSerializer(incident).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=[TAG],
        summary="Catálogo de categorías de incidencia",
        description="Categorías activas con la prioridad inicial que el servidor asigna a cada una.",
        responses={status.HTTP_200_OK: IncidentCategorySerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="categories")
    def categories(self, request):
        return Response(IncidentCategorySerializer(self._categories(), many=True).data)

    @extend_schema(
        tags=[TAG],
        summary="Catálogo de niveles de prioridad",
        responses={status.HTTP_200_OK: PriorityLevelSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="priorities")
    def priorities(self, request):
        return Response(PriorityLevelSerializer(self._priorities(), many=True).data)

    @extend_schema(
        tags=[TAG],
        summary="Opciones del formulario de registro de incidencia",
        description=(
            "Catálogos, ubicaciones (sectores), unidades y activos que el usuario actual puede "
            "vincular en el condominio activo, junto con las reglas de evidencias."
        ),
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        condominium = TenantContext.get_current_tenant()
        units = services.selectable_units(condominium, request.user, has_full_unit_scope(request))
        return Response(
            {
                "categories": IncidentCategorySerializer(self._categories(), many=True).data,
                "priorities": PriorityLevelSerializer(self._priorities(), many=True).data,
                "sectors": SectorOptionSerializer(services.tenant_sectors(condominium), many=True).data,
                "units": UnitOptionSerializer(units, many=True).data,
                "assets": AssetOptionSerializer(services.tenant_assets(condominium), many=True).data,
                "evidence_rules": services.evidence_rules(),
            }
        )

    @staticmethod
    def _categories():
        return IncidentCategory.objects.filter(is_active=True).order_by("name")

    @staticmethod
    def _priorities():
        return PriorityLevel.objects.filter(is_active=True).order_by("rank")
