"""Vistas REST API para CU13: Gestionar turnos del personal de seguridad."""

from datetime import timedelta

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

from auditlog.services import record_audit_event
from condominiums.models import Staff
from security.models import SecurityShift
from .permissions import CanManageSecurityShifts, is_admin_or_management, is_security_guard
from .serializers import SecurityShiftSerializer, ShiftActionSerializer
from .timing import EARLY_START_MINUTES, closing_timing, start_block_reason


@extend_schema_view(
    list=extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Listar turnos de seguridad",
        description="El administrador ve todos los turnos del condominio. El guardia de seguridad ve únicamente sus turnos.",
        parameters=[
            OpenApiParameter("guard", int, description="ID del personal de seguridad (Staff ID)."),
            OpenApiParameter("status", str, description="Estado del turno (SCHEDULED, OPEN, CLOSED, CANCELLED)."),
            OpenApiParameter("date_from", str, description="Fecha desde (YYYY-MM-DD o ISO)."),
            OpenApiParameter("date_to", str, description="Fecha hasta (YYYY-MM-DD o ISO)."),
            OpenApiParameter("search", str, description="Búsqueda por nombre o código de empleado."),
        ],
    ),
    retrieve=extend_schema(tags=["Seguridad - Turnos"], summary="Consultar detalle de un turno"),
    create=extend_schema(tags=["Seguridad - Turnos"], summary="Programar un turno de seguridad"),
    update=extend_schema(tags=["Seguridad - Turnos"], summary="Reemplazar datos de un turno programado"),
    partial_update=extend_schema(tags=["Seguridad - Turnos"], summary="Editar datos de un turno programado"),
    destroy=extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Cancelar o eliminar turno",
        description="Cancela un turno programado conservando la trazabilidad.",
    ),
)
@method_decorator(never_cache, name="dispatch")
class SecurityShiftViewSet(viewsets.ModelViewSet):
    """
    Controlador principal para CU13 / RF-13:
    - Ciclo de vida del turno: Programar -> Iniciar (Abrir) -> Cerrar (Finalizar) / Cancelar.
    - Reglas de negocio: no solapamiento, validación del área SEGURIDAD, transiciones estrictas de estado.
    - Registro de auditoría en todas las operaciones sensibles.
    """

    serializer_class = SecurityShiftSerializer
    permission_classes = [IsAuthenticated, CanManageSecurityShifts]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ("scheduled_start", "scheduled_end", "created_at", "status")
    ordering = ("-scheduled_start",)
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        user = self.request.user
        queryset = SecurityShift.objects.select_related(
            "guard_staff__person",
            "condominium",
            "created_by_user",
        )

        is_admin = is_admin_or_management(user)

        if not is_admin:
            # Guardia de seguridad: aislar únicamente sus propios turnos
            person = getattr(user, "person", None)
            if not person:
                return queryset.none()
            guard_staff = Staff.objects.filter(person=person, staff_type=Staff.Type.SECURITY).first()
            if not guard_staff:
                return queryset.none()
            queryset = queryset.filter(guard_staff=guard_staff)
        else:
            # Administración / Directiva: aplicar filtros opcionales
            guard_id = self.request.query_params.get("guard", "").strip() or self.request.query_params.get("guard_staff", "").strip()
            status_param = self.request.query_params.get("status", "").strip().upper()
            date_from = self.request.query_params.get("date_from", "").strip()
            date_to = self.request.query_params.get("date_to", "").strip()
            condo_id = self.request.query_params.get("condominium", "").strip()
            search = self.request.query_params.get("search", "").strip()

            if guard_id:
                queryset = queryset.filter(guard_staff_id=guard_id)
            if status_param:
                queryset = queryset.filter(status=status_param)
            if date_from:
                queryset = queryset.filter(scheduled_start__date__gte=date_from)
            if date_to:
                queryset = queryset.filter(scheduled_start__date__lte=date_to)
            if condo_id:
                queryset = queryset.filter(condominium_id=condo_id)
            if search:
                queryset = queryset.filter(
                    Q(guard_staff__person__first_name__icontains=search)
                    | Q(guard_staff__person__last_name__icontains=search)
                    | Q(guard_staff__employee_code__icontains=search)
                )

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        if not is_admin_or_management(user):
            raise PermissionDenied("Solo el administrador puede programar turnos de seguridad.")

        shift = serializer.save(created_by_user=user)
        record_audit_event(
            action_code="SECURITY_SHIFT_CREATED",
            resource_type="SecurityShift",
            resource_id=shift.id,
            description=(
                f"Turno programado para {shift.guard_staff.person.full_name} "
                f"({shift.scheduled_start.strftime('%Y-%m-%d %H:%M')} a {shift.scheduled_end.strftime('%H:%M')})."
            ),
            actor_user=user,
            after_data={
                "shift_id": shift.id,
                "guard_staff_id": shift.guard_staff_id,
                "scheduled_start": shift.scheduled_start.isoformat(),
                "scheduled_end": shift.scheduled_end.isoformat(),
                "status": shift.status,
            },
            request=self.request,
        )

    def perform_update(self, serializer):
        user = self.request.user
        if not is_admin_or_management(user):
            raise PermissionDenied("Solo el administrador puede modificar turnos programados.")

        instance = serializer.instance
        if instance.status != SecurityShift.Status.SCHEDULED:
            raise ValidationError(
                {"detail": f"Solo se pueden modificar turnos en estado PROGRAMADO. El turno actual está en {instance.get_status_display()}."}
            )

        before_data = {
            "guard_staff_id": instance.guard_staff_id,
            "scheduled_start": instance.scheduled_start.isoformat(),
            "scheduled_end": instance.scheduled_end.isoformat(),
            "status": instance.status,
        }

        shift = serializer.save()

        record_audit_event(
            action_code="SECURITY_SHIFT_UPDATED",
            resource_type="SecurityShift",
            resource_id=shift.id,
            description=f"Turno de seguridad #{shift.id} actualizado por la administración.",
            actor_user=user,
            before_data=before_data,
            after_data={
                "guard_staff_id": shift.guard_staff_id,
                "scheduled_start": shift.scheduled_start.isoformat(),
                "scheduled_end": shift.scheduled_end.isoformat(),
                "status": shift.status,
            },
            request=self.request,
        )

    def destroy(self, request, *args, **kwargs):
        """En lugar de eliminación física destructiva, cancela el turno conservando la trazabilidad."""
        instance = self.get_object()
        user = request.user
        if not is_admin_or_management(user):
            raise PermissionDenied("Solo el administrador puede cancelar o eliminar turnos.")

        if instance.status == SecurityShift.Status.CANCELLED:
            return Response({"detail": "El turno ya se encuentra cancelado."}, status=status.HTTP_200_OK)

        if instance.status in (SecurityShift.Status.OPEN, SecurityShift.Status.CLOSED):
            raise ValidationError(
                {"detail": f"No se puede eliminar o cancelar un turno que está en estado {instance.get_status_display()}."}
            )

        with transaction.atomic():
            before_status = instance.status
            instance.status = SecurityShift.Status.CANCELLED
            instance.save(update_fields=["status", "updated_at"])

            record_audit_event(
                action_code="SECURITY_SHIFT_CANCELLED",
                resource_type="SecurityShift",
                resource_id=instance.id,
                description=f"Turno de seguridad #{instance.id} cancelado.",
                actor_user=user,
                before_data={"status": before_status},
                after_data={"status": instance.status},
                request=request,
            )

        return Response(self.get_serializer(instance).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Iniciar turno de seguridad",
        description="Permite al guardia asignado iniciar su turno programado, registrando fecha/hora real de apertura y cambiando el estado a EN_CURSO (OPEN).",
        request=ShiftActionSerializer,
        responses={status.HTTP_200_OK: SecurityShiftSerializer},
    )
    @action(detail=True, methods=["post"], url_path="iniciar")
    def iniciar(self, request, pk=None):
        shift = self.get_object()
        user = request.user

        # Regla 16: El guardia solo puede operar sobre sus propios turnos
        person = getattr(user, "person", None)
        if not is_admin_or_management(user):
            if not person or shift.guard_staff.person != person:
                raise PermissionDenied("Solo el guardia de seguridad asignado puede iniciar este turno.")

        # Regla 8, 9, 10: Validar estado actual
        if shift.status == SecurityShift.Status.CANCELLED:
            raise ValidationError({"detail": "No se puede iniciar un turno que ha sido CANCELADO."})
        if shift.status == SecurityShift.Status.CLOSED:
            raise ValidationError({"detail": "No se puede iniciar un turno que ya ha sido FINALIZADO."})
        if shift.status == SecurityShift.Status.OPEN:
            raise ValidationError({"detail": "El turno ya se encuentra EN_CURSO (iniciado)."})
        if shift.status != SecurityShift.Status.SCHEDULED:
            raise ValidationError({"detail": f"No se puede iniciar un turno en estado {shift.get_status_display()}."})

        action_data = ShiftActionSerializer(data={
            "notes": request.data.get("notes") or request.data.get("opening_notes", "")
        })
        action_data.is_valid(raise_exception=True)
        notes = action_data.validated_data["notes"]

        with transaction.atomic():
            # Serializar las operaciones de apertura del mismo guardia.
            Staff.objects.select_for_update().get(pk=shift.guard_staff_id)
            shift = SecurityShift.objects.select_for_update().get(pk=shift.pk)
            now = timezone.now()
            other_id = SecurityShift.objects.filter(
                guard_staff_id=shift.guard_staff_id, status=SecurityShift.Status.OPEN
            ).exclude(pk=shift.pk).values_list("id", flat=True).first()
            reason = start_block_reason(shift, now, other_id)
            if reason:
                raise ValidationError({"detail": reason})
            before_status = shift.status
            shift.status = SecurityShift.Status.OPEN
            shift.opened_at = now
            if notes:
                shift.opening_notes = notes
            shift.save(update_fields=["status", "opened_at", "opening_notes", "updated_at"])

            record_audit_event(
                action_code="SECURITY_SHIFT_STARTED",
                resource_type="SecurityShift",
                resource_id=shift.id,
                description=f"Turno #{shift.id} iniciado por el guardia {shift.guard_staff.person.full_name}.",
                actor_user=user,
                before_data={"status": before_status},
                after_data={"status": shift.status, "opened_at": shift.opened_at.isoformat()},
                request=request,
            )

        serializer = self.get_serializer(shift)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Cerrar turno de seguridad",
        description="Permite al guardia asignado cerrar su turno activo, registrando fecha/hora real de cierre y cambiando el estado a FINALIZADO (CLOSED).",
        request=ShiftActionSerializer,
        responses={status.HTTP_200_OK: SecurityShiftSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cerrar")
    def cerrar(self, request, pk=None):
        shift = self.get_object()
        user = request.user

        # Regla 16: El guardia solo puede operar sobre sus propios turnos
        person = getattr(user, "person", None)
        if not is_admin_or_management(user):
            if not person or shift.guard_staff.person != person:
                raise PermissionDenied("Solo el guardia de seguridad asignado puede cerrar este turno.")

        # Regla 13: No permitir cerrar un turno que no esté EN_CURSO
        if shift.status != SecurityShift.Status.OPEN:
            raise ValidationError({"detail": "Solo se puede cerrar un turno que esté EN_CURSO (iniciado)."})

        action_data = ShiftActionSerializer(data={
            "notes": request.data.get("notes") or request.data.get("closing_notes", "")
        })
        action_data.is_valid(raise_exception=True)
        notes = action_data.validated_data["notes"]

        with transaction.atomic():
            Staff.objects.select_for_update().get(pk=shift.guard_staff_id)
            shift = SecurityShift.objects.select_for_update().get(pk=shift.pk)
            if shift.status != SecurityShift.Status.OPEN:
                raise ValidationError({"detail": "Solo se puede cerrar un turno que esté EN_CURSO (iniciado)."})
            now = timezone.now()
            close_type = closing_timing(shift, now)
            if close_type != "ON_TIME" and not notes:
                raise ValidationError({
                    "notes": "Debes indicar el motivo del cierre anticipado o posterior al horario programado."
                })
            before_status = shift.status
            shift.status = SecurityShift.Status.CLOSED
            shift.closed_at = now
            if notes:
                shift.closing_notes = notes
            shift.save(update_fields=["status", "closed_at", "closing_notes", "updated_at"])

            record_audit_event(
                action_code="SECURITY_SHIFT_CLOSED",
                resource_type="SecurityShift",
                resource_id=shift.id,
                description=f"Turno #{shift.id} cerrado por el guardia {shift.guard_staff.person.full_name}.",
                actor_user=user,
                before_data={"status": before_status},
                after_data={
                    "status": shift.status,
                    "closed_at": shift.closed_at.isoformat(),
                    "closing_timing": close_type,
                    "closing_notes": notes,
                },
                request=request,
            )

        serializer = self.get_serializer(shift)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Cancelar turno de seguridad",
        description="Permite al administrador cancelar un turno programado conservando la trazabilidad del registro.",
        request=ShiftActionSerializer,
        responses={status.HTTP_200_OK: SecurityShiftSerializer},
    )
    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        shift = self.get_object()
        user = request.user

        if not is_admin_or_management(user):
            raise PermissionDenied("Solo el administrador puede cancelar turnos.")

        if shift.status == SecurityShift.Status.CANCELLED:
            raise ValidationError({"detail": "El turno ya se encuentra cancelado."})

        if shift.status == SecurityShift.Status.CLOSED:
            raise ValidationError({"detail": "No se puede cancelar un turno que ya ha sido FINALIZADO."})
        if shift.status == SecurityShift.Status.OPEN:
            raise ValidationError({"detail": "Un turno en curso debe cerrarse; no puede cancelarse."})

        with transaction.atomic():
            before_status = shift.status
            shift.status = SecurityShift.Status.CANCELLED
            shift.save(update_fields=["status", "updated_at"])

            record_audit_event(
                action_code="SECURITY_SHIFT_CANCELLED",
                resource_type="SecurityShift",
                resource_id=shift.id,
                description=f"Turno de seguridad #{shift.id} cancelado.",
                actor_user=user,
                before_data={"status": before_status},
                after_data={"status": shift.status},
                request=request,
            )

        serializer = self.get_serializer(shift)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Consultar turno actual",
        description="Retorna el turno en curso (EN_CURSO) o programado vigente para el guardia autenticado.",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="actual")
    def actual(self, request):
        user = request.user
        person = getattr(user, "person", None)

        if is_admin_or_management(user):
            # Para administrador: se puede filtrar por ?guard_id=
            guard_id = request.query_params.get("guard", "").strip() or request.query_params.get("guard_staff", "").strip()
            if guard_id:
                active_shift = SecurityShift.objects.filter(
                    guard_staff_id=guard_id, status=SecurityShift.Status.OPEN
                ).first()
                if not active_shift:
                    active_shift = SecurityShift.objects.filter(
                        guard_staff_id=guard_id,
                        status=SecurityShift.Status.SCHEDULED,
                        scheduled_start__lte=timezone.now(),
                        scheduled_end__gte=timezone.now(),
                    ).first()
            else:
                active_shift = SecurityShift.objects.filter(status=SecurityShift.Status.OPEN).first()

            if not active_shift:
                return Response({"shift": None, "message": "No hay ningún turno activo en este momento."}, status=status.HTTP_200_OK)
            return Response(self.get_serializer(active_shift).data, status=status.HTTP_200_OK)

        # Para Guardia de seguridad:
        if not person:
            return Response({"shift": None, "message": "El usuario no tiene una persona asociada."}, status=status.HTTP_200_OK)

        guard_staff = Staff.objects.filter(person=person, staff_type=Staff.Type.SECURITY).first()
        if not guard_staff:
            return Response({"shift": None, "message": "El usuario no está registrado como personal de seguridad."}, status=status.HTTP_200_OK)

        # 1. Buscar turno EN_CURSO
        active_shift = SecurityShift.objects.filter(
            guard_staff=guard_staff, status=SecurityShift.Status.OPEN
        ).first()

        # 2. Turno vigente o dentro de la tolerancia de apertura, incluso si cruza medianoche.
        if not active_shift:
            now = timezone.now()
            active_shift = SecurityShift.objects.filter(
                guard_staff=guard_staff,
                status=SecurityShift.Status.SCHEDULED,
                scheduled_start__lte=now + timedelta(minutes=EARLY_START_MINUTES),
                scheduled_end__gt=now,
            ).order_by("scheduled_start").first()

        # 3. Si tampoco hay dentro del rango exacto, tomar el más cercano próximo programado para hoy
        if not active_shift:
            active_shift = SecurityShift.objects.filter(
                guard_staff=guard_staff,
                status=SecurityShift.Status.SCHEDULED,
                scheduled_start__date=timezone.localdate(),
                scheduled_end__gt=timezone.now(),
            ).order_by("scheduled_start").first()

        # 4. Mostrar el último turno de hoy sin iniciar si no hay uno vigente o próximo.
        if not active_shift:
            active_shift = SecurityShift.objects.filter(
                guard_staff=guard_staff,
                status=SecurityShift.Status.SCHEDULED,
                scheduled_end__date=timezone.localdate(),
                scheduled_end__lte=timezone.now(),
            ).order_by("-scheduled_end").first()

        if not active_shift:
            return Response({"shift": None, "message": "No tienes turnos activos ni asignados para hoy."}, status=status.HTTP_200_OK)

        return Response(self.get_serializer(active_shift).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Consultar próximos turnos",
        description="Lista los turnos futuros programados. Guardia ve los propios; Administrador ve los de todo el personal.",
        responses={status.HTTP_200_OK: SecurityShiftSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="proximos")
    def proximos(self, request):
        user = request.user
        now = timezone.now()
        queryset = SecurityShift.objects.filter(
            status=SecurityShift.Status.SCHEDULED,
            scheduled_start__gte=now,
        ).order_by("scheduled_start")

        if not is_admin_or_management(user):
            person = getattr(user, "person", None)
            if not person:
                return Response([], status=status.HTTP_200_OK)
            guard_staff = Staff.objects.filter(person=person, staff_type=Staff.Type.SECURITY).first()
            if not guard_staff:
                return Response([], status=status.HTTP_200_OK)
            queryset = queryset.filter(guard_staff=guard_staff)
        else:
            guard_id = request.query_params.get("guard", "").strip() or request.query_params.get("guard_staff", "").strip()
            if guard_id:
                queryset = queryset.filter(guard_staff_id=guard_id)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Consultar historial de turnos",
        description="Lista turnos finalizados, cancelados y turnos cuyo horario terminó sin iniciar.",
        parameters=[
            OpenApiParameter("guard", int, description="ID del guardia (Staff ID)."),
            OpenApiParameter("status", str, description="CLOSED o CANCELLED."),
            OpenApiParameter("date_from", str, description="Fecha desde (YYYY-MM-DD)."),
            OpenApiParameter("date_to", str, description="Fecha hasta (YYYY-MM-DD)."),
        ],
        responses={status.HTTP_200_OK: SecurityShiftSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="historial")
    def historial(self, request):
        user = request.user
        queryset = SecurityShift.objects.filter(
            Q(status__in=[SecurityShift.Status.CLOSED, SecurityShift.Status.CANCELLED])
            | Q(status=SecurityShift.Status.SCHEDULED, scheduled_end__lte=timezone.now())
        ).order_by("-scheduled_start")

        if not is_admin_or_management(user):
            person = getattr(user, "person", None)
            if not person:
                return Response([], status=status.HTTP_200_OK)
            guard_staff = Staff.objects.filter(person=person, staff_type=Staff.Type.SECURITY).first()
            if not guard_staff:
                return Response([], status=status.HTTP_200_OK)
            queryset = queryset.filter(guard_staff=guard_staff)
        else:
            guard_id = request.query_params.get("guard", "").strip() or request.query_params.get("guard_staff", "").strip()
            status_param = request.query_params.get("status", "").strip().upper()
            date_from = request.query_params.get("date_from", "").strip()
            date_to = request.query_params.get("date_to", "").strip()

            if guard_id:
                queryset = queryset.filter(guard_staff_id=guard_id)
            if status_param:
                queryset = queryset.filter(status=status_param)
            if date_from:
                queryset = queryset.filter(scheduled_start__date__gte=date_from)
            if date_to:
                queryset = queryset.filter(scheduled_start__date__lte=date_to)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Seguridad - Turnos"],
        summary="Consultar opciones y catálogos de turnos",
        responses={status.HTTP_200_OK: dict},
    )
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        return Response(
            {
                "statuses": [
                    {"value": code, "label": label}
                    for code, label in SecurityShift.Status.choices
                ],
            },
            status=status.HTTP_200_OK,
        )
