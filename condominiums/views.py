from rest_framework import status, viewsets

from django.db.models import Q

from django.utils.decorators import method_decorator

from django.views.decorators.cache import never_cache

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view

from rest_framework import filters, mixins, status, viewsets

from rest_framework.decorators import action

from rest_framework.permissions import IsAuthenticated

from rest_framework.response import Response

from .models import Condominium

from .serializers import CondominiumSerializer

from accounts.models import Person

from .models import Resident, Staff

from .permissions import CanManageResidents, CanManageStaff

from .serializers import ResidentSerializer, StaffSerializer

from rest_framework import filters, status, viewsets

from .models import Resident, ResidentUnit, Sector, Staff, Unit

from .permissions import CanManageResidents, CanManageStaff, CanManageUnits

from .serializers import (
    ResidentDirectorySerializer,
    ResidentUnitSerializer,
    SectorSerializer,
    StaffSerializer,
    UnitSerializer,
)


class CondominiumViewSet(viewsets.ModelViewSet):
    queryset = Condominium.objects.all()
    serializer_class = CondominiumSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get", "put", "patch"], url_path="current")
    def current(self, request):
        condo = Condominium.objects.filter(is_active=True).first()
        
        if not condo and request.method == "GET":
            return Response(
                {"detail": "No hay ningún condominio configurado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            serializer = self.get_serializer(condo)
            return Response(serializer.data)

        if request.method in ["PUT", "PATCH"]:
            if not condo:
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            partial = request.method == "PATCH"
            serializer = self.get_serializer(condo, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        tags=["Personal"],
        summary="Listar personal",
        parameters=[
            OpenApiParameter("search", str, description="Nombre, documento, correo, teléfono o código."),
            OpenApiParameter("staff_type", str, description="Área del personal."),
            OpenApiParameter("status", str, description="Estado laboral."),
            OpenApiParameter("ordering", str, description="Campo de orden; anteponer - para descendente."),
        ],
    ),
    retrieve=extend_schema(tags=["Personal"], summary="Consultar personal"),
    create=extend_schema(tags=["Personal"], summary="Registrar personal"),
    update=extend_schema(tags=["Personal"], summary="Reemplazar personal"),
    partial_update=extend_schema(tags=["Personal"], summary="Editar personal"),
    destroy=extend_schema(
        tags=["Personal"],
        summary="Eliminar vínculo de personal",
        description="Elimina el registro Staff y conserva Person como fuente única de identidad.",
    ),
)
@method_decorator(never_cache, name="dispatch")
class StaffViewSet(viewsets.ModelViewSet):
    """T016: CRUD y clasificación del personal del condominio."""

    serializer_class = StaffSerializer
    permission_classes = [IsAuthenticated, CanManageStaff]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = (
        "employee_code",
        "staff_type",
        "status",
        "hire_date",
        "person__first_name",
        "person__last_name",
    )
    ordering = ("person__last_name", "person__first_name")
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = Staff.objects.select_related("person")
        staff_type = self.request.query_params.get("staff_type", "").strip().upper()
        staff_status = self.request.query_params.get("status", "").strip().upper()
        search = self.request.query_params.get("search", "").strip()

        if staff_type:
            queryset = queryset.filter(staff_type=staff_type)
        if staff_status:
            queryset = queryset.filter(status=staff_status)
        if search:
            queryset = queryset.filter(
                Q(employee_code__icontains=search)
                | Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(person__document_number__icontains=search)
                | Q(person__contact_email__icontains=search)
                | Q(person__phone__icontains=search)
            )
        return queryset

    @extend_schema(
        tags=["Personal"],
        summary="Consultar catálogos de personal",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options_catalog(self, request):
        return Response(
            {
                "staff_types": self._choices(Staff.Type.choices),
                "statuses": self._choices(Staff.Status.choices),
                "document_types": self._choices(Person.DocumentType.choices),
            }
        )

    @staticmethod
    def _choices(choices):
        return [{"value": value, "label": label} for value, label in choices]


@extend_schema_view(
    list=extend_schema(
        tags=["Residentes"],
        summary="Listar residentes y copropietarios",
        parameters=[
            OpenApiParameter("search", str, description="Nombre, documento, correo o teléfono."),
            OpenApiParameter("status", str, description="Estado del residente."),
            OpenApiParameter("ordering", str, description="Campo de orden; anteponer - para descendente."),
        ],
    ),
    retrieve=extend_schema(tags=["Residentes"], summary="Consultar residente"),
    create=extend_schema(tags=["Residentes"], summary="Registrar residente o copropietario"),
    update=extend_schema(tags=["Residentes"], summary="Reemplazar residente"),
    partial_update=extend_schema(tags=["Residentes"], summary="Editar residente"),
)
@method_decorator(never_cache, name="dispatch")
class ResidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """T014: CRUD de residentes y copropietarios (CU05).

    Sin destroy: la baja se maneja mediante el estado lógico existente
    (Resident.status/deactivated_at), no se elimina físicamente el registro.
    """

    serializer_class = ResidentSerializer
    permission_classes = [IsAuthenticated, CanManageResidents]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = (
        "status",
        "registered_at",
        "person__first_name",
        "person__last_name",
    )
    ordering = ("person__last_name", "person__first_name")
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = Resident.objects.select_related("person")
        resident_status = self.request.query_params.get("status", "").strip().upper()
        search = self.request.query_params.get("search", "").strip()

        if resident_status:
            queryset = queryset.filter(status=resident_status)
        if search:
            queryset = queryset.filter(
                Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(person__document_number__icontains=search)
                | Q(person__contact_email__icontains=search)
                | Q(person__phone__icontains=search)
            )
        return queryset

    @extend_schema(
        tags=["Residentes"],
        summary="Consultar catálogos de residentes",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options_catalog(self, request):
        return Response(
            {
                "statuses": self._choices(Resident.Status.choices),
                "document_types": self._choices(Person.DocumentType.choices),
            }
        )

    @staticmethod
    def _choices(choices):
        return [{"value": value, "label": label} for value, label in choices]


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


@method_decorator(never_cache, name="dispatch")
class ResidentDirectoryViewSet(viewsets.ReadOnlyModelViewSet):
    """T014 read model used by CU06 to select active residents."""

    serializer_class = ResidentDirectorySerializer
    permission_classes = [IsAuthenticated, CanManageResidents]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("person__first_name", "person__last_name", "registered_at")
    ordering = ("person__last_name", "person__first_name")

    def get_queryset(self):
        queryset = Resident.objects.select_related("person").filter(status=Resident.Status.ACTIVE)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(person__first_name__icontains=search)
                | Q(person__last_name__icontains=search)
                | Q(person__document_number__icontains=search)
            )
        return queryset


@method_decorator(never_cache, name="dispatch")
class ResidentUnitViewSet(viewsets.ModelViewSet):
    """T015: asociaciones históricas entre residentes y unidades."""

    serializer_class = ResidentUnitSerializer
    permission_classes = [IsAuthenticated, CanManageResidents]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("start_date", "end_date", "created_at")
    ordering = ("-start_date", "-created_at")

    def get_queryset(self):
        queryset = ResidentUnit.objects.select_related("resident__person", "unit")
        resident_id = self.request.query_params.get("resident", "").strip()
        unit_id = self.request.query_params.get("unit", "").strip()
        active = self.request.query_params.get("active", "").strip().lower()
        if resident_id:
            queryset = queryset.filter(resident_id=resident_id)
        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)
        if active == "true":
            queryset = queryset.filter(end_date__isnull=True)
        elif active == "false":
            queryset = queryset.filter(end_date__isnull=False)
        return queryset

