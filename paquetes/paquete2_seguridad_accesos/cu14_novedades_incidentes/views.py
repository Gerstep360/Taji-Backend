from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated

from auditlog.services import record_audit_event
from condominiums.models import Staff
from security.models import SecurityShift, ShiftLogEntry
from ..cu13_turnos_seguridad.permissions import is_admin_or_management, is_security_guard
from .serializers import ShiftLogQuerySerializer, ShiftLogSerializer


class CanAccessShiftLogs(BasePermission):
    message = "No tienes permiso para acceder a las novedades de turno."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if view.action == "create":
            # Administración consulta; el registro corresponde al guardia de servicio.
            return is_security_guard(user) and not is_admin_or_management(user)
        return is_admin_or_management(user) or is_security_guard(user)


@extend_schema_view(
    list=extend_schema(tags=["Seguridad - Novedades"], parameters=[ShiftLogQuerySerializer]),
    retrieve=extend_schema(tags=["Seguridad - Novedades"]),
    create=extend_schema(tags=["Seguridad - Novedades"], summary="Registrar novedad en el turno propio abierto"),
)
@method_decorator(never_cache, name="dispatch")
class ShiftLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = ShiftLogSerializer
    permission_classes = [IsAuthenticated, CanAccessShiftLogs]
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = ShiftLogEntry.objects.exclude(entry_type=ShiftLogEntry.Type.HANDOVER_NOTE).select_related(
            "shift__guard_staff__person", "shift__condominium", "created_by_user"
        ).order_by("-occurred_at", "-id")
        user = self.request.user
        if not is_admin_or_management(user):
            queryset = queryset.filter(shift__guard_staff__person_id=user.person_id)
        query = ShiftLogQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        mapping = {"shift": "shift_id", "guard": "shift__guard_staff_id",
                   "condominium": "shift__condominium_id", "entry_type": "entry_type",
                   "severity": "severity", "date_from": "occurred_at__date__gte",
                   "date_to": "occurred_at__date__lte"}
        for key, field in mapping.items():
            if key in values:
                queryset = queryset.filter(**{field: values[key]})
        if values.get("search"):
            queryset = queryset.filter(Q(title__icontains=values["search"]) | Q(description__icontains=values["search"]))
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        staff = Staff.objects.filter(person_id=user.person_id, staff_type=Staff.Type.SECURITY,
                                     status=Staff.Status.ACTIVE).first()
        if not staff:
            raise PermissionDenied("Debes estar registrado como personal de seguridad activo.")
        # El mismo bloqueo utilizado al cerrar CU13 evita registrar mientras se cierra el turno.
        shift = SecurityShift.objects.select_for_update().filter(
            guard_staff=staff, status=SecurityShift.Status.OPEN
        ).first()
        if not shift:
            raise ValidationError({"shift": "Debes iniciar tu turno antes de registrar novedades."})
        expected = serializer.validated_data.pop("expected_shift", None)
        if expected is not None and expected != shift.pk:
            raise ValidationError({"shift": "Tu turno cambió. Actualiza la pantalla antes de registrar."})
        now = timezone.now()
        entry = serializer.save(shift=shift, created_by_user=user, occurred_at=now, created_at=now)
        record_audit_event(
            action_code="SHIFT_LOG_CREATED", resource_type="ShiftLogEntry", resource_id=entry.pk,
            description=f"{entry.get_entry_type_display()} registrada en turno #{shift.pk}.",
            actor_user=user, request=self.request,
            after_data={"shift_id": shift.pk, "condominium_id": shift.condominium_id,
                        "entry_type": entry.entry_type, "severity": entry.severity, "title": entry.title},
        )
