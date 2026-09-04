from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Person

from .models import Resident, Staff
from .permissions import CanManageResidents, CanManageStaff
from .serializers import ResidentSerializer, StaffSerializer


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

