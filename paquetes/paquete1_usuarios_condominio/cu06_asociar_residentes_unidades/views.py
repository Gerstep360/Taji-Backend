from rest_framework import viewsets
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated
from condominiums.models import Resident, ResidentUnit
from auditlog.services import record_audit_event
from paquetes.paquete1_usuarios_condominio.cu05_residentes.permissions import CanManageResidents
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

    def perform_create(self, serializer):
        ru = serializer.save()
        record_audit_event(
            action_code="condominium.resident_unit.assigned",
            resource_type="ResidentUnit",
            resource_id=ru.id,
            description=f"Asociación de residente {ru.resident.person.full_name} a unidad {ru.unit.code} ({ru.relation_type}).",
            actor_user=self.request.user,
            after_data={"resident_id": ru.resident_id, "unit_id": ru.unit_id, "relation_type": ru.relation_type},
            request=self.request,
        )

    def perform_update(self, serializer):
        ru = serializer.save()
        record_audit_event(
            action_code="condominium.resident_unit.updated",
            resource_type="ResidentUnit",
            resource_id=ru.id,
            description=f"Actualización de asociación residente {ru.resident.person.full_name} y unidad {ru.unit.code}.",
            actor_user=self.request.user,
            after_data={"resident_id": ru.resident_id, "unit_id": ru.unit_id, "relation_type": ru.relation_type, "end_date": str(ru.end_date) if ru.end_date else None},
            request=self.request,
        )

    def perform_destroy(self, instance):
        r_name = instance.resident.person.full_name if instance.resident and instance.resident.person else ""
        u_code = instance.unit.code if instance.unit else ""
        record_audit_event(
            action_code="condominium.resident_unit.unassigned",
            resource_type="ResidentUnit",
            resource_id=instance.id,
            description=f"Desvinculación de residente {r_name} de unidad {u_code}.",
            actor_user=self.request.user,
            request=self.request,
        )
        super().perform_destroy(instance)
