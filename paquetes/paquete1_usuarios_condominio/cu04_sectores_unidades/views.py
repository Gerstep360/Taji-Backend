from rest_framework import status, viewsets
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from condominiums.models import Sector, Unit
from paquetes.paquete1_usuarios_condominio.cu04_sectores_unidades.permissions import CanManageUnits
from paquetes.paquete1_usuarios_condominio.cu04_sectores_unidades.serializers import SectorSerializer
from paquetes.paquete1_usuarios_condominio.cu04_sectores_unidades.serializers import UnitSerializer


@extend_schema_view(
    list=extend_schema(tags=["Sectores"], summary="Listar sectores"),
    retrieve=extend_schema(tags=["Sectores"], summary="Consultar sector"),
    create=extend_schema(tags=["Sectores"], summary="Registrar sector"),
    update=extend_schema(tags=["Sectores"], summary="Reemplazar sector"),
    partial_update=extend_schema(tags=["Sectores"], summary="Editar sector"),
    destroy=extend_schema(tags=["Sectores"], summary="Eliminar sector"),
)
@method_decorator(never_cache, name="dispatch")
class SectorViewSet(viewsets.ModelViewSet):
    """T012: estructura física del condominio (sectores/bloques/torres/pisos/zonas)."""

    serializer_class = SectorSerializer
    permission_classes = [IsAuthenticated, CanManageUnits]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("code", "name", "sector_type")
    ordering = ("code",)

    def get_queryset(self):
        queryset = Sector.objects.select_related("parent")
        sector_type = self.request.query_params.get("sector_type", "").strip().upper()
        search = self.request.query_params.get("search", "").strip()

        if sector_type:
            queryset = queryset.filter(sector_type=sector_type)
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return queryset

    @extend_schema(tags=["Sectores"], summary="Consultar catálogos de sectores", responses={status.HTTP_200_OK: dict})
    @action(detail=False, methods=["get"], url_path="options")
    def options_catalog(self, request):
        return Response({"sector_types": self._choices(Sector.Type.choices)})

    @staticmethod
    def _choices(choices):
        return [{"value": value, "label": label} for value, label in choices]


@extend_schema_view(
    list=extend_schema(tags=["Unidades"], summary="Listar unidades"),
    retrieve=extend_schema(tags=["Unidades"], summary="Consultar unidad"),
    create=extend_schema(tags=["Unidades"], summary="Registrar unidad"),
    update=extend_schema(tags=["Unidades"], summary="Reemplazar unidad"),
    partial_update=extend_schema(tags=["Unidades"], summary="Editar unidad"),
    destroy=extend_schema(tags=["Unidades"], summary="Eliminar unidad"),
)
@method_decorator(never_cache, name="dispatch")
class UnitViewSet(viewsets.ModelViewSet):
    """T013: CRUD de unidades habitacionales."""

    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated, CanManageUnits]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("code", "unit_type", "status")
    ordering = ("code",)

    def get_queryset(self):
        queryset = Unit.objects.select_related("sector")
        sector_id = self.request.query_params.get("sector", "").strip()
        unit_type = self.request.query_params.get("unit_type", "").strip().upper()
        unit_status = self.request.query_params.get("status", "").strip().upper()
        search = self.request.query_params.get("search", "").strip()

        if sector_id:
            queryset = queryset.filter(sector_id=sector_id)
        if unit_type:
            queryset = queryset.filter(unit_type=unit_type)
        if unit_status:
            queryset = queryset.filter(status=unit_status)
        if search:
            queryset = queryset.filter(Q(code__icontains=search))
        return queryset

    @extend_schema(tags=["Unidades"], summary="Consultar catálogos de unidades", responses={status.HTTP_200_OK: dict})
    @action(detail=False, methods=["get"], url_path="options")
    def options_catalog(self, request):
        return Response({
            "unit_types": self._choices(Unit.Type.choices),
            "statuses": self._choices(Unit.Status.choices),
        })

    @staticmethod
    def _choices(choices):
        return [{"value": value, "label": label} for value, label in choices]
