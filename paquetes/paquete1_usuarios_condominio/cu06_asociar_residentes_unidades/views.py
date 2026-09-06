from rest_framework import viewsets
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated
from condominiums.models import Resident
from paquetes.paquete1_usuarios_condominio.cu05_residentes.permissions import CanManageResidents
from condominiums.models import Resident, ResidentUnit
from paquetes.paquete1_usuarios_condominio.cu06_asociar_residentes_unidades.serializers import ResidentDirectorySerializer
from paquetes.paquete1_usuarios_condominio.cu06_asociar_residentes_unidades.serializers import ResidentUnitSerializer


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
