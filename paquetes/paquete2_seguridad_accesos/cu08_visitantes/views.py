"""Vistas para CU08: Registrar y autorizar visitantes."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Person
from auditlog.services import record_audit_event
from security.models import VisitAuthorization
from .permissions import CanRegisterOrManageVisits
from .serializers import VisitAuthorizationSerializer


@extend_schema_view(
    list=extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Listar autorizaciones de visita",
        description=(
            "Los residentes solo ven sus propias autorizaciones creadas. "
            "Los administradores tienen visibilidad global y filtros por residente, unidad, estado y rango de fechas."
        ),
        parameters=[
            OpenApiParameter("search", str, description="Nombre o documento del visitante, o código de unidad."),
            OpenApiParameter("status", str, description="Estado de la autorización (AUTHORIZED, ACTIVE, FINISHED, CANCELLED, EXPIRED)."),
            OpenApiParameter("resident", int, description="ID del residente autorizante (solo administración)."),
            OpenApiParameter("unit", int, description="ID de la unidad de destino."),
            OpenApiParameter("date_from", str, description="Fecha inicio filtro vigencia (YYYY-MM-DD o ISO)."),
            OpenApiParameter("date_to", str, description="Fecha fin filtro vigencia (YYYY-MM-DD o ISO)."),
            OpenApiParameter("ordering", str, description="Campo de ordenación (valid_from, valid_until, created_at)."),
        ],
    ),
    retrieve=extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Consultar detalle de autorización",
        description="Consulta la información completa de una autorización de visita, incluyendo visitante, residente y unidad.",
    ),
    create=extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Registrar y autorizar visita",
        description=(
            "Permite a un residente (o administrador) registrar una autorización anticipada indicando "
            "visitante, unidad, motivo y periodo de validez. Garantiza consistencia transaccional y "
            "asociación atómica a Person y Unit."
        ),
    ),
    partial_update=extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Actualizar autorización",
        description="Actualiza motivo, periodo de validez o notas de la autorización.",
    ),
    destroy=extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Eliminar autorización",
        description="Elimina el registro de autorización si no tiene eventos de acceso asociados.",
    ),
)
@method_decorator(never_cache, name="dispatch")
class VisitAuthorizationViewSet(viewsets.ModelViewSet):
    """
    Controlador para CU08 / T020:
    - Registro anticipado de visitas con consistencia transaccional.
    - Consulta aislada para residentes y global para administración.
    - Cancelación segura de visitas.
    - Registro de auditoría en todas las operaciones.
    """

    serializer_class = VisitAuthorizationSerializer
    permission_classes = [IsAuthenticated, CanRegisterOrManageVisits]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("valid_from", "valid_until", "created_at", "status")
    ordering = ("-created_at",)
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = VisitAuthorization.objects.select_related(
            "visitor_person",
            "authorized_by_resident__person",
            "unit__sector",
            "created_by_user",
        )

        user = self.request.user
        is_admin = bool(user and user.has_system_permission("manage_visits"))

        # Actualizar automáticamente visitas vencidas en estado AUTHORIZED
        now = timezone.now()
        VisitAuthorization.objects.filter(
            status=VisitAuthorization.Status.AUTHORIZED, valid_until__lt=now
        ).update(status=VisitAuthorization.Status.EXPIRED)

        if not is_admin:
            # Residente: limitar a visitas autorizadas por su perfil
            resident = getattr(getattr(user, "person", None), "resident", None)
            if resident:
                queryset = queryset.filter(authorized_by_resident=resident)
            else:
                return queryset.none()
        else:
            # Administración: aplicar filtros opcionales
            resident_id = self.request.query_params.get("resident", "").strip()
            unit_id = self.request.query_params.get("unit", "").strip()
            status_param = self.request.query_params.get("status", "").strip().upper()
            date_from = self.request.query_params.get("date_from", "").strip()
            date_to = self.request.query_params.get("date_to", "").strip()
            search = self.request.query_params.get("search", "").strip()

            if resident_id:
                queryset = queryset.filter(authorized_by_resident_id=resident_id)
            if unit_id:
                queryset = queryset.filter(unit_id=unit_id)
            if status_param:
                queryset = queryset.filter(status=status_param)
            if date_from:
                queryset = queryset.filter(valid_until__gte=date_from)
            if date_to:
                queryset = queryset.filter(valid_from__lte=date_to)
            if search:
                queryset = queryset.filter(
                    Q(visitor_person__first_name__icontains=search)
                    | Q(visitor_person__last_name__icontains=search)
                    | Q(visitor_person__document_number__icontains=search)
                    | Q(unit__code__icontains=search)
                    | Q(purpose__icontains=search)
                )

        return queryset

    def perform_create(self, serializer):
        authorization = serializer.save()
        record_audit_event(
            action_code="VISIT_AUTHORIZATION_CREATED",
            resource_type="VisitAuthorization",
            resource_id=authorization.id,
            description=(
                f"Autorización de visita registrada para {authorization.visitor_person.full_name} "
                f"en la unidad {authorization.unit.code}."
            ),
            actor_user=self.request.user,
            after_data={
                "authorization_id": authorization.id,
                "visitor_id": authorization.visitor_person_id,
                "visitor_name": authorization.visitor_person.full_name,
                "unit_id": authorization.unit_id,
                "unit_code": authorization.unit.code,
                "valid_from": authorization.valid_from.isoformat(),
                "valid_until": authorization.valid_until.isoformat(),
                "status": authorization.status,
            },
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.instance
        user = self.request.user
        is_admin = bool(user and user.has_system_permission("manage_visits"))

        # Si es residente, verificar que sea el dueño de la autorización
        if not is_admin:
            resident = getattr(getattr(user, "person", None), "resident", None)
            if instance.authorized_by_resident != resident:
                raise PermissionDenied("No tienes permiso para modificar esta autorización.")

        before_data = {
            "purpose": instance.purpose,
            "valid_from": instance.valid_from.isoformat(),
            "valid_until": instance.valid_until.isoformat(),
            "notes": instance.notes,
        }
        authorization = serializer.save()
        record_audit_event(
            action_code="VISIT_AUTHORIZATION_UPDATED",
            resource_type="VisitAuthorization",
            resource_id=authorization.id,
            description=f"Autorización de visita {authorization.id} actualizada.",
            actor_user=self.request.user,
            before_data=before_data,
            after_data={
                "purpose": authorization.purpose,
                "valid_from": authorization.valid_from.isoformat(),
                "valid_until": authorization.valid_until.isoformat(),
                "notes": authorization.notes,
            },
            request=self.request,
        )

    @extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Cancelar autorización de visita",
        description="Cancela una autorización anticipada que esté en estado pendiente o autorizada.",
        responses={status.HTTP_200_OK: VisitAuthorizationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        authorization = self.get_object()
        user = request.user
        is_admin = bool(user and user.has_system_permission("manage_visits"))

        # Validar pertenencia
        if not is_admin:
            resident = getattr(getattr(user, "person", None), "resident", None)
            if authorization.authorized_by_resident != resident:
                raise PermissionDenied("No tienes permiso para cancelar esta autorización.")

        if authorization.status == VisitAuthorization.Status.CANCELLED:
            raise ValidationError({"detail": "La autorización ya se encuentra cancelada."})

        if authorization.status in (
            VisitAuthorization.Status.FINISHED,
            VisitAuthorization.Status.EXPIRED,
        ):
            raise ValidationError(
                {"detail": f"No se puede cancelar una autorización en estado {authorization.get_status_display()}."}
            )

        with transaction.atomic():
            before_status = authorization.status
            authorization.status = VisitAuthorization.Status.CANCELLED
            authorization.cancelled_at = timezone.now()
            authorization.save(update_fields=["status", "cancelled_at"])

            record_audit_event(
                action_code="VISIT_AUTHORIZATION_CANCELLED",
                resource_type="VisitAuthorization",
                resource_id=authorization.id,
                description=f"Autorización de visita {authorization.id} cancelada.",
                actor_user=user,
                before_data={"status": before_status},
                after_data={"status": authorization.status, "cancelled_at": authorization.cancelled_at.isoformat()},
                request=request,
            )

        serializer = self.get_serializer(authorization)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Visitas"],
        summary="Consultar opciones y catálogos de visitas",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        return Response(
            {
                "statuses": [
                    {"value": code, "label": label}
                    for code, label in VisitAuthorization.Status.choices
                ],
                "document_types": [
                    {"value": code, "label": label}
                    for code, label in Person.DocumentType.choices
                ],
            },
            status=status.HTTP_200_OK,
        )
