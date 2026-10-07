from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from auditlog.services import record_audit_event
from condominiums.models import Staff
from security.models import SecurityShift, ShiftHandover
from ..cu13_turnos_seguridad.permissions import is_admin_or_management, is_security_guard
from ..cu13_turnos_seguridad.serializers import SecurityShiftSerializer
from .serializers import CandidateQuerySerializer, DeliverySerializer, HandoverQuerySerializer, HandoverSerializer

RELAY_TOLERANCE = timedelta(minutes=15)


def relay_candidates(outgoing):
    if not outgoing.condominium_id:
        return SecurityShift.objects.none()
    return SecurityShift.objects.filter(
        condominium_id=outgoing.condominium_id, guard_staff__status=Staff.Status.ACTIVE,
        guard_staff__staff_type=Staff.Type.SECURITY,
        status__in=[SecurityShift.Status.SCHEDULED, SecurityShift.Status.OPEN],
        scheduled_start__gte=outgoing.scheduled_end - RELAY_TOLERANCE,
        scheduled_start__lte=outgoing.scheduled_end + RELAY_TOLERANCE,
    ).exclude(guard_staff_id=outgoing.guard_staff_id).filter(
        scheduled_start__gt=outgoing.scheduled_start
    ).filter(
        Q(status=SecurityShift.Status.OPEN) | Q(scheduled_end__gt=timezone.now())
    ).select_related("guard_staff__person", "condominium").order_by("scheduled_start", "id")


class CanAccessHandovers(BasePermission):
    message = "No tienes permiso para acceder a las entregas de turno."
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if view.action in ("create", "recibir", "candidatos"):
            return is_security_guard(user) and not is_admin_or_management(user)
        return is_admin_or_management(user) or is_security_guard(user)


@extend_schema_view(
    list=extend_schema(tags=["Seguridad - Entrega de turno"], parameters=[HandoverQuerySerializer]),
    retrieve=extend_schema(tags=["Seguridad - Entrega de turno"]),
    create=extend_schema(tags=["Seguridad - Entrega de turno"], request=DeliverySerializer, responses=HandoverSerializer),
)
@method_decorator(never_cache, name="dispatch")
class HandoverViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = HandoverSerializer
    permission_classes = [IsAuthenticated, CanAccessHandovers]
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        qs = ShiftHandover.objects.select_related(
            "outgoing_shift__guard_staff__person", "incoming_shift__guard_staff__person",
            "outgoing_shift__condominium", "incoming_shift__condominium",
        ).order_by("-delivered_at", "-id")

        from tenancy.context import TenantContext
        tenant = getattr(self.request, "tenant", None) or TenantContext.get_current_tenant()
        if tenant and not TenantContext.is_global():
            qs = qs.filter(
                Q(outgoing_shift__condominium=tenant) | Q(incoming_shift__condominium=tenant)
                | Q(outgoing_shift__guard_staff__condominium=tenant)
            )

        user = self.request.user
        if not is_admin_or_management(user):
            qs = qs.filter(Q(outgoing_shift__guard_staff__person_id=user.person_id) |
                           Q(incoming_shift__guard_staff__person_id=user.person_id))
        query = HandoverQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        for key, field in {"outgoing_shift": "outgoing_shift_id", "incoming_shift": "incoming_shift_id",
                           "status": "status", "condominium": "outgoing_shift__condominium_id",
                           "date_from": "delivered_at__date__gte", "date_to": "delivered_at__date__lte"}.items():
            if key in values:
                qs = qs.filter(**{field: values[key]})
        if "guard" in values:
            qs = qs.filter(Q(outgoing_shift__guard_staff_id=values["guard"]) | Q(incoming_shift__guard_staff_id=values["guard"]))
        return qs

    def active_staff(self):
        staff = Staff.objects.filter(person_id=self.request.user.person_id, staff_type=Staff.Type.SECURITY,
                                     status=Staff.Status.ACTIVE).first()
        if not staff:
            raise PermissionDenied("Debes ser personal de seguridad activo.")
        return staff

    @extend_schema(tags=["Seguridad - Entrega de turno"], parameters=[CandidateQuerySerializer])
    @action(detail=False, methods=["get"])
    def candidatos(self, request):
        query = CandidateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        staff = self.active_staff()
        outgoing = get_object_or_404(SecurityShift, pk=query.validated_data["outgoing_shift"], guard_staff=staff)
        if outgoing.status != SecurityShift.Status.OPEN:
            raise ValidationError({"outgoing_shift": "Debes tener el turno en curso para preparar una entrega."})
        if not outgoing.condominium_id:
            raise ValidationError({"outgoing_shift": "El administrador debe asignar un condominio al turno."})
        return Response(SecurityShiftSerializer(relay_candidates(outgoing), many=True).data)

    @transaction.atomic
    def create(self, request):
        data = DeliverySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        staff = self.active_staff()
        Staff.objects.select_for_update().get(pk=staff.pk)
        shifts = {s.pk: s for s in SecurityShift.objects.select_for_update().filter(
            pk__in=[values["outgoing_shift"], values["incoming_shift"]]
        ).order_by("pk")}
        outgoing = shifts.get(values["outgoing_shift"])
        incoming = shifts.get(values["incoming_shift"])
        if not outgoing or outgoing.guard_staff_id != staff.pk:
            raise PermissionDenied("Solo puedes entregar tu propio turno.")
        if outgoing.status != SecurityShift.Status.OPEN:
            raise ValidationError({"outgoing_shift": "Solo puedes entregar un turno en curso."})
        if ShiftHandover.objects.filter(outgoing_shift=outgoing).exists():
            raise ValidationError({"outgoing_shift": "Este turno ya tiene una entrega registrada."})
        if not incoming or not relay_candidates(outgoing).filter(pk=incoming.pk).exists():
            raise ValidationError({"incoming_shift": "Selecciona un relevo válido del mismo condominio dentro de la tolerancia de 15 minutos."})
        handover = ShiftHandover.objects.create(outgoing_shift=outgoing, incoming_shift=incoming,
            delivered_by_user=request.user, summary=values["summary"], delivered_at=timezone.now())
        self.audit(handover, "SHIFT_HANDOVER_DELIVERED")
        return Response(self.get_serializer(handover).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["Seguridad - Entrega de turno"], request=None, responses=HandoverSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def recibir(self, request, pk=None):
        visible = self.get_object()
        staff = self.active_staff()
        Staff.objects.select_for_update().get(pk=staff.pk)
        incoming = get_object_or_404(SecurityShift.objects.select_for_update(), pk=visible.incoming_shift_id)
        handover = ShiftHandover.objects.select_for_update().get(pk=visible.pk)
        if incoming.guard_staff_id != staff.pk:
            raise PermissionDenied("Solo el guardia destinatario puede confirmar la recepción.")
        if handover.status != ShiftHandover.Status.PENDING:
            raise ValidationError({"detail": "Esta entrega ya fue confirmada."})
        if incoming.status != SecurityShift.Status.OPEN:
            raise ValidationError({"incoming_shift": "Inicia tu turno antes de confirmar la recepción."})
        if not incoming.condominium_id or incoming.condominium_id != handover.outgoing_shift.condominium_id:
            raise ValidationError({"incoming_shift": "Los turnos deben pertenecer al mismo condominio."})
        if incoming.scheduled_start < handover.outgoing_shift.scheduled_end - RELAY_TOLERANCE or incoming.scheduled_start > handover.outgoing_shift.scheduled_end + RELAY_TOLERANCE:
            raise ValidationError({"incoming_shift": "El horario del relevo cambió. Consulta al administrador."})
        handover.status = ShiftHandover.Status.RECEIVED
        handover.received_by_user = request.user
        handover.received_at = max(timezone.now(), handover.delivered_at)
        handover.save(update_fields=["status", "received_by_user", "received_at"])
        self.audit(handover, "SHIFT_HANDOVER_RECEIVED")
        return Response(self.get_serializer(handover).data)

    def audit(self, handover, code):
        record_audit_event(action_code=code, resource_type="ShiftHandover", resource_id=handover.pk,
            actor_user=self.request.user, request=self.request, description=f"Entrega #{handover.pk}: {handover.get_status_display()}.",
            after_data={"outgoing_shift": handover.outgoing_shift_id, "incoming_shift": handover.incoming_shift_id,
                        "status": handover.status, "delivered_by_user": handover.delivered_by_user_id,
                        "received_by_user": handover.received_by_user_id})
